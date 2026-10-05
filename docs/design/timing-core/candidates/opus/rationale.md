# Timing core architecture (candidate: opus)

Map [#1](https://github.com/wScottSh/ares/issues/1). Decides [#9](https://github.com/wScottSh/ares/issues/9), [#13](https://github.com/wScottSh/ares/issues/13), [#14](https://github.com/wScottSh/ares/issues/14), [#15](https://github.com/wScottSh/ares/issues/15), [#28](https://github.com/wScottSh/ares/issues/28), and the determinism half of [#27](https://github.com/wScottSh/ares/issues/27). Grounded on `research/ares-timing-architecture` and the 19 research docs linked from the map. Sketch headers are in `sketch/`; the build sequence is `plan.md`.

## Problem

Every timing behavior on the map needs the same thing ares does not have: one emulated timeline on which CPU, RSP, RDP, the DMA engines and VI scanout issue RDRAM bursts in true time order, so that who waits for whom is decided by timestamps and not by host sync frequency. Today the CPU drags lagging devices forward in a fixed order per window (`cpu/cpu.cpp:83-121`), RDRAM access costs nothing and is not arbitrated, the RDP renders on a GPU thread inside the `DPC_END` write, and costs are constants scattered over 55 call sites plus a second, disagreeing table in the recompiler.

Constraints the design must honor:

- Accuracy is the only goal. Timing is always on, with no toggle. The interpreter is the timing reference; the recompiler survives only with bit-identical timing (map Notes).
- Bit-deterministic across runs: no host clock, no GPU thread, no host entropy.
- The RDP write traffic depends on per-pixel results (#12, #17), so whatever produces the pixels must hand per-segment write masks to the timing model before the write-back is scheduled.
- Ordering must not depend on sync granularity (#10 finding 4).
- Several parameters have no published value: client priority, command FIFO depth, span read latency. The design must hold them as named, cited rows that calibration (#16) can change in one place.
- 600 MM frames (10 s emulated) in at most 2 min on this machine.

## Usage (caller's view)

A device author sees two calls: post a burst and move bytes when it is granted, or catch the timeline up before touching another device. Everything else is behind them.

The CPU interpreter, after this design (`sketch/cpu/master.hpp`):

```cpp
auto CPU::instruction() -> void {
  auto slot = fetchWindow.next();
  auto& t = opTiming[decode(slot.word)];
  pipeline.issue(t);                                   // interlocks -> ex
  if(pipeline.ex >= timeline.horizon()) timeline.catchUp(pipeline.ex, ActorId::CPU);
  if(interruptTaken(pipeline.ex)) return pipeline.fault(FaultStage::RF), exception.interrupt();
  execute(slot.word);
  pipeline.retire(t, latencyFor(t));
}

// LW from KSEG1 RDRAM inside execute():
pipeline.freezeUntil(sysad.read(paddr, Word, value, pipeline.dc()));
```

The RSP reading the RDP's fetch pointer in MM's stall D (`rsp-rdp-fifo.md`):

```cpp
case DPC_CURRENT:
  timeline.catchUp(time, ActorId::RSP);   // RDP, bus, events reach `time`
  return rdp.dpc.read(DPC_CURRENT, time);
```

A DMA engine as a bus client (SP DMA, `sketch/rsp/actor.hpp`):

```cpp
auto SpDma::start(Clock at) -> void {
  RI::split(rdramAddress, rowBytes, Behavior::SpDmaBurstBytes,
    [&](u32 address, u8 bytes) { ri.post({address, bytes, dir, Requester::SpDma, tag}, at); });
}
auto SpDma::granted(const RI::Grant& g) -> void {
  copyBetween(rdram.ram, rsp.dmem, g.burst);             // bytes move at grant time
  if(moreRows()) postNextRow(g.complete);
}
```

Adding or changing a timing constant is one TSV row (`sketch/timing/behaviors.tsv`):

```
ri.refresh-dirty	54	rclk	vendor	IPL3 6105 RI_REFRESH DirtyRefreshDelay (B12)	bench:uncached-vs-hpos
```

`tools/n64-timing/behaviors.py` regenerates `Behavior::RiRefreshDirty`, the spec row, and checks that `bench:uncached-vs-hpos` exists in the check manifest. A row with no reference or no check does not build.

## Shape

### Data structures first

| Structure | File | What it encodes |
|---|---|---|
| `Clock` | `timing/clock.hpp` | Absolute time since power-on in 1/750 MHz units. 750 MHz is the LCM of RCLK, PClock and RCP clock, so tc = 3, pclk = 8, rclk = 12, COUNT = 16 units exactly. VCLK is rational (5500/357 units) with a remainder accumulator. Nothing subtracts from time at sync points. |
| `Timeline`, `Actor`, `Readiness` | `timing/timeline.hpp` | The conservative discrete-event scheduler and its single invariant. |
| `RI::Ri`, `Requester`, `RequesterSpec`, `Burst`, `Grant`, `BankState` | `ri/bus.hpp` | The channel: per-burst arbitration, 8 banks with open row and dirty bit, NEC wire costs, refresh. The only path from a hardware client to `rdram.ram`. |
| `OpTiming`, `Pipeline`, `FetchWindow`, `Cp0Writes`, `TimedCp0` | `cpu/pipeline.hpp` | VR4300 timing as stage times derived from one EX timestamp per instruction, plus a register scoreboard. |
| `SysAD` | `cpu/sysad.hpp` | Write buffer and SysAD port as one in-order queue. |
| `RSPActor`, `SpDma` | `rsp/actor.hpp` | RSP interpreter as an actor with a DMA-landing horizon; SP DMA as a bus client. |
| `RDPTimed::*` | `rdp/timed.hpp` | DPC front end, command FIFO, spans, segments, span-RAM halves, snapshots, ported pixel engine, noise LFSR. |
| `EventKind`, `ViFetch`, `AiDma`, `PiDma`, `SiDma` | `devices/events.hpp` | Fully scheduled devices as timeline events plus bus clients. |
| `behaviors.tsv` -> `Behavior::*` | `timing/behaviors.*` | Every constant, with basis, reference and verifying check. |

### Decision 1: a conservative discrete-event timeline with the CPU as the outer loop, no cothreads (#9, #14)

Each actor (bus, events, SysAD, RDP, RSP) reports `Runnable at t`, `Blocked` (waiting for a bus decision) or `Parked` (cannot act until someone acts on it). `Timeline::catchUp(t, caller)` repeatedly steps the runnable actor with the smallest `(time, rank)` until every actor not on the call stack is past `t`, never stepping past an actor that is on the stack. The bus is an actor whose time is its next decision; it decides a grant only when it is the minimum, which means every actor that could still post an earlier-arriving request has passed that time. Request latency is at least one unit, so a decision never races an equal-time post.

This gives exact time ordering of every bus request and every cross-device read or write, and it is independent of how often the host switches, because the switch points never decide an order. Only the CPU ever blocks inside a call (`Timeline::await`, for its own SysAD transaction), and it is always the outermost frame, so there is no need for cothreads. Nested catch-ups (RSP reads `DPC_CURRENT`, a SysAD drain writes `DPC_END`) recurse with strictly decreasing floors, so depth is bounded by the actor count.

Interrupts need no special channel. A raise happens at the raiser's step time; the CPU samples at `pipeline.ex` after catching everyone up to `ex`, so every earlier raise is visible and no later one is.

The CPU skips `catchUp` while `ex < timeline.horizon()`, the earliest time anyone else could act. With the RSP halted, the RDP idle and the bus empty, the horizon is the next VI/AI/PI/SI/COMPARE event, so the CPU runs alone for long stretches. While the RSP runs, CPU and RSP alternate per instruction, which is what today's interpreter already does.

The RSP's horizon is the earliest landing time of any undecided SP DMA burst (`Ri::earliestLanding`). It never executes past a DMA write into DMEM that has not been decided, so DMEM reads and `SP_DMA_BUSY` reads are exact.

### Decision 2: one RI arbiter that owns RDRAM bytes and RDRAM time (#4, #14)

Every hardware client posts bursts (8-128 B, never crossing a 2 KiB row) to `ri.post`. At each decision time `d` (the next rclk edge at or after the channel is free and a request has arrived) the arbiter picks `argmin(rank, arrival, requester, sequence)` among arrived requests, charges the NEC wire time for the bank's row state (hit, clean retry 22 tc, dirty retry 30 tc, 4 tc per octbyte, post-transaction gap), adds the per-direction RI overhead fitted from SP DMA throughput, updates the bank, and calls the client's `granted()`. The client copies its bytes in that callback. So RDRAM content changes only at grants, in grant order, and every read sees exactly the writes granted before it. Refresh is a rank-0 request posted at each VI HSYNC that holds the channel 52 or 54 rclk (clean or dirty), clears dirty bits and leaves rows open.

Requesters: Refresh, VI fetch, CPU SysAD (uncached, fills, writebacks, in SysAD order), SP DMA, DP command, DP color, DP depth, DP texture, DP fill, PI, SI, AI. Their rank, request latency and response latency live in one `requesterSpecs` table built only from `Behavior::*` rows.

Arbitration has no published source (#4 B4). The pick: refresh first, then VI, then everyone else first-come first-served (equal rank, ordered by arrival). This adds the fewest invented orderings: one inference (VI is the only hard real-time client) and no order among the others. Calibration changes it by editing `ri.rank.*` rows. Because rank is compared before arrival, a strict fixed-priority order is the same mechanism with distinct ranks, so there is one arbitration rule, not two.

CPU-visible totals are hardware-measured (uncached read 32 pclk, D-fill 41). The SysAD fixed path is a derived row: measured total minus the modeled uncontended RI time for the measurement's row state. So the uncontended case reproduces the measurement by construction, and contention, row misses and refresh add on top. The nemu64-test VI-same-bank case (36 pclk) is then a real test of the bank model, not a fitted number.

### Decision 3: one RDP engine, CPU-side, whose memory traffic is its pixel data (#13)

Pixels come from a C++ port of the cen64-jgemu RDP (`src/rdp`, about 15k lines, BSD-3-Clause, MAME lineage by Ryan Holtz with snapper64-fitted fixes by Rupert Carmichael). BSD-3 is compatible with ares's ISC; the notice is retained in the ported files and recorded in the PR. Checked alternatives:

- angrylion-rdp-plus ships under the old MAME license (non-commercial clause, `MAME License.txt` in the repo). Not compatible with ISC.
- paraLLEl-RDP (MIT) computes write enables on the GPU and keeps only a per-pass union mask. Per-segment masks would need a GPU readback before each write-back is scheduled, and its RDRAM writes race CPU reads unless every read waits on the GPU. Both break determinism or cost a round trip per span.
- A command-stream-only predictor cannot know the write set (#12) and would be most of an RDP anyway.

The port changes one seam: `rdp_read_pixel*`, `rdp_write_pixel*`, `rdp_z_compare` and `rdp_z_store` read span snapshots and write span-RAM halves instead of RDRAM. Edge walking (`rdp_render_spans` extents) stays as is and runs at primitive dispatch, because span extents depend only on the command and scissor.

The RDP actor follows the hardware dataflow:

- Command fetch posts `DpCommand` bursts while the FIFO has room; `DPC_CURRENT` advances at each grant. That is the fetch pointer MM's ucode throttles on (stalls B, C, D in `rsp-rdp-fifo.md`), so back-pressure emerges with no ucode-side code. `START`/`END` double buffering, `END_PENDING`, `DMA_BUSY`, `TMEM_BUSY` and the counters are modeled; the DP interrupt is raised when `SYNC_FULL` retires.
- Span prefetch posts `DpColor` (if `IM_RD`) and `DpDepth` (if `Z_CMP`) reads up to `prefetchLead` spans ahead; the grant copies the row into a `SpanSnapshot`.
- The pipeline processes `Segment`s: the stream positions of one span inside one span-RAM half (`span-ram.md`). A segment starts only when its snapshot is ready and its half is free; otherwise the RDP clock runs with GCLK off. `PixelEngine::shade` computes the segment's pixels at that time, with the noise LFSR at the exact RDP clock of each pixel.
- A full half, or the end of a span or primitive, triggers write-back: one burst per contiguous written run, end-trimmed, split at 128 B and 2 KiB rows; a fully rejected half posts nothing (`rdp-write-granularity.md`). The half frees when its last burst is granted.
- `G_PM_1PRIMITIVE` is a barrier: the next primitive's prefetch waits for the previous primitive's write-backs, plus `rdp.atomic-dead`. Without it, a prefetch can be granted before an overlapping write-back, and the stale read that the SDK warns about happens on its own.

paraLLEl-RDP and the Vulkan path leave the N64 core. VI output is ares's existing software VI filter, fed from the bytes the VI fetch bursts copied at their grant times.

### CPU timing seam (#15, #5, #6, #26, #10)

The VR4300 is single-issue and in-order, and every interlock and memory stall freezes the whole pipeline. So a stage simulator is not needed to get stage-exact timing. Each instruction gets one EX timestamp; IC, RF, DC and WB are fixed offsets from it; `ex(i) = ex(i-1) + 1 + stalls`. A register scoreboard (`gprReady`, `fprReady`, `hiloReady`, unit-free times) yields LDI, MFC0-as-load, MCI and the FPU forwarding bubble as one `max()` each. The parts that do need stage identity are explicit offsets:

- Memory happens at DC (`pipeline.dc()`), through `SysAD`.
- Fetch happens at IC, three slots ahead, in `FetchWindow`, which makes the self-modifying-code cases execute the old word.
- Exceptions charge by detection stage (5, 6 or 7 pclk; FPU arithmetic first pays its own latency).
- CP0 writes become visible after per-register delays (`Cp0Writes`), which covers the COUNT write, the one-instruction interrupt-sampling lag and Wired.
- COUNT and Random are functions of time (`TimedCp0`), and COMPARE is one scheduled event at the exact crossing, not a check per sync.

Where things live:

- Interlocks: `Pipeline::issue`.
- Cache: the existing `ICache`/`DataCache`, with hit cost folded into the issue cycle and misses going to `SysAD::fill`.
- Write buffer: `SysAD`.
- COUNT: `TimedCp0`.

The only cost tables are `opTiming[]`, built from the decoder's `OpInfo` masks plus behavior rows, and the behavior rows themselves.

The recompilers leave the timing build, CPU and RSP both. The interpreter is the reference by map rule; the budget estimate below says the interpreter fits; and a recompiler that is bit-identical under this model needs exits at every horizon crossing and every interaction, which is the interpreter's step size during the busy part of every MM frame. Removing them deletes the second cost table, `JitInterleaving`, `jitClockTarget` and the slow-path double-charge class of bug outright. If the budget measurement (plan U0, U16) fails, a block executor comes back only in quiescent windows (`ex + block's worst static cost < horizon`, slow paths calling the same `CpuMemory` functions), gated by a lockstep checker that compares Clock traces with the interpreter.

### RSP seam (#28, #10)

The RSP interpreter and its existing `Pipeline` (GPR/VR read-after-write, load-store stalls) are the RSP cost model, unchanged. A halted RSP is `Parked` and costs nothing. Its interactions use the issue pair's start time: DPC accesses catch the RDP up first, `MTC0` to the DMA length registers starts `SpDma`, BREAK and `SP_STATUS` raise MI at that time. SP DMA is a bus client posting 128 B bursts, so its rate comes from the RI model and the fitted overhead rather than today's 8 B per rclk. The +1.7% RSP recompiler divergence of #28 disappears with the recompiler; its two suspected causes (per-block DMA stepping and block overshoot) are exactly the two things this design forbids.

### Where parameters live and how verification attaches (item 6)

`ares/n64/timing/behaviors.tsv` is the single source. Its columns are id, value, unit, basis, reference, verify and note. Basis is one of measured, vendor, datasheet, wiki, derived, fit or assumption. `tools/n64-timing/behaviors.py` generates:

- `behaviors.hpp` with `Behavior::*` constants, converted to `Clock` units exactly. A non-integer value fails unless the row is a fit.
- The spec markdown with one row per behavior.
- A per-behavior results table when the harness runs.

It fails on an empty reference, an empty verify list, or a verify id missing from `tools/n64-timing/checks.tsv` (check id to ROM, test selector, expectation source). A lint rejects timing literals in `ares/n64` outside the generated header, and its error message names the TSV. The spec and the code therefore cannot drift, and "no unverified status" is a build failure instead of a review comment. Assumption rows (tie-break rank, client ranks, VI and SP burst sizes) are allowed but printed as assumptions in the spec, so they stay visible as calibration targets.

### Determinism (#27)

All ordering is by timestamp with fixed tie-breaks, and there is no GPU thread and no host clock. The remaining host-entropy uses get fixed values:

- CP0 Random becomes a function of time.
- `SP_PC` reads return the RSP's PC.
- The RDRAM current-calibration thresholds use a fixed value.
- The entropy seed is pinned.

Two identical runs must produce byte-identical per-frame stats, including the framebuffer hash. That check runs in every plan unit.

### Interface depth

`Timeline` exposes `catchUp`, `await`, `horizon`, `schedule` and `cancel`; it hides ordering, tie-breaks, nesting and bus safety. `Ri` exposes `post`, `complete` and `earliestLanding`; it hides arbitration, bank state, wire costs, refresh and the RDRAM bytes' single owner. A device implements `granted()` and, if stepped, `readiness()` and `step()`. No device knows another device's clock, and no device charges time to a caller's `Thread` (today's `Memory::RCP::read` steps whichever thread is passed). The RDP's public surface is still DPC register read/write; everything inside is private to `RDPTimed`.

### What it deliberately does not do

- No cothreads and no host threads in emulation. The pixel engine runs on the emulation thread; MAME-style worker parallelism is a later optimization that must not change any output, checked by the determinism test.
- No windowed or statistical bus charging.
- No toggle and no fast path.
- No per-tc channel scheduling finer than the RI's rclk-edge decisions. The wire time is in tc; grants land on rclk edges.

### Run budget (item 7)

Estimate for 10 s emulated MM (600 VI fields, 200 rendered frames). These are guesses from operation counts; the measurements to replace them are plan U0 and U16.

| Part | Work in 10 s emulated | Assumed host cost | Host time |
|---|---|---|---|
| CPU interpreter + pipeline timestamps | 937.5 M pclk, about 600 M instructions (idle thread spins) | 10 ns/instr | 6 s |
| CPU-RSP alternation (`catchUp` per instruction while RSP runs) | about 400 M calls | 3 ns | 1.2 s |
| RSP interpreter | about 60% busy, about 300 M issue pairs | 10 ns | 3 s |
| RDP pixels | about 300 k px/frame x 200 = 60 M px | 50 ns/px (MAME-lineage, single thread) | 3 s |
| RDP segments, spans, commands | about 15 k spans/frame x 200 | 300 ns/span | 1 s |
| RI decisions | about 100 k bursts/frame (spans, I/D fills, SP DMA 6 k, DP cmd 2 k, VI 3.5 k/field) = 20 M | 50 ns | 1 s |
| VI compose, AI, PI, SI | small | | under 0.5 s |
| **Total** | | | **about 15 s** (8x headroom to 120 s) |

What must be measured, in order of risk: (1) today's interpreter-only wall time for the 600-frame bench on this machine (U0), which calibrates the CPU and RSP lines; (2) ported pixel engine ns/pixel single-threaded (U11); (3) `catchUp` overhead while the RSP runs (U4). If (1) alone exceeds 60 s, the quiescent-window block executor is the first lever, and a deterministic multi-threaded pixel engine the second.

## Synthesis decision

## Tradeoffs accepted

- We accept an exact time-ordered scheduler that alternates CPU and RSP per instruction while the RSP runs, in exchange for ordering that no sync setting can change. The cost is the same per-instruction alternation the interpreter already pays.
- We accept removing both recompilers from the timing build in exchange for one cost model and no parity bugs. This looks like a regression in speed; it is a deliberate bet on the 8x estimated headroom, with a measured gate (U0) and a defined way back.
- We accept a port of about 15k lines of third-party C into the core in exchange for pixels and timing from one deterministic engine. Pixel output will differ from paraLLEl where MAME lineage and angrylion lineage disagree; snapper64 console captures, not paraLLEl, are the reference for those differences.
- We accept 750 MHz absolute time units, a mechanical rename of every `step(n*2)` and `*3`, in exchange for exact tc, pclk and rclk arithmetic and no subtract-at-sync bookkeeping.
- We accept first-come first-served arbitration below VI as an assumption, labeled as such in the spec, in exchange for the fewest invented orderings until calibration exists.
- We accept primitive-level attribute snapshots at first, which misses the unsynced-attribute corruption offsets, in exchange for a simpler first RDP. A plan unit replaces it.
- We accept RDP rendering on the emulation thread in exchange for determinism by construction. Parallelism comes later, only if U16 needs it.

## Alternatives considered

- **Windowed occupancy** (charge each window's bus demand as a share of channel time). It hides ordering entirely from callers and is cheap, but contention then depends on window size, so the interpreter and any block executor disagree, which is #10's core finding. It cannot express the VI-bank row-miss effect or a CPU read waiting behind one specific RDP burst. Rejected.
- **Cycle lockstep** (tick every device every rclk, cen64/MiSTer style). The interface is simplest of all (each device has `tick()`), and ordering is exact. But the RDP would have to render per clock, and the CPU and RSP pay a call per rclk even when halted or idle. It hides less than the event timeline, which gives identical ordering while idle devices cost nothing. Rejected on cost, with no accuracy difference.
- **Cothread per actor on ares's generic `Scheduler`.** Also exact, and the most natural shape for actors that block. It exposes a switch on every interaction and stacks per device. Since only the CPU ever blocks and it is always outermost, the stackless timeline gets the same ordering. Rejected as unneeded machinery.
- **Timestamped bus with a CPU-first sync loop** (keep `CPU::synchronize`, add timestamps to bursts only). Smaller change, but lagging devices still run whole windows in fixed order, so their mutual interactions (RSP polling `DPC_CURRENT` while the RDP fetches) stay window-ordered. Rejected: it fixes the bus and leaves the RSP-RDP back-pressure wrong, and that back-pressure is structural in MM (#21).
- **paraLLEl-RDP with per-span write counters and readback** for pixels. It keeps GPU speed and upscaling, but exposes a GPU sync point to timing on every span and leaves RDRAM written by another thread. Rejected for determinism and coupling.

## Implementation reconciliation

## Open questions and risks

- Is the cen64-jgemu renderer pixel-exact enough? It is fitted to snapper64 captures in the cases it names; its general agreement with angrylion on MM scenes is unmeasured. U11 measures it against snapper64 and against paraLLEl frame dumps before paraLLEl is removed. If it falls short, does the program accept MAME-lineage pixels, or fund a clean-room port of the disagreeing paths?
- Should the RI per-burst overhead be one global value per direction, or per requester? The only fits come from SP DMA (hcs64 for reads, n64brew memset for writes, which conflict by 17%). Using them for RDP and VI bursts is an assumption.
- Does a pipeline freeze also freeze the MULT/DIV and FPU iteration counters? The sketch assumes they keep running (`Pipeline::freezeUntil`). No reference was found either way; a nemu64-style test (DIV, then a D-miss, then MFLO) would settle it.
- The cen64 span law (`14 + Σ(px·129/128 + 12)`) was measured with an unknown othermode and probably includes memory time. This design models memory explicitly, so the law becomes a check (U14 reproduces it under the probe's likely config) rather than a cost term. If the full model cannot reproduce it, which term is wrong?
- Command FIFO depth: n64-systemtest's author note (CURRENT reaches START+240, 30 dwords) against MiSTer's 64. The sketch takes 30 as the only hardware-side hint. Is an author's note enough to build from, given the map's rule?
- Span-RAM half capacity at 16 bpp (16 or 32 pixels per half) is unmeasured (`span-ram.md` question 1). It changes segment count and stall points.
- Equal-time tie-break order between RCP blocks is a convention. No test ROM can observe it except through an exact tie. Is it acceptable as a labeled assumption?

## Next implementation step

U0 and U1 in `plan.md`: measure today's interpreter-only 600-frame bench wall time and nemu64 baseline through the harness, then remove both recompilers from the timing build and show nemu64 and the bench unchanged.
