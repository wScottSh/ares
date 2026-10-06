# Unit: ground (how ares N64 time works today)

GOAL
A traced, file:line-cited model of how emulated time flows through this fork's N64 core today, plus a table mapping every map decision to the code it will change. Three design units (CPU pipeline #15, bus model #14, RDP timing architecture #13) will be grounded on this document.

SCOPE
- Write only: worktree /home/wscottsh/repos/ares-wt/ground on branch research/ares-timing-architecture (from origin/master), file docs/research/ares-timing-architecture.md. Push the branch. No PR.
- Read anything. No code changes.

CONTEXT
- Map with all decisions so far: https://github.com/wScottSh/ares/issues/1 (gh issue view 1). Each decision links a doc on an origin/research/* branch; read them with `git show origin/research/<branch>:docs/research/<file>.md`. Read all of them.
- Open design questions to ground: #13, #14, #15 (gh issue view N --comments), and research #9 (scheduler granularity).
- Follow the output contract of the `how` skill at /home/wscottsh/.claude/plugins/cache/pstack-claude/pstack/<installed-version>\skills\how\SKILL.md (read it first). Do the reading yourself.

Cover at least:
1. Scheduler and threads: how ares sequences CPU, RSP, RDP, VI, AI, PI, SI, RI (the Thread/Scheduler classes, clock units, frequencies, synchronize calls, JitInterleaving or equivalent).
2. CPU: interpreter step, where cycles are charged (instruction, cache hit/miss, uncached, RCP register, PI), recompiler charging, interrupt sampling, COUNT/COMPARE.
3. Memory bus dispatch: how a CPU/RSP/DMA access reaches RDRAM/RCP registers/PI and what time it costs; any contention model.
4. RSP: step, DMA, sync with CPU, SP status/interrupts.
5. RDP: command fetch (DPC_START/END/CURRENT), processing, render paths (software render.cpp vs paraLLEl vulkan), threading, when DPC status bits change and when the DP interrupt is raised.
6. DMA engines SP/PI/SI/AI and VI scanout: when transfers complete and what they cost.
7. Determinism hazards visible in code: host threads, GPU sync, wall clock, uninitialized state.
8. A table: each map decision (one row per linked research doc) → code site(s) file:line it will change → what is there now.

ACCEPTANCE
- Every claim cites file:line at origin/master (59158c28a).
- The decision → code-site table covers every decision listed on the map.
- Doc pushed to origin/research/ares-timing-architecture.

VERIFY
Spot-check your own citations by reopening ten of them before pushing.

TIMEBOX
About 3 hours.

FORBIDDEN
No code edits, no PRs, no gt, no force-push.

REPORT
Write to /home/wscottsh/.claude/orchestrate/ares-n64-timing/reports/ground.md and return it: status, branch, head SHA, doc URL (https://github.com/wScottSh/ares/blob/research/ares-timing-architecture/docs/research/ares-timing-architecture.md), a 15-line summary of the model, the three biggest structural obstacles to a hardware-accurate timing model, suggested follow-ups.

STANDING
Read and obey /home/wscottsh/.claude/orchestrate/ares-n64-timing/preferences.md before starting.
