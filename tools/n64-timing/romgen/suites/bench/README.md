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

- `build.py` writes one `bench-<rom>.z64` per ROM, and a `bench-<rom>.tests.tsv` listing that names every point. Two builds produce byte-identical files.
- `run.sh` runs each ROM and writes `results/bench/<rom>/{stdout,stderr}.txt`. It then runs `report.py`, which writes `measurements.tsv` (every raw and derived value) and `results.tsv` (one row per `expected.tsv` entry, with a verdict). `run.sh` exits 1 only when a ROM did not print every point in its listing. A value outside its band is reported but does not change the exit code.
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
| `pi-dma-sizes` | `poll`, `cart-to-ram-{8,128,1024,65536}` | One PI DMA from cartridge 0x10000000, from trigger to `PI_STATUS` idle |
| `uncached-vs-hpos` | `bank5`, `bank2-vi` | Back-to-back timed uncached LWs over three VI lines, each with its offset from the line start. Bank 2 holds the VI front buffer. |
| `dirty-row-sweep` | `{clean,dirty}-<delta>` | One uncached LW after the bank's open row was read (clean) or written (dirty). The target is the same row (`8`) or another row in the same bank. |
| `dirty-miss-isolated` | `{invalid,clean,dirty}-{single,gap0,gap20,gap80}` | A D-cache LW miss whose victim is invalid, clean or dirty. Optionally a second miss follows after a 0, 20 or 80 iteration loop. |
| `rdp-sync-sweep` | `none-0`, `{pipe,tile,load}-{16,64,256}`, `rect-{16,64}`, `rect-{kind}-{16,64}` | N bare syncs, or N times an 8x1 rect followed by a sync |
| `rdp-setter-sweep` | `none-0`, `{nop,prim-color,env-color,other-modes}-{256,1024,4096}` | N one-word commands |
| `rdp-atomic-sweep` | `atomic{0,1}-{1,16,64}` | N 16x4 1-cycle rects with `atomic_prim` off or on |
| `rdp-rectn` | `rect-320x6`, `rect-320x6-x8`, `duty-320x240` | The cen64 dpc_probe RECTN and DUTY shapes |

RDP lists use 1-cycle mode with the combiner outputting the primitive color. The blender, Z and image read are off. The color image is 320-wide RGBA5551 at 0x00700000. The VI is blanked while an RDP list runs. Each list is built in uncached RDRAM at 0x00600000, ends with `SYNC_FULL`, and is timed until the DP interrupt.

Memory map (physical): the runtime owns banks 0-4. The memset buffer, the row sweep and the D-cache miss lines are in bank 5. The RDP list, the SP and PI DMA buffers and the drain address are in bank 6. The RDP color image is in bank 7.

## expected.tsv

The columns are `rom`, `point`, `metric`, `expected`, `lo`, `hi`, `kind` and `source`.

- `kind` is `check` when a timing-core unit asserts that `lo <= value <= hi`, and `report` when the value is only shown. `report` rows are values with no hardware measurement, values whose sources conflict, and values whose provenance is doubted.
- `source` cites the hardware reference: the n64brew page, the research doc section on its `research/*` branch, or the n64-systembench line. n64-systembench has no license, so only its numbers are cited. No code is copied from it.
- Metric names come from `report.py` `derive`. For example, `pclk_per_sd` is 2 x min ticks / (bytes / 8), and `per_sync_clk` is the DPC_CLOCK difference from the empty list, divided by N.

Plan unit T3 consolidates these rows into `checks.tsv`.

## Attribution

All code in this suite was written for this repository. The measurement designs follow the descriptions in the cited references. No third-party code is included.
