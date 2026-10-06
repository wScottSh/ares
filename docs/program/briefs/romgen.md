# Unit: romgen (in-repo test ROM generator + nemu64-test timing port)

GOAL
The fork can generate its own self-checking timing test ROMs from in-repo code, with no external toolchain, and the first suite generated this way is a faithful port of nemu64-test's timing, cycle and cop0hazard tests. Its result on the unmodified core reproduces the published baseline.

WHY THIS WAY
Building nemu64-test with cargo on this machine was blocked by the permission classifier ("Code from External"). Do not retry that, do not run cargo, make, or any external build system, and do not execute code from cloned repos. Reading MIT-licensed source and re-implementing its test cases in our own Python is the path. Keep attribution: nemu64-test is MIT (thelemmy/nemu64-test @ 9a8b9f7); put the license text and the source commit in the generated suite's README.

SCOPE
- Worktree /home/wscottsh/repos/ares-wt/romgen on branch feat/romgen, created from origin/feat/harness (the stack base, PR #30). PR targets feat/harness.
- May write: tools/n64-timing/romgen/ (Python package: MIPS R4300 assembler subset, ROM image builder using the libdragon ipl3_compat.z64 boot stub as tools/n64-timing/make-emux-smoke-rom.py does, emux XLOG/XIOCTL helpers, test-suite modules), tools/n64-timing/run-suite.sh or extend run-nemu64.sh, README.
- Generated ROMs go to /home/wscottsh/n64-timing/roms/ (not committed).
- May not write: ares/ core, any other worktree.

CONTEXT
- Harness (read its README and code first): `git -C /home/wscottsh/repos/ares show origin/feat/harness:tools/n64-timing/README.md`; runner `/home/wscottsh/n64-timing/build/harness/n64-run/rundir/n64-run` (build with `bash <worktree>/tools/n64-timing/build.sh`; usage in the README). Report: /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/harness.md.
- nemu64-test source clone (read only, do not build or execute): /home/wscottsh/n64-timing/scratch/r29/clones/nemu64-test. Key: src/tests/timing/mod.rs (measure_cycles_codegen: contiguous I-cache-aligned program, body run twice offset by one instruction to recover half-cycles), src/tests/cycle*, cop0hazard tests, src/emux.rs, src/tests/mod.rs (output format).
- Baseline to reproduce: `git -C /home/wscottsh/repos/ares show origin/research/nemu64-timing-failures:docs/research/nemu64-timing-failures.md`. Interpreter fails 924/1604 timing, 9/13 cycle, 5/5 cop0hazard; recompiler 1109/10/5. It also lists the 11 root-cause categories with counts; your per-category failure counts should match.

ACCEPTANCE
- `python tools/n64-timing/romgen/build.py --suite nemu64 --out /home/wscottsh/n64-timing/roms` (or equivalent single command) generates the ROMs deterministically (same bytes twice).
- A single command runs them through n64-run and prints `Timing: Failed X of Y`, cycle and cop0hazard summaries in nemu64's format, plus a per-test TSV.
- Test count matches nemu64-test (1604 / 13 / 5) or the difference is listed test by test with reason.
- Interpreter and recompiler failure counts on the stack base match the baseline, or every divergent test is listed with its cause traced (port bug vs settings difference such as deterministic entropy).
- The assembler has a self-test: encode a list of instructions and compare against hand-checked encodings (cite the VR4300 manual encoding tables).
- PR opened against feat/harness.

VERIFY
Run the acceptance commands yourself; paste raw summaries.

TIMEBOX
About 5 hours. On expiry push partial work, report what fraction of the suite is ported and the blocker.

FORBIDDEN
No cargo/make/external builds, no executing cloned code, no core edits, no gt, no rebase, no force-push, no merging.

REPORT
Write /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/romgen.md and return it: status, branch, head SHA, PR URL, commands, raw counts both CPU modes, per-category comparison with the baseline, divergences, follow-ups (which other corpora — Thar0 RDP-Timing-Tests, n64-systembench, Mr-Wiseguy cache tests — port next and how hard).

STANDING
Read and obey /home/wscottsh/.claude/orchestrate/ares-n64-timing/preferences.md.
