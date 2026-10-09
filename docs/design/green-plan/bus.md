# Green plan: cluster `bus` (RDRAM channel, SysAD drains, VI fetch, refresh)

Investigator: plan-bus, 2026-10-09. Base: origin/master 8d86b87cd.
- Worktree: /home/wscottsh/repos/ares-wt/plan-bus (detached master, plus uncommitted env-gated experiment knobs; the patch is saved).
- Build: /home/wscottsh/n64-timing/build/plan-bus.
- Results: /home/wscottsh/n64-timing/results/plan-bus/.

Labels: **[M]** measured this session (the command and file are named), **[C]** cited, **[I]** inferred, **[G]** guess.

## 0. What I ran (so a reviewer can rerun it)

- **Experiment knobs.** The patch is `exp-knobs.patch`. Each knob is an env var, and the default is byte-identical to master. With no knob set, the bench run reproduces the standing values exactly **[M]** (memset 17.716..17.718 / 72.735..72.738, rspdma 6.492..6.501, sp-dma 6.169..6.678 mean 6.35, u32-banked 131..132).
  - `PB_BLANK=1`: posts a refresh at each idle-VI line (TYPE=0).
  - `PB_BLANK=2`: does the same, and the idle VI keeps its programmed H_TOTAL line instead of the 0x800 grid.
  - `PB_LINE=N`: sets the idle line length.
  - `PB_RETRY_TC=N`: clean row-miss retry in tc. Dirty stays clean + 8.
  - `PB_VIBURST=N`: VI segment size.
- **nemu64 probe.** `mkprobe.sh` and `runprobe.sh` build 4 nemu64-timing ROMs from master's romgen. In each ROM one averaged statistic (min, max, median or sum) is forced to fail, so its value prints. Layout is unchanged: only the range numbers change. ROM sha256s are in `probe-rom-sha256.txt`, and the ROMs are in `probe-roms/`. Raw tables are `nemu64-probe-<knob>.txt` and `scan/L*.txt`.
- **Bench.** 8 ROMs × 32 boot delays, rebuilt from my tree (pref 25), with outputs in `home/res-{base,PB_BLANK=2,PB_RETRY_TC=11}/results.tsv`.
- **systembench.** The calib-kit-merge era stage binary (sha prefix 094b29fc; not rebuilt, docker build skipped), with outputs in `home/sb-*.log`.
- **n64brew.** I fetched the raw wikitext and the full revision history of MIPS_Interface (`n64brew-MIPS_Interface-history.json`), plus Video_Interface and RDRAM_Interface.

## 1. The three key questions, settled as far as evidence allows

### Q1. Is the n64brew memset table VI-on or VI-off? Can a published source decide it?

**No published source decides it [C].**
- The table entered n64brew MIPS_Interface in rev 5278, 2023-11-13, by user Phire. The edit comment is "Rewrite RepeatMode with better examples". Rev 4988, the earlier MI_MODE write-up, has no table [M, fetched].
- No revision states the loop code, the video state, the run count or a source link. There is no Talk page.
- phire's GitHub has only a libdragon fork with no matching branch [M, gh api].
- Web and code search found nothing that names the benchmark [M].
- The only remaining source is the author. Contacting him is an external message (Always-pause), and Scott's call. Scott declined the analogous jgemu contact (#25).

**The data cannot separate the two readings, because they are confounded [I].**
- **VI-off table.** Integer SClock drains fit. Periods 12/12 and ri.overhead-write 1 gave -0.56% / -0.34% / -0.4% (T6 and T8, measured then).
- **VI-on table.** The model's VI contention costs the uncached stream 1.3-1.65 pclk/SD. That needs a non-integer raw drain of about 11.2 rclk, which the rclk grid cannot produce: 11 gives -3.6% and 12 gives +5.5% (t11-fix).
- **VI-on table, VI half as costly to the CPU as modeled.** 12 rclk fits again.
- The third reading is the independent nemu64 evidence in Q3. So the memset rows and nemu64 point at the same model property: the CPU-visible VI cost. Neither proves the table's video state.

**Decider.** Kit question `memset-vi` (q20): the four memsets with the VI on and blanked. The VI-on minus VI-off difference on hardware also measures the CPU-visible VI cost directly.

### Q2. Is the D-fill tail refresh? If refresh is off before VI init, what else gives a 42.5 mean?

