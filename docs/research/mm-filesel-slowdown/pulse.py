"""Game frame rate from the file-select cursor pulse period.

FileSelect_PulsateCursor (mm src/overlays/gamestates/ovl_file_choose/
z_file_choose_NES.c:522) ramps the highlight alpha toward a target and flips
the target every 20 game frames, so the pulse period is exactly 40 game frames
at any frame rate. Its period in capture time gives mean VI fields per game
frame: fields_per_frame = period_s * VI_HZ / 40. The period is fit over several
cycles, so it survives compression noise that hides per-frame duplicates.

usage: pulse.py VIDEO t0 t1 x0 y0 x1 y1 [plot.png]
The crop must enclose only the highlighted button (its glow rim).
"""
import sys, cv2, numpy as np
VI_HZ = 59.826  # NTSC VI field rate, 48.681812 MHz / (3094 x 263) (n64brew Video Interface)
video = sys.argv[1]; t0, t1 = float(sys.argv[2]), float(sys.argv[3])
x0, y0, x1, y1 = map(int, sys.argv[4:8])
cap = cv2.VideoCapture(video); fps = cap.get(cv2.CAP_PROP_FPS)
cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
ts, vals = [], []
while True:
    ms = cap.get(cv2.CAP_PROP_POS_MSEC); ok, f = cap.read()
    if not ok or ms / 1000 > t1: break
    ts.append(ms / 1000); vals.append(f[y0:y1, x0:x1].reshape(-1, 3).mean(0))
ts = np.array(ts); V = np.array(vals)
sig = V[:, int(np.argmax(V.var(0)))]
sig = sig - np.polyval(np.polyfit(ts, sig, 1), ts)
freqs = np.linspace(0.45, 1.8, 2701)  # brackets the 20/30/60 fps pulse: 0.50/0.75/1.50 Hz
s = sig * np.hanning(len(ts))
P = np.array([abs(np.sum(s * np.exp(-2j * np.pi * f * ts))) ** 2 for f in freqs])
f0 = freqs[int(np.argmax(P))]
period = 1 / f0
cands = {fpf: 40 * fpf / VI_HZ for fpf in (1, 1.5, 2, 3)}
rel = {fpf: P[int(np.argmin(abs(freqs - 1 / p)))] / P.max() for fpf, p in cands.items()}
print('%s t=%.2f-%.2f (%.1f s, %d frames) period %.4f s -> %.3f fields/game frame (%.2f game fps); rel power at 1/1.5/2/3 fields: %s' % (
    video, t0, t1, ts[-1] - ts[0], len(ts), period, period * VI_HZ / 40, 40 / period,
    ' '.join('%.2f' % rel[k] for k in sorted(rel))))
if len(sys.argv) > 8:
    W, H = 1800, 260
    img = np.full((H, W, 3), 255, np.uint8)
    sx = lambda t: int((t - ts[0]) / (ts[-1] - ts[0]) * (W - 20) + 10)
    for k in range(int(ts[-1] - ts[0]) + 1): cv2.line(img, (sx(ts[0] + k), 0), (sx(ts[0] + k), H), (210, 210, 210), 1)
    ys = (H - 10 - (sig - sig.min()) / (np.ptp(sig) + 1e-9) * (H - 20)).astype(int)
    pts = np.stack([[sx(t) for t in ts], ys], 1).reshape(-1, 1, 2)
    cv2.polylines(img, [pts], False, (200, 0, 0), 1)
    for (x, y) in pts[:, 0]: cv2.circle(img, (int(x), int(y)), 2, (0, 0, 200), -1)
    cv2.putText(img, '%s %.1f-%.1fs  1 s grid' % (video, t0, t1), (10, 20), 0, 0.5, (0, 0, 0), 1)
    cv2.imwrite(sys.argv[8], img)
