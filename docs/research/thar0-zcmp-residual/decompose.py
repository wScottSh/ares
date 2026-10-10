"""Decompose the model's RDP memory timeline per Thar0 config from an ARES_MEMLOG trace.

usage: decompose.py mem.tsv compare.tsv [runs_per_config]

mem.tsv comes from a build with memlog.diff applied, run as ARES_MEMLOG=mem.tsv on a Thar0 ROM built with
--define RUNS=2; compare.tsv is any full Thar0 compare (it gives the config order). Each config leaves a
setup segment, a lone-FULLSYNC baseline and RUNS timed runs; a timed run is a segment of exactly 240 spans.
The last run of each config is decomposed. The match column says whether its total is within 0.1% of the
model BUF avg in compare.tsv; a config whose runs differ (zbrw-pass: Z state carries across runs) is off.
Prints, per config, per 320-px line (rclk): span period, and for each read burst the mean of
  wait  = RI grant start - port post (request latency, arbitration, refresh)
  wire  = RI dataEnd - grant start (hit latency or row miss, 8 octbytes)
  ovh   = port freeAt - dataEnd (rdp.mem-overhead-read)
  lat   = landAt - freeAt (rdp.span-read-latency)
  gap   = next post of the same image - previous landing
plus row misses and refreshes that fell inside the run window.
"""
import sys, csv, collections
U = 12.0
trace, cfgs = sys.argv[1], sys.argv[2]
runs = int(sys.argv[3]) if len(sys.argv) > 3 else 2
cmp = list(csv.DictReader(open(cfgs), delimiter='\t'))
ids = [r['id'] for r in cmp]
buf = [float(r['model_buf'].split('/')[1]) for r in cmp]
REQ = {5: 0, 6: 1}  # DpColor -> image 0, DpDepth -> image 1

segs, cur = [], []
for line in open(trace):
    f = line.rstrip('\n').split('\t')
    if f[0] == 'F':
        segs.append((cur, int(f[1]))); cur = []
    else:
        cur.append(f)
test = [s for s in segs if sum(1 for e in s[0] if e[0] == 'S') == 240]
assert len(test) == len(ids) * runs, (len(test), len(ids) * runs)

print('idx\tid\tspans\tperiod\tlines_total\trd_bursts/line\twait\twire\tovh\tlat\tgap\tser/burst\trowmiss/line\trefresh/line\twr_bursts/line\tmatch')
for n, (ev, fend) in enumerate(test):
    if n % runs != runs - 1: continue
    idx = n // runs
    S = [e for e in ev if e[0] == 'S']
    starts = [int(e[6]) for e in S]
    t0 = min(int(e[5]) for e in ev if e[0] == 'P') if any(e[0] == 'P' for e in ev) else starts[0]
    period = (starts[-1] - starts[0]) / (len(starts) - 1) / U
    # pair posts with grants per (image, address) in order
    posts = collections.defaultdict(collections.deque)
    rec = []
    pending_r = collections.defaultdict(collections.deque)
    refreshes = 0
    for e in ev:
        if e[0] == 'P' and e[2] == '0':
            posts[(int(e[1]), e[4])].append(int(e[5]))
        elif e[0] == 'R':
            req = int(e[1])
            if req == 0: refreshes += 1
            if req in REQ and e[2] == '0':
                pending_r[(REQ[req], e[3])].append((int(e[5]), int(e[7]), int(e[8])))
        elif e[0] == 'G' and e[2] == '0':
            k = (int(e[1]), e[4])
            p = posts[k].popleft(); st, de, rm = pending_r[k].popleft()
            rec.append((int(e[1]), p, st, de, int(e[6]), int(e[7]), rm))
    lines = len(S)
    nb = len(rec)
    if nb:
        wait = sum(r[2]-r[1] for r in rec)/nb/U; wire = sum(r[3]-r[2] for r in rec)/nb/U
        ovh = sum(r[4]-r[3] for r in rec)/nb/U; lat = sum(r[5]-r[4] for r in rec)/nb/U
        gaps = []
        last = {}
        for r in rec:
            if r[0] in last: gaps.append(r[1] - last[r[0]])
            last[r[0]] = r[5]
        gap = sum(gaps)/len(gaps)/U if gaps else 0
        rm = sum(r[6] for r in rec)/lines
    else:
        wait = wire = ovh = lat = gap = rm = 0
    wb = sum(1 for e in ev if e[0] == 'G' and e[2] == '1') / lines
    total = (fend - t0) / U
    print(f'{idx}\t{ids[idx]}\t{lines}\t{period:.2f}\t{total:.1f}\t{nb/lines:.2f}\t{wait:.2f}\t{wire:.2f}\t{ovh:.2f}\t{lat:.2f}\t{gap:.2f}\t{wait+wire+ovh+lat+gap:.2f}\t{rm:.3f}\t{refreshes/lines:.3f}\t{wb:.2f}\t{abs(total - buf[idx]) / buf[idx] < 0.001}')
