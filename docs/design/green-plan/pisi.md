# Cluster pisi: green plan (PI/SI poll rows, PI DMA, pidma, joybus reports)

Investigator run, 2026-10-09. Master 8d86b87cd. Read-only on the repo. My scratch worktree held env-gated instrumentation and was removed after the run. Its diff is at `~/n64-timing/results/plan-pisi/instrumentation.diff`.

Labels: **measured** = I ran it this session. **cited** = file:line or URL. **inferred** = reasoning from measured or cited facts. **guess** = an unverified premise, with the experiment that would replace it.

Artifacts are in `~/n64-timing/results/plan-pisi/`:
- `sweep-W.txt` and `sweep-WBUS.txt`: the era systembench rows against the register-write drain.
- `pidma/exact*.tsv` and `pidma/summary-*.txt`: the exact pidma replay at each W.
- `tools/`: sb.sh, era33.sh, win.sh, tab.py, pidma-exact.py, coupling.sh.
- `coupling.log`.
- nemu64, bench and MM output for W=60 and W=100 under `~/n64-timing/plan-pisi-w{60,100}/`.

Runner: `~/n64-timing/build/plan-pisi/rundir/bin/`. `n64-run-base` is the master build. `n64-run-sweep2` reads the values from these env vars: PLAN_W, PLAN_WBUS, PLAN_PIB, PLAN_SIB, PLAN_SIROM, PLAN_SIRAM, PLAN_PIDMA0, PLAN_PIWB. With no env var set, `n64-run-sweep2` matches master: the era rows are identical (measured), and MM 600 has md5 9629185039701bddcdbd90c248a4f38b, equal to the calib-kit-merge standing run (measured).

ROMs:
- Era ROM, built from my own tree with build-systembench-era.sh 2023: z64 sha256 fd5ec6c06acb686608c53554950c8b6b12b011dca5b30bf22bd7277a8d986823, the same as sysbench-era (measured). The 32 boot-delay ROMs are in `~/n64-timing/plan-pisi-home/era32`.
- pi_dma_test.z64: sha256 1d2c999c42ba..., pinned.
- nemu64 and bench ROMs: rebuilt into `~/n64-timing/plan-pisi-home/roms`.

## The headline finding: one shared cause, and an independent hardware check that agrees

**Mechanism (measured with PLANLOG).** Example: one rep of PI I/O W in the era build, in Clock units (8 per pclk, 12 per rclk).
- t0 COUNT is at +0. The `sw` is at +8.
- The posted write drains at +68, which is +60 units (`sysad.register-write`, 5 rclk) after the store. That drain starts PI busy, so busy ends at +68+1608.
- The first `lw PI_STATUS` waits behind the write (SysAD in order) and starts at the drain. Every poll samples at the end of its 21 pclk register read. Polls repeat every 184 units (23 pclk = 15.33 rclk), plus 40 units at each 8-poll wrap (andi/bnez/andi).
- So the poll grid is anchored on the drain end, and the reading is R = (store to drain) + a grid point.
- In this rep the first idle sample is preceded by mfc0 at +1568 = 130.67 rclk, so the reading is 130.

**Consequence 1 (measured).** The busy durations cannot move these readings except in steps of one poll period. I swept `pi.io-busy` over 110..160 rclk, and PI I/O W reads only 112, 130, 145 or 161. Every B from 122 to 138 gives 130, and 134 is unreachable. `si.io-busy` over 2130..2180 reads only 2136, 2150, 2166 or 2181, so 2158 is unreachable. No value of pi.io-busy, si.io-busy or si.write64-rom can make these checks pass at master's W. The -4/-8/-4 residuals are not busy-time errors.

**Consequence 2 (measured).** The continuous lever is the time from the store to the moment the first poll read can issue. That time is `sysad.register-write` (W), whose basis is model-choice: "no hardware measurement", MiSTer floor 2+3 (behaviors.tsv:72).
- Sweeping W moves every poll row roughly 1:1 (`sweep-W.txt`).
- It moves the PI DMA rows about 2.6-3:1. In bench_pidma and in pi_dma_test, the PI_DRAM_ADDR, PI_CART_ADDR and PI_WR_LEN writes are all still in the write buffer when t0 is read. MEMORY_BARRIER is compiler-only (era disassembly at 800135d0-800135d8; pi_dma_test.c:39-46). So the DMA starts 3W after t0.
- In the logged rep the three drains land at +44, +104 and +164 units after t0 (measured).

