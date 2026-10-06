# Unit: harness (pilot)

GOAL
Anyone on this Windows machine can build the ares fork and run an N64 ROM headless from one script, deterministically. The nemu64-test corpus runs through that script and reproduces the known baseline for this fork's interpreter.

SCOPE
- May write: a new worktree /home/wscottsh/repos/ares-wt/harness on branch feat/harness (from origin/master). Inside it: a headless runner target (suggested: tools/n64-run/ or a new CMake target under desktop-ui/ or mia/, your call; justify), build/run scripts under tools/n64-timing/, a README there, CMake wiring for the new target. Minimal, surgical edits to ares/ core only if strictly required for headless operation (e.g. a platform hook) — list each one in the report.
- May write outside the repo: /home/wscottsh/n64-timing/ (corpus ROMs, build caches, results). Do not commit ROMs.
- May not write: the main checkout /home/wscottsh/repos/ares, any other worktree, any timing behavior in ares/n64 (that is other units' work).

CONTEXT
- Map: https://github.com/wScottSh/ares/issues/1. Prior research describing the baseline and how it was run: `git show origin/research/nemu64-timing-failures:docs/research/nemu64-timing-failures.md` (see "Raw-result summary": built RelWithDebInfo with -DARES_CORES=n64, run with ForceInterpreter=true and HomebrewMode=true settings; ROM exits itself via emux; ISViewer output to stdout). The tool that ran it then (mm-decomp-60fps tools/ares/ares-headless.sh) is NOT available here; rebuild the capability inside this fork.
- Toolchain on this machine: no compiler on PATH. Available: Docker Desktop 29.5 (installed, currently stopped; start it with "C:\Program Files\Docker\Docker\Docker Desktop.exe" and wait for `docker info`), MSYS2 at C:\msys64 with pacman (clang64 environment empty; you may pacman-install packages), Python 3.14, node 24, git, gh. Pick the build route (Docker Linux image vs MSYS2 clang64 native) on evidence: build success, run speed, determinism. Later units will run the 600-frame MM bench (budget <= 2 min) and hundreds of test ROMs through this, so speed matters.
- ares emux/ISViewer: ares/n64/cpu/emux.cpp; settings in desktop-ui. The headless runner must have no GUI, no host video/audio driver, no host clock dependence, and must expose: ROM path, frame (VI field) limit, wall/emulated time limit, interpreter-vs-recompiler selection, stdout of ISViewer, exit status from emux, and a per-frame line of machine-readable stats (at minimum frame index and a hash of the displayed framebuffer region; add CPU/RSP/RDP clock counters if cheaply available). Document what the RDP does headless (paraLLEl needs Vulkan; say whether you use a Vulkan software device, ares's software path, or none, and what that costs).
- nemu64-test: https://github.com/thelemmy/nemu64-test at commit 9a8b9f7. Build per the research doc (cargo run --release --no-default-features --features {timing|cycle|cop0hazard}, nightly-2026-07-16, nust64 0.4.1, rust:1-bookworm Docker). Script the build.

ACCEPTANCE
- One command builds the fork (document it). One command runs a ROM headless with the options above.
- One command builds the three nemu64-test ROMs and runs them, writing a per-test result file plus summary counts.
- On origin/master (59158c28a) interpreter: timing 924/1604 failing, cycle 9/13, cop0hazard 5/5 — or a fully explained divergence (exact numbers both ways, cause traced).
- Two consecutive runs of the same ROM produce byte-identical outputs (stdout + per-frame stats). Report if not, with which field differs.
- Wall-clock time for each run reported.
- PR opened from feat/harness to wScottSh/ares master with a short description (technical-writing style: what, how to run, verification). Do not merge.

VERIFY
Run the acceptance commands yourself and paste the raw summary lines in the report.

TIMEBOX
About 4 hours of work. On expiry, push what you have, report partial status and the blocker.

FORBIDDEN
No gt, no rebase, no force-push, no merging, no edits outside SCOPE, no timing behavior changes, no committing ROMs or Nintendo binaries.

REPORT
Write the report to /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/harness.md and also return it: status, branch, head SHA, PR URL, the exact build and run commands, raw result counts, determinism result, wall-clock times, deviations from this brief, what the next units need to know (gotchas), suggested follow-ups.

STANDING
Read and obey /home/wscottsh/.claude/orchestrate/ares-n64-timing/preferences.md (standing orders) before starting.
