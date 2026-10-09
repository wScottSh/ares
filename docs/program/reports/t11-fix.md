# t11-fix report: PR #63 (T11, VI fetch on the bus) to a landable accuracy state

Status: done, with two acceptance items not met and listed (memset uncached outside 3%; SP DMA wr-4096 check band). Not merged.

- Branch feat/t11, head feae47da8fcf8cf0877884fb23b9a497e255f80b, pushed. PR https://github.com/wScottSh/ares/pull/63, body updated.
- Merged origin/master 1a6a9de57 first (cc31b225d). No rebase, no force-push.
- Builds: ~/n64-timing/build/t11-fix-base (master, worktree /home/wscottsh/repos/ares-wt/t11-fix-base, detached, kept), ~/n64-timing/build/t11-fix (head). Sweep build build/t11-fix-sweep (its worktree removed).
- Raw output and drivers: ~/n64-timing/results/t11-fix/ (standing.sh, quick.sh, sweep.sh, wall.sh, compare.py; base/, base-report-fix/, head/, q-*/, sweep/, mm-refit/, mm-tear/, wall/, wall2/).

## Commits (after the merge)

1. ae9899f1c bench: back out the hpos outliers fix from the T11 change.
2. 0c8fadd65 bench: uncached-vs-hpos counts every refresh outlier in the window. Own commit. I replaced the prior worker's logic: it divided by an HSYNC count that assumed the HSYNC phase and read bank2-vi 1.5 on master (verified). The real flaw was dropping an outlier past full_lines*line_ticks (line_ticks is measured; bank5 outliers 2986/5965/8945 vs limit 8928). On master's raw output: bank5 0.667 -> 1.0 (fail -> pass), bank2-vi stays 1.0, all else identical (measured, results/t11-fix/base vs base-report-fix).
3. 6caca98ae ri: ViFetch trailer = ri.overhead-vi (0 rclk, derived, vi-fetch.md) + post-read gap. New check row nemu64:timing/load-from-uncached-vi-on-other-bank.
4. 7b14a41c4 timing: refit write rows with VI on. ri.overhead-write 1 -> 0 (fit -> derived), sysad.rdram-write-period 12 -> 11, sysad.rdram-block-write-period 12 -> 11 (both fit, verify-is-fit), ri.overhead-rdp text, vi.burst note.
5. 925c6822f timing: five model-choice rows labeled inferred (vi.register-sample, vi.fetch-overrun, vi.unfetched-sample, vi.aa-mode-lines, vi.display-window); vi.vclk-per-pixel names VI_H_TOTAL.
6. feae47da8 vi: drop VI::scanned (1.47 MB) and the per-pixel raw write; n64-run vi_tear compares the screen compose wrote with RDRAM converted the same way. Coverage/alpha-bit-only changes no longer count (not displayed). Mutation (compose reads next fetched line): 478/600 MM fields flagged; head 0.

## Fit provenance (pref 21)

- Assumption, stated in each refitted row: n64brew memset table measured with VI on. Unknown (page states no video state). Support circumstantial: 17 wire + 1 gap = 18 rclk per 128 B = 7.11 B/rclk x (1 - 0.074 - 0.0125) = 6.50.
- ri.overhead-write = 0 is the datasheet value with no term added; RSP DMA memset (6.499) and sp-dma-sweep are its checks. Caveat for the verifier: the choice 0 vs 1 coincides with what rspdma prefers under the VI-on assumption; I label it derived because no free parameter is adjusted.
- Periods: fit on memset uncached/cached, verify-is-fit (no other data decides a CPU write drain). Grid measured: any period in (11,12] behaves as 12 (11.25/11.5/11.75 tried). No grid value within 3% for uncached (11: -3.6%, 12: +5.5%). Cached: 11 +2.1%, 10 +0.1% rejected (4-word writeback below a 2-word uncached write; that SysAD argument is my inference).
- Independent checks not used in the fit: nemu64 20.1 (passes), Load Miss VI on (passes), rspdma (passes).

## Acceptance (measured; base = master 1a6a9de57, head = feae47da8)

