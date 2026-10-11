"""Judges the nemu64 averaged tests over the VI phases (phases.py; docs/design/green-plan.md
section 3, "nemu64 phase walk").

usage: python -m romgen.suites.nemu64.phase RESULTS_DIR [LAYOUT]
       python -m romgen.suites.nemu64.phase --self-test
LAYOUT is the harness the phase ROMs link (measure.LAYOUT_2026, the default, or LAYOUT_2022).
RESULTS_DIR holds phase-<K>/stdout.txt for every delay K. Writes RESULTS_DIR/measurements.tsv
(min, max, median and sum of each averaged value at each delay) and RESULTS_DIR/phase.tsv (one row
per value: each statistic's range over the delays, the phase mean, the ROM's bands and the verdict).

A value passes when the model's mean over the phases lies in the ROM's own average band, the
hardware mean +- the test's published epsilon, and the ROM's min, max and median checks hold at
every phase. No value passes because one phase passes.
"""
import re
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from ... import runtime as rt
from ...suite import Suite
from . import measure, phases, timing

AVG = re.compile(r"^avg (\d+) (\d+) (\d+) (\d+)$")
RECORD = re.compile(r"^@(\d+\.\d+) \d")
STATS = ("min", "max", "median", "sum")
RUNS = 1000


def averaged_values(layout=measure.LAYOUT_2026):
    """(index, test, value desc, {result slot: (lo, hi)}) in phase-ROM order, from the same
    builder the ROM's checks come from."""
    suite = Suite("phase", "Timing", "")
    timing.build_averaged(suite, layout)
    return [(f"{ti}.{vi}", t.name, v.full_desc or v.desc,
             {c.a: (c.b, c.c) for c in v.checks if c.op == rt.CHK_RANGE})
            for ti, t in enumerate(suite.tests) for vi, v in enumerate(t.values)]


def read_phase(stdout):
    """{index: (min, max, median, sum)}: each avg line belongs to the record that follows it."""
    out, pending = {}, None
    for line in stdout.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := AVG.match(line):
            pending = tuple(int(x) for x in m.groups())
        elif (m := RECORD.match(line)) and pending:
            out[m.group(1)] = pending
            pending = None
    return out


def span(values, fmt=str):
    lo, hi = fmt(min(values)), fmt(max(values))
    return lo if lo == hi else f"{lo}..{hi}"


def per_run(total):
    return f"{total / RUNS:.3f}"


def judge(bands, runs):
    """The failed parts of one value over its phase runs, empty when it passes."""
    failed = [name for slot, name in enumerate(STATS[:3])
              if not all(bands[slot][0] <= r[slot] <= bands[slot][1] for r in runs)]
    mean_sum = Fraction(sum(r[3] for r in runs), len(runs))
    if not bands[3][0] <= mean_sum <= bands[3][1]:
        failed.append("mean")
    return failed, mean_sum


def self_test():
    bands = {0: (41, 103), 1: (41, 103), 2: (40, 42), 3: (42000, 43000)}
    cases = [
        ("every phase in band", [(41, 90, 41, 42500)] * 4, []),
        ("one phase in band, the phase mean out", [(41, 90, 41, 42500)] + [(41, 90, 41, 41000)] * 3, ["mean"]),
        ("no phase in band, the phase mean in", [(41, 90, 41, 41900), (41, 90, 41, 43100)], []),
        ("the median out at one phase", [(41, 90, 41, 42500), (41, 90, 43, 42500)], ["median"]),
        ("the max out at one phase", [(41, 104, 41, 42500), (41, 90, 41, 42500)], ["max"]),
    ]
    bad = [f"{name}: failed {judge(bands, runs)[0]}, expected {want}" for name, runs, want in cases
           if judge(bands, runs)[0] != want]
    tmp = Path(tempfile.mkdtemp())
    (tmp / "stdout.txt").write_text("@0.0 0\navg 41 90 41 42500\n\n@0.1 1\n@0.2 0\n", encoding="utf-8")
    if read_phase(tmp / "stdout.txt") != {"0.1": (41, 90, 41, 42500)}:
        bad.append(f"an avg line pairs with the record after it: got {read_phase(tmp / 'stdout.txt')}")
    if len(averaged_values()) != 21 or any(sorted(b) != [0, 1, 2, 3] for *_, b in averaged_values()):
        bad.append("the phase ROM holds the 21 averaged values, each with min, max, median and sum bands")
    sums = {layout: {i: b[3] for i, _, _, b in averaged_values(layout)}
            for layout in (measure.LAYOUT_2026, measure.LAYOUT_2022)}
    moved = {i for i in sums[measure.LAYOUT_2026] if sums[measure.LAYOUT_2026][i] != sums[measure.LAYOUT_2022][i]}
    if moved != {"2.0"} or not sums[measure.LAYOUT_2022]["2.0"][0] <= 40700 <= sums[measure.LAYOUT_2022]["2.0"][1]:
        bad.append(f"the 2022 layout differs from 2026 only in the same-bank mean 40.7: values {sorted(moved)} differ")
    for line in bad:
        print(f"phase self-test FAIL: {line}")
    print(f"phase self-test: {len(cases) + 3 - len(bad)} of {len(cases) + 3} pass")
    return 1 if bad else 0


def main():
    if sys.argv[1] == "--self-test":
        sys.exit(self_test())
    results = Path(sys.argv[1])
    layout = sys.argv[2] if len(sys.argv) > 2 else measure.LAYOUT_2026
    runs = {k: read_phase(results / f"phase-{k}" / "stdout.txt") for k in phases.DELAYS}
    with open(results / "measurements.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("delay\tindex\t" + "\t".join(STATS) + "\n")
        for k, by_index in runs.items():
            for index, r in sorted(by_index.items()):
                f.write(f"{k}\t{index}\t" + "\t".join(map(str, r)) + "\n")
    rows = []
    for index, test, value, bands in averaged_values(layout):
        got = [runs[k][index] for k in phases.DELAYS if index in runs[k]]
        missing = len(phases.DELAYS) - len(got)
        if missing:
            rows.append([index, test, value, str(len(got))] + ["-"] * 8 + ["missing", f"{missing} phases have no result"])
            continue
        failed, mean_sum = judge(bands, got)
        rows.append([index, test, value, str(len(got)),
                     span([r[0] for r in got]), span([r[1] for r in got]), span([r[2] for r in got]),
                     span([r[3] for r in got], per_run), f"{float(mean_sum / RUNS):.4f}",
                     f"{bands[0][0]}..{bands[0][1]}", f"{bands[2][0]}..{bands[2][1]}",
                     f"{per_run(bands[3][0])}..{per_run(bands[3][1])}",
                     "fail" if failed else "pass", ",".join(failed) or "-"])
    header = ["index", "test", "value", "phases", "min", "max", "median", "mean", "phase_mean",
              "band_minmax", "band_median", "band_mean", "result", "failed"]
    with open(results / "phase.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    for row in rows:
        print(f"{row[1]}{row[2]}: phase mean {row[8]} (band {row[11]}), mean {row[7]}, median {row[6]} "
              f"over {row[3]} phases: {row[12]}" + (f" ({row[13]})" if row[13] != "-" else ""))
    print(f"averaged values: {len(rows)}, failing: {sum(1 for r in rows if r[12] != 'pass')}")


if __name__ == "__main__":
    main()
