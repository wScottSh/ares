## Independent verification (verify-mm1): PASS-WITH-NOTES

Head 7ab7fdd1b, own worktree `/home/wscottsh/repos/mm-wt/verify-mm1`, runner built from ares master 253e1c8ea into `~/n64-timing/build/verify-mm1`. Host load 6.7-9.3.

1. **Import 5b0436e9f**: `git show 5b0436e9f:<f> | cmp - ~/repos/mm-decomp-60fps/<f>` is identical for all 15 files (7 modified, 8 new). Scott's tree has 7 M + 5 untracked entries; everything bench-related is imported. Only `docs/research/` and `tools/bench/__pycache__/*.pyc` are excluded, both correct.
2. **No binaries**: `git log -p 56fa21dd0..7ab7fdd1b` has 0 "Binary" lines; all 14 changed files are text (C, asm, make, py, sh, md, spec). No ROM.
3. **Runner**: bench.py runs `<runner> <rom> --wall-seconds N`, ok requires `stop=emux-exit` and all frames. meta.json (unpinned-a): runner path, runner_sha256 b8f1ab2dcb85..., `ares_fork` = nightly-234-g253e1c8ea (recorded only when bench.py builds the runner; null with --runner/$N64_RUN, as README says). All 12 runs: ok, 600 frames, `stop=emux-exit`.
4. **Pin removal**: game.c at HEAD is identical to base 56fa21dd0 (empty `git diff`). Built BENCH ROM: sha256 b58e49e9...2e52 (unpinned, matches worker). Pinned ROM (game.c from 5b0436e9f, my worktree only): c3114b46...6b7f (matches worker/Scott's). `bench.py --scene all --runs 1 --jobs 4` x2 on unpinned: all 4 CSV + 4 log `cmp` byte-identical. Host s/run 150.5..211.3.
   Pinned vs unpinned (measured, 1 run each): actors, divisor, opa/xlu/ovl_bytes identical every frame, all 4 scenes. Median game_ticks pinned/unpinned: SCT 1048270/1052534, TF 1076958/1071215, MV 850887/846890, GBC 1464396/1450853 (exact match to worker). SCT frames with vi>3: 6/7. ZeldaArena last-frame free: pinned-unpinned = 64 B in all scenes. `vi` differs in SCT (22 frames), as the worker's lag-frame note implies.
5. **Retail**: `make` -> `build/n64-us/mm-n64-us.z64: OK`.
6. **README / issue #82**: issue accurate. At 512acc926 `rsp.cpp` loses `profile.haltedCycles += pclk(64).units` (and the halted-step cycles); on master `profile.cycles` increments only at rsp.cpp:77 (executed pipeline), `emux.cpp:168` still returns haltedCycles for 0x0201. `rsp_halted` max = 0 in all 4 scenes (measured). README claim that rsp_cycles = busy: consistent with code.

Notes (non-blocking):
- README line 97 / worker claim "unpinned budget stays between 14.0 and 24.0 ms": my 3*782727 - rdp_ticks gives SCT 14.0..17.9, TF 22.4..26.5, MV 20.9..24.2, GBC 19.6..30.1 ms. Lower bound and snow-saturation argument hold; upper bound 24.0 not reproduced (my formula assumes divisor 3 constant, which holds: divisor identical). Suggest "14.0 to 30.1".
- README says runs "always run the CPU and RSP interpreters"; I did not find a recompiler in the fork's n64 cpu dir, not verified further.
- README line 11 links docs/research files absent from the branch; it says so.
- bench.py `timed_out` is derived from the stop line; fine. Commit trailers say "Claude Opus 5.5", worker-disclosed.
- Scott's checkout: `status --porcelain` and sha256 of all modified/untracked files unchanged before/after (only a registered worktree added).

Raw: `~/n64-timing/results/verify-mm1/{unpinned-a,unpinned-b,pinned}`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
