# Unit: verify-<pr> (independent verification of one stacked PR)

GOAL
Decide whether the PR named in your spawn prompt does what its plan unit says, on the real built emulator, independently of the worker's report.

DO
1. Read the unit's section in docs/design/timing-core/plan.md (on origin/feat/design) and the worker's report at the path in your spawn prompt. Treat the report as claims to check, not facts.
2. Make your own worktree /home/wscottsh/repos/ares-wt/verify-<pr> at the PR head (detached is fine) and another at its base, or build both from one worktree in turn. Build dirs /home/wscottsh/n64-timing/build/verify-<pr>-{base,head}.
3. Rerun the unit's Check items and the standing checks yourself (determinism, MM bench if on the branch, any suite present). Compare base vs head where the check says "identical".
4. Read the full diff. Flag: scope creep, leftover dead code, behavior changes not in the plan, timing constants without a cited reference, comments that narrate instead of explaining a why.
5. Post one PR comment (gh pr comment <pr> --body-file ...) with verdict PASS / FAIL / PASS-WITH-NOTES, the commands you ran and the raw numbers. End it with: 🤖 Generated with [Claude Code](https://claude.com/claude-code)

DO NOT
Edit code, push commits, merge, approve via review API, rebase, force-push. If a classifier denies a call, do not work around it; record it.

REPORT
Write /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/verify-<pr>.md and return it: verdict, what you ran, raw numbers, diff findings (file:line), anything the worker's report claimed that you could not reproduce.

STANDING
Read /home/wscottsh/.claude/orchestrate/ares-n64-timing/preferences.md.