**The two n64brew pages conflict [C].**
- Video_Interface: "setting VI_CTRL.TYPE=0 ... will totally stop VI activity (no output signal)".
- RDRAM_Interface: "VI HSYNC defaults to 41us on power-cycle. This results in a 10.5ms refresh cycle, causing a noticeable memory bandwidth reduction until the VI is configured". That is a TYPE=0 state.
- PIF ROM "stop the VI" writes only VI_INTR, H_START=0 and V_CURRENT=0, not TYPE (decompals N64-IPL `src/pifrom.s:85-90`) [C].
- The ri.refresh-trigger row and the vi.cpp:57-61 comment rest on the first page alone.

**The stated reason for the model choice is refuted [M].**
- T6 rejected refresh-at-blank because VI-off uncached loads "averaged about 35.5".
- On current master, refresh at blank reads 32.99..34.32 (VI-off uncached, all 8 banks averaged), depending on line length (`scan/L*.txt`), never 35.5. At the programmed NTSC line (`PB_BLANK=2`) it reads 33.3.
- The T6 number was a pre-T8 artifact [I]. T8 found the 1-VCLK-line refresh overflow, which is a likely cause [G].

**Refresh explains the uncached VI-off tail but only about a third of the D-fill tail [M + I].**
- In the deterministic model the result is a phase lottery. Across idle line lengths 2040..3102 quarter-clocks:
  - D-fill VI-off mean ranges 41.00..42.03, about 41.47 averaged.
  - Uncached ranges 32.99..34.32, about 33.6 averaged.
- Phase-averaged tails over the median: D-fill +0.47 (hardware +1.5), uncached +0.6 (hardware +0.54).
- At the nemu64 vi_init line (3094), D-fill reads 41.837, which still fails the 42.0..43.0 band.
- So refresh can carry the uncached tail. It leaves about 1 pclk of the D-fill tail unexplained, and no reference names a mechanism for it.

**Hardware systembench argues against the model's refresh at TYPE=0 [M].**
- Same era binary, refresh at blank:
  - u32r-seq and u32r-rand read 136..137 against hardware 134, and rand fails at 33/33 delays.
  - Single loads read 35..36 against 34. This holds at both the 0x800 and the 3094 line length.
- So a hardware run at VI_CTRL=0 shows no refresh inflation that the model's refresh would cause. This also holds at the NTSC rate, where TIMEIT_MULTI's trimmed mean should hide most of one hit per run [I].
- Either refresh is off at TYPE=0 on hardware, which leaves the nemu64 VI-off tails unexplained, or the model's per-hit refresh cost to a CPU load is too large. The hpos report row `holdoff_rclk_max` reads 74.67 rclk against the 52/54 RI field [M], which points to the latter [G].
- Both hardware suites are TYPE=0 measurements. No reading I tested satisfies both.

**Other candidates for a 42.5 mean [G, none referenced].**
- An extra D-fill latency state the model lacks: a SysAD restart phase, or a refresh during the row-miss retry window.
- The nemu64 author's single run (1000 samples) is one hardware VI phase, because the VI crystal is asynchronous to the CPU (clocks.md X1 vs X2). The ±0.5 epsilon may be tighter than the run-to-run spread [I]. No published run-to-run figure exists.

**Decider.**
- Kit q34 `nemu64-console` (pass/fail only) and q16 `dirty-miss`.
- Kit q77 `vi-blank-counting` (does the VI count lines and the RI refresh while blank).
- Add-on I recommend: dump nemu64's D_HIST histogram for the 8 VI-off Load Miss and 9 uncached values. The harness already builds the histogram at `DATA_BASE + D_HIST`, so this is a data dump, not a new test. A refresh tail shows as a flat 41..80 spread at about 1-2%. A latency-state tail shows as a second peak at 42-44.

### Q3. True RDRAM row-miss cost? Does it fix the same-bank VI-on tail?

**The datasheet's 22 tc clean retry is the value the hardware median supports [M + I].**
- Each nemu64 sample sums two executions (ticks1+ticks2-5, `measure.py`), so it is the mean of 2 loads.
- The same-bank median shift is +4 on hardware (32→36) and +4 in the model (33→37 at 22 tc). That is one row miss in one of the two runs, about 8 pclk = 5.5 rclk = 22 tc.
- With `PB_RETRY_TC=11` the median shift drops to +2 (35), and other things break [M]:
  - D-fill VI-off reads 37, because the SysAD fixed path was derived at 22 tc.
  - Cached memset reads 63.3 against 71.24.
  - rspdma reads 6.58 and fails.
