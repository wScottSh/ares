# N64 timing harness

Scripts that build this fork's headless N64 runner (`tools/n64-run`), run ROMs through it, and run the nemu64-test timing corpus.

All host-side state lives under `$N64_TIMING_HOME` (default `~/n64-timing`): build trees, ROMs, and results. Nothing in this directory writes into the repository, and no ROM is committed.

## Prerequisites (Windows)

- MSYS2 at `C:\msys64` with the clang64 toolchain:

  ```sh
  /c/msys64/usr/bin/pacman -S --needed mingw-w64-clang-x86_64-toolchain mingw-w64-clang-x86_64-cmake mingw-w64-clang-x86_64-ninja
  ```

- Git Bash to run the scripts, and Python 3 for the result parser.
- Docker Desktop, only for `build-nemu64.sh`.

## Build the runner

```sh
tools/n64-timing/build.sh
```

The script configures `-DARES_CORES=n64`, `RelWithDebInfo`, and Ninja on first use, then builds only the `n64-run` target. It prints the binary path, `$N64_TIMING_HOME/build/<worktree name>/n64-run/rundir/n64-run.exe`. A clean build takes about 50 seconds on the reference machine.

## Run a ROM

```sh
n64-run ROM [--frames N] [--emulated-seconds S] [--wall-seconds S]
            [--cpu interpreter|recompiler] [--rdp none|vulkan]
            [--stats FILE] [--controllers N] [--script FILE]
```

