# verify-75: PR #75 (sysbench), head 8db33c424544851a94401ac8d606f22c69fce689, base 3beb066ea

Verdict: PASS-WITH-NOTES. Merge is safe. Do not act on the worker's pi.io-busy attribution (see N1).

Setup: worktrees ares-wt/verify-75 (head), ares-wt/verify-75-base; builds ~/n64-timing/build/verify-75-{base,head}; private homes ~/n64-timing/verify-75-home-{base,head}; raw in ~/n64-timing/results/verify-75/{base,head,baseruns-newroms,baseruns-oldrom}. standing.sh run base then head back to back, every suite ROM rebuilt from each tree. Load avg 1.5-6.6 (start/end in {base,head}/load-{start,end}.txt). No leftover processes. Extra scratch worktrees removed. Wall-time (pref 26) not re-run (not asked; MM wall unchanged in worker data, 22.7 vs 22.9 s).

## 1. ROM ports (read vs main.c @845635c)
Faithful. Checked line by line:
- TIMEIT_MULTI (main.c:105-127): original sums all reps but one min and one max, divides by n-2 in xcycles. Port bench_multi keeps min/max/sum in ticks; report.py sysbench() = (sum-min-max)*12//(reps-2), then //6 or //9 (floor). Equivalent, ties included (original adds a tied result to total, i.e. drops exactly one min and one max). Reps 50, 10 for the SI write: match (bench_sidmaw_ram 10, piiow 50, siior 50, joybus 50).
- TIMEIT_WHILE (main.c:75-103): 8 x (COUNT, poll), loop while 8th poll busy, tend = COUNT before first poll that saw idle. k_sb_while matches; mask 3 = DMA_BUSY|IO_BUSY for PI and SI status.
- Access sequences: C/U reads lbu/lhu/lw/ld with warm read outside timing for cached (match main.c:230-268); RCP I/O R = VI_CONTROL lw; SI I/O R = lw 0xBFC007C0; PI I/O W = sw to 0xB0000000, poll PI_STATUS (0x10 off PI base); SI DMA W = DRAM_ADDR setup, PIF_ADDR_WR64B (0x10) = PIF RAM, poll SI_STATUS (0x18); JOY nJ command blocks match buf[] layout in main.c:427-510 (n x 0xff010401ffffffff, 0xfe00.., zeros, 1), joybus_write ack/DMA/poll/ack then timed RD64B read (0x04) with out = rambuf+64.
- Expected values cite right lines (verified by grep): 572-575 C*R 3, 577-580 U*R 34/37, 586 RCP 24, 595 PI W 134, 597 SI W 4065, 599 SI R 1974, 609-612 JOY. Pass rule: diff <= meas_error or <0.2% (main.c:664-669); meas_error CPU 1 pclk, RCP 2 rclk (4 pclk * 6 /9): bands match.
- Harness: original C32R 3 pclk, less cached hit 1 = 2 pclk. Port c32 = 2 pclk (min=max=1 tick), less 1 = overhead 1 pclk, subtracted per point. Same method. Independent cross-check of the original's "2": its U32R 34 vs nemu64-test's 32 (existing cpu.uncached-read-total).
- Nit: expected.tsv text "as its's C8R" typo (4 rows).
- Nit: pif-ram-read and pi-io-write/si-dma compare raw sb_rclk (port harness 1 pclk vs original 2). Gap 0.67 rclk, far inside the bands; harmless but the pif check cannot resolve +-5.9 pclk.

## 2. Before/after, new checks (base runner vs head runner on the same head-built ROMs)
| check | expected (band) | base | head |
|---|---|---|---|
| uncached-sizes u8/u16/u32 net_pclk | 32 (31..33) | 32 | 32 |
| uncached-sizes u64 net_pclk | 35 (34..36) | 32 fail | 35 pass |
| rcp-reg-read vi-control net_pclk | 22 (21..23) | 22 | 22 |
| pif-ram-read sb_rclk | 1974 (1970.05..1977.95) | 15 fail | 1973 pass |
| pi-io-write sb_rclk | 134 (132..136) | 140 fail | 140 fail |
| si-dma write64 | 4065 | 4065 | 4065 |
| si-dma read64-1 | 37987 | 38477 fail | 38477 fail |
| read64-2/3/4 (report) | 57972/77924/97890 | 57890/77321/96734 | same |
Identical to worker's table. pi-io-write is 140 on BASE too (old 200 pclk = 133.3 rclk), so the PI commit changes nothing the check sees (see N1).

