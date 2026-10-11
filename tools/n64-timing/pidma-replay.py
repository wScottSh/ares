#!/usr/bin/env python3
"""Replays rasky/n64_pi_dma_test's hardware golden logs against an ARES_PILOG run.

The ROM (pi_dma_test.z64, prebuilt, no license, kept outside the repo) times each
cart-to-RDRAM DMA with COP0 COUNT: t0 just after its PI_WR_LEN store, t1 just after the
PI_STATUS poll that sees the DMA done, interrupts disabled in between (pi_dma_test.c:31-60).
It averages 4 runs per point in a uint16_t, or 1 run once 8 points have failed its own 10%
band, and prints a measured value only for a point that fails that band.

The run's PI log carries every COUNT read ("C value at"), so this script recovers the ROM's
own measurement exactly: for each timed DMA start ("L W size dram cart at"), t0 is the last
COUNT read before the start and t1 the first one after it. The replay must agree with what the
ROM said in the same run: it reproduces every "Found:" value the ROM printed, and when the ROM
reports 0 failures, every replayed mean at sizes 1-383 lies inside the ROM's own band, since the
ROM printed nothing (pi_dma_test.c:211). A run that would pass the rule but whose replay
contradicts the ROM's silence reads UNCHECKED; a failing comparison reads FAIL either way.

Pass rule (green-plan.md section 3, pidma:logs): every point at sizes 8-382, except 305-352,
lies within the golden min..max +-3%, and the ROM's own self-check reports 0 failures.

Log record (data/pidma_ram<off>_rom0.log, 1040 B per size 1..383): 512 B buffer,
u16 min ticks, u16 max ticks, u32 post dram, u32 post cart, u32 post len (big
endian), 512 B buffer after an 8 B follow-up DMA.

usage: pidma-replay.py PILOG LOGDIR --stdout ROMSTDOUT [--table FILE]
       pidma-replay.py --self-test
"""
import argparse
import bisect
import re
import struct
import sys
from pathlib import Path

RAM_BUFFER = 0x300780
TOLERANCE = 0.03
SIZES = (8, 382)
EXCLUDED = (305, 352)
EXCLUDED_REASON = ("the golden logs come from the ROM's MODE_GENERATE build, whose cart buffer sits at another "
                   "PI page phase: this ROM's buffer starts 0xd0 into a 512 B page, so its DMAs cross a page from "
                   "305 B on, while hardware's jump falls at about 353 B (green-plan/pisi.md item 3, inferred)")


def f32(x):
    """x rounded to an IEEE single, as the ROM's float arithmetic rounds each step."""
    return struct.unpack("f", struct.pack("f", x))[0]


#TIMING_TEST_TOLERANCE 0.1f (pi_dma_test.c:14); the constants fold in float.
ROM_LOW, ROM_HIGH = f32(1 - f32(0.1)), f32(1 + f32(0.1))


def golden(logdir):
    table = {}
    for off in range(0, 0x80, 2):
        data = Path(logdir, f"pidma_ram{off + 0x780:x}_rom0.log").read_bytes()
        for size in range(1, 384):
            lo, hi = struct.unpack(">HH", data[(size - 1) * 1040 + 512:(size - 1) * 1040 + 516])
            table[off, size] = (lo, hi)
    return table


class MalformedLog(Exception):
    pass


def hex_field(v):
    return int(v, 16)


#Every record ARES_PILOG writes (cpu/interpreter-scc.cpp, pi/io.cpp) and its fields' types.
RECORDS = {"C": (int, int), "S": (int, int), "L R": (int, hex_field, hex_field, int), "L W": (int, hex_field, hex_field, int)}


