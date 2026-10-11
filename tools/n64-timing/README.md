# N64 timing harness

Scripts that build this fork's headless N64 runner (`tools/n64-run`), run ROMs through it, and run the nemu64-test timing corpus.

All host-side state lives under `$N64_TIMING_HOME` (default `~/n64-timing`): build trees, ROMs, and results. Nothing in this directory writes into the repository, and no ROM is committed.

## Prerequisites

The scripts detect the host: `cygpath` on the PATH means Windows (MSYS2), anything else is Linux. `host.sh`, which every script sources, holds the per-host differences: the Python command and where the CMake tree puts each target.

### Windows

- MSYS2 at `C:\msys64` with the clang64 toolchain:

  ```sh
  /c/msys64/usr/bin/pacman -S --needed mingw-w64-clang-x86_64-toolchain mingw-w64-clang-x86_64-cmake mingw-w64-clang-x86_64-ninja
  ```

- Git Bash to run the scripts, and Python 3 for the result parser.
- Docker Desktop, only for `build-nemu64.sh`.

### Linux

- A C++ compiler, CMake and Ninja. `build.sh` uses clang when `clang++` is on the PATH, else gcc. On Ubuntu: `apt install g++ cmake ninja-build`.
- Python 3 (`python3` is enough; `python` is used when present).
- For `romgen/suites/snapper/fetch.sh`: `7z` or `7zz` (Ubuntu `7zip`). `git-lfs` is optional.
- Docker, only for `build-nemu64.sh`.

## Build the runner

```sh
tools/n64-timing/build.sh
```

The script configures `-DARES_CORES=n64`, `RelWithDebInfo`, and Ninja on first use, then builds only the `n64-run` target. It prints the binary path: `$N64_TIMING_HOME/build/<worktree name>/n64-run/rundir/n64-run.exe` on Windows, `$N64_TIMING_HOME/build/<worktree name>/rundir/bin/n64-run` on Linux. `N64_BUILD_DIR` overrides the build directory. A clean build takes about 50 seconds on the Windows reference machine.

## Run a ROM

```sh
n64-run ROM [--frames N] [--emulated-seconds S] [--wall-seconds S]
            [--stats FILE] [--controllers N] [--script FILE]
            [--dump-frame N FILE]... [--behaviors FILE]
```

