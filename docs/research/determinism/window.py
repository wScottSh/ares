#!/usr/bin/env python3
"""window.py A.tsv B.tsv [W]: per-W-field window rsp_busy_clocks difference, max and mean abs %."""
import sys


def col(path, name):
    rows = [line.rstrip('\n').split('\t') for line in open(path)]
    i = rows[0].index(name)
    return [int(r[i]) for r in rows[1:]]


a = col(sys.argv[1], 'rsp_busy_clocks')
b = col(sys.argv[2], 'rsp_busy_clocks')
w = int(sys.argv[3]) if len(sys.argv) > 3 else 120
diffs = []
for s in range(0, min(len(a), len(b)) - w, w):
    da, db = a[s + w] - a[s], b[s + w] - b[s]
    if da:
        diffs.append((abs(db - da) / da * 100, s, da, db))
diffs.sort(reverse=True)
mean = sum(d[0] for d in diffs) / len(diffs)
print(f'windows={len(diffs)} W={w} max={diffs[0][0]:.4f}% at field {diffs[0][1]} ({diffs[0][2]} vs {diffs[0][3]}) mean={mean:.4f}%')
