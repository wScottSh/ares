"""Per-capture-frame mean abs luma diff vs previous frame.

usage: framediff.py VIDEO OUT.tsv [x0 y0 x1 y1] [t0 t1]
Crop excludes stream overlays; t0/t1 in seconds limit the range.
"""
import sys, cv2, numpy as np
path, out = sys.argv[1], sys.argv[2]
crop = tuple(map(int, sys.argv[3:7])) if len(sys.argv) >= 7 else None
t0, t1 = (float(sys.argv[7]), float(sys.argv[8])) if len(sys.argv) >= 9 else (0.0, 1e9)
cap = cv2.VideoCapture(path)
fps = cap.get(cv2.CAP_PROP_FPS)
cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
prev = None
rows = []
while True:
    ms = cap.get(cv2.CAP_PROP_POS_MSEC)
    ok, f = cap.read()
    if not ok or ms / 1000 > t1: break
    if crop: f = f[crop[1]:crop[3], crop[0]:crop[2]]
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (320, 240), interpolation=cv2.INTER_AREA).astype(np.int16)
    if prev is not None:
        d = np.abs(g - prev)
        rows.append((ms / 1000, float(d.mean()), float(d.max()), int((d > 6).sum()), float(g.mean())))
    prev = g
with open(out, 'w') as fh:
    fh.write('frame\tt\tmad\tmaxd\tnpix_gt6\tluma\n')
    for i, r in enumerate(rows):
        fh.write('%d\t%.4f\t%.4f\t%.1f\t%d\t%.2f\n' % ((i,) + r))
print(path, 'fps', fps, 'frames', len(rows) + 1)
