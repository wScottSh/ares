"""Least-squares triangle-wave fit of the cursor pulse (40 game frames/period).

Use when the window holds only 1-3 pulse cycles and a spectrum cannot resolve
the period. Scans the period, fits phase/amplitude/offset/linear drift per
period, and prints the residual curve so the minimum's sharpness is visible.
usage: trifit.py VIDEO t0 t1 x0 y0 x1 y1
"""
import sys, cv2, numpy as np
VI_HZ = 59.826
v = sys.argv[1]; t0, t1 = map(float, sys.argv[2:4]); x0, y0, x1, y1 = map(int, sys.argv[4:8])
cap = cv2.VideoCapture(v); cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000); ts, vals = [], []
while True:
    ms = cap.get(cv2.CAP_PROP_POS_MSEC); ok, f = cap.read()
    if not ok or ms / 1000 > t1: break
    ts.append(ms / 1000); vals.append(f[y0:y1, x0:x1].reshape(-1, 3).mean(0))
ts = np.array(ts); V = np.array(vals); y = V[:, int(np.argmax(V.var(0)))]
tri = lambda x: 2 * np.abs(2 * (x - np.floor(x + 0.5))) - 1
best = {}
for fpf in np.arange(0.8, 3.21, 0.02):
    P = 40 * fpf / VI_HZ; r = 1e18
    for ph in np.linspace(0, 1, 120, endpoint=False):
        A = np.vstack([tri(ts / P + ph), np.ones_like(ts), ts - ts.mean()]).T
        c, res, *_ = np.linalg.lstsq(A, y, rcond=None)
        rr = float(np.sum((A @ c - y) ** 2))
        if c[0] > 0 and rr < r: r = rr
    best[round(fpf, 2)] = r
k = min(best, key=best.get); rmin = best[k]
print('%s %.2f-%.2f: best %.2f fields/game frame (%.1f fps); residual ratio vs best at 1.0/1.5/2.0/3.0: %s' % (
    v, t0, t1, k, VI_HZ / k, ' '.join('%.2f' % (best[x] / rmin) for x in (1.0, 1.5, 2.0, 3.0))))
print('  fields within 1.5x of best residual: %s' % [x for x in sorted(best) if best[x] < 1.5 * rmin])