- The research doc's "about half the retry" reading of the +4 (rdram-bus-arbitration.md:121) ignores the two-run averaging [I].

**The row-miss cost does not cause the tail and does not fix it honestly [M].**
- Same-bank model: median 37, mean 41.73, max 58. The tail (mean-median) is 4.7 against hardware 0.3. Other-bank tail is 1.7 against hardware 0.5. VI-off is 0.0 against 0.54.
- So on hardware VI-on adds about 0 tail in either bank, and in the model about 1.7 (VI burst waits) plus about 3 (same-bank ping-pong).
- Retry 11 tc passes 20.0 (mean 36.72, median 35) only by breaking the median physics and three other rows. That is a circular refit, rejected.
- VI bursts of 64/32/16 B make the same-bank median 41 (fail), and the mean stays about 41 [M]. Rank changes nothing for isolated loads (verify-63b) [C]. One line per output line fails the median and Load Miss VI-on (verify-63 C) [C].
- **No referenced lever fixes 20.0.** The tail is the VI-vs-CPU contention question.

## 2. Per-item plans

### A. bench:mi-memset-uncached (17.717 vs 18.38 ±0.19%) and bench:mi-memset-cached (72.736 vs 71.24)

1. **State.**
   - Rule `mean`; phase spread 0.002 (essentially phase-free) [M].
   - Rows: `sysad.rdram-write-period` 11 and `sysad.rdram-block-write-period` 11 (fit, verify-is-fit, VI-on assumption). Also `ri.write-hit` and the VI rows.
2. **Reference strength.**
   - n64brew table, one number per method, 0.1 ms resolution. Loop, VI state and run count are unpublished [C]. It is the fit's own data, so it can never be independent for these two rows (pref 21).
3. **Root cause (ranked).**
   - (a) The model's CPU-visible VI cost is about 2x too large (Q3, nemu64 independent data) [I, strongest].
   - (b) The table was VI-off [I, equally consistent with the memset data alone].
   - (c) A sub-SClock drain structure [G, no reference; the SysAD drain is SClock-synchronous, NEC §12.7].
   - These are not separable without #16.
4. **Coupling.** Rows 18.0/18.1/20.0/20.1, rspdma, sp-dma, MM VI share.
   - Refresh-at-blank does not move the memsets [M, `res-PB_BLANK=2`].
   - Retry-cost changes move cached by -11% [M].
5. **Path to green.** Only through #16 q20 `memset-vi`. Ingest both points:
   - If hardware VI-on minus VI-off ≈ the model's (1.3-1.65 pclk/SD), the table is VI-on with heavy VI cost, and the periods need a non-grid mechanism. That is reference-blocked.
   - If it is about half, refit the VI cost (item D) first, then refit the periods on the VI-off hardware point. The VI-on point becomes the independent check.
   - If the table was VI-off (hardware VI-off ≈ 18.38), relabel the expected rows `vi-off` and restore 12/12/1. The bench vi-off point is the check.
   - Acceptance: both memset points within the 0.1 ms band at the mean rule. Effort: about 1 unit after the data arrive. Needs: hardware.
6. **Do not.**
   - Refit 11 vs 12 again on these rows.
   - Pick 10 for cached: +0.1%, but it puts a 4-word writeback below a 2-word write.
   - Widen the 0.1 ms band.
   - Retune ri.retry-clean.

### B. bench:mi-memset-rspdma (pass-conditional:#77) and issue #77 (first VI line after enable)

1. **State.**
   - 6.492..6.501, mean 6.498, band 6.49..6.515, rule `mean`, condition #77. Row `ri.overhead-write` 0 (derived, VI-on premise).
   - The pass rests on the idle VI's 0x800-VCLK grid (vi.cpp:115).
2. **Reference strength.**
   - Same table. About 41 VI lines, so it is closer to one phase than an average (verify-78) [C].
   - The mean margin is 0.001-0.008 at some code layouts (verify-79) [C].
