# verify-63: PR #63 (T11, VI fetch on the bus), head 4f8ecfdde

Verdict: **FAIL as a landing candidate on accuracy; the mechanism passes.** Recommendation: **fix-unit before landing** (scope below). If the coordinator lands it as-is, land then fix-unit is the minimum, but the PR is a net accuracy loss against hardware references until then.

Base for comparison: a1c92f1b9 (worktree verify-63-base, build verify-63-base). Head: verify-63 (4f8ecfdde). Builds RelWithDebInfo gcc 15.2 via tools/n64-timing/build.sh. Results: ~/n64-timing/results/verify-63/{base,head,wall}. Host load: standing runs 23 -> 6 (T7d building), wall runs 1.6-3.0.

## 1. Reproduction (all reproduced; nothing in the worker report failed to reproduce)

| Check | base | head |
|---|---|---|
| nemu64 timing failures | 11 of 1604 | 10 of 1604 |
| Cycle / cop0hazard (old ROM) | 7/13, 2/5 | 7/13, 2/5 |
| cop0hazard with PR #64 ROM (master 1a6a9de57 romgen) | 5/5 | 5/5 |
| snapper | 2592/2592 (432+32+2048+80) | same |
| rdpstat | 0/7, 0/2, 0/21 failed | same |
| thar0 rows 94-99 (and 84/85/92/93 per worker) | identical min/avg/max both sides | |
| ctest | 5/5 | 5/5 |
| behaviors.py --check / --self-test / lint-literals | | ok / ok / ok |
| determinism MM | PASS 27 files, 8158 fields | PASS 27 files, 8186 fields |
| stepcap MM | PASS 8158 | PASS 8186 |
| determinism + stepcap nemu64 (timing, cycle, cop0hazard) | PASS | PASS |
| state round trip (150/300/457) + TMEM poke | PASS | PASS (poke first differs at field 31) |
| bench fail/pass/report | 10/11/19 | 10/11/19 (different mix) |

nemu64 VI rows, head sums: 20.0 same-bank a=0xa33a = mean 41.786 (needs 36.3 +/- 4); 20.1 other-bank a=0x93e9 = mean 37.865 (needs 32.5 +/- 4, newly failing). 18.0 and 18.1 Load Miss VI-on pass (base 0xa365 = 41.83 and 0xa37b vs 43.25 +/- 1). 20.0 median 37 passes the 36 +/- 1 check; only the mean fails.

Bench rows (base -> head): memset uncached 18.277 -> 19.701 pclk/SD (hw 18.38); cached 71.012 -> 75.771 pclk/line (hw 71.24); rspdma 6.473 -> 6.081 B/rclk (hw 6.5); sp-dma-sweep wr-4096 6.495 -> 5.851 (hw 6.5, pass -> fail). pi-dma-sizes 65536: 778498.67 -> 779277.33 (band holds).

MM fb_hash: 511 of 600 fields differ. Run-length collapse gives 242 base images vs 241 head images; the 241 common images are identical in order. Per-image first-appearance offset, head minus base: +3 fields for 135 images, +2 for 103, 0 for 3. Confirms "same images 2-3 fields later". vi_tear fields=0 (head, 600 fields).
Ri counters (head, MM 600 fields): vi_rclk_per_line 354.54 (8.93% of 3972.25), refresh 52.65 (1.33%); since power-on 8.41% and 1.25%. Also vi_row_misses 1,001,152 of 2,138,430 grants (47%) and 26.1 rclk mean per burst.

Wall, 5 interleaved pairs, load 1.6-3.0: base 19.556 19.746 19.656 19.792 19.583 (median 19.656 s); head 20.482 20.525 20.489 20.675 20.476 (median 20.489 s). +4.2%. Head above base in 5/5 pairs.

Not rerun: the worker's mutation test (compose reading the next fetched line, 505/600 in vi_tear). Not rerun: MM second scene; MM filesel only through determinism.

## 2. Is the over-contention a model defect? Yes in part: one parameter has no reference and a reference contradicts it; the rest is a stale fit.

