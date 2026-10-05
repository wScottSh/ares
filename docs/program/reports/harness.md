# Report: harness (pilot)

**Status: PARTIAL.** The runner, the scripts, the determinism checks, and the PR are done. The nemu64-test baseline (924/1604, 9/13, 5/5) was not reproduced. The auto-mode permission classifier blocked the ROM build step ("Code from External": `cargo install nust64` and `cargo run` of the external nemu64-test crate inside Docker). Per its terms I did not retry or work around it. A human has to run, or allow, `tools/n64-timing/build-nemu64.sh`.

- Branch: `feat/harness` (worktree `C:\Users\Scott\repos\ares-wt\harness`, based on origin/master 59158c28a)
- Head SHA: `c8592d16aaca28ea9a844f7a2b3e68ecd5662ff6`
- PR: https://github.com/wScottSh/ares/pull/30 (not merged)

## Commands

Build the runner (one command):
```
bash C:/Users/Scott/repos/ares-wt/harness/tools/n64-timing/build.sh
# -> C:/Users/Scott/n64-timing/build/harness/n64-run/rundir/n64-run.exe
```

Run a ROM headless (one command):
```
n64-run.exe ROM [--frames N] [--emulated-seconds S] [--wall-seconds S] [--cpu interpreter|recompiler] [--rdp none|vulkan] [--stats FILE] [--controllers N]
```
- stdout carries guest output only (ISViewer plus emux XLOG/XHEXDUMP).
- stderr carries core `[unusual]` notices, the `[emux] ... exit` message, and the last line `n64-run: stop=<reason> frames=N emulated_s=X wall_s=Y rdp=<mode>`.
- Exit codes: 0 emux-exit or frame-limit, 2 emulated-time-limit, 3 wall-time-limit, 1 error.
- `--stats` TSV columns: `frame origin width depth fb_hash cpu_cycles rsp_busy_clocks`.

Corpus (one command, blocked here):
```
bash tools/n64-timing/build-nemu64.sh && bash tools/n64-timing/run-nemu64.sh [--cpu interpreter|recompiler]
```
Results go to `C:\Users\Scott\n64-timing\results\nemu64-<cpu>\<set>\{tests.tsv,failures.txt,summary.txt,stdout.txt,stderr.txt,frames.tsv}` and `...\summary.txt`.

## Raw results (all measured this session)

nemu64-test: **not run** because the ROMs were never built. No counts exist. The parser and corpus runner were exercised only on stand-ins: the emux smoke ROM through `run-nemu64.sh`, and a synthetic stdout in the nemu64 format through `nemu64-results.py`. Parser output on the synthetic input: `Timing: Failed 2 of 5 tests (60% success rate)` / `tests run: 3, tests with failures: 2, failure lines: 2`. I read the nemu64-test source at 9a8b9f7 (`src/tests/mod.rs`, `src/emux.rs`). It prints through emux XLOG when XDETECT reports support, which homebrew mode does, prints `Running <name>...` per test and `Test '<name>'... failed...` per failure, ends with `Timing: Failed X of Y tests`, and calls XIOCTL exit. The runner handles all of these paths (XLOG and exit verified with the smoke ROM).

Determinism (two consecutive runs, `cmp`):
- MM (`Legend of Zelda - Majora's Mask.v64`), 600 fields, interpreter, `--rdp none`: stats byte-identical. Raw stop line: `n64-run: stop=frame-limit frames=600 emulated_s=10.525738 wall_s=8.447` / `wall_s=8.481`.
- MM, 600 fields, interpreter, `--rdp vulkan`: stats byte-identical, 601 distinct fb hashes. `wall_s=10.276` / `9.434`.
- MM `--rdp none` vs `--rdp vulkan`: identical frame/VI/cpu_cycles/rsp_busy_clocks columns. The RDP renderer does not feed back into core timing today.
- `rasky_n64_pi_dma_test/pi_dma_test.z64`, 300 fields: stdout (ISViewer, 1024 B) and stats byte-identical in interpreter (`wall_s=1.749`/`1.755`). Recompiler also identical (`wall_s=0.950`/`0.953`).
- Emux smoke ROM: `emux smoke: hello` on stdout, `stop=emux-exit` exit 0, interpreter and recompiler, wall 0.016 s.

Wall-clock:
- Clean build with `build.sh`: 46.5 s.
- MM 600 fields: interpreter 8.4 s, recompiler 1.44 s (`emulated_s=10.529286`), interpreter plus paraLLEl 9.4-10.3 s. That is well under the 2-minute bench budget.

## Decisions (my calls, within scope)