def measurements(lines):
    """(off, size) -> [ticks per run] for the ROM's timed DMAs, in run order."""
    counts, starts = [], []
    for number, line in enumerate(lines, 1):
        p = line.split()
        kind = " ".join(p[:2]) if p[:1] == ["L"] else p[0] if p else ""
        if kind not in RECORDS:
            raise MalformedLog(f"PI log line {number} has the unknown record {kind!r}: {line.rstrip()!r}")
        fields = p[len(kind.split()):]
        try:
            if not line.endswith("\n") or len(fields) != len(RECORDS[kind]):
                raise ValueError
            values = [parse(v) for parse, v in zip(RECORDS[kind], fields)]
        except ValueError:
            raise MalformedLog(f"PI log line {number} is malformed: {line.rstrip()!r}") from None
        if kind == "C":
            count, at = values
            counts.append((at, count))
        elif kind == "L W":
            size, dram, pbus, at = values
            starts.append((at, size, dram, pbus))
    #the SysAD drain that starts a DMA and the CPU's COUNT reads log from different threads
    counts.sort()
    starts.sort()
    times = [at for at, _ in counts]
    cart = next((pbus for _, size, dram, pbus in starts if dram == RAM_BUFFER and size == 1), None)
    out = {}
    for at, size, dram, pbus in starts:
        off = dram - RAM_BUFFER
        if pbus != cart or not 0 <= off < 0x80 or off & 1:
            continue
        i = bisect.bisect_left(times, at)
        if i == 0 or i == len(times):
            continue
        out.setdefault((off, size), []).append((counts[i][1] - counts[i - 1][1]) & 0xffff)
    return out


def rom_mean(ticks):
    """The ROM's mean: a uint16_t sum divided by its run count."""
    return (sum(ticks) & 0xffff) // len(ticks)


def found(text):
    """(off, size) -> mean ticks the ROM printed for its failing checks."""
    res = {}
    off = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"Offsets: RAM=0x([0-9a-f]+)", line)
        if m:
            off = int(m.group(1), 16) - 0x780
        m = re.match(r"ERROR on timing of DMA of size (\d+)", line)
        if m:
            res[off, int(m.group(1))] = int(lines[i + 1].split()[1])
    return res


def rom_failures(text):
    m = re.search(r"^Test finished\n(?:(\d+) failures|SUCCESS)$", text, re.M)
    return int(m.group(1) or 0) if m else None


def rom_band(lo, hi):
    """The ROM's band for a point: exp_minticks*(1.0f-TOLERANCE) .. exp_maxticks*(1.0f+TOLERANCE), in float."""
    return f32(lo * ROM_LOW), f32(hi * ROM_HIGH)


def rom_silent(mean, lo, hi):
    """pi_dma_test.c:211 does not fire: avgticks, converted to float, is not outside the ROM's band."""
    low, high = rom_band(lo, hi)
    return mean is not None and not (mean < low or mean > high)


def deviation(mean, lo, hi):
    return (mean - lo) / lo if mean < lo else (mean - hi) / hi if mean > hi else 0.0


def within(mean, lo, hi):
    return mean is not None and lo * (1 - TOLERANCE) <= mean <= hi * (1 + TOLERANCE)


def bands(worst, sizes):
    lo_s, hi_s = sizes
    return " ".join(f"{b}-{b + 31}:{max((worst[s] for s in worst if b <= s < b + 32 and lo_s <= s <= hi_s), key=abs, default=0):+.2%}"
                    for b in range(lo_s - lo_s % 32, hi_s + 1, 32))