## 3. The three builds
(a) cpu.pif-ram-read 2959 pclk: systembench siior is one plain uncached lw of 0xBFC007C0 per rep (main.c:218-220), no DMA, no state. 1974 rclk = 2961 pclk; less harness 2 = 2959. Every CPU PIF RAM read is that one SI I/O transaction, so applying it to every read is what was measured; SI::readWord still returns early if SI io is busy. Independent corroboration in cpu-memory-costs.md: gopher64 3000 CPU cycles per PIF read, MiSTer floor 1910 rclk. Code: 23672 units = 2959*8, subtracts the 176 already charged by RCP::read, range (addr&0x7ff)>=0x7c0. Two caveats: an LD (Dual) from PIF RAM calls readWord twice so it pays twice (unmeasured, rare); PIF ROM keeps register cost (documented). Boot effect: I instrumented a scratch build: 7 PIF RAM reads in 600 MM frames, all at boot (also 7 in 3 frames; addrs 1fc007fc x5, 7e4, 7f0), not "about 6". 7 x 2937 = 20559 pclk added; MM frame 0 cpu_cycles 58259184 -> 58278904 (+19720), smaller than 20559 because the boot waits on absolute-time events. Plausible.
(b) cpu.uncached-read-dword-total 35: U64R 37 less 2 = 35. The 3 pclk dword-over-word step (37-34) is independent of the harness assumption, and 32+3 = 35 agrees. Honest. Applied only in SysAD::read<Dual> via throughRi (RDRAM).
(c) pi.io-busy 134 rclk still 140: the check fails honestly, but the worker's explanation is wrong or at least unsupported, and I measured the real cause. The kernel is a poll loop with ~25 pclk (16.7 rclk) spacing, and ares is deterministic, so every rep has the same phase between the write and the polls; hardware's 134 is a mean over random phases. I built variants of the ROM with N extra nops (N=0..42) between the store and the poll loop on the head runner. Result sawtooth with period 25 nops, range 125.3 to 141.3 rclk; mean over one full period (N=11..35) = 133.4 rclk (floor 133, band 132..136: pass). N=0 sits near the top of the tooth (140). So busy = 134 rclk is consistent with the systembench figure once phase-averaged; no evidence for a 6 rclk excess from sysad.register-write (5 rclk) + issue. Consistent with base giving the same 140 for 133.3 vs 134 busy. Caveat: assumes hardware poll spacing is similar to ares's (22 pclk register read), so this is consistent-with, not proof. Recommendation: do NOT refit sysad.register-write or PiIoBusy; instead make the ROM average over phase (per-rep nop jitter of 0..24) or drop the row's single-phase check. The spec text does not record the worker's wrong cause (it is only in the report).

