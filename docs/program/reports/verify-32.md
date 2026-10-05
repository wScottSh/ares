# verify-32: PASS-WITH-NOTES

PR comment: https://github.com/wScottSh/ares/pull/32#issuecomment-5995383105
Artifacts: C:\Users\Scott\n64-timing\verify\{r32base,r32head,r32mm,nemu-home-base,nemu-home-head}; builds build\verify-32-{base,head,mm}. Worktrees ares-wt\verify-32, verify-32-base, verify-32-mm (scratch merge, uncommitted patch).

Verifier ran on a different model than the worker. Built head 7a92d98c0 and base 9136cea32 (feat/design) from my own worktrees (`ares-wt/verify-32`, `verify-32-base`), RelWithDebInfo, n64-run only. Report claims checked, not trusted.

### Checks run (raw)
- `capture.sh` (worker's, copied): MM 600 fields rdp none and vulkan, pi_dma_test 300 fields, 3 runs each, base vs head.
  - mm-none stats md5 base x3 = head x3 = 1c9e549d1ac778aa12e824b491ee567f
  - mm-vulkan stats md5 base x3 = head x3 = a93518a54fcd0efb82ac7ec6c1955441
  - pidma stats md5 base x3 = head x3 = 0e384658298bb13cce69eb1e909769d6; stdout 710ade4a07fd52a686b6046b8adbc3aa both
  - stdout empty for MM both; stderr identical. `det` PASS (3 runs identical per config, both builds).
- mmbench scenes (not on base): scratch merge of origin/feat/mmbench into head (README conflict only; mmbench.py patched locally to drop `--cpu`, see note 1). Four scenes, stats.tsv md5 equal to PR #33's own run on a build with the recompilers present (interpreter): filesel 60aa9ea1..., sct df374e0c..., field 7d936238..., title 310022c8...; fields.tsv and gframes.tsv identical. This is the plan's `mm:*` byte-identical check on the real scenes, which the worker did not run.
- nemu64 (worker did NOT RUN; I did): romgen ROMs built from origin/feat/romgen (`build.py --suite nemu64`), run with each build via its own `run-nemu64.sh`. Base: Timing 924 of 1604, Cycle 9 of 13, CP0-hazards 5 of 5 failed. Head: identical counts. tests.tsv and failures.txt byte-identical for all 3 sets (only wall_s in stderr/summary differ). Equals T0 (924/9/5).
- Wall time MM 600 fields rdp none, s: base 13.51 16.54 16.91; head 12.40 9.95 9.76 (machine shared and noisy; not a speedup claim). pidma: base 2.89 2.85 2.56; head 1.94 1.97 2.00.

### Diff findings
Full diff read (33 files, -9631/+159). Deletions are the recompiler files and their only consumers; per-instruction synchronize preserved (cpu.cpp:35-37). forceSynchronize/interruptPoll were no-ops outside the JIT clock target, so removal is behavior-neutral (matches the byte-identical results). decoder.cpp op() count unchanged (311 both).
1. Cross-PR break: PR #33 `tools/n64-timing/mmbench/mmbench.py:188,375` and `mmbench/README.md:19` pass/accept `--cpu`. T1 removes it from n64-run, so mmbench on top of T1 exits with usage ("run did not reach the end of its script"). Whichever branch lands second must drop `--cpu` from mmbench. Not a defect in #32 alone.
2. Dead leftover: `RBusDevice::ARES_JIT` (ares/n64/n64.hpp:117) and its name string (ares/n64/rdram/rdram.hpp:232); its only user was recompiler.cpp:475.
3. Stray double blank line ares/n64/cpu/cpu.cpp:115-116.
4. Self-disclosed and accepted as noted: CPU::OpInfo flags (Branch, LikelyBranch, ...) now unread, kept for T7a; commit trailer wording differs from brief.
5. Not verified: full desktop-ui link (SDL3 headers missing in env, as the worker said); I did not try it either. desktop-ui edits are single-line removals of the "Recompiler" option and look correct by reading.
6. No timing constants added; no narrating comments added.

Verdict: PASS-WITH-NOTES. All plan Check items (nemu64 equal, mm per-field TSV byte-identical, det) reproduced; notes 1-3 are cleanup.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Worker claims not reproduced: none. Fact-3 8.5 s wall also not seen (head 9.8-12.4 s).
