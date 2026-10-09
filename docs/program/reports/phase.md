# phase report

Status: done. Branch feat/phase, head 584b9fdac, base master 5718d2124. PR: https://github.com/wScottSh/ares/pull/78. Issue filed: https://github.com/wScottSh/ares/issues/77.
Worktree /home/wscottsh/repos/ares-wt/phase. Build ~/n64-timing/build/phase. Private homes ~/n64-timing/phase-home and phase-home-base. Raw results ~/n64-timing/results/phase/: before, after, scan-dense (872 delays, first layout), scan-dense2 (872 delays, final layout), scan-walk32, scan-walk32b, scan-exp, scan-pre76full, thar0-walk, wall, benchtime, and bench-compare.txt. The scratch worktrees phase-base and phase-exp are removed. No processes of mine are running (checked by PID).

## Item 1. The boot-phase walk

- **Harness.** `romgen/runtime.py` `BOOT_DELAY_LOOP` is inserted only for sets that define BOOT_DELAY (bench). `li` is always 2 words, so the code size is the same at every delay. `suites/bench/phases.py` lists `DELAYS = [1 + 41*i for i in range(32)]`, and `N64_BENCH_DELAYS` overrides it for scans. `build.py` writes `roms/bench/boot-<K>/`. `run.sh` runs every (delay, ROM) pair through xargs with 4 runners. `report.py` writes measurements.tsv (with a boot_delay column), phases.tsv and results.tsv (min, median, max, mean, rule, verdict).
- **Rules.** expected.tsv has a new `rule` column. `report.py` `verdict` enforces it, and `behaviors.py --check` rejects a check row without a valid rule. A self-test case covers that (43 cases now).
  - `consistent`: the band overlaps the phase range. 27 rows, the n64-systembench ports. TIMEIT_MULTI reps are phase-locked (VI and interrupts off, main.c:623-624, one master clock). That is inferred, in sysbench2 and verify-76.
  - `mean`: the phase mean is in the band. 8 rows, `mi-memset-*` and `sp-dma-sweep`. The n64brew memset times span about 41 (rspdma) to 780 (cached) VI lines, so they average refresh and fetch phase. The SP DMA 6.5 is that memset's average over 256 DMAs.
  - `every`: every delay is in the band. 9 rows, the RDP fixed costs and hpos refresh-per-line.
  - Each row's source text states its rule and why.
- **Poll range.** For TIMEIT_WHILE points (`walk=poll`), bench_multi stores `max2`, the second highest rep, at RES[3]. The kernel a1 is now &RES[4]. `report.py` takes `min`..`max2` as the model's poll-phase range (`sb_rclk_rep_min`/`_rep_max`). pi-io-write reads 94..107 ticks = 125.33..142.67 rclk, which matches verify-76's fixed-N scan of 125..142.
- **Periods.** All measured.
  - One loop iteration is 3 pclk. The idle VI's 0x800-VCLK line event is 3944 pclk = 1313 iterations.
  - mi-memset-rspdma dips at K = 1 and 1300 to 1316 (step 1), and near 2611, 3924 and 5237 (step 13). The 872-delay scan includes geometric steps to K = 625302, about 1.2 fields, and found no value past one period that the first period lacked.
  - The CPU poll loops are 25 and 26 pclk. 41 iterations = 123 pclk, and 123 mod 26 = 19, so the 32 delays land on 32 poll phases.
- **Delay count.** 32 delays give the same verdict on every check as all 872, on both ROM layouts (diff of summary verdicts). Against a uniform one-period reference of 101 delays, the 32-delay mean is off by 0.001 for mi-memset-rspdma (6.495 vs 6.496) and 0.02 for sp-dma-sweep (6.361 vs 6.334..6.346). Neither is near a band edge that would flip.
- **Cost.** Measured at load average 15: 19 s to build the 640 ROMs and 28 s to run them with 4 runners. The whole standing run took 12m44s, against 12m18s for the base. The bench results are byte-identical across two runs (benchtime vs after).

## Item 2. Every row; the four relabels

- **Rules.** Every check row has a rule. The four relabels:
  - pi-io-write reads 125.33..142.67 against 132..136. Consistent, pass.
  - si-io-write reads 2149.33..2166.67 against 2153.7..2162.3. Consistent, pass.
  - write64 reads 4058.67..4069.33. Consistent, pass.
  - write64-rom reads 2136.0..2149.33. Consistent, pass.
  - Their source text says the hardware number is one phase of a 16.7 rclk poll sawtooth, with about ±8 rclk of poll quantization, and that the check is consistent-with, not ±2 agreement (verify-76 section 2).
