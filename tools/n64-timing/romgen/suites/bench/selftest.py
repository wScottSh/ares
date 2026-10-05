"""Checks report.py's derived metrics on synthetic measurements with known answers.

usage: python tools/n64-timing/romgen/suites/bench/selftest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from romgen.suites.bench.report import derive  # noqa: E402

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

sys.exit(1 if failures else 0)
