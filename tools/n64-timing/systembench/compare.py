"""Puts the original n64-systembench on the fork next to its romgen port on the fork and the hardware value.

usage: compare.py SYSTEMBENCH_RESULTS BENCH_RESULTS     (each a results.tsv; prints compare.tsv to stdout)

Each side is shown as its offset from its own expected value, since a port's expected value is the hardware total
less the original's 2 pclk harness where the port measures net of its own (bench README). `inside` says whether the
original's value on the fork meets the original's own rule, and `port_rule` the port's verdict under its phase rule.
"""
import sys
from pathlib import Path


def rows(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l]


def num(text):
    return float(text) if text not in ("", "-", "None") else None


def offset(value, expected):
    return "-" if value is None or expected is None else f"{value - expected:+g}"


def main():
    original = rows(sys.argv[1])
    port = {(r["rom"], r["point"]): r for r in rows(sys.argv[2])}
    print("row\thw\torig_fork\torig_offset\torig_runs\tinside\tport\tport_expected\tport_range\tport_median_offset\tport_rule\tport_verdict")
    for o in original:
        p = port.get(tuple(o["port"].split(" ", 1)), {})
        hw = num(o["expected"])
        spread = o["pristine"] if o["min"] == o["max"] else f"{o['pristine']} ({o['min']}..{o['max']})"
        rng = "-" if not p else p["min"] if p["min"] == p["max"] else f"{p['min']}..{p['max']}"
        print("\t".join([o["row"], o["expected"], spread, offset(num(o["pristine"]), hw), f"{o['runs_pass']}/{o['runs']}",
                         o["verdict"], o["port"], p.get("expected", "-"), rng,
                         offset(num(p.get("median", "-")), num(p.get("expected", "-"))), p.get("rule", "-"),
                         p.get("verdict", "-")]))


if __name__ == "__main__":
    main()