- **behaviors.tsv notes.** The pi.io-busy, si.io-busy, si.write64-rom and si.write64 notes now say their values carry about ±8 rclk of poll quantization and that their checks pass by construction. si.write64 is the same case as the other three, so its note is added too (deviation). behaviors.hpp is regenerated: the strings change, not the timing.
- **pi-dma-sizes.** This deviates from a pure relabel. The hardware number is TIMEIT_WHILE_MULTI(10) (main.c:171-180), one poll phase. The old port took the min of 4 reps of one DMA with VI on, and the boot walk barely moves its poll phase (196.0/197.33 at all 872 delays). So consistent-with could not be honest without a poll walk.
  - The port now uses k_sb_while, which takes a second setup write (PI_DRAM_ADDR, PI_CART_ADDR), runs 10 reps with 5-nop jitter and blanks VI.
  - The metric is now `sb_rclk`, and the checks.tsv selector changed with it.

## Verdict changes, old (base standing run) vs new (head standing run)

| check | old | new: phase range, rule |
|---|---|---|
| bench:mi-memset-rspdma | fail 6.423 | pass 6.422..6.501, median 6.498, mean 6.495 (mean, band 6.49..6.515) |
| bench:pi-dma-sizes | fail, cart-to-ram-8 197.33 | pass: 8 B 180.0..194.67 (hw 193), 128 B 1574.67..1592.0 (1591), 1 KiB 12156.0..12169.33 (12168), 64 KiB 778332.0..778345.33 (777807), all consistent |

- **Unchanged verdicts.** All other bench checks keep their verdicts. Full old/new detail is in ~/n64-timing/results/phase/bench-compare.txt.
  - sp-dma-sweep still fails at 6.169..6.693, mean 6.361 (mean rule).
  - u32-banked still fails at 131..132.
  - empty-0b still passes at 15060, the band edge.
- **Row status.** Unchanged: pass 67, fail 36, no-corpus 15, fit only 10. Both flipped checks sit on rows that a failing check also decides: ri.overhead-write fails on sp-dma-sweep, and pi.page-setup, halfword-bias and block-writeback fail on pidma:logs.
- **Caveat.** The pi.block-writeback reference says "fit to systembench PI DMA rows", but its fit-from column is empty. The pi-dma-sizes pass is therefore weak evidence for it.
- **Layout moves.** Some values moved because the code layout changed, not the core. The same core runs both and MM is identical. pi-io-read went from 142 to 143, rcp-reg-read net from 21 to 22, the write64 mean from 4067 to 4065, the write64-rom mean from 2147 to 2143, and the u32-rand median from 131 to 132.
- **Intermediate flips, both resolved.**
  - With the first layout, u32-banked read 131..133 and passed as consistent-with. The final layout reads 131..132 and fails. Layout is a phase the boot walk cannot reach (follow-up).
  - uncached-vs-hpos read 0.667 at all 872 delays once the boot loop was in. The ROM's line estimate fell from 2975 to 2926 ticks, which pushed the window's last HSYNC outside the window. report.py now counts only interior HSYNCs (lines 1..full_lines-1). It reads 1.0 on both layouts, and on master's raw output too.

## Item 3. The head-core mi-memset-rspdma 6.42 plateau

- **Mechanism.** Measured. It is the VI enable phase, not thread scheduling and not legacy.pif.step-quantum.
  - While VI_CONTROL selects no type, `VI::line` steps 0x800 VCLKs (ares/n64/vi/vi.cpp:112). The first active line after `vi_init` writes VI_CONTROL starts on that grid, which runs from power-on. So the VI line phase against the program depends on where the boot ends modulo 3944 pclk.
  - When the grid event falls between the VI_CONTROL write and the VI_H_SYNC write, the VI runs 1-VCLK lines, because `quarterLineDuration + 1` is 1 with H_SYNC = 0, and with V_SYNC = 0 every line is a field. `--stats` at K=3 shows 6 fields with cpu_cycles 16063938..16064034. The line phase then locks to the H_SYNC write. That is the 6.42 case: the VI fetches 11520 more bytes in the run (bus counters, K=3 vs K=20).
- **Proof 1.** A scratch build with the idle step at 1 VCLK (activation follows the write) gives the same value at all 45 delays tried. mi-memset-rspdma reads 6.422 and sp-dma-sweep wr-4096-off0 reads 6.334 at K = 1 to 40, 100, 200, 400, 1000 and 2000 (scan-exp).
- **Proof 2.** The pre-#76 core (build/verify-76-base) shows the same dip at K = 426 to 450 (scan-pre76full, 1320 delays). verify-76's "base flat over 49" was a sampling miss: its delays skipped 426..450. PR #76's boot-time change moved the window onto the shipped ROM's boot.
- **Not fixed.** No reference says whether the hardware VI counts while blanked or when line 0 starts after enable. Immediate activation would be a model choice, and it moves VI-on bench values. Its effect on MM was not measured.
- **Recorded.**
  - Issue #77, with the experiments.
  - The literal-allowlist note on `step(0x800)`, which claimed "no register sees it", now says it sets the VI line phase at enable.
  - The bench walk covers one full grid period, so no verdict depends on where the grid lands.

