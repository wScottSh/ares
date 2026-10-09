# Review: green-plan.md (adversarial, read-only)

Plan = /home/wscottsh/repos/ares-wt/green-plan/docs/design/green-plan.md (cited as P:line, numbering of `cat -n`). Appendices: bus/pisi/rdp/pending .md (B/PI/R/PE:line). Ground truth: master results tsv, behaviors.tsv, checks.tsv, standing run. Labels: [V] I re-ran or re-read the source; [I] inferred.

## Ranked findings

### S1 (high) U-RDP-DRAIN turns none of the 10 failing thar0 checks green; plan says "green without hardware"
- P:115 "thar0 write-only configs (F1) ... green without hardware"; P:166 "Thar0 in-band 4 to at least 6"; P:233 P2 "a few Thar0 configs come into band".
- [V] The "in band" counts are configs in compare.tsv, not checks. The results tsv has 13 thar0 checks (10 fail). The F1 check, thar0:nozb-visame-noimrd-1cyc, reads 77772 on master and 80857 under x1/x33 against hw 81654..81868 (results/plan-rdp/thar0/x1/compare.tsv). Still -1.0%, still fail. The two configs that enter band (nozb-vioff/visame-noimrd-2cyc, R:13) are not checks. R:133 itself says the 1-cycle ones stay out of band.
- [V] The other 9 are unaffected by x1 (e.g. zbrw-pass-zbsep-vioff 225260 -> 225273; imrd 176749 -> 176833; zcmp/ac-* byte-identical).
- Net of U-RDP-DRAIN on the 28: 0 checks green, 1 new check (rdp-rectn slope), 1 passing MM row broken (R1).
- Fix: rewrite P:115, P:166, P:233 to "improves nozb-visame-noimrd-1cyc from -4.9% to -1.1% (still fail); adds bench:rdp-rectn-slope; no named thar0 check goes green". Add a per-check thar0 mapping table (S2). Adopt R:152's metric (mean abs residual per family F1-F5) as the Thar0 progress report.

### S2 (high) The 10 named thar0 checks are never mapped to F1-F5; two have no mechanism in rdp.md
Mapping from rdp.md (compare.tsv numbers [V]):
| check | resid | mechanism |
|---|---|---|
| thar0:imrd-1cycle (cfg 2) | +8.07% | F2 |
| thar0:nozb-vioff-imrd-1cyc | +8.07% | F2. Same config as imrd-1cycle (checks.tsv:91): a duplicate check |
| thar0:nozb-visep-imrd-1cyc | +4.05% | F2 + F5 |
| thar0:ac-zcmp-zbsep-vioff-imrd-1cyc | +2.43% | F2 (imrd) |
| thar0:separate-bank (zbrw-pass-zbsep-vioff-noimrd-1c) | -0.19% | F2 (R:32 lists -2 rclk/line). Fails because the VI-off band is 0.12% wide |
| thar0:zbrw-pass-zbsep-visep-noimrd-1cyc | -5.28% | F2 + F5 |
| thar0:zbrw-fail-zbsame-visame-imrd-2cyc | -4.68% | F3 (2-cycle Z_CMP) + F4 + F5 |
| thar0:nozb-visame-noimrd-1cyc | -4.91% | F1 + F5. Stays fail after F1 |
| thar0:zcmp (ac-zcmp-zbsame-vioff-noimrd-1cyc) | +2.54% | UNMAPPED. 1-cycle Z-read only, not in F1-F5 |
| thar0:ac-zbsame-vioff-imrd-1cyc | +2.55% | UNMAPPED. Alpha-compare + IM_RD, same model value (108697) as zcmp |
- Plan P:81 and P:116 say F2 drives "Z read with color write (-12%)". rdp.md assigns -12% to F3 (R:34), and no named check is at -12%. Fix the attribution.
- Three failing thar0 checks (ac-zbsame-vioff-imrd-1cyc, nozb-vioff-imrd-1cyc, ac-zcmp-zbsep-vioff-imrd-1cyc) belong to no behaviors.tsv row [V]. They block no row, which is why a row-based "all 33 failing rows covered" check misses them.
- Fix: add the table above to P:3 (split the P:115-118 rows per check). Tell the reader zcmp and ac-zbsame-vioff-imrd-1cyc need either an F-family assignment from the investigator or an honest "unexplained, #16 thar0-console".

