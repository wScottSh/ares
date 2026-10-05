## Verify #57 (T8): PASS-WITH-NOTES

Independent build of base `0eeaa278f` and head `808e5f54b` (RelWithDebInfo, clang 22, dirs `build\verify-57-{base,head}`), same suite driver and ROMs both sides. The worker's headline claims reproduce.

### Reproduced (raw)
| Check | base | head |
|---|---|---|
| nemu64 timing / cycle / cop0hazard failed | 453/1604, 9/13, 5/5 | 453/1604, 9/13, 5/5 |
| nemu64 `values.tsv` (timing 1605 lines, cycle 14, cop0hazard 6) | | `cmp` byte-identical to base, 0 moved |
| stepcap nemu64 x3 | PASS | PASS |
| stepcap MM | PASS (27 files, 8158 fields) | PASS (27 files, 8158 fields) |
| det MM | PASS (27 files, 8158 fields) | PASS (27 files, 8158 fields) |
| state-roundtrip + TMEM poke | PASS | PASS |
| ctest (head build) | n/a | 5/5 PASS (timeline, ri-cost-table, ri-split, dpc-regs, rdram-private) |
| `behaviors.py --check`, `lint-literals.py` | | ok, ok |
| MM mmbench 7 scenes | all reach window | all reach window, rc 0 |

### unit:rdram-private negative control
Scratch worktree at head with one line changed (`private:` to `public:` at ares/n64/rdram/rdram.hpp:285). Both probe variants compiled; `ctest -R rdram-private` FAILED ("no longer private to the RI"). The guard catches a real regression.

### pidma (`tools/n64-timing/pidma-replay.py`; my own run of pi_dma_test.z64 --frames 3000 with `ARES_PILOG`)
Sizes 8-382 within +-3% of golden min..max, out of 24000:

