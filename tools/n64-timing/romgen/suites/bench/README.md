# bench suite

The bench suite is a set of romgen microbenchmark ROMs. Each ROM measures one memory-system or RDP behavior and prints the raw measurement. The timing-core units (plan unit R1, checked by T6, T8, T11 and T12) compare these measurements with the hardware values in `expected.tsv`.

The ROMs do not grade themselves. Each one prints COUNT ticks and device counters. `report.py` derives rates from them and compares the rates with `expected.tsv`.

## Commands

Run these from the repository root.

```sh
python tools/n64-timing/romgen/build.py --suite bench --out $N64_TIMING_HOME/roms/bench
N64_RUN=<path to n64-run.exe> tools/n64-timing/romgen/suites/bench/run.sh [ROM...]
python tools/n64-timing/romgen/suites/bench/selftest.py
```

- `build.py` writes one `pad-<P>/boot-<K>/bench-<rom>.z64` per ROM, layout pad P and boot delay K (see [Phase](#phase)), and a `bench-<rom>.tests.tsv` listing next to each that names every point. Two builds produce byte-identical files.
- `run.sh` runs each ROM at each pad and delay, `BENCH_JOBS` (default 4) runners at once, and writes `results/bench/pad-<P>/boot-<K>/<rom>/{stdout,stderr}.txt` and `runs.txt` (one stop line per run). It then runs `report.py`, which writes `measurements.tsv` (every raw and derived value per pad and delay), `phases.tsv` (each `expected.tsv` metric at every pad and delay) and `results.tsv` (one row per `expected.tsv` entry: the joint min, median, max and mean over every pad and delay, the rule, the condition, each pad's verdict and range (`pad_verdicts`, `pad_phases`) and the verdict under the layout rule, and for a `consistent` row the `mean` verdict and the acceptance window). `run.sh` exits 1 only when a ROM did not print every point in its listing. A value outside its band is reported but does not change the exit code.
- `selftest.py` checks the derived metrics in `report.py` against synthetic inputs whose answers are known.

## Output format

Each point prints one XLOG line:

```text
#bench <rom> <point> <constant fields> reps=N min=<ticks> max=<ticks> [<counter>=<value> ...]
```

- `min` and `max` are COUNT ticks over `reps` repetitions. A COUNT tick is 2 PClock (93.75 MHz) and 4/3 rclk (62.5 MHz).
- RDP points add `clock`, `bufbusy`, `pipebusy` and `tmembusy`. These are the DPC counters, read after the DP interrupt, from the last repetition.
- `uncached-vs-hpos` prints a header line with `line_ticks` and `count`. It then prints `samples=<offset>:<latency>,...` lines with 64 samples each. Both numbers are COUNT ticks.
- The runtime also prints `Running <rom>...`, an `@<test>.<value>` record per point, and `Bench: Failed 0 of N tests`. A count other than 0 means a point raised an exception.

## ROMs

| ROM | Points | What it measures |
|---|---|---|
| `mi-memset-uncached` | `vi-on`, `vi-off` | 1 MiB of uncached SD stores, 8 per loop iteration |
| `mi-memset-cached` | `vi-on`, `vi-off` | 1 MiB of cached SD stores. After the first pass, every line is a store miss with a dirty victim. |
| `mi-memset-rspdma` | `vi-on`, `vi-off` | 1 MiB from DMEM to RDRAM, as 4 KiB SP DMAs queued whenever `SP_DMA_FULL` clears |
| `mi-memset-repeat` | `vi-on`, `vi-off` | 1 MiB in MI repeat mode: `MI_MODE` = 0x17F, then one uncached SD per 128 B |
| `sp-dma-sweep` | `poll`, `{rd,wr}-<8..4096>-off{0,7c0,7f8}` | One SP DMA from trigger to `SP_DMA_BUSY` clear, in both directions. Offsets are row-aligned, and 64 B and 8 B before a 2 KiB row end. |
| `pi-dma-sizes` | `cart-to-ram-{8,128,1024,65536}` | n64-systembench PI DMA: one PI DMA from cartridge 0x10000000, from the `PI_WR_LEN` write until 8-poll rounds of `PI_STATUS` see idle, with the poll phase walked as `pi-io-write` |
| `uncached-vs-hpos` | `bank5`, `bank2-vi` | Back-to-back timed uncached LWs over three VI lines, each with its offset from the line start. Bank 2 holds the VI front buffer. |
| `dirty-row-sweep` | `{clean,dirty}-<delta>` | One uncached LW after the bank's open row was read (clean) or written (dirty). The target is the same row (`8`) or another row in the same bank. |
| `dirty-miss-isolated` | `{invalid,clean,dirty}-{single,gap0,gap20,gap80}` | A D-cache LW miss whose victim is invalid, clean or dirty. Optionally a second miss follows after a 0, 20 or 80 iteration loop. |
| `rdp-sync-sweep` | `none-0`, `{pipe,tile,load}-{16,64,256}`, `rect-{16,64}`, `rect-{kind}-{16,64}` | N bare syncs, or N times an 8x1 rect followed by a sync |
| `rdp-setter-sweep` | `none-0`, `{nop,prim-color,env-color,other-modes}-{256,1024,4096}` | N one-word commands |
| `rdp-atomic-sweep` | `atomic{0,1}-{1,16,64}` | N 16x4 1-cycle rects with `atomic_prim` off or on |
| `rdp-rectn` | `rect-320x6`, `rect-320x6-x8`, `duty-320x240` | The cen64 dpc_probe RECTN and DUTY shapes |
| `uncached-sizes` | `c{8,16,32,64}`, `u{8,16,32,64}`, `u32-{seq,rand,banked}` | n64-systembench RDRAM C*R, U*R and U32R seq, rand and banked: one cached (warmed) or uncached LBU, LHU, LW or LD between two COUNT reads, or four uncached LWs at adjacent words, scattered words of one row, or the first word of four banks |
| `rcp-reg-read` | `c32`, `vi-control` | n64-systembench RCP I/O R: one VI_CONTROL read, with the cached LW baseline |
| `pif-ram-read` | `c32`, `pif-ram` | n64-systembench SI I/O R: one PIF RAM word read, with the cached LW baseline |
| `pi-io-read` | `c32`, `rom-word` | n64-systembench PI I/O R: one cart word read, with the cached LW baseline |
| `pi-io-write` | `rom-word` | n64-systembench PI I/O W: one cart word write, then 8-poll rounds of PI_STATUS until idle. Each rep starts the polls at a different phase (below). |
| `si-io-write` | `pif-ram` | n64-systembench SI I/O W: one PIF RAM word write, then 8-poll rounds of SI_STATUS until idle |
| `si-dma` | `write64`, `write64-rom`, `read64-{1..4}`, `empty-{0,1,4,8,32,56,63}b`, `accessory` | n64-systembench SI DMA W RAM and ROM, and JOY: a 64 B SI DMA to the PIF RAM or PIF ROM address until SI_STATUS idle, and a 64 B read after a joybus block: n read-buttons commands, an end marker after N zero bytes, or one info command |
| `ifill-isolated` | `warm`, `cold` | The kit's `ifill` points: one call to a function alone in its 32 B I-cache line, with the line index-invalidated first (`cold`) or not. `cold_minus_warm_pclk` is one instruction-cache fill |
| `wb-fifth-store` | `sw-<1..8>`, `sw-<1..8>-lw` | The kit's `wb-stores` points: N back-to-back uncached RDRAM stores, alone or followed by one load. `minus_prev_pclk` is the Nth store's cost over N - 1 |
| `rdp-loadsz-sweep` | `{block,tile}-<8..4096>-n{1,4}` | The kit's `tex-load` points: one or four back-to-back Load Block or Load Tile commands of RGBA16. `per_load_clk` is (4 loads less 1) / 3 of TMEMBUSY; its fit over bytes, `clk_per_byte` and `intercept_clk`, is on the 4096 B `n4` point |
| `vi-frame-latch` | `base`, `vvideo-outside`, `vvideo-outside-late`, `y-late-bank{2,3}` | kit-bus's frame-latch points (#107): uncached loads over 10 VI lines after V_VIDEO, or ORIGIN with Y_SCALE and Y_OFFSET, is written mid-frame. `report.py` derives which reference the late V_VIDEO case matches (`fetches`) and which bank the VI reads after the Y write (`vi_bank`) |

The last four ROMs run the calibration kit's own builders or points (`suites/calib`) under the bench check's name, so the fork's bench and the console kit measure each quantity one way. They need the kit's kernels (`benches.ROM_ASM`, and `sets.EXTRA_ASM` for `vi-frame-latch`, whose kernels live in a module that imports `benches`).

The n64-systembench ports run its TIMEIT_MULTI: 50 reps (10 for `write64`, `write64-rom` and `pi-dma-sizes`), and `report.py` takes the mean of all but the lowest and highest rep in its xcycle units, truncated to whole pclk or rclk (`sb_pclk`, `sb_rclk`). Its harness adds about 2 pclk, its cached read (3) less a cached hit (1). The port's harness is its own, so `net_pclk` is `sb_pclk` less the port's overhead, measured the same way from the ROM's `c<bits>` point (`overhead_pclk`). The bands are the original's pass rule: within 1 pclk or 2 rclk, or under 0.2 %.

A TIMEIT_WHILE result can only end on a poll, and the polls are about 25 pclk apart. The core is deterministic, so every rep would put the poll grid at the same phase, and the result would be the busy time plus that one phase's delay. The `pi-dma-sizes`, `pi-io-write`, `si-io-write` and `si-dma` `write64*` reps therefore run 0 to 49 nops (5 per rep for the 10-rep points) between the write and the first poll. This spreads them over two poll periods. These points print `walk=poll` and `max2`, the second highest rep (the highest is the cold first one, which TIMEIT_MULTI drops too), and `report.py` takes `min`..`max2` as the model's range over poll phase (`sb_rclk_rep_min`, `sb_rclk_rep_max`).

RDP lists use 1-cycle mode with the combiner outputting the primitive color. The blender, Z and image read are off. The color image is 320-wide RGBA5551 at 0x00700000. The VI is blanked while an RDP list runs. Each list is built in uncached RDRAM at 0x00600000, ends with `SYNC_FULL`, and is timed until the DP interrupt.

Memory map (physical): the runtime owns banks 0-4. The memset buffer, the row sweep and the D-cache miss lines are in bank 5. The RDP list, the SP and PI DMA buffers and the drain address are in bank 6. The RDP color image is in bank 7.

## Phase

A bench value from one boot is one point on a sawtooth. The value depends on where the measurement starts against the VI line, the refresh and the CPU's poll loops, and the start moves with every byte of boot code (verify-76: `sp-dma-sweep` `wr-4096-off0` read 6.169 to 6.678 B/rclk over 49 boot offsets of one model). So no verdict rests on one boot. `phases.py` lists the boot delays. The runtime's `BOOT_DELAY_LOOP`, which only bench sets get, spins K iterations at the ROM entry, so each delay moves the start without moving code. `report.py` reads every delay and reduces each metric to its phase range (min and max, widened by the kept reps of a poll-walked point), median and mean.

The value also moves with code layout. Four extra runtime instructions moved `mi-memset-rspdma`'s minimum from 6.422 to 6.492 B/rclk, and with the layout moved by 4 to 6 words its mean over the delays is 6.491 against a 6.49 floor (verify-79). So `phases.py` also lists layout pads. A pad of P words (`runtime.layout_pad`, set by the `LAYOUT_PAD` constant) sits at boot after the delay loop and moves every later instruction by 4P bytes. Pads 0 to 7 cover one 32 B I-cache line; pad 8 gives pad 0's values exactly (verify-79). Each pad is walked over every delay. Every range in `results.tsv` is joint over the pads and delays. Each pad gets its own verdict under the row's rule, and the row's verdict follows the plan's layout rule (docs/design/green-plan.md section 3, Bench layout pads): it holds only if it is the same at every pad, otherwise the row is `consistent-only` with its joint range, and `report.py` prints each pad's verdict beside it.

Each `check` row names a `rule`. The rule follows from what the hardware number is:

| Rule | Passes when | Rows | Why |
|---|---|---|---|
| `consistent` | the band overlaps the model's phase range | n64-systembench ports | The original's reps are phase-locked (VI and interrupts off, main.c:623-624, one master clock; inferred in sysbench2 and verify-76), so its number is one unknown phase. Only consistency with the model's range can be asserted. |
| `mean` | the model's phase mean is in the band | `mi-memset-*` | The n64brew memset times cover 41 to 780 VI lines each, so they average many refresh and fetch phases. `sp-dma-sweep` reports the RSP DMA memset rate, the memset's average over 256 transfers, against one transfer that includes its setup and poll exit, so it asserts nothing. |
| `every` | every delay is in the band | `rdp-*`, `uncached-vs-hpos` | A documented fixed cost (a sync, a setter, the 1-primitive gap) or one refresh per line must hold at every phase. |

A `consistent` pass is weaker than the other two. The model median may move by half the band plus half its own phase range and still pass, so `results.tsv` gives each consistent row that window as a % of the hardware number (`window_pct`; `pi-io-write` is about ±8 %, since one 16.7 rclk poll period is wider than its 4 rclk band). It also gives the `mean` rule's verdict on the same values (`mean_verdict`). A row that passes `consistent` and fails `mean` is `consistent-only`: some phase of the model agrees with the hardware number, the model's average does not. That is consistency with the hardware number, not agreement, and `behaviors.py` counts it apart from pass.

A check row whose pass rests on a model choice with no hardware reference names that choice's issue in `condition`, and its pass reads `pass-conditional:<issue>`. `mi-memset-rspdma` is `#77`: its mean is in the band only because of the idle VI's 0x800-VCLK grid; with a 1-VCLK idle step it reads 6.422 B/rclk at every delay (verify-78), a fail.

The `si-dma` JOY points end on a one-read poll loop that the port does not walk, so their range covers boot phase only, not poll phase.

The delays come from two measured periods.

- The idle VI. While VI_CONTROL selects no pixel type, the VI posts a line event every 0x800 VCLKs, 3944 pclk (`ares/n64/vi/vi.cpp` `VI::line`). The first line after `vi_init` sets a type starts on that grid, so the VI's line phase against the program is set by where the boot ends against a grid that runs from power-on. One delay iteration is 3 pclk, so the grid is 3944 / 3 = 1314.7 iterations (measured dip spacing 1314 and 1315, verify-78). Over 872 delays (K = 1 to 400, every 13th to 5991, then 40 geometric steps to 625302, about 1.2 VI fields), `mi-memset-rspdma` dips to 6.42 B/rclk at K = 1 and 1300 to 1316 (every delay; a scan of every K = 1 to 1330 puts the dip at 1292 to 1316, verify-78), and near 2611, 3924 and 5237 (every 13th delay), and `sp-dma-sweep` `wr-4096-off0` repeats its 6.16 to 6.69 pattern on the same period. No value appears past the first period that the first period lacks. With the idle step at 1 VCLK (a scratch build), every value is the same at all 45 delays tried.
- The CPU poll loops, 25 and 26 pclk.

`phases.py` takes 32 delays 41 iterations (123 pclk) apart. They cover one grid period and land at 32 different poll phases (123 mod 26 = 19). The 32 give every check the verdict the 872 give. Every pad walks all 32: with pads 1 to 7 at every second delay, `mi-memset-rspdma` reads consistent-only instead of pass-conditional, because its mean at pads 4 to 6 sits 0.001 above the band floor (measured from a full grid's `phases.tsv`, u-layout). A standing bench run is 8 x 32 phase points, 5120 ROM builds and 5120 runner runs: 32 s to build with `build.py`'s 8 workers and 536 s to run with 4 runners (measured at load average 39 to 67; one pad was 24 s and 95 s at a similar load).

`N64_BENCH_DELAYS=K,K,...` and `N64_BENCH_PADS=P,P,...` replace the lists in `build.py`, `run.sh` and `report.py` alike, for a scan.

## expected.tsv

The columns are `rom`, `point`, `metric`, `expected`, `lo`, `hi`, `kind`, `rule`, `condition` and `source`.

- `kind` is `check` when a timing-core unit asserts the row, under its `rule` (see [Phase](#phase)), and `report` when the value is only shown. `report` rows are values with no hardware measurement, values whose sources conflict, and values whose provenance is doubted. A `report` row's `rule` is `-`. `behaviors.py --check` rejects a check row without a rule.
- `condition` is `-`, or the `#<issue>` of a model choice with no hardware reference that the row's pass depends on (see [Phase](#phase)). A `report` row's `condition` is `-`.
- `source` cites the hardware reference: the n64brew page, the research doc section on its `research/*` branch, or the n64-systembench line. n64-systembench has no license, so only its numbers are cited. No code is copied from it.
- Metric names come from `report.py` `derive`. For example, `pclk_per_sd` is 2 x min ticks / (bytes / 8), and `per_sync_clk` is the DPC_CLOCK difference from the empty list, divided by N.

Plan unit T3 consolidates these rows into `checks.tsv`.

## Attribution

All code in this suite was written for this repository. The measurement designs follow the descriptions in the cited references. No third-party code is included.