1. **Build route: native MSYS2 clang64, not Docker.** Native passed all three criteria: the build succeeded, MM ran at about 1.25x realtime in the interpreter, and runs were deterministic. It also keeps host-GPU Vulkan available for `--rdp vulkan`, which a Docker Linux container would lose without lavapipe. I did not build in Docker for comparison. The criteria were met and Docker on Windows adds bind-mount I/O cost.
2. **Runner location: new target `tools/n64-run`**, wired from the root `CMakeLists.txt` when `n64` is in `ARES_CORES`. desktop-ui links hiro and ruby (GUI and host drivers), so a separate console target is the only way to have no GUI. It reads core state directly (VI regs, RDRAM, profile counters) by compiling against `<n64/n64.hpp>` with the core's private include dirs. That avoided adding a core API.
3. **Headless mechanism: `ares::setRunAhead(true)`.** This makes `Screen::frame` and the audio stream skip all host work. No screen thread runs `VI::refresh` concurrently with the core, which on desktop reads RDRAM racily. No core edit was needed for this.
4. **Exit-status semantics.** The emux XIOCTL exit carries no code, so "exit status from emux" is the stop reason `emux-exit` (exit 0). A frame-limit stop also exits 0, and the stop line tells the two apart.
5. **Frame = VI field with the VI enabled.** Pseudo-frames while the VI is off (boot) are not counted. `--emulated-seconds` covers ROMs that never enable the VI.
6. **Default `--rdp none`.** See the RDP gotcha below. `--rdp vulkan` is opt-in.
7. Settings are fixed: NTSC, Expansion Pak on, homebrew mode on, deterministic entropy on, 1 gamepad, saves never loaded or written.

## Core edits (ares/)

- `ares/n64/vulkan/vulkan.cpp`: when paraLLEl-RDP is not loaded, `Vulkan::load` points `rdram.hidden.data` at a host buffer (`rdram.ram.size/2` bytes, filled with 0x03 to match paraLLEl's clear value). Before this, any RDRAM write with GPU acceleration off segfaulted in `HiddenRAM::update` on a null pointer. This is a pre-existing bug from commit 45c229126 that would hit the desktop build with Vulkan off too. Not a timing change.

## Deviations from the brief

- nemu64 baseline not reproduced, for the permission block described above.
- `build-nemu64.sh` is written but never ran to completion. Its first attempt failed at `docker pull` on Docker Desktop's credential helper ("A specified logon session does not exist"). The script now points `DOCKER_CONFIG` at a stub helper, which I verified fixes `docker pull rust:1-bookworm`. The cargo steps themselves were never exercised.
- The research baseline used the desktop binary, likely with paraLLEl on and deterministic entropy unknown. My runner differs: `--rdp none` by default and deterministic entropy on. Random-register tests (C11) read `random()`, so their exact values could differ from the research run. Rerun with `--rdp vulkan` if the counts diverge.

## Gotchas for next units

- **Run the corpus first.** `bash tools/n64-timing/build-nemu64.sh` (needs Docker Desktop running and permission to build external code), then `run-nemu64.sh` and `run-nemu64.sh --cpu recompiler`. Compare with 924/1604, 9/13, 5/5 (interpreter) and 1109/10/5 (recompiler).
- **No software RDP exists in this fork.** With `--rdp none`, framebuffers stay black (MM fb_hash takes 4 distinct values over 600 fields), so games that read rendered pixels diverge from hardware. `--rdp vulkan` renders, but through the host GPU, which the map rules out as a timing dependency. The RDP-engine unit should replace this.
- **Paths with an apostrophe** (the MM ROM) are not converted by Git Bash's MSYS path conversion. Pass `C:/Users/...` form, not `/c/Users/...`.
- `core.autocrlf` would turn `.sh` into CRLF. `tools/n64-timing/.gitattributes` pins LF.
- The build uses `-march=native` (ares default), so binaries are tied to this CPU.
- Generated `ares/ares/resource/resource.{cpp,hpp}` and `mia/resource/*` land in the source tree during build. They are gitignored.
- `cpu_cycles` is `cpu.profile.cpuCycles` (PClock cycles). `rsp_busy_clocks` is in scheduler clocks (2 per PClock), not RSP cycles.
- The emulated-seconds limit uses `cpuCycles / 93.75e6`.

## Suggested follow-ups

- Run the corpus and fill in the baseline numbers (blocked item).
- Add a `--dump-frame N FILE` option so a later unit can eyeball paraLLEl output. I did not visually confirm MM rendering. The 601 distinct hashes are the only evidence.
- Controller input scripting for the MM bench (the runner connects pads with no input).
- Optional: a Docker/Linux build of `n64-run` for CI.
