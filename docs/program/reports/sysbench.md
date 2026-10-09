# sysbench report

Status: done. Branch: feat/sysbench. Head: 8db33c424. Base: master 3beb066ea. PR: https://github.com/wScottSh/ares/pull/75.
Worktree: /home/wscottsh/repos/ares-wt/sysbench. Builds: ~/n64-timing/build/sysbench, sysbench-base, sysbench-083f18b0e (PI only), sysbench-caf3fbeb7 (PI+PIF). Homes: ~/n64-timing/sysbench-home-{base,head,083f18b0e,caf3fbeb7}. Raw: ~/n64-timing/results/sysbench/{before,after,before-newroms,wall}, mm600-<commit>.tsv.

Commits: 4ef5c2e09 ROMs; f70b7bda5 verify-74 notes; 083f18b0e pi.io-busy; caf3fbeb7 cpu.pif-ram-read; 604d5b809 dword read; 7d78bb625 spec regen; 8db33c424 mm-bench.md.

## What changed

**ROMs.** Five romgen bench ROMs re-implement the n64-systembench @845635c measurements the spec waited on. No code is copied; the original has no license, so only its numbers are cited (`src/main.c` file:line on every `expected.tsv` row).

| ROM | Points | Original |
|---|---|---|
| `uncached-sizes` | `c8..c64`, `u8..u64` | C*R and U*R, main.c:572-580 |
| `rcp-reg-read` | `c32`, `vi-control` | RCP I/O R, main.c:586 |
| `pif-ram-read` | `c32`, `pif-ram` | SI I/O R, main.c:599 |
| `pi-io-write` | `rom-word` | PI I/O W, main.c:595 |
| `si-dma` | `write64`, `read64-1..4` | SI DMA W RAM and JOY 1J-4J, main.c:597, 609-612 |

- `bench_multi` is TIMEIT_MULTI: 50 reps (10 for the SI write), the mean of all reps except the lowest and highest, in xcycles (main.c:105-127). `k_sb_while` is TIMEIT_WHILE's 8-poll loop (main.c:75-103). `report.py` rounds down to pclk or rclk as the original does.
- The original's harness adds about 2 pclk: its C32R of 3 less a 1 pclk cached hit. The port measures its own overhead the same way, from its `c<bits>` point: 2 pclk less the 1 pclk hit gives 1 pclk. `net_pclk` subtracts that overhead.
- Bands follow the original's pass rule: within 1 pclk or 2 rclk, or under 0.2 % (main.c:17-18, 664-669).
- JOY 2J-4J are report rows. The original does not say which ports held a controller, and n64-run connects one on port 1.

**Behaviors built.** Each is its own commit.

- `pi.io-busy`: `PI::writeWord` schedules `PiIoBusy` (134 rclk) in place of 200 pclk. The `legacy.pi.write-busy` row and its allowlist entry are deleted.
- `cpu.pif-ram-read`: `SI::readWord` adds `CpuPifRamRead - CpuRcpRegisterRead` for PIF RAM (0x7c0-0x7ff). The value is now 2959 pclk, **derived**: 1974 rclk = 2961 pclk, less the original's 2 pclk harness. PIF ROM reads are unmeasured and keep the register-read cost.
- `cpu.uncached-read-dword-total`: `SysAD::read<Dual>` takes `DwordReadPath`. The value is now 35 pclk, **derived**: U64R 37 less the 2 pclk harness.

**verify-74 notes.**

- `--check` blanks comments before it looks for `Timing::Behavior::X` reads, bare names, and code-pointer symbols. A new self-test case turns the ClockUnit static_assert into a comment. It fails with the old `core_sources`.
- The `ri.refresh-waits-for-burst` static_assert is dropped. The row's code column now points at `ares/n64/ri/bus.hpp:post` and `:decide`.
- Empty "Not built" sections now say none.

## Verification

Separate worktrees and builds, private `N64_TIMING_HOME` per tree, and every suite ROM rebuilt from each tree. `standing.sh` ran on base and then on head, back to back. Load averages: base 1.57 -> 4.25, head 2.54 -> 2.58.

New ROMs, base runner vs head runner:

| Check | Expected | Base | Head |
|---|---|---|---|
| uncached-sizes u64 net_pclk | 35 (34..36) | 32 fail | 35 pass |
| uncached-sizes u8/u16/u32 net_pclk | 32 (31..33) | 32 | 32 |
| rcp-reg-read vi-control net_pclk | 22 (21..23) | 22 | 22 |
| pif-ram-read sb_rclk | 1974 (1970.05..1977.95) | 15 fail | 1973 pass |
| pi-io-write sb_rclk | 134 (132..136) | 140 fail | 140 fail |
| si-dma write64 sb_rclk | 4065 (+-8.13) | 4065 | 4065 |
| si-dma read64-1 sb_rclk | 37987 (+-75.97) | 38477 fail | 38477 fail |
| read64-2/3/4 (report) | 57972/77924/97890 | 57890/77321/96734 | same |

