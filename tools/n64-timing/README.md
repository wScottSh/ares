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

`tools/n64-timing/state-roundtrip.sh ROM [FRAMES]` checks that: a run that saves and reloads its state at fields 150, 300 and 457 must write the same stats file as a plain run, and a TMEM byte poked at field 30 must change `trace_hash` and no other column of that row.

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
tools/n64-timing/run-nemu64.sh [timing cycle cop0hazard]
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

`results/nemu64/summary.txt` concatenates the set summaries.

## Behavior table, spec and checks

`ares/n64/timing/behaviors.tsv` is the one source for every timing constant. Each row has an id, a value, a unit, a basis, a reference, the checks that decide it, the checks a fit was solved from (`fit-from`), and a note. `checks.tsv` defines every check id: its runner, target, selector, expectation and source.

```sh
python tools/n64-timing/behaviors.py              # writes behaviors.hpp, docs/spec/n64-timing.md and docs/spec/map-1-closure-draft.md
python tools/n64-timing/behaviors.py --check      # the gen check; the CMake target n64-timing-gen runs it before every build
python tools/n64-timing/behaviors.py --self-test  # breaks each rule once and checks that the failure names its fix
python tools/n64-timing/behaviors.py --fix-lines  # moves each legacy row's file:line to its current code site
python tools/n64-timing/behaviors.py --results RUN_DIR  # writes docs/spec/n64-timing-results.tsv from one standing run
```

`--check` fails when:

- a row has no value, no reference, or no check;
- a check id is not defined in `checks.tsv`;
- a time value is not a whole number of 750 MHz units and the basis is not `fit`;
- a `fit` row has an empty `fit-from`, or every check in its verify column is in its `fit-from`, reports only, or is pending, and its note does not start with `verify-is-fit: <reason>`;
- a row's note says `verify-is-fit` but another check decides it, or a row that is not `fit` has a `fit-from`;
- code names `Timing::Behavior::X` for a row with no numeric value, or for no row;
- a check that a row names has no line in `docs/spec/n64-timing-results.tsv`, a line's result is not `pass`, `fail` or `pending:<gate>`, its gate is not a `pending:` row of `checks.tsv`, or a line names a check no row uses;
- `behaviors.hpp`, `docs/spec/n64-timing.md` or `docs/spec/map-1-closure-draft.md` differs from the generated output;
- `lint-literals.py` finds a timing literal that the allowlist does not pin to a row.

To add or change a constant, edit its row and run `behaviors.py`. Code reads the value as `Timing::Behavior::<Name>`, in 750 MHz units.

A row with basis `legacy` is a cost that today's core still charges. Its reference is the code site. `literal-allowlist.tsv` pins the literal at that site to the row, and the row's value must appear on the line. The note names the plan unit that replaces the cost. That unit deletes the allowlist entries and the row, so the allowlist only shrinks. A row with basis `model-choice` has no published value, and its reference states the reason for the choice. A row with basis `fit` is solved from data that some checks also assert, so a pass on those checks verifies the arithmetic, not the model. Its `fit-from` column names those checks. When no other check decides the row (a check whose expectation is only a report does not), its note starts with `verify-is-fit: <reason>`, and the spec labels it **fit only, no independent check**.

A `checks.tsv` row whose id ends in `:*` is a suite row. Its expect column is `file:<path>` to the suite's expected-value file, and its selector names the file's key column. When that file exists, each id under the prefix that the file defines resolves with no row of its own. Each explicit row whose expect is `suite` must then find its target and selector in the file. A `pending:<gate>` check names a corpus that the program cannot run yet. The spec prints it as pending, never as verified.

### Results

`tools/n64-timing/standing.sh OUT MM_ROM` builds every suite ROM into `$N64_TIMING_HOME/roms` and runs the whole standing set into `OUT` in that layout. `--results RUN_DIR` reads one standing run of every suite and writes one line per check that a row names: `pass`, `fail`, or `pending:<gate>`, with the measured detail. `RUN_DIR` holds `nemu64/`, `bench/`, `thar0/`, `rdpstat/`, `snapper/` and `noise/` (each suite's `$N64_TIMING_HOME/results/<suite>` directory), `mmbench/` (an mmbench `--out` directory), `ctest.txt` (ctest in the build directory), `behaviors.txt` (`--check`, `--self-test` and `lint-literals.py` output), `det-*.txt` and `stepcap-*.txt` (`determinism.sh` and `determinism.sh --step-cap` over the nemu64 ROMs and MM), and `rom-sha256.txt` (`sha256sum` of every suite ROM, paths relative to the ROM directory). The gate comes from the check itself: a check that can only report is `pending:calibration-16`, a pidma check is `pending:build-corpora`, and a check whose ROM the suite does not build is `pending:no-rom`. Any other check without output is an error. A Thar0 check passes when the model's count lies inside the console's minimum..maximum. Then run `behaviors.py` to regenerate the spec and the closure draft from the results.

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
