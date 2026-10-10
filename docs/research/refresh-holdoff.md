# The 74.67 rclk hpos "holdoff"

Green-plan unit U-REFRESH. Question: the bench report row `uncached-vs-hpos bank5 holdoff_rclk_max` reads 74.67 rclk, but the model's refresh holds the channel for 52 rclk clean or 54 rclk dirty (`ri.refresh-clean`, `ri.refresh-dirty`). Is the model's per-hit refresh cost to a CPU load too large?

**Answer.** No. The 74.67 is not a refresh cost. It is the first sample of the window, which pays three costs at once: the rest of a refresh holdoff (45.25 rclk), a cold instruction-cache line inside the timed instructions (23.83 rclk), and a row miss on the first load to bank 5 (5.5 rclk). Every other refresh hit in the run costs a load at most 44.67 rclk over the median, which is inside 52. The model's refresh cost agrees with the RI row. The statistic does not measure a holdoff for its first sample, on the model or on a console.

Evidence labels: [M] measured in this unit, [C] cited, [I] inferred.

## Reproduction

Master at 78b4427b8, runner and ROMs built from that tree with a private `N64_TIMING_HOME`:

```sh
export N64_TIMING_HOME=~/n64-timing/home-u-refresh N64_BUILD_DIR=~/n64-timing/build/u-refresh
tools/n64-timing/build.sh
python3 tools/n64-timing/romgen/build.py --suite bench --out $N64_TIMING_HOME/roms/bench \
  --ipl3 ~/n64-timing/scratch/r29/clones/libdragon/boot/bin/ipl3_compat.z64
BENCH_RESULTS=~/n64-timing/results/u-refresh/before/bench \
  bash tools/n64-timing/romgen/suites/bench/run.sh uncached-vs-hpos
```

Result: `holdoff_rclk_max = 74.67..74.67` at all 32 boot delays [M], the same as the plan's `plan-bus/home/res-base` run. ROM sha256 at boot-1: `320cb0be081cb58b8ccef50faca7d4331da0f150423c5d03b8627c76eab1b693`.

Raw bank-5 latencies at boot-1, in COUNT ticks (1 tick = 2 pclk = 4/3 rclk) [M]:

| Sample | Offset from HSYNC | Latency | Over the median (17) |
|---|---|---|---|
| 0 (first of the window) | 3 | 73 | 56 ticks = 74.67 rclk |
| first of line 2 | 2 | 51 | 34 ticks = 45.33 rclk |
| line 3 | 9 | 44 | 27 ticks = 36.00 rclk |
| line 4 | 9 | 45 | 28 ticks = 37.33 rclk |
| the other 364 | | 17 or 18 | |

So the maximum comes from sample 0 alone. The report takes `max(lat - median)` over the outliers (`tools/n64-timing/romgen/suites/bench/report.py:72`) [C].

## Trace

I added an `ARES_RILOG` log to a scratch build: one line per RI decision in `RiBus::Channel::decide` (requester, address, arrival, grant, data end, row miss), plus one line per COUNT read with the PC. The patch, the attribution script, its output and the ROM hashes are in [refresh-holdoff/](refresh-holdoff/). The raw traces (1.5 MB each, gzipped) stay on unicron in `~/n64-timing/results/u-refresh/trace/`. The instrumented runner printed byte-identical `#bench` lines to the plain runner at boot-1, 42 and 1272 [M]. The patch is not applied to the core.

To rerun the trace:

```sh
git apply docs/research/refresh-holdoff/rilog.patch   # scratch tree only
N64_BUILD_DIR=~/n64-timing/build/u-refresh-instr tools/n64-timing/build.sh
ARES_RILOG=ri.log ~/n64-timing/build/u-refresh-instr/rundir/bin/n64-run \
  $N64_TIMING_HOME/roms/bench/boot-1/bench-uncached-vs-hpos.z64 --emulated-seconds 120
python3 docs/research/refresh-holdoff/attribute.py ri.log
```

Times below are in Clock units: 8 per pclk, 12 per rclk (`ares/n64/timing/clock.hpp:26-29`) [C]. Offsets are from the `mfc0 $t6, $count` that opens sample 0.

