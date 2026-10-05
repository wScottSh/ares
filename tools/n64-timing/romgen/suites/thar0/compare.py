"""Compares a thar0-rdp.z64 run with the hardware results, per spec.

usage: python -m romgen.suites.thar0.compare STDOUT_TXT [--out TSV]

Parses the ROM's BUF/PIPE blocks, reduces each like Thar0's analyze.py (drop values outside the
1% and 99% quantiles, then min/avg/max), and prints model against hardware in RDP clocks
(62.5 MHz) with expected.tsv as the hardware side. A counter delta prints as a signed 32-bit
value, so today's idle counters (run == baseline) show as -1 rather than 4294967295.
Exits 1 if any spec has no block.
"""
import argparse
import os
import sys

from .configs import SPECS

EXPECTED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected.tsv")


def signed32(v):
    return v - (1 << 32) if v >= 1 << 31 else v


def parse(stdout_txt):
    """Returns {spec index: {"BUF": [...], "PIPE": [...]}} in the order the blocks appear."""
    by_desc = {s.desc: i for i, s in enumerate(SPECS)}
    blocks, current, key, values = {}, None, None, None
    for line in open(stdout_txt, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if key is not None:
            if line == "]":
                blocks[current][key] = values
                key = None
            else:
                values += [signed32(int(v)) for v in line.replace(",", " ").split()]
        elif line in by_desc:
            current = by_desc[line]
            blocks[current] = {}
        elif line in ("BUF = [", "PIPE = [") and current is not None:
            key, values = line.split()[0], []
    return blocks


def quantile(sorted_values, q):
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def reduce(values):
    """analyze.py: prune outside [q01, q99], then (min, avg, max)."""
    s = sorted(values)
    lo, hi = quantile(s, 0.01), quantile(s, 0.99)
    kept = [v for v in values if lo <= v <= hi]
    return min(kept), sum(kept) / len(kept), max(kept)


def load_expected():
    rows = {}
    with open(EXPECTED, encoding="utf-8") as f:
        next(f)
        for line in f:
            c = line.rstrip("\n").split("\t")
            rows[int(c[0])] = (c[1], tuple(float(v) for v in c[2:5]), tuple(float(v) for v in c[5:8]))
    return rows


def fmt(t):
    return f"{t[0]:.0f}/{t[1]:.1f}/{t[2]:.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stdout_txt")
    ap.add_argument("--out", help="also write the table as TSV")
    args = ap.parse_args()
    blocks = parse(args.stdout_txt)
    expected = load_expected()
    header = ["index", "id", "runs", "model_buf", "hw_buf", "buf_avg_delta",
              "model_pipe", "hw_pipe", "pipe_avg_delta"]
    rows = []
    for i, spec in enumerate(SPECS):
        sid, hw_buf, hw_pipe = expected[i]
        assert sid == spec.id, (i, sid, spec.id)
        b = blocks.get(i, {})
        if "BUF" not in b or "PIPE" not in b:
            rows.append([str(i), sid, "0", "missing", fmt(hw_buf), "", "missing", fmt(hw_pipe), ""])
            continue
        mb, mp = reduce(b["BUF"]), reduce(b["PIPE"])
        rows.append([str(i), sid, str(len(b["BUF"])), fmt(mb), fmt(hw_buf), f"{mb[1] - hw_buf[1]:+.1f}",
                     fmt(mp), fmt(hw_pipe), f"{mp[1] - hw_pipe[1]:+.1f}"])
    widths = [max(len(r[k]) for r in rows + [header]) for k in range(len(header))]
    for r in [header] + rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    missing = sum(r[3] == "missing" for r in rows)
    print(f"specs reported: {100 - missing}/100 (min/avg/max in RDP clocks, 62.5 MHz)")
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            for r in [header] + rows:
                f.write("\t".join(r) + "\n")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
