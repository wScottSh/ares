# Unit: measure-<ticket> (research #9, #27, #28 with the new harness)

Three sibling units share this brief. Your ticket is named in your spawn prompt. Do only yours.

COMMON
- Harness: `git -C C:\Users\Scott\repos\ares show origin/feat/harness:tools/n64-timing/README.md`; report C:\Users\Scott\.claude\orchestrate\ares-n64-timing\reports\harness.md. Make your own worktree C:\Users\Scott\repos\ares-wt\<unit> from origin/feat/harness and build there with its tools/n64-timing/build.sh (point the build dir at C:\Users\Scott\n64-timing\build\<unit> if the script allows; do not reuse another unit's build dir while it may be building). Instrumentation edits to the core are allowed in your worktree for measurement only; they are never delivered.
- MM ROM: C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64 (C:/ form; apostrophe). Boot-to-600-fields is the available workload until the MM bench unit lands.
- Grounding: `git -C C:\Users\Scott\repos\ares show origin/research/ares-timing-architecture:docs/research/ares-timing-architecture.md`.
- Deliver: docs/research/<name>.md on branch research/<name>, pushed. No PR. Write the doc in plain technical English; every number labelled measured / cited / inferred with the command that produced it.
- Report to C:\Users\Scott\.claude\orchestrate\ares-n64-timing\reports\<unit>.md and return it: status, branch, head SHA, doc URL, one-line map gist, open questions.
- Timebox about 2.5 hours. Forbidden: gt, rebase, force-push, PRs, merging, edits outside your worktree.
- Standing orders: C:\Users\Scott\.claude\orchestrate\ares-n64-timing\preferences.md.

measure-27 (branch research/determinism)
Answer wScottSh/ares#27: every host-dependent input that can leak into emulated timing or state. The harness shows MM 600 fields byte-identical with deterministic entropy on and --rdp none. Enumerate and test each source: entropy setting off vs on, --rdp vulkan vs none (incl. RDRAM written by the GPU and read back), recompiler vs interpreter, thread scheduling, audio/video drivers, RTC/wall clock (ares RTC for carts), uninitialised memory, save files. For each: mechanism (file:line), measured effect (run pairs, which field differs, from which frame), and what removing it requires. Also say what the original 1% South Clock Town noise most likely was.

measure-9 (branch research/scheduler-granularity)
Answer wScottSh/ares#9: what interleaving granularity CPU, RSP, RDP and DMA need for exact bus-contention ordering, and its host cost. Measure: interpreter MM 600 fields wall time today; profile where host time goes (per device main(), synchronize overhead); cost of forcing per-instruction RSP sync and per-bus-access sync (instrument); recompiler at JitInterleaving budgets 4096/512/64 ticks if the setting exists. Report the remaining budget against 2 min for 600 frames, and how much per-transaction bus arbitration could cost (microbenchmark an arbiter-shaped event loop if useful).

measure-28 (branch research/rsp-recompiler-timing)
Answer wScottSh/ares#28: why RSP tasks run longer on the RSP recompiler than the interpreter. Reproduce on MM (rsp_busy_clocks in stats; per-task durations via instrumentation), isolate the cause (DMA progress per block, block overrun past sync point, cost tables, pipeline-stall model differences), and state what bit-identical RSP timing requires or whether the RSP recompiler should leave the timing path.
