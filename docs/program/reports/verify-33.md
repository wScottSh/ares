# verify-33: PASS-WITH-NOTES

PR comment: https://github.com/wScottSh/ares/pull/33#issuecomment-5995383561
Artifacts: C:\Users\Scott\n64-timing\verify\r33 (run1, run2); worktree ares-wt\verify-33.

Built head a1f3544ab from my own worktree (`ares-wt/verify-33`, build dir `n64-timing/build/verify-33-head`, separate bench build `build/verify-33`). Checked against the worker report, not trusted.

### Command
`bash tools/n64-timing/mmbench/mmbench.sh "C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64" --out C:/Users/Scott/n64-timing/verify/r33 --check-determinism`

### Raw result
- `determinism: PASS, 17 files byte-identical (wall.tsv excluded)`
- Frame counts (gframes), both runs identical to the worker's report: filesel 449 (dist_1 449, window start 460), sct 198 (dist_3 198, start 329), field 199 (start 349), title 199 (start 269). rsp_busy mean per field: 458629.1 / 1270203.9 / 1289098.2 / 376865.2. gfx_tasks 451/200/200/200, game_frames -/200/200/200. All equal the report.
- Wall: run1 total 25.8 s, run2 25.3 s (4 scenes in parallel; report said 22-29 s).
- Same scene stats.tsv md5 reproduced when run on the T1 head (PR #32 plus this PR merged): sct df374e0c57457470c4279ecd67d98fcd, etc.

### Diff findings
Read tools/n64-run/n64-run.cpp, script.hpp, mmbench.py/.sh, READMEs (913 additions, 7 files).
1. `mmbench.py:188,375` and `mmbench/README.md:19` use `--cpu`; breaks once T1 (#32) lands (see #32 comment). The `--cpu recompiler` option should go with it.
2. Guest memory access reads/writes dcache lines and RDRAM directly, bypassing the bus (n64-run.cpp GuestMemory); sound for timing isolation. Scene routes poke the game (overlay table copy, dREG); documented in the README, intentional.
3. The `GameState.gfxCtx` read of 0 on title is unexplained (report gotcha); worked around via fixed address 0x801F9CB8.
4. Not reproduced: the #23 21-item table (recipe values) and the recompiler wall times; I did not rerun those. Cross-check counters (gfx_tasks, game_frames) did reproduce.
5. No core edits, no timing constants, no ROM committed.

Verdict: PASS-WITH-NOTES. The check (determinism PASS, four scene frame counts) reproduces exactly.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