3. **Root cause.**
   - The verdict depends on the idle-VI model:
     - 1-VCLK idle step: 6.422 at every delay, fail (verify-78) [C].
     - The model's 0x800 grid: pass.
     - My `PB_BLANK=2` (idle lines keep the programmed H_TOTAL, refresh runs): 6.435..6.501, mean 6.495, still a pass at the mean [M].
   - So two of three blank models pass.
4. **Coupling.**
   - sp-dma-sweep moves with the blank model: mean 6.35 → 6.316 under `PB_BLANK=2` [M].
   - u32-banked moves too: 131..132 → 132..134, consistent-only [M].
   - Also the nemu64 VI-off rows (Q2) and the systembench uncached rows (+2 under refresh-at-blank) [M].
5. **Path to green.**
   - #16 q12 `vi-first-line` and q77 `vi-blank-counting` decide the idle model (V_CURRENT at enable, ticks to first change, counting while blank).
   - Unit after the data: implement the measured idle behavior in VI::line (vi.cpp:57-118) and ri.refresh-trigger together. They are one decision: does the timing generator run at TYPE=0. Rerun rspdma, the nemu64 VI-off rows, systembench and u32-banked.
   - Acceptance: rspdma mean in band with the condition removed; nemu64 VI-off uncached 32.54±1; systembench u32r/seq/rand within main.c's rule at ≥ the current 33/33.
   - Needs: hardware. Effort: 1 unit.
6. **Do not.** Drop the condition on the strength of today's pass. Pick the idle model that passes rspdma: that is choosing a model by its check.

### C. bench:sp-dma-sweep wr-4096-off0 (6.169..6.678, mean 6.35 vs 6.5)

1. **State.**
   - Rule `mean`. Rows `ri.overhead-write`, `ri.octbyte`, `ri.post-write-gap`.
   - Expected value = the rspdma memset rate 1 MiB / 2.58 ms.
2. **Reference strength.** Unsound as a check of this quantity (verify-78 §2b) [C + I].
   - The model value is one 4 KiB DMA from trigger to a CPU busy-poll exit. That includes setup and a 26-pclk poll quantum: 17.3 rclk, 2.7% of 630 rclk (verify-63c) [C].
   - The reference is the steady rate of 256 back-to-back DMAs, where setup is amortized.
   - The model's own memset port of that quantity reads 6.498.
3. **Root cause.**
   - The +15 rclk (645 vs 630) is per-transfer setup plus poll exit [I from the arithmetic].
   - This is not a channel-rate error. The rspdma port of the same channel rate passes.
4. **Coupling.** Shares `ri.overhead-write` with rspdma. The blank-VI model moves it (B).
5. **Path to green: reclassify, no hardware needed.**
   - Make wr-4096-off0 a report point, or compare it against a model-derived end-to-end expectation. The second option is not honest without hardware.
   - Let mi-memset-rspdma carry the 6.5 check alone.
   - The real per-size, per-direction check is #16 q21 `sp-dma-direction`: chained DMAs timed through SP_DMA_FULL, so the poll falls on the chain.
   - Scope: expected.tsv row kind `check` → `report` with the reason; checks.tsv; README.
   - Acceptance: behaviors.py --check ok; the row status of ri.overhead-write is decided by rspdma (pass-conditional) and q21.
   - Effort: small. Needs: nothing (labeling).
6. **Do not.**
   - Tune ri.overhead-write negative.
   - Switch to the `consistent` rule because it would pass (verify-78 noted consistent passes it).

### D. nemu64:timing/load-from-uncached-vi-on-same-bank (20.0) and the VI-vs-CPU "about 2x" finding

1. **State.**
   - Mean 41.73 (real ROM 41.6-41.69), median 37, against 36.3±4 and 36±1.
   - Rows: `ri.rank.vi`, `ri.rank.other`, `vi.burst`, `ri.overhead-vi`, `vi.lines-per-output-line`, `vi.aa-mode-lines`, `vi.fetch-window`, `ri.retry-clean`, `ri.row-of`.
2. **Reference strength.**
   - nemu64-test hardware means: "re-measured (very stably) at ~36.3" (cache.rs:301-306) [C].
   - The other-bank 32.5 and VI-off 32.54 come from the same author and setup, so the differences between them are meaningful.
   - ±4 is a wide epsilon. It is independent of every fit.
