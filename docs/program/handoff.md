# Handoff: timing-model program, paused 2026-10-05

Scott paused the program after this batch because of token budget ("when this batch of work is done, we need to pause. to much token budget used."). Nothing is running and no PR is open. Everything below is on master in wScottSh/ares.

## Landed (plan units)

- Harness: n64-run headless runner, mmbench (7 MM scenes incl. the #11 file-select acceptance scenes and `filesel_check.py`), romgen in-repo ROM generator with suites nemu64, bench, thar0, rdpstat, snapper.
- Design: ADR 0001 (`docs/adr/0001-timing-core.md`), build plan (`docs/design/timing-core/plan.md`), sketches.
- T1 recompilers removed. T2 determinism floor + trace_hash. T3 behaviors table, generator, spec, literal lint. T4 absolute 750 MHz clock, exact VCLK. T5 timeline scheduler. T6 RI arbiter + SysAD port. T7a CPU pipeline scoreboard. T8 DMA engines as RI bus clients. T9/T10 cen64-jgemu software RDP is the only RDP (paraLLEl/Vulkan removed). T12 timed DPC front end.
- Tooling: fit provenance in behaviors.py (a fit row needs an independent check or a `verify-is-fit:` note); research docs consolidated in `docs/research/`.

## Where the numbers stand (master, measured by independent verifiers)

- nemu64 failures: timing 453 / 1604 (from 924 at the start), cycle 9 / 13, cop0hazard 5 / 5.
- snapper64 console dumps: 2592 / 2592 match. rdpstat: systemtest 0/7, dpc 0/2, repeater64 0/21 failed.
- Thar0 RDP: configs 84/92 = 77,772 and 85/93 = 155,052 exactly (these are fit-only, flagged); the other 96 configs need memory time (T13).
- pidma replay: about 23.8k / 24k points within ±3%.
- MM 600 fields: about 11–12 s wall on the shared host (budget 120 s). Determinism, stepcap and save-state round trip pass.
- #11 acceptance: empty-files file select 1.00 field/frame (pass); two-named-files row FAILS (model 1.00, hardware 2.00). The RDP memory interface (T13) is what should move it.

## Next units, in order (plan.md has goal, files, check for each)

0. L0 Linux harness port (new; not in plan.md). The program moved to the Linux host `qwen` (unicron: Ubuntu, 32 cores, 107 GB RAM, g++/cmake/ninja/python3/gh; no clang, no bun). `tools/n64-timing/build.sh` is MSYS2-clang64-only and the scripts assume a `.exe` runner and Windows drive-letter path conversion (`cygpath`). Make the harness build and run natively on Linux (g++ or clang via apt), keep Windows working, then rerun the full standing-check set on master and record the Linux baseline: nemu64 453/9/5, snapper 2592/2592, rdpstat 0/7 0/2 0/21, thar0 84/92/85/93 exact, det, stepcap, state-roundtrip, MM 600-field wall time. Determinism across hosts is not required, but within-host runs must be byte-identical; report any value that differs from the Windows baseline with cause. Regenerate local data: `romgen/build.py`, `suites/snapper/fetch.sh` into `~/n64-timing/corpora`, and re-clone the research corpora the briefs name (`~/n64-timing/scratch/r29/clones/...`, cen64 jgemu at `~/n64-timing/scratch/jgcen64`) from the URLs and commits in `docs/research/hardware-corpora.md` and `docs/research/jgemu-dpc-probe.md`.
1. T7b exceptions and bubbles (C1, 439 nemu64 values; `Pipeline::fault()` is the hook, see reports/t7a.md "For T7b").
2. T7c CP0 timing, then T7d fetch window and I-fills (cycle 13/13).
3. T11 VI fetch on the bus (memset band residuals, VI-on same-bank 36), drops VI from the Rdram::ram friend list.
4. T13 RDP memory interface (Thar0 100 configs, snapper span, MM #11 named-files row), drops RDP from the friend list.
5. T14 noise LFSR, T15 unsynced attributes, T16 budget, T17 bench integration and final spec assembly, then close map #1.
- A cleanup unit for `followups.md` (mostly behaviors.tsv labels: rows the verifiers found unlabeled or inferred) is cheap and can run any time.

## How to resume

On qwen this is already done: the repo is `~/repos/ares` (pulled to master), the store is installed at `~/.claude/orchestrate/ares-n64-timing/` with the STOP line removed, and the model sheet is `~/.claude/pstack-models.md`. The MM ROM is `~/repos/mm-decomp-60fps/baseroms/n64-us/baserom.z64` (md5 2a0a8acb61538235bc1094d297fb6556, the NTSC-U 1.0 the decomp matches). `tools/n64-timing/program-paths.py --home <home>` rewrites the operative program files for another host.

1. Install the pstack plugin in Claude Code on the host (the briefs name its skills and the orchestrate CLI; the CLI needs bun: `npm install -g bun`).
2. Start the coordinator in `~/repos/ares` with `/pstack:poteto-mode continue the ares timing program from ~/.claude/orchestrate/ares-n64-timing/handoff.md`. It runs L0 first.
3. Each build unit: spawn a fresh worker with `briefs/build-common.md` naming the unit and base `master`; then an independent verifier on a different model with `briefs/verify-pr.md`; merge on PASS. Model policy (Scott): opus workers, sonnet verifiers, medium effort.
4. Human-only items, unchanged: #16 hardware calibration run, #25 contact the jgemu author (draft in the #25 comment).

Paths in `reports/` refer to the original Windows machine's user directory and are kept as a historical record; briefs, standing orders and this handoff use qwen paths.