## 4. Moved standing values (all reproduced)
- MM 600 --stats md5: base 56e118e2..., head be54e6668112d49045b2072a9f98eaa5. Matches.
- filesel-named 1.6884 (353 gframes, 68.8% at 2 fields) -> 1.6723 (357, 67.2%); target 1.90-2.10, FAIL both. filesel-rotate 1.0938 -> 1.0886; sct 1704305.6 -> 1692429.8. Cause: only the 7 boot reads move; after that the model is unchanged, so this is a boot-phase shift, not a new per-frame cost. Not provably a regression of a model, but it is a measured move in the wrong direction on a failing check; the check was not fit to anything, so treat as noise-magnitude (-1%) on an already failing row. I did not run a phase-sweep to bound the noise.
- pi-dma-sizes cart-to-ram-8: 196.0 -> 197.33 (band 191.07..194.93, fail both; one COUNT tick). Base runner on head ROM = 196.0, so it is the core (boot phase), not the ROM bytes.
- thar0: 25 of 100 rows moved, max |delta mean ares| 21 clocks; summary identical otherwise.
- pidma: 23770..23808/24000 -> 23769..23828/24000; offsets 384 -> 448; FAIL both.
- Report rows not in worker's list: uncached-vs-hpos bank5 median_pclk 34 -> 36 (hardware 32; base runner on same ROM gives 34, so it is the core), holdoff_rclk_max moves mostly from ROM bytes (36 -> 49.3 base runner -> 48), dirty-single 46 -> 48 (no hardware value). Report-only, small, same boot-phase cause likely.
- nemu64 timing/cycle/cop0hazard values.tsv: cmp identical x3 (Timing fails 9 of 1604 both). rdpstat/snapper/noise: no result changes (diffs are emulated_s/wall and the noise first-pixel clock, which follows boot). det PASS (nemu64 x3; MM 29 files, 8219 fields), stepcap PASS, round trip PASS 150/300/457, TMEM poke PASS, ctest 9/9 both, --check ok, --self-test 42 cases 0 failed, lint ok, pidma-replay self-test 5/5.

## 5. Net accuracy vs hardware references
Improved: cpu.uncached-read-dword-total (u64 32 -> 35 pass), cpu.pif-ram-read (15 -> 1973 pass vs 1974), si.write64/cpu.rcp-register-read now checked (pass). Regressed (all already failing, small): filesel-named 1.6884 -> 1.6723 (target 1.90), pi-dma cart-to-ram-8 196 -> 197.33 (band top 194.93), uncached-vs-hpos median 34 -> 36 (hw 32, report). Mixed/neutral: thar0 25 rows +-21 clocks, pidma band edges. No check flipped pass -> fail. 2 flipped fail -> pass; 3 previously unmeasured rows pass; 2 new rows fail (pi.io-busy spurious per N1; si.read64-base 1.3% over, real, from pif.estimateTiming).

## 6. --check comment stripping
Mutation: bus.hpp:78 -> `scheduleAfter(..., pclk(134)); //Timing::Behavior::PiIoBusy` in a scratch worktree. New --check: flags the literal and "no code reads Timing::Behavior::PiIoBusy"; the base behaviors.py (git show 3beb066ea) emits no "no code reads" error for the same tree. Self-test case added by the PR covers ClockUnit-in-comment. Regex handles strings, chars, digit separators. Interim commits: 4ef5c2e09 and f70b7bda5 fail --check (3 errors: generated header/spec out of date); the build runs --check (my first scratch build died on it), so those two commits do not build. 083f18b0e..8db33c424 all --check ok. Acceptable if merge commits land only the head (preference 17: merge commits), but it hurts bisect of the second-parent side; flag only.

## 7. Diff hygiene
- legacy.pi.write-busy: row and allowlist entry deleted; no stale reference in ares/ or checks. Left: tools/n64-timing/codemods/clock-rebase.py:103 still lists "legacy.pi.write-busy" (historical one-shot codemod; harmless, could be dropped); docs/program/reports/t4.md history.
- Dropped ri/bus.hpp static_assert(RiRefreshWaitsForBurst) leaves a bare comment `//post() sets the next decision...` with no code under it (ares/n64/ri/bus.hpp:134): a compile-time guard removed as a verify-74 follow-up; scope is declared in the report.
- Comments are why-comments citing refs; timing constants cite main.c lines. No scope creep beyond declared. Interim result files in 083f18b0e..604d5b809 are regenerated in 7d78bb625.
- Worker claims not reproduced: none failed. Worker claim not supported: pi-io-write cause (N1); "about 6 reads" is 7.

## Recommendation
Merge. Follow-ups: (1) pi-io-write: add per-rep phase jitter (or report-only) and do not refit sysad.register-write; (2) note the 7 boot PIF reads in the spec row; (3) consider whether PIF Dual reads should pay once.
