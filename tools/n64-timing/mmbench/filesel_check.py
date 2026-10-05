#!/usr/bin/env python3
"""Evaluates the MM file-select acceptance check (docs/research/mm-filesel-slowdown.md, wScottSh/ares#11)
against one mmbench result directory.

The model passes when both primary rows pass: the empty-file main screen at 1 field per game frame
and the two-named-file main screen at 2. The Options and rotation rows are secondary: they are
reported but do not decide the exit code.
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path


def read_tsv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def idle(row, n_fields, share_min=None, mean_min=None, mean_max=None):
    gframes = int(row["gframes"])
    mean = float(row["fields_per_gframe_mean"])
    share = int(row[f"dist_{n_fields}"]) / gframes if gframes else 0.0
    ok = gframes > 0
    if mean_min is not None:
        ok &= mean >= mean_min
    if mean_max is not None:
        ok &= mean <= mean_max
    if share_min is not None:
        ok &= share >= share_min
    return ok, f"mean {mean:.4f}, {share:.1%} of {gframes} game frames at {n_fields} field(s)"


def longest_run_of_ones(lengths):
    best = run = 0
    for length in lengths:
        run = run + 1 if length == 1 else 0
        best = max(best, run)
    return best


def rotations(rows):
    by_rotation = defaultdict(list)
    for r in rows:
        by_rotation[int(r["rotation"])].append(int(r["fields"]))
    results = []
    for n, lengths in sorted(by_rotation.items()):
        mean = sum(lengths) / len(lengths)
        run = longest_run_of_ones(lengths)
        results.append((1.0 <= mean <= 1.6 and run >= 4,
                        f"rotation {n}: fields {','.join(map(str, lengths))}, mean {mean:.3f}, "
                        f"longest 1-field run {run}"))
    return results


# (row, primary, scene, evaluate(summary row) -> (ok, measured)), in the order of the doc's table.
ROWS = [
    ("empty files, main idle: mean <= 1.05, >= 95% at 1 field", True, "filesel",
     lambda r: idle(r, 1, share_min=0.95, mean_max=1.05)),
    ("Options idle: mean <= 1.05", False, "filesel-options",
     lambda r: idle(r, 1, mean_max=1.05)),
    ("two named files, main idle: mean 1.90-2.10, >= 90% at 2 fields", True, "filesel-named",
     lambda r: idle(r, 2, share_min=0.90, mean_min=1.90, mean_max=2.10)),
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("results", type=Path, help="an mmbench --out directory (or its run1)")
    args = p.parse_args()

    summary = {r["scene"]: r for r in read_tsv(args.results / "summary.tsv")}
    verdicts = []
    for name, primary, scene, evaluate in ROWS:
        if scene not in summary:
            verdicts.append((name, primary, None, f"scene {scene} not in this run"))
            continue
        ok, measured = evaluate(summary[scene])
        verdicts.append((name, primary, ok, measured))

    name = "Main to Options rotation, empty files: 1.0-1.6 per rotation, >= 4 consecutive 1-field frames"
    rotation_file = args.results / "rotations.tsv"
    if rotation_file.is_file():
        per_rotation = rotations(read_tsv(rotation_file))
        verdicts.append((name, False, all(ok for ok, _ in per_rotation) and bool(per_rotation),
                         "; ".join(measured for _, measured in per_rotation)))
    else:
        verdicts.append((name, False, None, "scene filesel-rotate not in this run"))

    for name, primary, ok, measured in verdicts:
        verdict = "MISSING" if ok is None else "PASS" if ok else "FAIL"
        print(f"{verdict:7}  {'primary' if primary else 'secondary':9}  {name}\n{'':18}{measured}")
    primaries = [ok for _, primary, ok, _ in verdicts if primary]
    passed = all(ok is True for ok in primaries)
    print(f"acceptance: {'PASS' if passed else 'FAIL'} (primary rows: empty-file and two-named-file main idle)")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