## Item 4. thar0

- **Not walked. Decision based on measurement.** thar0 was built at 6 boot delays (1, 333, 667, 1000, 1500, 2600) from a scratch tree.
  - 26 of 100 rows move their model avg by up to 54.6 clocks, on zbrw-pass-zbsame-visame-noimrd-1cyc: 271695.7..271750.3 against 271k.
  - No verdict differs between any delay and master. The 4 passing rows (alpha-fail VI-off) have zero spread. The closest failing row is 258 clocks outside its console range, also with zero spread.
- **Rule.** The thar0 rule already compares against the console's min..max over 1000 runs, a phase spread of its own.
- **Cost.** Each delay costs 44 s of runner time. That is real cost for no verdict signal, so thar0 is recorded and not walked.

## Standing checks, before / after (load 11.6-18.1 before, 15.6-20.6 after)

- **Identical outputs.**
  - MM 600 --stats is byte-identical (md5 210d0d4625788e5e8d0e1d74be65a07f).
  - The nemu64 timing, cycle and cop0hazard values.tsv are byte-identical.
  - Also identical: thar0 compare.tsv, the mmbench summary.tsv, and every non-bench line of n64-timing-results.tsv.
  - The before run reproduces master's committed results file exactly (after rerunning noise, whose binary sat beside the copied runner).
- **Checks.**
  - det and stepcap PASS: nemu64 x3, MM 29 files, 8219 fields.
  - The state round trip and TMEM poke PASS.
  - ctest 9/9.
  - behaviors --check is ok, --self-test passes 43 cases with 0 failed, lint-literals is ok, and the pidma-replay self-test passes 5/5.
  - The bench selftest passes 22 cases (10 new: rep range, max2, phase stats, each rule's pass and fail, a missing delay).
  - The romgen assembler self-test passes 72/72.
- **ROMs.** Lists: before 35 ROMs (sha256 prefix df296edc, which matches verify-76 head), after 655 ROMs (f6bb9434). The non-bench ROMs are identical. Two bench builds are byte-identical.
- **MM wall** (pref 26). Copied runners, interleaved, load 13-15. Base 26.85 / 26.70 / 26.68 s, head 26.66 / 26.85 / 26.72 s. No change.

## Deviations

- The pi-dma-sizes port is rebuilt as TIMEIT_WHILE_MULTI(10) with a poll walk, VI blanked, and metric sb_rclk. Without this the consistent-with rule would be dishonest for it.
- uncached-vs-hpos rate counts interior HSYNCs (report.py). This fixes a layout fragility that the boot loop exposed.
- bench_multi records max2 at RES[3]. Kernels get &RES[4] (no kernel used a1).
- results.tsv drops its `value` column. min, median, max and mean replace it. behaviors.py prints the range as `min..max median M mean A`, or a single value when every delay agrees.
- `standing.sh` clears `roms/bench` and `results/bench` before building, so ROMs from another delay list do not linger.
- The si.write64 note is added alongside the three named rows.
- The literal-allowlist note is corrected. No code changed with it.
- Commit trailers use the session's attribution line ("Claude Opus 5.5").
- The results header names 172bddb00, then 48be98188, because the results were re-derived after report-only commits. The bench ROMs and the runner are unchanged since the standing run at 7f393fbe9.

## Follow-ups

1. #77: the VI first-line timing after enable needs a hardware reference (calibration #16 class).
2. The si-dma JOY points (read64-*, empty-*, accessory) end on a one-read poll the port does not walk. Their range covers boot phase only. No verdict is near flipping except empty-0b at its band edge.
3. u32-banked moves with code layout (131..133 vs 131..132), which the boot walk cannot reach. A layout walk (padding variants) would close it.
4. pi.block-writeback: its reference says fit, but it has no fit-from (pref 21 labeling gap, pre-existing).
5. The hpos ROM estimates the line period from one line. Measuring over several lines would also make line_ticks robust.

## For the next unit

- Bench ROMs now live in `roms/bench/boot-<K>/` (32 delays). Behaviors' ROM gate matches `./bench/boot-*/bench-<rom>.z64`.
- To scan, set `N64_BENCH_DELAYS=K,K,...` and run build.py and run.sh. Scratch driver: scan.sh in this session's scratchpad. The pattern is build.py with the env var, then run.sh with BENCH_ROMS/BENCH_RESULTS.
- A bench value is now a range. Read results.tsv min/median/max/mean under the row's rule, not one number.