Experiments (scratch worktree, not pushed; patch at results/verify-63/exp-experiments.patch). All numbers from the real runner. nemu64 means are from the real ROM; the probe ROM columns come from the worker's probe.sh and differ slightly by phase.

| Variant | nemu64 timing fails | 20.1 other-bank mean (probe) | 20.0 same-bank | memset unc | memset cached | rspdma | sp-dma wr-4096 | bench fails | MM VI rclk/line |
|---|---|---|---|---|---|---|---|---|---|
| base | 11 | 33.31 | fail (median 33) | 18.28 | 71.01 | 6.473 | 6.495 | 10 | n/a |
| head | 10 | 37.68 (37.87 real) | fail mean | 19.70 | 75.77 | 6.081 | 5.851 | 10 | 354.5 (8.93%) |
| A: VI trailer = post-read gap only | 9 | 34.72, passes | fail mean 41.69 | 19.39 | 74.53 | 6.153 | 6.0 | 10 | not run |
| B: A + ri.overhead-write 0 + both sysad periods 11 rclk | 9 | 34.76, passes | fail mean 41.63 | 17.72 | 72.74 | 6.499 (pass) | 6.334 | 8 | 293.4 (7.39%) |
| C: B + 1 fetched line when AA_MODE >= 2 | 11 | 33.59 | median 33, fails | | | | | | |

Findings.

