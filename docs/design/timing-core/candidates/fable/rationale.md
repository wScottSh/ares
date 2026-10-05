# Timing core for the ares N64 fork: candidate "fable"

## Problem

Every behavior on map #1 needs three things the current core does not have: one shared timeline on which RDRAM bursts from eight requesters are ordered by time, an RDP that occupies time and produces per-pixel write sets, and a CPU whose cost depends on the next instruction and on the bus. Today the CPU drags lagging device clocks forward after each step, devices run one whole window each in a fixed order, the RDP renders in zero time inside the `DPC_END` write on a GPU, and 55 scattered `step()` calls plus two recompilers hold duplicated cost tables (`ares-timing-architecture.md`, sections 1, 5, "Three structural obstacles"). The constraints that shape the answer are bit-determinism with no host-thread or GPU dependence, contention ordering independent of sync frequency (#10 input on #14), MM's ucode back-pressure through `DPC_CURRENT` (#8), per-pixel write runs reaching the bus (#12, #17), hardware noise stepping per RDP clock including stalls (#18), and a 600-frame MM run in at most 2 minutes on a Ryzen 5 9600X. The research leaves several hardware numbers unknown (arbitration priority, command FIFO depth, span read latency, noise pixel offset), so the shape must make them single, named parameters rather than code.

## Usage (caller's view)

A device author sees four things: an `Actor` to implement, a `Bus` to post bursts to, a `Scheduler` to observe other devices through, and a TSV row to add for every constant. Nothing else touches time.

A CPU uncached load, in `cpu/timing.cpp`:

```cpp
auto CpuTiming::uncachedLoad(u32 paddr, u32 size) -> MemResult {
  Tick issue = max(now, self.writeBuffer.drainedBy(now));     //reads wait behind older posted writes (vr4300-wb)
  self.actor.clock = issue;
  bus.request({&self.actor, Master::VR4300_UNCACHED, false, paddr & ~7, 8, 0, 0, issue, 0});
  scheduler.settle(issue);                                     //serves our request once every master is at >= its grant
  return {pendingGrant.data + pclk(constants.ri.overheadCpuReadPclk), true};
}
```

The RSP polling the RDP's fetch pointer (stall D of F3DZEX2, `rsp/interpreter-scc.cpp`):

```cpp
case COP0::DPC_CURRENT: return scheduler.observe(rdp.engine, rsp.actor).readWord(DPC_CURRENT);
```

The RDP span unit issuing a prefetch (`rdp/engine.cpp`):

```cpp
for(auto& burst : BurstPlan::split(span.colorAddress(xStart), span.colorBytes(), false)) {
  burst.owner = this; burst.master = Master::DP_DRAW; burst.time = clock; burst.tag = half;
  bus.request(burst); return;                                   //blocked until granted(); runUntil resumes from span.state
}
```

Adding a constant is one TSV line, `rdp.cmd_fifo_words  64  u64  <reference>  assumed  <check>`, then `constants.rdp.cmdFifoWords` exists, the spec table gains a row, and the bench readout prints the row's status next to any metric that depends on it.

## Shape

**Data structures first.** `Tick` is an absolute `u64` on the 187.5 MHz master tick (2 per PClock, 3 per RCP clock). Every timed device is an `Actor` with one `clock`, a `runUntil(until)` that stops early only at a bus request, and a `granted()` callback. The `Bus` holds a tiny pending set (at most one request per master), `freeAt`, eight `BankState{row, valid, dirty}`, and a pending refresh tick. The `Scheduler` holds the actor list and the static observer table. `TimingConstants` is one generated struct. The CPU has a `CpuTiming` scoreboard (per-register ready ticks, a 2-slot fetch queue, lagged interrupt masks) and a `WriteBuffer` actor. The RDP has a `CommandDma` FIFO, a `Decoder`, a `SpanUnit`, a `SpanRam` of two color and two Z halves, and a `Noise` triple. `SpanTable` and `WriteRuns` are the only objects that cross between pixels and time.