| build | offset (read,write) units | pass |
|---|---|---|
| head | 0,0 (uncalibrated) | 22438 |
| head | 144,0 / 152,8 / 160,4 / 168,15 / 183,15 | 23763 / 23763 / 23798 / 23799 / 23834 |
| base (master plus the PR's PILOG commit cherry-picked, so base can log) | 144,0 / 160,4 / 183,15 | 7218 / 7085 / 6955 |

`--calibrate` on head: printed values {(4,3):112,(4,4):111,(6,4):112,(12,3):112,(12,4):111,(14,3):112,(14,4):111,(22,4):112}, best worst-case error 1 tick, 448 (read,write) pairs, read 144..183. On base the same eight-value fit gives the same read range. Head ~23.8k vs base ~7.0-7.2k reproduces the claim (worker: 23763-23834 vs 7346 on feat/t6).

Calibration soundness: the shifts are CPU code-path constants (PI event to COUNT read) fitted to values the ROM printed in the same ares run, i.e. to ares's own COUNT measurement, not to hardware. The hardware golden logs are not used in the fit, so the fit cannot inflate the hardware match. Weaknesses: only 8 printed values, all at sizes 3-4 (below the scored 8-382 range), so a size-independent shift is assumed; the read shift is pinned only to 40 units (~2.5 ticks). Sensitivity is bounded: across the whole feasible read range the pass count moves 23763-23834 (0.3%). Uncalibrated (0,0) gives 22438, so a shift is needed, but "~23.8k" holds over the entire feasible set. Verdict: sound; the 1-tick uncertainty is real and small against the effect size. Residuals by size band on head: 0-31 B up to +15% off hardware, 32-63 B -5.6..-5.9%.

### Benches (head; base)
| bench | head | base |
|---|---|---|
| pi-dma-sizes 8 B (193 +-1%) | 197.33 FAIL | 196.0 FAIL |
| 128 B (1591) | 1600.0 pass | 1600.0 pass |
| 1 KiB (12168) | 12174.67 pass | 12000.0 FAIL |
| 64 KiB (777807) | 778498.67 pass | 777960 pass |
| sp-dma-sweep wr-4096 B/rclk (6.5, 6.49..6.515) | 6.495 pass | 7.797 FAIL |
| sp-dma-sweep rd-4096 (report, hcs64 5.55) | 5.216 | 7.797 |
| mi-memset-rspdma b_per_rclk (6.5) | 6.473 FAIL (ms/MiB 2.5919 vs 2.575..2.585) | 7.998 FAIL |

The worker's table cell for rd-4096 (5.189) is stale; their own after2/bench.txt and mine both say 5.216. mi-memset-rspdma still fails its band on head (-0.4%); the worker lists it as a follow-up but gives it no fail mark in the table.

### MM RSP busy per field (mmbench, 4 jobs; head vs base)
title 397472 vs 376850 (+5.5%), filesel 482978 vs 458752 (+5.3%), filesel-named 736864 vs 703933 (+4.7%), filesel-options 684650 vs 652206 (+5.0%), filesel-rotate 724367 vs 690897 (+4.8%), sct 1310047 vs 1283221 (+2.1%), field 1333563 vs 1289198 (+3.4%). Worker said +1.4-5.5%; I read +2.1-5.5%. Total mmbench wall 72.3 s head vs 73.2 s base (parallel, noisy); no wall regression seen.

### Code read
- SP DMA (rsp/dma.cpp): burst = `RiBus::split(dramAddress, rowLeft)` capped at `SpDmaBurst` (128 B); `split` clips to the 2 KiB row (`0x800 - (addr & 0x7ff)`); unit:ri-split covers it. `dramAddress`, `pbusAddress` and `rowLeft` advance in `granted()`, one burst in flight, next posted at `g.dataEnd`. Busy reads via `busyAt` until the last dataEnd. Matches the claim.
- PI (pi/dma.cpp): blocks clipped at row end and 128 B; fill at BSD timing; write burst; `piBlockPath` = 28 rclk minus request latency, half-rclk edge wait and wire. `dmaDuration`, `dmaQueue`, `dmaTransferStep`, `dma.landing` have no remaining references. `PI::readWord` now steps `writeForceFinish(...)` once (the old code stepped `remaining + remaining`); the double charge is gone.
- `pi.halfword-bias` 2 rclk is a new `wiki` row with a named source. `PiEdgeWait` (0.5 rclk) and the row-hit assumption in `piBlockPath` are code-only constants with no row.
- ri.overhead-write 1.7 to 1 rclk: row, hpp and spec are consistent; the reference text states honestly that rclk-edge quantization drives the change (17 + 1 + ceil). `check` = bench:mi-memset-rspdma, `fit-from` = that plus bench:sp-dma-sweep, `verify-is-fit` note kept, spec still prints "fit only, no independent check". `behaviors.py --check` ok. `ri.overhead-rdp` text now cites the unquantized 1.7 fit; value unchanged at 20 units.
- RI refresh rule (ri/bus.cpp RI::refresh, lines 13-16): HSYNC adds no refresh while one waits or runs. Only a code comment calls it specific to short VI lines; no reference cited.
- rdram.hpp friends: AI, PI, PIF, RSP removed; RI, MI, Loader, VI, RDP remain (documented deviation).
- Dead code: none found. Removed legacy rows and literals are cleaned in the allowlist, behaviors.tsv and the spec.

### Notes (not blocking)
1. **The new RI rule is not labelled in the spec.** The latch lives only in a source comment (ri/bus.cpp:13-16) and the worker report. No behaviors.tsv row (model-choice, "none published"), and `ri.refresh-trigger` (hsync, wiki) is unchanged, so the spec still reads as one SetRR per HSYNC without exception. It needs a model-choice row or a note on `ri.refresh-trigger`.
2. PI `PiEdgeWait` and the row-hit assumption: code-only model choices, no row.
3. mi-memset-rspdma fails its own band on head (6.473 vs 6.49..6.515); the grid quantizes the fit to 19 or 20 rclk per 128 B, so it cannot hit 19.7. The change trades a +20% miss for a -0.4% miss and the check stays red.
4. pidma: sizes 8-31 B are up to +15% off hardware; the worker's "~12 rclk below the hardware midpoint at every size" is inferred, unreferenced. Head still stops the ROM's own 10% self-check at its cap of 8 failures (sizes 3-4).
5. pi-dma-sizes 8 B fails on head (197.33 vs 193 +-1%), as on base (196.0). The poll-phase explanation is plausible but I did not test it.
6. Report table cell sp-dma-sweep rd-4096 5.189 is stale (actual 5.216).

### Not reproduced / not run
- Worker's interleaved master-vs-head wall table and the sct grants-per-field table: not rerun. `bench:si-dma` has no ROM.
- Base pidma uses master plus the PR's PILOG commit (e34c5e367 cherry-picked in a scratch worktree) because master has no log hook; the worker's 7346 was on feat/t6.

Raw outputs: `C:\Users\Scott\n64-timing\verify\t8\` (out-head, out-base, mm-head, mm-base, head-pilog.txt, base-pilog.txt).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
