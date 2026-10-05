# Unit: design-core (architect arena runner: timing core architecture)

You are one runner in an architect arena. Other runners on other models get this same brief. Produce the best design your model can make; do not hedge toward a safe middle.

GOAL
A design package for the timing core of this ares fork's N64 emulation: the architecture every timing behavior on map #1 plugs into. It must decide, with reasons:
1. Scheduler and shared time (#9, #14): how CPU, RSP, RDP, SP/PI/SI/AI DMA and VI scanout share one emulated timeline such that RDRAM bus contention is ordered exactly by time, independent of sync frequency, and bit-deterministic. Lockstep transaction timeline vs windowed occupancy vs something else.
2. The bus model (#4, #14): RDRAM/RI with 8 banks x open row, burst costs, refresh per HSYNC, requesters (CPU cache fill/writeback, write buffer drain, uncached, RSP DMA, RDP command fetch + span reads/writes + TMEM loads, PI/SI/AI DMA, VI fetch), arbitration (client priority has no published source: say what you pick and how it is parameterised so calibration #16 can change it).
3. The CPU timing seam (#15, #5, #6, #26, #10): pipeline-stage simulation vs register scoreboard plus per-stage exception/CP0 delays; where interlocks, cache, write buffer and COUNT live; how the interpreter and recompiler share one cost function per event so they are bit-identical, or why the recompiler should be dropped from the timing path.
4. The RDP as a time-stepped device (#13, #2, #3, #8, #12, #17, #18, #19, #20, #21): where pixels and per-pixel results come from (paraLLEl GPU with per-span counters + readback, a CPU-side software rasterizer such as a port of angrylion-rdp-plus or cen64/MAME RDP — check licenses vs ares ISC — or other), how DPC_CURRENT advances, END_PENDING/DMA_BUSY/TMEM_BUSY, FIFO back-pressure, DP interrupt at modeled time, span RAM, write granularity per run of written pixels.
5. The RSP (#28, #10): its timing seam and recompiler policy.
6. Where behaviour parameters live (one table of hardware constants with reference citations, so the spec rows and the code cannot drift), and how verification attaches per behaviour.
7. The run budget: 600 MM frames (10 s emulated) must run in <= 2 min host time on this machine (Windows 11, x86-64 desktop). Estimate cost of your design with reasoning; flag what must be measured.

CONTEXT (read all)
- Map: `gh issue view 1 -R wScottSh/ares` (Notes = hard constraints; Decisions = findings). Open design tickets: `gh issue view 13 --comments`, `14`, `15`, `9`, `27`, `28` (repo wScottSh/ares).
- Grounding (Phase A, already done): `git -C C:\Users\Scott\repos\ares show origin/research/ares-timing-architecture:docs/research/ares-timing-architecture.md`. Read it first; it is the traced model of today's code with file:line citations and maps every decision to code sites.
- Every research doc linked from the map: `git -C C:\Users\Scott\repos\ares show origin/research/<branch>:docs/research/<file>.md` (branches: rdp-command-timing, rdp-memory-traffic, rdram-bus-arbitration, nemu64-timing-failures, cpu-memory-costs, dma-timing, rsp-rdp-fifo, recompiler-parity, rdp-pixel-timing-coupling, rdp-write-granularity, rdp-noise, 1prim-cost, span-ram, mm-rdp-stream, vi-fetch, clocks, vr4300-wb, mm-buffer-placement, jgemu-dpc-probe).
- Source: C:\Users\Scott\repos\ares (read only; ares/n64/**).
- The architect skill: C:\Users\Scott\.claude\plugins\cache\pstack-claude\pstack\0.9.67\skills\architect\SKILL.md, runner discipline references/runner-prompt.md, package shape references/rationale-template.md, screen against references/design-red-flags.md. Follow them.

OUTPUT
Write to C:\Users\Scott\n64-timing\design\core\candidate-<your-model-name>\:
- rationale.md, shaped per rationale-template.md (Problem, Usage, Shape, Tradeoffs, Alternatives, Open questions, Next step; leave Synthesis decision empty).
- sketch/ : C++ header sketches (types, signatures, module map) in the ares code style, bodies `/* not implemented */` with pseudocode for tricky logic. Show the core data structures (timeline/event, bus transaction, bank state, device interface, cost tables) concretely.
- plan.md : the build sequence as verifiable units (each with its check: which test ROM / bench / measurement proves it), ordered so each lands on a green base. This is what the program's build track will execute.
Do not write anywhere else. No repo edits, no branches.

TIMEBOX
About 2.5 hours.

REPORT
Return: path, a 20-line summary of your shape and the three load-bearing decisions, the cost estimate, and what you are least sure of.

STANDING
Read and obey C:\Users\Scott\.claude\orchestrate\ares-n64-timing\preferences.md.
