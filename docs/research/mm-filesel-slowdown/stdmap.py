"""Temporal std-dev heat map of a capture window, to locate the pulsing cursor.
usage: stdmap.py VIDEO t0 t1 out.png"""
import sys, cv2, numpy as np
cap = cv2.VideoCapture(sys.argv[1]); t0, t1 = float(sys.argv[2]), float(sys.argv[3])
cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000); fr = []; last = None
while True:
    ms = cap.get(cv2.CAP_PROP_POS_MSEC); ok, f = cap.read()
    if not ok or ms / 1000 > t1: break
    fr.append(cv2.resize(f, (640, 360)).astype(np.float32)); last = f
s = np.array(fr).std(0).max(2)
heat = cv2.applyColorMap(np.clip(s / np.percentile(s, 99.5) * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
cv2.imwrite(sys.argv[4], np.hstack([cv2.resize(last, (640, 360)), heat]))
