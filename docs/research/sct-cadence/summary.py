"""Pools the high-motion bursts of a bursts.py report into a cadence table.

Low-motion bursts (median diff under MIN_MED) and short ones (under MIN_NEW
new frames) are dropped: mm-filesel-slowdown.md found their single 1s and 2s
unreliable. RATE is capture fps over the NTSC VI field rate (59.826 Hz), so
mean / RATE is fields per game frame.
usage: summary.py BURSTS.txt CAPTURE_FPS
"""
import re, sys, collections
MIN_MED, MIN_NEW = 2.0, 15
rate = float(sys.argv[2]) / (48681812 / (3094 * 263))
pat = re.compile(r't=\s*([\d.]+)-\s*([\d.]+) med\s+([\d.]+) new\s+(\d+) intervals (\S+)')
pool = collections.Counter()
for line in open(sys.argv[1]):
    m = pat.search(line)
    if not m: continue
    t0, t1, med, new, iv = float(m[1]), float(m[2]), float(m[3]), int(m[4]), m[5]
    if med < MIN_MED or new < MIN_NEW: continue
    n = [10 if c == '+' else int(c) for c in iv]
    c = collections.Counter(n)
    pool.update(n)
    print('%8.2f-%8.2f s  frames %3d  at 3: %5.1f%%  mean %.3f capture frames = %.3f fields' % (
        t0, t1, len(n), 100 * c[3] / len(n), sum(n) / len(n), sum(n) / len(n) / rate))
tot = sum(pool.values())
mean = sum(k * v for k, v in pool.items()) / tot
print('pooled: frames %d  histogram %s  at 3: %.1f%%  mean %.3f capture frames = %.3f fields' % (
    tot, dict(sorted(pool.items())), 100 * pool[3] / tot, mean, mean / rate))