**Decision 1, scheduler (#9, #14): a lockstep transaction timeline, CPU-led, with explicit horizons.** The CPU pipeline is the only "pull" actor; every other device is a resumable state machine. Three invariants (timeline.hpp I1-I3) make bus order a pure function of request timestamps. A device never runs past the clock of any device that can observe it, a device that needs the channel posts a timestamped request and stops, and the bus grants a request only when every other master's clock is at or beyond the grant time. The CPU calls `scheduler.settle(now)` once per instruction (skipped while `now < nextWake()`), so interrupts raised at tick t by any device are sampled by the first instruction issued after t plus the MI latency parameter, in both directions of causality. Windowed occupancy loses exact order; cothreads (`ares::Scheduler`) would buy nothing because only the CPU has a deep stack. The RSP, which does read RDP registers mid-instruction, is handled by the observer table, where the RDP's horizon includes the RSP's clock, so `observe` always runs the RDP forward, never back. Sync frequency has no meaning left, because there is no window.

**Decision 2, bus (#4, #14).** One `Bus::request` path for all RDRAM bytes; `rdram.ram.read/write` becomes private. Cost is NEC µPD488170L wire time (10 tc read hit, 4 tc write hit, 4 tc per octbyte, 22/30 tc retry) quantized to RCP clocks at the RI plus a per-master-class overhead calibrated to the hardware totals nemu64-test and systembench give for the CPU (32/41 pclk) and n64brew's memset gives for DMA (19.7 rclk per 128 B). Refresh is a 52/54 rclk channel hold posted by the VI actor at each HSYNC. Arbitration among requests that are waiting when the channel frees is a fixed priority list in the TSV (`arb.priority`, status `assumed`, VI first, RDP last); `arb.policy` can switch to round robin. Calibration #16 edits two TSV rows and nothing else. Requesters: CPU I-fill (32 B), D-fill and writeback (16 B), uncached (8 B) through the write buffer, SP DMA (128 B bursts), RDP command fetch, RDP span reads and per-run writes, TMEM loads, PI blocks, SI 64 B, AI 8 B, VI 15 × 128 B per active line.

**Decision 3, CPU seam (#15, #5, #6, #26, #10): an issue-time scoreboard, not stage simulation, and the recompiler is dropped.** Every nemu64 root cause is a ready-tick rule (LDI, MCI, FPU forwarding, DCB), a latency-table entry with an operand-dependent fast path (FPU), a per-class exception cost (5/6/7), a delayed effect tick (COUNT, Cause/Status sampling lag, slow MTC0), or a fetch-queue property (stores not seen by slots already fetched). A full IC/RF/EX/DC/WB simulation would reproduce the same numbers at several times the host cost and with more state to serialize. The cache, write buffer and COUNT live in `CpuTiming` and `WriteBuffer`; the interpreter's execute functions become pure. The recompiler leaves the build, because bit-identical timing needs the JIT to stop at the exact instruction after any device interrupt, which needs the device's interrupt tick before the block runs, which needs devices to run ahead of the CPU, which breaks I1 whenever the CPU then writes a device register at an earlier tick (SP_STATUS, DPC, DMA starts all do). The three parity bugs in `recompiler-parity.md` are symptoms of that structural problem. The budget section shows the interpreter fits.

**Decision 4, RDP (#13, #2, #3, #8, #12, #17-#21): one engine, CPU-side, span-driven.** Pixels come from a port of angrylion-rdp-plus restructured as `Raster::setup` (edge walk to a `SpanTable`) and `Raster::renderSpan` (one span against prefetched span RAM, returning `WriteRuns`). paraLLEl-RDP and the Vulkan tree leave the core, because a GPU writes RDRAM asynchronously (hazard table in `ares-timing-architecture.md` section 7), returns no per-span write set, and cannot reproduce the hardware LFSRs. The timing state machine owns `DPC_CURRENT` (advances per fetched burst into a 64-word FIFO), the START/END double buffer with END_VALID and DMA_BUSY, the decoder at one word per clock with fixed syncs, the span unit with two alternating 64 B halves per buffer so prefetch of span N+1 overlaps compute of N and write-back of N overlaps N+1, GCLK stalls when the needed half is not ready, one `Wseq` write per contiguous written run cut at 128 B and 2 KiB rows, TMEM loads staged through the Z halves, `atomicPrim` as a 35-clock barrier, and the DP interrupt at SyncFull retirement after the last write-back grant. Pixel bytes reach RDRAM at the write-back burst's data tick, so a CPU read between spans sees hardware order. The noise LFSRs step per RDP clock lazily (`Noise::at(clock)`), so write enables in MM's two noise-gated texrects depend on the exact clock count including stalls; the pixel-to-clock offset is an open TSV row. On license, angrylion-rdp-plus states MIT in its repository README; the import unit must read its LICENSE file at the pinned commit and record it (MIT is ISC-compatible; MAME's RDP is BSD-3 and also compatible, but its code is older).

**Decision 5, RSP (#28, #10).** The existing dual-issue pipeline model stays (it passes nemu64's RSP timing set). The RSP becomes an actor behind the CPU; its DMA engine becomes its own actor and bus master with 128 B bursts and the DMA overhead parameter, so `SP_DMA_BUSY/FULL` are exact at any tick. The RSP recompiler is dropped for the same reason as the CPU's, since block overshoot past the CPU's clock violates I1, and the +1.7% was that overshoot plus per-block DMA stepping. `SP_PC` returns the live PC.

**Decision 6, parameters.** `timing/constants.tsv` is the single source. A generator emits `constants.hpp/.cpp` and `docs/timing/behaviors.md`. Each row carries value, unit, reference, status (`cited`, `derived`, `assumed`, `conflict`, `open`) and the check that verifies it. The generator fails the build on an `open` row used without a value and on a `conflict` row without a chosen value. Verification attaches per row. The harness (`n64-timing/build/harness`, `n64-run`) runs nemu64-test, n64-systemtest, systembench-style ROMs, the RDP sweep ROMs written in the plan, and the MM bench; the bench readout prints the status of every row a metric depends on.

**Decision 7, run budget.** 600 frames is 10 s emulated, 937.5 M PClocks, 625 M RCP clocks. Nothing below is measured on this machine; each line names what fixes it. CPU first. MM's IPC is roughly 0.6 (inferred from ares's own miss counters, 19 k I-misses per frame, and a 2-cycle average memory cost), so about 560 M instructions; at 30 ns each (ares's interpreter today plus a scoreboard update and a one-compare `nextWake` skip) that is 17 s. RSP next. About half of 625 M clocks busy at under one instruction per clock, so about 250 M issue pairs at 12 ns, 3 s. RDP. 200 rendered MM frames (20 fps) through a single-threaded angrylion at an estimated 25 ms per 320×240 frame with Z and AA, 5 s; the span-unit bookkeeping adds under 10 ns per span and there are about 100 k spans per frame, 0.2 s. Bus. RDP traffic dominates at an estimated 10 to 20 MB per frame in 64 B average bursts, 150 k to 300 k grants per frame, plus VI's 3.6 k, plus CPU misses; 60 M grants at 40 ns, 2.5 s. Settle overhead while the RSP runs is one extra actor switch per RSP issue pair, folded into the RSP line. Software VI filter, 600 fields at 2 ms, 1.2 s. The sum is about 30 s, with a 2 to 3× uncertainty on the CPU and RDP lines, so 30 to 90 s against the 120 s limit. The first measurement is the current interpreter's host time on the harness (plan unit 0); the second is angrylion-rdp-plus standalone on MM frame dumps; the third is the per-instruction cost of the scoreboard after plan unit 6a. If the CPU line lands above 40 s the lever is the `nextWake` skip and a cheaper decode cache, not a JIT.

**Interface depth.** The public surface is `Actor` (3 virtuals), `Bus::request`, `Scheduler::observe`, and the TSV. Behind it sit grant ordering, bank state, refresh, priority, overlap of RDP memory with compute, interrupt timestamps. A device author cannot read RDRAM without time, cannot read another device at the wrong tick, and cannot invent a constant. That is where the complexity goes, per `boundary-discipline` and `model-the-domain`.

**What the design does not do.** No run-ahead, no speculation, no rollback, no threads in the timing path, no second renderer, no toggle.

## Synthesis decision

*(left empty for the arena)*

## Tradeoffs accepted

- We accept losing both recompilers in exchange for one cost model with a provable ordering invariant and no parity class of bugs. The budget estimate says the interpreter fits with margin; unit 0 measures it before anything else is built.
- We accept dropping paraLLEl-RDP (and GPU rendering, upscaling, and the Vulkan VI path) in exchange for pixels and time from one deterministic engine whose write sets reach the bus.
- We accept per-instruction `settle()` while the RSP or RDP is active in exchange for exact interrupt and register timing. The cost is bounded by the `nextWake` skip and by the RSP's own instruction rate.
- We accept RDRAM wire costs quantized to RCP clocks (`ri.quantize_rclk`) because the RI issues in its own domain and the CPU-visible totals are calibrated anyway; the flag can be turned off.
- We accept a fixed-priority default with no hardware source, isolated in one TSV row, because the map forbids an unverified status in code but demands that every behavior be built; the row's `assumed` status is the honest record.
- We accept an issue-time scoreboard instead of a stage simulation; if a future nemu64 case needs a stage the scoreboard cannot express, the fetch queue is the place to add it, not a rewrite.
- We accept restructuring angrylion into per-span calls (a real porting effort) because the alternative, rendering whole primitives then replaying, would commit pixels at the wrong ticks and read framebuffer state that CPU writes could have changed in between.

## Alternatives considered

- **Cothreads (`ares::Scheduler`, libco) with run-until-sync per device.** Same ordering as this design but every device, including the RDP rasterizer, must be able to yield mid-call; the recompilers still cannot stop at an arbitrary tick, and savestates must capture stacks. It hides nothing extra from callers. Lost on complexity with no gain in depth.
- **Windowed occupancy, where devices run in windows, the bus charges each window a share of occupancy.** Simple, but contention becomes a statistic that depends on window size, which is the sync-frequency dependence #10 rules out. Lost on correctness.
- **Keep the recompiler with a per-instruction clock check and device run-ahead with rollback.** Rollback of the RSP and bus state on every CPU register write is a second emulator. Lost on complexity; the budget makes it unnecessary.
- **paraLLEl with per-span atomic counters and readback.** Needs a GPU sync per batch, gives union masks without run structure unless the shaders are rewritten, and cannot reproduce hardware noise. Lost on determinism and on the write-granularity finding (#17).
- **Stage-accurate VR4300 (cen64 style).** Reproduces the same nemu64 numbers at higher host cost and with the bus still external. Lost on budget; the scoreboard exposes the same surface to the bus.
- **RDRAM wire timing in 250 MHz tc units on a 750 MHz master tick.** Exact, but it multiplies every existing constant by 4 and the RI quantizes anyway. Lost on reader load; kept as a flag.

## Implementation reconciliation

*(empty until implementation starts)*

## Open questions and risks

1. Is the budget real? Nothing here is measured. Unit 0 must time the current interpreter build on the harness for 600 frames; if the CPU interpreter alone exceeds ~40 s, the scoreboard's per-instruction cost becomes the design's main risk and the plan's unit order should put the cheap settle skip first.
2. Does angrylion-rdp-plus restructure cleanly into per-span calls without changing its pixel results? Its span loops are per-scanline already, but TMEM load staging and copy mode need care; the conformance check is its own output before and after the restructure.
3. The per-span +12 and per-primitive 14 clocks come from one unpublished measurement whose author reverted sibling laws (jgemu-dpc-probe). Should the span unit charge them at all, or only the vendor rates plus modeled memory time? The TSV marks them `cited-weak`; the RECTH sweep ROM in plan unit 12 decides, but only on hardware.
4. Which arbitration default should the program ship with until calibration #16 happens? The design picks VI-first, RDP-last; a different default is one TSV edit.
5. MM's bench build disables the retail per-frame particle scaling by RDP time (`func_80173B48`, mm-rdp-stream). With a slow RDP that scaling changes the command stream; should the bench re-enable it once the RDP is timed?
6. Savestates. Every actor and the bus serialize; the rasterizer's TMEM and mode state already do. Is the fork's savestate compatibility a requirement at all? Assumed not.

## Next implementation step

Build unit 0 and unit 1 of `plan.md`. Time the current interpreter on the harness, then replace `Thread` with `Actor` and `CPU::synchronize` with `Scheduler::settle` with a zero-cost bus, and prove the per-frame `cpu_cycles` and `fb_hash` columns are unchanged.
