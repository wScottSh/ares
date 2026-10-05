"""Distinct-frame cadence from a framediff.py TSV.

A capture frame is 'new' when its mean abs diff to the previous frame exceeds
THRESH (duplicates of a 240p source re-encoded by OBS/YouTube sit near 0.01).
Prints intervals between new frames (in capture frames) and distinct fps per
segment, where a segment is a run of frames classified by motion level.
"""
import csv, sys, collections
path = sys.argv[1]
thresh = float(sys.argv[2]) if len(sys.argv) > 2 else 0.05
big = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
rows = list(csv.DictReader(open(path), delimiter='\t'))
mad = [float(r['mad']) for r in rows]
new = [m > thresh for m in mad]
idx = [i for i, n in enumerate(new) if n]
iv = [b - a for a, b in zip(idx, idx[1:])]
print(path, 'capture frames', len(mad) + 1, 'new frames', len(idx))
print('mad of non-new frames: max %.3f' % max([m for m, n in zip(mad, new) if not n] or [0]))
print('mad of new frames: min %.3f' % min([m for m, n in zip(mad, new) if n] or [0]))
print('interval histogram (capture frames between distinct frames):', dict(sorted(collections.Counter(iv).items())))
# segment by motion: 'move' if a new frame has mad > big
segs = []
cur = None
for i, m in zip(idx, [mad[i] for i in idx]):
    kind = 'move' if m > big else 'idle'
    if cur and cur[0] == kind and i - cur[2] <= 4:
        cur[2] = i; cur[3].append(i)
    else:
        if cur: segs.append(cur)
        cur = [kind, i, i, [i]]
if cur: segs.append(cur)
for kind, a, b, pts in segs:
    span = b - a
    ivs = [y - x for x, y in zip(pts, pts[1:])]
    fps = (len(pts) - 1) / span * 60 if span else float('nan')
    print('%-4s frames %5d-%5d (%.2f-%.2f s) distinct %3d  intervals %s  distinct/s %.2f' % (
        kind, a, b, a / 60, b / 60, len(pts), dict(sorted(collections.Counter(ivs).items())), fps))