### S3 (high) U-DRAIN's "independent checks" are not independent; "green" must be labelled fit-only
- PI:40-48: W=100 is the intersection of the pass windows of pi-io-w (76..128), si-io-w (>=100), si-dma-w-rom (60..108), si-dma-w-ram (<=108), pi-dma-128 ({80,88,92,100,108}). The lower bound 100 comes from si-io-w and pi-dma-128. All five were used to choose W.
- P:164 says fit from pi-io-w and si-dma-w-rom (copied from PI:122, which contradicts PI's own table) and lists si-io-w, si-dma-w-ram as "independent". They are not. P:101-104 call all four "green".
- The only independent datum is pidma:logs (PI:82), which is a broad 84..108 window. Under pref 21 these checks pass by construction.
- Fix: P:101-104 and P:164 end state "pass, fit-only: window-selected; independent confirmation = pidma:logs + #16 register-write/wb-drain-target". fit-from = all five. Spec row sysad.register-write goes model-choice -> fit and no check outside fit-from may be called verification.
- Also note knife-edges (PI:112-147, 54-58): pi-dma-128 passes at W=88/92/100/108 but fails at 96/104 (1595/1596). si-io-w passes at 0.185% against a 0.2% rule.

### S4 (high) SOFTWARE_READY is unreachable by construction, and P:50-57 reads as a promise
- P:52 "the best reachable state is SOFTWARE_READY with these residuals still open". P:20-24 require no fail/consistent-only/pass-conditional and no report-only. P:237 says it "stays false after P4". Contradiction.
- Even after every unit, #77 pass-conditional and 11 report-only checks (joy x3, read64 x3, dirty x2, rdp-rectn, south-clock-town, and so on) remain (P:121-126), plus failing memset/nemu64/thar0/PI DMA 8/file select.
- Fix: replace P:52 with "Without hardware SOFTWARE_READY stays false. The reachable state is 'software-complete': every unit landed and every residual names its deciding kit question." Report SOFTWARE_READY as a count (n of m clauses) not a state. Or rename the clause set.

### S5 (high) Predicted-outcome table (P:224-237) is arithmetically wrong and optimistic
- 28 -> P0: relabels are 3 checks (sp-dma-sweep, pi-dma-sizes, pi-dma-sizes-8) = 25. The dead checks are pending, not in the 28 (P:229 "about 24").
- P2: U-DRAIN greens 4 (pi-io-w, si-io-w, si-dma-w-rom, pi-dma-128) = 21. U-RDP-DRAIN greens 0 (S1). D5's default "every point" leaves pidma:logs failing (PI:206-207: ~19 scattered points remain). Plan says "about 18" (P:233).
- P3 "about 15" (P:234) has no basis: R:44 says U-rdp-2 improving the 2c-Z family is a "guess; not run", and only 1 of the 10 named checks is 2-cycle Z (plus F4/F5 terms).
- Honest: 28 -> 25 -> 25 -> 21 -> 21 (P3 unknown). Also say that P0 removes 3 fails by reclassification, not by fixing (the 5 rows sp.dma-burst, ri.octbyte, ri.post-read-gap, ri.post-write-gap, ri.overhead-read fail only through sp-dma-sweep [V] and drop to pending).
- Add the possible regression from S6.

### S6 (high) Untracked failing point and an unlisted U-DRAIN regression risk
- [V] standing/bench.txt: `fail mi-memset-repeat vi-on ms_per_mib 1.31 (expected 3.8)`, a hardware-referenced point (expected.tsv:8, `check`) that is in no results-tsv row (grep: none in checks.tsv or results tsv). The "28" omits it. P:164 mentions it only as "(already failing)". U-DRAIN moves it to 2.18, still -43% (PI:114).
- Fix: wire it into checks.tsv (or mark report with reason) in U-LBL; add it to P:3; treat the remaining 2.18 vs 3.8 as an open datum against the "W is right" story. It shares the n64brew table with q20.
- [I] mi-memset-rspdma: pisi mean 6.498 -> 6.494 at W=100 (PI:114). Band floor 6.49; at layout pads 4-6 the master mean is already 6.491 (PE:176). So U-DRAIN likely lands 6.487 at those pads, a conditional pass becoming a fail. Not in P:164 risks. Fix: add to the risk cell, and run U-LAYOUT before judging (already P0).

### S7 (med-high) D6 and R1 make the "no hardware" Thar0 gain conditional, and the chain behind it stalls
- P:169 "land behind D6" versus P:248 default "do not land". By default U-RDP-DRAIN never lands, so bench:rdp-rectn-slope (P:125), U-SPANRAM (P:216 "after U-RDP-DRAIN") and P:233 are blocked.
- The R1 baseline (empty 1.148, named 1.932) was measured on master before U-DRAIN (R:13). Plan does not order U-DRAIN before U-RDP-DRAIN.
- Fix: in P:222 state "U-DRAIN, then re-measure R1 baselines, then U-RDP-DRAIN". Say U-SPANRAM can be developed on a branch with F1 applied but cannot land until D6 resolves. State the default outcome (F1 unlanded) in P:233.

### S8 (med) Circularity and reference-strength problems in U-RDP-DRAIN / U-ROWEND / D5
- U-RDP-DRAIN (P:166): the F1 mechanism was identified from the Thar0 write-only residuals and chosen among 7 variants against Thar0 (R:10-19). "Thar0 write-only configs" are then called an independent check. Only the cen64 slope is independent. Also the bracket-cancel in DUTY-RECTN (334.47) is [I] (conditions unpublished, P:258 itself says so), and "n64brew: no buffering across multiple rows" is cited text but the rule "span starts after earlier write-backs land" is an interpretation. P:80 labels the combination as cited/measured. Fix: label the rule inferred; list Thar0 as "selection data" and cen64 slope as the one independent check, tolerance derived per R:60.
- U-ROWEND (P:165): fit from the 0x7fe golden points and "check" on 0x7fc/0x7fa/0x7f8 from the same logs that pidma:logs then scores; PI:201 says the mechanism itself is undecided (masked burst vs "+21/+6" terms never measured). One-point fit = invented parameter (pref 7). Fix: scope as "find a referenced mechanism; if none, record as not built and leave the row-end points failing/excluded". Acceptance must be PI:203 (0x7f8..0x7fe within +-3% at every size, no other offset moves).
- D5 (P:247): a "stated count" chosen after seeing ~23990/24000 is a post-hoc band. Require the rule to be fixed now: "every point within the golden min..max +-3% and ROM self-check 0 failures" (PI:207), or derive the count from the hardware 8-run spread.
- U-NEMU-PHASE (P:144): fix the pass rule before running (phase-mean in hw +-0.5 and median rule). "Any phase passes" would be a widening.

### S9 (med) Headline pidma figure omits the ROM-cap confound
- P:72 "23765 to 23960". PI:78: at W=60 the ROM hits its 8-failure cap and drops to 1 run/point, so part of the jump is ROM averaging. Only the like-for-like 4512-point subset counts (fails 24 -> 2 at W=100, 0 at 84/92). The plan quotes that subset's window but headlines the confounded number.
- Fix: P:72 give the subset fails (24 at W=60, 2 at 100, window 84..108) and drop 23960 as evidence. Also add PI:126 acceptance (pidma >= 23950 and ROM self-check <= 1) to U-DRAIN; W=108 gives SUCCESS but PI DMA 8 198..200. State the 100 vs 108 vs 9 rclk choice (PI:121).

### S10 (med) Dropped appendix recommendations
1. bus.md:295 / :238 model-side refresh-cost trace (hpos holdoff 74.67 vs 52/54 rclk; systembench +3 under refresh-at-blank). The one no-hardware step that could expose a model defect. Not in any unit. Must precede any refresh-at-TYPE=0 decision. Add as P1 unit U-REFRESH-TRACE.
2. bus.md:274 ROMs for bench:ifill-isolated and wb-fifth-store (report kind) versus pending.md:129-130 delete. P:123 says "delete or give them ROMs", U-DEAD says delete. Pick one (pending's argument: kit points already measure them) and say you overruled bus.
3. rdp.md:52,56 thar0:fill-mode and rdp-loadsz-sweep: keep as report / retarget at kit-tex and add the rdp.tmem-load-rate note (effective 0.703 clk/B + 7). pending.md says delete. U-DEAD deletes; unmentioned conflict.
4. pisi.md:226-231 rdpstat:current-prefetch: wire guard to kit reading. pending: delete. Plan silently deletes.
5. rdp.md:70 mm:south-clock-town: no-hardware coarse check from existing captures (W, 408/428 intervals). P:126 says "stays report-only until hardware".
6. pisi.md:205 exclude pidma:logs sizes 305-352 (cart page-phase mismatch) -- U-PISIZE adds a kit question (P:184) but no exclusion unit; pidma:logs will keep scoring a mismatched condition.
7. pending.md:254 U-LBL items missing from P:140: fix sysad-frozen-step note, drop pending:no-corpus where a kit question exists, mark joy-empty-56b/63b not deciding skip/escape, strip comments in code-read test, closure-draft third class "charged with no hardware reference", scheduler.tie-rank/ri.request-latency/vclk-pal reclassification.
8. pending.md:123-127 pre-run rule hygiene: derive vi-first-line abs:24 tolerance from the fork's 8-delay spread, count-per-field rel:0.01% vs crystal tolerance, nemu64-console exact rule on range-valued cases, cmd-fetch-burst "8 vs 16 phases" text, thar0-console cross-binary compare (port --hw hang unexplained). All "derive tolerance first" (P:259) work; no unit.
9. pending.md:252 U-MMR may use a pinned commit instead of waiting for D3. P:186/245 makes it wait on the merge.
10. rdp.md:43 / R:44 acceptance lines: U-86 should require unsynced 2/2, repeater64 20/20, snapper rect-nosync 20/40/20 (P:154 only snapper 2592); U-82 acceptance rsp_halted + rsp_cycles = frame span (P:155 "non-zero" is a proxy); U-RDP-DRAIN/U-SPANRAM should require det, stepcap, state round trip and MM wall (R:43 did not run them). Fix rdpstat citation rdp_core.c:4584-4601 (checks.tsv cites 4551-4567).
11. bus.md:323 contingency: if #16 shows no VI tail and no referenced mechanism, VI cost is "not built" (map ruling). No decision or note.
12. pisi.md:183 licence: pi_dma_test has no licence; no modified ROM may be built/committed. Plan's P:184 U-PISIZE and any pidma capture must be new code/ROM.

### S11 (med) Ordering and coupling errors
- U-WALL is P0 (P:146) but the 120 s budget is re-timed before U-DRAIN, U-RDP-DRAIN, U-SPANRAM (R:175 "wall time" risk). Add a closing re-time after the last model-output unit, and det/stepcap/state round trip.
- P5 gated on P3/P4 serially (P:212-218). The console run needs only P0, P1 (U-84, U-87, U-86 so known defects do not spend console answers; PE:105,109,118) and the P4 kit additions. U-SPANRAM (2-4 days, high risk) need not delay the run. Make P3 parallel with P4/P5.
- U-HIST (P:181) says histograms for "q34 and q44". Per bus.md:299 the per-load histogram goes in q24 (vi-cpu-contention) ingest; D_HIST in q34. Fix to "q34 and q24".
- U-DRAIN changes MM output (md5, PI:115) but acceptance omits mmbench filesel rows and MM wall (PI:128 "measure filesel-named").
- Memset coupling: bus says memset needs q24 then q20 and "do not refit"; U-DRAIN should state memset-uncached/cached values before/after (pisi lists only rspdma, repeat, sp-dma). Add: "mi-memset-cached/uncached unchanged or explained".

### S12 (med) Reclassification and "green" wording that over-reads
- rdpstat:1prim (P:119): "reclassify 32 px as cen64-derived" leaves the check live. If U-SPANRAM makes 32 px fresh, the check goes green on a fitted cen64 threshold (R:64). Fix: move 32-px rows to report or give them pass-conditional with the reason; only 8 px counts toward green. 8 px stale already passes.
- pi-dma-128 (P:104): "P2 re-solve labeled fit" is not in any unit and contradicts P:252 and PI:162 (do not refit pi.block-writeback before U1; U-DRAIN alone passes it). Delete "then P2 re-solve".
- pidma:logs Now column (P:106) quotes the invalid calibrated range 23776..23833; PI:210 says report the exact 23765.
- bench:pi-dma-sizes reclass (P:107) is correct; add that pi-dma-8 stays fail through systembench.

### S13 (low) Fidelity nits
- P:64 "+2..+3" systembench shift; bus says +1..+3 (B:233) and u32r-seq/rand 136..137 vs 134.
- P:84 "(measured)" tags: B:80-96 labels row-miss/tail attribution [M + I]. The "VI waits, not row misses" is inferred from 2-run averaging. P:65 and P:72 bullet headers should say measured + inferred.
- R:33 F2 prediction error is up to 5.1% (97.2 vs 92.5), not "within 5%" (P:81).
- P:82 "must stream reads through two halves" is [I] (128 B is the cited fact).
- P:127 "80 hw:* checks | section 5" should point to P5 (section 4). No per-check disposition for the 80: add the readiness class R1/R2/R3 and predicted-F list (PE:71-119) or link it.
- P:91 vs PE:121: "65 / 11 / 4" is right (65 R1 + 11 R2 = 76).
- Counts verified [V]: results 87/23/4/1/80/14/1; 28 weak-or-failing; 33 failing rows; 7 excluded + 9 out-of-kit; 14 report-only listed. All 28 non-green checks appear in section 3.

### S14 (med) Missing decisions for Scott
- D7: Console prerequisites for #16 R2 items: 4 controllers + second run, reset run, phase builds, operator libdragon builds of Thar0 a81ced93/snapper64, USB/SRAM for 26-30 KB noise logs, systembench era binary fd5ec6c0 (PE:79-116). P5 lists none.
- D8: Approve reclassifications that remove fails (sp-dma-sweep, pi-dma-sizes, rdpstat 32 px, dead-check deletions): pref 2 "no unverified status".
- D9: W choice (100 vs 108 vs 9 rclk) and whether pidma ROM self-check 0 failures is required (PI:121).
- D10: What counts as "software-complete" (S4), since SOFTWARE_READY cannot go true.
- D11: Pre-registered pass rules for the phase-walk (U-NEMU-PHASE, U-MM-PHASE) and the pidma rule (S8).
- D12: Out-of-scope ruling is D1, but also on #16: if predicted-F hw checks (>= 15) fail, are they "ingested" for MAP_GREEN? P:30 says every hw:* "ingested and passes"; PE:121 says at least 15 will fail until model fixes. State that MAP_GREEN needs those fix units (P6).

## Honesty summary (pref 21, 2, 7)
- Circular/fit-selected greens: pi-io-w, si-io-w, si-dma-w-rom, pi-dma-128 (S3); pidma row-end points (S8); Thar0 F1 as "independent" (S8).
- Band widening: none proposed, but D5 stated-count and phase-walk pass rule can become one (S8). sp-dma-sweep/pi-dma-sizes relabels are reasoned (verify-78) but should be shown as reclassified-not-fixed (S5).
- "Green without hardware" that needs hardware: thar0 F1 (no named check goes green, S1); P3 predicted -3 (S5); rdpstat 32 px (S12).
- Inferred claims tagged measured: S13 first two bullets.
