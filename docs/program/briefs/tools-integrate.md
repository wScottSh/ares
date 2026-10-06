# Unit: tools-integrate (one tools lane: R1 + R2 + R4 on feat/tools)

GOAL
One branch, feat/tools, carrying romgen plus the bench (R1), thar0 (R2) and rdpstat (R4) suites, with shared code unified and every suite independently re-verified. Core build units then merge this one branch.

SCOPE
- Worktree /home/wscottsh/repos/ares-wt/tools on new branch feat/tools from origin/feat/romgen. `git merge --no-edit origin/feat/r1`, then origin/feat/r2, then origin/feat/r4 (merge commits; never rebase). Resolve conflicts (build.py suite_sets, README tables, encoders).
- Then refactor tools/n64-timing/romgen/ only:
  1. One RDP command builder: fold R4's rdp helpers and R1's rdp.py encoders into R2's tools/n64-timing/romgen/rcp.py; suites import it. ROM bytes of each suite must stay identical or the change must be explained (encoding fix) with before/after results identical.
  2. Runtime boot calls the PIF boot-termination write so long ROMs do not halt after 5 s (R2 found ares halts the CPU otherwise). This changes nemu64 ROM bytes; nemu64 results (values.tsv) must stay identical.
  3. Decouple the runtime from nemu64's measure templates (no more stub measure_loop_* labels in other suites).
- PR from feat/tools to feat/romgen. Write nothing outside tools/n64-timing/ and the worktree.

CONTEXT
Reports: /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/{romgen,r1,r2,r4}.md (read all; follow-ups listed there are your inputs). PRs #34 (romgen), #38 (R1), #39 (R2), #37 (R4). Runner: build with tools/n64-timing/build.sh into /home/wscottsh/n64-timing/build/tools (this base still has n64-run --cpu; use interpreter).

VERIFY (you are also the independent verifier for R1, R2, R4: a different model wrote them)
- Before refactor (after merges): run every suite: nemu64 (924/9/5 interpreter), bench (run.sh: 138/138 points, format ok), thar0 (100/100 configs report; -1 deltas today), rdpstat (systemtest/dpc/repeater64 counts per R4 under --rdp none and vulkan). Save under /home/wscottsh/n64-timing/results/tools/merged/.
- After refactor: same runs, results identical (except ROM bytes where explained). Save under ...\refactored\.
- Each suite's build is deterministic (build twice, cmp).
- Spot-check five expected values per suite against their cited sources (bench expected.tsv citations, thar0 vs Thar0 sample_results, rdpstat references' SHA-256 pins).
- Post one comment on each of PRs #37, #38, #39 with verdict PASS / FAIL / PASS-WITH-NOTES for that suite and the raw evidence. End comments with: 🤖 Generated with [Claude Code](https://claude.com/claude-code)

TIMEBOX About 4 hours. Commit and push after each step.

FORBIDDEN No gt, rebase, force-push, merging PRs, core edits, executing code from cloned repos.

REPORT /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/tools-integrate.md and return it: branch, head SHA, PR URL, verdict per suite with numbers, refactor results, deviations, follow-ups.

STANDING /home/wscottsh/.claude/orchestrate/ares-n64-timing/preferences.md
