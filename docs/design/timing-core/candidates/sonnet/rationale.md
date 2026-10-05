# Timing core architecture (candidate sonnet)

Map: wScottSh/ares#1. Design tickets covered: #9, #13, #14, #15, #27, #28. Behaviors plugged in: #2 #3 #4 #5 #6 #7 #8 #10 #12 #17 #18 #19 #20 #21 #22 #24 #26.
Grounding: `origin/research/ares-timing-architecture` (file:line citations below are from it). Sketch: `sketch/`. Build order: `plan.md`.

## Problem

Today the N64 core has one master (the CPU) and lagging devices. `CPU::synchronize` (cpu/cpu.cpp:83-121) subtracts the CPU's elapsed ticks from every device, runs each device's whole window in a fixed order, then the event queue. Nothing charges RDRAM time, nothing arbitrates, the RDP renders inside the `DPC_END` write at zero cost on the GPU, and every cost is a flat constant at one of 55 call sites with a second copy in the recompiler. Three structural obstacles from the grounding doc decide the shape.

1. No shared timeline. Who wins the bus is decided by the order of `main()` calls and the window size, which differs between the interpreter (one instruction) and the recompiler (up to 4096 ticks).
2. The RDP has no time and its pixels live on an asynchronous GPU that returns no per-span write information (#12, #17).
3. Costs are scattered constants, duplicated, with no stage state (#5) and no write buffer (#26).

Hard constraints from the map that the design must honor: accuracy is the only goal, the timing model is always on, the interpreter is the timing reference and the recompiler survives only if bit-identical, timing is bit-deterministic with no host clock or GPU-thread input, 600 MM frames (10 s emulated) run in at most 2 min on this machine.

The budget is looser than it first looks. 10 s emulated in 120 s host is 12x slower than real time, so about 128 ns of host time per emulated CPU cycle. That changes which options are affordable (a software RDP, lockstep scheduling) and makes the CPU recompiler the wrong thing to protect.

## Usage (caller's view)

The consumers are device authors, the CPU/RSP cores, the test harness and the calibration run. Three call sites show the whole surface.

**A device that needs RDRAM (the AI, as written in the new core).**

```cpp
auto Ai::advance(Limit limit) -> void {
  while(Agent::next() < limit.t) {
    req = {.client = Client::Ai, .dir = Dir::Read, .paddr = dma.addr, .bytes = 8,
           .arrival = nextSampleTick, .data = fifo.slot(), .done = this};
    channel.submit(req);               //no decisions here; the channel decides when the timeline reaches it
    nextSampleTick = nextSampleTick + dacPeriod();   //exact: ViClock rational
  }
}
auto Ai::onBus(const Request&, Tick done) -> void { fifo.push(done); }
```

The AI never reads `rdram.ram` and never calls `step()`. Time is a `Tick` the device owns or receives.

**The CPU stepping an instruction** (full pseudocode in `sketch/timing/cpu-pipe.hpp`).

```cpp
auto info = opTable[decode(inst)];
auto plan = pipe.plan(info, operands, fetchReady);        //pure
if(plan.firstSharedTouch > limit.t) { parkUntil = plan.firstSharedTouch; return; }   //others act first
pipe.commit(info, plan);                                   //the one cost function; no step() anywhere else
execute(inst);                                             //architectural effect
```

A cache hit never reaches `limit`. A miss, an uncached access, an MMIO access or a CACHE op does, so it is ordered against every other agent by timestamp.

**Verification and calibration.**

```
tools/timing/determinism.sh mm.z64 600        # two runs, varied host conditions, per-frame trace hash must match
build/ares --timing-overlay calib-nus001.tsv  # (id, value, source) rows override params.def; header goes into the savestate
```

`params.def` rows carry `ref` and `verify`. A build lint fails a row with no ref or a `verify` id that is not in `tests/timing/manifest.tsv`. The spec table (`docs/timing/parameters.md`) is generated from `params.def`, so spec and code cannot drift.

## Shape

Data structures first. Five types carry the whole model.

| Type | What it is | Why it is the right unit |
|---|---|---|
| `Tick` | s64 at 750 MHz. Strong type, with `Pclk`/`Rclk`/`Tc` as distinct types | RDRAM tc is 3 ticks, RCP 12, PClock 8, COUNT 16. The old 187.5 MHz base cannot hold a tc. VCLK is the rational 5500/357 ticks, so VI/AI are exact on every host. |
| `Agent` | `next()` and `advance(limit)`. CPU, RSP, RDP, bus, SP DMA, VI, AI, PI, SI, MI | One scheduling concept replaces `Thread::clock`, `queue`, `CPU::synchronize` and the JIT budget. |
| `Request` | One atomic RDRAM burst with a timestamp, a client, a payload and a completion | The unit the research says the hardware arbitrates. It is also the only way a timed client touches RDRAM. |
| `Bank`/`BankSet` + `busCost` | 8 open rows with dirty bits and a pure cost function | Cost is testable against the datasheet table without a running machine. |
| `PipeState` + `Pipe::plan/commit` | Stage times, scoreboard, store visibility | One cost function for every instruction. |

### Decision 1. Scheduler and shared time (#9, #14): earliest-timestamp-first, no quantum

The agent with the smallest `(next(), id)` acts. Agents are state machines advanced by a plain call, not coroutines. The CPU and RSP interpreters have a pure plan phase and park themselves at the tick of their first shared touch when other agents must act first.

Why this and not a window. Exact contention ordering needs the channel to decide at time T only after every request with `arrival <= T` is present. The timeline guarantees that by construction, because the channel is never advanced while another agent has `next() < T`. Nothing depends on how often anything syncs, because nothing syncs on a period. A test proves it: `Timeline::maxActionsPerAdvance = 1` and `= 0` must give equal trace hashes.

What stays cheap. Cache hits, ALU work, VU work and DMEM access with no DMA in flight touch no shared state, so they do not park. The hot path is a CPU/RSP pair loop with no heap. Two agents that both run continuously alternate at instruction granularity, about 3 ns per step (budgeted, not measured).

Cross-agent effects are all `Request`s or timeline events. MMIO reads and writes ride the same CPU port, serviced at the target's service tick. This is what removes "stale device state between syncs" and "queue events fire early" (grounding doc section 1), and it makes interrupt timing a pipeline property: an interrupt asserted at tick `a` is taken at instruction `i` iff `a <= i.ex`.

COUNT is a pure function of the tick. COMPARE is one timeline event at the exact tick. CP0 Random is also a pure function of the tick (decrement per PClock, wrap at Wired), which removes the PRNG.

Principles: foundational-thinking (one time type, one request type before any logic), model-the-domain (the bus is a typed queue plus a pure cost function, not scattered `step()`), separate-before-serializing-shared-state (each agent owns its state; sharing happens only through timestamped requests).

### Decision 2. The bus model (#4, #14): a lockstep transaction timeline

`Channel` is an Agent. Clients `submit` timestamped `Request`s. At each decision tick it picks among queue heads with `arrival <= T` by `ArbPolicy`, applies the payload at the grant (so read-after-write order equals channel order), updates the bank, sets `freeAt`, and posts a completion event. It also owns refresh (one broadcast per VI HSYNC, holdoff 52 or 54 rclk).

Cost is `busCost(dir, bytes, bank, row, params) -> {dataEnd, occupied, bankAfter}`, derived from the NEC datasheet at the IPL3 delays (read hit 10 tc + 4 tc/octbyte, write hit 4, retry 22 clean or 30 dirty, gaps 2/4). A unit test pins it to the "derived per-transaction wire time" table in the research doc.

Client latency outside the channel (SysAD, MI, RAC pipeline) is separate and uncontended. It is derived, not stored: `overhead = measured total - wire time`. Uncached word 32 pclk (nemu64-test) minus the 14 tc wire time leaves about 71 tc. This keeps measured totals true in the uncontended case and lets contention add on top, as research row B9 asks. The 32 vs 36 pclk bank-sharing difference must then emerge from the model (a row miss from the VI's reopened row). If it does not, that is a calibration finding, not a reason to add a constant.

Requesters carried: CPU (I fill 32 B, D fill 16 B, uncached 8 B, write buffer drain, dirty victim), SP DMA, DP command fetch, DP memory (span reads, span write runs, TMEM loads, fill), VI, AI, PI, SI, Refresh.

Arbitration is the one parameter with no source. The default is stated and swappable. `ArbPolicy::realtimeFirst()` ranks Refresh > VI > AI > CPU > SI > PI > SP DMA > DP command > DP memory. Reasoning: the VI is the only hard real-time reader with a small buffer, the CPU stalls the machine on a miss, bulk engines buffer. `ArbPolicy::mister()` is kept as a comparison preset. The policy is a plain value in `params.def` (`arb.preset`, `arb.maxConsecutive`), so calibration #16 changes it with an overlay, no code change. A latency-sweep ROM (CPU uncached-load latency while each DMA client saturates, singly and in pairs) is the experiment that fits it; it is listed as `HW-ONLY:arb-latency-sweep`.

Burst chaining is exact: when the same client has the next request queued and `Timeline::horizonFor(channel) >= freeAt`, the channel decides again without returning to the scheduler.

The channel is the single door. `Rdram::ram` data accessors become private to the channel, debugger and loader. A device that tried to read RDRAM directly would not compile. That removes today's "DMA engines bypass `Bus`" and prevents the next one.

Principles: boundary-discipline (one boundary, pure cost inside), model-the-domain, encode-lessons-in-structure through the compile-time door instead of a convention.

### Decision 3. The CPU timing seam (#15, #5, #6, #26, #10): stage-time recurrence in the interpreter; drop the recompiler from the timing path

`Pipe::plan/commit` computes the time each instruction enters IC, RF, EX, DC, WB from the previous instruction's stage times, a scoreboard of operand-ready times, and resource-busy times (mul/div, FPU). For an in-order scalar pipeline this recurrence equals a cycle-by-cycle stage simulation, evaluated once per instruction. Everything the 924 nemu64-test failures need falls out as comparisons of stage times, not special cases.

| nemu64 cluster | Mechanism in the recurrence |
|---|---|
| C1 exceptions (439) | `Pipe::raise(stage)` charges the refill cost for the stage that detected it (5 decode, 6 EX/DC, 7 FPU unimplemented, plus the op's own latency for FPU) |
| C2 cached hit +1 (204) | D hit has no extra cost. LDI is `readyAt(load) > ex(consumer)` |
| C3 FPU operand latency (172) | `fpuLatency(op, a, b)`, pure, 2 clocks for trivial operands |
| C4 FPU dependency (50) | scoreboard `fprReady` with the forwarding bubble |
| C5 C9 C10 CP0 (26) | `cp0Ready`, `cpu.mtc0SlowRegs`, `cpu.mfc0Bubble`, CACHE op rows |
| C6 C7 uncached, miss (21) | bus port, not constants |
| C8 likely-branch bubble (10) | `nullified` flag consumes one slot |
| C11 Random (3) | pure function of tick |
| cycle group: self-modifying code (7) | `StoreVisibility`: a fetch before a store's DC/WB sees the old bytes |
| interrupt sampled one instruction late | `interruptTakenBefore(assertedAt)` against `ex` |

The write buffer is four entries with weights (a line writeback takes two). Reads queue behind older writes on the CPU port (R4300i flush buffer). A dirty miss fills first, then queues the victim write (NEC 12.5, R4300i datasheet; this rejects MiSTer's order). The 5th-store policy is one enum because the two sources conflict and only burst shape differs.

Recompiler decision: drop the CPU recompiler. Reasons, in order.

1. The cost of a bit-identical JIT is one `Pipe::plan/commit` call per instruction, because costs depend on operand values (FPU), cache state and the previous instruction. That is the timing work that dominates; a JIT keeps only decode and dispatch savings, which I estimate at 20 to 30 percent of CPU time (inferred, not measured).
2. A JIT block cannot park mid-block at a shared touch without a retry protocol for compiled code. The seven divergences in the recompiler-parity doc (I-guard at mid-line entries, slow-path double charge, FPU tables, charge order, branch-to-self 64, CACHE re-guard, sync granularity) would each become a permanent obligation.
3. Subtract before add. Deleting `recompiler*.cpp`, `Accuracy::CPU::JitInterleaving`, `jitClockTarget` and `forceSynchronize` removes the unit mismatch and the double-charging bugs instead of fixing them.

Re-admission gate: if the budget measurement in the Cost section fails after the RDP and bus land, a JIT returns as an eligibility-gated block cache that calls the same `plan/commit` and must pass the same trace-hash test against the interpreter. Nothing in the seam prevents it. I do not build it speculatively.

The RSP recompiler stays (RSP timing is already static per block and keyed by `pipeline.hash()`), with the eligibility rule in Decision 5.

Principles: subtract-before-you-add, model-the-domain, make-operations-idempotent (plan is pure, so a retry after parking cannot double-charge, which is the root of the recompiler's bug B).

### Decision 4. The RDP as a time-stepped device (#13 and the RDP behaviors): a CPU-side software rasterizer, timed at span granularity

Where pixels and per-pixel results come from: a software rasterizer on the emulation thread. Reasons from the research, not taste.

- Timing needs, per span, the set of written color and Z runs (#12, #17). Only a renderer that computes `wen` per pixel can provide that. paraLLEl keeps a per-render-pass union mask and nothing per primitive or span. Surgery would need a per-(primitive, y) atomic bitmap in `depth_blend.comp`, a GPU to CPU readback before the timing model can retire the span, and a host wait per command chunk. MM sends 400 to 700 chunks per frame, so that is hundreds of thousands of GPU round trips per bench run, each also a host-timing-dependent point.
- Noise-gated writes are circular with timing (LFSRs step per RDP clock). That is only exact if pixel evaluation happens at its modeled clock on the same thread as the timeline.
- The span-buffer coherency hazard (SDK 12.2.3) is reproduced for free if the shade stage reads only prefetched bytes captured at the channel grant. That needs a CPU core with an explicit input.
- A write-predictor that runs coverage, alpha compare and Z but not color math still needs texture sampling, the combiner alpha path and a shadow Z/coverage copy. That is most of an RDP, so it is the software renderer plus a duplicate.
- Cost is affordable. At the 12x budget a software RDP at a few Mpx/s fits (see Cost).

Source of the core. Base: the MAME/angrylion-derived software RDP that ares removed in `5f9804fb6` (BSD-3-Clause; the notice was in `LICENSE` until that commit, so ISC-compatible with attribution as ares already did). Updates from angrylion-rdp-plus only after its license text is read and recorded. Fallback: port the paraLLEl shader stages to scalar C++ (MIT, already vendored). Oracle: paraLLEl in the same tree, built into the test harness only, compared per frame on non-noise modes. paraLLEl leaves the emulation path (`Vulkan::render` is deleted) and remains presentation only (VI scanout from a snapshot, upscaling). cen64/jgemu code is not imported; its DPS model and 14/12-cycle comment are used as references and as a verification source. I did not verify any of these licenses in this unit, see open question 1.

Time-stepping. `Rdp` is one Agent with three parts on one RDP clock.

- `CmdFetcher` runs the DMA from the ring into a FIFO through `Client::DpCmd` bursts. `DPC_CURRENT` is the fetch pointer and advances when a burst completes. Depth, refill threshold and burst size are `Rtl` quality params (64, 32, 22 dwords); there is no hardware source and the experiment is `HW-ONLY:dpc-current-prefetch`.
- `DpcRegs` are pure transition functions: START latches only when START_VALID is clear, END parks in END_NEXT with END_PENDING when the fetcher is busy, CURRENT promotes the pending pair. `DMA_BUSY`, `CMD_BUSY`, `PIPE_BUSY`, `TMEM_BUSY`, `START_GCLK` are computed at read time from device state. The dead `data == 7` branch (io.cpp:58) is deleted, not fixed.
- Back-pressure needs no special code. The RSP ucode polls `DPC_CURRENT`; the register moves only as fetch bursts complete; bursts complete only as the channel grants them; the FIFO has room only as the executor consumes commands. MM's stalls A to E and the 1.4 to 2.8 ring laps per frame become the physical behavior.
- `Executor` charges state setters (1), syncs (50/33/25, Full waits for all write completions), per primitive (14) and per span (12) overhead, and the atomic-primitive null cycles. It raises the DP interrupt at the tick SYNC_FULL retires on the RDP timeline, not at the RSP's last `DPC_END` write.
- `SpanEngine` per span: `core.plan` (addresses and pixel clocks from command fields only), prefetch `Request`s on `DpMem` for color if IM_RD and Z if Z_CMP, wait for the grants and for a free span RAM half, `core.shade` with prefetched bytes and the noise for the absolute RDP clock, then write-back `Request`s, one per run of written pixels (`rdp.writeGranularity`, default Runs per #17; Octbyte and Pixel are alternatives behind the same enum). A fully rejected span writes nothing. Pipeline time advances by `pixelClocks`; time spent waiting on memory is GCLK-stalled and excluded from the PIPE/TMEM counters but included in `DPC_CLOCK`.
- `Noise` is a function of the clock: three LFSRs, `state = M^n * s0` over GF(2) with cached squares, O(log n), so no per-clock stepping.
- `SpanRam` holds two color halves and two Z/TMEM halves with `freeAt` ticks, and backs the `DPS_BUFTEST` registers with real contents.

Principles: model-the-domain (the executor phase is one variant type), foundational-thinking (the per-span write set is the type that decides the architecture), boundary-discipline (the core is pure, the engine owns time), separate-before-serializing-shared-state (paraLLEl no longer writes RDRAM concurrently with the emulated machine).

### Decision 5. The RSP (#28, #10)

The existing dual-issue static pipeline model stays. What changes is the meeting with the rest of the machine.

- SP DMA becomes its own Agent. Rows are `Client::SpDma` requests; DMEM bytes move at the channel grant. The halted RSP has `next() = max` instead of polling every 128 ticks, and a CPU `SP_STATUS` write wakes it at the exact tick.
- Shared touches are enumerated (`RspTouch`): MFC0/MTC0 on SP and DPC registers, BREAK, and DMEM access while a DMA is in flight. Everything else is private.
- Recompiler policy. Blocks end before any instruction with a touch, and those instructions run through the interpreter path, so there is one implementation of every shared touch. A block may start only if `block.maxTicks <= timeline.horizonFor(rsp) - now()`. The rule is exact because both paths charge identical ticks. A block can never overrun a sync point since the sync point is the horizon, and DMA progress is event driven, which removes the two #28 candidate causes (DMA stepped once per block; main loop overshoot) by design. Which candidate caused the +1.7 percent is still unisolated; the plan has a measurement unit that confirms the fix instead of assuming it.
- Honest limit. While the CPU is runnable its `next()` sits within a few ticks of the RSP's, so the horizon is small and the RSP mostly interprets. When the CPU is blocked on a bus completion, its wake tick is known and the horizon opens. The JIT gain is therefore smaller than a quantum design would show and is measured, not assumed.

### Decision 6. Behavior parameters and verification (item 6)

`params.def` is the one table. Each row: id, unit, value, quality (Hw, Vendor, Wiki, Rtl, Fit, Infer, NoSrc), ref, verify. A generator builds `docs/timing/parameters.md` from it, so the map's "spec rows" are the code's rows. A literal-lint rejects `step(<n>)`, `Tick{<n>}` or `Tc{<n>}` outside `params.*`. `Params::overlay` loads calibration results with the source recorded in the savestate header.

Verification attaches per row through `tests/timing/manifest.tsv` (id, kind, command, pass criterion). Kinds and the behaviors they cover.

| Verifier | Covers |
|---|---|
| nemu64-test `timing`, `cycle`, `cop0hazard` (counts must fall monotonically per unit) | CPU pipe rows, exceptions, FPU, write buffer, SMC |
| n64-systembench (uncached, D miss, SP/PI/SI DMA, RCP reg, PIF) | fits, DMA rows, contention-free totals |
| unit test `bus.cost.table` | `busCost` against the derived datasheet table |
| unit test `dpc.regs` + n64-systemtest DPC probes | START/END/END_NEXT, status bits |
| snapper64 "RDP Test-Mode - Span Tri" 216 dumps | span RAM halves, write runs content |
| paraLLEl oracle diff per frame | pixel core bit-exactness (non-noise) |
| jgemu DPC probe (#25) | per-primitive and per-span overhead, TMEM rate |
| MM bench with `ARES_DPLOG` | ring laps, back-pressure, DP interrupt placement |
| `tools/timing/determinism.sh` | #27, sync independence, tie order |
| `HW-ONLY:*` | arbitration order, DPC_CURRENT prefetch depth, 5th-store policy, span read latency (calibration #16 / #25) |

A row whose verifier is `HW-ONLY` is built from its best reference, tagged, and is not an "unverified" state. It is a built behavior with a named experiment.

Principles: build-the-lever (generator, lint, trace-hash tool), encode-lessons-in-structure (the lint and the private-RDRAM door instead of prose).

### Determinism sources (#27) and what removes each

| Source (grounding doc section 7) | Removal |
|---|---|
| `Deterministic Entropy` off, RNG seeded from host | no RNG in the timing model; seed is fixed in the savestate header |
| RDRAM current-calibration thresholds random at power-on | fixed values from the IPL3 6105 init, an overlay row |
| CP0 Random PRNG | pure function of tick |
| SP_PC read while running returns `random()` | returns the actual PC at the touch tick |
| paraLLEl writes RDRAM on the GPU, wait only at SyncFull; crash flag async | not on the state path at all |
| VI scanout waits on the UI thread | presentation reads a snapshot; nothing flows back |
| Wall-clock RTC | epoch from a fixed header value |
| Window order differs between interpreter and JIT | no windows |
| The unexplained 1 percent run-to-run difference | not found by reading; the first plan unit adds the trace hash and bisects it before anything else changes |

### Interface depth

The public surface is small relative to what it hides. A device author learns `Agent::next/advance`, `Request`, `Channel::submit`, and `Completion::onBus`. Hidden behind that are bank state, retry timing, refresh, arbitration, burst splitting and the tie order. A CPU author learns `plan/commit`. The RDP exposes one pure `Core` interface; the engine hides the span buffer coherency window, GCLK stalls and noise.

## Synthesis decision

(Empty. Filled in by arena.)

## Cost estimate (item 7)

Reasoning from the workload, not a measurement. Nothing below was run.

| Component | Quantity for 10 s emulated | Host cost assumed | Estimate |
|---|---|---|---|
| CPU interpreter + `plan/commit` | about 500M instructions (937.5M cycles at IPC about 0.55) | 30 to 45 ns each | 15 to 22 s |
| RSP | about 240M issue pairs (RSP busy about 50 percent of 625M rclk) | 25 ns interpreted, 4 ns in eligible blocks, about 40 percent eligible | 4 to 7 s |
| Pair-loop scheduling | 740M steps | 3 ns | 2 s |
| Channel | about 120k requests per frame x 600 = 72M (CPU misses about 65k, RDP spans about 40k, SP DMA 5k, VI 3.5k, ring fetch 3k per frame) | 120 to 200 ns each including payload copy | 9 to 14 s |
| Software RDP | about 135M pixel evaluations (about 225k per frame, inferred from 136 to 273 KB of commands and the 1/2 to 2/3 stall fraction) | 100 to 300 ns each | 14 to 40 s |
| VI, AI, PIF, misc | | | under 1 s |
| Trace hash (verification runs only) | 600 x 8 MiB RDRAM | about 5 GB/s | about 1 s |

Nominal total about 60 s, plausible range 35 to 110 s, so the nominal margin to the 120 s limit is about 2x and the upper range has none. The software RDP and the CPU `plan/commit` cost carry most of the uncertainty.

Levers if the measurement fails, in order of expected gain and ease.

1. Deterministic span-parallel shading. `shade` is independent across spans once each span's prefetch is granted. Workers compute `WriteSet`s ahead; the timeline consumes them in span order. Output is bit-identical by construction.
2. SIMD in the pixel core and a fast path for fill and copy, which are 64 bit per clock and need no per-pixel evaluation beyond the write set.
3. Exact burst chaining and RDP span-run coalescing in the channel (already designed).
4. A gated CPU block cache (re-admission gate in Decision 3).

What must be measured first. (a) ns per pixel of the restored MAME/angrylion core on a dumped MM RDP stream (`ARES_DPLOG` exists). (b) ns per instruction of a `plan/commit` prototype inside the current interpreter. (c) real requests per frame by counting in a prototype `Channel`. (d) ns per step of the CPU/RSP pair loop. (e) the current baseline: the interpreter already synchronizes every instruction, so `bench.py` on the fork gives the real cost of "lockstep" today, which is the #9 measurement.

## Tradeoffs accepted

- We accept losing GPU rendering on the emulation path (and with it upscaling as a side effect of rendering) in exchange for per-span write sets, exact noise, deterministic state and a coherency hazard that falls out of the structure. Presentation keeps paraLLEl.
- We accept a software RDP at a few Mpx/s because the budget is 12x slower than real time. If it measures slower than about 3 Mpx/s the budget fails and lever 1 is mandatory.
- We accept instruction-granularity alternation of CPU and RSP in exchange for exactness. A lookahead quantum would be faster and would reintroduce a window; it is allowed only as a Params row with a hardware-derived minimum cross-agent latency, default 0.
- We accept dropping the CPU recompiler from the timing path in exchange for one cost function and fewer places for timing to diverge. The re-admission gate exists.
- We accept a stage-time recurrence instead of a per-cycle pipeline simulation. If a hardware behavior needs intra-instruction stage interaction the recurrence cannot express (a multi-cycle stall that changes what an older instruction does), the model gets one explicit rule for it. The nemu64 clusters I mapped all fit.
- We accept shipping a stated arbitration default with no source. It is parameterized and the experiment is named.
- We accept a 750 MHz tick and 4x larger numbers than today for exact tc arithmetic.
- `Rdram` direct access being private looks heavy-handed. It is the point.

## Alternatives considered

| Alternative | Why it lost |
|---|---|
| **Windowed occupancy** (devices run ahead, bus keeps `busyUntil`, contention approximated within a window) | Exactness depends on window size, which is the thing the brief forbids. A request that arrives earlier than one already granted cannot be fixed afterward. |
| **Coroutine per agent** (switch at every shared touch) | Works, but needs a stack switch mid-instruction, forces the JIT to yield from compiled frames, and costs about 20 to 50 ns per touch times 100M touches. Plan-then-park gets the same ordering with a function return. |
| **Optimistic execution with rollback (time warp)** | Needs state snapshots of the CPU, caches, DMEM and device registers, and a rollback of side effects. Large, and rollback bugs are nondeterminism. |
| **Quantum + retroactive reordering of bus requests** | A request already satisfied has already changed CPU state. Reordering after the fact is rollback again. |
| **paraLLEl + per-span counters + readback** (the "extend paraLLEl" option) | Shader surgery (per-(primitive, y) atomic write bitmap), a synchronous GPU round trip per command chunk, GPU threads on the timing path, inexact noise. Violates the determinism constraint unless every chunk blocks the host, and then the cost is hundreds of thousands of GPU waits per run. |
| **CPU write-predictor next to paraLLEl** | Needs texture sampling, combiner alpha, Z and coverage shadow state kept coherent with every CPU and DMA write. That is a second RDP. |
| **Port cen64 / jgemu RDP** | License not verified; its value here is the DPS model and a measured overhead comment, which I use as references. |
| **Per-cycle VR4300 stage simulation (cen64 style)** | Equivalent output, more work per instruction and a second table of stage behaviors to keep consistent with the recompiler-free interpreter. The recurrence reaches the same times in one evaluation. |
| **Scoreboard + exception table only (extend ares)** | Misses SMC fetch ordering and interrupt sampling stage, which the research already flags as real stages (#15). Each would be a special case. |
| **Fix the three CPU JIT bugs and keep it** | Fixes today's divergence, not the structural one (per-event cost functions, parking at shared touches, order of charge). Every later timing unit would be written twice. |

## Open questions and risks

1. Which license text governs the angrylion-rdp-plus code, and does the restored MAME-era core have bit-exact parity with it on MM? Is a clean port of the paraLLEl shader stages the safer base?
2. Does the software RDP reach 3 Mpx/s on the real MM stream? Everything in the budget leans on it.
3. Is instruction-granularity CPU/RSP alternation as cheap as 3 ns per step once cache and pipe state are in the loop? If not, is a hardware-derived minimum cross-agent latency available as a lookahead?
4. Do the jgemu `14 per primitive + 12 per span` numbers already include span-flush memory time? If yes, charging them as compute and also modeling the write-back double counts. The probe (#25) data needs to be split before `rdp.primOverhead` and `rdp.spanOverhead` are final.
5. Do the RDP noise LFSRs step during RDRAM stalls? Inferred yes. One boolean; the answer changes MM only in the two full-screen noise texrects.
6. Can the 32 vs 36 pclk uncached-load difference (VI front buffer bank) emerge from the model, or does it need a client-overhead term that depends on row state?
7. Interrupt propagation latency MI to CPU (`mi.propagate`) has no source. Default 1 PClock; the effect shows only in nemu64 `cop0hazard`-style tests.
8. Does 8 B per AI request and 128 B per VI segment match hardware closely enough? Both are inferred; the contention effect is small (AI 0.026 percent of peak, VI 6.5 to 9 percent).
9. Is it acceptable for the first deliverable to lose the GPU renderer for interactive play (frame rate far below real time on the software RDP)? The map says accuracy only, but the coordinator may want a presentation-only fast mode later.
10. `Rdram` hidden bits already exist (`rdram/hidden.hpp`); is their layout identical to what the software core needs per pixel or does the core need its own coverage view?

## Next implementation step

Add the trace-hash and determinism script to the unmodified fork and run it twice on the MM bench, so the unexplained 1 percent difference becomes a located first-differing-frame before any timing code changes (plan unit U0).