| Option | Meaning |
|---|---|
| `--frames N` | Stop after N VI fields. Boot time before the VI is enabled does not count. |
| `--emulated-seconds S` | Stop after S seconds of emulated VR4300 time (93.75 MHz PClock). |
| `--wall-seconds S` | Stop after S seconds of host time. This is a safety net and does not affect emulation. |
| `--cpu` | `interpreter` (default) or `recompiler`. The option switches the CPU and the RSP together. |
| `--rdp` | `none` (default) or `vulkan`. See [RDP](#rdp). |
| `--stats FILE` | Writes one TSV line per VI field. See [Per-field stats](#per-field-stats). |
| `--controllers N` | Number of gamepads connected at power-on (default 1). |
| `--script FILE` | Runs an input script. See [Input scripts](#input-scripts). |

The runner always emulates an NTSC console with the Expansion Pak, with homebrew mode (emux, ISViewer) and deterministic entropy on.

Output:

- stdout carries only guest output: ISViewer text and emux `XLOG`/`XHEXDUMP` text.
- stderr carries core debug notices, the emux exit message, and one final line: `n64-run: stop=<reason> frames=N emulated_s=X wall_s=Y rdp=<mode>`.
- With a script, stderr also carries one `n64-run: mark NAME frame=N` or `n64-run: peek NAME frame=N VALUE` line per `mark` or `peek` step.
- The exit code is 0 for `emux-exit`, `script-stop`, or `frame-limit`, 2 for `emulated-time-limit`, 3 for `wall-time-limit`, and 1 for a load or usage error.

The runner checks the stop conditions between VI fields. A ROM that requests an emux exit therefore runs to the end of the current field.

### Per-field stats

| Column | Source |
|---|---|
| `frame` | VI field index, counted from 0 at the first field with the VI enabled. |
| `origin`, `width`, `depth` | `VI_ORIGIN`, `VI_WIDTH`, and the `VI_CTRL` pixel type at the end of the field. |
| `fb_hash` | FNV-1a 64 of the displayed image. With `--rdp none`, the hash covers the RDRAM pixels that the VI samples, using the same walk as `VI::refresh`. With `--rdp vulkan`, it covers paraLLEl-RDP's VI scanout. |
| `cpu_cycles` | Cumulative VR4300 PClock cycles (`cpu.profile.cpuCycles`, the value emux `XPROFREAD 0x0000` returns). |
| `rsp_busy_clocks` | Cumulative non-halted RSP time, in the core's scheduler clocks (2 per PClock). |
| `dpc_start`, `dpc_end` | `DPC_START` and `DPC_END` at the end of the field. |
| `cimg`, `zimg` | The address of the last `SET_COLOR_IMAGE` and `SET_MASK_IMAGE` (Z buffer) command the core parsed. Only `--rdp none` parses commands, so both are 0 with `--rdp vulkan`. |

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
| `shot FILE` | With `--rdp vulkan`, writes the next field's scanout to FILE as a binary PPM. |
| `stop` | Ends the run with `stop=script-stop`. |

`W` is `b`, `h`, or `w` (1, 2, or 4 bytes). Numbers are decimal or `0x` hex. `ADDR` is a KSEG0 or KSEG1 RDRAM address, and `[EXPR]` loads the word at `EXPR`, so `[[0x801E3FB0]+0x1CCC]+0x24` follows two pointers. A read sees a dirty data-cache line the way a CPU load would, and a write to a cached line goes into the line. Neither touches bus or cache timing state. A step that cannot resolve its address waits (`until`), logs `unreadable` (`peek`), or logs `poke-failed`/`copy-failed`.

`tools/n64-timing/mmbench` uses scripts to run the Majora's Mask bench.

### RDP

The fork has no software RDP rasterizer. The desktop build draws through paraLLEl-RDP on Vulkan.

- `--rdp none` runs no rasterizer. The core still consumes RDP command lists, but no pixels are drawn, so RDRAM framebuffers hold only CPU and RSP writes. Games that read back rendered pixels see different data than on hardware. `cpu_cycles` and `rsp_busy_clocks` matched `--rdp vulkan` exactly over 600 Majora's Mask fields, so the core's timing does not depend on the renderer today.
- `--rdp vulkan` uses paraLLEl-RDP on the host GPU, the same renderer as the desktop build. Two consecutive runs produced identical stats files, but the result depends on the host GPU and driver. A Vulkan software device (lavapipe) is not wired up.

### Determinism

The runner removes the host dependencies that the desktop build has:

- No screen or audio thread does work. The runner sets ares' run-ahead flag, which makes the screen and audio stream nodes skip their host-side processing, so nothing reads RDRAM concurrently with the core.
- Deterministic entropy seeds the core's random generator with 0.
- Save files are never loaded or written. mia's save location points at an unused directory next to the binary.
- Wall time is used only for `--wall-seconds` and the stderr stop line.

One host dependency remains: a cartridge with an RTC seeds it from the host clock. mia enables the RTC only for ROMs whose manifest declares one.

## nemu64-test corpus

```sh
python tools/n64-timing/romgen/build.py --suite nemu64 --out $N64_TIMING_HOME/roms
tools/n64-timing/run-nemu64.sh [--cpu interpreter|recompiler] [timing cycle cop0hazard]
```

`romgen/build.py` generates the three ROMs from the in-repo Python port of nemu64-test, with no external toolchain. See [romgen/README.md](romgen/README.md).

`build-nemu64.sh` is the alternative that builds the original Rust ROMs. It builds nemu64-test at commit `9a8b9f7` in `rust:1-bookworm`, using the toolchain from the repository's `rust-toolchain.toml` (`nightly-2026-07-16`) and `nust64 0.4.1`. It runs `cargo run --release --no-default-features --features <set>`. Docker volumes named `n64timing-*` cache the Rust toolchain and the build trees.

`run-nemu64.sh` writes these files under `$N64_TIMING_HOME/results/nemu64-<cpu>/<set>/`:

- `stdout.txt` is the raw guest output.
- `stderr.txt` holds the stop line and debug notices.
- `frames.tsv` holds the per-field stats.
- `tests.tsv` lists each test with its number of failed values and pass or fail.
- `failures.txt` lists every failure message.
- `summary.txt` holds the ROM's own category totals, such as `Timing: Failed X of Y tests`.
- `values.tsv` (romgen ROMs only) has one row per test value: result, measured cycles, and expected cycles.
- `categories.tsv` (romgen timing ROM only) assigns each failed value to a root-cause category.

`results/nemu64-<cpu>/summary.txt` concatenates the set summaries.

## Thar0 RDP timing

```sh
python tools/n64-timing/romgen/build.py --suite thar0 --out $N64_TIMING_HOME/roms
tools/n64-timing/run-thar0.sh [--cpu interpreter|recompiler]
```

`run-thar0.sh` writes `stdout.txt`, `stderr.txt`, `compare.tsv` and `summary.txt` under `$N64_TIMING_HOME/results/thar0-<cpu>/`. See [romgen/suites/thar0/README.md](romgen/suites/thar0/README.md).

## Self-test without the corpus

`make-emux-smoke-rom.py` builds a ROM that prints one line through emux `XLOG` and then requests an emux exit. It uses libdragon's public-domain `ipl3_compat.z64` as boot code.

```sh
python tools/n64-timing/make-emux-smoke-rom.py <libdragon>/boot/bin/ipl3_compat.z64 smoke.z64
n64-run smoke.z64     # stdout: "emux smoke: hello", stderr ends with stop=emux-exit
```
