"""Cadence inside high-motion bursts of a framediff TSV.

A burst is a run of capture frames where motion (mad) exceeds HOT, joined
across gaps of <= GAP frames. Inside a burst a frame is a new game frame when
its mad exceeds REL x the burst's median of hot frames (duplicates of a
compressed capture sit at 0.0-0.2 while new frames in a moving window sit at
1-30). Prints the run of intervals and the distinct-frame rate per burst and
writes a thumbnail strip per burst for visual state labelling.
usage: bursts.py DIFF.tsv VIDEO OUTPREFIX [crop x0 y0 x1 y1]
"""
import csv, sys, statistics, collections, cv2, numpy as np
fn, video, prefix = sys.argv[1:4]
crop = tuple(map(int, sys.argv[4:8])) if len(sys.argv) >= 8 else None
HOT, GAP, REL = 0.8, 5, 0.15
rows = list(csv.DictReader(open(fn), delimiter='\t'))
m = [float(r['mad']) for r in rows]
t = [float(r['t']) for r in rows]
hot = [i for i, x in enumerate(m) if x > HOT]
bursts = []
for i in hot:
    if bursts and i - bursts[-1][-1] <= GAP: bursts[-1].append(i)
    else: bursts.append([i])
cap = cv2.VideoCapture(video)
tot = collections.Counter()
for k, b in enumerate(bursts):
    if len(b) < 3: continue
    med = statistics.median(m[i] for i in b)
    new = [i for i in range(b[0], b[-1] + 1) if m[i] > REL * med]
    iv = [y - x for x, y in zip(new, new[1:])]
    span = new[-1] - new[0]
    print('burst %2d t=%8.3f-%8.3f med %5.1f new %3d intervals %s  fields/frame %.2f' % (
        k, t[b[0]], t[b[-1]], med, len(new), ''.join(str(x) if x < 10 else '+' for x in iv), span / max(1, len(iv))))
    tot.update(iv)
    cap.set(cv2.CAP_PROP_POS_MSEC, t[(b[0] + b[-1]) // 2] * 1000)
    ok, f = cap.read()
    if ok:
        if crop: f = f[crop[1]:crop[3], crop[0]:crop[2]]
        cv2.imwrite('%s_b%02d.png' % (prefix, k), cv2.resize(f, (320, 240)))
print('all bursts interval histogram', dict(sorted(tot.items())))
