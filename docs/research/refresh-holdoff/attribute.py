"""Attribute each hpos outlier sample to RI events from an ARES_RILOG trace.
usage: attribute.py RILOG [START_PC END_PC]"""
import sys, re, statistics
log = sys.argv[1]
start_pc = sys.argv[2] if len(sys.argv) > 2 else "80001618"
end_pc = sys.argv[3] if len(sys.argv) > 3 else "80001624"
NAMES = {0: "refresh", 1: "vi", 2: "cpu"}
events, samples, open_ = [], [], None
for line in open(log):
    p = line.split()
    if len(p) < 2 or not p[0].isdigit(): continue
    t = int(p[0])
    if p[1] == "COUNT":
        pc = p[2][3:]
        if pc == start_pc: open_ = (t, len(events))
        elif pc == end_pc and open_:
            samples.append((open_[0], t, events[open_[1]:]))
            open_ = None
        continue
    kv = dict(x.split("=", 1) for x in p[1:] if "=" in x)
    if "free" not in kv: continue
    events.append(dict(d=t, r=int(kv["r"]), a=int(kv["a"], 16), n=int(kv["n"]), arr=int(kv["arr"]),
                       ds=int(kv["ds"]), de=int(kv["de"]), free=int(kv["free"]), miss=int(kv["miss"])))
# group samples into runs by the uncached address of their first CPU word load
runs = {}
for s, e, evs in samples:
    loads = [x for x in evs if x["r"] == 2 and x["n"] == 4 and x["arr"] <= e]
    if not loads: continue
    runs.setdefault(loads[0]["a"], []).append((s, e, evs))
for addr, ss in runs.items():
    lens = [e - s for s, e, _ in ss]
    med = statistics.median(lens)
    print(f"addr={addr:06x} samples={len(ss)} median={med} units ({med/16} ticks)")
    for i, (s, e, evs) in enumerate(ss):
        if e - s < med + 20 * 16: continue
        refresh = [x for x in evs if x["r"] == 0 and x["d"] < e] + \
                  [x for x in events if x["r"] == 0 and x["d"] < s < x["de"]]
        parts = []
        for x in [y for y in events if y["d"] < s < y["free"] and y["r"] != 0] + evs:
            if x["arr"] > e: break
            name = NAMES.get(x["r"], str(x["r"]))
            if x["r"] == 2: name = "load" if x["a"] == addr else f"cpu{x['n']}@{x['a']:x}"
            parts.append(f"{name}(arr+{x['arr']-s} wait={x['d']-x['arr']} wire={x['de']-x['d']} miss={x['miss']})")
        rinfo = ",".join(f"refresh[{x['d']-s:+}..{x['de']-s:+}]" for x in refresh)
        print(f"  #{i} len={e-s} excess={(e-s-med)/12:.2f} rclk {rinfo} :: " + " ".join(parts))
