#!/usr/bin/env python3
"""Rebases the N64 core from 187.5 MHz scheduler ticks to 750 MHz Timing::Clock units (plan T4).

usage: clock-rebase.py [--root DIR]           rewrite, then regenerate the behavior header and spec
       clock-rebase.py --check [--root DIR]   rewrite nothing; print each line a rule would change and
                                              each tick-era idiom no rule covers; exit 1 if there are any

A tick was 1/187.5 MHz: 2 per PClock, 3 per RCP clock. A unit is 1/750 MHz, so every
rewrite multiplies a time by exactly 4 and the core's behavior does not change. The
rules cover what is mechanical: `step(n * 2)` becomes `step(pclk(n))`, RCP `n * 3`
becomes `rclk(n)`, device loops run to the CPU's absolute time instead of to 0, clock
differences divide by Timing::UnitsPerRclk, and wall-time literals become
Timing::us/ms/seconds. The hand-written half of T4 (Timing::Clock, Thread, the CPU's
synchronize, the RSP pipeline and DMA types, VI and AI on VclkAccumulator) is not here.

The same rules rewrite the `line` column of tools/n64-timing/literal-allowlist.tsv, so
the literal lint keeps matching. Rows that T4 retires are deleted from
ares/n64/timing/behaviors.tsv and from the allowlist; rows whose literal changed unit get
their new value. Then behaviors.py --fix-lines and behaviors.py regenerate.

Every rule matches only tick-era text, so a second run changes nothing. Run it again
after merging a branch that predates T4: it converts that branch's sites, and --check
lists the ones it cannot.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCAN_ROOT = "ares/n64"
ALLOWLIST = "tools/n64-timing/literal-allowlist.tsv"
TABLE = "ares/n64/timing/behaviors.tsv"
SKIP = ("ares/n64/timing/behaviors.hpp", "ares/n64/timing/clock.hpp", "ares/n64/vulkan/parallel-rdp/")

#(file regex, pattern, replacement); applied in order to every line of every matching file.
RULES = [
    #CPU costs: n PClocks were n * 2 ticks.
    (r"", r"\bstep\(\((\d+) - 1\) \* 2\)", r"step(pclk(\1 - 1))"),
    (r"pi/bus\.hpp$", r"thread\.step\(writeForceFinish\(\) \* 2\);",
     r"{ auto remaining = writeForceFinish(); thread.step(remaining + remaining); }"),
    (r"", r"\bstep\((\w+) \* 2\)", r"step(pclk(\1))"),
    (r"cpu/cpu\.cpp$", r"countClock \+= clocks << 1;", r"countClock += pclk(clocks);"),
    (r"cpu/cpu\.cpp$", r"\(93750000\*2\)/60/240", r"Clock{Timing::UnitsPerSecond / 60 / 240}"),

    #RCP costs: n RCP clocks were n * 3 ticks.
    (r"si/io\.cpp$", r"queueInsert\((Queue::\w+), (\w+)\s*\*\s*3\)", r"queueInsert(\1, rclk(\2))"),
    (r"rsp/dma\.cpp$", r"dmaQueue\(\(dma\.current\.length\+8\) / 8 \* 3,", r"dmaQueue(rclk((dma.current.length+8) / 8),"),
    (r"pi/dma\.cpp$", r"return cycles \* 3;", r"return rclk(cycles);"),
    (r"pi/(dma\.cpp|pi\.hpp)$", r"dmaDuration\(bool read\) -> u32", r"dmaDuration(bool read) -> Clock"),
    (r"rsp/rsp\.hpp$", r"clocks \+= 3;", r"clocks += Timing::Behavior::RspSlot;"),
    (r"rsp/(debugger|emux)\.cpp$", r"clocksTotal / 3\b", r"clocksTotal / Timing::UnitsPerRclk"),
    (r"rdp/io\.cpp$", r"\(Thread::clock - thread\.clock\) / 3", r"(Thread::clock - thread.clock).units / Timing::UnitsPerRclk"),

    #Raw tick counts.
    (r"pi/bus\.hpp$", r"queueInsert\(Queue::PI_BUS_Write, 400\)", r"queueInsert(Queue::PI_BUS_Write, pclk(200))"),
    (r"pi/(bus|pi)\.hpp$", r"writeForceFinish\(\) -> u32", r"writeForceFinish() -> Clock"),
    (r"pi/bus\.hpp$", r"return queue\.remove\(Queue::PI_BUS_Write\);", r"return {(s64)queue.remove(Queue::PI_BUS_Write)};"),
    (r"rsp/rsp\.cpp$", r"\bstep\(128\);", r"step(pclk(64));"),
    (r"rsp/rsp\.cpp$", r"(profile\.(?:cycles|haltedCycles)) \+= 128;", r"\1 += pclk(64).units;"),
    (r"pif/hle\.cpp$", r"constexpr u32 clocks = 10240 \* 8;", r"constexpr Clock clocks = pclk(10240 * 4);"),
    (r"pif/hle\.cpp$", r"intram\.bootTimeout -= clocks;", r"intram.bootTimeout -= clocks.units;"),
    (r"pif/hle\.cpp$", r"intram\.bootTimeout = 6 \* 187500000;", r"intram.bootTimeout = Timing::seconds(6).units;"),
    (r"pif/pif\.hpp$", r"\bs32 bootTimeout;", r"s64 bootTimeout;"),
    (r"rdp/rdp\.cpp$", r"const u32 clocks = system\.frequency\(\);", r"constexpr Clock quantum = Timing::seconds(1);"),
    (r"rdp/rdp\.cpp$", r"\bstep\(clocks\);", r"step(quantum);"),
    (r"rdp/rdp\.cpp$", r"command\.clock \+= clocks / 3;", r"command.clock += quantum.units / Timing::UnitsPerRclk;"),

    #Wall time.
    (r"cartridge/joybus\.cpp$", r"187'500 \* 6\)", r"Timing::ms(6))"),
    (r"cartridge/rtc\.cpp$", r"queueInsert\(Queue::RTC_Tick, 187'500'000\)", r"queueInsert(Queue::RTC_Tick, Timing::seconds(1))"),
    (r"cartridge/flash\.cpp$", r"^static constexpr u32 FlashMs = 187'500;\n?", r""),
    (r"cartridge/flash\.cpp$", r"\((\d+) \* FlashMs\) / 1000", r"Timing::us(\1)"),
    (r"cartridge/flash\.cpp$", r"\b(\d+) \* FlashMs\b", r"Timing::ms(\1)"),
    (r"cartridge/flash\.cpp$", r"\bu32 duration = model->", r"Clock duration = model->"),
    (r"cartridge/cartridge\.hpp$", r"\bu32 (sectorEraseClocks|chipEraseClocks|programClocks);", r"Clock \1;"),

    #64DD delays are counts of 187.5 MHz ticks (DD::ticks).
    (r"dd/.*\.cpp$", r"queueInsert\((Queue::DD_\w+), (?!ticks\()(.*)\);", r"queueInsert(\1, ticks(\2));"),

    #Device loops run until they reach the CPU's absolute time.
    (r"", r"while\(Thread::clock < 0\)", r"while(Thread::clock < cpu.clock)"),
]

#Tick-era idioms. A hit that no rule rewrites needs a hand conversion.
LEGACY = [
    (r"\bstep\([^;]*\*\s*2\s*\)", "a step() charged in ticks (n * 2); use pclk(n)"),
    (r"(queueInsert|dmaQueue)\([^;]*\*\s*3\b", "an RCP time in ticks (n * 3); use rclk(n)"),
    (r"\breturn cycles \* 3;", "an RCP time in ticks (n * 3); use rclk(n)"),
    (r"Thread::clock\s*<\s*0\b", "a device loop that runs to 0; run to cpu.clock"),
    (r"clock\)?\s*/\s*3\b", "a tick difference divided by 3; divide .units by Timing::UnitsPerRclk"),
    (r"\b(187'?500|93'?750'?000)", "a 187.5 MHz or 93.75 MHz literal; use Timing::us/ms/seconds or pclk"),
    (r"system\.frequency\(\)", "the 187.5 MHz tick rate; use Timing::UnitsPerSecond"),
]

#Rows whose every code site the rules above remove.
RETIRED = {
    "legacy.clock.ticks-per-pclk", "legacy.clock.ticks-per-pclk-shift", "legacy.clock.ticks-per-rclk",
    "legacy.clock.ticks-per-ms", "legacy.clock.ticks-per-s", "legacy.rsp.issue", "legacy.rsp.stall",
}
#Rows whose literal the rules restate in another unit: id -> (value, unit).
RESTATED = {
    "legacy.pi.write-busy": ("200", "pclk"),
    "legacy.rsp.halted-quantum": ("64", "pclk"),
    "legacy.pif.step-quantum": ("40960", "pclk"),
    "legacy.cart.rtc-tick": ("1", "s"),
}
#Rows the rules need: (id, row text, id of the row to insert after).
ADDED = [
    ("rsp.slot", "rsp.slot\t1\trclk\twiki\tclocks.md: the RSP runs on the RCP clock (n64brew Clock_Timing; SDK pro-man ch.3 RCP 62.5 MHz); one pipeline slot, an issue or a bubble, per clock\tnemu64:rsp_timing/sll\tRSP::Pipeline charges it per issued pair and per stall bubble (ADR 0001 keeps the RSP pipeline as the RSP cost model)", "sp.dma-rate-check"),
    ("legacy.rdp.step-quantum", "legacy.rdp.step-quantum\t1\ts\tlegacy\tares/n64/rdp/rdp.cpp:30\tstepcap\treplaced by T5: the RDP steps as a timeline actor", "legacy.rsp.dma-bytes-per-rclk"),
]
#Allowlist entries for sites the rules create: (path, function, line, rows, note).
ADDED_SITES = [
    ("ares/n64/rdp/rdp.cpp", "main", "constexpr Clock quantum = Timing::seconds(1);", "legacy.rdp.step-quantum", ""),
]


def rules_for(rel):
    return [(re.compile(p, re.M), r) for f, p, r in RULES if re.search(f, rel)]


def rewrite(text, rules):
    for pattern, replacement in rules:
        text = pattern.sub(replacement, text)
    return text


def sources(root):
    for path in sorted((root / SCAN_ROOT).rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.suffix in (".cpp", ".hpp") and not rel.startswith(SKIP):
            yield path, rel


def read(path):
    return path.read_bytes().decode("utf-8")


def write(path, text):
    path.write_bytes(text.encode("utf-8"))


def converted(root):
    """Yields (path, rel, text, rewritten text, crlf) for every source file, line endings normalized."""
    for path, rel in sources(root):
        old = read(path)
        text = old.replace("\r\n", "\n")
        yield path, rel, text, rewrite(text, rules_for(rel)), "\r\n" in old


def legacy_sites(rel, text):
    hits = []
    for number, line in enumerate(text.split("\n"), 1):
        code = line.split("//")[0]
        if "ticks(" in code:
            continue
        for pattern, why in LEGACY:
            if re.search(pattern, code):
                hits.append(f"{rel}:{number}: {why}: {line.strip()}")
    return hits


def edit_tsv(path, edit):
    old = read(path)
    crlf = "\r\n" in old
    lines = old.replace("\r\n", "\n").split("\n")
    new = "\n".join(edit(lines))
    if new != "\n".join(lines):
        write(path, new.replace("\n", "\r\n") if crlf else new)
        return True
    return False


def rewrite_allowlist(lines):
    out = [lines[0]]
    present = set()
    for line in lines[1:]:
        if not line:
            out.append(line)
            continue
        rel, function, source, rows, note = line.split("\t")
        source = rewrite(source, rules_for(rel)).strip()
        kept = [r for r in rows.split() if r not in RETIRED]
        if not kept:
            continue
        present.add((rel, function, source))
        out.append("\t".join([rel, function, source, " ".join(kept), note]))
    for rel, function, source, rows, note in ADDED_SITES:
        if (rel, function, source) not in present:
            out.insert(len(out) - (1 if out[-1] == "" else 0), "\t".join([rel, function, source, rows, note]))
    return out


def rewrite_table(lines):
    out = []
    ids = {line.split("\t")[0] for line in lines}
    for line in lines:
        fields = line.split("\t")
        if fields[0] in RETIRED:
            continue
        if fields[0] in RESTATED:
            fields[1], fields[2] = RESTATED[fields[0]]
            line = "\t".join(fields)
        out.append(line)
        for rid, row, after in ADDED:
            if fields[0] == after and rid not in ids:
                out.append(row)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)

    changes, hits = [], []
    for path, rel, text, new, crlf in converted(root):
        if new != text:
            after = set(new.split("\n"))
            changes += [f"{rel}: {line.strip()}" for line in text.split("\n") if line not in after]
            if not args.check:
                write(path, new.replace("\n", "\r\n") if crlf else new)
        hits += legacy_sites(rel, new)
    if args.check:
        for line in changes:
            print(f"rewrite: {line}")
        for line in hits:
            print(f"by hand: {line}")
        print(f"clock-rebase: {len(changes)} line(s) to rewrite, {len(hits)} to convert by hand")
        return 1 if changes or hits else 0

    allowlist = edit_tsv(root / ALLOWLIST, rewrite_allowlist)
    table = edit_tsv(root / TABLE, rewrite_table)
    print(f"clock-rebase: rewrote {len(changes)} line(s); allowlist {'updated' if allowlist else 'unchanged'}; "
          f"table {'updated' if table else 'unchanged'}")
    behaviors = root / "tools/n64-timing/behaviors.py"
    subprocess.run([sys.executable, str(behaviors), "--root", str(root), "--fix-lines"], check=True)
    return subprocess.run([sys.executable, str(behaviors), "--root", str(root)]).returncode


if __name__ == "__main__":
    sys.exit(main())
