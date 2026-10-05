# How emulated time flows through the ares N64 core today

Unit: ground (map [#1](https://github.com/wScottSh/ares/issues/1)). Grounds the design questions [#13](https://github.com/wScottSh/ares/issues/13) (RDP timing architecture), [#14](https://github.com/wScottSh/ares/issues/14) (bus model), [#15](https://github.com/wScottSh/ares/issues/15) (VR4300 timing behaviors) and research [#9](https://github.com/wScottSh/ares/issues/9) (scheduler granularity).

Every `file:line` is at `origin/master` = `59158c28a`. Paths are relative to the repo root. Claims marked **[inference]** are reasoning from the cited code that was not run. Nothing in this doc was measured; numbers in the table in section 8 that say "measured" come from the linked research docs.

## Overview

The N64 core does not use ares's cooperative-thread scheduler. It has its own model: the CPU is the only master, and every other device is a lagging clock that the CPU drags forward after each CPU step.

- Every timed component owns one signed counter, `Thread::clock` (`ares/n64/n64.hpp:62-76`). The unit is a 187.5 MHz master tick (`ares/n64/system/system.hpp:37`).
- `System::run` calls `cpu.main()` once per host frame (`ares/n64/system/system.cpp:83-89`). `CPU::main` runs instructions until the VI sets `refreshed` (`ares/n64/cpu/cpu.cpp:37-47`).
- After a CPU step, `CPU::synchronize` (`ares/n64/cpu/cpu.cpp:83-121`) subtracts the CPU's elapsed clocks from VI, AI, RSP, RDP and PIF. Each of those then runs its own `main()` until its counter is no longer negative. Then the event queue (PI, SI, RTC, flash, DD, GDB) advances. Finally COUNT advances.
- The interpreter synchronizes after every instruction (`ares/n64/cpu/cpu.cpp:39`, `:184`). The recompiler synchronizes only when the CPU clock passes `jitClockTarget`, a budget of at most `JitInterleaving` = 4096 ticks (2048 CPU cycles) (`ares/n64/accuracy.hpp:10`, `ares/n64/cpu/cpu.cpp:160-174`).
- Costs are constants passed to `step()` at the place where the work happens. No component charges time for RDRAM access, and no component arbitrates the bus.
- The RDP has no time. A `DPC_END` write renders the whole command range synchronously inside the writer's instruction and raises the DP interrupt then (`ares/n64/rdp/io.cpp:78-87`, `:195-209`, `ares/n64/rdp/render.cpp:617-624`). Pixels come only from paraLLEl-RDP on the GPU; the CPU-side `render()` is a command decoder whose primitive handlers are empty (`ares/n64/rdp/render.cpp:557-624`).

## Key concepts

| Concept | What it is | Where |
|---|---|---|
| Master tick | 187.5 MHz = 2 × PClock = 3 × RCP clock. 1 CPU cycle = 2 ticks, 1 RCP cycle = 3 ticks, 1 COUNT tick = 4 ticks | `ares/n64/system/system.hpp:37`; CPU `step(1 * 2)` `ares/n64/cpu/memory.cpp:158`; RSP `clocks += 3` `ares/n64/rsp/rsp.hpp:214,221` |
| `Thread` | A struct with one `s64 clock` and `step(n)` that adds to it. No coroutine, no stack | `ares/n64/n64.hpp:62-76` |
| Lag window | After `CPU::synchronize`, each device's clock is ≥ 0, so each device has caught up to or overshot the CPU's time. Between syncs, devices lag the CPU by the CPU's unsynced clocks | `ares/n64/cpu/cpu.cpp:84-99` |
| `queue` | A 512-entry binary min-heap of `(u32 clock, event)` for PI/SI/flash/RTC/DD/GDB completions | `ares/n64/n64.hpp:78-96`, `nall/nall/priority-queue.hpp:27-99` |
| `jitClockTarget` | The recompiler's exit budget. `forceSynchronize()` sets it to 0 | `ares/n64/cpu/cpu.cpp:56-66` |
| `RBusDevice` | An enum naming each RDRAM client. Used only for debugger byte counters in homebrew mode, never for cost | `ares/n64/n64.hpp:104-125`, `ares/n64/rdram/rdram.hpp:53-56` |
| ares `Scheduler` / `Thread` (cothreads) | The generic ares scheduler. The N64 core never references it | `ares/ares/scheduler/scheduler.hpp:3-45`; grep of `ares/n64` for `scheduler`/`cothread` finds only a comment at `ares/n64/cpu/recompiler.cpp:31` |

## 1. Scheduler and threads

**The sync loop.** `CPU::synchronize` (`ares/n64/cpu/cpu.cpp:83-121`) does, in order:

1. Takes `clocks = Thread::clock` (CPU ticks since the last sync) and zeroes the CPU clock, `countClock` and `jitClockTarget` (`:84-88`).
2. Subtracts `clocks` from `vi`, `ai`, `rsp`, `rdp`, `pif` (`:90-94`).
3. Runs `vi.main()`, `ai.main()`, `rsp.main()`, `rdp.main()`, `pif.main()` in that fixed order (`:95-99`). Each loops `while(Thread::clock < 0)`.
4. Steps the queue by `clocks` and fires every due event (`:101-118`).
5. Advances COUNT by the ticks not already counted (`:120`).

So within one window the devices do not interleave in time. The VI runs its whole window, then the AI, then the RSP, then the RDP, then the PIF, then the queued events. Only the window size bounds the reordering.

**Per-device step granularity.** A device can only overshoot by one of its own steps:

| Device | Step per `main()` iteration | Where |
|---|---|---|
| CPU interpreter | 1 instruction, sync after each | `ares/n64/cpu/cpu.cpp:39`, `:177-184` |
| CPU recompiler | 1 block, sync when clock ≥ `jitClockTarget` (≤ 4096 ticks, the timer, or the next queue event) | `ares/n64/cpu/cpu.cpp:160-174` |
| RSP running, interpreter | 1 issue pair, `step(pipeline.clocks)` | `ares/n64/rsp/rsp.cpp:49-86` |
| RSP running, recompiler | 1 block | `ares/n64/rsp/rsp.cpp:50-52`, `:107-111` |
| RSP halted | 128 ticks (42.7 RCP cycles) | `ares/n64/rsp/rsp.cpp:37-40` |
| RDP | `system.frequency()` = 187,500,000 ticks, i.e. one emulated second; only advances `command.clock` | `ares/n64/rdp/rdp.cpp:29-35` |
| VI | 1 scan line in VCLK units, converted to ticks with an exact remainder | `ares/n64/vi/vi.cpp:10-14`, `:120-123` |
| AI | 1 sample at `dac.period` ticks | `ares/n64/ai/ai.cpp:27-33` |
| PIF | 81,920 ticks | `ares/n64/pif/hle.cpp:262-264` |

**Frequencies.** `system.frequency()` = 187.5 MHz (`ares/n64/system/system.hpp:37`). VCLK = 48,681,818 Hz NTSC (`ares/n64/system/system.cpp:107-110`). The VI converts VCLK to ticks with a remainder carried in `clockFraction` (`ares/n64/vi/vi.cpp:10-14`). The AI sets `dac.frequency = videoFrequency / (dacRate + 1)` and `dac.period = frequency / dac.frequency`, both integer divisions (`ares/n64/ai/io.cpp:61-62`).

**The queue.** `queue.insert(event, d)` schedules at `queue.clock + d` (`nall/nall/priority-queue.hpp:35-39`). `queue.clock` advances only inside `CPU::synchronize` (`ares/n64/cpu/cpu.cpp:101`). An event inserted mid-window therefore fires `d` ticks after the *last sync*, not `d` ticks after the CPU instruction that requested it. **[inference]** Queue events fire early by the CPU ticks elapsed since the last sync. In the interpreter that is the current instruction's ticks before the register write (2 for a plain store). In the recompiler it can approach 4096. `CPU::queueInsert` sets `jitClockTarget = Thread::clock + timeToNextEvent()` (`ares/n64/cpu/cpu.cpp:56-62`), which assumes the opposite convention, so the two disagree.

**Cross-device reads.** A CPU read of a device register sees the device state as of the last sync. `forceSynchronize()` (`ares/n64/cpu/cpu.cpp:64-66`) only zeroes `jitClockTarget`, so the *next* recompiler exit check syncs; it does not catch the device up before the read. Callers: SP_STATUS, SP_SEMAPHORE (`ares/n64/rsp/io.cpp:48,65,147,161`), every DPC read from the CPU (`ares/n64/rdp/io.cpp:8-61`), VI_V_CURRENT (`ares/n64/vi/io.cpp:37`), AI_STATUS (`ares/n64/ai/io.cpp:18`), SI (`ares/n64/si/io.cpp:51`). Two devices correct for the lag explicitly by reading `Thread::clock - thread.clock`: RSP DMA start (`ares/n64/rsp/dma.cpp:1-3`) and `DPC_CLOCK` (`ares/n64/rdp/io.cpp:41`, `:104`).

**Interrupts.** A device raises an MI line (`ares/n64/mi/mi.cpp:21-32`). `MI::poll` sets CPU `Cause.IP2` (`:46-55`). `CPU::setInterruptPending` calls `interruptPoll`, which forces a sync if the interrupt is enabled (`ares/n64/cpu/cpu.cpp:123-134`). The CPU samples interrupts at the start of `instruction()`, charges 1 cycle and takes the exception (`ares/n64/cpu/cpu.cpp:137-144`). Because devices run inside `synchronize`, an RCP interrupt is seen at the first CPU instruction after the sync window in which the device raised it.

**Answer for #9 (what exists today).** There is no shared timeline. The interpreter gives per-instruction interleaving for free; the recompiler gives ≤ 4096-tick windows; and inside a window devices run in a fixed order. The RDP and the PIF step in huge quanta and the halted RSP in 128-tick quanta. A bus model has nowhere to put "who asked first" except the order of the `main()` calls.

## 2. CPU

**Interpreter step** (`ares/n64/cpu/cpu.cpp:136-185`):

1. Interrupt check: if pending and enabled, `step(2)` then `exception.interrupt()` (`:137-144`). NMI and SysAD freeze also `step(2)` (`:146-155`).
2. `devirtualize` the PC (`:157`).
3. `fetch()` charges `step(1 * 2)` **before** the instruction executes, then reads through the I-cache or the bus (`ares/n64/cpu/memory.cpp:157-164`).
4. Decode and execute (`ares/n64/cpu/cpu.cpp:179-183`). Multi-cycle ops add `step((n - 1) * 2)` inside the op.

**Where cycles are charged.**

| Event | Charge (CPU cycles) | Where |
|---|---|---|
| Every instruction | 1 at fetch | `ares/n64/cpu/memory.cpp:158` |
| I-cache hit | 0 extra | `ares/n64/cpu/cpu.hpp:162-171` |
| I-cache miss | +48 | `ares/n64/cpu/cpu.hpp:208-214` |
| D-cache hit, load or store | +1 | `ares/n64/cpu/dcache.cpp:61`, `:90` |
| D-cache miss | +40, after a +40 writeback if the victim is dirty, serially | `ares/n64/cpu/dcache.cpp:6-19`, `:53-58`, `:82-87` |
| Uncached RDRAM read or write | 0 | `ares/n64/memory/bus.hpp:5`, `:50` → `ares/n64/mi/bus.hpp:2-12`, `:73-95` (no `step`) |
| RCP register read (SP, DP, MI, VI, AI, PI, RI, SI, RDRAM regs) | +20 | `ares/n64/memory/io.hpp:3`, `:8` |
| RCP register write | 0 (`DefaultWriteCycles = 0`, "not implemented until we implement the CPU write queue") | `ares/n64/memory/io.hpp:4`, `:37` |
| PI cart read | +20 (RCP) +250, ignoring the BSD registers | `ares/n64/memory/io.hpp:8`, `ares/n64/pi/bus.hpp:63` |
| PI cart read while a PI write is busy | +20 + the remaining busy time | `ares/n64/pi/bus.hpp:58-61`, `:88-91` |
| PI cart write | 0 to the CPU; IO_BUSY for 400 ticks (133.3 RCP) | `ares/n64/pi/bus.hpp:71-82` |
| PIF RAM read | +20 | `ares/n64/si/io.cpp:1-9` via `ares/n64/memory/io.hpp:8` |
| MULT/DIV family | fixed per op, e.g. DIV 37, DDIV 69 | `ares/n64/cpu/interpreter-ipu.cpp:289`, `:315` |
| FPU arithmetic | fixed per op, e.g. ADD.S 3, DIV.S 29 | `ares/n64/cpu/interpreter-fpu.cpp:470`, `:810` |
| Misaligned access exception | 1 | `ares/n64/cpu/memory.cpp:209-227` |
| Other exceptions, ERET, CACHE, MFC0/MTC0, nullified likely slot | 0 | `ares/n64/cpu/exceptions.cpp:1-30`; `ares/n64/cpu/interpreter-scc.cpp:291-306`; `ares/n64/cpu/interpreter-ipu.cpp:120`; `ares/n64/cpu/cpu.hpp:76` |

There is no pipeline state between instructions. `CPU::Pipeline` holds only PC, next PC and branch flags (`ares/n64/cpu/cpu.hpp:59-86`). No cost can depend on the next instruction, so load-use and FPU interlocks cannot be expressed.

**COUNT/COMPARE.** COUNT is kept at PClock resolution in `scc.count` (33-bit, `CountMask`, `ares/n64/cpu/cpu.hpp:36`) and read as `effectiveCount() >> 1` (`ares/n64/cpu/interpreter-scc.cpp:39`). `effectiveCount` adds the unsynced `(Thread::clock - countClock) >> 1` (`ares/n64/cpu/cpu.hpp:42-43`), so MFC0 COUNT is exact mid-window. `stepCount` raises the timer interrupt when the advance crosses COMPARE (`ares/n64/cpu/cpu.cpp:68-75`). It runs in `synchronize` (`:120`) and in `flushCount` on COUNT/COMPARE writes (`ares/n64/cpu/interpreter-scc.cpp:171-183`). A COUNT write takes effect immediately (`:173`). A Cause or Status write calls `interruptPoll` immediately (`ares/n64/cpu/interpreter-scc.cpp:216`, `:219-222`), so the next instruction can take the interrupt. Random is `random() % (32 - wired) + wired` (`ares/n64/cpu/interpreter-scc.cpp:269-272`).

**Recompiler charging.** `emitCpuStep(n)` adds to the CPU clock in memory (`ares/n64/cpu/recompiler-ipu.cpp:5-7`). Per-instruction cycles accumulate in `emitDeferredCycles` and are flushed at branches, delay slots, helper calls, internal labels and I-cache line guards (`ares/n64/cpu/recompiler.cpp:701-750`). So the base cycle is charged *after* the instruction's code, where the interpreter charges it before. Specific charge sites:

- I-cache guard only at the block's first instruction and at 32-byte line starts (`ares/n64/cpu/recompiler.cpp:721-736`). Internal entries such as JAL return addresses (`:529-533`) are reached through the entry dispatcher (`:671-679`) with no guard.
- I-cache miss slow path: inline `emitCpuStep(96)` and a raw 32-byte copy from `rdram.ram.data`, bypassing `Bus` (`ares/n64/cpu/recompiler.cpp:809-830`).
- D-cache hit inline `emitCpuStep(2)` (`ares/n64/cpu/recompiler-ipu.cpp:160-167`). Misses and uncached or MMIO accesses call the interpreter op on a slow path.
- Slow-path bookkeeping: `instructionCycles = deferredCycles - slow.deferredCycles` (`ares/n64/cpu/recompiler.cpp:614-623`) is added again in the slow path (`:838-839`) after `setupCallf` already flushed (`ares/n64/cpu/recompiler-ipu.cpp:29-36`). For DIV and FPU the op cost is added after `deferSlowPath` (`ares/n64/cpu/recompiler-ipu.cpp:1369-1370`, `ares/n64/cpu/recompiler-fpu.cpp:436-447`).
- Own FPU table: ADD.S `(5 - 1) * 2` (`ares/n64/cpu/recompiler-fpu.cpp:1075`) against the interpreter's 3 (`ares/n64/cpu/interpreter-fpu.cpp:470`).
- Branch-to-self and jump-to-self cost 64 cycles (`ares/n64/cpu/recompiler.cpp:743-748`).
- Exit checks only at conditional-branch dispatch (`ares/n64/cpu/recompiler.cpp:633-635`) and block end (`:799-800`).

The JIT budget compares `scc.compare - effectiveCount()` (COUNT half-units, 2 ticks each) with tick-based `jitClockTarget` (`ares/n64/cpu/cpu.cpp:165-170`). **[inference]** The unit mismatch makes the JIT stop at about half the remaining time to the timer, which is early and harmless.

## 3. Memory bus dispatch

`Bus::read` / `Bus::write` route by physical address (`ares/n64/memory/bus.hpp:1-68`):

- `0x0000_0000-0x03FF_FFFF` → `MI::readRdram` / `writeRdram` (`ares/n64/memory/bus.hpp:5`, `:50`). RDRAM data goes straight to `rdram.ram.read/write` with no `step` (`ares/n64/mi/bus.hpp:2-12`, `:73-95`). Register space goes through `rdram.read/write`, which is `Memory::RCP` and so costs 20 on read (`ares/n64/rdram/rdram.hpp:5`, `ares/n64/memory/io.hpp:7-8`).
- RSP, RDP, MI, VI, AI, PI, RI, SI registers → each device's `Memory::RCP<T>::read/write`, which charges `DefaultReadCycles = 20` CPU cycles on read and 0 on write to the *calling* thread (`ares/n64/memory/io.hpp:1-59`).
- Cart and PIF windows → PI and SI (`ares/n64/memory/bus.hpp:19-21`).
- Cache line fills and writebacks use `Bus::readBurst/writeBurst` → `MI::readRdramBurst/writeRdramBurst` → `rdram.ram.readBurst/writeBurst` (`ares/n64/memory/bus.hpp:26-89`, `ares/n64/mi/bus.hpp:97-128`). The burst itself costs nothing; the caller (`DataCache::Line::fill`, `ICache::Line::fill`) charges the constant first.

DMA engines do not use `Bus` at all. They call `rdram.ram.read/write` directly: SP DMA (`ares/n64/rsp/dma.cpp:33-57`), PI (`ares/n64/pi/dma.cpp:11`, `:50-55`), AI (`ares/n64/ai/ai.cpp:40`), RDP command fetch (`ares/n64/vulkan/vulkan.cpp:106-107`), VI software scanout (`ares/n64/vi/vi.cpp:200`, `:218`).

`rdram.ram.read/write` (`ares/n64/rdram/rdram.hpp:41-57`, `:84-97`) charges nothing. It counts bytes per `RBusDevice` only when `system.homebrewMode` is set (`:53-56`). `RBusDevice::DP_DRAW` is defined (`ares/n64/n64.hpp:115`) but no producer uses it; only the bench readout `ares/n64/cpu/emux.cpp:179-181` reads it.

**Contention.** None. There is no arbitration, no bank or row state, no refresh, no write buffer. RI registers are stored and read back only (`ares/n64/ri/io.cpp:78-81`). `RI::checkRefresh` prints a warning in homebrew mode if refresh is disabled and does nothing else (`ares/n64/ri/ri.cpp:27-34`).

## 4. RSP

**Step.** `RSP::main` (`ares/n64/rsp/rsp.cpp:33-47`) loops while its clock is negative. If halted it steps 128 ticks. Otherwise it runs `instruction()` and then `dmaStep(elapsed)`. The interpreter issues one or two instructions and charges `pipeline.clocks` (`:49-86`). `Pipeline::end` adds 3 ticks per issue and `stall()` 3 per bubble (`ares/n64/rsp/rsp.hpp:204-223`). Stalls come from GPR read-after-write (2 or 1 bubbles), VR read-after-write (3, 2, 1), and a store after a load in the previous slot (`ares/n64/rsp/rsp.hpp:236-260`). The recompiler evaluates the same model at compile time and keys blocks by `pipeline.hash()` (`ares/n64/rsp/rsp.hpp:187-196`, `ares/n64/rsp/recompiler.cpp:310`).

**DMA.** A length write latches the request and calls `dmaTransferStart` (`ares/n64/rsp/io.cpp:95-118`). The start sets `dma.clock = (rsp.clock - thread.clock) - (length + 8) / 8 * 3` (`ares/n64/rsp/dma.cpp:1-3`, `:14-22`). That is 3 ticks = 1 RCP cycle per 8 bytes per row. `dmaStep` adds elapsed RSP ticks and, once `dma.clock >= 0`, copies one whole row at once (`ares/n64/rsp/dma.cpp:5-12`, `:24-62`). The next row is queued with `dma.clock` reset to `-rowClocks` (`:64-67`), which drops any overshoot. **[inference]** So each row's completion rounds up to the RSP's step size: 128 ticks while halted, one issue pair or one recompiled block while running.

**Sync with the CPU.** None beyond the lag window. RSP status is read and written through `RSP::ioRead/ioWrite` (`ares/n64/rsp/io.cpp:9-165`). SP_STATUS writes halt, unhalt and raise or lower the SP interrupt immediately at the writer's time (`:120-148`). BREAK sets halted and broken and raises the SP interrupt if `interruptOnBreak` (`ares/n64/rsp/interpreter-ipu.cpp:54-58`). SP_PC reads return `random()` while the RSP runs (`ares/n64/rsp/io.cpp:173-177`).

**RSP access to the RDP.** RSP `MFC0/MTC0` with `rd & 8` call `rdp.readWord/writeWord` directly, with the RSP as `thread` (`ares/n64/rsp/interpreter-scc.cpp:1-11`). No `Memory::RCP` cost and no sync.

## 5. RDP

**Registers.** `DPC_START` latches only if `startValid` is clear and always sets `startValid` (`ares/n64/rdp/io.cpp:72-76`). `DPC_END` sets `end`, copies `start` into `current` if `startValid`, clears `startValid`, and calls `flushCommands()` (`:78-87`). `flushCommands` sets `bufferBusy`, `pipeBusy`, `startGclk`, calls `render()` if `end > current`, clears `bufferBusy` and sets `ready` (`:195-209`). All of this happens inside the writer's instruction, at zero emulated cost.

**DPC_STATUS** (`ares/n64/rdp/io.cpp:23-37`): bit 8 (DMA_BUSY) is hard-wired 0. Bit 9 reads `endValid`, which nothing ever sets (declared at `ares/n64/rdp/rdp.hpp:88`). The `DPC_TMEM_BUSY` branch tests `data == 7` instead of `address == 7`, so it never runs (`ares/n64/rdp/io.cpp:58`). `DPC_BUSY` and `DPC_PIPE_BUSY` return the busy flags, not cycle counts (`:46-56`). `DPC_CLOCK` = `command.clock - (rdp.clock - thread.clock) / 3`, which is scheduler time in RCP cycles (`:39-44`).

**Processing paths.** `RDP::render()` (`ares/n64/rdp/render.cpp:47-553`):

- With Vulkan enabled it calls `Vulkan::render()` and returns (`:48-53`). `Vulkan::render` copies `current..end` from RDRAM (as `RBusDevice::DP_DMA`) or DMEM into a host buffer, enqueues whole commands to paraLLEl-RDP, and sets `command.current = command.end` (`ares/n64/vulkan/vulkan.cpp:82-148`). On SyncFull it blocks the host on the GPU timeline, then calls `rdp.syncFull()` (`:136-139`). A trailing partial command stays buffered while `current` is set to `end` (`:126-129`). If the host buffer would exceed 0x8000 64-bit words it returns without consuming anything (`:102`).
- Without Vulkan the loop fetches and decodes every command (`ares/n64/rdp/render.cpp:192-553`) into state structs, but every primitive, sync and load handler is empty (`:557-614`, `:651-665`). There is no software rasterizer, so the CPU path produces no pixels.
- `syncFull()` raises `MI::IRQ::DP` and clears `bufferBusy` and `pipeBusy` (`ares/n64/rdp/render.cpp:617-624`). In both paths it runs inside the `DPC_END` write, so the DP interrupt lands at the writer's time (the RSP for MM).

**Threading.** paraLLEl-RDP runs on the GPU and its own host worker threads; ares constructs it over `rdram.ram.data` directly with `COMMAND_PROCESSOR_FLAG_HOST_VISIBLE_HIDDEN_RDRAM_BIT` (`ares/n64/vulkan/vulkan.cpp:54`, `:237`, `:252`). The only wait in the command path is at SyncFull (`:136-139`).

**RDP thread.** `RDP::main` only advances `command.clock` in one-second quanta (`ares/n64/rdp/rdp.cpp:29-35`). Othermode bits that decide timing are decoded and stored but unused, including `atomicPrimitive`, `imageRead`, `zCompare`, `zUpdate` (`ares/n64/rdp/render.cpp:363`, `:395-402`). DPS test registers store raw data without any span RAM behind them (`ares/n64/rdp/io.cpp:126-193`).

## 6. DMA engines and VI scanout

| Engine | When data moves | When it completes / IRQ | Cost charged | Where |
|---|---|---|---|---|
| SP DMA | Per row, when the row's time has elapsed | `dma.busy` clears after the last row; no SP interrupt (DMA has none) | 1 RCP cycle per 8 B, no setup, no contention | `ares/n64/rsp/dma.cpp:14-73` |
| PI DMA cart→RDRAM | All at once in the `PI_WRITE_LENGTH` write | `Queue::PI_DMA_Write` after `dmaDuration`, then `dmaFinished` clears busy and raises PI | `(14+LAT+1)·pages + (PWD+1+RLS+1)·len/2 + 28·numBuffers + 1·partialBytes` RCP | `ares/n64/pi/io.cpp:114-121`, `ares/n64/pi/dma.cpp:16-112` |
| PI DMA RDRAM→cart | All at once in the `PI_READ_LENGTH` write | Same queue path | Same formula | `ares/n64/pi/io.cpp:105-112`, `ares/n64/pi/dma.cpp:1-14` |
| SI DMA | At completion (`pif.dmaRead/dmaWrite` inside the queue callback) | `Queue::SI_DMA_Read` after `pif.estimateTiming()` RCP; `SI_DMA_Write` after 4065 RCP | Fixed constants and a per-command estimate | `ares/n64/si/io.cpp:80-105`, `ares/n64/si/dma.cpp:1-17`, `ares/n64/pif/hle.cpp:195-240` |
| SI/PIF bus write | Immediately | `SI_BUS_Write` after 2150 RCP | 0 to the CPU | `ares/n64/si/io.cpp:58-69` |
| AI | One 4-byte read per sample in `AI::sample` | IRQ when a buffer is queued while idle, and when the next buffer starts | No bus time | `ares/n64/ai/ai.cpp:27-65`, `ares/n64/ai/io.cpp:36-45` |
| VI | Vulkan: paraLLEl reads RDRAM at `vstart` via `scanoutAsync`. Software: `VI::refresh` reads the whole frame on the host side | VI IRQ when `vcounter` matches `coincidence` | No bus time | `ares/n64/vi/vi.cpp:77-136`, `:138-226` |

The VI raises its interrupt and calls `scanoutAsync` at line granularity inside `VI::main` (`ares/n64/vi/vi.cpp:88-118`). The VI_CONTROL read drops bit 16 (dedither) (`ares/n64/vi/io.cpp:5-16`). AI power-on rate is 44,100 Hz (`ares/n64/ai/ai.cpp:76-78`).

## 7. Determinism hazards visible in code

| Hazard | Where | Effect on emulated time |
|---|---|---|
| Host entropy seeds `random` unless the "Deterministic Entropy" setting is on | `ares/n64/system/system.cpp:434-440`, setting parsed at `:38` | Every consumer below differs run to run by default |
| RDRAM current-calibration thresholds `ccLow`/`ccHigh` are random at power-on | `ares/n64/rdram/rdram.cpp:43-44`; read decay `degrade()` uses `random()` per bit at `:195-207` | **[inference]** IPL3's calibration loop can take a different number of iterations, so boot timing and RDRAM read values before calibration vary |
| CP0 Random is `random()` | `ares/n64/cpu/interpreter-scc.cpp:269-272` | TLB writes with TLBWR land in different slots; code reading Random diverges |
| SP_PC read while the RSP runs returns `random()` | `ares/n64/rsp/io.cpp:173-177` | Any code that polls SP_PC diverges |
| paraLLEl writes RDRAM on the GPU, and ares waits only at SyncFull | `ares/n64/vulkan/vulkan.cpp:54`, `:133`, `:136-139` | **[inference]** A CPU or RSP read of a color or Z buffer between a `DPC_END` and the next SyncFull sees whatever the GPU has finished, which depends on host timing |
| paraLLEl crash flag is set asynchronously | `ares/n64/vulkan/vulkan.cpp:27-34`, `:50-51` | When `crash()` triggers depends on GPU progress |
| VI scanout waits on the UI thread | `ares/n64/vulkan/vulkan.cpp:160-168`, `:217-224` | Host wall time only; no emulated-state effect found |
| Wall clock | `ares/n64/cartridge/rtc.cpp:13-33`, `ares/n64/dd/rtc.cpp:14-45`, `ares/n64/controller/gamepad/bio-sensor.cpp:3,16` | Not used by MM (no RTC, no DD) |
| Connected controllers change SI read duration | `ares/n64/pif/hle.cpp:195-240` | Deterministic for a fixed controller setup |
| Window-order effects: RSP, RDP and queue order within a sync window | `ares/n64/cpu/cpu.cpp:95-118` | Deterministic for a fixed CPU core and budget, but the recompiler and interpreter see different orders |
| `Thread::clock` has no initializer | `ares/n64/n64.hpp:75` | Reset on power by every device (`ares/n64/cpu/cpu.cpp:207`, `ares/n64/rsp/rsp.cpp:122`, `ares/n64/rdp/rdp.cpp:38`, `ares/n64/vi/vi.cpp:229`, `ares/n64/ai/ai.cpp:72`); no live hazard found |
| Memory power-on contents | `ares/n64/memory/lsb/writable.hpp:28-32` fills 0 | Deterministic (not hardware-like) |

The recompiler-parity research measured up to 1.0% `game_ticks` difference between two identical interpreter runs (South Clock Town). Its cause was not found. The random seeding above is the first candidate to rule out; whether the bench enables "Deterministic Entropy" was not checked here.

## 8. Decision → code site table

One row per map decision (each links its research doc). "Now" is what the code does at `59158c28a`.

| Decision | Code site(s) the build will change | What is there now |
|---|---|---|
| [#12 RDP pixel-timing coupling](https://github.com/wScottSh/ares/blob/research/rdp-pixel-timing-coupling/docs/research/rdp-pixel-timing-coupling.md) | `ares/n64/rdp/render.cpp:557-614` (primitive handlers), `ares/n64/vulkan/vulkan.cpp:121-148` (enqueue), vendored `ares/n64/vulkan/parallel-rdp/parallel-rdp/shaders/depth_blend.comp` | Primitive handlers are empty. paraLLEl gets whole commands and returns nothing per span. No per-pixel write-enable result reaches the CPU side |
| [#3 RDP memory traffic and stalls](https://github.com/wScottSh/ares/blob/research/rdp-memory-traffic/docs/research/rdp-memory-traffic.md) | `ares/n64/rdp/rdp.cpp:29-35`, `ares/n64/rdp/render.cpp:395-402`, `ares/n64/rdp/io.cpp:28`, `ares/n64/rdram/rdram.hpp:41-97` | RDP thread only ticks `command.clock`. `IM_RD`/`Z_CMP`/`Z_UPD` decoded, unused. `startGclk` is a flag set at flush and cleared at SyncFull, not a stall. No RDRAM cost |
| [#8 RSP-RDP FIFO back-pressure](https://github.com/wScottSh/ares/blob/research/rsp-rdp-fifo/docs/research/rsp-rdp-fifo.md) | `ares/n64/rdp/io.cpp:72-87`, `:195-209`, `:33-34`, `:58`; `ares/n64/vulkan/vulkan.cpp:146`; `ares/n64/rdp/render.cpp:617-624`; `ares/n64/rsp/interpreter-scc.cpp:1-11` | `DPC_END` renders synchronously and sets `current = end`, so ucode stalls B, C, D never spin. No END_PENDING, DMA_BUSY 0, TMEM_BUSY read dead. DP IRQ at RSP time. RSP DPC reads have no sync |
| [#7 DMA engine timing](https://github.com/wScottSh/ares/blob/research/dma-timing/docs/research/dma-timing.md) | `ares/n64/rsp/dma.cpp:20`, `:67`; `ares/n64/pi/dma.cpp:72-112` (bugs at `:90-92`, `:97-99`); `ares/n64/pi/io.cpp:105-121`; `ares/n64/si/io.cpp:87`, `:104`; `ares/n64/ai/ai.cpp:35-48`; `ares/n64/vi/vi.cpp:77-136` | SP DMA 8 B/RCP with no setup. PI data lands at start, IRQ later, formula off for full edge pages and small single-page transfers. SI from systembench constants. AI and VI charge no bus time |
| [#5 nemu64-test timing failures](https://github.com/wScottSh/ares/blob/research/nemu64-timing-failures/docs/research/nemu64-timing-failures.md) | `ares/n64/cpu/cpu.cpp:136-185`; `ares/n64/cpu/cpu.hpp:59-86`; `ares/n64/cpu/memory.cpp:157-164`; `ares/n64/cpu/dcache.cpp:61`, `:90`; `ares/n64/cpu/exceptions.cpp:1-30`; `ares/n64/cpu/interpreter-fpu.cpp:463-1023`; `ares/n64/cpu/interpreter-scc.cpp:171-173`, `:219-222`, `:269-272`; `ares/n64/cpu/interpreter-ipu.cpp:37-40`, `:120` | One instruction at a time with a fixed cost. No stage state, so no LDI, FPU forwarding, stage-dependent exception cost, late CP0 writes or delayed interrupt sampling. Exceptions, CACHE, nullified slots cost 0. Random is a PRNG |
| [#4 RDRAM, RI and bus arbitration](https://github.com/wScottSh/ares/blob/research/rdram-bus-arbitration/docs/research/rdram-bus-arbitration.md) | `ares/n64/memory/bus.hpp:1-89`; `ares/n64/mi/bus.hpp:1-128`; `ares/n64/rdram/rdram.hpp:41-181`; `ares/n64/ri/io.cpp:78-81`; `ares/n64/ri/ri.cpp:27-34`; `ares/n64/cpu/cpu.cpp:83-121` | One synchronous call per access, no cost, no bank/row state, no refresh, no arbitration. RI_REFRESH stored only. DMA engines bypass `Bus` and call `rdram.ram` directly |
| [#2 RDP command and span duration](https://github.com/wScottSh/ares/blob/research/rdp-command-timing/docs/research/rdp-command-timing.md) | `ares/n64/rdp/render.cpp:192-553` (dispatch), `:557-707` (handlers), `ares/n64/rdp/rdp.cpp:29-35` | Every command costs 0. Syncs are empty. No span walk, no per-primitive overhead |
| [#6 CPU memory access costs](https://github.com/wScottSh/ares/blob/research/cpu-memory-costs/docs/research/cpu-memory-costs.md) | `ares/n64/cpu/dcache.cpp:7`, `:16`, `:61`, `:90`; `ares/n64/cpu/cpu.hpp:209`; `ares/n64/memory/io.hpp:3-4`; `ares/n64/mi/bus.hpp:2-12`; `ares/n64/pi/bus.hpp:63`; `ares/n64/cpu/recompiler-ipu.cpp:167`; `ares/n64/cpu/recompiler.cpp:825` | D-hit 2 total, uncached RDRAM read 1, PIF read 21, PI read 271 fixed, I-miss 49, dirty miss 81 serial, RCP read 21 |
| [#10 Recompiler timing parity](https://github.com/wScottSh/ares/blob/research/recompiler-parity/docs/research/recompiler-parity.md) | `ares/n64/cpu/recompiler.cpp:614-623`, `:721-736`, `:743-750`, `:809-830`, `:838-839`; `ares/n64/cpu/recompiler-fpu.cpp:436-447`, `:1075`; `ares/n64/cpu/recompiler-ipu.cpp:1369-1370`; `ares/n64/cpu/cpu.cpp:160-174`; `ares/n64/rsp/rsp.cpp:42-45` | Mid-line entries skip the I-cache guard. Slow paths double-charge. JIT FPU table differs. Base cycle charged after the op. Branch-to-self = 64. Inline I-fill bypasses `Bus`. Sync ≤ 4096 ticks. RSP DMA stepped per block |
| [#21 MM RDP command stream per frame](https://github.com/wScottSh/ares/blob/research/mm-rdp-stream/docs/research/mm-rdp-stream.md) | Characterization; consumed by the #8 and #3 sites. Directly relevant: `ares/n64/vulkan/vulkan.cpp:99-102` (host queue of 0x8000 64-bit words) and the bench readout `ares/n64/cpu/emux.cpp:179-181` | The ring is drained instantly, so the 1.4–2.8 ring laps per frame cost nothing |
| [#22 VI scanout fetch pattern](https://github.com/wScottSh/ares/blob/research/vi-fetch/docs/research/vi-fetch.md) | `ares/n64/vi/vi.cpp:77-136` (line loop), `ares/n64/vi/io.cpp:5-16` (VI_CONTROL read), `ares/n64/ri/ri.cpp:27-34` | VI steps per line and raises IRQs, but issues no fetch transactions. Refresh is not modeled. Bit 16 not returned |
| [#18 RDP noise generator stepping](https://github.com/wScottSh/ares/blob/research/rdp-noise/docs/research/rdp-noise.md) | Vendored `ares/n64/vulkan/parallel-rdp/parallel-rdp/shaders/noise.h:26-41`; `ares/n64/rdp/render.cpp:395-402` | Noise is a hash of x, y and primitive in the GPU shader. No LFSR, no RDP clock count to step it |
| [#24 NUS-001 clock frequencies](https://github.com/wScottSh/ares/blob/research/clocks/docs/research/clocks.md) | `ares/n64/system/system.hpp:37-38`; `ares/n64/system/system.cpp:107-114`; `ares/n64/ai/io.cpp:61-62`; `ares/n64/ai/ai.cpp:76-78`; `ares/n64/vi/vi.cpp:10-14` | Ratios correct (187.5 MHz master, VCLK 48,681,818 with exact remainder). AI period double-truncated |
| [#20 Span RAM buffering and write-back overlap](https://github.com/wScottSh/ares/blob/research/span-ram/docs/research/span-ram.md) | `ares/n64/rdp/io.cpp:126-193` (DPS test regs); new RDP memory-interface code | DPS_BUFTEST_DATA is a plain array. No span RAM, no ping-pong, no prefetch |
| [#17 RDP write granularity](https://github.com/wScottSh/ares/blob/research/rdp-write-granularity/docs/research/rdp-write-granularity.md) | Same as #12: `ares/n64/vulkan/vulkan.cpp:121-148`, vendored `depth_blend.comp`; future RDP memory interface | No write transactions exist to count |
| [#26 VR4300 dirty miss and write buffer](https://github.com/wScottSh/ares/blob/research/vr4300-wb/docs/research/vr4300-wb.md) | `ares/n64/cpu/dcache.cpp:6-19`, `:53-58`, `:82-87`; `ares/n64/memory/io.hpp:4`, `:37`; `ares/n64/cpu/memory.cpp:129-132`, `:186-194`; `ares/n64/mi/bus.hpp:73-95`; `ares/n64/pi/bus.hpp:58-61`, `:71-82` | Writeback then fill, 40 + 40, synchronous. Writes free and immediate. No buffer, so no stall on a 5th store and no read waiting behind writes |
| [#19 1-primitive mode cost](https://github.com/wScottSh/ares/blob/research/1prim-cost/docs/research/1prim-cost.md) | `ares/n64/rdp/render.cpp:363`, `:647-649` | `atomicPrimitive` decoded and never used |

Not on the map's decision list, but on a research branch: [jgemu-dpc-probe](https://github.com/wScottSh/ares/blob/research/jgemu-dpc-probe/docs/research/jgemu-dpc-probe.md) (#25). It casts doubt on the span law and TMEM rate used by #2 and lands on the same `ares/n64/rdp/render.cpp` sites.

## Where things live

| Concern | Files |
|---|---|
| Time base, queue, device clocks | `ares/n64/n64.hpp`, `ares/n64/system/system.{hpp,cpp}`, `nall/nall/priority-queue.hpp` |
| Master loop and sync | `ares/n64/cpu/cpu.cpp` |
| CPU costs (interpreter) | `ares/n64/cpu/{memory.cpp,dcache.cpp,cpu.hpp,interpreter-ipu.cpp,interpreter-fpu.cpp,interpreter-scc.cpp,exceptions.cpp}` |
| CPU costs (recompiler) | `ares/n64/cpu/{recompiler.cpp,recompiler-ipu.cpp,recompiler-fpu.cpp}` |
| Bus dispatch | `ares/n64/memory/{bus.hpp,io.hpp}`, `ares/n64/mi/bus.hpp`, `ares/n64/pi/bus.hpp` |
| RDRAM and RI | `ares/n64/rdram/{rdram.hpp,rdram.cpp}`, `ares/n64/ri/{io.cpp,ri.cpp}` |
| RSP | `ares/n64/rsp/{rsp.cpp,rsp.hpp,dma.cpp,io.cpp,interpreter-scc.cpp,recompiler.cpp}` |
| RDP | `ares/n64/rdp/{rdp.cpp,io.cpp,render.cpp}`, `ares/n64/vulkan/vulkan.cpp`, vendored `ares/n64/vulkan/parallel-rdp/` |
| DMA engines and VI | `ares/n64/pi/{dma.cpp,io.cpp}`, `ares/n64/si/{io.cpp,dma.cpp}`, `ares/n64/pif/hle.cpp`, `ares/n64/ai/{ai.cpp,io.cpp}`, `ares/n64/vi/{vi.cpp,io.cpp}` |
| Bench counters (fork) | `ares/n64/cpu/emux.cpp`, `ares/n64/rsp/emux.cpp` |

## Gotchas

- **Two different `Thread` types.** `ares::Thread` in `ares/ares/scheduler/thread.hpp` is the cothread scheduler. The N64 core shadows it with `Nintendo64::Thread` (`ares/n64/n64.hpp:62-76`), a plain counter. Reading the generic scheduler tells you nothing about N64 time.
- **"Synchronize" does not mean "catch up before this read."** `forceSynchronize()` only shortens the recompiler's budget (`ares/n64/cpu/cpu.cpp:64-66`).
- **Costs land on the caller's clock.** `Memory::RCP::read` charges whichever `thread` is passed (`ares/n64/memory/io.hpp:7-8`). RSP accesses to DPC registers skip `Memory::RCP` entirely (`ares/n64/rsp/interpreter-scc.cpp:3-4`).
- **Queue events and RSP DMA use different offset conventions.** RSP DMA and `DPC_CLOCK` subtract the caller's offset; the queue does not (section 1).
- **The software RDP path renders nothing.** Disabling Vulkan gives a working command decoder with a black screen, not a CPU renderer (`ares/n64/rdp/render.cpp:557-624`).
- **The RDP thread steps one emulated second at a time** (`ares/n64/rdp/rdp.cpp:29-35`). Any RDP timing work replaces this loop outright.

## Three structural obstacles to the hardware-accurate timing model

1. **A CPU-master, catch-up scheduler with no shared timeline.** Devices run only inside `CPU::synchronize`, one whole window each, in a fixed order, followed by queue events (`ares/n64/cpu/cpu.cpp:83-121`). Device reads see stale state, queue events fire relative to the last sync, and the window size differs between interpreter (one instruction) and recompiler (≤ 4096 ticks). A shared RDRAM bus with per-burst arbitration (#4, #14) needs the requesters ordered by time across devices, which this loop cannot express without either syncing at every bus access or giving each transaction a timestamp.
2. **The RDP is not a device in time, and its pixels live on the GPU.** Rendering happens inside the `DPC_END` write at zero cost, `current` jumps to `end`, and the DP interrupt is raised at the writer's time (`ares/n64/rdp/io.cpp:78-87`, `ares/n64/vulkan/vulkan.cpp:146`, `ares/n64/rdp/render.cpp:617-624`). The CPU-side path has no rasterizer, and paraLLEl returns no per-span write information (#12, #17). A timed RDP needs its own clocked command fetch, span-level memory traffic and write sets, and those depend on per-pixel results that today exist only on the GPU, asynchronously.
3. **Costs are flat constants scattered across call sites and duplicated in the recompiler.** There are 55 `step()` call sites in the CPU interpreter, cache and fetch code alone (grep of `ares/n64/cpu/{interpreter*,memory,dcache,cpu}.*`), parallel tables in `recompiler-*.cpp`, and no RDRAM cost anywhere (`ares/n64/mi/bus.hpp:2-12`, `ares/n64/rdram/rdram.hpp:41-57`). There is no stage state for interlocks (`ares/n64/cpu/cpu.hpp:59-86`) and no write buffer (`ares/n64/memory/io.hpp:4`). The map's rule that the recompiler survives only with bit-identical timing needs these costs computed in one shared place, at one consistent point in each instruction.
