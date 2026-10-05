# Report: measure-28 (#28 RSP recompiler timing)

Status: DONE.
Branch: research/rsp-recompiler-timing (from origin/feat/harness c8592d16a), pushed. No PR.
Head SHA: b0f6818f395ca3b837854a40a3f5f12ff7b538f7
Doc: https://github.com/wScottSh/ares/blob/research/rsp-recompiler-timing/docs/research/rsp-recompiler-timing.md

Map gist: RSP-JIT +1.16% busy (gfx +1.85%) = context cache ignores entry pipeline state (69%) + SP DMA stepped per block (31%); block overrun past sync shifts CPU-visible timing; with all three matched the cores are byte-identical, so recommend RSP interpreter as timing reference, JIT off the timing path.

Key numbers (measured, MM boot 600 fields, --rdp none, deterministic, 2 runs identical):
- CPU interp: RSP interp 178,662,558 vs RSP JIT 180,727,842 rsp_busy_clocks (+2,065,275 over tasks, +1.157%). Gfx tasks +1.845%, audio +0.052%.
- Fix A (context keyed on pipeline hash): removes 1,429,071. Audit: 756,009 of 9,773,487 context hits use a stale block; stale-minus-correct static clocks +1,435,326, of which +1,105,230 where singleIssue differs.
- B (interp with DMA stepped at JIT block ends): +636,204, matches remainder exactly per task.
- C (interp runs whole blocks before clock check): 0 busy ticks with CPU interp, but 224/600 fields' cpu_cycles differ by up to 40 PClocks; 7,410 busy ticks under CPU JIT.
- JIT+A == interp+B+C: stats and task logs byte-identical, both under CPU interp and CPU recompiler.
- DMA overshoot carry: -11,730, not a cause. Cost tables: identical (shared Pipeline model).
- Wall (instrumented build, n=3, noisy): RSP interp costs 0.13-0.57 s more per 600 fields than RSP JIT with CPU JIT.

Artifacts: instrumentation patch (not delivered) C:\Users\Scott\n64-timing\results\measure-28\instrumentation.patch; raw outputs same dir; scripts in docs/research/rsp-recompiler-timing/{run.sh,cmp.py}. Worktree C:\Users\Scott\repos\ares-wt\measure-28 is clean (core edits reverted). Build dir C:\Users\Scott\n64-timing\build\measure-28 holds an instrumented binary.

Open questions:
- Whether the interpreter's RSP pipeline rules (taken-branch stall, branch.pc&4 single-issue, hazard distances) match hardware: not in scope, unverified.
- Per-scene A/B split on the MM bench scenes not measured (bench unit not landed); only boot-600.
- Halt-exit pipeline state (Block::execute sets end-of-block state before running) is a code-reading parity gap with no measured MM effect.

No permission denials.
