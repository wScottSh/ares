# verify-63b: PR #63 (T11, VI fetch on the bus) after t11-fix, head feae47da8

Verdict: **PASS-WITH-NOTES. Recommendation (a): land now.** No reference supports a further bounded fix; the open residuals are documented and need calibration #16.

Base 1a6a9de57 (worktree verify-63b-base, build verify-63b-base). Head feae47da8 (verify-63b, build verify-63b-head). RelWithDebInfo gcc via tools/n64-timing/build.sh. Results ~/n64-timing/results/verify-63b/{base,head,wall,exp-rank3}; drivers standing.sh, quick.sh, wall.sh there. Load: standing 17 -> 5.3 (T7d build + mine in parallel, deterministic checks only), wall runs 1.3-2.6, interleaved base/head x5. No process of mine remains.

## 1. Reproduced (all key worker numbers reproduce)

| Check | base | head |
|---|---|---|
| nemu64 timing failures | 11 of 1604 | **9** of 1604 |
| 18.0 / 18.1 Load Miss VI on | fail / fail | pass / pass |
| 20.1 other-bank mean | pass (33.3 probe) | pass |
| 20.0 same-bank | fail (median 33) | median passes; **mean fails** a=0xa2a0 = 41.60 vs 36.3 +/- 4 |
| remaining 8 | C7 Load Miss VI off x8, unchanged | same |
| cycle / cop0hazard (PR #64 ROM) | 7/13, 0/5 | 7/13, **0/5**; cop0hazard values.tsv identical |
| snapper | 2592/2592 | 2592/2592 |
| rdpstat | 0/7, 0/2, 0/21 failed | same |
| thar0 100 configs | | model columns identical to base (diff empty) |
| ctest (incl. unit:rdram-private) | 5/5 | 5/5 |
| behaviors --check, --self-test, lint-literals | ok | ok |
| determinism / stepcap nemu64 x3 | PASS | PASS |
| determinism / stepcap MM | PASS 8158 fields | PASS 8177 fields |
| state round trip 150/300/457 + TMEM poke | PASS | PASS (poke first differs field 31) |
| bench fail/pass | 10/11 | **8/13** |

Bench rows (hw / base / head): memset uncached 18.38 / 18.277 / **17.717 (-3.6%)**; cached 71.24 / 71.012 / **72.744 (+2.1%)**; rspdma 6.5 / 6.473 / **6.499**; sp-dma wr-4096-off0 6.5 / 6.495 / **6.334 (-2.6%, fails its band)**. Unasserted sp-dma offsets: off7c0 6.334 -> 6.169, off7f8 6.334 -> 6.012 (no hardware value, -5% from 6.334 at off7f8; not in the worker report).

MM 600 fields (head): vi_rclk_per_line 293.39 = 7.39% of 3972.25, refresh 52.64 = 1.33%, vi_tear fields=0. fb_hash: 375 of 600 differ; 241 common images identical in order; head is 1-2 fields later (1:104, 2:135, 0:2); base has 242 images, head 241.
Tear mutant (compose reads the next fetched line, scratch worktree verify-63b-mut): **vi_tear fields=478**; head 0. The counter and its mutant work after the VI::scanned removal.
Wall (5 interleaved pairs, load 1.3-2.6): base 19.725 19.851 19.761 19.602 19.583 (median 19.725 s); head 20.900 20.548 20.709 20.512 20.462 (median 20.548 s). +4.2%. Worker reported +5.2% (their load was 1.9-3.0); same ballpark. Head above base in 5/5.

Not rerun: dirty-row-sweep dirty-8 / dirty-800 report rows, the by-value regression table row by row (I counted the bench and nemu64 outputs above only), the worker's period/overhead sweep (grid claim "any value in (11,12] drains on the 12 rclk edge").

## 2. Diff review

- **report.py** (commits ae9899f1c, 0c8fadd65): confirmed by running master's and head's report.py over the same master raw bench output (rp-old vs rp-new): the only changed row is uncached-vs-hpos bank5 outliers_per_line 0.667 -> 1.0 (fail -> pass); bank2-vi stays 1.0; every other measurement and result row identical. It is a separate commit now, so the 10 -> 8 bench-fail count is partly this one (base re-reported with the fix reads 9/12). Logic: counts every outlier over floor(window/line) lines, since line_ticks is measured and the third HSYNC sits at tick 2986-8945 vs a floor limit of 8928. Sound for the 1-outlier-per-line contract; it would over-count if a 4th HSYNC fell in the window remainder, which is not the case in this data.
- **ri.overhead-vi = 0, "derived" from vi-fetch.md**: the doc estimates occupancy as wire + 2 tc gap and says nothing about an RI overhead either way. A value of 0 from silence is a choice, not a derivation; and the MM share band (6.5-9.0%) it is "checked" against is computed from the same wire inputs, so that check is circular. The real support is independent and good: nemu64 20.1 and Load Miss VI on (neither was used to pick it) pass with 0. Label should be model-choice (or derived with a note that the band check is by construction). Not blocking.
- **ri.overhead-write 1 -> 0, "derived"**: still a fit in effect. The deciding data is the same n64brew rspdma point as before; 0 with VI on and 1 with VI off both reproduce 6.5 within 1% (6.499 vs 6.56 per the row's own note). The zero-parameter arithmetic (17 wire + 1 gap, x (1 - 0.074 - 0.0125) = 6.50) is real but needs the VI-on premise, which nothing measures. The row says all of that honestly (the worker also flagged the coincidence). Acceptable as labeled, with the premise stated; do not count rspdma 6.499 as independent verification (fit-from is empty, verify = the memset-like data itself).
- **sysad periods 12 -> 11, verify-is-fit**: correct form under pref 21 (fit-from + verify-is-fit note). Uncached 11 gives -3.6%, 12 gives +5.5%, so the fit is outside 3% and the row says so. The VI-off value (16.55) is recorded.
- **cached 11 over 10**: 10 fits +0.1%. The row rejects it with "a 4-word writeback below a 2-word uncached write, which the SysAD transfer cannot do". That is an inference by the worker and is not marked as one in the tsv text (the worker report calls it inference). It also ties the cached period to the uncached period that itself misses by 3.6%. Note: label it inference in the row. Not blocking.
- **five model-choice rows** (vi.register-sample, fetch-overrun, unfetched-sample, aa-mode-lines, display-window): basis model-choice, reference says "inferred, none published", verify column names a check (mostly mm det / mm scene, which cannot decide them). Honest labels; vi.aa-mode-lines has real evidence behind it (verify-63 variant C). behaviors --check passes.
- **VI::scanned removal**: gone from vi.hpp and compose; only scannedOrigin and fieldScanned remain as the runner hook. n64-run compares the screen as compose wrote it (coverage/alpha-only changes no longer count). Mutation 478/600 vs 0 shows it still detects tearing. The head-vs-prior-head wall gap (+0.2 s) was not isolated by the worker; I did not either.
- ri/bus.hpp trailer(): ViFetch branch sits first, one line, comment names the row. No dead code seen in the fix commits.
- ri.overhead-rdp text now says it copies a superseded VI-off fit (20 units, model-choice); T13 owns it. Correct and visible.

## 3. The "VI holds the CPU 2x too long" finding: unmeasured, no reference supports a model change

What the references give: rdram-bus-arbitration.md B1/B5: one in-order channel, atomic 8-128 B bursts, no mid-burst preemption, a waiting client's worst-case wait is one in-flight burst (plus refresh). B4: priority "not documented", VI "highest or near-highest" is inference only, MiSTer's order is a DDR3 design choice. vi-fetch.md: burst size 128 B is inference (X_SCALE erratum + RI max), 15 bursts per active line is the patent's block fetch, VI priority is inference. The patent (US 6,166,748) says VI blocks go into a small double buffer, which says nothing about whether an idle-buffer VI yields to the CPU.

Arithmetic: with non-preemptive FCFS, 7.4% VI + 1.3% refresh occupancy and ~24 rclk bursts, a random CPU request waits on average about 0.074 x 12 rclk x 1.5 pclk/rclk + 0.013 x 26 x 1.5 = 1.3 + 0.5 = 1.8 pclk. The model's +1.76 (other-bank load) is exactly what the reference structure (B5) predicts, so the "2x" is not a bug against the references. It is a disagreement between B5 and one pair of hardware means.

The hardware side is weak: the nemu64 other-bank mean 32.5 has a +/- 4 tolerance, Load Miss means differ by 0.75 with +/- 1, and cpu-memory-costs.md notes the test author calls the measurement unstable. Hardware says "VI adds about 0-1 pclk", the model says 1.5-2; both pass the checks.

Experiment (mine, scratch worktree verify-63b-exp, not pushed): ri.rank.vi 1 -> 3 (VI loses every tie, CPU/DMA first):

| | head (rank 1) | rank 3 |
|---|---|---|
| nemu64 fails | 9 | 9 (20.0 mean 41.7) |
| memset uncached | 17.717 | 17.716 |
| memset cached | 72.744 | 72.657 |
| rspdma | 6.499 | 6.823 (VI starves, passes the wrong way) |
| sp-dma wr-4096 | 6.334 | 6.693 |

Rank changes who is next, not who is in flight, so it does not touch the isolated-load wait and it leaves the CPU memset exactly where it was. That refutes the worker's guess that arbitration strength is what over-slows the CPU stream: rank is not the lever for the dominant case. The remaining candidates (burst size, VI yielding to the CPU while its double buffer is not near empty, bank/row interleave with the CPU) have no published reference: ri.rank.vi, ri.rank.other and vi.burst are model-choice rows, sweeps of burst size (worker: 32 B fails Load Miss again) and rank give no improvement, and preference 7 forbids inventing the parameter. Genuinely unmeasured. Only calibration #16 (CPU uncached load latency histogram under VI on/off, and memset VI on/off) can decide.

## 4. Recommendation: (a) land now

- The structure is correct and reference-backed: VI as 15 x 128 B reads per active line at wire + 2 tc gap, refresh per HSYNC, MM shares inside the research band (7.39% / 1.33%), 0 tearing with a counter proven by mutation, determinism and round trip intact.
- Independent hardware evidence moved the right way: nemu64 11 -> 9, Load Miss VI on x2 newly pass (not fit data), 20.1 passes, cop0hazard 0/5.
- What got worse is by-value error on three bench rows (memset uncached -0.6 -> -3.6%, cached -0.3 -> +2.1%, sp-dma wr-4096 -0.1 -> -2.6%) and the 20.0 mean. Those rows are verify-is-fit with no VI in the fit data; master's closeness was fitted without the VI that the real console (very likely) had in those measurements, so it was not accuracy evidence. Under preference 2 I am not claiming a clean net gain; I am saying the PR is the better model of the hardware, with named residuals.
- (b) has no supportable scope: rank is refuted as a lever, burst size and VI-yield have no reference. A fix unit would be inventing parameters (pref 7). (c) throws away a correct mechanism that T13 needs; leaving T11 out would make T13 calibrate the RDP against a bus with no VI at all (thar0 VI-on configs).
- T13 hazard to carry forward: ri.overhead-rdp (20 units) copies the superseded VI-off fit; RDP now contends with real VI bursts. T13 should refit it, not inherit it.

Follow-ups to file (none block landing): relabel ri.overhead-vi model-choice and mark the cached-11 rejection as inference; 20.0 same-bank mean tail (41.6 vs 36.3, max 64-66 pclk) and the VI-vs-CPU interaction strength both wait on calibration #16; sp-dma off7f8 -5% unasserted; MM wall +4.2% (pref budget for T16).
