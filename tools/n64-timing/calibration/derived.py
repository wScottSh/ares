"""Derived metrics of the kit ROMs whose questions compare a fit or a difference, not a raw point.

Each function takes one log's records ({(rom, point): fields}) and returns {(rom, point): fields} to
add, or raises KeyError when the log lacks its points (kit.derive skips it). The points are named in
romgen/suites/calib/<module>.py.
"""


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
    """kit-zmem (written in place, after the zmem module's report): write-run fits over the Z comb, the
    per-primitive atomic cost, IM_RD/Z_CMP overlap, 1 px triangle cost, the clobber verdict, the X-bus
    and RDRAM command rates, the hold summary and PIPEBUSY's share of memory time."""
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
    for w in (8, 16, 24, 32, 48, 64, 96, 128, 192, 320):
        m = {k: p("slots", f"{k}-w{w}") for k in ("plain", "imrd", "zcmp", "imrd-zcmp")}
        if all(m.values()):
            a, b = m["imrd"]["clock"] - m["plain"]["clock"], m["zcmp"]["clock"] - m["plain"]["clock"]
            both = m["imrd-zcmp"]["clock"] - m["plain"]["clock"]
            records[("zmem-slots", f"overlap-w{w}")] = {"both_over_sum": round(both / (a + b), 3) if a + b else None,
                                                     "both_over_max": round(both / max(a, b), 3) if max(a, b) else None}
    for t in ("fill", "z", "shade", "shade-z"):
        lo, hi = p("tri", f"{t}-16"), p("tri", f"{t}-64")
        if lo and hi:
            records[("zmem-tri", f"{t}-setup")] = {"rclk_per_tri": round((hi["clock"] - lo["clock"]) / 48, 2)}
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


def bus(recs):
    """kit-bus: the AI rate from spans against the 1103-VCLK point (cancels the VI:COUNT ratio), per-load
    extra ticks under each bus client, the reorder difference, VI loads lost per fetch case, refresh
    hits per bank and the VI interrupt lag."""
    """kit-bus: the AI's power-on VCLK per sample (against the 1103-VCLK point, so the VI:COUNT clock
    ratio cancels), per-load slowdown under each RDRAM client, the SP DMA's slowdown from same-bank
    loads over other-bank loads (ri-reorder), VI fetch cost in loads lost per window, refresh hits and
    holdoff per bank, and the VI interrupt's mean lag."""
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
    v = recs[("bus-vintr", "v-intr")]
    out["vintr-mean-lag"] = round((v["sum"] - v["min"] - v["max"]) / (v["reps"] - 2) - v["bias"], 1)
    return {("bus-derived", "all"): out}


DERIVED = [tex, zmem, cpu2, bus]
