# tools-bench report

status: done
PR: https://github.com/wScottSh/mm-decomp-60fps/pull/1 (base main, not merged)
branch: bench/fork, head 7ab7fdd1ba413d5c0338a69f05980d892b8f85af
worktree: /home/wscottsh/repos/mm-wt/bench-fork (from origin/main 56fa21dd0)
raw results: /home/wscottsh/n64-timing/results/tools-bench/{state,smoke,unpinned-a,unpinned-b,pinned,analyze-unpinned,compare.txt,*.log}

## Scott's tree state check (pref 29)
- before: state/before-status.txt (7 M, 5 ??), state/before-sha.txt (18 files sha256).
- after: state/after-status.txt, state/after-sha.txt. cmp: both identical. HEAD still 56fa21dd0, stash list empty.
- Only side effect on that repo: `git worktree add` registered the worktree in its .git (as instructed). Read-only use of its baserom (copied into the worktree, gitignored) and its prebuilt bench ROM (smoke test).

## Commits
1. 5b0436e9f import the uncommitted bench harness. Byte-identical to Scott's files (cmp). All hunks of the 7 modified files are BENCH-related; none excluded. Excluded: docs/research/ (research notes, not harness; README links 2 of them), tools/bench/__pycache__/.
2. b01d0408a bench.py drives n64-run directly. --runner / $N64_RUN, else builds via $ARES_FORK (default ~/repos/ares) tools/n64-timing/build.sh (honors $N64_BUILD_DIR). meta.json: runner, runner_sha256, ares_fork (git describe --tags --dirty, only when bench.py built it), per-result runner_stop. ok requires stop=emux-exit. --interpreter removed (fork has no recompiler). analyze.py summary line updated.
3. 40923f300 func_80173B48 pin removed; game.c == upstream.
4. 55d1cadc1 README: runner table, budget rationale, fork validity notes, fork baseline table.
5. 7ab7fdd1b --timeout default 300 -> 600 (a run took 214 s at load ~6).
Why n64-run over ares-headless.sh: deterministic headless runner (no Xvfb, no host clock, no screen/audio threads, emux+ISViewer always on, exits on XIOCTL with a parseable stop line).

## Commands
- runner: `N64_BUILD_DIR=/home/wscottsh/n64-timing/build/tools-bench tools/n64-timing/build.sh` in /home/wscottsh/repos/ares at 253e1c8ea (nightly-234-g253e1c8ea). rc 0.
- decomp (repo toolchain present: IDO recomp, binutils-mips-linux-gnu; nothing installed): `make venv && make setup -j16 && make assets -j16 && make disasm -j16 && make -j16 && make -j16 BENCH=1` -> retail `build/n64-us/mm-n64-us.z64: OK`; pinned BENCH sha256 c3114b46631a84049a3e0bda7e35eda94f0d7c292592daff108d342493f56b7f (== Scott's prebuilt). After pin removal `make -j16 BENCH=1` -> b58e49e939a70c332745f5619747ff1bc1f0ca44bf6f12917cad1ca013022e52. ROM copies only under results/, none in git.
- bench: `N64_BUILD_DIR=... python3 tools/bench/bench.py --rom <rom> --scene all --runs 1 --jobs 4 --label X --out results/tools-bench/X` for unpinned-a, unpinned-b, pinned (default-build path exercised; ares_fork recorded nightly-234-g253e1c8ea). Load avg 2.57 before, 6.20 after.

## Results (measured)
- Determinism: unpinned-a vs unpinned-b CSV and log byte-identical, all 4 scenes. All 12 runs stop=emux-exit, 600 frames.
- Pinned vs unpinned (1 run each): actors, divisor, opa/xlu/ovl_bytes identical every frame, all 4 scenes. Budget (3*retrace - rdp_ticks) unpinned 14.0..24.0 ms; snow clamps at >=14 ms (z_object_kankyo.c /1.4e7), no rain, Link static -> no workload change in these scenes. Timing shifts from code change: median game_ticks pinned/unpinned SCT 1048270/1052534, TF 1076958/1071215, MV 850887/846890, GBC 1464396/1450853; SCT lag frames 6 vs 7; ZeldaArena free -64 B. Single points, not trends (pref 27).
- Host time per 600-frame run: 150.1..214.2 s at 4-way parallel (not single-run, not cp'd binary; not a wall-time comparison).
- Fork baseline table in README (analyze.py on unpinned-a).

## DEVIATIONS
- Commit trailer uses "Co-Authored-By: Claude Opus 5.5" per harness attribution reminder, not build-common's bare "Claude".
- Kept tools/ares/ares-headless.sh (general stock-ares tool), unused by bench.

## FOLLOW-UPS
- Filed https://github.com/wScottSh/ares/issues/82: emux XPROFREAD 0x0201 (RSP halted) always 0 since T5 (512acc926 removed profile.haltedCycles accounting); analyze.py rsp busy % reads 100. README documents workaround (rsp_cycles = busy, 750 MHz units; inferred from agreement with rsp_gfx+aud ticks).
- rdram_dp on fork = DP_DRAW (pixel bursts, ri/bus.cpp) + DP_DMA; DP_DMA has no feeder in fork (grep). Command-DMA attribution unverified.
- Bench scenes never exercise the effect budget; add a rain scene / moving Link (n64-run --script input) to see RDP-time dependence.
- Map #1 closure row "MM bench integration" can move to done once PR #1 lands; the per-behavior provenance part was not in this unit.
- No background processes of mine left running (monitor stopped; remaining n64-run processes belong to calib-kit and systembench units).