3. **Root cause.**
   - Q3: the model's VI bursts delay isolated CPU loads (tail 1.7 other bank, 4.7 same bank). Hardware shows about 0.
   - Tested and failed:
     - burst size [M];
     - retry cost [M];
     - rank [C verify-63b];
     - 1 line per output line [C verify-63];
     - refresh-at-blank (no effect on VI-on rows) [M].
   - Untested, no reference [G]:
     - (i) The RI overlaps the next request packet with the current data packet. Rambus base protocol: request and data share BusData, so unlikely [I].
     - (ii) The VI has a schedule the CPU loop rarely meets (fetch clustered at H_START?). A cluster makes the mean wait worse unless the CPU is phase-locked, so unlikely [I].
     - (iii) The VI fetches far fewer bytes than 3 lines × 640 B, but enough row touches to keep the same-bank median +4. That needs about one touch per 300-400 rclk in the bank: fewer, smaller fetch events, but not 1 line per output line [G].
     - (iv) The hardware VI-on means are a short-run artifact [G].
   - **No surviving referenced hypothesis.**
4. **Coupling.** Any VI-cost change moves:
   - 18.0/18.1 (Load Miss VI-on, now pass at 42.36/42.99);
   - 20.1 (34.7 pass);
   - all memsets and sp-dma;
   - MM VI share (7.39% vs the 6.5-9.0 band);
   - thar0 VI-on configs (rdp cluster).
5. **Path to green.** #16 q24 `vi-cpu-contention` (hpos loads over three VI lines, by bank and line position) plus q44 `vi-fetch-modes`.
   - Add a per-load latency histogram to kit-hpos ingest. It records outliers_per_line and medians now, but the mean tail decides this.
   - Unit after the data: fit one VI-cost mechanism to q24 (fit-from), and use nemu64 20.0/20.1/18.x plus the memset VI-on minus VI-off difference (q20) as independent checks.
   - Acceptance:
     - 20.0 mean 36.3±4 with median 36±1;
     - 20.1 32.5±4;
     - 18.x 43.25±1;
     - memset uncached and cached within band;
     - MM VI share 6.5-9%.
   - Effort: 1-2 units. Needs: hardware. Scott decision only if the hardware histogram shows no tail (then a mechanism must be chosen with no reference, which pref 7 forbids, and the honest state is "not built").
6. **Do not.**
   - Retry 11 tc (circular, breaks D-fill and memset).
   - Rank tweaks.
   - Smaller bursts.
   - Widen ±4.

### E. nemu64:timing/load-miss-vi-off (C7 × 8: every miss exactly 41; hardware mean 42.5±0.5, median 41)

1. **State.** Sum 41000 per value [M]. Rows `cpu.dfill-total` 41 (measured median), `ri.refresh-trigger` (model choice, active-VI only), `ri.refresh-clean/dirty`.
2. **Reference strength.**
   - nemu64-test console mean, one run per value, ±0.5 [C]. Independent.
   - It compares a phase-random hardware run (asynchronous VI crystal) against one deterministic model phase [I]. That alone makes a single-phase verdict unsound for any tail mechanism. The model reads 41.0..42.03 across idle line lengths [M].
3. **Root cause (Q2).**
   - (a) Refresh at TYPE=0: explains about 1/3 of the D-fill tail, phase-averaged [M], and contradicts systembench in the model [M].
   - (b) An unmodeled D-fill latency state, about 1 pclk [G].
   - (c) Run spread [G].
   - **None survives cleanly.**
4. **Coupling.**
   - Refresh-at-blank moves the nemu64 VI-off uncached rows: 33.0 → 33.3 at NTSC, up to 34.3 at other lines, which would fail 32.54±1 [M].
   - It also moves systembench u8r/u32r/u64r/seq/rand: +1..+3, with rand failing 33/33 [M], and rspdma, u32-banked and the hpos holdoff.
