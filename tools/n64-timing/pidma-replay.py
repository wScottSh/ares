#!/usr/bin/env python3
"""Replays rasky/n64_pi_dma_test's hardware golden logs against an ARES_PILOG run.

The ROM (pi_dma_test.z64, prebuilt, no license, kept outside the repo) times each
cart-to-RDRAM DMA four times with COP0 COUNT, from just after its PI_WR_LEN store to
just after the PI_STATUS poll that sees the DMA done, and checks the mean against the
hardware min/max within 10%. It prints a measured value only when that check fails.

This script recovers every measurement from the run's PI log instead:
  ticks = floor((idle PI_STATUS read + READ) / 16) - floor((PI_WR_LEN write + WRITE) / 16)
in Clock units (16 per COUNT tick). READ and WRITE are the ROM's own code paths from
those PI events to its two COUNT reads; --calibrate finds the shifts that reproduce
every "Found:" value the ROM printed in the same run, or the least worst-case error
in ticks when none reproduces all of them. A run that prints SUCCESS prints no value;
then the shifts are those that keep every timed point inside the ROM's own band, which
leaves them far wider than one tick, so the every-offset verdict of --calibrated can
still fail a model that matches the hardware at its true shift.

Log record (data/pidma_ram<off>_rom0.log, 1040 B per size 1..383): 512 B buffer,
u16 min ticks, u16 max ticks, u32 post dram, u32 post cart, u32 post len (big
endian), 512 B buffer after an 8 B follow-up DMA.

--calibrated does both and scores at every best-fit offset; standing.sh runs it.

usage: pidma-replay.py PILOG LOGDIR [--stdout ROMSTDOUT] [--offset UNITS]
                       [--tolerance 0.03] [--sizes 8-382] [--calibrate | --calibrated]
       pidma-replay.py --self-test
"""
import argparse
import re
import struct
import sys
from pathlib import Path

RAM_BUFFER = 0x300780
UNITS_PER_TICK = 16
UNITS_PER_RCLK = 12


def golden(logdir):
    table = {}
    for off in range(0, 0x80, 2):
        data = Path(logdir, f"pidma_ram{off + 0x780:x}_rom0.log").read_bytes()
        for size in range(1, 384):
            rec = data[(size - 1) * 1040:size * 1040]
            lo, hi, dst, src, ln = struct.unpack(">HHIII", rec[512:528])
            table[off, size] = (lo, hi, dst, src, ln)
    return table


def measurements(pilog):
    """(off, size) -> [raw units] for the ROM's timed DMAs, in run order."""
    out = {}
    start = None
    cart = None
    with open(pilog) as f:
        for line in f:
            p = line.split()
            if p[0] == "L":
                start = None
                if p[1] != "W":
                    continue
                size, dram, pbus, at = int(p[2]), int(p[3], 16), int(p[4], 16), int(p[5])
                off = dram - RAM_BUFFER
                if not 0 <= off < 0x80 or off & 1:
                    continue
                if cart is None and off == 0 and size == 1:
                    cart = pbus
                if pbus != cart:
                    continue
                start = (off, size, at)
            elif p[0] == "S" and start is not None and int(p[1]) & 3 == 0:
                off, size, at = start
                out.setdefault((off, size), []).append((at, int(p[2])))
                start = None
    return out, cart


def found(stdout):
    """(off, size) -> mean ticks the ROM printed for its failing checks."""
    res = {}
    off = None
    lines = Path(stdout).read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"Offsets: RAM=0x([0-9a-f]+)", line)
        if m:
            off = int(m.group(1), 16) - 0x780
        m = re.match(r"ERROR on timing of DMA of size (\d+)", line)
        if m:
            res[off, int(m.group(1))] = int(lines[i + 1].split()[1])
    return res


