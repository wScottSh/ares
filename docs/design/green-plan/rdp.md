# Green plan: cluster rdp

Investigator: plan-rdp, 2026-10-09. Read-only against master 8d86b87cd (outputs equal calib-kit-merge/standing).
Scratch: worktrees /home/wscottsh/repos/ares-wt/plan-rdp (clean master) and plan-rdp-v (removed; its throwaway `ARES_PLAN_VARIANT` patch is results/plan-rdp/variants.diff, build kept at ~/n64-timing/build/plan-rdp-v). Builds ~/n64-timing/build/plan-rdp{,-v}. Private home ~/n64-timing/plan-rdp-home (ROMs rebuilt from master: thar0-rdp.z64 a01bcc95..., identical to standing; rdpstat-1prim 9acc05ef...; list in results/plan-rdp/rom-sha256.txt). Results ~/n64-timing/results/plan-rdp/.
Tools I wrote (rerunnable): results/plan-rdp/thar0/factors.py (per-line residual by factor, paired VI and bank contrasts), thar0/fit.py (OLS of residuals, diagnostic).
Labels: measured (I ran it), cited (file:line), inferred, guess.

## Diagnostic variants run (throwaway, reported, not adopted)

| id | change | thar0 mean abs residual | VI-off / VI-on | in band | other |
|---|---|---|---|---|---|
| v0 | master | 5.16% | 4.79 / 5.71 | 4 | byte-identical to standing compare.tsv (measured) |
| x1 | a span starts only after every earlier write-back landed (n64brew Set Color Image: "no such buffering across multiple rows") | **4.92%** | 4.57 / 5.43 | **6** (+ nozb-vioff/visame-noimrd-2cyc) | DUTY 80,295 (cen64 80,287); atomic-sweep 28.7 FAIL unless x33; filesel named 1.932 PASS, empty 1.148 FAIL, options 1.040 |
| x33 | x1 + 1PRIMITIVE dead cycles counted after the last write lands (ADR 0001's original "plus") | same as x1 (byte-identical) | | 6 | atomic-sweep 34.67 PASS, sync rect-interleaved points 58.8/41.7/33.9 (master 61.8/44.7/36.8) |
| x8 | x1 only for 2-cycle Z_CMP spans | 5.14% | | 4 | no help for 2-cycle Z |
| w16 | memory-port write waits for every read in flight | 5.09% | 5.31 / 4.76 | 5 | fixes zbr-pass-zbsep 1c (-89.8 to +13.4 rclk/line), breaks zbrw-pass-zbsep (-1.7 to +101.6) |
| v2 | no read prefetch while a span shades | 34.37% | | 5 | full serialization, far off |
| v4 | v2 only for 2-cycle Z_CMP | 17.77% | | 4 | 2c Z read-only 647.9 to 1097.6 rclk/line against hw 734.7: hardware is partly overlapped |

All numbers measured (results/plan-rdp/thar0/{v0,x1,x8,x33,w16,v2,v4}/compare.tsv, bench-x{0,1,33}.txt, fs-x1/filesel.txt). Load was 0.3-9 during thar0 runs, up to 29 during fs-x1 (timing-independent: emulated counts only).

## 1. Thar0 band (thar0:* rows, 96 of 100 configs outside hardware min..max)

**Current state (measured, standing).** 4/100 in band (the 4 alpha-fail compute-only anchors, exact). Mean abs residual of BUF avg 5.16% (VI-off 4.79%, VI-on 5.71%). Named checks: imrd-1cycle (cfg 2) +8.07%; nozb-visep-imrd-1cyc +4.05%; zcmp (cfg 86) +2.54%; ac-zbsame-vioff-imrd-1cyc +2.55%; ac-zcmp-zbsep-vioff-imrd-1cyc +2.43%; nozb-visame-noimrd-1cyc -4.91%; separate-bank (cfg 48) -0.19%; zbrw-fail-zbsame-visame-imrd-2cyc -4.68%; zbrw-pass-zbsep-visep-noimrd-1cyc -5.28%. Rule: model BUF inside hw min..max. Rows decided: rdp.mem-overhead-read/-write, rdp.span-read-latency, rdp.port-lookahead, rdp.span-slots, rdp.read-gate, ri.overhead-rdp, ri.arbitration. Basis of the three mem rows: fit (grid on the 60 VI-off mean, t13.md "Fit provenance").

**Reference strength.** Strong for the quantity: Thar0/RDP-Timing-Tests @a81ced93, one console (model unstated, Everdrive X7), 1000 runs per config, min/avg/max of DPC_BUFBUSY and PIPEBUSY, lone-FULLSYNC baseline +1 subtracted (cited, hardware-corpora.md row 1). Weak points: one rectangle size (320x240, 16 bpp), so per-line vs per-pixel and per-burst vs per-byte cannot be separated; console unconfirmed against the map target (no Expansion Pak stated). The band rule is very tight for VI-off configs (spread 0.06-0.12%, e.g. 163,436..163,654) so "in band" is close to "exact". Independence: every VI-off config fed the fit's mean; VI-on configs were not in the fit but are twins of VI-off workloads plus VI (verify-67 s.1). So no Thar0 config is a clean independent check of the three fit rows today.

**Root cause: the residuals are five separable mechanisms, not one** (measured contrasts, factors.py, per 320-px line, model minus hardware, rclk):

| Family | configs | residual | survives as |
|---|---|---|---|
| F1 write-only color | nozb-noimrd 1c/2c, all VI | -11.4 / -9.8 (VI-off), -13..-17 (VI-on) | **missing per-row write drain.** x1 (span waits for prior write-backs to land) gives -1.3 / +0.2 with no new parameter. cen64 dpc_probe DUTY-RECTN slope independently says 334.5 rclk/line (cen64 rdp_core.c:5346-5362: DUTY 80,287, RECTN 2,021.4; bracket cancels in the difference); master 324.0, x1 334.08 (measured). Reference: n64brew Set Color Image "for single rows span buffers are employed to alleviate stalls ... there is no such buffering across multiple rows" (cited, rdp-command-timing.md:141, rdp-pixel-timing-coupling.md:42). |
| F2 stream overlap rules, 1-cycle VI-off sep banks | imrd (+55), zbr-pass-sep (-90), zbw-sep (+5), zbrw-pass-sep (-2), zbrw-pass-sep-imrd (+96) | mixed sign | **wrong overlap structure, not wrong costs.** Hardware fits a serial sum per 64 B half with 4 values solved on 4 configs: single-stream read 44.2, read with a second read stream 34.7, write 28.9 (solved twice, from Zr+Cw and Zw+Cw: 28.9 and 29.0), write to an image also read 24.0; it then predicts Zr+Zw+Cw 97.1 (hw 94.0), Zr+Cr+Cw 93.4 (97.0), Zr+Zw+Cr+Cw 117.4 (117.0), Zw+Cw+Cr 97.2 (92.5) (inferred, hardware-only arithmetic). The model's per-op occupancies already equal these (read wire 10.5 + 21 + latency 12.5 = 44; write wire 9 + 19.5 = 28.5), so the error is in Port::eligible's rules: writes fill another image's read latency (Zr+Cw 64/half vs hw 73) and same-image order serializes RMW (73.6 vs 68.1). w16 shows a single rule fix moves one family and breaks another. No reference states the RDP memory interface's ordering. |
| F3 2-cycle Z read | every 2c config with Z_CMP: 13,17,37,41,53,57,61,65,87,95 (-11.8..-12.8%), 15,19,39,43,55,59,63,67,91,99 (-3..-7%) | -87 rclk/line on Z-read-only 2c; color-read-only 2c only -11 | **Z read in 2-cycle is partly exposed on hardware (734.7 vs compute 646), color read is not (659.0).** In 1-cycle both read-only cases are identical on hardware (441.7). Master overlaps both fully; v4 (no prefetch for 2c Z) serializes the whole 640 B read and overshoots to 1097.6. The model cannot express partial exposure because a span shades only after its whole window snapshot (up to SpanBytes = 4096 + 16, rdp.hpp:101) has landed. Hardware span RAM is 128 B per image (32 rows x 72 bits, color rows 0-15, Z rows 16-31: span-ram.md TL;DR, hw-cap) so hardware must stream a 640 B span through 2 halves. Why Z and not color: unknown (guess: in 2-cycle the Z half is also the second cycle's working storage, or Z compare sits later in the pipe). |
| F4 bank conflicts with writes | zbsame minus zbsep | hw +202..+366/line, model +94..+237 | under-modelled same-bank row turnarounds when writes alternate rows (ri.retry-dirty/clean, ri.post-write-gap, datasheet). Belongs with the RI rows. |
| F5 VI interaction under heavy RDP traffic | VI-on minus VI-off twins | hw +83..+245/line on zbrw-pass, model +31..+89; write-only hw +2..+6.5, model 0 | VI costs the RDP 2.5-3x the model when the RDP is memory-bound. Coupled to vi.* (lines per output line, vi-fetch-modes kit question) and RI. Not an RDP-only fix. |

A plain additive OLS of residuals on 13 traffic indicators explains only R2 0.64 (fit.py, measured): the residuals are structural (max/overlap), so refitting the three mem constants cannot reach the band and would be circular anyway.

**Coupling.** F1 fix (x1) moves every writing span: MM filesel named 1.694 to 1.932, empty 1.011 to 1.148 (fails), options 1.000 to 1.040 (measured); rdp-atomic-sweep 34.39 to 28.70 unless the barrier also changes (x33: 34.67); sync rect-interleaved report points drop about 3 rclk. F2/F3 changes move rdp.port-lookahead (sensitivity 1/8/16: 8.61/5.16/6.24%, t13-fix) and rdp.span-slots, and rdpstat:1prim (item 5). F4 couples to ri.* and nemu64 same-bank loads; F5 to vi.* and the VI cluster.

**Path to green.**
- U-rdp-1 per-row write drain (F1). Scope ares/n64/rdp/timed.cpp RDP::startSpan (start = max(pipe.time, slot.ready, last earlier write landed)), RDP::prefetch atomic barrier = max(lastWrite, lastSpanEnd) + rdp.atomic-dead, behaviors rows rdp.write-run note and a new rule row rdp.row-drain (basis wiki, n64brew Set Color Image), ADR 0001 reconciliation (supersedes deviation 3). Acceptance (measured on x1/x33 already): thar0 nozb-*-noimrd-2cyc in band; nozb-vioff-noimrd-1cyc within 0.5%; bench:rdp-rectn DUTY-RECTN slope 334.5 +-0.5% (promote to an asserted check, bracket-free); atomic-sweep 30-40 (x33 34.67); snapper 2592/2592 and rdpstat systemtest/dpc/unsynced/emux-bus 0 failed, 1prim 2/4 unchanged (all measured on x33); nemu64, det, stepcap, state round trip, MM wall not run here. Independent check: the cen64 DUTY-RECTN slope (console data, not Thar0), and Thar0 write-only configs, which no parameter was fit to after the change provided the mem constants are NOT refit. Risk: filesel empty fails (1.148); the unit must report it and not refit the per-byte overhead to rescue it (see item 7). Effort: half a day. Hardware: none needed to land; #16 rdp-rect-base confirms.
- U-rdp-2 literal span RAM halves (F3, also item 5). Replace the 4 KiB per-span window snapshot with 2 x 64 B halves per image (span-ram.md): reads stream per half, the pipeline waits only on the half it enters, a span's halves are read no earlier than buffer space allows, content is rendered per half from the bytes landed at that half's start. Scope timed.cpp (prefetch/startSpan/beginChunk/endChunk), rdp.hpp, engine window API (render per chunk, not per span), serialization. Acceptance: thar0 2c Z read-only family residual |res| < 3% with no new parameter; rdpstat:1prim cases measured and reported (expected fresh at 32 px only if the half/lead structure gives it); snapper 2592/2592; mem_misses 0. Independent check: the 2c Z family (F3) was never fit by anything; rdpstat:1prim. Regression risk high (render per chunk, det, wall time). Effort 2-4 days. It also resolves the ADR deviation "halves never stall" against its own reference (span-ram.md). Needs no hardware to build; #16 span-width / imrd-zcmp-slots decide the details. Guess: it will not by itself explain why color and Z differ in 2-cycle (F3 asymmetry); that needs the new 2-cycle kit point below.
- U-rdp-3 kit gap: add a 2-cycle Z_CMP and IM_RD width sweep (8-line rects, 8-320 px, 16 bpp, Z all pass no update, and all fail) to romgen/suites/calib/zmem.py next to imrd-zcmp-slots (all its points are 1-cycle, zmem.py:22 PLAIN = CYC_1CYCLE) and a questions.tsv row closing rdp.span-read-latency / F3. Effort 2 h. Without it #16 cannot decide F3.
- F2, F4, F5: no reference-backed fix. Honest end state until #16: report the residual per family, keep rdp.port-lookahead labelled fit with verify-is-fit. #16 questions that decide them: imrd-zcmp-slots (F2), span-width (read latency, F2/F3), thar0-console (all), ri-reorder and ri-priority (F4), vi-fetch-modes and vi-cpu-contention (F5).

**What not to do.** Do not regrid rdp.mem-overhead-read/-write/span-read-latency or rdp.port-lookahead on Thar0 again after a structural change and call Thar0 a check (pref 21). Do not widen the band to "within 2%": the hardware spread is the honest tolerance. Do not add per-config-family fudge terms (2-cycle Z penalty constant) without a reference: v4 shows the effect is structural.

## 2. thar0:fill-mode (report-only)

State: pending:report-only; no Thar0 fill config (cited, checks.tsv). Reference: SDK 12.1.4 8 B/rclk (vendor, no measurement). The kit question fill-copy-rate records the fork at 6.69 B/clk at 16 bpp, 6.44 at 32 bpp (cited, questions.tsv). Root cause of the gap to 8: per-line costs (dead pixels, line gap, and from U-rdp-1 the row drain) on short fill lines (inferred). Path: none without hardware; #16 kit-tex tex-derived fill-b16/b32-bytes-per-clk decides. Honest end state: report-only until #16. Do not tune the fill rate to 8 B/clk effective.

## 3. bench:rdp-loadsz-sweep (report-only)

State: no ROM exists (checks.tsv: "no ROM in plan R1 yet"; bench run.sh fails "missing bench-rdp-loadsz-sweep.z64", measured). The two references conflict: MiSTer RTL 8 B/rclk vs jgemu dpc_probe LOADSZ about 15 + 0.418 clk/B (reverted by its author for methodology doubts, jgemu-dpc-probe.md). The fork's effective cost is 0.703 clk/B + 7 (cited, questions.tsv tmem-load-rate) because T13 makes loads pay span-read memory costs, so rdp.tmem-load-rate's 8 B/rclk value no longer describes what the model does (inferred from the two cited numbers). Path: (a) a label unit: rdp.tmem-load-rate note states the effective rate and that loads are memory-bound by assumption (t13.md deviation 3); (b) point bench:rdp-loadsz-sweep at the kit-tex load points (they exist in tex.py) instead of a separate ROM. Green needs #16 questions tmem-load-rate, tmem-load-setup, loadtile-rows. See item 7 for whether the load law matters for filesel.

## 4. bench:rdp-rectn (report-only)

State: RECTN 320x6 2,069 (cen64 2,021), DUTY 320x240 77,885 (cen64 80,287) (measured). Reference: cen64 commit 0f388bb/30c2459 numbers from dpc_probe on a console, bracket unstated, VI blanked, min-of-8 (cited, jgemu-dpc-probe.md, rdp_core.c:5346-5362). The absolute values depend on the unstated bracket (where timing starts and stops), so they cannot be asserted. The difference DUTY-RECTN (234 lines of 320 px) cancels the bracket: 334.47 rclk/line on hardware, 324.0 on master, 334.08 under x1 (measured). Path: U-rdp-1 promotes the slope to an asserted check (bench:rdp-rectn-slope, tolerance from cen64's stated 2021.4 vs 2021 fit, about 0.3%); the absolutes stay report-only until #16 rdp-rect-base.

## 5. rdpstat:1prim (2/4, 32 px stale)

State: 1- and 2-cycle 32 px non-atomic stacks retire the two-blend (stale) value; expectation is four-blend (fresh) (measured, standing). Reference: cen64 jgemu rdp_core.c:4584-4601 (comment above rdp_fill_rect_stale_read; checks.tsv cites 4551-4567, which at 2f8d7bc is unrelated tile code, so the citation needs fixing): adjudicated against "PRDP 12:15 and 12:16" checksums; commit e6b58c6 ("passing the N64 Diagnostic cartridge") shows PRDP is the RDP section of Nintendo's diagnostic cartridge (cited). So the 8 px stale and "wide stacks fresh" shapes rest on Nintendo hardware-golden checksums: a real but indirect hardware reference. The 32 px width is not: the comment says "wide (D <= L)" with D = min(3L-2, 25), so fresh is cen64's fitted threshold (>= 25 px) applied at 32 px; the diagnostic cart's actual widths are not public. Verdict: the 8 px rows are hardware-backed via cen64; the 32 px rows are cen64 extrapolation.
Root cause (measured): the model reads stale at every width I tried, 8 to 256 px in both cycle modes (20-case sweep, results/plan-rdp/stale-width-sweep.txt: 14/20 fail, all widths >= 32). So this is structural, not a threshold: the next primitive's whole span window is read before the previous span's write-back lands (whole-span snapshot, item 1 F3). Hardware with 128 B of span RAM per image cannot do that for a wide span.
Path: U-rdp-2 (literal halves). Acceptance: report the stale/fresh boundary width the structure produces, without tuning it to 25. Independent check: #16 stale-read (kit rdpstat-1prim on a console) decides 32 px; for no-hardware green, relabel the 32 px rows "cen64 extrapolation" (expect=self, weak) and keep them failing until U-rdp-2 or #16, or move them to report-only. Do not reinstate cen64's D = min(3L-2, 25) hack.

## 6. mm:south-clock-town (report-only)

State: 3.0000 fields per game frame, 1,708,022 RSP busy clocks per field (cited, results.tsv). No hardware value. MM gameplay runs at divisor 3, so 3.00 only shows the model is not too slow (inferred). Path to an asserted check: measure SCT cadence on capture U or W the way mm-filesel-slowdown.md did (W already shows 20 fps gameplay, 408/428 intervals at 3 capture frames, cited); a research unit, 2 h, no hardware. Honest end state otherwise: report-only.

## 7. mm:filesel-named (1.6941, band 1.90-2.10, >= 90% at 2), the map #1 acceptance row

**Current state (measured, standing).** mm:filesel-named mean 1.6941, 69.4% of 353 game frames at 2 fields; band 1.90-2.10 with >= 90% at 2. Partners: mm:filesel-empty 1.0113 / 98.9% at 1 (pass, <= 1.05 and >= 95%), mm:filesel-options 1.0000 (pass). Rows decided: rdp.mem-overhead-read/-write (empty and options are their fit-from: per-byte vs per-burst was chosen on them, t13.md), rdp.span-read-latency. Named is the only independent row.

**Reference strength.** Named: one hardware recording (capture W, 19.95-21.50 s, cursor-pulse triangle fit 2.00, range 1.96-2.04, residual 193x worse at 1.0 and 79x at 1.5); empty: capture U, 0.991 spectral / 1.02 fit (cited, mm-filesel-slowdown.md). Rig details undocumented, one capture per state. It is a sound frame-cadence observation, not a timing measurement; it constrains the frame cost only to "named above one field, empty below".

**Root cause (measured by the delegated profiling run, results/plan-rdp/filesel/, knobs-off build bit-exact with master).**
- The RDP is the critical path: RDP busy 15.4-15.5 ms of TV (retrace to SYNC_FULL) in named, about 92%. CPU delivers display lists >= 9.8 ms early (one empty-file outlier). RSP gfx 2.3 ms. Memory stall plus interface overhead is about 60% of RDP busy (compute 6.1 ms).
- Frame-to-frame jitter is audio: the audio task yields gfx about 0.2 ms into the frame and the RDP runs dry for the audio RSP time (1.6-1.8 ms); corr(T, audio) 0.8-0.9. This is MM's scheduler on hardware too (mm-rdp-stream.md rules 4, 7, 8, cited), so the jitter's size depends on the RSP audio timing (another cluster's rows).
- Distributions: empty TV p10/p50/p90 15.49/15.98/16.36 ms; named 16.48/16.79/17.35; the boundary is about 16.65-16.69 ms. Empty's high tail and named's low tail are about 0.1 ms apart, against about 1.5 ms of audio jitter.
- What named adds over empty: triangles 153 to 223 (+46%), spans +14%, pixels +1.7%, TMEM loads +22%, setters/syncs +20%; options has as many loads/setters/syncs as named and more load bytes, and survives only on 1.07 ms of slack. Triangles are the only feature with named >> empty > options.

**Every single mechanism tried fails at least one primary row (measured, mean and % at target).**

| Variant | reference | empty | options | named |
|---|---|---|---|---|
| uniform RDP scale 1.02 / 1.04 / 1.07 | none | 1.030 / 1.101 / 1.223 | 1.000 / 1.012 / 1.072 | 1.787 / 1.895 (89.5%) / 1.974 |
| x1 row drain (U-rdp-1) | n64brew Set Color Image | 1.148, 85.2% FAIL | 1.040 | 1.932, 93.2% PASS |
| per-burst share of mem overhead 0.10 / 0.15 | none (t13 tried) | 1.062 / 1.117 FAIL | 1.000 | 1.843 / 1.932 |
| jgemu TMEM law as extra command-processor time | jgemu dpc_probe (reverted by author) | 1.796 FAIL | 1.798 FAIL | 2.000 |
| jgemu TMEM law as total load time | same | 1.000 | 1.000 | 1.213 (model already slower per load) |
| setter 2.68 rclk | jgemu (reverted) | 1.018 | 1.000 | 1.696 |
| cen64 span law (12/span + 14/prim) | cen64 dpc_probe | 1.039, 96.1% | 1.000 | 1.798 |
| +150 / +170 / +200 rclk per triangle | none ("Triangle setup: no measured or vendor number", rdp-command-timing.md:150) | 1.052 / 1.064 / 1.085 FAIL | 1.000 | 1.877 / 1.907 (90.7%) / 1.961 |
| +120 per load, +150/+300 per primitive | none | all fail one row | | |

Phase spread (pref 27, measured with a pre-title wait of 1/4/9/17 frames): base named 1.6864-1.6941, empty 1.0113-1.0181; at +150/triangle empty flips 94.8% to 95.6% with phase alone. So any variant that lands near the empty edge is not decidable from one bench run.

**Surviving hypotheses (ranked).**
1. The empty/named gap on hardware is larger than the model's 0.8 ms median because a per-triangle (or per-span-on-short-spans) cost is missing (inferred from which feature separates the scenes; the nearest single miss is +170 rclk/triangle, unreferenced). Discriminator: #16 triangle-setup (many 1 px triangles) and mm-filesel (console RDP time per frame on both screens).
2. The model's frame-time jitter (audio-driven RDP starvation) is wider than hardware's, so tails overlap that do not overlap on hardware (guess). Discriminator: #16 mm-filesel per-frame DPC_CLOCK distribution; RSP audio timing rows in the RSP cluster.
3. The memory term is mis-structured (item 1 F2/F3), and once U-rdp-1 and U-rdp-2 land the scene balance changes (inferred).

**Coupling.** Every RDP row moves both scenes; the empty and options rows are already fit data for the per-byte choice, so tuning anything to pass them is circular. RSP audio timing and the scheduler/yield path move the jitter.

**Path to green.** No reference-backed single mechanism exists today (measured). Plan: (a) land U-rdp-1 and U-rdp-2 on their own references and report filesel as it falls, without refitting anything to filesel; (b) re-run the three rows with a phase sweep (the subagent's mmbench_phase.py wait-N copy in results/plan-rdp/filesel/ should become an mmbench option, so pref 27 is met for this check); (c) green only via #16: kit questions mm-filesel (decides whether hardware's named frame is RDP-bound and by how much, and empty's margin) and triangle-setup (decides hypothesis 1). Acceptance stays the doc's two primary rows. Effort for (b): 2 h.

**What not to do.** Do not add a per-triangle or per-primitive constant to hit 2.00 (no reference; pref 7). Do not switch per-byte/per-burst or the split again on filesel data. Do not loosen the 1.90 or 95% bars: they come from the capture analysis.

## 8. Issue #86 (hazard tail keeps first-pass pixels when the new state rejects them)

State: z_mode decal to opaque gives 27/13 px (n64brew table), opaque to decal 0/0 where the table predicts 27/26 (cited, issue #86). Root cause (cited code, read): rdp_haz_publish (engine/rdp_core.c:306-369) renders the whole primitive with the old state (line 322), then re-renders each tail with the new state; a tail whose new state rejects pixels writes nothing, so the old pixels stay. The same mechanism double-blends IM_RD tails (T15 follow-up). Reference: n64brew Pipeline "Effect of unsynced attribute changes" (wiki). Path: U-rdp-4: render disjoint ranges: old state for [first pixel, first landing), each later state from its landing to the next. Scope rdp_haz_publish only. Acceptance: kit-tex z_mode opaque-to-decal tail 27 (1-cycle) / 26 (2-cycle) per the table, decal-to-opaque unchanged, rdpstat unsynced 2/2, repeater64 20/20, snapper rect-nosync 20/40/20, MM fb_hash diff reported (timing columns identical expected, since write/pixel counts are counted per pass: check). Independent check: none without hardware (wiki table only); #16 attribute-stage decides. Effort half a day. No circularity.

## 9. rdp.* fit rows

- rdp.mem-overhead-read 21, -write 19.5, rdp.span-read-latency 12.5 (fit, VI-off mean grid). Their per-op values match hardware's own serial sums (item 1 F2: read 44 = 10.5 + 21 + 12.5, write 28.9 vs 9 + 19.5). That agreement is not independent (same data). Green only with #16 span-width (read latency and per-byte vs per-burst, which is also the filesel per-byte choice) and imrd-zcmp-slots. Honest end state now: fit only.
- rdp.port-lookahead 8 (fit, verify-is-fit). Encodes F2's overlap rule. No reference. Fit only until #16 imrd-zcmp-slots; U-rdp-2 may change or delete it (the eligible rule is what F2 says is wrong).
- rdp.span-slots 4 (model-choice). Bounds run-ahead; Thar0-insensitive (4.96/5.16/5.16% at 2/4/8). U-rdp-2 replaces it with the span RAM capacity (cited 128 B per image), which removes an unreferenced parameter (pref 7).
- rdp.primitive-base 13 (fit, verify-is-fit, Thar0 alpha-fail). Independent check possible only from cen64 RECTH "first-span vs added-span offset" 14 incl. 2-word fetch (cited) whose bracket is unknown; #16 rdp-rect-base decides. Fit only.

## Dependency order

1. U-rdp-3 (kit gap, tools only) and U-rdp-4 (#86) are independent, first.
2. U-rdp-1 (row drain + atomic barrier) next: smallest structural change, reference-backed, moves item 4 to an asserted pass and item 1 F1 into band.
3. Item 7: phase-sweep option for mmbench, then re-measure after U-rdp-1 (x1 measured: named 1.932 pass, empty 1.148 fail) and again after U-rdp-2.
4. U-rdp-2 (literal halves) after U-rdp-1: changes F3, item 5, rdp.span-slots, maybe port-lookahead. Re-measure item 7.
5. Label units for items 2, 3, 5, 9 can ride along.

## Can go green without hardware

- bench:rdp-rectn slope (new asserted check) via U-rdp-1: measured 334.08 vs 334.47.
- thar0 write-only configs nozb-vioff/visame-noimrd-2cyc via U-rdp-1 (measured in band); the 1-cycle ones to within 0.4% (not in band: 80,176 vs 80,462..80,562).
- Issue #86 against the wiki table (weak reference; the issue's own acceptance names hw:attribute-stage).
- Thar0 2-cycle Z family likely to |res| < 3% via U-rdp-2 (guess; not run).

## Only with #16 (kit question that decides)

- mm:filesel-named: mm-filesel and triangle-setup.
- Thar0 F2 overlap rules: imrd-zcmp-slots, span-width; whole band: thar0-console.
- Thar0 F3 2-cycle Z asymmetry: the new U-rdp-3 point (not in the kit today).
- Thar0 F4: ri-reorder, ri-priority. F5: vi-fetch-modes, vi-cpu-contention.
- rdpstat:1prim 32 px: stale-read.
- thar0:fill-mode: fill-copy-rate. bench:rdp-loadsz-sweep: tmem-load-rate, tmem-load-setup, loadtile-rows.
- rdp.mem-overhead-*, span-read-latency: span-width. port-lookahead: imrd-zcmp-slots. primitive-base: rdp-rect-base.

## Honest end state is a reclassification

- rdpstat:1prim 32 px rows: "cen64 extrapolation" (weak, expect=self), not a hardware expectation.
- bench:rdp-rectn absolutes: report-only (unknown bracket); only the slope is assertable.
- thar0:fill-mode, bench:rdp-loadsz-sweep, mm:south-clock-town: report-only until #16 (SCT can become an asserted coarse check from the existing captures).
- The Thar0 "in band" rule for VI-off configs is effectively exact match; keep it, but report mean abs residual per family (F1-F5) as the progress metric so a structural fix is visible.
