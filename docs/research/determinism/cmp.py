#!/usr/bin/env python3
"""cmp.py A.tsv B.tsv: first frame where each column differs, and final-row deltas."""
import sys


def load(path):
    rows = [line.rstrip('\n').split('\t') for line in open(path)]
    return rows[0], rows[1:]


ha, a = load(sys.argv[1])
hb, b = load(sys.argv[2])
cols = [c for c in ha if c in hb]
n = min(len(a), len(b))
print(f'rows {len(a)} vs {len(b)}')
first = {}
for i in range(n):
    for c in cols:
        if c in first:
            continue
        if a[i][ha.index(c)] != b[i][hb.index(c)]:
            first[c] = i
for c in cols:
    if c == 'frame':
        continue
    print(f'{c:16} ' + (f'first diff at row {first[c]}' if c in first else 'identical'))
for c in ('cpu_cycles', 'rsp_busy_clocks'):
    if c in cols:
        x, y = int(a[n - 1][ha.index(c)]), int(b[n - 1][hb.index(c)])
        print(f'final {c}: {x} vs {y} delta {y - x} ({(y - x) / x * 100:+.4f}%)')
if 'cpu_cycles' in first:
    i = first['cpu_cycles']
    print('first cpu_cycles diff row:', a[i][:7], b[i][:7])