def verdict(gold, meas, printed, failures):
    means = {k: rom_mean(v) for k, v in meas.items()}
    wrong = {k: (v, means.get(k)) for k, v in printed.items() if means.get(k) != v}
    in_all = [k for k in gold if SIZES[0] <= k[1] <= SIZES[1]]
    in_rule = [k for k in in_all if not EXCLUDED[0] <= k[1] <= EXCLUDED[1]]
    ok_rule = sum(within(means.get(k), *gold[k]) for k in in_rule)
    ok_all = sum(within(means.get(k), *gold[k]) for k in in_all)
    worst = {}
    for k in in_all:
        if k in means:
            worst[k[1]] = max(worst.get(k[1], 0.0), deviation(means[k], *gold[k]), key=abs)
    loud = sorted(k for k in gold if not rom_silent(means.get(k), *gold[k])) if failures == 0 else []
    if wrong or failures != 0 or ok_rule != len(in_rule):
        word = "FAIL"
    else:
        word = "UNCHECKED" if loud else "PASS"
    if wrong:
        replay = ("replay INVALID, printed values not reproduced (point: printed, replayed) "
                  + ", ".join(f"(0x{o + 0x780:x},{s}): {p}, {r}" for (o, s), (p, r) in sorted(wrong.items())))
    elif printed:
        replay = f"replay reproduces {len(printed)}/{len(printed)} printed values"
    elif failures != 0:
        replay = "the ROM printed no measured value"
    elif loud:
        replay = (f"replay contradicts the ROM's silence at {len(loud)}/{len(gold)} points, outside the ROM's own "
                  f"float band min*0.9..max*1.1 (pi_dma_test.c:211) though it printed none (point: replayed, band) "
                  + ", ".join(f"(0x{o + 0x780:x},{s}): {means.get((o, s), 'missing')}, "
                              f"{rom_band(*gold[o, s])[0]:g}..{rom_band(*gold[o, s])[1]:g}" for o, s in loud[:8])
                  + (", ..." if len(loud) > 8 else ""))
    else:
        replay = (f"replay agrees with the ROM's silence: {len(gold)}/{len(gold)} points inside the ROM's own float "
                  f"band min*0.9..max*1.1 (pi_dma_test.c:211)")
    return word, (f"pidma: {word}: exact COUNT replay, {replay}; "
                  f"sizes {SIZES[0]}-{SIZES[1]} except {EXCLUDED[0]}-{EXCLUDED[1]} {ok_rule}/{len(in_rule)} within "
                  f"+-{TOLERANCE:.0%} of hardware min..max (all sizes {SIZES[0]}-{SIZES[1]}: {ok_all}/{len(in_all)}); "
                  f"ROM self-check {'no verdict' if failures is None else f'{failures} failures'}; "
                  f"worst by size band {bands(worst, (SIZES[0], EXCLUDED[0] - 1))} {bands(worst, (EXCLUDED[1] + 1, SIZES[1]))}; "
                  f"excluded {EXCLUDED[0]}-{EXCLUDED[1]}, report only because {EXCLUDED_REASON}: worst {bands(worst, EXCLUDED)}")


