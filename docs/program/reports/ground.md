# Report: ground (ares N64 timing architecture)

Status: done. The doc is pushed and has no PR, as the brief says.
Branch: research/ares-timing-architecture (from origin/master 59158c28a)
Head SHA: 4a20353b7ae08bf60a5572928a2a09a85082dd9c
Doc: https://github.com/wScottSh/ares/blob/research/ares-timing-architecture/docs/research/ares-timing-architecture.md
Local: C:\Users\Scott\repos\ares-wt\ground\docs\research\ares-timing-architecture.md

## Model summary (15 lines)

1. The N64 core does not use ares's cothread Scheduler. It shadows it with `Nintendo64::Thread`, which is one s64 counter (n64.hpp:62-76). The unit is a 187.5 MHz tick: CPU cycle = 2, RCP cycle = 3, COUNT tick = 4.
2. The CPU is the only master. `CPU::synchronize` (cpu.cpp:83-121) subtracts the CPU's elapsed ticks from VI, AI, RSP, RDP and PIF. It then runs each `main()` until that device's clock is ≥ 0, in fixed order, then fires queue events, then advances COUNT.
3. The interpreter syncs after every instruction. The recompiler syncs when its clock passes `jitClockTarget`, which is at most 4096 ticks, the timer, or the next queue event (accuracy.hpp:10, cpu.cpp:160-174).
4. Step sizes: RSP is one issue pair or one JIT block, and 128 ticks while halted. VI is one line, AI one sample, PIF 81,920 ticks. The RDP steps one emulated second and only advances `command.clock` (rdp.cpp:29-35).
5. Queue events are scheduled relative to the last sync, not the requesting instruction. They fire early by the unsynced CPU ticks: about 1 cycle in the interpreter, up to about 4096 ticks in the JIT [inference, code reading].
6. `forceSynchronize()` only zeroes the JIT budget. A CPU read of a device register sees state as of the last sync.
7. CPU costs: 1 at fetch, before execute. D-hit +1, D-miss +40, plus +40 writeback first if the victim is dirty. I-miss +48. RCP register read +20. Writes 0. PI read +270. RDRAM uncached 0. MULT/DIV/FPU fixed. Exceptions, ERET and CACHE cost 0. No inter-instruction pipeline state.
8. The JIT charges the base cycle after the op. It has its own FPU table and double-charges on slow paths. The I-cache guard is skipped at mid-line entries, and the I-fill path bypasses Bus.
9. Bus: `Bus::read/write` dispatch by address. RDRAM goes through `MI::readRdram` → `rdram.ram.read`, with no cost, no arbitration, no row state and no refresh. DMA engines call `rdram.ram` directly. RBusDevice is used only for homebrew-mode byte counters.
10. RSP DMA moves 1 RCP cycle per 8 B, per row. It copies at row end and drops overshoot, so row completion rounds up to the RSP step (128 ticks while halted) [inference].
11. RDP: a `DPC_END` write renders synchronously inside the writer's instruction, sets `current = end` and raises the DP IRQ at the writer's time (io.cpp:78-87, vulkan.cpp:146, render.cpp:617-624). There is no END_PENDING, DMA_BUSY is 0, and the TMEM_BUSY read is dead (`data == 7`).
12. Pixels come only from paraLLEl-RDP on the GPU. The CPU `render()` decodes commands, but every primitive, sync and load handler is empty. The host waits on the GPU only at SyncFull.
13. PI data lands at DMA start and the IRQ comes later via the queue, using a BSD formula with two known bugs. SI data moves at completion, using systembench constants. AI and VI charge no bus time. The VI steps per line and raises IRQs then.
14. Determinism: `random` is host-seeded unless "Deterministic Entropy" is on. Its consumers are the RDRAM CC thresholds (which affect IPL3 calibration), CP0 Random, SP_PC reads while the RSP runs, and RDRAM degrade. GPU-async RDRAM writes are visible to CPU/RSP reads before SyncFull [inference].
15. Reported 1% interpreter run-to-run noise (recompiler-parity doc): cause still unknown. Random seeding is the first candidate. I did not check whether the bench enables Deterministic Entropy.

## Three biggest structural obstacles

1. The scheduler is a CPU-master catch-up loop with no shared timeline. Devices run whole windows in fixed order. Reads see stale state, queue events fire relative to the last sync, and the window size differs between interpreter and JIT. A per-burst RDRAM arbiter (#4/#14) cannot order requesters by time without either syncing at every bus access or adding timestamped transactions.
2. The RDP is not a device in time, and its per-pixel results exist only on the GPU, asynchronously. A timed RDP needs clocked command fetch, span-level traffic and write sets (#12/#17). That means either a CPU-side rasterizer or GPU per-span counters with a readback sync point (#13).
3. Costs are flat constants scattered over 55 interpreter `step()` sites, with parallel recompiler tables and no RDRAM cost anywhere. There is no stage state for interlocks and no write buffer. The rule "the recompiler survives only with bit-identical timing" needs one shared cost function per event, charged at one consistent point in each instruction (#10/#15).

## Decisions and how I verified

- I treated the brief's "Do the reading yourself" as overriding the `how` skill's explorer/explainer subagents. I read the code and all 17 research-branch docs directly. The doc keeps the how output sections: Overview, Key concepts, How it works (sections 1-7), Where things live, Gotchas.
- The table covers all 16 decisions listed on map #1. jgemu-dpc-probe (#25) has a research branch but is not on the decision list, so I noted it under the table instead of giving it a row.
- Verification: a script (scratchpad `checkcites.py`) checked that all 253 full-path citations name an existing file and an in-range line. It reported 0 bad. I reopened 12 citations by hand and they match the doc (cpu.cpp:90-99, accuracy.hpp:10, rdp.cpp:29-35, rdp/io.cpp:58, rsp/dma.cpp:64-67, memory/io.hpp:3-4, pi/bus.hpp:63, vulkan.cpp:136-139, rsp/io.cpp:173-177, priority-queue.hpp:35-39, pif/hle.cpp:262-264, ai/io.cpp:61-62). Before writing, I corrected 8 line numbers I had first taken from memory.
- Nothing was run or measured. Every behavioral claim comes from reading code, and inferences are labeled in the doc.

## Suggested follow-ups

1. #9: measure the host cost of interpreter lockstep against the JIT at 4096 / 512 / 64-tick budgets on the 600-frame MM bench. Also check whether the bench sets "Deterministic Entropy". If it does not, rerun the B-vs-B2 determinism pair with it on.
2. File a bug for the queue-offset early-fire (pi/io.cpp:110,119 via cpu.cpp:56-62 + priority-queue.hpp:35-39). It changes PI/SI completion times between interpreter and JIT.
3. File the small defects as tracked issues: the `data == 7` TMEM_BUSY read (rdp/io.cpp:58), RSP DMA overshoot dropped per row (rsp/dma.cpp:64-67), and the VI_CONTROL bit 16 readback (vi/io.cpp:5-16).
4. For #13: decide between a CPU-side rasterizer (the software path is an empty decoder today, so this is new code) and paraLLEl per-span write counters with readback. Account for the fact that the CPU path has no existing pixel pipeline to extend.
5. For #14: the design must replace the `CPU::synchronize` device order and the "DMA engines call rdram.ram directly" pattern together. Every requester currently bypasses `Bus`.
