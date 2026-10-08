"""Checks report.py's derived metrics on synthetic measurements with known answers.

usage: python tools/n64-timing/romgen/suites/bench/selftest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from romgen.suites.bench.report import derive, phase_of, verdict  # noqa: E402

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got!r} (want {want!r})")


line = 2979
samples = []
for n in range(3):
    for off in range(0, line, 17):
        samples.append(f"{n * line + off}:{16 if off != 340 else 16 + 40}")
hpos = derive("uncached-vs-hpos", {"bank5": {"line_ticks": line, "samples": samples,
                                              "count": len(samples)}})["bank5"]
check("hpos one refresh per line", hpos["outliers_per_line"], 1.0)
check("hpos holdoff 40 ticks = 53.33 rclk", hpos["holdoff_rclk_max"], 53.33)
check("hpos median 16 ticks = 32 pclk", hpos["median_pclk"], 32)

sync = derive("rdp-sync-sweep", {
    "none-0": {"n": 0, "kind": "none", "clock": 100, "min": 10},
    "pipe-256": {"n": 256, "kind": "pipe", "clock": 100 + 256 * 50, "min": 10},
    "rect-16": {"n": 16, "kind": "rect", "clock": 900, "min": 10},
    "rect-tile-16": {"n": 16, "kind": "rect+tile", "clock": 900 + 16 * 33, "min": 10},
})
check("sync pipe net of the empty list", sync["pipe-256"]["per_sync_clk"], 50.0)
check("sync tile net of the rect-only list", sync["rect-tile-16"]["per_sync_clk"], 33.0)

memset = derive("mi-memset-uncached", {"vi-on": {"bytes": 1 << 20, "min": 1204688}})["vi-on"]
check("25.7 ms/MiB uncached memset", memset["ms_per_mib"], 25.7)
check("18.38 pclk per SD", memset["pclk_per_sd"], 18.382)

sb = derive("uncached-sizes", {
    "c32": {"bits": 32, "unit": "pclk", "reps": 50, "min": 1, "max": 9, "sum": 1 + 9 + 48 * 2},
    "u32": {"bits": 32, "unit": "pclk", "reps": 50, "min": 16, "max": 17, "sum": 16 + 17 + 24 * 16 + 24 * 17},
})
check("systembench drops the lowest and highest rep: 48 x 2 ticks = 4 pclk", sb["c32"]["sb_pclk"], 4)
check("16.5 ticks = 33 pclk", sb["u32"]["sb_pclk"], 33)
check("harness overhead is the cached sample less a 1 pclk hit", sb["u32"]["overhead_pclk"], 3)
check("net is the sample less the overhead", sb["u32"]["net_pclk"], 30)
rclk = derive("pi-io-write", {"rom-word": {"unit": "rclk", "reps": 50, "min": 100, "max": 200, "sum": 100 + 200 + 48 * 101}})
check("101 ticks = 134.67 rclk rounds down to 134", rclk["rom-word"]["sb_rclk"], 134)

walked = derive("pi-io-write", {"rom-word": {"unit": "rclk", "reps": 50, "walk": "poll", "min": 94, "max": 160,
                                             "max2": 107, "sum": 94 + 160 + 48 * 100}})["rom-word"]
check("a poll-walked point spans its kept reps: 94 ticks = 125.33 rclk", walked["sb_rclk_rep_min"], 125.33)
check("the second highest rep, not the cold first one: 107 ticks = 142.67 rclk", walked["sb_rclk_rep_max"], 142.67)

key = ("r", "p", "m")
delays = [{key: v} for v in (6.169, 6.169, 6.334, 6.495, 6.678)]
phase = phase_of(delays, key)
check("phase range over the boot delays", (phase.lo, phase.hi, phase.median, phase.mean), (6.169, 6.678, 6.334, 6.369))
band = {"kind": "check", "lo": "6.49", "hi": "6.515"}
check("consistent: the band overlaps the phase range", verdict({**band, "rule": "consistent"}, phase), "pass")
check("mean: the phase mean is outside the band", verdict({**band, "rule": "mean"}, phase), "fail")
check("every: not every phase is inside the band", verdict({**band, "rule": "every"}, phase), "fail")
inside = phase_of([{key: 6.5}, {key: 6.51}], key)
check("every: every phase inside the band", verdict({**band, "rule": "every"}, inside), "pass")
check("consistent: a range wholly below the band", verdict({"kind": "check", "lo": "7", "hi": "8", "rule": "consistent"}, phase), "fail")
poll = phase_of([{key: 133, key[:2] + ("m_rep_min",): 125.33, key[:2] + ("m_rep_max",): 142.67}], key)
check("a poll-walked range comes from its reps", (poll.lo, poll.hi, poll.mean), (125.33, 142.67, 133))
check("a delay that printed nothing is missing", phase_of([{key: 1}, {}], key), None)

sys.exit(1 if failures else 0)