def rom_mean(raws, offset):
    """The ROM's integer mean of COUNT deltas: the write and idle-read times shifted to its
    two COUNT reads by OFFSET = (read shift, write shift)."""
    ticks = [(s + offset[0]) // UNITS_PER_TICK - (w + offset[1]) // UNITS_PER_TICK for w, s in raws[:4]]
    return sum(ticks) // len(ticks)


def rom_band(lo, hi):
    """The ROM's own pass band in ticks, in its float32 arithmetic (pi_dma_test.c:211, tolerance 0.1f)."""
    f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]
    tol = f32(0.1)
    return f32(lo * f32(1 - tol)), f32(hi * f32(1 + tol))


READS = range(-UNITS_PER_TICK * 64, UNITS_PER_TICK * 64)


def first_read(raws, write, test):
    """The least read shift in READS whose mean satisfies TEST, which is monotone in the shift; len(READS) if none."""
    lo, hi = 0, len(READS)
    while lo < hi:
        mid = (lo + hi) // 2
        if test(rom_mean(raws, (READS[mid], write))):
            hi = mid
        else:
            lo = mid + 1
    return lo


def calibrate(meas, printed, gold):
    """The (read, write) shifts with the least error against what the ROM printed.

    With printed values, the error is the worst-case distance in ticks from them. When the ROM
    printed none (it reports SUCCESS), every point it timed passed its own band, so the error is
    the number of timed points outside that band."""
    if printed:
        error = {(read, write): max(abs(rom_mean(meas[k], (read, write)) - v) for k, v in printed.items())
                 for read in READS for write in range(UNITS_PER_TICK)}
    else:
        timed = [(meas[k], *rom_band(*gold[k][:2])) for k in meas if k in gold]
        error = {}
        for write in range(UNITS_PER_TICK):
            inside = [0] * (len(READS) + 1)
            for raws, lo, hi in timed:
                a = first_read(raws, write, lambda m: m >= lo)
                b = first_read(raws, write, lambda m: m > hi)
                if a < b:
                    inside[a] += 1
                    inside[b] -= 1
            count = 0
            for i, read in enumerate(READS):
                count += inside[i]
                error[read, write] = len(timed) - count
    best = min(error.values())
    return best, sorted(k for k, e in error.items() if e == best)


def score(gold, meas, offset, sizes, tolerance):
    """(fails, rows, scored points, worst deviation per size) at one offset."""
    lo_s, hi_s = sizes
    fails, rows = [], []
    for (off, size), (lo, hi, *_rest) in sorted(gold.items()):
        if (off, size) not in meas:
            fails.append((off, size, None, lo, hi))
            continue
        mean = rom_mean(meas[off, size], offset)
        rows.append((off, size, mean, lo, hi))
        if lo_s <= size <= hi_s and not (lo * (1 - tolerance) <= mean <= hi * (1 + tolerance)):
            fails.append((off, size, mean, lo, hi))
    worst = {}
    for off, size, mean, lo, hi in rows:
        if lo_s <= size <= hi_s:
            dev = (mean - lo) / lo if mean < lo else (mean - hi) / hi if mean > hi else 0.0
            worst[size] = max(worst.get(size, 0.0), dev, key=abs)
    return fails, rows, sum(1 for (o, s) in gold if lo_s <= s <= hi_s), worst


def bands(worst, sizes):
    lo_s, hi_s = sizes
    return " ".join(f"{b}-{b + 31}:{max((worst[s] for s in worst if b <= s < b + 32), key=abs, default=0):+.2%}"
                    for b in range(lo_s - lo_s % 32, hi_s + 1, 32))


