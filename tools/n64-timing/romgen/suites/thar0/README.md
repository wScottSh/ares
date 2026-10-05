# thar0 suite

A romgen port of [Thar0/RDP-Timing-Tests](https://github.com/Thar0/RDP-Timing-Tests) at commit `a81ced93b28d`. The ROM times a 320x240 RGBA16 fill rectangle under 100 RDP and VI configurations with the DPC `BUFBUSY` and `PIPEBUSY` counters. `expected.tsv` holds the console's min, average, and max for each configuration, so the suite measures how close the emulator's RDP timing is to hardware.

## Commands

Run these from the repository root.

```sh
python tools/n64-timing/romgen/build.py --suite thar0 --out $N64_TIMING_HOME/roms [--define RUNS=1000]
tools/n64-timing/run-thar0.sh [--cpu interpreter|recompiler]
python -m romgen.suites.thar0.selftest                     # from tools/n64-timing
python -m romgen.suites.thar0.import_hw <clone dir>        # from tools/n64-timing; rewrites expected.tsv
```

- `build.py` writes `thar0-rdp.z64`. Two builds from the same sources give byte-identical files.
- `RUNS` is the number of timed rectangles per configuration. The original uses 1000. The default is 32, which takes about 36 s of emulated time. 1000 runs would take about 18 minutes, extrapolated linearly and not measured.
- `run-thar0.sh` runs the ROM and then `compare.py`. The comparator prints one row per configuration, with model and hardware min/avg/max in RDP clocks (62.5 MHz) and the difference of the averages. It writes the same table to `compare.tsv`, and it exits 1 if any configuration printed no result.

## Files

| File | Role |
|---|---|
| `configs.py` | The 100 `timing_specs[]` entries, in the C table's order, with the `GROUP` and `AC_GROUP` macros ported as functions. Each spec has a stable `id` such as `ac-zbsep-vioff-noimrd-1cyc`. |
| `thar0.py` | The ROM: the per-spec VI register writes, the setup command list, and the `thar0_spec` routine (`exec_timing` and `main`'s print loop). |
| `../../rcp.py` | Generic helpers that other suites can use: the RDP command encoders, `rdp_exec`, `wait_count` and `io_writes`. |
| `expected.tsv` | Hardware results from `compare.py` `hw_data`, converted from ms to clocks (x 62500). `import_hw.py` generates it and checks that the values match `sample_results.txt` (100/100 match). |
| `compare.py` | Parses the ROM output, reduces each list as `analyze.py` does (drops values outside the 1% and 99% quantiles), and prints model against hardware. |
| `selftest.py` | Checks the RDP encodings against known GBI values, the hardware anchors 77772 and 155052, and the comparator's parsing and reduction. |

## Output

For each configuration, the ROM prints the original's block through emux `XLOG`:

```text
<desc>
BUF = [
    <BUFBUSY - baseline - 1>, ...
]
PIPE = [
    <PIPEBUSY - baseline - 1>, ...
]
```

The baseline is the counter value after a lone `FULLSYNC`, as in the original. The subtraction wraps in 32 bits like the C `%lu` print. `compare.py` reads the result as signed. Each block sits inside the romgen runner's `Running ...` line and `@<n>.0` record. The final `Thar0: Failed 0 of 100` line only counts the configurations that ran. It does not compare anything.

## Port notes

These are the places where the port is not a direct translation of `src/test_main.c`.

- **DP interrupt.** The original waits for the DP interrupt in a handler. The port polls `MI_INTR` bit 5 and acknowledges the interrupt through `MI_MODE`. The counters are read 2 ms later in both versions, so the change does not affect the result.
- **Random wait.** The original calls `srand(C0_COUNT())` and waits `(rand() >> 28) & 0xF` ms before each run, which is 0 to 7 ms with newlib's `rand`. The port uses the same newlib LCG with the unseeded state 1, so the ROM is deterministic.
- **Buffer placement.** The original's `fb_region` is a static 1 MiB-aligned array. The port puts it at `0x80100000` (bank 1), which is inferred from libdragon's layout and not observed. The original puts the separate Z-buffer at `0xA0400000` (bank 4). romgen's runtime keeps its data and stack in bank 4, so the port uses `0xA0600000` (bank 6) instead. Both banks are on the Expansion Pak and neither holds the framebuffer. The separate VI buffer stays at `0xA0500000`.
- **Command lists.** The setup list is generated on the host and stored in the payload. The per-run list (`gfx_run[]`) is written through KSEG1 at `0xA07F0000`, near the top of RDRAM where libdragon's stack holds it, so no cache writeback is needed. DPC addresses are written as physical addresses.
- **PIF.** The romgen runtime does not set the PIF boot-termination bit, and ares halts the CPU 5 s after boot without it. `thar0_spec` sets the bit, as libdragon's boot code does.
- **Run count.** `RUNS` defaults to 32 instead of 1000 (see Commands).

## Attribution

The suite is a port of Thar0/RDP-Timing-Tests at commit `a81ced93b28d`. `expected.tsv` holds that repository's hardware measurements. RDP-Timing-Tests is distributed under the MIT License. A copy is in `LICENSE.RDP-Timing-Tests`:

```text
MIT License

Copyright (c) 2023 Tharo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