The 140 rclk on `pi-io-write` is not a port defect, as far as I can tell. In ares the timed interval also holds the posted write's drain (`sysad.register-write` 5 rclk, a model-choice value) plus the store's issue. The original's 134 already includes its own hardware form of those costs. This breakdown is inferred from the code and was not traced. Nothing was refit.

Row status, master -> head:

- cpu.pif-ram-read and cpu.uncached-read-dword-total: not-built -> pass.
- cpu.rcp-register-read and si.write64: no-rom -> pass.
- pi.io-busy: not-built -> fail.
- si.read64-base: no-rom -> fail.
- The four legacy.si.dma-read-* rows: calibration-16 -> fail, through their guard `bench:si-dma-read64-1`.

**Standing values that moved.** Each was attributed by building the intermediate commits.

- **PIF commit.** The boot's PIF RAM reads now cost 2959 pclk each. Boot runs about 0.19 ms longer (emulated_s of the romgen ROMs; MM frame 0 cpu_cycles +19720), which shifts the phase of everything after it.
  - MM 600 `--stats` md5 56e118e2 -> be54e666. fb_hash differs on 369 of 600 frames.
  - mmbench: filesel-named 1.6884 -> **1.6723** fields per game frame (target 1.90-2.10, **worse**; 353 -> 357 gframes). filesel-rotate 1.0938 -> 1.0886. sct RSP clocks per field 1704305.6 -> 1692429.8. title, filesel, filesel-options and field moved by less than 0.1 %.
  - thar0: the mean buffer clocks of 25 of 100 rows moved, by at most 21 clocks (0.0065 %). Pass/fail is unchanged.
  - bench pi-dma-sizes cart-to-ram-8: 196.0 -> **197.33** rclk (expected 191.07..194.93, **one tick worse**). memset values moved by under 0.01 %.
  - pidma: 23770..23808 -> 23769..23828 of 24000, calibrated offsets 384 -> 448, verdict FAIL on both.
- **PI commit.** MM `--stats` changes only trace_hash, from frame 51 on: same cpu_cycles, fb_hash and rsp. mmbench, thar0, bench and pidma are identical to base.
- **dword commit.** MM `--stats` is identical to the PIF commit.
- Unchanged:
  - nemu64 timing, cycle and cop0hazard `values.tsv` are identical (Timing fails 9 of 1604 on both).
  - rdpstat, snapper and noise check results are identical.
  - det and stepcap PASS on both: nemu64 x3, and MM with 29 files and 8219 fields.
  - The round trip PASSes at 150/300/457, and the TMEM poke PASSes.
  - ctest 9/9 on both.
  - `--check` and lint report ok. The self-test runs 42 cases with 0 failed.
- The ROM sha256 list moved from d82b030d to fa2357d4. The 5 new ROMs were added. The old bench ROMs changed bytes because the shared asm grew, but their values on the PI-only core match base. Non-bench ROMs are identical.

**MM wall time.** Copied runners, 3 rounds interleaved, load 2.0-2.7. Base 22.74/23.22/23.07 s and head 22.71/22.89/23.14 s. The medians are 23.07 and 22.89 s.

## Deviations

- Commits 4ef5c2e09 and f70b7bda5 do not pass the build's `--check` on their own: the results and generated files lagged until 083f18b0e. Every later commit builds.
- The results committed in 083f18b0e..604d5b809 are interim. They were regenerated from the not-built/after run. 7d78bb625 regenerates them from this branch's run.
- `cpu.pif-ram-read` is now in pclk (2959, derived) rather than 1974 rclk (measured), so the harness overhead can come off.
- JOY 2J-4J are report rows, not checks.
- I added `bench:uncached-sizes-u32` to `cpu.uncached-read-total`. It is a second, independent check of the 32 pclk word read.

## Follow-ups

- pi.io-busy fails by 6 rclk. The likely parts are `sysad.register-write` (model-choice) and the poll sampling point. That has to be resolved first. A refit of either value would need a fit-from and an independent check.
- The SI RD64B 1J read is 1.3 % over (38477 vs 37987). `si.read64-base` and `legacy.si.dma-read-*` come from pif.estimateTiming.
- PIF ROM CPU read cost is unmeasured.
- n64-systembench measurements not yet ported: PI I/O R (144 rclk; ares charges 271 pclk = 181 rclk), U32R seq/rand/banked, SI DMA W ROM, SI I/O W, JOY empty and accessory.


## For the next unit

- PIF read cost shifts boot by ~0.19 ms: every boot-phase-sensitive standing value moves a little. Baseline new units on this head.
- n64-run has one pad (port 1); systembench JOY nJ for n>1 are report-only for that reason.
- No background process of mine is running. Intermediate worktrees removed.