1. **Specific parameter: the RI trailer applied to the VI.** `ri/bus.hpp` `trailer()` adds `ri.overhead-read` (4.5 rclk) to every non-RDP read, including `Requester::ViFetch`. That row is a fit from hcs64's SP DMA rate (3.7 B/pclk = 23 rclk per 128 B) in behaviors.tsv; its own note says the direction of the hcs64 run is unstated, and rdram-bus-arbitration.md B10 says the fit carries a ~41 pclk poll-loop overhead. Nothing in the references attributes an RI overhead to VI scanout. vi-fetch.md "MM bus-occupancy estimate" costs a VI burst as the NEC wire time plus the 2 tc post-read gap only: "a 128-B read costs 74 tc (hit), 96 tc (clean miss) or 104 tc (dirty miss), plus a 2-tc post-read gap", giving 285-398 rclk per active line. Head's 354.5 per HSYNC line is 393 per active line, which is the all-dirty-miss end (398) although the same doc infers VI's own sequence is "mostly row hits". Dropping the trailer for ViFetch (variant A) gives 293.4 rclk/line = 7.39%, mid-band, and fixes the newly failing 20.1 (mean 37.9 -> 34.7). The ADR "assumption" (apply the read overhead to all read clients) is the unreferenced step. This is a defect in the PR's model, supported by vi-fetch.md.
2. **A parameter-only trailer fix is not enough: the memset fits predate the VI.** `sysad.rdram-write-period`, `sysad.rdram-block-write-period` (12 rclk each) and `ri.overhead-write` (1 rclk) were fitted with no VI traffic, and their notes say the residual "is inferred, not measured, to be VI fetch contention (plan T11)". The residual they assumed was 0.1 pclk/SD; the modeled VI costs 1.3-1.65. A zero-free-parameter check supports the table having been measured with the VI on: a 128 B write is 17 rclk on the wire + 1 rclk gap = 18 rclk = 7.11 B/rclk; times (1 - 0.0739 VI - 0.0125 refresh) = 6.50 B/rclk, equal to n64brew's 2.58 ms/MiB. Variant B (overhead-write 0) reproduces it: 6.499. This is an inference (arithmetic from datasheet figures and the research share), not a measurement.
3. **Is it known whether the n64brew memset table was measured with the VI on? No.** I fetched https://n64brew.dev/wiki/MIPS_Interface: the section is one line, "Memset benchmarks for 1MiB of data", four results, and it states no loop code, framebuffer or video state. vr4300-wb.md line 125 records the same ("does not publish the loop code, the VI state"). The bench ROMs label the expected rows `vi-on` (expected.tsv), which is itself an unreferenced assumption. Finding 2 is circumstantial support for VI on, not proof. Only calibration #16 decides.
4. **Arbitration rank** (`ri.rank.vi` 1, model-choice, "none published") is unmeasured. I did not vary it. The research's only hint is that the VI is "highest or near-highest (inference)". The 20.1 fix under variant A suggests rank is not the dominant factor.
5. **Burst spread** is as the research says (15 bursts evenly spaced H_START..H_END). Not a defect.
6. **Rejected alternative:** fetching 1 line when AA_MODE >= 2 (nemu64's vi_init runs mode 2) lowers contention but then Load Miss VI-on and the same-bank median fail again (variant C, 11 fails). So hardware nemu64 data are consistent with heavy VI traffic in mode 2; the PR's "AA mode not consulted" choice survives, labeled inferred.
7. **Remaining after fix B:** uncached memset 17.72 (-3.6% vs 18.38) and cached 72.74 (+2.1% vs 71.24) bracket the target between 11 and 12 rclk, so the periods need a refit (a missing cached-line term is likely; rclk-grid limits are the worker's claim, I did not verify them). Same-bank mean (41.6 vs 36.3 +/- 4) stays failing under every variant; it comes from the row-miss tail (max 64-66 pclk), a separate cause. The mean is also phase sensitive: the probe ROM and the real ROM disagree by 2.7 pclk, so the loop aliases with the 15-per-line burst schedule.

## 3. Landing as-is: net accuracy loss

Hardware-referenced values, base -> head:

Improved (2): nemu64 18.0 and 18.1 Load Miss VI-on (fail -> pass, 41.8 -> within 43.25 +/- 1).
Partially improved (1 check of 2): 20.0 same-bank median 33 -> 37 passes; mean 34.06 (probe ROM; the real base mean passed its 36.3 +/- 4 check, only the median failed) -> 41.79 (fails): the value still fails and its mean error grew from -2.2 to +5.5.
Regressed (5): nemu64 20.1 other-bank (pass -> fail, 33.3 -> 37.9 vs 32.5), memset uncached (-0.6% -> +7.2%), memset cached (-0.3% -> +6.4%), RSP DMA memset (-0.4% -> -6.4%), SP DMA wr-4096 (-0.1% -> -10.0%).

So 2 improve, 1 split, 5 regress, and four of the five regress from within 1% to 6-10%. The bench "fail 10 -> 10" hides this: base's memset rows already "failed" the bands (tight, the table's 0.1 ms resolution) but within 0.6%. The head fail count is flat only because of the report.py change (item 4): without it head would be 11.

Against that, adding VI contention is the physically right direction for a console that has the VI on (the research puts it at 7-10% of the channel). The loss is in calibration of the parameters in finding 1 and 2, not in the structure.

## 4. Provenance

| Row | Label in PR | My read |
|---|---|---|
| vi.vclk-per-pixel 4 vclk/px | wiki | Correct. n64brew Video_Interface (fetched): H_TOTAL "One less than the total length of a scanline in 1/4 pixel units", NTSC 3093; H_VIDEO in screen pixels. (3093+1)/4 = 773.5 px. Minor: the row calls the register VI_H_SYNC, n64brew calls it VI_H_TOTAL. Not a fit. |
| vi.burst 128 B | model-choice | Correct label (inferred from the X_SCALE erratum + RI max). The added note is honest; its "Unmeasured inputs" list is accurate. |
| vi.lines-per-output-line 3 | vendor | Unchanged. SDK text and patent; Angrylion/paraLLEl use 4. Variant C shows hardware nemu64 data do not support fewer lines in mode 2. |
| vi.fetch-window active-line | wiki | Unchanged. |
| sysad.rdram-write-period / block-write-period | fit, verify-is-fit | Notes appended with the VI deltas. Accurate numbers (19.70 vs 18.05 = 1.65; 75.77 vs 70.49 = 5.28). But these rows now carry a fit that the PR itself shows is off by 7% with the VI present; the fit-from data (the n64brew table) has unknown VI state. |
| Worker deviation 6 choices (registers read per line with no field latch; a line still fetching at the next HSYNC keeps fetching and the new line fetches nothing; samples outside the 3 fetched lines read 0; AA mode not consulted; fetch/compose rows follow ares's 480-row window) | no behaviors.tsv row, comments in vi.cpp/vi.hpp only | **Inferred, no reference, and not in the spec.** They should be model-choice rows (or the code should state they are unreferenced) per the map rule "a behavior is either built from its references or not built". Not blocking. |
| ri.rank.vi 1 / ri.overhead-read applied to VI | unchanged rows | The application of ri.overhead-read to the VI has no row of its own and no reference (finding 1). |

report.py hpos fix: it **does change a base number.** Re-running both report.py versions over the same base raw output: uncached-vs-hpos bank5 outliers_per_line 0.667 -> 1.0 (fail -> pass); bank2-vi outliers_per_line 1.0 -> 1.5 (a report row); every other row identical. The logic is sound (the sampling window opens at the line change the sync loop saw, so that line's refresh stalls the poll and never a sample; the old divisor counted lines that cannot hold a sample), and base with the fix reads 1.0, so it is a measurement-tool correction independent of T11. But it should have been its own commit/PR: it turns one base bench failure into a pass inside a PR whose own change adds one failure, which makes "bench fail 10 -> 10" read as no change. Bank2-vi 1.5 outliers per line is not explained in the report (15 VI outliers per line were noted separately).

## 5. Diff hygiene and scope (17 files, +273/-75; read in full)

- Plan files named `devices/events.*` do not exist in the tree; events landed in timing/events.hpp + timeline.cpp, `ViFetch` as `VI::Fetch`. Consistent with T8's SpDma placement; fine.
- Unlisted files: ri/bus.cpp (VI_DMA tag, 1 line), rdram.hpp (friend drop, wanted), serialization.cpp (version v153.9-vifetch), behaviors.tsv/.hpp/.py, spec, n64-run, mmbench.py, report.py, rdram-private.cpp comment. All explained. The serialization bump covers T7c's unbumped layout change too; good.
- **Test hooks in core:** `VI::scanned[640*576]` (u32, 1.47 MB, unserialized), `scannedOrigin`, `std::function fieldScanned` exist only for n64-run's vi_tear count; `compose()` writes `raw[]` per pixel on every field. This is a host diagnostic in a core device and part of the +4.2% wall. Acceptable, flag for T16's wall budget.
- No dead code found. Comments explain whys and cite doc sections; "dedither" bit 16 added to io read/write/serialize as planned.
- `Fetch::slots` and `bytes` arrays are sized for the 4095-px, 32 bpp worst case; serialization writes `bytes` (49 KB) per state; fine.
- `n64-run` vi_tear is progressive-only (disclosed).

## Recommendation: fix-unit before landing

Scope of the fix unit (one PR on top of this branch, same files):
1. In `ri/bus.hpp` `trailer()`, give `Requester::ViFetch` reads the post-read gap only, citing vi-fetch.md (74/96/104 tc + 2 tc). Add a behaviors.tsv row (basis datasheet/derived) instead of inheriting ri.overhead-read. Expect VI 7.4% and nemu64 20.1 back to pass.
2. Refit `ri.overhead-write`, `sysad.rdram-write-period` and `sysad.rdram-block-write-period` with the VI present, stating the assumption that the n64brew table was measured with VI on, or keep the VI-off fit and relabel the bench points `vi-off`. Variant B is a starting point, not a fit (uncached 17.72, cached 72.74, rspdma 6.499, sp-dma 6.334). Record that the table's video state is unknown and the arithmetic in finding 2 is the support.
3. Move the report.py fix to its own commit (or note it explicitly in the PR) and add rows for the five deviation-6 model choices.
4. Leave `unit:rdram-private`, VI structure, compose and the MM tear check as they are.

Acceptance for the fix: nemu64 timing <= 9 failures with 20.1 passing; memset/rspdma/sp-dma rows each within 3% of hardware or each listed with the missing reference; no change to determinism/stepcap/round trip; MM VI share 6.5-9% with refresh 1.3-1.4%.

If landed first, T13 would inherit the 4.5-rclk VI trailer and recalibrate the RDP against a contention level that is too high (thar0 VI-on configs).