def self_test():
    """calibrate() and score() on synthetic runs; prints one line per case."""
    raws = [(0, 160 * UNITS_PER_TICK)] * 4
    gold = {(0, 8): (160, 160)}
    every = {(r, w) for r in READS for w in range(UNITS_PER_TICK)}
    cases = []
    cases.append(("nothing measured or printed", calibrate({}, {}, {}), (0, sorted(every))))
    #160 ticks pass the ROM's band 144..176 for read shifts whose tick lands 144..176
    inside = sorted((r, w) for r, w in every if 144 <= 160 + r // UNITS_PER_TICK <= 176)
    cases.append(("a SUCCESS run (no printed values)", calibrate({(0, 8): raws}, {}, gold), (0, inside)))
    cases.append(("a SUCCESS run with a point outside the ROM band at every shift",
                  calibrate({(0, 8): raws, (0, 9): [(0, 0)] * 4}, {}, {**gold, (0, 9): (5000, 5000)})[0], 1))
    exact = sorted((r, w) for r, w in every if 160 + r // UNITS_PER_TICK == 162)
    cases.append(("a printed value", calibrate({(0, 8): raws}, {(0, 8): 162}, gold), (0, exact)))
    cases.append(("a model at the hardware value passes at its own offset",
                  len(score(gold, {(0, 8): raws}, (0, 0), (8, 8), 0.03)[0]), 0))
    failures = 0
    for name, got, want in cases:
        ok = got == want
        failures += not ok
        print(f"pidma-replay: self-test: {name}: {'ok' if ok else 'FAILED'}")
    print(f"pidma-replay: self-test: {len(cases)} cases, {failures} failed")
    return 1 if failures else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("pilog")
    ap.add_argument("logdir")
    ap.add_argument("--stdout")
    ap.add_argument("--offset", default="0,0", help="READ,WRITE shifts in units, from --calibrate")
    ap.add_argument("--tolerance", type=float, default=0.03)
    ap.add_argument("--sizes", default="8-382")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--calibrated", action="store_true",
                    help="calibrate from --stdout, score at every best-fit offset, and print one verdict line "
                         "that also carries the ROM's own self-check")
    ap.add_argument("--table")
    a = ap.parse_args()

    gold = golden(a.logdir)
    meas, cart = measurements(a.pilog)
    sizes = tuple(map(int, a.sizes.split("-")))
    print(f"cart address 0x{cart:08x}; {len(meas)} (offset, size) points measured")

    if a.calibrate or a.calibrated:
        printed = found(a.stdout)
        best, fits = calibrate(meas, printed, gold)
        print(f"printed values: {printed}")
        unit = "tick(s)" if printed else "point(s) outside the ROM's own band"
        print(f"best worst-case error {best} {unit}, {len(fits)} offsets (read, write), "
              f"read {min(f[0] for f in fits)}..{max(f[0] for f in fits)}: {fits}")
        if a.calibrate:
            return 0 if best == 0 else 1
        scored = [(len(score(gold, meas, f, sizes, a.tolerance)[0]), f) for f in fits]
        most, least = max(scored), min(scored)
        fails, _, n, worst = score(gold, meas, most[1], sizes, a.tolerance)
        m = re.search(r"^Test finished\n(?:(\d+) failures|SUCCESS)$", Path(a.stdout).read_text(errors="replace"), re.M)
        rom_failures = int(m.group(1) or 0) if m else None
        ok = most[0] == 0 and rom_failures == 0
        print(f"pidma: {'PASS' if ok else 'FAIL'}: replay sizes {sizes[0]}-{sizes[1]} "
              f"{n - most[0]}..{n - least[0]}/{n} within +-{a.tolerance:.0%} of hardware min..max over {len(fits)} "
              f"calibrated offsets (calibration error {best} {'tick' if printed else 'points outside the ROM band'}); worst offset {most[1]} by size band {bands(worst, sizes)}; "
              f"ROM self-check {'no verdict' if rom_failures is None else f'{rom_failures} failures'}")
        return 0 if ok else 1

    offset = tuple(map(int, a.offset.split(",")))
    fails, rows, n, worst = score(gold, meas, offset, sizes, a.tolerance)
    if a.table:
        with open(a.table, "w") as f:
            f.write("ram_offset\tsize\tticks\thw_min\thw_max\n")
            for r in rows:
                f.write("0x%x\t%d\t%d\t%d\t%d\n" % (r[0] + 0x780, *r[1:]))
    print(f"sizes {sizes[0]}-{sizes[1]}: {n - len(fails)}/{n} within +-{a.tolerance:.0%} of hardware min..max")
    print("worst deviation by size band: " + bands(worst, sizes))
    for f in fails[:40]:
        print("FAIL ram=0x%x size=%d ticks=%s hw=[%d..%d]" % (f[0] + 0x780, f[1], f[2], f[3], f[4]))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
