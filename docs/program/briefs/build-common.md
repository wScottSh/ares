# Build unit brief (common to every T-unit)

GOAL
Implement exactly one unit of the timing-core build plan, named in your spawn prompt, so that its Check passes on the real built emulator.

THE CONTRACT
- Plan: docs/design/timing-core/plan.md (your unit's section is the spec: Goal, Files, Check). Design: docs/adr/0001-timing-core.md and docs/design/timing-core/sketch/. Both live on master. Read the ADR in full and your unit's section before touching code.
- The sketch is the contract (architect Phase D). If the code needs a deviation from the sketch or the plan (a parameter the sketch lacks, a file the plan did not name, a check that cannot run), make the smallest sound choice, and list it under DEVIATIONS in your report with why. Do not silently absorb it.
- Grounding for today's code: `git show origin/research/ares-timing-architecture:docs/research/ares-timing-architecture.md`. Research docs: origin/research/* (map #1 links them).

SCOPE
- Worktree: /home/wscottsh/repos/ares-wt/<unit> on branch feat/<unit>, created from the base branch named in your spawn prompt (`git -C /home/wscottsh/repos/ares fetch origin && git -C /home/wscottsh/repos/ares worktree add -b feat/<unit> /home/wscottsh/repos/ares-wt/<unit> origin/<base>`). Build dir /home/wscottsh/n64-timing/build/<unit> (pass it to tools/n64-timing/build.sh if supported; never share a build dir).
- If your spawn prompt names extra tool branches to bring in, `git merge --no-edit origin/<branch>` into your branch (merge commit; never rebase).
- Write only the files your unit's section names plus tests/tools it needs. No changes outside the unit's purpose. Mid-run discoveries outside scope go in FOLLOW-UPS.

VERIFY
- Build: tools/n64-timing/build.sh. Runner: n64-run (tools/n64-timing/README.md). MM ROM: /home/wscottsh/repos/mm-decomp-60fps/baseroms/n64-us/baserom.z64.
- Run your unit's Check items yourself, plus the standing checks that exist on your base: determinism (two runs byte-identical), the romgen nemu64 suite if present on your branch (counts not worse than the base; list every newly failing test with cause), generator check if present, step-cap if present, MM 600-field wall time.
- Capture the BEFORE numbers on your base branch first, then AFTER. Save raw outputs under /home/wscottsh/n64-timing/results/<unit>/{before,after}/.
- If a Check item's corpus is not available on your branch or is blocked, say so and run everything else; never mark it passed.

DELIVER
- Commits with clear messages (what and why; cite the hardware reference for any timing constant). End each commit message with: Co-Authored-By: Claude <noreply@anthropic.com>
- Push feat/<unit>. Open a PR whose base is the base branch from your spawn prompt (gh pr create --base <base>). PR body: what changed, how verified (commands + raw numbers before/after), deviations, follow-ups. End the PR body with: 🤖 Generated with [Claude Code](https://claude.com/claude-code)
- Do not merge anything.

TIMEBOX
About 5 hours. On expiry: commit and push what builds, open the PR as draft, report precisely what is done and what is not.

FORBIDDEN
No gt, no rebase, no force-push, no merging PRs, no edits outside your worktree, no external code execution (cargo, make of cloned repos, running scripts from clones), no Nintendo data in git. If the permission classifier denies a call, do not retry or work around it; record it and continue with what remains.

REPORT
Write /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/<unit>.md and return it: status (done/partial), branch, head SHA, PR URL, the Check list with each item's raw result (pass/fail/pending + numbers), standing checks before/after, MM wall time before/after, DEVIATIONS, FOLLOW-UPS, anything the next unit must know.

STANDING
Read and obey /home/wscottsh/.claude/orchestrate/ares-n64-timing/preferences.md.