5. **Path to green.**
   - **Harness fix, no hardware.** Give the nemu64 averaged tests a VI-phase walk, the same pattern as bench's BOOT_DELAY: build the ROM at N boot delays and take the mean over phases for the mean checks. This makes the comparison honest whatever the mechanism. It does not make C7 green by itself, because the model has no tail.
     - Scope: romgen nemu64 runtime, run-nemu64.sh, report.
     - Acceptance: values.tsv per delay, and the phase-mean verdict documented in checks.tsv.
   - **Mechanism, needs hardware.** q34 `nemu64-console` with the D_HIST dump add-on (Q2), q16 `dirty-miss`, and q77 `vi-blank-counting`. If the histogram shows a refresh-shaped tail and q77 shows counting while blank, implement refresh at TYPE=0 at the H_TOTAL rate. Investigate the model's per-hit refresh cost first (hpos 74.67 vs 52/54 rclk, and why systembench inflates by +3), because that is a model-side defect candidate checkable without hardware.
   - Acceptance: C7 phase-mean in 42.5±0.5; VI-off uncached 32.54±1; systembench rows unchanged.
6. **Do not.**
   - Turn on refresh-at-blank now (it breaks systembench in the model [M]).
   - Add a fitted constant to the D-fill.
   - Use cpu.dfill-total 42.

### F. bench:uncached-sizes-u32-banked (131..132 vs 134) and systembench:u32r-banked (134 vs 136, consistent-only)

1. **State.**
   - The model reads banked = seq. Hardware reads banked = seq + 2 (systembench 136 vs 134) [C main.c:582-584].
   - Row `cpu.uncached-read-total`.
2. **Reference strength.**
   - One hardware run per value. It is a TIMEIT_MULTI(50) trimmed integer mean, so the resolution is 1 COUNT tick = 2 pclk [C main.c:105-123].
   - The -2 is one tick (followups, verify-88) [C].
3. **Root cause.**
   - (a) Cross-device turnaround: banks 0-3 = modules 0/1, and consecutive reads alternate device or bank. The NEC datasheet gives a post-read gap for the same device only [C B8]. A different-device turnaround is unmodeled [G].
   - (b) The MultiBank (RI_REFRESH[22:19]) shared-resource timing, "Research Needed" on n64brew [C].
   - (c) Refresh at TYPE=0: under `PB_BLANK=2` the port reads 132..134 (consistent-only), but seq/rand inflate too, so this is not the mechanism [M].
4. **Coupling.** Any device-switch cost moves every multi-bank access: the RDP color/Z in different banks (thar0 separate-bank) and the VI-vs-CPU other-bank row.
5. **Path to green.**
   - #16 q18 `cpu-reads` and q35 `systembench` (same binary, row by row) decide whether 136 reproduces and whether banked − seq = 2.
   - If yes, add a cross-device read-to-read gap only if the datasheet gives one. Check the NEC µPD488170L pp. 44-45 transaction timing first: this is a cheap no-hardware research step. Otherwise the honest state is "consistent-only, 1 tick, unmodeled".
6. **Do not.** Add a 2-pclk banked penalty fitted to this row.

### G. Report-only rows (dirty-miss-isolated, dirty-row-sweep, ifill-isolated, wb-fifth-store)

All four are `pending:report-only` with no hardware value. Their honest end state is report rows with a kit ingest path, not checks until #16.

| Row | Model [M] | Expected | Kit question | Note |
|---|---|---|---|---|
| dirty-miss-isolated | clean-single 46, dirty-single 46, dirty-gap0 18..20 | 41 includes harness; no hardware value | q16 dirty-miss | Retry-cost knob moves it: 42/42.75/17.6 at 11 tc |
| dirty-row-sweep | 0 / 2 / 2 / 2 / 2 | datasheet 3 | q17 dirty-row | 2 vs 3 is 2-pclk COUNT aliasing [C t11-fix]; 11 tc reads 3-4 [M] |
| ifill-isolated | no ROM | cpu.ifill-stall 45, inferred (formulas 46) | q14 ifill | No-hardware step: build the ROM so the model value is reported. It still cannot be a check |
| wb-fifth-store | no ROM | NEC "has a space" vs R4300i "emptied" | q15 wb-release, q72 wb-drain-target | Same; ROM first |

Units without hardware: ROMs for ifill-isolated and wb-fifth-store (romgen bench, report kind), so ingestion has a model column to compare. Effort: small each.

### H. Row-level notes (ri.overhead-read, ri.overhead-write, ri.overhead-vi, ri.octbyte, cpu.dfill-total, vi.*, ri.refresh-*)

