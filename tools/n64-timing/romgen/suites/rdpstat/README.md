# rdpstat

The rdpstat suite builds self-checking ROMs that test RDP command sequencing: the DPC registers, the command DMA, and what the pixel pipeline does when a program leaves out a sync.

| ROM | Tests | Source | Expectations come from |
|---|---|---|---|
| `rdpstat-systemtest.z64` | 6 tests, 7 values: START/END masking, START_VALID, the status pattern during a run, and three XBUS (DMEM) runs | n64-systemtest `src/tests/rdp/mod.rs` | The test source |
| `rdpstat-dpc.z64` | 2 tests: DMA_BUSY while a long list is fetched, and the START/END double buffer (END_PENDING) | Written for this suite | n64brew `Reality_Display_Processor/Interface` and MiSTer `RDP.vhd`, as cited in `docs/research/rsp-rdp-fifo.md` rows 9, 10 and 12. No console capture backs them. |
| `rdpstat-repeater64.z64` | "RDP 1-Cycle No-Sync" (20 values) and "RDP Fill-Mode Syncs" (1 value) | repeater64 `src/demos/RDPNoSync1C.cpp`, `RDPSync.cpp`, `src/rdpDumpTest.cpp`, `src/rdp/rdp.h` | No-Sync: the 20 console framebuffer dumps `assets/10000000.test` to `10000013.test`. Fill-Mode Syncs: the repeater64 README ("on console you will see the color set after the rectangle command"). |
| `rdpstat-1prim.z64` | 4 tests: four stacked one-row image-read rectangles, 1- and 2-cycle, 8 and 32 px wide | Written for this suite (plan T13) | cen64 jgemu `rdp_core.c:4551-4567`, which states the outcome it fit to the PRDP 12:15 and 12:16 checksums: non-atomic narrow stacks retire the two-blend value, atomic and wide (25 px or more in 1-cycle) stacks the four-blend value. The two- and four-blend values are atomic stacks of 2 and 4 in the same ROM, so each check compares two outcomes. The capture set is not public (`docs/research/1prim-cost.md`). |
| `rdpstat-unsynced.z64` | 2 tests: a Set Combine written right after a 64x4 rectangle with no SYNC_PIPE, 1- and 2-cycle | Written for this suite (plan T15) | The n64brew `Reality_Display_Processor/Pipeline` table "Effect of unsynced attribute changes", combiner row: the last 24 cycles (1-cycle) or 22 (2-cycle) of the rectangle take the new combiner, as cited in `docs/research/rdp-command-timing.md` s.3.7. No console capture backs it. |

## Commands

Run these from the repository root.

```sh
python tools/n64-timing/romgen/build.py --suite rdpstat --out $N64_TIMING_HOME/roms
N64_RUN=<path to n64-run.exe> tools/n64-timing/romgen/suites/rdpstat/run.sh
```

- The build reads the 20 No-Sync references from a local repeater64 checkout. The default path is `$N64_TIMING_HOME/scratch/r29/clones/repeater64/assets`; set `REPEATER64_ASSETS` to override it. The build stops if a file's SHA-256 differs from the value pinned in `repeater64.py`. The references are not committed.
- `run.sh` writes `$N64_TIMING_HOME/results/rdpstat/<set>/` with `stdout.txt`, `stderr.txt`, `values.tsv` and `summary.txt`.

## Port notes

- A Rust `?` ends a test at its first failed assertion. The port puts a `checkpoint()` at each such point that has later side effects, like romgen's nemu64 port does.
- `wait_for_status` polls 10,000 times, as in the Rust source. The repeater64 waits poll up to 2^26 times instead of using a 100 ms tick timeout.
- `RSP::start_dma_cpu_to_sp` writes the byte length, not the length minus 1, to `SP_RD_LEN`. The port does the same.
- The No-Sync port draws each test case once. It skips `RDPDumpTest::run`'s crash probe (a SYNC_PIPE + SYNC_FULL list followed by a PIPE_BUSY check) and the on-screen report. The ROM counts the pixels in the test region (x 16 to 304 inclusive, y 48 to 191) that differ from the reference, as `rdpDumpTest.cpp` does.
- The Fill-Mode Syncs port draws one row (y = 100) of 160 two-pixel fill rectangles in the demo's command pattern (SetFillColor A, rectangle, SetFillColor B, SYNC_PIPE). The fill colors are fixed instead of sampled from an image, and the port appends SYNC_FULL so the CPU can wait for the list. The check expects every pixel in color B.
- The command encoders are the shared builder in `../../rcp.py`. They follow both sources' encoders field for field (checked by ROM bytes).

## Attribution

- n64-systemtest, https://github.com/lemmy-64/n64-systemtest at commit `196f542`. MIT License, copied in `LICENSE.n64-systemtest`.
- repeater64, https://github.com/HailToDodongo/repeater64 at commit `6ec3811`. The repository has no LICENSE file. Each ported source file carries the header `@copyright 2025 - Max Bebök` (`2024` for `src/rdp/*`) and `@license MIT`. The MIT terms are the same as in `LICENSE.n64-systemtest`, with that copyright line. The reference dumps carry no header of their own, so this suite reads them from a local checkout and does not redistribute them.
- `RDPQ_COMBINER1((0,0,0,ENV), (0,0,0,1))` in `repeater64.py` is evaluated from libdragon `include/rdpq_macros.h` at commit `e356bf3` (Unlicense).