**The "multiples of 4" are floor arithmetic, not a 4-rclk quantum (inferred).** Under main.c's rule (≤2 rclk or <0.2 %), the W window that passes each row is as follows (measured, unpadded era ROM):

| row | passes for W (units) |
|---|---|
| PI I/O W | 76..128 |
| SI I/O W | ≥100 |
| SI DMA W ROM | 60..108 |
| SI DMA W RAM | ≤108 |
| PI DMA 128 | {80, 88, 92, 100, 108} |
| PI DMA 8 | {76..88, 96} |

The intersection is W = 100 or 108 units (8.33-9 rclk) for every row except PI DMA 8.

**W = 100 over all 33 era runs (unpadded plus 32 boot delays), measured:**

| row | reading | hardware | result |
|---|---|---|---|
| PI I/O W | 134 | 134 | pass |
| SI I/O W | 2154 | 2158 | pass, 0.19 % |
| SI DMA W ROM | 2146 | 2144 | pass on 33/33 runs (was 1/33) |
| SI DMA W RAM | 4072 | 4065 | pass, 0.17 % |
| PI DMA 128 | 1590..1591 | 1591 | pass |
| PI DMA 1 KiB | 12180 | 12168 | pass |
| PI DMA 64 KiB | 778374 | 777807 | pass |
| PI DMA 8 | 196 | 193 | **+3, fail** |

PI I/O R and SI I/O R do not move. JOY rows shift +10 and all still pass. W = 108 gives PI DMA 8 198..200; everything else passes.