| Offset | Event |
|---|---|
| -87 | HSYNC posts a refresh; it reaches the arbiter at -86 (`ares/n64/vi/vi.cpp:62`, `ares/n64/ri/bus.cpp:11`). |
| -80 | The refresh wins the channel (rank 0, `ares/n64/ri/bus.hpp:99`) and holds it 624 units = 52 rclk, clean (`bus.hpp:198`). |
| -40 | `bh_sync2` has seen VI_CURRENT change; `mfc0 $t3` reads the window base (pc 0x80001604). |
| 0 | `mfc0 $t6` at pc 0x80001618, the first instruction of `bh_loop` (`tools/n64-timing/romgen/suites/bench/asm.py:399`). |
| +1 | The fetch of 0x80001620 (the `addu` after the timed `lw`) misses the I-cache. Its 32 B fill reaches the RI. The loop has not run yet, so this line is cold. |
| +544 | The refresh releases the channel. The I-fill is granted after waiting 543 units. |
| +622 | I-fill data end: 78 units on the wire (row hit, 4 octbytes). |
| +830 | The pipeline restarts, 208 units later (`IfillPath`, `ares/n64/cpu/sysad.hpp:63`, applied at `sysad.cpp:163`). |
| +841 | The timed `lw` from 0xA05A0000 reaches the RI. Bank 5 has no open row: a clean row miss, 108 units instead of 42 (`bus.hpp:206`, `ri.retry-clean` 22 tc at `bus.hpp:117`). |
| +1176 | `mfc0 $t8` closes the sample. A normal sample closes at +280. |

The attribution script reproduces the same numbers at boot-42 and boot-1272 [M]. The sync loop aligns sample 0 to the HSYNC that starts the refresh, so this sample is not a phase lottery. That is why the value is identical at all 32 delays.

## The 74.67 as a sum

Excess of sample 0 over a normal sample, 1176 - 280 = 896 units [M]:

| Cost | Units | rclk | Source |
|---|---|---|---|
| Rest of the refresh holdoff, paid by the I-fill | 543 | 45.25 | `ri.refresh-clean` 52 rclk (624 units) less the 81 units already elapsed; `bus.hpp:161,198` |
| I-fill wire time, row hit | 78 | 6.50 | `ri.read-hit` 10 tc + 4 x `ri.octbyte` 4 tc; `bus.hpp:113-119` |
| I-fill restart path | 208 | 17.33 | `cpu.ifill-stall` 45 pclk less `MeanEdgeWait` (8) and the clean-miss wire (144); `sysad.hpp:46-64` |
| `lw` issue offset after the restart, net | 3 | 0.25 | 1 (I-fill post) + 11 (restart to `lw` arrival) - 9 (normal `mfc0` to `lw` arrival) |
| Row miss on the first bank-5 load | 66 | 5.50 | `ri.retry-clean` 22 tc; `bus.hpp:117` |
| Edge alignment after the data | -2 | -0.17 | 224 units data end to `mfc0` vs 226 in a normal sample |
| **Total** | **896** | **74.67** | |

The refresh's own share is 45.25 rclk, below its 52 rclk length, because the load cannot arrive before the CPU notices the HSYNC. The I-fill and the row miss are first-iteration costs of the measuring loop, not refresh costs.

## What this means

- **The model's per-hit refresh cost agrees with the RI row [M].** In every pure refresh hit the load waits only for the rest of a 624-unit refresh: 543, 439 and 451 units, for excesses of 44.67, 36.00 and 37.33 rclk. No pure refresh hit exceeds 52 rclk. This trace saw no VI burst in the bank-5 window, so bus.md's guess (VI bursts at rank 1 queued ahead of the CPU) is not the cause.
- **The report row's expected value (53, 52..54, `tools/n64-timing/romgen/suites/bench/expected.tsv:17`) is not what the statistic measures [I].** On a console the same ROM would also put sample 0 on an HSYNC, with a cold 0x80001620 line and a closed bank-5 row. The row is report-only, so no check changes.
- **This does not explain the systembench +2..+3 under refresh-at-blank [I].** That is a mean over many loads. With a per-hit cost of at most 52 rclk, the inflation must come from how often loads land in a refresh, not from a per-hit cost above the RI row. This unit did not trace it.

## Follow-ups

- Make `holdoff_rclk_max` measure a holdoff: run one untimed `bh_loop` iteration before the window (warms 0x80001620 and opens the bank-5 row), or drop sample 0 from the statistic. From this trace the row would then read the largest pure-refresh excess, 45.33 rclk at boot-1 in COUNT ticks [I]. That is a harness change for a label or harness unit, and it should land with `item:fu.hpos-holdoff` (`tools/n64-timing/calibration/items.tsv:47`), which already names "a window that starts on a refresh".
- The systembench +2..+3 under refresh-at-blank needs its own trace (hit frequency per load) before any refresh-at-TYPE=0 decision. Plan section 8 still forbids turning refresh on while the VI is blank.