- **ri.overhead-read 4.5.** Fit to hcs64 with an unstated direction. Verify-is-fit, rd-4096 5.213 vs 5.55 is report-only [C]. It stays fit-only until q21 measures read DMA.
- **ri.overhead-write 0 and ri.overhead-vi 0.** Both labeled derived. Verify-63b says ri.overhead-vi is a model choice from silence, and ri.overhead-write is a fit in effect [C].
  - Relabel ri.overhead-vi as model-choice now. This is labeling only, no hardware.
  - Keep ri.overhead-write's status tied to rspdma (conditional) and q21.
- **ri.octbyte 4 tc.** Datasheet. Fine as built. Its checks (sp-dma) are reclassified in C.
- **cpu.dfill-total 41.** Measured median, sound. Its check fails on the tail (E), not on the median.
- **vi.\* fetch rows.** These are 7 model-choice rows plus vi.burst. Hardware q44 `vi-fetch-modes`, q76 `vi-fetch-position` and q24 decide them. None can go green without hardware.
- **ri.refresh-trigger.** The note's quantitative claim ("would raise by about 2") is false on current master [M]. Update the note to the measured 0.3 at the NTSC line, and the systembench conflict [M]. Labeling only, no hardware.
- **ri.refresh-clean/-dirty 52/54.** Vendor values, sound. The model's observed per-hit CPU cost (hpos holdoff_rclk_max 74.67 rclk) exceeds them. That is a model-side investigation, done without hardware: trace one refresh-hit load in uncached-vs-hpos bank5 and attribute the extra ~20 rclk (VI bursts queued at rank 1 ahead of the CPU during the holdoff are the likely cause [G]).
- **Missing row.** The "HSYNC adds no refresh while one waits" latch still has no model-choice row (followups verify-57) [C].

## 3. Dependency order

1. Labeling, no hardware:
   - C (sp-dma reclassify);
   - H (relabel ri.overhead-vi; correct the ri.refresh-trigger note; add the refresh-latch row);
   - G (ROMs for ifill-isolated and wb-fifth-store).
2. Model-side investigation, no hardware: trace the per-hit refresh cost (hpos 74.67, and the systembench +3 under refresh-at-blank). If it is a model defect, fix it before any refresh-at-TYPE=0 decision.
3. Harness, no hardware: the nemu64 VI-phase walk (E), so every nemu64 mean check is phase-honest before hardware arrives.
4. Kit add-ons, no hardware to build, hardware to run:
   - the D_HIST histogram dump in q34;
   - the per-load latency histogram in q24 ingest.
5. After #16:
   1. q77 and q12: idle VI and refresh at TYPE=0. This decides B and part of E.
   2. q24 and q44: the VI cost mechanism (D).
   3. q20: memset VI-on/off (A). Do it after D, because the VI cost must be fixed first and the memset difference then checks it.
   4. q18 and q35: u32-banked (F).
   5. q16, q17, q14, q15: the G report rows become checks.

## 4. Summary

- **Green without hardware.** None of the failing checks can honestly go green without hardware.
  - Labeling and harness work makes the verdicts honest: C, H, the E phase walk and the G ROMs.
  - The refresh-cost trace (step 2) may expose a model defect that is fixable without hardware. It would not by itself green any check in this cluster.
- **Green only with #16, and the question that decides each:**
  - mi-memset-uncached and mi-memset-cached: q20 `memset-vi`, after q24.
  - mi-memset-rspdma (drop #77): q12 `vi-first-line` and q77 `vi-blank-counting`.
  - nemu64 same-bank 20.0 and the 2x finding: q24 `vi-cpu-contention` with a histogram, plus q44.
  - nemu64 load-miss-vi-off C7: q34 `nemu64-console` with the D_HIST dump, q16, and q77.
  - u32-banked (bench and systembench): q18 `cpu-reads` and q35 `systembench`.
  - The G rows: q16, q17, q14, q15/q72.
- **Honest end state is reclassification:**
  - bench:sp-dma-sweep wr-4096-off0: report, because it measures a different quantity from the memset rate.
  - The nemu64 averaged mean checks (C7 and 20.0): compare a phase-random hardware run against one deterministic phase today, so they become phase-mean checks once the phase walk exists.
  - The four G rows stay report-only until #16.
  - If #16 shows no VI tail on hardware and no referenced mechanism exists, the VI-cost behavior is "not built" (map ruling), not fit.