**Independent check: pidma:logs, a different ROM and different hardware data (rasky's golden logs).** Exact replay results (measured; method under pidma:logs below):

| W (units) | sizes 8-382 within ±3 % | ROM self-check |
|---|---|---|
| 60 (master) | 23765/24000 | 8 failures, capped |
| 72 | 23930 | 1 failure |
| 84 | 23961 | 1 failure |
| 92 | 23955 | 1 failure |
| 100 | 23960 | 1 failure |
| 108 | 23954 | SUCCESS |
| 116 | 23947 | SUCCESS |
| 132 | 23840 | SUCCESS |

**Explain the number.** At W=60 the ROM hits its 8-failure cap. It then drops to 1 run per point, so part of the 23765 to 23930 jump is the ROM averaging 4 runs again, not W. On the same subset that has 4 runs at every W (RAM 0x780..0x796, 4512 points):
- Fails: 24 at W=60, 2 at 72, 0 at 84, 0 at 92, 2 at 100, 3 at 108, 4 at 116, 25 at 132.
- The 8-31 B mean deviation crosses zero between W=92 (-0.09 %) and 100 (+0.05 %).

So pidma independently places W at about 84-108 units, centred near 96-100, overlapping the systembench window 100-108 (measured). This is the one place in the cluster where a fit has an independent hardware check that agrees.

**Split test, H1' (inferred from measured).** I added PLAN_WBUS, which holds the bus longer after the write takes effect. WBUS = 36-48 gives the same systembench picture, with PI DMA 8 failing at 197-200 (measured). pidma reads 23918 at WBUS=40. These data cannot tell "the write takes effect later" from "the bus frees later". W is the simpler single knob and already a row. n64brew's SysAD Interface page (Data: Word non-cached write, step 4) says the RCP holds EoK high "until the write is completed internally", then EoK is low "for a full cycle" before the next command. That supports a drain longer than MiSTer's 2+3 (cited, qualitative; no cycle count).

## Items

### 1. systembench:pi-io-w (130 vs 134), systembench:si-io-w (2150 vs 2158), systembench:si-dma-w-rom (2140 vs 2144, consistent-only)

**1. Current state.**
- The checks run the era build under main.c's rule.
- pi-io-w decides pi.io-busy (134 rclk, basis measured = the hardware total written in as a busy time).
- si-io-w decides si.io-busy (2158, measured).
- si-dma-w-rom decides si.write64-rom (2144, measured).
- si-dma-w-ram (pass, 4065) decides si.write64.

**2. Reference strength.**
- Each value is one hardware reading of TIMEIT_WHILE_MULTI (main.c @50f5066, cited). The binary's poll phase is fixed (verify-83, sysbench-era).
- The readings are independent of every fit, but they are **not** busy times. A reading is R = (store to drain) + a poll-grid point.
- Measured at W=100 with my B sweeps, each reading constrains its busy only to a 15-17 rclk window: pi.io-busy 122..139 reads 134; si.io-busy 2146..2160 reads 2154; si.write64-rom 2127..2144 reads 2146; si.write64 4056..4070 reads 4072.
- What the readings pin is W, to about ±2 rclk.
- Remaining premise (guess, from sysbench-era): the hardware binary was built with GCC 12, so its poll cadence equals this build's. kit `systembench` (#16, the same binary on a console) replaces that guess.

**3. Root cause, ranked.**
- **(a) Survives.** sysad.register-write is about 3.3-4 rclk short. Evidence: the B sweeps rule out the busy values, the W sweeps make all four rows pass inside one window, and pidma agrees independently.
- **(b) Ruled out as the cause of a continuous offset: the poll sample point.** Sampling at the end of the read, which MiSTer does not do (memorymux.vhd WAITBUS latches data at bus_done, then waits bus_slow; cited), only changes which poll sees idle, in steps of one poll period (inferred from the mechanism). Where the sample sits inside the read stays unverified, because no reading here can see it.
- **(c) Ruled out: poll-step cost.** P = 23 pclk in the model. The hardware RCP I/O R of 24 measures mfc0;lw;mfc0 with a WAW interlock on v1 (era disassembly 8001352c-80013530), which is consistent with P_hw = 23 (inferred).
- **(d) Ruled out: B values.** See Consequence 1.

**4. Coupling (measured, W 60 to 100).**
- **Poll and DMA rows.** All the poll rows, the PI DMA rows (3:1) and the JOY rows (+10 rclk) move.
- **Unchanged.** nemu64 timing, cycle and cop0hazard values.tsv are byte-identical. PI and SI I/O R do not move.
- **Bench verdicts that flip, pass to consistent-only:** bench:pi-io-write (median 133 to 137) and bench:si-dma-write64-rom (2143 to 2149). These are the romgen ports with a 25/26 pclk poll loop and nop jitter. systembench:* replaced them for these rows (behaviors.tsv:82-85).
- **Other bench moves.** mi-memset-repeat 1.31 to 2.18 ms/MiB (hardware 3.8; it already fails, because MI repeat writes take the register-write drain path, throughRi() is false when repeating). mi-memset-rspdma mean 6.498 to 6.494 (min 6.393, still pass). sp-dma-sweep mean 6.35 to 6.229 (already fails). rdp-sync-sweep load-256 25.05 to 25.12 (still passes, every rule).
- **MM.** md5 changes (c8578ef6...). mmbench was not measured.
- **Joybus fit.** pif.joybus-* were fit with a 36 rclk ares-side offset measured on master (pif-joy.md). That offset becomes about 46 at W=100, so joybus-fit.py must be rerun. The JOY checks stay in band either way.

**5. Path to green. Unit U1 "register-write drain", no hardware needed, needs no ruling.** It is a fit under pref 21.
- **Files:** behaviors.tsv row sysad.register-write; the generated hpp; possibly cpu/sysad.cpp if the value is not whole rclk.
- **Method.**
  1. Set the value from the systembench fit window: 100 units (8.33 rclk, 12.5 pclk). Alternatively 9 rclk, if whole rclk is required. 9 rclk passes the same rows but leaves PI DMA 8 at 198..200.
  2. Set basis to fit, with fit-from = systembench:pi-io-w and systembench:si-dma-w-rom, the two rows that bound the window from opposite sides.
  3. Verify against independent checks: pidma:logs (exact replay), systembench:si-io-w, systembench:si-dma-w-ram, systembench:pi-dma-128/1024/65536 (fit data for pi.block-writeback, so not independent of that row) and the kit question `register-write`.
  4. Rewrite the notes of pi.io-busy, si.io-busy, si.write64 and si.write64-rom. Each should say the check pins its busy only to its measured window (above) and that the reading tests the drain.
  5. Rerun joybus-fit.py with the new ares-side offset and update pif.joybus-* (fit stays fit).
- **Acceptance (measured, all 33 era runs):** pi-io-w 134; si-io-w within 0.2 %; si-dma-w-rom and si-dma-w-ram pass on 33/33; pi-dma-128, 1024 and 65536 pass; pidma exact replay ≥ 23950/24000 with ROM self-check ≤ 1 failure; nemu64 values identical; det and stepcap PASS.
- **Independent confirmation:** pidma:logs (above), then kit-cpu `register-write` and kit-cpu2 `wb-drain-target` on #16.
- **Regression risks:** the MM md5 and mmbench values move (measure filesel-named against its target); the two bench port flips; mi-memset-rspdma margin (min 6.393).
- **Effort:** small code, one standing run, plus the joybus refit.

**6. Do not:**
- Refit pi.io-busy, si.io-busy or si.write64-rom to the readings. This is impossible (B sweep), and it would be circular anyway.
- Widen bands.
- Fit W to pidma and then call pidma its check. Fit from systembench only.

### 2. systembench:pi-dma-8 (187 vs 193), bench:pi-dma-sizes and bench:pi-dma-sizes-8 (consistent-only), systembench:pi-dma-128 (1580 vs 1591)

**1. Current state.**
- pi-dma-8 checks pi.page-setup (wiki 15), pi.halfword-bias (wiki 2) and pi.block-writeback (fit 28, with fit-from 128/1K/64K).
- pi-dma-128 is fit data for pi.block-writeback.
- The bench pi-dma-sizes port reads 180..194.67, median 190 at 8 B (consistent rule).

**2. Reference.** main.c:589-592 (cited), one TIMEIT_WHILE reading. The 128 B point is already fit data (pref 21).

**3. Root cause.**
- 6 of PI DMA 8's -6 and all 11 of PI DMA 128's -11 come from the three-write chain (measured: W=100 gives 196 and 1590).
- PI DMA 8 then sits +3 high. At W=96 it reads 195 (pass), but PI DMA 128 alternates 1595/1590/1596 between W 96/100/104. The 128 B reading sits on a poll boundary (measured). PI DMA 8's +3 is inside one-binary poll quantization plus the PI cost model.
- No single "PI setup cost" explains both PI DMA 8 and the pidma small band (measured, see item 3):
  - pidma at W=100 has an 8-31 B mean deviation of +0.02 %, so the small-DMA cost is already right there.
  - PLAN_PIDMA0 = -48 units (a -4 rclk first-block setup) worsens pidma, from 23765 to 23627.
  - The +15 % was never a setup cost (item 3).

**4. Coupling.** Same as U1, plus pi.block-writeback's fit.

**5. Path.**
- **U1 first.** Then PI DMA 128, 1 KiB and 64 KiB pass (measured).
- **PI DMA 8 stays a 1-rclk-over-tolerance fail** at the U1 value. Honest end state: fail until #16. Kit question `systembench` (same binary on a console) decides whether the fork's +3 is a model error. kit `pi-dma-small` gives the walked range.
- Do not add a PI DMA 8-specific term. The only candidate parameters (page-setup, halfword-bias, PiEdgeWait) are pinned by pidma, which would get worse.
- **bench:pi-dma-sizes and pi-dma-sizes-8: reclassify to report-only.** They are romgen ports of the same hardware numbers that systembench:pi-dma-* now runs at the original code. This is the precedent set by the four poll rows (behaviors.tsv:82-85 notes, systembench.md section 4). Their `consistent` pass compares a port phase window with a single-phase reading (verify-78). Effort: checks.tsv and behaviors.tsv verify columns only.

**6. Do not:**
- Refit pi.block-writeback to the era 128 B reading before U1; most of its -11 is W (measured).
- Add a small-DMA setup constant.

### 3. pidma:logs (fail 23776..23833/24000, worst band 0-31 B +14.97 %) and hw:pidma-offset (no reader)

**1. Current state.**
- Fail. It decides pi.page-setup, pi.halfword-bias, pi.block-bytes and pi.block-writeback (independent check), and now also sysad.register-write (inferred: three posted writes precede t0).

**2. Reference.**
- Golden logs: min..max of 8 hardware runs per (RAM offset, size) at DOM1 0x40/0x12/7/3 (pi_dma_test.c:130-136, 164; dma-timing.md). Independent of every fit.
- **Condition gap (inferred, partly measured).** The logs come from the MODE_GENERATE build, whose rom_buffer cart page phase differs from the prebuilt ROM's. Our cart address is 0x1002b6d0, page offset 0xd0, so a page crossing falls at +304 B. Hardware's falls at about +352 (T8, inferred from the jump).
- Measured at W=100: band 288-319 mean +0.86 % and 320-351 +1.64 %, with 352+ at +0.10 %. Sizes 305-352 are compared under a different condition than hardware ran.

**3. Root causes.**
- **(a) The "offset" problem is solved without touching the ROM (measured).**
  - PLANLOG logs every COP0 COUNT read with its Clock time. Each PI_WR_LEN store is paired with the COUNT read within 200 units after it (t0) and the next one (t1). That pair is exactly the ROM's measurement (pi_dma_test.c:39-50).
  - `pidma-exact.py` joins the pairs to ARES_PILOG DMA starts.
  - Validation: it reproduces all 8 values the ROM printed in the same run, (0x784,3)=112 ... (0x796,4)=112, 8/8.
  - Exact result on master: 23765/24000. That is **outside** the calibrated range 23776..23833, so the constant-shift calibration is wrong.
  - Why (measured): the store-to-DMA-start distance varies per point (52, 108 or 228 units after t0), which a constant (read, write) shift cannot represent.
  - So hw:pidma-offset needs no hardware and no ROM variant. The golden logs are the ROM's own COUNT deltas, and the emulator can log the same COUNT reads.
  - License: pi_dma_test has no license file (checked: README, .gitignore, Makefile and sources only). A modified or COUNT-printing variant may not be built or committed. Building one would need a ruling like pref 28b. It is not needed.
- **(b) The +15 % is a single-run phase outlier, not a setup cost (measured).**
  - The worst point is 0x7ee/10: model 216 ticks against hardware 181-187, with neighbors 177 (9 B) and 190 (11 B).
  - At master's W the ROM hits its 8-failure cap and drops to 1 run per point, so single-run outliers are scored.
  - At W=100 the band 0-31 worst is -6.08 % and there is no +15 %.
- **(c) Row-end first block (measured).** RAM 0x7fc/0x7fe give 67 of 235 fails at W=60 and 21 of 40 at W=100. The model is low by 3-6 % at 8-60 B. This is T8's "hardware about 29 rclk more" case, where the first block's RDRAM write is empty in ares (pi/dma.cpp dmaFill: bytes = curLen - misalign = 0 when distEndOfRow < 8, so no RI write is posted).
- **(d) The cart page-phase condition gap**, under 2 above.

**4. Coupling.** U1 moves pidma from 23765 to 23960. A row-end fix touches only RAM offsets with distEndOfRow < 8.

**5. Path.**
- **U2 "exact pidma replay" (tooling, no hardware, no ruling).**
  - Add COUNT-read logging to ARES_PILOG (one line per MFC0 COUNT with value and time; pi/io.cpp already owns the log).
  - Replace `--calibrated` with the exact join. Keep `--calibrate` only as a self-test cross-check that the printed values reproduce.
  - Acceptance: master reproduces 23765/24000 and 8/8 printed values. pidma-replay --self-test gains a case that fails if a printed value mismatches.
  - This closes hw:pidma-offset. Reclassify the calibration question pidma-offset as answered by emulator-side logging.
- **U3 "row-end first block".**
  - Scope: pi/dma.cpp.
  - Method: find the hardware behavior for a first block that ends within 8 B of a 2 KiB row. Candidates: an extra masked RDRAM write burst, or the bea395b24 "+21 masked write" and "+6 row open" terms (dma-timing.md, upstream PR #2139, cited but never measured).
  - The data to fit is the 0x7fc/0x7fe golden points. That is a fit, so split it: fit from 0x7fe, check against 0x7fc and 0x7fa/0x7f8.
  - Acceptance: 0x7f8..0x7fe within ±3 % at every size, and no other offset moves.
  - Risk: MM DMAs that end near a row. Effort: medium. Hardware: none.
- **Reclassify sizes 305-352** in pidma:logs as condition-mismatched (exclude them, with the reason, and list them as a report) until the hardware rom_buffer page offset is known. Use exclusion, not tolerance. The kit question that would decide it is a pi_dma_test-style capture on #16 with a known cart address. kit-dma `pi-dma-small` is the nearest.
- **Expected end state after U1+U2+U3:** about 23990/24000 (inferred, from the 21 row-end fails at W=100). The remaining roughly 19 scattered small-size ±3-5 % points are single-phase model readings against an 8-run hardware range. Not all of them are expected to clear (inferred).
- The pass rule "every point within ±3 % and ROM self-check 0 failures" may then still fail on a handful of points. Decide with Scott whether pidma:logs keeps an every-point rule or a stated count. This is a decision, not a refit.

**6. Do not:**
- Report the calibrated range as the result; it excludes the exact value.
- Use pidma as fit data for W.

### 4. bench:si-dma-read64-2/3/4 and systembench:joy-2j/3j/4j (report-only, controller presence)

**2. Reference.** main.c:610-612 (cited). The rig's pads are unpublished.

**3. Status (measured).**
- `n64-run --controllers 4` on the era build reads 2J 60941 (+5.1 %), 3J 83908 (+7.7 %) and 4J 106857 (+9.2 %).
- With one pad: 57977, 77962 and 97948 (+0.01/+0.05/+0.06 %).
- 1J and Accessory are identical in both. So the one-pad reading fits, and the four-pad reading misses by 5-9 %. That holds under fits that use 2J as data (pif.joybus-no-device is verify-is-fit).

**5. Path.** No green without hardware. End state: report-only. Decided by kit `joybus-pads` (#16, runs with 1 and 4 pads). U1 shifts these rows +10 rclk, which needs the joybus refit only.

**6. Do not:** promote 3J/4J to checks; they are predictions of a fit that rests on an assumption.

### 5. rdpstat:current-prefetch (no-rom)

- **Reference:** n64-systemtest rdp/mod.rs:21-23 is a TODO comment (cited). It is not a recorded result.
- **Measured:** the calib kit's kit-rdp fifo-depth already reads current_minus_start=240 on master (calib-kit-merge standing calib/boot-*/kit-rdp output, nops-64 and nops-512).
- **Path:** wire `~rdpstat:current-prefetch` (guard) to that reading. That makes the guard run (pass-consistent), but it stays a guard.
- **End state:** green only via kit question `cmd-fifo-depth` (#16). Effort: checks.tsv only.

### 6. Rows

| row | how it ends |
|---|---|
| pi.io-busy, si.io-busy, si.write64, si.write64-rom | Pass after U1. The notes must say the checks pin each busy only to its measured window (item 1). The basis stays "measured (cited total)". |
| si.write64-rom | Also reaches 33/33 after U1. |
| pi.block-writeback | Stays fit. The 128/1K/64K twins are fit data. pi-dma-8 and pidma are its independent checks. |
| pi.block-bytes | Decided by pidma after U2/U3. |
| cpu.pi-io-read | Already passes (144) and is unmoved by W (measured). |
| pif.joybus-* | Refit after U1 (same five totals, new ares-side offset). |
| sysad.register-write | Goes from model-choice to fit (U1), with pidma:logs as its independent check and kit `register-write` / `wb-drain-target` on #16 as the final word. |

## Dependency order

U2 (exact replay, tooling) first, so that U1's independent check is exact. Then U1 (register-write drain, plus the joybus refit). Then the bench pi-dma-sizes reclassification. Then U3 (row-end first block). Then the pidma rule decision and the sizes 305-352 exclusion.

## Green without hardware

- systembench:pi-io-w, systembench:si-io-w and systembench:si-dma-w-rom (33/33) via U1.
- systembench:pi-dma-128, plus the 1024 and 65536 points kept passing, via U1.
- pidma:logs, mostly, via U1+U2+U3. The verdict on a few residual points needs Scott's rule decision.
- The hw:pidma-offset question closes via U2.

## Green only with #16

| item | kit question that decides it |
|---|---|
| systembench:pi-dma-8 (+3 after U1) | `systembench`, the same binary fd5ec6c0 on a console |
| sysad.register-write final confirmation | kit-cpu `register-write`, kit-cpu2 `wb-drain-target` |
| joy-2j/3j/4j and bench:si-dma-read64-2/3/4 | `joybus-pads` |
| rdpstat:current-prefetch | `cmd-fifo-depth` |
| pidma sizes 305-352 | a capture with a known cart page phase (no kit question names it yet; add one to kit-dma) |

## Honest end state is a reclassification

- bench:pi-dma-sizes and bench:pi-dma-sizes-8: report-only, superseded by systembench:pi-dma-*.
- pidma:logs sizes 305-352: condition-mismatched.
- hw:pidma-offset: answered by emulator-side COUNT logging. No hardware reader is needed.
- joy-2j/3j/4j: stay report-only.
- rdpstat:current-prefetch: stays a guard.
