#!/usr/bin/env python3
"""Evaluates the MM file-select acceptance check (docs/research/mm-filesel-slowdown.md, wScottSh/ares#11)
against one mmbench result directory.

The model passes when both primary rows pass: the empty-file main screen at 1 field per game frame
and the two-named-file main screen at 2. The Options and rotation rows are secondary: they are
reported but do not decide the exit code.

An idle row is judged on the median of each quantity its criterion reads over mmbench's phase sweep
(docs/design/green-plan.md section 3, "MM file select"), and reports the minimum and maximum beside
it. A run without every phase of the sweep leaves the row missing.
"""

import argparse
import csv
import importlib.util
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_spec = importlib.util.spec_from_file_location("mmbench", Path(__file__).resolve().parent / "mmbench.py")
mmbench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mmbench)


def read_tsv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def spread(values, fmt):
    return f"{fmt(statistics.median(values))} (min {fmt(min(values))}, max {fmt(max(values))})"


def idle(rows, n_fields, share_min=None, mean_min=None, mean_max=None):
    """`rows` holds the scene's summary row at each phase of the sweep."""
    means = [float(r["fields_per_gframe_mean"]) for r in rows]
    shares = [int(r[f"dist_{n_fields}"]) / int(r["gframes"]) if int(r["gframes"]) else 0.0 for r in rows]
    mean, share = statistics.median(means), statistics.median(shares)
    ok = all(int(r["gframes"]) > 0 for r in rows)
    if mean_min is not None:
        ok &= mean >= mean_min
    if mean_max is not None:
        ok &= mean <= mean_max
    if share_min is not None:
        ok &= share >= share_min
    return ok, (f"median over {len(rows)} phases: mean {spread(means, lambda v: f'{v:.4f}')}, "
                f"{spread(shares, lambda v: f'{v:.1%}')} of game frames at {n_fields} field(s)")


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


def phase_rows(results, scene):
    """The scene's summary row at each phase of the sweep that this run holds, phase 0 first."""
    rows = []
    for k in range(mmbench.PHASES):
        path = mmbench.phase_dir(results, k) / "summary.tsv"
        row = next((r for r in read_tsv(path) if r["scene"] == scene), None) if path.is_file() else None
        if row:
            rows.append(row)
    return rows


def row_verdict(results, index):
    """ROWS[index] against an mmbench result directory: (ok, measured), ok None when the run lacks a phase."""
    _, _, scene, evaluate = ROWS[index]
    rows = phase_rows(results, scene)
    if len(rows) < mmbench.PHASES:
        return None, f"scene {scene} at {len(rows)} of the sweep's {mmbench.PHASES} phases in this run"
    return evaluate(rows)


def self_test():
    import tempfile

    def write_sweep(root, scene, per_phase):
        for k, (gframes, dist_1) in enumerate(per_phase):
            d = mmbench.phase_dir(root, k)
            d.mkdir(parents=True, exist_ok=True)
            mean = (dist_1 + 2 * (gframes - dist_1)) / gframes
            (d / "summary.tsv").write_text("scene\tgframes\tfields_per_gframe_mean\tdist_1\tdist_2\n"
                                           f"{scene}\t{gframes}\t{mean:.4f}\t{dist_1}\t{gframes - dist_1}\n")

    n = mmbench.PHASES
    cases = [
        ("phase 0 fails, the median passes", [(100, 90)] + [(100, 99)] * (n - 1), True),
        ("phase 0 passes, the median fails", [(100, 99)] + [(100, 90)] * (n - 1), False),
        ("one phase missing", [(100, 99)] * (n - 1), None),
    ]
    failed = 0
    for name, per_phase, want in cases:
        with tempfile.TemporaryDirectory() as tmp:
            write_sweep(Path(tmp), "filesel", per_phase)
            got = row_verdict(Path(tmp), 0)[0]
        failed += got != want
        print(f"filesel_check: self-test: {name}: {'ok' if got == want else f'FAILED (got {got}, want {want})'}")
    print(f"filesel_check: self-test: {len(cases)} cases, {failed} failed")
    sys.exit(1 if failed else 0)


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("results", type=Path, help="an mmbench --out directory (or its run1)")
    args = p.parse_args()

    verdicts = [(name, primary, *row_verdict(args.results, i)) for i, (name, primary, _, _) in enumerate(ROWS)]

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
