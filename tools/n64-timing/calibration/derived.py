"""Derived metrics of the kit ROMs whose questions compare a fit or a difference, not a raw point.

Each function takes one log's records ({(rom, point): fields}) and returns {(rom, point): fields} to
add, or raises KeyError when the log lacks its points (kit.derive skips it). The points are named in
romgen/suites/calib/<module>.py.
"""
import collections
import math
from romgen.suites.bench import report as bench_report


def fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return slope, my - slope * mx


def tex(recs):
    """kit-tex: TMEM load slope and intercept from 4 loads minus 1 (tmembusy, a gated counter: DPC_CLOCK
    carries the CPU's MI_INTR poll quantum), the Load Tile per-row cost, fill and copy bytes per
    clock, copy-mode alpha-compare ratios, and the attribute sync costs."""
    g = lambda rom, pt, f: recs[(rom, pt)][f]  # noqa: E731
    out = {}
    sizes = [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
    for op in ("block", "tile"):
        per = [(g("tex-load", f"{op}-{b}-n4", "tmembusy") - g("tex-load", f"{op}-{b}-n1", "tmembusy")) / 3 for b in sizes]
        slope, intercept = fit(sizes, per)
        out[f"load-{op}-clk-per-byte"], out[f"load-{op}-intercept"] = round(slope, 4), round(intercept, 1)
    rows = [1, 2, 4, 8, 16, 32, 64, 128, 256]
    out["rows-tmem-per-row"] = round(fit(rows, [g("tex-rows", f"rows-{r}", "tmembusy") for r in rows])[0], 3)
    out["rows256-minus-block2048"] = g("tex-rows", "rows-256", "tmembusy") - g("tex-load", "block-2048-n1", "tmembusy")
    widths = [8, 16, 32, 64, 128, 256, 320]
    for mode, bpp in (("fill", 16), ("fill", 32), ("copy", 16)):
        xs = [w * bpp // 8 * 8 for w in widths]
        slope = fit(xs, [g("tex-fillcopy", f"{mode}-b{bpp}-w{w}", "pipebusy") for w in widths])[0]
        out[f"{mode}-b{bpp}-bytes-per-clk"] = round(1 / slope, 3)
    base = g("tex-copyac", "pass-ac1", "pipebusy")
    for pat in ("fail-ac1", "word-ac1", "texel-ac1", "fail-ac0"):
        out[f"copyac-{pat}-over-pass"] = round(g("tex-copyac", pat, "pipebusy") / base, 3)
    for c in ("c1", "c2"):
        for attr, sync in (("tile", "pipe"), ("tile", "tile"), ("blender", "pipe"), ("dither", "pipe")):
            out[f"attr-{attr}-{c}-{sync}-sync-cost"] = (g("tex-attr", f"{attr}-{c}-{sync}", "pipebusy")
                                                        - g("tex-attr", f"{attr}-{c}-none", "pipebusy"))
    return {("tex-derived", "all"): out}


def zmem(records):
    """kit-zmem and kit-zread (written in place, after the zmem module's report): write-run fits over
    the Z comb, the per-primitive atomic cost, IM_RD/Z_CMP overlap in 1- and 2-cycle, the 2-cycle and
    1-cycle read-only per-line and per-rectangle costs, the 1-cycle cost per 64 B read of a 320 px
    line (10 serial reads), 1 px triangle cost, the cost per MM file-name glyph, the clobber verdict, the X-bus and RDRAM command
    rates, the hold summary and PIPEBUSY's share of memory time."""
    def p(rom, point):
        return records.get((f"zmem-{rom}", point))

    def comb_shape(n, width=320):
        xs = [x for x in range(width) if (x // n) & 1]
        runs = sum(1 for x in xs if x == 0 or not (x - 1) // n & 1)
        return runs, len({x // 4 for x in xs})

    def r2(xs, ys):
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        syy = sum((y - my) ** 2 for y in ys)
        return (sxy / sxx if sxx else 0.0), (sxy * sxy / (sxx * syy) if sxx and syy else 0.0)

    for tag in ("zcmp", "zcmp-zupd"):
        combs = [(f["comb"], f["clock"]) for (rom, pt), f in records.items()
                 if rom == "zmem-write-gran" and pt.startswith(f"{tag}-comb")]
        out = {}
        if len(combs) > 2:
            shapes = [comb_shape(n) for n, _ in combs]
            clocks = [c for _, c in combs]
            out["run_slope"], out["r2_runs"] = (round(v, 3) for v in r2([s[0] for s in shapes], clocks))
            out["octbyte_slope"], out["r2_octbytes"] = (round(v, 3) for v in r2([s[1] for s in shapes], clocks))
            out["comb_range"] = max(clocks) - min(clocks)
        ok, bad, none = p("write-gran", f"{tag}-all-pass"), p("write-gran", f"{tag}-all-fail"), p("write-gran", "no-rect")
        if ok and bad and none:
            out["reject_saving"] = ok["clock"] - bad["clock"]
            out["fail_over_pass"] = round((bad["clock"] - none["clock"]) / (ok["clock"] - none["clock"]), 3)
        records[("zmem-write-gran", f"{tag}-fit")] = out
    for mode in ("plain", "zcmp-zupd", "imrd"):
        c = {(a, n): p("atomic", f"{mode}-atomic{a}-{n}") for a in (0, 1) for n in (16, 64)}
        if all(c.values()):
            on = c[(1, 64)]["clock"] - c[(1, 16)]["clock"]
            off = c[(0, 64)]["clock"] - c[(0, 16)]["clock"]
            records[("zmem-atomic", f"{mode}-cost")] = {"atomic_rclk": round((on - off) / 48, 2)}
    for rom, widths in (("slots", (8, 16, 24, 32, 48, 64, 96, 128, 192, 320)), ("slots2", (8, 32, 48, 64, 128, 320))):
        for w in widths:
            m = {k: p(rom, f"{k}-w{w}") for k in ("plain", "imrd", "zcmp", "imrd-zcmp")}
            if all(m.values()):
                a, b = m["imrd"]["clock"] - m["plain"]["clock"], m["zcmp"]["clock"] - m["plain"]["clock"]
                both = m["imrd-zcmp"]["clock"] - m["plain"]["clock"]
                records[(f"zmem-{rom}", f"overlap-w{w}")] = {
                    "both_over_sum": round(both / (a + b), 3) if a + b else None,
                    "both_over_max": round(both / max(a, b), 3) if max(a, b) else None}
    for mode in ("plain", "imrd", "zcmp", "imrd-zcmp"):
        for w in (32, 320):
            h8, h16 = p("read2", f"{mode}-w{w}-h8"), p("read2", f"{mode}-w{w}-h16")
            if h8 and h16:
                line = (h16["clock"] - h8["clock"]) / 8
                records[("zmem-read2", f"{mode}-w{w}-fit")] = {"rclk_per_line": round(line, 2),
                                                             "rclk_per_rect": round(h8["clock"] - 8 * line, 1)}
    #kit-zread's per-line cost is from BUFBUSY, not DPC_CLOCK: the DP-interrupt poll quantizes each clock,
    #so the clock difference of 16 less 8 lines did not move when the window's row misses did.
    for mode in ("none", "imrd", "zcmp", "both"):
        for bank in ("zsep", "zsame"):
            for w in (8, 32, 64, 128, 320):
                h8, h16 = p("read1", f"{mode}-{bank}-w{w}-h8"), p("read1", f"{mode}-{bank}-w{w}-h16")
                if h8 and h16:
                    line = (h16["bufbusy"] - h8["bufbusy"]) / 8
                    out = {"rclk_per_line": round(line, 3), "rclk_per_rect": round(h8["bufbusy"] - 8 * line, 1)}
                    if mode in ("imrd", "zcmp") and w == 320:
                        out["rclk_per_read"] = round(line / 10, 3)
                    records[("zmem-read1", f"{mode}-{bank}-w{w}-fit")] = out
    for t in ("fill", "z", "shade", "shade-z", "tex", "shade-tex"):
        lo, hi = p("tri", f"{t}-16"), p("tri", f"{t}-64")
        if lo and hi:
            records[("zmem-tri", f"{t}-setup")] = {"rclk_per_tri": round((hi["clock"] - lo["clock"]) / 48, 2)}
    lo, hi = p("glyph", "glyph-16"), p("glyph", "glyph-64")
    if lo and hi:
        records[("zmem-glyph", "fit")] = {"rclk_per_glyph": round((hi["clock"] - lo["clock"]) / 48, 2)}
    for w in (8, 64):
        blend, coherent, alone = p("clobber", f"blend-w{w}"), p("clobber", f"blend-atomic-w{w}"), p("clobber", f"blend-only-w{w}")
        reject = p("clobber", f"reject-w{w}-atomic0")
        if blend and coherent and alone and reject:
            stale = 1 if blend["hash"] == alone["hash"] else 0 if blend["hash"] == coherent["hash"] else -1
            records[("zmem-clobber", f"w{w}")] = {"stale_read": stale, "first_kept": reject["count"],
                                                 "block_writeback": int(reject["count"] < w)}
    for lst, (lo, hi) in (("nop", (64, 448)), ("rect", (16, 128))):
        out = {}
        for src in ("rdram", "dmem"):
            a, b = p("xbus", f"{lst}-{src}-{lo}"), p("xbus", f"{lst}-{src}-{hi}")
            if a and b:
                out[f"{src}_rclk_per_cmd"] = round((b["clock"] - a["clock"]) / (hi - lo), 3)
        records[("zmem-xbus", f"{lst}-rate")] = out
    whole = p("hold", "whole")
    if whole:
        seen = [int(pt[7:]) for (rom, pt), f in records.items()
                if rom == "zmem-hold" and pt.startswith("append-") and f["count"] == whole["count"]]
        records[("zmem-hold", "summary")] = {"whole_count": whole["count"],
                                            "last_delay_seen": max(seen) if seen else -1}
    plain, imrd = p("pipebusy", "plain-vioff"), p("pipebusy", "imrd-vioff")
    out = {}
    if plain and imrd:
        out["imrd_pipe_share"] = round((imrd["pipebusy"] - plain["pipebusy"]) / (imrd["clock"] - plain["clock"]), 3)
    for mode in ("imrd", "imrd-zcmp-zupd"):
        off, on = p("pipebusy", f"{mode}-vioff"), p("pipebusy", f"{mode}-vion")
        if off and on and on["clock"] != off["clock"]:
            out[f"{mode}_vi_pipe_share"] = round((on["pipebusy"] - off["pipebusy"]) / (on["clock"] - off["clock"]), 3)
    records[("zmem-pipebusy", "summary")] = out
    return {}


def cpu2(records):
    """kit-cpu2: exception entries against AdEL (cpu.exc-ex), the fetch fault against a plain jr, ERET
    and FPU ops in pclk net of the harness's mfc0 (base-nop0), the load interlocks, CACHE op pclk
    (op_sum / 4 is the phase-averaged reading in pclk, less the closing mfc0's 1) and the
    write-buffer drain per buffered store."""
    g = lambda rom, pt, f="min": records[(f"cpu2-{rom}", pt)][f]  # noqa: E731
    out = {}
    base = g("base", "nop0")
    out["harness-pclk"] = base
    adel = g("exc", "adel-lw")
    for pt in ("ades-sw", "ades-sd", "tlbl-lw", "tlbs-sw", "mod-sw", "fpe-ctc1-v", "fpe-ctc1-e", "irq-sw"):
        out[f"{pt}-minus-adel"] = g("exc", pt) - adel
    out["fetch-ade-minus-jr"] = g("exc", "fetch-ade") - g("exc", "jr-aligned")
    out["eret-pclk"] = g("exc", "eret") - base
    for pt in ("watch-lw", "watch-sw"):
        out[f"{pt}-fired"] = g("exc", pt, "fired")
    out["irq-timer-ticks"] = g("exc", "irq-timer", "lo")
    for pair, dep, indep in (("lwc1-add-s", "lwc1-add-s-next", "lwc1-add-s-indep"),
                             ("ldc1-add-d", "ldc1-add-d-next", "ldc1-add-d-indep"),
                             ("lw-mtc1", "lw-mtc1-next", "lw-mtc1-indep"),
                             ("lw-mtc2", "lw-mtc2-next", "lw-mtc2-indep"),
                             ("lw-mfc2", "lw-mfc2-next", "lw-mtc2-indep"),
                             ("lw-bc1t", "lw-at-bc1t", "lw-t1-bc1t")):
        out[f"{pair}-interlock"] = g("ldi", dep) - g("ldi", indep)
    for (rom, pt), f in records.items():
        if rom == "cpu2-fpu":
            out[f"fpu-{pt}-pclk"] = f["min"] - base
            out[f"fpu-{pt}-fired"] = f["fired"]
        elif rom == "cpu2-cache":
            out[f"cache-{pt}-op-pclk"] = f["op_sum"] / 4 - 1
            out[f"cache-{pt}-next-ticks"] = f["next_min"]
    for store in ("rdram", "sp-semaphore", "pi-cart"):
        for load in ("rdram", "mi-version", "pi-cart", "dcache-hit"):
            mins = [g("wb", f"{store}-{n}-{load}") for n in range(5)]
            out[f"wb-{store}-{load}-per-store"] = ",".join(str(b - a) for a, b in zip(mins, mins[1:]))
    return {("cpu2-derived", "all"): out}


def countw(recs):
    """kit-cpu2's COUNT write points: dmax - min per slot, the reading's spread over the eight entry phases.
    It shows the COUNT divider's phase through an MTC0 COUNT apart from the hold length that min reads."""
    out = {("cpu2-countw-spread", point): {"spread": f["dmax"] - f["min"]}
           for (rom, point), f in recs.items() if rom == "cpu2-countw"}
    if not out:
        raise KeyError("cpu2-countw")
    return out


def bus(recs):
    """kit-bus: the AI's power-on VCLK per sample (against the 1103-VCLK point, so the VI:COUNT clock
    ratio cancels), per-load slowdown under each RDRAM client, the SP DMA's slowdown from same-bank
    loads over other-bank loads (ri-reorder), VI fetch cost in loads lost per window, refresh hits and
    holdoff per bank."""
    g = lambda rom, pt, f: recs[(rom, pt)][f]  # noqa: E731
    out = {}
    span = lambda pt: g("bus-ai", pt, "last_change") - g("bus-ai", pt, "first_change")  # noqa: E731
    out["ai-power-on-vclk"] = round(1103 * span("power-on") / span("dacrate-1102"), 2)
    out["ai-dacrate-1103-vclk"] = round(1103 * span("dacrate-1103") / span("dacrate-1102"), 2)
    idle = g("bus-ri", "idle-bank5", "min")
    for client in ("sp-rd-16k", "pi-8k", "rdp-fill", "rdp-imrd"):
        for where in ("own", "bank5"):
            out[f"ri-{client}-{where}-extra-per-load"] = round((g("bus-ri", f"{client}-{where}", "min") - idle) / 32, 2)
    out["ri-reorder-own-minus-bank5"] = (g("bus-ri", "sp-rd-16k-own", "client_ticks")
                                         - g("bus-ri", "sp-rd-16k-bank5", "client_ticks"))
    out["ri-sp-bank5-minus-alone"] = (g("bus-ri", "sp-rd-16k-bank5", "client_ticks")
                                      - g("bus-ri", "sp-rd-16k-alone", "client_ticks"))
    nofetch = g("bus-vi", "vvideo-outside", "n")
    for (rom, point), f in recs.items():
        if rom == "bus-vi" and f.get("n"):
            out[f"vi-{point}-loads-lost"] = nofetch - f["n"]
    half = recs[("bus-vi", "hvideo-half")]
    out["vi-hvideo-half-late-minus-early"] = sum(half[f"c{i}"] for i in range(4, 8)) - sum(half[f"c{i}"] for i in range(4))
    for bank in range(8):
        f = recs[("bus-refresh", f"bank{bank}")]
        out[f"refresh-bank{bank}-hits"] = f["slow"]
        out[f"refresh-bank{bank}-excess"] = f["lat_max"] - f["lat_min"]
    return {("bus-derived", "all"): out}


def vintr(recs):
    """kit-bus's VI interrupt lag: the trimmed mean over the reps. A timed-out point has none (#132)."""
    v = recs[("bus-vintr", "v-intr")]
    if v.get("timeout"):
        return {}
    return {("bus-derived", "vintr"): {"vintr-mean-lag": round((v["sum"] - v["min"] - v["max"]) / (v["reps"] - 2) - v["bias"], 1)}}


#DPC_CLOCK's read lands on the CPU's MI_INTR poll, at most 20.4 rclk late (questions.tsv rdp-rect-base).
POLL_RCLK = 20.4
#One refresh: the IPL3 dirty refresh delay (ri.refresh-dirty, 54 rclk) plus the row retry it leaves
#(ri.retry-dirty, 30 tc = 7.5 rclk).
REFRESH_RCLK = 61.5
#A width step adds one pixel per line at 1 px/rclk (rdp.span-1cycle). Two adjacent widths differ
#outside that by less than one poll period and, the rectangle growing by less than one refresh
#interval, by at most one refresh less or two more: an excess above this is a stall.
STEP_RCLK = POLL_RCLK + 2 * REFRESH_RCLK
#One 64 B read and one 64 B write-back on the RDRAM wire, row hits: (10 + 32 + 2) + (4 + 32 + 4) tc
#(ri.read-hit, ri.write-hit, ri.octbyte, ri.post-read-gap, ri.post-write-gap) = 21 rclk at 4 tc per
#rclk, above the 16 clocks a 32 bpp half shades in; with a refresh's share of the channel (61.5 rclk
#per VI line of 42 us = 2625 rclk, rdram-bus-arbitration.md B11) and the poll and refresh error of a
#160 px difference over 10 halves of 256 lines.
WIRE_HALF_RCLK = 21.6


def release(clocks, lines, segment_px, half_px):
    """The width spacing of DPC_CLOCK's stall steps over consecutive widths ({width: clock})."""
    steps = [w + 1 for w in sorted(clocks) if w + 1 in clocks and clocks[w + 1] - clocks[w] - lines > STEP_RCLK]
    if not steps:
        return "no-step", steps
    if len(steps) == 1:
        return f"single-{steps[0]}", steps
    gaps = collections.Counter(b - a for a, b in zip(steps, steps[1:]))
    top = max(gaps.values())
    period = math.gcd(*[g for g, n in gaps.items() if n == top])
    return {segment_px: "segment", half_px: "half"}.get(period, f"period-{period}"), steps


#COUNT runs at half the 93.75 MHz PClock (VR4300 User's Manual 6.3.3); VCLK at 48.681812 MHz and the RCP
#at 62.5 MHz on NTSC (n64brew Clock_Timing). The longest refresh holdoff is 54 rclk (n64brew RDRAM_Interface).
TICKS_PER_VCLK = 46.875 / 48.681812
REFRESH_MAX_TICKS = 54 * 46.875 / 62.5


def hsync(recs):
    """kit-bus's short lines (bus.py hsync_short). On the refresh points no line is in V_VIDEO, so each
    slow load is one refresh holdoff: lines per holdoff from the lines H_SYNC puts in the window.
    fetch-overrun's VI time is the loads fetch-overrun-none gains, at its mean load period. With no
    burst both windows hold the same one refresh per line, so they differ by at most one holdoff, and
    by the load each window ends on: `fetch-overrun-fetched` is 1 when the VI time exceeds that."""
    out = {}
    pts = {point: f for (rom, point), f in recs.items() if rom == "bus-hsync" and f.get("starved") == 0}
    for point, f in pts.items():
        lines = f["window"] / ((f["hsync"] + 1) * TICKS_PER_VCLK)
        if point.startswith("refresh-") and f["slow"]:
            out[f"{point}-lines-per-holdoff"] = round(lines / f["slow"], 3)
    if "fetch-overrun" in pts and "fetch-overrun-none" in pts:
        fetch, none = pts["fetch-overrun"], pts["fetch-overrun-none"]
        vi = (none["n"] - fetch["n"]) * none["window"] / none["n"]
        lines = fetch["window"] / ((fetch["hsync"] + 1) * TICKS_PER_VCLK)
        out["fetch-overrun-vi-ticks-per-line"] = round(vi / lines, 2)
        out["fetch-overrun-fetched"] = int(vi > REFRESH_MAX_TICKS + 2 * max(fetch["lat_max"], none["lat_max"]))
    return {("bus-derived", "hsync"): out} if out else {}


def span2(recs):
    """kit-span2: per depth, the spacing of a write-only span's stall steps (segment: every 16 B,
    half: every 64 B, no-step, else period-<px> or single-<width>), the 32 bpp write-only steady cost
    per 64 B half, and IM_RD's steady cost per 64 B half against the RI wire time (wire-bound or above-wire)."""
    out = {}
    lines = recs[("span-write", "b32-w1")]["h"]
    for bpp in (32, 16):
        pts = [f for (rom, _), f in recs.items() if rom == "span-write" and f.get("bpp") == bpp]
        clocks = {f["w"]: f["clock"] for f in pts if f["w"] <= 80}
        px = bpp // 8
        cat, steps = release(clocks, lines, 16 // px, 64 // px)
        out[("span-write", f"release-b{bpp}")] = {"release": cat, "steps": ",".join(map(str, steps)) or "none"}
    #span-write-release compares the 32 bpp cost per 64 B half; 4 places keep rounding far under its 0.76 band.
    write = {f["w"]: f["clock"] for (rom, _), f in recs.items() if rom == "span-write" and f.get("bpp") == 32}
    out[("span-write", "release-b32")]["steady_half"] = round((write[320] - write[160]) / (lines * 10), 4)
    imrd = {f["w"]: f for (rom, _), f in recs.items() if rom == "span-imrd"}
    steady = (imrd[320]["clock"] - imrd[160]["clock"]) / (lines * 10)
    write16 = recs[("span-write", "b32-w16")]["clock"]
    out[("span-imrd", "port")] = {"port": "wire-bound" if steady <= WIRE_HALF_RCLK else "above-wire",
                                  "steady_half": round(steady, 2),
                                  "one_half_read": round((imrd[16]["clock"] - write16) / lines, 2)}
    return out


def vi_latch(recs):
    """kit-bus's frame-latch points read as bench:vi-frame-latch reads them (bench report.py), so the
    console and the fork's bench decide the same two categories: fetches (1 when the late V_VIDEO
    case's loads are nearer the no-write case's than the no-fetch case's) and vi_bank (the bank whose
    loads lose more after the late Y write)."""
    points = {pt: recs[("bus-vi", pt)] for pt in ("base", "vvideo-outside", "vvideo-outside-late")}
    points.update((pt, recs[("bus-vi-latch", pt)]) for pt in ("y-late-bank2", "y-late-bank3"))
    got = bench_report.derive("vi-frame-latch", points)
    return {("bus-derived", "vi-latch"): {"fetches": got["vvideo-outside-late"]["fetches"],
                                          "vi_bank": got["y-late-bank2"]["vi_bank"]}}


def repeat(recs):
    """kit-dma's single MI repeat writes: rclk per write from the N = 64 less N = 16 COUNT, 48 writes at
    4/3 rclk per COUNT tick (COUNT at half the 93.75 MHz PClock, RCLK 62.5 MHz), so ticks / 36."""
    out = {}
    for (rom, point), f in recs.items():
        if rom == "mi-repeat-write" and f.get("n") == 16:
            hi = recs.get((rom, point.replace("-n16", "-n64")))
            if hi:
                out[(rom, f"rc{f['rc']}-fit")] = {"rclk_per_write": round((hi["min"] - f["min"]) / 36, 4)}
    if not out:
        raise KeyError("mi-repeat-write")
    return out


def op_slope(recs):
    """kit-cpu's back-to-back operations: rclk per operation from the N = 64 less N = 16 COUNT, as repeat."""
    out = {}
    for (rom, point), f in recs.items():
        if rom == "op-slope" and f.get("n") == 16:
            hi = recs.get((rom, point.replace("-n16", "-n64")))
            if hi:
                out[(rom, f"{f['op']}-fit")] = {"rclk_per_op": round((hi["min"] - f["min"]) / 36, 4)}
    if not out:
        raise KeyError("op-slope")
    return out


DERIVED = [tex, zmem, cpu2, countw, bus, vintr, vi_latch, span2, hsync, repeat, op_slope]