- nemu64 timing 11 -> **9** failures. 20.1 pass (probe mean 34.76), 18.0/18.1 pass. Remaining: 8x Load Miss VI off (C7, 41.0 vs 42.5 +/- 0.5, unchanged, T7a follow-up) and 20.0 same-bank mean 41.63 (real ROM) vs 36.3 +/- 4; median 37 passes. 20.0 cause: tail of loads queued behind a whole VI burst plus row reopen (probe: median 37, mean 38.99, max 66). Missing reference: hardware latency histogram for the test; VI burst size and arbitration (vi.burst, ri.rank.vi are model choices).
- bench (hw / base / head): memset uncached 18.38 / 18.277 / **17.717 (-3.6%, outside 3%; no grid value fits, reference missing: sub-SClock drain structure or hardware vi-on/vi-off pair, calibration #16)**; cached 71.24 / 71.012 / 72.744 (+2.1%); rspdma 6.5 / 6.473 / 6.499 (pass); sp-dma wr-4096 6.5 / 6.495 / 6.334 (-2.6%, within 3%, fails its 6.49..6.515 band). bench fail/pass: base 9/12 (with report fix; 10/11 as run) -> head 8/13.
- MM 600 fields: VI 293.39 rclk/HSYNC line = 7.39%, refresh 52.64 = 1.33%, vi_tear 0. fb_hash 375/600 differ: base's first 241 images in order, 1-2 fields later (0:2, 1:104, 2:135); cause VI contention slows the game.
- Hardware-referenced count (verify-63 method, one per quantity): improved 5 (Load Miss VI on x2, RSP DMA, 20.0 median, bank2-vi median report 34 -> 36 vs 36). Regressed 7: memset uncached (-0.6 -> -3.6%), cached (-0.3 -> +2.1%), SP DMA wr-4096 (-0.1 -> -2.6%), 20.1 mean error 0.8 -> 2.3 (passes both), 20.0 mean error, dirty-row-sweep dirty-8 0 -> 2 (hw 0) and dirty-800 2 -> 0 (hw 3) (report rows, 2-pclk COUNT aliasing; dirty-8 tracks the periods, dirty-800 tracks ri.overhead-write, from the sweep). Checks: 4 newly pass (18.0, 18.1, rspdma x2), 1 newly fails (sp-dma wr-4096). Verdict: a gain in passing checks, a loss in memset error magnitude. Master's memset closeness came from fits with no VI to absorb; every regression above is explained, but by error count it is not a clean net gain. Coordinator/verifier must judge.
- Versus the PR as the verifier saw it (4f8ecfdde): every value improves or holds (memset 19.70 -> 17.72, 75.77 -> 72.74, rspdma 6.08 -> 6.50, sp-dma 5.85 -> 6.33, 20.1 fail -> pass, VI 8.93% -> 7.39%).
- Standing (base -> head): snapper 2592/2592 both; rdpstat 0/7, 0/2, 0/21 both; thar0 model columns identical all 100 configs; cop0hazard 0/5 failures with new ROM and cycle 7/13, values.tsv identical; ctest 5/5; behaviors --check/--self-test, lint-literals ok; unit:rdram-private in ctest; det + stepcap PASS MM (27 files, 8158 -> 8177 fields) and nemu64 x3; round trip 150/300/457 + TMEM poke PASS (first differs field 31).
- Wall MM 600 fields --stats, 4 interleaved pairs, load 1.9-3.0: base median 19.70 s, head 20.73 s (+5.2%). Head vs previous PR head (3 pairs, load 1.1-1.4): +0.2 s; cause not isolated (dropping the raw copy did not make it faster).

## Key finding for the coordinator (follow-up)

nemu64's own hardware expected means give VI-on minus VI-off: other-bank uncached 32.5 - 32.54 = ~0 pclk; Load Miss 43.25 - 42.5 = +0.75. Model (probe ROM): +1.76 and +1.5..+2.1. So the model's VI delays isolated CPU accesses about 2x more than hardware. The same interaction probably over-slows the CPU uncached memset stream (7% loss); with about half, 12 rclk would fit. 64 B and 32 B VI bursts make it worse (sweep: 32 B fails Load Miss again and slows memset more). No reference names the mechanism; calibration #16 decides. Under that reading the VI-off fits of master would come back, so the VI-on assumption is the contested premise.

## Deviations

- Report fix rewritten, not moved (see commit 2).
- ri.overhead-write basis changed fit -> derived (value 0).
- Rows added for item 4 use basis model-choice with "inferred" in the reference; values are rule tokens so no code constant changes.
- Item 5 done by removing the core array rather than gating; tear count semantics narrowed to displayed bits.

## Follow-ups

- VI-vs-CPU interaction strength (above); 20.0 same-bank tail.
- ri.overhead-read was also fit with no VI; sp-dma-sweep rd-4096 5.216 vs hcs64 5.55, unchanged.
- ri.overhead-rdp (20 units) copies a superseded VI-off fit; T13 owns it.
- C7 Load Miss VI off x8.

## For the next unit

- T13: VI bursts are wire + 2 tc gap only; CPU/DMA writes have no RI overhead now; RDP keeps 20 units.
- n64-run vi_tear uses screen pixels; VI keeps scannedOrigin and fieldScanned only.
- No background processes of mine remain.