| Option | Meaning |
|---|---|
| `--frames N` | Stop after N VI fields. Boot time before the VI is enabled does not count. |
| `--emulated-seconds S` | Stop after S seconds of emulated VR4300 time (93.75 MHz PClock). |
| `--wall-seconds S` | Stop after S seconds of host time. This is a safety net and does not affect emulation. |
| `--stats FILE` | Writes one TSV line per VI field. See [Per-field stats](#per-field-stats). |
| `--dump-frame N FILE` | Writes the RDRAM image the VI samples at field N as a 640x480 binary PPM. Repeatable. See [Frame dumps](#frame-dumps). |
| `--controllers N` | Number of gamepads connected at power-on (default 1). |
| `--script FILE` | Runs an input script. See [Input scripts](#input-scripts). |
| `--behaviors FILE` | Writes the timing behaviors the binary was built with (`Timing::behaviors`: id, basis, value, unit, checks) as TSV, then runs as usual. |

The runner always emulates an NTSC console with the Expansion Pak, with homebrew mode (emux, ISViewer) on. The CPU and the RSP always run on their interpreters; the fork has no recompiler.

Output:

- stdout carries only guest output: ISViewer text and emux `XLOG`/`XHEXDUMP` text.
- stderr carries core debug notices, the emux exit message, and one final line: `n64-run: stop=<reason> frames=N emulated_s=X wall_s=Y`. A second line follows: `n64-run: rdp_engine render_calls=N render_ms=X pixels=N ns_per_pixel=X`, the host time spent inside the pixel engine and the pixels it rasterized. A third, `n64-run: ri grants_cpu=N grants_refresh=N cpu_row_misses=N cpu_bytes_read=N cpu_bytes_written=N cpu_wait_rclk=N refresh_busy_rclk=N`, counts the RDRAM channel's grants since power-on: CPU SysAD bursts and refreshes, the CPU bursts that missed their bank's open row, the bytes they moved, the RCP clocks they waited for the channel, and the RCP clocks refresh held it. A fourth, `n64-run: ri_dma grants_sp=N sp_bytes=N sp_wait_rclk=N ...`, gives the same grants, bytes moved and RCP clocks waited for each DMA engine (SP, PI, SI, AI).
- With a script, stderr also carries one `n64-run: mark NAME frame=N` or `n64-run: peek NAME frame=N VALUE` line per `mark` or `peek` step.
- The exit code is 0 for `emux-exit`, `script-stop`, or `frame-limit`, 2 for `emulated-time-limit`, 3 for `wall-time-limit`, and 1 for a load or usage error.

The runner checks the stop conditions between VI fields. A ROM that requests an emux exit therefore runs to the end of the current field.

### Per-field stats

| Column | Source |
|---|---|
| `frame` | VI field index, counted from 0 at the first field with the VI enabled. |
| `origin`, `width`, `depth` | `VI_ORIGIN`, `VI_WIDTH`, and the `VI_CTRL` pixel type at the end of the field. |
| `fb_hash` | FNV-1a 64 of the displayed image: the RDRAM pixels that the VI samples, using the same walk as `VI::refresh`. |
| `cpu_cycles` | Cumulative VR4300 PClock cycles (`cpu.profile.cpuCycles`, the value emux `XPROFREAD 0x0000` returns). |
| `rsp_busy_clocks` | Cumulative non-halted RSP time, in 187.5 MHz ticks (2 per PClock), the core's clock unit before the 750 MHz rebase, so files stay comparable across it. |
| `dpc_start`, `dpc_end` | `DPC_START` and `DPC_END` at the end of the field. |
| `cimg`, `zimg` | The address of the last `SET_COLOR_IMAGE` and `SET_MASK_IMAGE` (Z buffer) command the pixel engine executed. |
| `rdp_pixels` | Cumulative pixels the pixel engine rasterized (clipped span widths summed over every primitive). Deterministic, so it belongs in the `det` comparison. |
| `trace_hash` | `Timing::TraceHash` (`ares/n64/timing/verify.hpp`). A rolling XXH3 hash of every device queue event the core has fired, folded at each row with a hash of the whole serialized machine state (CPU, RSP, RDP, RDRAM, every device). Two runs that diverge anywhere differ in this column from the first field after the divergence on. |

### Input scripts

An input script is a text file with one step per line. `#` starts a comment. The runner executes steps after each VI field until a step has to wait, so a step's effect is visible to the game from the next field. Frame numbers in the log count completed fields, so `mark window frame=N` means the window starts with stats row `N`.

| Step | Effect |
|---|---|
| `wait N` | Waits N fields. |
| `until ADDR W OP VALUE` | Waits until the guest value at `ADDR` compares true. `OP` is `==`, `!=`, `>=`, or `<`. |
| `input [BUTTON...] [x=X] [y=Y]` | Sets controller 1 until the next `input`. Buttons use the gamepad's names: `A B Z Start L R Up Down Left Right C-Up C-Down C-Left C-Right`. `x` and `y` are ares axis values from -32768 to 32767, where `y` < 0 is up. `input` alone releases everything. |
| `poke ADDR W VALUE` | Writes a guest value. |
| `copy SRC DST LEN` | Copies LEN guest bytes. |
| `peek NAME ADDR W` | Logs a guest value as `n64-run: peek NAME frame=N 0x...`. |
| `mark NAME` | Logs `n64-run: mark NAME frame=N`. |
| `bus NAME` | Logs `n64-run: bus NAME frame=N refresh=B,R,W,M,H,T vi=... cpu=... sp=... dp_cmd=... dp_color=... dp_depth=... dp_texture=... dp_fill=... pi=... si=... ai=...`: per RI requester since power-on, bursts, bytes read, bytes written, row misses, RCP clocks it held the channel, RCP clocks it waited. |
| `shot FILE` | Writes the next field's RDRAM image, as `--dump-frame` does, to FILE. |
| `save-state FILE` | Writes the core's save state to FILE. |
| `load-state FILE` | Loads a save state from FILE. The `trace_hash` chain and the RSP profile behind `rsp_busy_clocks` carry across the load, because they describe the run, not the machine. |
| `poke-tmem OFFSET VALUE` | Writes one byte of the pixel engine's TMEM (OFFSET below 0x1000). For checking that the state hash covers TMEM. |
| `stop` | Ends the run with `stop=script-stop`. |

`W` is `b`, `h`, or `w` (1, 2, or 4 bytes). Numbers are decimal or `0x` hex. `ADDR` is a KSEG0 or KSEG1 RDRAM address, and `[EXPR]` loads the word at `EXPR`, so `[[0x801E3FB0]+0x1CCC]+0x24` follows two pointers. A read sees a dirty data-cache line the way a CPU load would, and a write to a cached line goes into the line. Neither touches bus or cache timing state. A step that cannot resolve its address waits (`until`), logs `unreadable` (`peek`), or logs `poke-failed`/`copy-failed`.

`tools/n64-timing/mmbench` uses scripts to run the Majora's Mask bench.

### RDP

The core has one rasterizer: the cen64-jgemu pixel engine (`ares/n64/rdp/engine/`) on the emulation thread, with no worker threads, so the result does not depend on the host. The DPC front end (`ares/n64/rdp/timed.hpp`, `timed.cpp`) is a timeline actor: a `DPC_END` write starts the command DMA, `DPC_CURRENT` advances as its bursts land in the 30-dword command FIFO, the command processor dispatches one command at a time and stays busy for its compute cost, and `SYNC_FULL` raises the DP interrupt when it retires. Each dispatch renders the command's pixels into RDRAM. The engine state (modes, tiles, TMEM, buffered command words) and the front end's state are part of the save state, so `trace_hash` covers them.

`ARES_DPLOG=FILE n64-run ...` logs every `DPC_START`/`DPC_END`/`DPC_STATUS` write, every `DPC_CURRENT`/`DPC_STATUS` read and every DP interrupt. `python tools/n64-timing/dplog-check.py FILE` reports the RSP's back-pressure from it: the `DPC_CURRENT` and `DPC_STATUS` poll loops that iterated, `DPC_END` writes made while `DPC_CURRENT` trailed, and where each DP interrupt fell.

`tools/n64-timing/state-roundtrip.sh ROM [FRAMES]` checks that: a run that saves and reloads its state at fields 150, 300 and 457 must write the same stats file as a plain run, and a TMEM byte poked at field 30 must change `trace_hash` and no other column of that row. It also builds romgen's `state` suite (MI repeat writes behind an RSP DMA, `romgen/suites/state/sets.py`), saves after each field of its plain run but the last, and loads each state in a fresh run after field 0, before the ROM's first repeat write: that run must print the plain run's `#bench` line and rows. The runner reports `posted-repeats=N` at each `save-state` (MI repeat writes posted to the RI and not yet granted), and each ROM fails unless one of its saves holds one; a save that does fails when the state lacks the SysAD entry's repeat flag.

### Frame dumps

`--dump-frame N FILE` writes the image the VI would scan out at field N (the `frame` column of the stats file) as a binary PPM (`P6`, 640x480). The pixels come from RDRAM through the same walk as `fb_hash`, so two dumps compare RDRAM output, not VI filters. 5-bit channels are expanded by a shift. Positions the VI does not sample are black. `tools/n64-timing/framediff.py A.ppm B.ppm [--out diff.png]` reports the differing pixels per tile.

### Determinism

The core reads no host clock or host entropy: its random generator is always seeded with 0, CP0 Random counts instructions, `SP_PC` returns the RSP's PC, and the cartridge and 64DD RTCs start at a fixed epoch. The runner also removes the host dependencies that the desktop build has:

- No screen or audio thread does work. The runner sets ares' run-ahead flag, which makes the screen and audio stream nodes skip their host-side processing, so nothing reads RDRAM concurrently with the core.
- Save files are never loaded or written. mia's save location points at an unused directory next to the binary.
- Wall time is used only for `--wall-seconds` and the stderr stop line.

```sh
tools/n64-timing/determinism.sh ROM [FRAMES]
```

Runs the ROM twice and fails unless every output file is byte-identical, `trace_hash` included. Majora's Mask NTSC-U 1.0 runs every mmbench scene; any other ROM runs FRAMES fields (default 600). A failure prints the first differing row and its columns for each TSV. `N64_RUN` skips the build, and `DET_OUT` sets the output directory (default `$N64_TIMING_HOME/determinism/<rom>`).

```sh
tools/n64-timing/determinism.sh --step-cap ROM [FRAMES]
```

Checks `stepcap`: the second run passes `n64-run --step-cap`, which makes the CPU catch the timeline up before every instruction instead of only at the timeline's horizon. Every output must still be byte-identical, which proves the horizon skip changes nothing. The default output directory is `$N64_TIMING_HOME/stepcap/<rom>`.

### Unit tests

`tools/n64-timing/build.sh` also builds `n64-timing-tests`, the host tests behind the `unit:` checks. Run `n64-timing-tests/rundir/n64-timing-tests.exe` (Windows) or `rundir/bin/n64-timing-tests` (Linux) in the build directory, or `ctest` there. With no argument it runs every test; an argument names one, as the `checks.tsv` selector does (`timeline`, `ri-cost-table`). `unit:timeline` drives `Timing::Timeline` with scripted actors. `unit:ri-cost-table` drives the RI's channel model (`ares/n64/ri/bus.hpp`) alone: wire costs at row hit and miss, arbitration order and refresh. It also builds `n64-timing-dpc-regs` (`unit:dpc-regs`), which drives the DPC register block and the RDP cost model in `ares/n64/rdp/timed.hpp` without a timeline.

## nemu64-test corpus

```sh
python tools/n64-timing/romgen/build.py --suite nemu64 --out $N64_TIMING_HOME/roms
tools/n64-timing/run-nemu64.sh [timing cycle cop0hazard timing-phase timing-phase-2022]
```

`romgen/build.py` generates the three ROMs from the in-repo Python port of nemu64-test, with no external toolchain. See [romgen/README.md](romgen/README.md).

`build-nemu64.sh` is the alternative that builds the original Rust ROMs. It builds nemu64-test at commit `9a8b9f7` in `rust:1-bookworm`, using the toolchain from the repository's `rust-toolchain.toml` (`nightly-2026-07-16`) and `nust64 0.4.1`. It runs `cargo run --release --no-default-features --features <set>`. Docker volumes named `n64timing-*` cache the Rust toolchain and the build trees.

`run-nemu64.sh` writes these files under `$N64_TIMING_HOME/results/nemu64/<set>/`:

- `stdout.txt` is the raw guest output.
- `stderr.txt` holds the stop line and debug notices.
- `frames.tsv` holds the per-field stats.
- `tests.tsv` lists each test with its number of failed values and pass or fail.
- `failures.txt` lists every failure message.
- `summary.txt` holds the ROM's own category totals, such as `Timing: Failed X of Y tests`.
- `values.tsv` (romgen ROMs only) has one row per test value: result, measured cycles, and expected cycles.
- `categories.tsv` (romgen timing ROM only) assigns each failed value to a root-cause category.

`timing-phase` runs the averaged timing tests at every VI phase of `romgen/suites/nemu64/phases.py` ([romgen README, Phase walk](romgen/README.md#phase-walk)). Its directory holds `phase-<K>/` (`stdout.txt`, `stderr.txt` and `values.tsv` per delay), `runs.txt`, `measurements.tsv` (min, max, median and sum of each averaged value at each delay) and `phase.tsv` (each value's phase ranges, phase mean, bands and verdict). `timing-phase-2022` writes the same files for the same tests under nemu64-test's 2022 harness ([romgen README, The 2022 harness](romgen/README.md#the-2022-harness)).

`results/nemu64/summary.txt` concatenates the set summaries.

## Behavior table, spec and checks

`ares/n64/timing/behaviors.tsv` is the one source for every timing constant. Each row has an id, a value, a unit, a basis, a reference, the checks that decide it, the checks a fit was solved from (`fit-from`), and a note. A check written `~id` in the verify column is a guard: it runs and can fail the row, but it never passes it, because it does not measure the row's value. `det` and `stepcap` are always guards. A `model-choice` row whose checks are all guards gets the status `model-choice`, not `pass`. `checks.tsv` defines every check id: its runner, target, selector, expectation and source.

```sh
python tools/n64-timing/behaviors.py              # writes behaviors.hpp, docs/spec/n64-timing.md and docs/spec/map-1-closure-draft.md
python tools/n64-timing/behaviors.py --check      # the gen check; the CMake target n64-timing-gen runs it before every build
python tools/n64-timing/behaviors.py --self-test  # breaks each rule once and checks that the failure names its fix
python tools/n64-timing/behaviors.py --fix-lines  # moves each legacy row's file:line to its current code site
python tools/n64-timing/behaviors.py --results RUN_DIR [--run-commit SHA]  # writes docs/spec/n64-timing-results.tsv from one standing run
python tools/n64-timing/behaviors.py --failing RUN_DIR  # lists each suite with a failing or not-run check; writes nothing
```

`--check` fails when:

- a row has no value, no reference, or no check;
- a check id is not defined in `checks.tsv`;
- `det` or `stepcap` is named without `~`, a gate is written as a guard, or every check of a row that is not `model-choice` is a guard;
- a time value is not a whole number of 750 MHz units and the basis is not `fit`;
- a `fit` row has an empty `fit-from`, or every check in its verify column is in its `fit-from`, reports only, or is pending, and its note does not start with `verify-is-fit: <reason>`;
- a row's note says `verify-is-fit` but another check decides it, or a row that is not `fit` has a `fit-from`;
- code names `Timing::Behavior::X` for a row with no numeric value, or for no row;
- a check that a row names has no line in `docs/spec/n64-timing-results.tsv`, a line's result is not `pass`, `fail` or `pending:<gate>`, its gate is not a `pending:` row of `checks.tsv`, or a line names a check no row uses;
- `behaviors.hpp`, `docs/spec/n64-timing.md` or `docs/spec/map-1-closure-draft.md` differs from the generated output;
- `lint-literals.py` finds a timing literal that the allowlist does not pin to a row.

To add or change a constant, edit its row and run `behaviors.py`. Code reads the value as `Timing::Behavior::<Name>`, in 750 MHz units.

`joybus-fit.py` solves the PIF joybus-phase rows (`si.read64-base`, `pif.joybus-*`) from the n64-systembench RD64B totals in the bench `expected.tsv`. It prints each value and, for every JOY point, the model total and whether the point is fit data, a check or a report.

A row with basis `legacy` is a cost that today's core still charges. Its reference is the code site. `literal-allowlist.tsv` pins the literal at that site to the row, and the row's value must appear on the line. The note names the plan unit that replaces the cost. That unit deletes the allowlist entries and the row, so the allowlist only shrinks. A row with basis `model-choice` has no published value, and its reference states the reason for the choice. A row with basis `fit` is solved from data that some checks also assert, so a pass on those checks verifies the arithmetic, not the model. Its `fit-from` column names those checks. When no other check decides the row (a check whose expectation is only a report does not), its note starts with `verify-is-fit: <reason>`, and the spec labels it **fit only, no independent check**.

A `checks.tsv` row whose id ends in `:*` is a suite row. Its expect column is `file:<path>` to the suite's expected-value file, or `self` when the suite's runner judges each check itself (`rdpstat`, `snapper`), and its selector names the file's key column. A `file:` path that does not exist is an error. Each id under the prefix that the file defines resolves with no row of its own. Each explicit row whose expect is `suite` must then find its target and selector in the file. A `pending:<gate>` check names a corpus that the program cannot run yet. The spec prints it as pending, never as verified.

### Results

`tools/n64-timing/standing.sh OUT MM_ROM` builds n64-run with `build.sh` (unless `N64_RUN` names a runner) and records the runner's sha256 in `OUT/n64-run.txt`. It builds every suite ROM into `$N64_TIMING_HOME/roms`, and the Majora's Mask BENCH ROMs into `$N64_TIMING_HOME/roms/mm-bench` with `calibration/build-mm-bench.sh` from `MM_ROM` (unless `MM_BENCH_ROMS` names them; the first build takes about 12 minutes). It then runs the whole standing set into `OUT` in that layout. `--results RUN_DIR` reads one standing run of every suite and writes one line per check that a row names: `pass`, `fail`, or `pending:<gate>`, with the measured detail. `RUN_DIR` holds `nemu64/`, `cpu/`, `bench/`, `thar0/`, `rdpstat/`, `snapper/` and `noise/` (each suite's `$N64_TIMING_HOME/results/<suite>` directory), `mmbench/` (an mmbench `--out` directory), `ctest.txt` (ctest in the build directory), `behaviors.txt` (`--check`, `--self-test` and `lint-literals.py` output), `det-*.txt` and `stepcap-*.txt` (`determinism.sh` and `determinism.sh --step-cap` over the nemu64 ROMs and MM), and `rom-sha256.txt` (`sha256sum` of every suite ROM, paths relative to the ROM directory). The gate comes from the check itself: a check that reports a number but asserts none is `pending:report-only`, and a check whose ROM the suite does not build is `pending:no-rom`. `pidma/` holds the pi_dma_test run: standing.sh runs the prebuilt ROM from `$PIDMA_DIR` (default `$N64_TIMING_HOME/scratch/r29/clones/n64_pi_dma_test`, sha256 pinned) for 3000 frames with `ARES_PILOG`, then `pidma-replay.py` pairs each timed DMA with the ROM's own COUNT reads, writes the verdict line to `pidma/summary.txt` and each point to `pidma/points.tsv`. It stops on a PI log record it does not know. A run that fails the pidma rule reads `FAIL`. A run that passes it must also agree with what the ROM said: the replay reproduces every value the ROM printed, and when the ROM reports 0 failures it printed nothing, so every replayed mean at sizes 1-383 lies inside the ROM's own float band `min*0.9..max*1.1` (`pi_dma_test.c:211`). A passing run whose replay contradicts that reads `UNCHECKED`, scored `pending:replay-unchecked`, and its line names the points. A `harness:` check guards a measuring tool, not a behavior, so it gets a result though no row names it. Any other check without output is an error. A Thar0 check passes when the model's count lies inside the console's minimum..maximum. A `cpu:` check passes when its ROM's own `CPU: Failed X of Y` line (in `cpu/<set>/summary.txt`) reports 0 failed, and fails when the line reports a failure or is missing. Beside the results, `--results` writes `docs/spec/n64-timing-fork.tsv`, the fork's side of every kit question as `kit.py` compares it (lo..hi over boot delays and layout pads, a value set for an exact rule), and `docs/spec/n64-timing-dry-run.tsv`, each `hw:*` check's result after `calibration/dry-run.sh` on `RUN_DIR/calib` (about 90 s). Both carry the results' header line; PREHW_COMPLETE reads the first for `separates` cells and the second for its dry-run clause, and `--check` fails when the fork file names another run. Then run `behaviors.py` to regenerate the spec and the closure draft from the results. standing.sh ends by printing, and writing to `OUT/failing.txt`, the scripts that failed (ROM builds, suite scripts, the calibration run, the MM runs, and ctest, `determinism.sh` and the pidma replay when they write no verdict line) and the `--failing` list, and exits 1 when any script failed. A failing check does not make it exit 1. `scripts-selftest.py` runs snapper `run.sh`, `calibration/run.sh` and standing.sh against a stub runner and checks that each failure reaches the exit status.

The first line of `n64-timing-results.tsv` names the commit the run was made on, not the commit of the tree that scores it. standing.sh writes that commit to `run-commit.txt` in `OUT`: the short SHA of the tree it ran from, followed by `dirty` when tracked files had uncommitted changes. `--results` reads the header from that file. A run made before standing.sh wrote `run-commit.txt` has no record, so `--results` stops with an error until you give the commit with `--run-commit SHA`. Do not add `run-commit.txt` to another unit's run directory. Give the commit on the command line instead:

```sh
python tools/n64-timing/behaviors.py --results ~/n64-timing/results/calib-kit-merge/standing --run-commit 214c46421
python tools/n64-timing/behaviors.py --results ~/n64-timing/results/u-pidma-fix/standing --run-commit f6fab4dc0
```

When a run has `run-commit.txt` and `--run-commit` names a different commit, `--results` stops with an error.

## Clock units

The core keeps time as `Timing::Clock` (`ares/n64/timing/clock.hpp`): absolute time since power-on in 750 MHz units. A PClock is 8 units, an RCP clock 12, an RDRAM tc 3, a COUNT tick 16. VI and AI time VCLKs with `Timing::VclkAccumulator` at the exact rational period. Write a cost as `pclk(n)`, `rclk(n)` or `Timing::us/ms/seconds(n)`; the literal lint reads their arguments.

```sh
python tools/n64-timing/codemods/clock-rebase.py --check   # lists tick-era code: 187.5 MHz ticks, n * 2, n * 3
python tools/n64-timing/codemods/clock-rebase.py           # converts it, updates the allowlist and table, regenerates
```

Run the codemod after merging a branch that predates the rebase. It rewrites only tick-era text, so a second run changes nothing. `--check` exits 1 while anything is left, and names each line it cannot convert.

## Thar0 RDP timing

```sh
python tools/n64-timing/romgen/build.py --suite thar0 --out $N64_TIMING_HOME/roms
tools/n64-timing/run-thar0.sh
```

`run-thar0.sh` writes `stdout.txt`, `stderr.txt`, `compare.tsv` and `summary.txt` under `$N64_TIMING_HOME/results/thar0/`. See [romgen/suites/thar0/README.md](romgen/suites/thar0/README.md).

## n64-systembench, the original ROM

```sh
tools/n64-timing/build-systembench-era.sh  # docker; 50f5066 + GCC 12.2 into $N64_TIMING_HOME/systembench-era/2023
tools/n64-timing/build-systembench.sh      # docker; 845635c + GCC 16.2 into $N64_TIMING_HOME/systembench
tools/n64-timing/systembench/run.sh        # SYSBENCH_ROMS and SYSBENCH_RESULTS override the directories
python tools/n64-timing/systembench/compare.py $N64_TIMING_HOME/results/systembench/results.tsv \
  $N64_TIMING_HOME/results/bench/results.tsv   # original vs romgen port vs hardware, per row
```

The `systembench:*` checks run the hardware-era build. `standing.sh` builds it into `$N64_TIMING_HOME/roms/systembench` and the 845635c build into `roms/systembench-845635c`, which it runs as a report only. Without docker the `systembench:*` checks are `pending:no-rom`. n64-systembench has no license file, so its source and ROMs stay outside the repo; libdragon is public domain (Unlicense).

`build-systembench-era.sh` builds the commit and toolchain the table's values were committed with. That a console produced those values, PI I/O R's 144 rclk included, is inferred: main.c states no source for its expected table (`docs/research/hardware-corpora.md` row 3, "presumably console"):

- `git blame` of main.c's table dates the PI DMA and PI I/O W values (a commit date, not a measurement date) to de9d9dd (2022-08-08), PI I/O R's 144 to the earlier 8313bcb (the same day), the RDRAM and RCP values to 3c6a0ee (2022-08-09) and the SI and JOY values to 50f5066 (2023-01-25). No value changed after that. From de9d9dd to 50f5066 the timed functions are the same source; later commits add code around them.
- `2023` (the default) is 50f5066, the only era commit with every row. `2022` is d12e8ea, the last 2022-08 commit. Each uses the vendored libdragon and a toolchain image built from libdragon's own Dockerfile at the last toolchain change before that date: a54ccd736 (GCC 12.2.0, binutils 2.39) and eed8ef3b7 (GCC 12.1.0, binutils 2.38). The ubuntu:18.04 base is pinned by digest. Two builds give the same z64.
- The era `timeit_average` drops only one sample when every sample is equal and still divides by n-2. The fork's samples are identical, so an unfixed era build reads (n-1)/(n-2) high wherever that happens: PI DMA 1 KiB 13692 instead of 12170, JOY Empty 4B-56B +2 %, and 64 KiB 9/8 high in other layouts (measured). The script changes `>` to `>=` in its max test. That is two instructions, and `nm` lists the same addresses (measured). `ERA_TIE_FIX=0` builds the original.

`build-systembench.sh` builds `845635c` with libdragon `preview` `cc490afe0` in the libdragon preview toolchain image, pinned by digest (GCC 16.2). Both scripts write `n64-systembench.z64` and `.elf`, 32 `boot-<K>` ROMs and `provenance.txt` with the sha256s.

A `boot-<K>` ROM counts down K iterations in libdragon's `_start` before `main`. It pads `_start` so that every later address moves by exactly 2 KiB at every K, so the boot-delay ROMs share one code and data layout. That layout is the unpadded ROM's moved by one RDRAM row.

The ROM prints its table through ISViewer, which `n64-run` writes to stdout. `run.sh` runs the unpadded ROM and every boot-delay ROM. `report.py` parses each `*** NAME [QTY]` block and applies main.c's own rule to every run: within the sampling error (1 CPU cycle, or 2 RCP cycles) or under 0.2 % (main.c:17-18, 664-669 at 845635c). The expected value is the one the ROM prints, compiled into main.c. `rows.tsv` names each benchmark, its romgen port and whether it is a check. `results.tsv` gives the unpadded value, the range over every run and the verdict: `pass` when every run passes, `consistent-only` when only some do, `fail` when none do.

What the comparison can and cannot show:

- The timed instructions of the poll benchmarks (PI DMA, PI I/O W, SI I/O W, SI DMA W) are the same in GCC 12.1, 12.2 and 16.2 builds, apart from register names. de9d9dd's PI DMA has one more `nop` after the length write (objdump, measured). Across seven builds the readings move by at most 4 rclk. So the compiler and layout do not explain the PI I/O W, SI I/O W, SI DMA W ROM, PI DMA 8 and PI DMA 128 offsets. A changed poll step does move them: one to three `nop`s per step move them by up to 10 rclk (verify-83). These checks therefore hold for this instruction sequence, which the hardware build also had if it used a GCC 12 (inferred).
- `rambuf`'s address depends on the whole link, which includes libdragon, and the hardware build's address is not known. U32R rand (+1024, +12, +568, +912) reads 134 when `rambuf` sits in one 2 KiB RDRAM row, as in the 50f5066 build (0x800278c0). It reads 150-151 when the reads cross a row, as in the 2022 builds (0x80026580) and 845635c (0x8002de00). PI DMA 1 KiB reads 12170 within one row and 12185 across two.
- C8R-C64R read 2 or 4 CPU cycles per binary, and hardware reads 3. COUNT ticks every 2 pclk, and the fork's samples are identical, so a run reads one COUNT phase (inferred). Changing two instructions in `timeit_average` flips C16R, C32R and C64R between 2 and 4 (measured), so the value is the run's COUNT parity, not a cache cost. The hardware 3 is a mean over mixed phases (inferred). 4b538eb (2024-05) rewrote TIMEIT_MULTI after the hardware values were taken. In the 50f5066 build U32R seq reads 134, as on hardware, and 845635c reads 133. The tie fix leaves that 134 unchanged, so the difference comes from layout or code, not from the averaging (measured).

## Self-test without the corpus

`make-emux-smoke-rom.py` builds a ROM that prints one line through emux `XLOG` and then requests an emux exit. It uses libdragon's public-domain `ipl3_compat.z64` as boot code.

```sh
python tools/n64-timing/make-emux-smoke-rom.py <libdragon>/boot/bin/ipl3_compat.z64 smoke.z64
n64-run smoke.z64     # stdout: "emux smoke: hello", stderr ends with stop=emux-exit
```

## Linux baseline

Measured 2026-10-07 on master `bf2882c3f` (harness port `feat/l0`) on the Linux host qwen: AMD Ryzen AI MAX+ 395 (16 cores, 32 threads, `powersave` governor, about 3.46 GHz under load), Ubuntu 26.04, g++ 15.2 (`RelWithDebInfo`, the host was shared with other jobs). The Windows column is the MSYS2 clang 22 baseline from `docs/program/handoff.md` and the T8 verifier.

| Check | Linux | Windows |
|---|---|---|
| nemu64 failed: timing / cycle / cop0hazard | 453/1604, 9/13, 5/5 | 453/1604, 9/13, 5/5 |
| snapper64 dumps matched | 2592/2592 | 2592/2592 |
| rdpstat failed: systemtest / dpc / repeater64 | 0/7, 0/2, 0/21 | 0/7, 0/2, 0/21 |
| thar0 configs 84 and 92 / 85 and 93 (BUF, min=avg=max) | 77,772 / 155,052 | 77,772 / 155,052 |
| bench pi-dma-sizes 8 B / 128 B / 1 KiB / 64 KiB (rclk) | 197.33 / 1600.0 / 12174.67 / 778498.67 | same |
| det, stepcap (MM, every mmbench scene) | PASS, 27 files, 8158 fields | PASS, 27 files, 8158 fields |
| det, stepcap (nemu64 ROMs) | PASS, PASS | stepcap PASS |
| state round trip, TMEM poke | PASS, PASS | PASS, PASS |
| ctest (5 unit checks) | 5/5 | 5/5 |
| `behaviors.py --check`, `--self-test`, `lint-literals.py` | ok, ok, ok | ok, 3 cases FAILED (inferred, see below), ok |
| MM 600 fields wall | 18.7 to 22.0 s | 11.3 to 11.8 s |

Every emulated value above matches Windows, and the mmbench per-scene `rsp_busy_clocks` means match the T8 verifier's to the cycle. A gcc build and a clang 22 build on this host write byte-identical MM stats. The MM wall time is not the compiler: gcc and clang ran within 10% of each other interleaved. It moved with host load (21.7 s at load average 15, 18.7 s at 6). The rest of the gap to Windows is the host (inferred; the Windows machine's CPU is not recorded). The `--self-test` legacy cases had failed on master since T7a removed the rows they edited; `feat/l0` points them at a row that still exists. The failure depends on file content, not the host, so Windows fails the same cases on master (inferred; measured on Linux at T7a and its parent).

## Run budget

Map #1 sets the budget: "a 600-frame MM bench run ... takes <= 2 min" (plan T16: every `mm:*` scene at most 120 s wall). Measured 2026-10-08 on master `6dfbf7166` on the Linux host unicron: AMD Ryzen AI MAX+ 395 (16 cores, 32 threads), `amd-pstate-epp` driver, `powersave` governor with `balance_performance`, about 3.5 GHz effective on the runner's core (cycles divided by wall time). The runner is the `build.sh` build (`RelWithDebInfo`, g++ `-O2 -g`), copied to a fresh file before timing. Each scene ran alone (one runner at a time, load average 1.0 to 2.4), three times:

```sh
perf stat -e task-clock,cycles,instructions n64-run MM.z64 --script <scene>/script.txt --stats stats.tsv --frames 3000 --wall-seconds 600
```

The scripts are the ones `mmbench.py` writes. Each scene's wall time covers the whole cold-boot run: boot, the route and the window. Every run wrote a `stats.tsv` byte-identical to the bench's.

| Scene | Fields run | Wall median (s) | Min to max (s) | Largest share of host time |
|---|---|---|---|---|
| power-on, `--frames 600` | 600 | 25.93 | 25.85 to 25.97 | CPU interpreter 37% |
| `title` | 852 | 39.27 | 39.22 to 39.34 | CPU interpreter 35% |
| `filesel` | 1043 | 55.95 | 55.94 to 56.09 | CPU interpreter 30% |
| `filesel-named` | 1510 | 81.33 | 81.18 to 82.25 | CPU interpreter 30% |
| `filesel-options` | 1220 | 67.07 | 66.85 to 67.55 | CPU interpreter 29% |
| `filesel-rotate` | 1764 | 102.90 | 102.73 to 103.63 | CPU interpreter 28% |
| `sct` | 906 | 63.10 | 62.92 to 63.57 | CPU interpreter 23%, RSP 22%, RI and timeline 22% |
| `field` | 924 | 60.67 | 60.66 to 60.74 | CPU interpreter 24%, RSP 22%, RI and timeline 21% |

`mmbench/wall-budget.tsv` keeps every timing, oldest first, with its commit, date, load average, user CPU and `instructions:u`. The map #1 closure draft reads each scene's last row, and SOFTWARE_READY clause 1 holds only when every scene's last row names the standing run's commit in its `commit` or `same_tree_as` column. `same_tree_as` is `-` or a standing-run commit whose tree outside `docs/` equals the timed commit's (`git diff --quiet <same_tree_as> <commit> -- . ':!docs'` exits 0). `behaviors.py --check` rejects a `commit` that is not 7 to 40 hex digits, and a `same_tree_as` that is neither `-` nor such a commit. The T16 rows' `wall_s` is the runner's own `wall_s`. The U-WALL rows' `wall_s` is `perf stat` time elapsed, which includes process start. The verify-142 review of PR #142 measured that basis about 0.45 s higher on the same runner (filesel-rotate 103.36 s against 102.90 s); this repository does not re-measure it. Every scene is within the budget. `filesel-rotate` is the closest, at 103 s for 1764 fields, because its window runs eight rotations (1157 fields) instead of 600. The runner is single-threaded and runs 3.8 to 4.8 instructions per cycle, so the wall time follows the instruction count on one core. The shares come from `perf record -F 999` runs that are not part of the timing. The other subsystems are the pixel engine's shading (11 to 23%), the RDP front end's scheduling (6 to 8%), and the per-field state hash behind `trace_hash` (7 to 11%).

### Re-timing (U-WALL)

`mmbench/wall.py` repeats the measurement above. Each side is a runner copied to a fresh file and the mmbench result directory its scripts and `stats.tsv` come from. The scenes run one at a time. The sides alternate, and their order flips every repeat. Each run records the 1-minute load average before and after it, and `perf stat` wall, user and sys seconds, `cycles:u` and `instructions:u`. A run whose `stats.tsv` differs from its side's reference is marked `DIFF`. `--sweep 1,5` times whole `mmbench.py` runs at each `--phases` value instead.

```sh
wall.py MM.z64 --out OUT --side t16=COPY_A=REF_A --side head=COPY_B=REF_B   # 5 repeats by default
wall.py MM.z64 --out OUT --side head=COPY_B=REF_B --sweep 1,5
```

On 2026-10-10, master `fbf33c91a` ran 5 repeats per scene, interleaved with T16's runner. T16's runner is the same file T16 timed (sha256 `82cdf3b0...`), and it used T16's scripts. Load average was 1.00 to 1.87 on 32 threads. All 80 runs wrote their reference `stats.tsv`. The master scripts add `bus start` and `bus end`, so `filesel-named` runs 1512 fields and `filesel-rotate` runs 1762.

| Scene | Wall median, T16 runner (s) | Wall median, `fbf33c91a` (s) | `fbf33c91a` range (s) | Wall | `instructions:u` |
|---|---|---|---|---|---|
| power-on | 26.37 | 26.87 | 26.78 to 26.97 | +1.9% | +0.66% |
| `title` | 39.70 | 40.44 | 40.34 to 40.68 | +1.9% | +0.63% |
| `filesel` | 56.28 | 57.14 | 57.05 to 57.51 | +1.5% | +0.57% |
| `filesel-named` | 81.56 | 83.07 | 82.99 to 84.13 | +1.9% | +0.86% |
| `filesel-options` | 67.56 | 68.45 | 68.34 to 70.38 | +1.3% | +0.47% |
| `filesel-rotate` | 103.36 | 104.82 | 104.57 to 104.93 | +1.4% | +0.50% |
| `sct` | 63.49 | 64.00 | 63.90 to 64.24 | +0.8% | +0.31% |
| `field` | 61.13 | 62.07 | 61.91 to 62.16 | +1.5% | +0.55% |

Every scene is still within the budget. The slowest is `filesel-rotate`, at 104.8 s, which leaves 15.2 s. The run is still bound by one core: user CPU is within 0.14 s of wall, sys is under 0.4 s, it runs 3.8 to 4.8 instructions per cycle, and the clock is 3.44 to 3.45 GHz. `instructions:u` is the same in every repeat of a scene to four significant figures. User CPU grew more than the instruction count, so the extra time is lower IPC as well as more work (inferred). On `field`, the largest symbols are `Timeline::advance` (16%), `CPU::instruction` (14%), RSP execution (about 15% over 4 symbols), the state-hash serializer (6%), and 2-cycle span drawing (5%). These shares come from one `perf record -F 999` run that is not part of the timing.

The file-select phase sweep (`mmbench.py --phases 5`, default `--jobs`) costs 3.0x the CPU of `--phases 1`: 1466 s user against 485 s, and 2.015e13 `instructions:u` against 7.135e12 (5 interleaved repeats each). Its wall time is 106.2 s (105.8 to 111.2) against 105.5 s (105.2 to 105.9). The sweep adds 12 runs, and on this host each one gets a free core, so the wall time stays bound by `filesel-rotate`, the longest single run. The host's own load was about 1. The bench drove load to 3 to 10.5. On a host with fewer free cores than the bench's 19 runs, the sweep adds wall time (inferred). verify-131 measured +31% at load 20 to 32.

## Calibration kit

`calibration/run.sh [OUT]` builds the console calibration kit (`romgen/build.py --suite calib`, and `--hw` builds of the rdpstat and nemu64 ROMs) at each layout pad (`build.py --layout-pad`) and runs every kit ROM on the fork. `calibration/kit.py --layout OUT` lists which questions are layout-sensitive. `calibration/kit.py --noise-rate [OUT]` is the noise-mapping reader: for each question over a G_AD_NOISE, G_CD_NOISE or G_AC_DITHER snap it bounds the false-match rate of the cited mappings and says whether a console capture could decide it. `calibration/ingest.py CAPTURE_DIR` stores a console capture under `docs/calibration/hardware/` and puts each `hw:<question>` result into the spec. `calibration/dry-run.sh OUT` feeds the fork's own logs to it as a fake capture in a scratch tree. The procedure is [docs/calibration/hardware-run.md](../../docs/calibration/hardware-run.md), and the questions are in [docs/calibration/inventory.md](../../docs/calibration/inventory.md), generated by `behaviors.py` from `calibration/questions.tsv`.
