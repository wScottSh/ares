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
            [--cpu interpreter|recompiler] [--rdp none|vulkan|soft]
            [--stats FILE] [--controllers N] [--dump-frame N FILE]...
```

| Option | Meaning |
|---|---|
| `--frames N` | Stop after N VI fields. Boot time before the VI is enabled does not count. |
| `--emulated-seconds S` | Stop after S seconds of emulated VR4300 time (93.75 MHz PClock). |
| `--wall-seconds S` | Stop after S seconds of host time. This is a safety net and does not affect emulation. |
| `--cpu` | `interpreter` (default) or `recompiler`. The option switches the CPU and the RSP together. |
| `--rdp` | `none` (default), `vulkan`, or `soft`. See [RDP](#rdp). |
| `--stats FILE` | Writes one TSV line per VI field. See [Per-field stats](#per-field-stats). |
| `--dump-frame N FILE` | Writes the RDRAM image the VI samples at field N as a 640x480 binary PPM. Repeatable. See [Frame dumps](#frame-dumps). |
| `--controllers N` | Number of gamepads connected at power-on (default 1). |

The runner always emulates an NTSC console with the Expansion Pak, with homebrew mode (emux, ISViewer) and deterministic entropy on.

Output:

- stdout carries only guest output: ISViewer text and emux `XLOG`/`XHEXDUMP` text.
- stderr carries core debug notices, the emux exit message, and one final line: `n64-run: stop=<reason> frames=N emulated_s=X wall_s=Y rdp=<mode>`. With `--rdp soft` a second line follows: `n64-run: rdp_soft render_calls=N render_ms=X pixels=N ns_per_pixel=X`, the host time spent inside the engine and the pixels it rasterized.
- The exit code is 0 for `emux-exit` or `frame-limit`, 2 for `emulated-time-limit`, 3 for `wall-time-limit`, and 1 for a load or usage error.

The runner checks the stop conditions between VI fields. A ROM that requests an emux exit therefore runs to the end of the current field.

### Per-field stats

| Column | Source |
|---|---|
| `frame` | VI field index, counted from 0 at the first field with the VI enabled. |
| `origin`, `width`, `depth` | `VI_ORIGIN`, `VI_WIDTH`, and the `VI_CTRL` pixel type at the end of the field. |
| `fb_hash` | FNV-1a 64 of the displayed image. With `--rdp none` or `--rdp soft`, the hash covers the RDRAM pixels that the VI samples, using the same walk as `VI::refresh`. With `--rdp vulkan`, it covers paraLLEl-RDP's VI scanout. |
| `cpu_cycles` | Cumulative VR4300 PClock cycles (`cpu.profile.cpuCycles`, the value emux `XPROFREAD 0x0000` returns). |
| `rsp_busy_clocks` | Cumulative non-halted RSP time, in the core's scheduler clocks (2 per PClock). |

### RDP

- `--rdp soft` runs the cen64-jgemu pixel engine (`ares/n64/rdp/engine/`) on the emulation thread. Each `DPC_END` write renders its command range into RDRAM before returning, with no worker threads, so the result does not depend on the host. `fb_hash` covers the RDRAM pixels.
- `--rdp none` runs no rasterizer. The core still consumes RDP command lists, but no pixels are drawn, so RDRAM framebuffers hold only CPU and RSP writes. Games that read back rendered pixels see different data than on hardware. `cpu_cycles` and `rsp_busy_clocks` matched `--rdp vulkan` exactly over 600 Majora's Mask fields, so the core's timing does not depend on the renderer today.
- `--rdp vulkan` uses paraLLEl-RDP on the host GPU, the same renderer as the desktop build. Two consecutive runs produced identical stats files, but the result depends on the host GPU and driver. A Vulkan software device (lavapipe) is not wired up.

### Frame dumps

`--dump-frame N FILE` writes the image the VI would scan out at field N (the `frame` column of the stats file) as a binary PPM (`P6`, 640x480). The pixels come from RDRAM through the same walk as `fb_hash`, in every RDP mode, so a `--rdp vulkan` dump and a `--rdp soft` dump of the same field compare the two rasterizers' RDRAM output, not their VI filters. 5-bit channels are expanded by a shift. Positions the VI does not sample are black. `tools/n64-timing/framediff.py A.ppm B.ppm [--out diff.png]` reports the differing pixels per tile.

With `--rdp vulkan` the RDRAM bytes are paraLLEl-RDP's, which writes them asynchronously and is waited on only at Sync_Full; a dump taken while a frame is still rendering can be partial. Dump twice and compare to confirm a stable reference.

### Determinism

The runner removes the host dependencies that the desktop build has:

- No screen or audio thread does work. The runner sets ares' run-ahead flag, which makes the screen and audio stream nodes skip their host-side processing, so nothing reads RDRAM concurrently with the core.
- Deterministic entropy seeds the core's random generator with 0.
- Save files are never loaded or written. mia's save location points at an unused directory next to the binary.
- Wall time is used only for `--wall-seconds` and the stderr stop line.

One host dependency remains: a cartridge with an RTC seeds it from the host clock. mia enables the RTC only for ROMs whose manifest declares one.

## nemu64-test corpus

```sh
tools/n64-timing/build-nemu64.sh                 # ROMs -> $N64_TIMING_HOME/roms/nemu64-{timing,cycle,cop0hazard}.z64
tools/n64-timing/run-nemu64.sh [--cpu interpreter|recompiler] [timing cycle cop0hazard]
```

`build-nemu64.sh` builds nemu64-test at commit `9a8b9f7` in `rust:1-bookworm`, using the toolchain from the repository's `rust-toolchain.toml` (`nightly-2026-07-16`) and `nust64 0.4.1`. It runs `cargo run --release --no-default-features --features <set>`. Docker volumes named `n64timing-*` cache the Rust toolchain and the build trees.

`run-nemu64.sh` writes these files under `$N64_TIMING_HOME/results/nemu64-<cpu>/<set>/`:

- `stdout.txt` is the raw guest output.
- `stderr.txt` holds the stop line and debug notices.
- `frames.tsv` holds the per-field stats.
- `tests.tsv` lists each test with its number of failed values and pass or fail.
- `failures.txt` lists every failure message.
- `summary.txt` holds the ROM's own category totals, such as `Timing: Failed X of Y tests`.

`results/nemu64-<cpu>/summary.txt` concatenates the set summaries.

## Self-test without the corpus

`make-emux-smoke-rom.py` builds a ROM that prints one line through emux `XLOG` and then requests an emux exit. It uses libdragon's public-domain `ipl3_compat.z64` as boot code.

```sh
python tools/n64-timing/make-emux-smoke-rom.py <libdragon>/boot/bin/ipl3_compat.z64 smoke.z64
n64-run smoke.z64     # stdout: "emux smoke: hello", stderr ends with stop=emux-exit
```
