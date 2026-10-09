# verify-78: PR #78 (phase), head 584b9fdac76f6bf4a34fe4dc8a34a4735b5dd99a, base master 5718d2124

Verdict: PASS-WITH-NOTES. Safe to merge. Two verdict flips need relabeling, not reverting: pi-dma-sizes cart-to-ram-8 passes only under `consistent` (fails `mean`), and mi-memset-rspdma passes only because of the idle-VI grid model choice (issue #77). Neither is verification of a model (pref 21).

Setup: worktrees ares-wt/verify-78 (head), verify-78-base; builds ~/n64-timing/build/verify-78-{head,base}; private homes ~/n64-timing/verify-78-home-{head,base} (scratch symlinked for the IPL3); results ~/n64-timing/results/verify-78/{head,base,scan,scan2,pre76,exp}. Every suite ROM rebuilt from my tree (pref 25). Head ROM list: 655 ROMs sha prefix f6bb9434; base 35 ROMs df296edc; both equal the worker's. A /tmp quota hiccup killed my first build; rebuilt with TMPDIR in my home. Scratch worktree verify-78-exp (idle step 1) removed. No processes left.

## 1. No core change (measured)
- `git diff 5718d2124` under ares/: only ares/n64/timing/behaviors.{hpp,tsv}, four note strings (pi.io-busy, si.io-busy, si.write64, si.write64-rom). No value changes.
- MM 600 --stats md5 base = head = 210d0d4625788e5e8d0e1d74be65a07f. nemu64 timing/cycle/cop0hazard values.tsv: cmp identical x3. thar0 compare.tsv identical, mmbench summary identical, rdpstat identical.

## 2. The three rules
Cross-rule matrix computed from my head results.tsv (P/F under consistent|mean|every):
- consistent rows where rules disagree: pi-dma-8 PFF, pi-dma-128 PPF, pi-io-write PPF, si-io-write PPF, si-dma write64-rom PPF. Mean passes all of them except pi-dma-8.
- mean rows: mi-memset-rspdma (both metrics) PPF; sp-dma-sweep PFF (consistent would have PASSED it; the worker chose the stricter rule there, so the rule set is not tuned to flip things).
- every rows: all PPP, ranges of zero width at 8 of 9 (rdp, hpos).

(a) consistent, 27 rows. Effective acceptance window for the model median = band width + model range width.
| row | model range (w) | band (w) | window as +-% of hw |
|---|---|---|---|
| pi-io-write | 125.33..142.67 (17.3) | 132..136 (4) | +-10.7 rclk = +-8.0% |
| pi-dma-8 | 180..194.67 (14.7) | 191.07..194.93 (3.9) | +-9.3 rclk = +-4.8% |
| si-io-write | 2149.33..2166.67 (17.3) | 2153.7..2162.3 (8.6) | +-13 = 0.6% |
| si-dma write64-rom | 2136..2149.33 (13.3) | 2139.7..2148.3 (8.6) | +-11 = 0.5% |
| si-dma write64 | 4058.67..4069.33 (10.7) | 4056.9..4073.1 (16.3) | +-13.5 = 0.33% |
| pi-dma-128 | 1574.67..1592 (17.3) | 31.8 | +-24.5 = 1.5% |
| pi-dma-1024 / 65536 | 13.3 | 243 / 15556 | +-1.05% / +-1.0% (band is plan T8's +-1%, not the original's 0.2%) |
| the 15 unwalked rows (uncached, rcp/pif/pi-io-read, JOY, banked) | 0..1 | 2 pclk / 0.2% | pointwise, as before |
The width is intrinsic: one poll period is 16.7 rclk, and a single hardware reading is one unknown phase of it. Narrower is not honest unless the hardware poll phase is known. It can still fail: pi-io-write's old model value 140 (the pre-#76 fail) now passes, so the check cannot tell 133 from 140 (5%). pi-io-write and pi-dma-8 are the loosest (+-8%, +-5%). JOY empties fail robustly even if widened by 8 rclk (empty-1b is 57 off, 0.35%).
Tighter honest rule: none from the data on hand. Do instead (1) have report.py also print the `mean` verdict next to every `consistent` row, and label a consistent-only pass "consistent-with, not agreement"; (2) the real fix is to compile n64-systembench (libdragon toolchain, not on this host) so the hardware poll phase is the compared quantity, or at least to match its poll prologue in k_sb_while and compare the jitter-0 rep pointwise.

(b) mean. n64brew publishes one time per method at 0.1 ms resolution; the loop code, VI state and run count are not published (vr4300-wb.md caveats). Cached/uncached memset cover 400 to 780 lines and do average refresh and fetch phase within a run, so mean is fair. rspdma covers 41 lines: one VI fetch more or less is 2.4%, so the hardware number is closer to one phase than an average; mean there is a judgment call. It is stricter than consistent (rspdma range 6.422..6.501 overlaps the band anyway), so no easing, but margin is 0.005 above lo (mean 6.495 vs 6.49). sp-dma-sweep's reference (6.5) is that same 2.58 ms rspdma figure: 1 MiB / 2.58 ms. It averages 256 queued 4 KiB DMAs including inter-DMA gaps; the model value is one DMA from trigger to idle. They are not the same quantity, so the fail (mean 6.361 dense 6.345, range 6.156..6.693) is not a clean model signal either way. Fine to keep as a fail.
(c) every: the 9 rows are fixed costs (a sync, a setter, 1 prim, one refresh per line) that must hold at every phase; model ranges are zero or 0.066 wide; justified.

## 3. The two flips
- mi-memset-rspdma fail -> pass. Reproduced: range 6.422..6.501, median 6.498, mean 6.495 (32 delays); dense 1330 delays mean 6.496. Caveat (N2): I built a scratch core with the idle VI step at 1 VCLK. mi-memset-rspdma reads 6.422 at 19 of 19 delays tried (fail at every phase). So the pass depends on the 0x800 idle grid that issue #77 says has no hardware reference. The pass is a property of a phase model choice, not independent hardware agreement.
- pi-dma-sizes: now a TIMEIT_WHILE_MULTI(10) with 2 setup writes (PI_DRAM_ADDR, PI_CART_ADDR) before COUNT, PI_WR_LEN timed, 8-poll rounds on status & (DMA_BUSY|IO_BUSY), VI blanked. Read against main.c:171-180 and the TIMEIT_WHILE macro (75-103): faithful. Old port: min of 4 reps of one DMA, VI on, no poll walk (196.0/197.33 at all delays). Deviations from the original: RDRAM buffer address differs (rambuf vs PI_DMA_BUF) and the deliberate nop jitter between write and first poll. Both disclosed.
- Rule dependence (key): 8 B reads 180..194.67, median and mean 189.0 (dense: always 189.0). Hardware 193. Under `consistent` it passes; under `mean` it FAILS (189.0 is 2.07 below the band, 4 rclk below 193, 2.1%). It is the only consistent row where the rule choice decides, and it is the one that flipped. 128/1024/64K pass under both, and are the rows pi.block-writeback was fit to, so they are circular. pi.block-writeback has an empty fit-from column (pref 21), so this pass is not verification of it; the independent check pidma:logs still fails.
- The inference that makes `consistent` right (hardware reps phase-locked) is the worker's and verify-76's, not tested. If reps were phase-spread, the 8 B point is a real -2% miss.

## 4. 32-delay claim, denser scans, periods (measured)
- results.tsv and measurements.tsv from my head run are byte-identical to the worker's (cmp measurements.tsv; diff results.tsv columns).
- Dense scan: 5 ROMs (mi-memset-rspdma, pi-io-write, sp-dma-sweep, pi-dma-sizes, si-io-write) at every K = 1..1330 (1330 delays, step 1; one full period). Verdicts identical to the 32 delays on all 5: rspdma b_per_rclk mean 6.496 vs 6.495 (pass); sp-dma-sweep mean 6.345 vs 6.361 (fail; dense min 6.156 vs 6.169); pi-io-write 133.0 both; si-io-write 2157.51 vs 2157.56; pi-dma-8 189.0 both; 128 1581.94 vs 1582.19.
- Dip windows (rspdma < 6.49): K=1 and 1292..1316 in the dense scan. Further scan 2560..2660, 3880..3960, 5190..5290, 6500..6580, 7800..7900: dips start 1292, 2606, 3921, 5236, 6550, 7865 (width 25-26). Spacing 1314, 1315, 1315, 1314, 1315 iterations x 3 pclk = 3943 to 3945 pclk = 0x800 VCLK (3944). Confirmed. Note phases.py says 1313 iterations; 3944/3 = 1314.7. Cosmetic. The 32 delays cover 32 x 123 = 3936 pclk and hit the dip at K=1 only (1 of 32 vs 25/1314 = 1.9% expected). Mean effect 0.001.
- Poll periods 25/26 pclk: arithmetic checked (123 mod 26 = 19, coprime, so 32 delays reach 26 distinct phases). The poll loop length itself I did not instrument.

## 5. Plateau mechanism (measured)
- Pre-#76 core (verify-76-base binary, head ROMs): K=415..425 6.492, 426..450 6.478/6.464/6.436/6.422/6.435 (dip), 451..460 6.501, K=600 6.500. Dip at K=426..450 reproduced; verify-76's 49-sample scan missed it. Claim true.
- 1-VCLK idle step (scratch build): rspdma 6.422 at all 19 delays (K = 1,2,3,5,8,10,13,20,30,40,100,200,400,428,440,1000,1292,1300,1305). sp-dma-sweep wr-4096-off0 reads 6.321 or 6.334 (not 6.334 everywhere as the report says; spread 0.2% vs 8% in the idle-0x800 core). Mechanism claim stands, the "same at all" wording is slightly off.
- Issue #77 is accurate to what I measured. vi.cpp:112 step(0x800) confirmed; allowlist note corrected. Not fixed is right: no reference.

## 6. hpos ROM change
bank5 at K=1, 42, 1272: line_ticks estimate 2926, window 8801 ticks, HSYNC outliers at offsets 2981 and 5965 (spacing 2984, identical at every K). The true line is ~2984 ticks, so the ROM's one-line estimate (2926, 2% low) made full_lines 3 instead of 2, giving 2/3. Counting interior HSYNCs gives 2/2 = 1.0. This is a ROM-estimate fix, not a model hide: the model's HSYNC spacing is constant and outliers do not move. Residual weakness: still derived from the wrong line estimate; measuring over several lines is the right fix (worker's follow-up 5).

## 7. Standing (measured)
- det/stepcap PASS: nemu64 x3 (25/2/1 fields), MM 29 files 8219 fields; state round trip PASS (saves/loads at 150, 300, 457); tmem poke PASS; ctest 9/9; behaviors --check ok, --self-test 43 cases 0 failed, lint-literals ok, pidma-replay self-test 5/5; bench selftest all ok. pidma still FAIL 23776..23833/24000, worst +14.97%.
- Bench base vs head: expected rows base fail 18/pass 26; head fail 15/pass 29. Flips: mi-memset-rspdma ms_per_mib and b_per_rclk fail -> pass; pi-dma-sizes (new metric sb_rclk) fail -> pass. Nothing else moved verdict. Remains fail: sp-dma-sweep 6.156..6.693, u32-banked 131..132, JOY except empty-0b.
- Wall: head standing 752 s (run while my dense scan competed, load 11-17), base 709 s (alone, load 16-19 from other users). Worker's 12m44s/12m18s is the same order. Not an apples-to-apples comparison; bench step itself is about 1 min.
- Spec results: behaviors.py --results on my head run reproduces docs/spec/n64-timing-results.tsv except the header (it names 48be98188, not the head 584b9fdac; the ROMs and runner are unchanged since) and the two snapper rows (my private home had no snapper corpora; not run). Restored the file afterwards.

## Diff findings
- tools/n64-timing/romgen/suites/bench/expected.tsv pi-dma-sizes cart-to-ram-8: pass is consistent-only (N1).
- tools/n64-timing/romgen/suites/bench/phases.py comment: "3944 pclk = 1313 iterations" should be 1314.7 (measured spacing 1314.4).
- docs/spec results header provenance (48be98188 vs head).
- No dead code or scope creep seen beyond declared deviations (si.write64 note, max2 at RES[3], results.tsv columns). Comments explain whys with citations.

## Not reproduced / differences
- "sp-dma-sweep reads 6.334 at every 1-VCLK delay": I get 6.321 and 6.334.
- Dip window "K = 1 and 1300 to 1316": I see 1292..1316.
- Snapper rows not run by me.

## Recommendation
Merge. Follow-ups: (1) show mean next to consistent, label pi-dma-8 as consistent-only; (2) fix-from for pi.block-writeback (pref 21); (3) compile the original systembench to compare poll phase pointwise; (4) #77 stays open; mi-memset-rspdma must not be read as model agreement until it resolves.
