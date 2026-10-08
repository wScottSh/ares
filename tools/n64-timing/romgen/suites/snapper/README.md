# snapper

The snapper suite ports four test families of [snapper64](https://github.com/HailToDodongo/snapper64) at commit `e1cd8a61fc43` to romgen ROMs. snapper64 is an RDP test ROM whose references are console dumps of each test's surface. The ROMs here run the same RDP command lists and print one record per surface. `compare.py` checks the records against the console dumps.

| Set (check id) | ROM | Source | Records | Reference |
|---|---|---|---|---|
| `span-tri` (`snapper:span-tri`) | `snapper-span-tri.z64` | `src/tests/RDPTestModeSpan.cpp` | 216 tests x 2: the 76x64 triangle surface and the 4x32 span-buffer surface read back through DPS test mode | 432 console dumps |
| `test-mode-rw` (`snapper:test-mode-rw`) | `snapper-test-mode-rw.z64` | `src/tests/RDPTestModeRW.cpp` | 32 tests x 128 span-buffer words read back through DPS test mode | The source's assertion (`cases.expected_rw`). snapper64 has no dumps for this group. |
| `fill-tri-sweep` (`snapper:fill-tri-sweep`) | `snapper-fill-tri-sweep.z64` | `src/tests/RDPFillTriSweep.cpp` | 2048 tests x the 128x128 surface | 2048 console dumps |
| `rect-nosync` (`snapper:rect-nosync`) | `snapper-rect-nosync.z64` | `src/tests/RDPRectNoSync1C.cpp`, `RDPRectNoSync2C.cpp`, `RDPRectNoSyncFill.cpp` | 20 + 40 + 20 tests x the 288x180 surface | 80 console dumps |

## Commands

Run these from the repository root.

```sh
tools/n64-timing/romgen/suites/snapper/fetch.sh
python tools/n64-timing/romgen/build.py --suite snapper --out $N64_TIMING_HOME/roms
N64_RUN=<path to n64-run.exe> tools/n64-timing/romgen/suites/snapper/run.sh
```

- `fetch.sh` clones snapper64 into `$N64_TIMING_HOME/corpora/snapper64`, runs `git lfs pull` for the 7094 `assets/*.test.7z` archives (4.3 MB), and extracts them into `$N64_TIMING_HOME/corpora/snapper64-decoded/` (688 MB). Without git-lfs it downloads the same objects through GitHub's LFS batch API and checks each one's sha256 against its pointer. It extracts with `7z` or `7zz` when present and otherwise `tar.exe` or `bsdtar` (libarchive reads 7z). It runs nothing from the clone. A rerun skips the work already done.
- `build.py --suite snapper` writes the four ROMs. `--define DUMP=1` makes every record carry a full hex dump. Without it, only the span-buffer and R/W records carry one.
- `run.sh` writes `$N64_TIMING_HOME/results/snapper/<set>/` with `stdout.txt`, `stderr.txt`, `records.tsv` and `compare.txt`, and appends each set's lines to `summary.txt`. `SNAPPER_ROMS` and `SNAPPER_RESULTS` override the ROM and result directories.
- `compare.py SET STDOUT OUT_DIR` compares one set. It first checks the dumps the set reads against the digest pinned in `REFERENCE_DIGEST`, and stops if they differ. If the dumps are missing, it prints `pending:snapper-lfs`.

## Output format

Each record is one line, followed by the emux `XHEXDUMP` of its bytes when the record is dumped:

```text
@snap <id> <bytes> <fnv>
```

- `<id>` is snapper64's dump name, `%08X_%08X_%02X` of `crc32(group name)`, `crc32(test name)` and the 1-based assert index (`src/framework/assert.cpp`). The console dump of the record is `<id>.test`.
- `<bytes>` is the record size. Surfaces are RGBA32, big-endian, rows packed.
- `<fnv>` is FNV-1a 32 over the big-endian words, computed by the ROM.

`records.tsv` gives each record's result, `match`, `differ` or `not-run`, and the number of differing pixels when the record was dumped. `compare.txt` has one `snapper:<set> <group>: X/Y match` line per group.

## Port notes

- The triangle encoder (`tri.py`) reproduces `src/renderer/rdp.cpp` in float32, one rounding per operation, as the VR4300 build computes it (`-fsingle-precision-constant`, no fused multiply-add). Like the source, it takes the shade deltas from the vertices in argument order and the edges from the Y-sorted order.
- The simple commands use the shared builder `../../rcp.py`. Its command bytes carry the RDP's command id in bits 56-61 with bits 62-63 set (`0xFF` for SET_COLOR_IMAGE). snapper64's encoder leaves bits 62-63 clear (`0x3F`). ares and paraLLEl-RDP decode only bits 56-61.
- The combiner words are evaluated from libdragon `include/rdpq_macros.h` at commit `e356bf3` (`RDPQ_COMBINER1`, `RDPQ_COMBINER2`, including the `RDPQ_COMBINER_2PASS` bit).
- Each test runs its lists the way `RDP::DPL::runSync` does: wait for DMA_BUSY clear, START, END, wait for PIPE_BUSY clear. `TestSurface::attachAndClear` runs the attach list and clears the surface with the CPU. The port runs the list to completion and then clears; the source clears while the list runs. The attach list draws nothing, so the surface content is the same.
- Surfaces sit at fixed addresses (`0x00500000`, span surface `0x00540000`, R/W words `0x00541000`). snapper64 allocates them per test with `surface_alloc`.
- The runtime's VI shows a 320x240 16 bpp framebuffer. snapper64 shows 320x240 RGBA32 (640x480 for the R/W group) and draws text between tests. The VI's RDRAM traffic therefore differs. Only tests whose result depends on RDP timing, such as the no-sync groups, can observe it.
- The R/W group asserts values, not surfaces. The ROM reads the 128 words back into a buffer, and `compare.py` checks them against the rule the source asserts: register `i` holds the last word written to `i mod 128`, words `4k+2` keep their low byte, and words `4k+3` read 0.

## Attribution

snapper64, https://github.com/HailToDodongo/snapper64 at commit `e1cd8a61fc43`, copyright 2025 Max Bebök, MIT License, copied in `LICENSE.snapper64`. The console dumps are not committed. `fetch.sh` downloads them, and `compare.py` reads them from the corpus directory.
