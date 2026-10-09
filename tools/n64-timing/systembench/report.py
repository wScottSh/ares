"""Joins n64-systembench's own ISViewer output, from the unpadded ROM and every boot-delay ROM, into one
verdict per benchmark under the ROM's own pass rule.

usage: report.py RESULTS_DIR          writes RESULTS_DIR/{measurements.tsv,results.tsv} and prints a summary
       report.py --self-test
RESULTS_DIR holds pristine/stdout.txt and boot-<K>/stdout.txt (run.sh).
"""
import re
import sys
from pathlib import Path

ROWS = Path(__file__).resolve().parent / "rows.tsv"
BLOCK = re.compile(r"^\*\*\* (.+) \[(\d+)\]\n"
                   r"Expected: +(-?\d+) (CPU|RCP) cycles.*\n"
                   r"Found: +(-?\d+) (?:CPU|RCP) cycles", re.M)
#main.c:17-18: MEASUREMENT_ERROR_CPU is 1 CPU cycle; MEASUREMENT_ERROR_RCP is 4 CPU cycles = 24 xcycles, which
#xcycle_to_cycletype truncates to 2 RCP cycles.
MEAS_ERROR = {"CPU": 1, "RCP": 2}


def passes(unit, expected, found):
    """main.c:664-669, the ROM's +/- 0% class: within the sampling error or under 0.2 %."""
    diff = abs(found - expected)
    return diff <= MEAS_ERROR[unit] or diff * 100.0 / expected < 0.2


def parse(text):
    """{(name, qty): (unit, expected, found)} from one run's stdout; None when the run did not finish."""
    if "Benchmarks done" not in text:
        return None
    return {(m[1], int(m[2])): (m[4], int(m[3]), int(m[5])) for m in BLOCK.finditer(text)}


def verdict(kind, oks):
    if kind != "check":
        return "report"
    return "pass" if all(oks) else "consistent-only" if any(oks) else "fail"


def read_rows():
    lines = ROWS.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l]


def boot_key(name):
    return (name != "pristine", int(name[5:]) if name.startswith("boot-") else 0)


def report(results):
    runs = {}
    for d in sorted((p for p in results.iterdir() if (p / "stdout.txt").exists()), key=lambda p: boot_key(p.name)):
        parsed = parse((d / "stdout.txt").read_text(encoding="utf-8", errors="replace"))
        if parsed is None:
            raise SystemExit(f"systembench: {d.name} did not print 'Benchmarks done'; see {d}/stderr.txt")
        runs[d.name] = parsed
    if "pristine" not in runs:
        raise SystemExit(f"systembench: no pristine/stdout.txt under {results}; run run.sh first")
    measurements = ["run\trow\tunit\texpected\tfound\tpass"]
    out = ["row\tname\tqty\tunit\texpected\tpristine\tmin\tmax\truns\truns_pass\tverdict\tkind\tport"]
    for r in read_rows():
        key = (r["name"], int(r["qty"]))
        got = {}
        for run, parsed in runs.items():
            if key not in parsed:
                raise SystemExit(f"systembench: {run} printed no '*** {key[0]} [{key[1]}]' block")
            unit, expected, found = parsed[key]
            got[run] = (unit, expected, found, passes(unit, expected, found))
            measurements.append(f"{run}\t{r['row']}\t{unit}\t{expected}\t{found}\t{int(got[run][3])}")
        unit, expected, pristine, _ = got["pristine"]
        found = [g[2] for g in got.values()]
        oks = [g[3] for g in got.values()]
        out.append("\t".join(str(x) for x in (r["row"], r["name"], r["qty"], unit, expected, pristine, min(found), max(found),
                                              len(oks), sum(oks), verdict(r["kind"], oks), r["kind"], r["port"])))
    (results / "measurements.tsv").write_text("\n".join(measurements) + "\n", encoding="utf-8")
    (results / "results.tsv").write_text("\n".join(out) + "\n", encoding="utf-8")
    return out


def self_test():
    cases = [
        (passes("CPU", 3, 4), True, "1 CPU cycle off is inside MEASUREMENT_ERROR_CPU"),
        (passes("CPU", 34, 36), False, "2 CPU cycles off at 34 is 5.9 %"),
        (passes("RCP", 193, 195), True, "2 RCP cycles off is inside MEASUREMENT_ERROR_RCP"),
        (passes("RCP", 193, 190), False, "3 RCP cycles off at 193 is 1.6 %"),
        (passes("RCP", 37987, 38062), True, "75 off at 37987 is 0.197 %"),
        (passes("RCP", 37987, 38063), False, "76 off at 37987 is 0.2001 %"),
        (verdict("check", [True, False]), "consistent-only", "a pass at some delays only is not a pass"),
        (verdict("check", [False, False]), "fail", "no delay passes"),
        (verdict("report", [False]), "report", "a report row has no verdict"),
        (parse("*** PI DMA [8]\nExpected:      193 RCP cycles\nFound:         190 RCP cycles\n"), None,
         "a run without 'Benchmarks done' is not a result"),
        (parse("*** PI DMA [8]\nExpected:      193 RCP cycles     (2.5 Mbyte/s)\nFound:         190 RCP cycles     "
               "(2.5 Mbyte/s)\nBenchmarks done\n"), {("PI DMA", 8): ("RCP", 193, 190)}, "one block parses"),
    ]
    failed = [why for got, want, why in cases if got != want]
    for why in failed:
        print(f"FAILED: {why}")
    print(f"systembench report: self-test: {len(cases)} cases, {len(failed)} failed")
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    lines = report(Path(sys.argv[1]))
    rows = [dict(zip(lines[0].split("\t"), l.split("\t"))) for l in lines[1:]]
    for r in rows:
        spread = r["pristine"] if r["min"] == r["max"] else f"{r['pristine']} ({r['min']}..{r['max']})"
        print(f"{r['row']:14} {r['unit']} expected {r['expected']:>7} found {spread:24} "
              f"{r['runs_pass']}/{r['runs']} pass  {r['verdict']}")
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("systembench: " + ", ".join(f"{n} {v}" for v, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
