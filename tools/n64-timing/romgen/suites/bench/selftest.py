"""Checks report.py's derived metrics on synthetic measurements with known answers.

usage: python tools/n64-timing/romgen/suites/bench/selftest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from romgen.suites.bench.report import Layout, acceptance, derive, layout_of, pad_phases_text, phase_of  # noqa: E402
from romgen.suites.bench.report import verdict as layout_rule_verdict  # noqa: E402

failures = 0


def verdict(row, phase):
    """One layout pad: the phase rule alone."""
    return layout_rule_verdict(row, Layout({0: phase}) if phase else None)


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

ifill = derive("ifill-isolated", {"warm": {"min": 3}, "cold": {"min": 25}})
check("one I-cache fill is the cold call less the warm one: 22 ticks = 44 pclk", ifill["cold"]["cold_minus_warm_pclk"], 44)

wb = derive("wb-fifth-store", {f"sw-{n}{t}": {"stores": n, "min": 10 + (8 * (n - 4) if n > 4 else 0) + (2 if t else 0)}
                               for n in range(1, 7) for t in ("", "-lw")})
check("a store into a free entry costs nothing more", wb["sw-4"]["minus_prev_pclk"], 0)
check("the fifth store waits 8 ticks = 16 pclk", wb["sw-5"]["minus_prev_pclk"], 16)
check("a load point steps from the load point before it", wb["sw-5-lw"]["minus_prev_pclk"], 16)
check("the first store has no step", "minus_prev_pclk" in wb["sw-1"], False)

load = {}
for b in (8, 64, 512, 4096):
    for n in (1, 4):
        load[f"block-{b}-n{n}"] = {"op": "block", "bytes": b, "n": n, "tmembusy": 30 + n * (7 + b // 2)}
        load[f"tile-{b}-n{n}"] = {"op": "tile", "bytes": b, "n": n, "tmembusy": 30 + n * (15 + b // 8)}
loadsz = derive("rdp-loadsz-sweep", load)
check("one load is (4 loads less 1) / 3, without the list's fixed cost", loadsz["block-512-n4"]["per_load_clk"], 263.0)
check("Load Block fit: 0.5 clk/B + 7", (loadsz["block-4096-n4"]["clk_per_byte"], loadsz["block-4096-n4"]["intercept_clk"]),
      (0.5, 7.0))
check("Load Tile fit: 8 B/clk + 15", (loadsz["tile-4096-n4"]["clk_per_byte"], loadsz["tile-4096-n4"]["intercept_clk"]),
      (0.125, 15.0))

key = ("r", "p", "m")
delays = [{key: v} for v in (6.169, 6.169, 6.334, 6.495, 6.678)]
phase = phase_of(delays, key)
check("phase range over the boot delays", (phase.lo, phase.hi, phase.median, phase.mean), (6.169, 6.678, 6.334, 6.369))
band = {"kind": "check", "lo": "6.49", "hi": "6.515", "expected": "6.5", "condition": "-"}
check("consistent: the band overlaps the range but the mean 6.369 misses it", verdict({**band, "rule": "consistent"}, phase),
      "consistent-only")
check("consistent: the mean rule's verdict and the window (0.025 + 0.509) / 2 of 6.5",
      acceptance({**band, "rule": "consistent"}, phase), ("fail", "4.1"))
straddle = phase_of([{key: 6.48}, {key: 6.52}], key)
check("consistent: the band overlaps the range and holds the mean", verdict({**band, "rule": "consistent"}, straddle), "pass")
inside = phase_of([{key: 6.5}, {key: 6.51}], key)
check("a pass that rests on a model choice names its issue", verdict({**band, "rule": "every", "condition": "#77"}, inside),
      "pass-conditional:#77")
check("a conditional row that fails is a fail", verdict({**band, "rule": "mean", "condition": "#77"}, phase), "fail")
check("only a consistent row has a window", acceptance({**band, "rule": "mean"}, phase), ("-", "-"))
check("mean: the phase mean is outside the band", verdict({**band, "rule": "mean"}, phase), "fail")
below = phase_of([{key: 6.47962}, {key: 6.5}], key)
check("mean: an unrounded mean 0.0002 below the floor fails though it displays as 6.49",
      (below.mean, verdict({**band, "rule": "mean"}, below)), (6.49, "fail"))
check("consistent: the same mean is consistent-only", verdict({**band, "rule": "consistent"}, below), "consistent-only")
check("the pad text keeps the unrounded mean behaviors.py recomputes from", pad_phases_text(Layout({6: below})),
      "6:6.48..6.5/6.48981")
check("every: not every phase is inside the band", verdict({**band, "rule": "every"}, phase), "fail")
check("every: every phase inside the band", verdict({**band, "rule": "every"}, inside), "pass")
check("consistent: a range wholly below the band", verdict({"kind": "check", "lo": "7", "hi": "8", "rule": "consistent"}, phase), "fail")
poll = phase_of([{key: 133, key[:2] + ("m_rep_min",): 125.33, key[:2] + ("m_rep_max",): 142.67}], key)
check("a poll-walked range comes from its reps", (poll.lo, poll.hi, poll.mean), (125.33, 142.67, 133))
check("a delay that printed nothing is missing", phase_of([{key: 1}, {}], key), None)

grid = {(0, 1): {key: 6.50}, (0, 42): {key: 6.51}, (4, 1): {key: 6.27}, (4, 42): {key: 6.50}}
pads = layout_of(grid, key)
check("each pad's range over the delays", [(ph.lo, ph.hi) for ph in pads.pads.values()], [(6.5, 6.51), (6.27, 6.5)])
check("the joint range spans every pad and delay", (pads.joint.lo, pads.joint.hi, pads.joint.mean), (6.27, 6.51, 6.445))
mean_row = {**band, "rule": "mean"}
check("pads that disagree (pass at pad 0, fail at pad 4) are consistent-only, never pass or fail",
      layout_rule_verdict(mean_row, pads), "consistent-only")
check("every pad passing passes", layout_rule_verdict(mean_row, layout_of({(0, 1): {key: 6.5}, (4, 1): {key: 6.51}}, key)), "pass")
check("every pad failing fails", layout_rule_verdict(mean_row, layout_of({(0, 1): {key: 6.2}, (4, 1): {key: 6.3}}, key)), "fail")
check("a pad that lacks the metric makes the row missing",
      layout_rule_verdict(mean_row, layout_of({(0, 1): {key: 6.5}, (4, 1): {}}, key)), "missing")

sys.exit(1 if failures else 0)