def self_test():
    """measurements() and verdict() on synthetic runs; prints one line per case."""
    def log(points, count=0):
        """A log with each (off, size, ticks) DMA started 52 units after its t0 and written before it."""
        lines, at = [], 1000
        for off, size, ticks in points:
            lines.append(f"L W {size} {RAM_BUFFER + off:06x} 10000000 {at + 52}\n")
            lines.append(f"C {count & 0xffffffff} {at}\n")
            lines.append(f"S 0 {at + 16 * ticks - 8}\n")
            lines.append(f"C {(count + ticks) & 0xffffffff} {at + 16 * ticks}\n")
            at += 16 * ticks + 400
            count += ticks + 25
        return lines

    def run(points, printed, failures):
        return verdict(gold, measurements(log(points)), printed, failures)[0]

    def malformed(lines):
        try:
            measurements(lines)
        except MalformedLog as e:
            return str(e)

    first = (0, 1, 120)
    gold = {(0, 1): (100, 130), (0, 8): (160, 160), (0, 320): (3000, 3000)}
    at_hw = [first] + [(0, 8, 160)] * 4 + [(0, 320, 3000)] * 4
    reproduced_outside_rule = {(0, 1): 120}
    cases = [
        ("ticks are the ROM's two COUNT reads around a DMA start logged before them",
         measurements(log([first, (0, 8, 163)])), {(0, 1): [120], (0, 8): [163]}),
        ("a COUNT wrap between t0 and t1", measurements(log([first, (0, 8, 163)], 2**32 - 195))[0, 8], [163]),
        ("a last line cut inside its time names its line", malformed(log([first])[:-1] + ["C 2325743572 373002"]),
         "PI log line 4 is malformed: 'C 2325743572 373002'"),
        ("a last line cut before its time names its line", malformed(log([first])[:-1] + ["C 23468\n"]),
         "PI log line 4 is malformed: 'C 23468'"),
        ("a short DMA start names its line", malformed(["L W 8 300780\n"]), "PI log line 1 is malformed: 'L W 8 300780'"),
        ("a record the PI log does not write names its line", malformed(log([first]) + ["X 1 2\n"]),
         "PI log line 5 has the unknown record 'X': 'X 1 2'"),
        ("a DMA start of an unknown direction names its line", malformed(["L Q 8 300780 10000000 5\n"]),
         "PI log line 1 has the unknown record 'L Q': 'L Q 8 300780 10000000 5'"),
        ("a PI_STATUS read without its time names its line", malformed(["S 0\n"]), "PI log line 1 is malformed: 'S 0'"),
        ("a cart-ward DMA start is read and not timed", measurements(log([first]) + ["L R 8 300780 10000000 9999\n"]),
         {(0, 1): [120]}),
        ("the ROM's uint16_t mean of 4 runs", rom_mean([160, 161, 161, 161]), 160),
        ("a model at the hardware value passes", run(at_hw, reproduced_outside_rule, 0), "PASS"),
        ("a point 4% over hardware fails", run([first] + [(0, 8, 167)] * 4 + [(0, 320, 3000)] * 4, reproduced_outside_rule, 0), "FAIL"),
        ("a point 3% over hardware passes", run([first] + [(0, 8, 164)] * 4 + [(0, 320, 3000)] * 4, reproduced_outside_rule, 0), "PASS"),
        ("an excluded size out of band does not fail",
         run([first] + [(0, 8, 160)] * 4 + [(0, 320, 3300)] * 4, reproduced_outside_rule, 0), "PASS"),
        ("a missing point fails", run([first] + [(0, 320, 3000)] * 4, reproduced_outside_rule, 0), "FAIL"),
        ("a ROM self-check failure fails", run(at_hw, {}, 1), "FAIL"),
        ("no ROM verdict fails", run(at_hw, {}, None), "FAIL"),
        ("a printed value the replay does not reproduce fails", run(at_hw, {(0, 8): 161}, 0), "FAIL"),
        ("a silent ROM whose band holds every replayed mean passes", run(at_hw, {}, 0), "PASS"),
        ("a point 4% over hardware fails though the ROM was silent",
         run([first] + [(0, 8, 167)] * 4 + [(0, 320, 3000)] * 4, {}, 0), "FAIL"),
        ("a passing run whose replay lies outside the silent ROM's band is unchecked",
         run([(0, 1, 144)] + at_hw[1:], {}, 0), "UNCHECKED"),
        ("a failing run whose replay lies outside the silent ROM's band still fails",
         run([(0, 1, 144)] + [(0, 8, 167)] * 4 + [(0, 320, 3000)] * 4, {}, 0), "FAIL"),
        ("a replayed mean at the ROM's float bound max*1.1 is inside", run([(0, 1, 143)] + at_hw[1:], {}, 0), "PASS"),
        ("an excluded point missing from the replay contradicts the silent ROM",
         run([first] + [(0, 8, 160)] * 4, {}, 0), "UNCHECKED"),
    ]
    failed = 0
    for name, got, want in cases:
        ok = got == want
        failed += not ok
        print(f"pidma-replay: self-test: {name}: {'ok' if ok else f'FAILED (got {got}, want {want})'}")
    print(f"pidma-replay: self-test: {len(cases)} cases, {failed} failed")
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("pilog")
    ap.add_argument("logdir")
    ap.add_argument("--stdout", required=True)
    ap.add_argument("--table", help="write one TSV line per timed point")
    a = ap.parse_args()

    gold = golden(a.logdir)
    try:
        with open(a.pilog) as f:
            meas = measurements(f)
    except MalformedLog as e:
        print(f"pidma-replay: {e}")
        return 2
    text = Path(a.stdout).read_text(errors="replace")
    printed = found(text)
    print(f"{len(meas)} (offset, size) points timed; printed values: {printed}")
    if a.table:
        with open(a.table, "w") as f:
            f.write("ram_offset\tsize\truns\tticks\thw_min\thw_max\tdev_pct\n")
            for (off, size), (lo, hi) in sorted(gold.items()):
                if (off, size) in meas:
                    m = rom_mean(meas[off, size])
                    f.write(f"0x{off + 0x780:x}\t{size}\t{len(meas[off, size])}\t{m}\t{lo}\t{hi}\t{deviation(m, lo, hi) * 100:+.2f}\n")
    word, line = verdict(gold, meas, printed, rom_failures(text))
    print(line)
    return 0 if word == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
