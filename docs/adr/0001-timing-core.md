# Timing core architecture (synthesis)

Map [#1](https://github.com/wScottSh/ares/issues/1). Decides [#9](https://github.com/wScottSh/ares/issues/9), [#13](https://github.com/wScottSh/ares/issues/13), [#14](https://github.com/wScottSh/ares/issues/14), [#15](https://github.com/wScottSh/ares/issues/15), [#28](https://github.com/wScottSh/ares/issues/28), and the determinism half of [#27](https://github.com/wScottSh/ares/issues/27). Base: candidate-opus. Grafts and rejections are in [Synthesis decision](#synthesis-decision). Sketch headers are in `sketch/`; the build sequence is `plan.md`; the judge's scores are `judge.md`.

## Problem

Every timing behavior on the map needs the same thing ares does not have: one emulated timeline on which CPU, RSP, RDP, the DMA engines and VI scanout issue RDRAM bursts in true time order, so that who waits for whom is decided by timestamps and not by host sync frequency. Today the CPU drags lagging devices forward in a fixed order per window (`cpu/cpu.cpp:83-121`), RDRAM access costs nothing and is not arbitrated, the RDP renders on a GPU thread inside the `DPC_END` write, and costs are constants scattered over 55 call sites plus a second, disagreeing table in the recompiler (`ares-timing-architecture.md`, three structural obstacles).

Constraints the design honors:

- Accuracy is the only goal. Timing is always on, with no toggle. The interpreter is the timing reference (map Notes).
- Bit-deterministic across runs: no host clock, no GPU thread, no host entropy.
- RDP write traffic depends on per-pixel results (#12, #17), so whatever produces the pixels must hand per-segment write masks to the timing model before write-back is scheduled.
- Ordering must not depend on sync granularity (#10 finding 4).
- Parameters with no published value (client priority, command FIFO depth, span read latency) are named, cited rows that calibration (#16) changes in one place.
- Third-party code must be ISC-compatible with its license recorded (preferences line 9; facts 1-2).
- Verification uses only the in-repo ROM generator (romgen), the MM bench (mmbench), the prebuilt ROMs on disk, and romgen ports of MIT corpora (fact 4).
- 600 MM VI fields in at most 2 min on this machine. Today's interpreter does it in 8.5 s (fact 3).

## Usage (caller's view)

A device author sees two calls: post a burst and get told when it is granted, or catch the timeline up before touching another device. Everything else is behind them.

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
pipeline.freezeUntil(sysad.read(paddr, Word, &value, pipeline.dc()));
```

The RSP reading the RDP's fetch pointer in MM's stall D (`rsp-rdp-fifo.md`):

```cpp
case DPC_CURRENT:
  timeline.catchUp(time, ActorId::RSP);   // RDP, bus, events reach `time`
  return rdp.dpc.read(DPC_CURRENT, time);
```

A DMA engine as a bus client (SP DMA, `sketch/rsp/actor.hpp`). The client names the bytes; the RI moves them at grant time:

```cpp
auto SpDma::start(Clock at) -> void {
  RI::split(rdramAddress, rowBytes, Behavior::SpDmaBurstBytes,
    [&](u32 address, u8 bytes, u32 offset) {
      ri.post({address, bytes, dir, Requester::SpDma, &dmem[pbusAddress + offset], nullptr, tag}, at);
    });
}
auto SpDma::granted(const RI::Grant& g) -> void {   // bytes already moved by the RI
  if(moreRows()) postNextRow(g.complete);
}
```

Adding or changing a timing constant is one TSV row (`sketch/timing/behaviors.tsv`):

```
ri.refresh-dirty	54	rclk	vendor	IPL3 6105 RI_REFRESH DirtyRefreshDelay (B12)	bench:uncached-vs-hpos
```

`tools/n64-timing/behaviors.py` regenerates `Behavior::RiRefreshDirty`, the spec row, and checks that `bench:uncached-vs-hpos` exists in `checks.tsv`. A row with no reference or no check does not build. A row whose check is a corpus the program cannot run yet carries `pending:<gate>` and the spec prints it as pending, never as verified.

Verification is two scripts (`sketch/timing/verify.hpp`):

```
tools/n64-timing/determinism.sh <rom> <frames>     # two runs; per-field stats and trace hash must match byte for byte
n64-run <rom> --frames N --stats a.tsv --step-cap   # catchUp before every instruction; a.tsv must equal the uncapped run
```

## Shape

### Data structures first

| Structure | File | What it encodes |
|---|---|---|
| `Clock` | `timing/clock.hpp` | Absolute time since power-on in 1/750 MHz units. 750 MHz is the LCM of RCLK, PClock and RCP clock, so tc = 3, pclk = 8, rclk = 12, COUNT = 16 units exactly. VCLK is rational (5500/357 units) with a remainder accumulator. Nothing subtracts from time at sync points. |
| `Timeline`, `Actor`, `Readiness` | `timing/timeline.hpp` | The conservative discrete-event scheduler and its single invariant. |
| `RI::Ri`, `Requester`, `RequesterSpec`, `Burst`, `Grant`, `BankState` | `ri/bus.hpp` | The channel: per-burst arbitration, 8 banks with open row and dirty bit, NEC wire costs, refresh. The only writer of `rdram.ram` among hardware clients; it moves the burst's bytes at grant. |
| `OpTiming`, `Pipeline`, `FetchWindow`, `Cp0Writes`, `TimedCp0` | `cpu/pipeline.hpp` | VR4300 timing as stage times derived from one EX timestamp per instruction, plus a register scoreboard. |
| `SysAD` | `cpu/sysad.hpp` | Write buffer and SysAD port as one in-order queue. |
| `RSPActor`, `SpDma` | `rsp/actor.hpp` | RSP interpreter as an actor with a DMA-landing horizon; SP DMA as a bus client. |
| `RDPTimed::*` | `rdp/timed.hpp` | DPC front end, command FIFO, spans, segments, span-RAM halves, snapshots, ported pixel engine, noise LFSR. |
| `EventKind`, `ViFetch`, `AiDma`, `PiDma`, `SiDma` | `devices/events.hpp` | Fully scheduled devices as timeline events plus bus clients. |
| `behaviors.tsv` -> `Behavior::*` | `timing/behaviors.*` | Every constant, with basis, reference and verifying check. |
| `TraceHash` | `timing/verify.hpp` | Rolling hash of every action and grant, plus a state hash per VI field. The artifact `det` and `stepcap` compare. |

### Decision 1: a conservative discrete-event timeline with the CPU as the outer loop, no cothreads (#9, #14)

Each actor (bus, events, SysAD, RDP, RSP) reports `Runnable at t`, `Blocked` (waiting for a bus decision) or `Parked` (cannot act until someone acts on it). `Timeline::catchUp(t, caller)` repeatedly steps the runnable actor with the smallest `(time, rank)` until every actor not on the call stack is past `t`, never stepping past an actor that is on the stack. The bus is an actor whose time is its next decision; it decides a grant only when it is the minimum, which means every actor that could still post an earlier-arriving request has passed that time. Request latency is at least one unit, so a decision never races an equal-time post.

This gives exact time ordering of every bus request and every cross-device read or write, independent of how often the host switches, because the switch points never decide an order. Only the CPU ever blocks inside a call (`Timeline::await`, for its own SysAD transaction), and it is always the outermost frame, so there is no need for cothreads. Nested catch-ups (RSP reads `DPC_CURRENT`, a SysAD drain writes `DPC_END`) recurse with strictly decreasing floors, so depth is bounded by the actor count.

Interrupts need no special channel and no latency parameter. A raise happens at the raiser's step time; the CPU samples at `pipeline.ex` after catching everyone up to `ex`, so every earlier raise is visible and no later one is.

The CPU skips `catchUp` while `ex < timeline.horizon()`, the earliest time anyone else could act. With the RSP halted, the RDP idle and the bus empty, the horizon is the next VI/AI/PI/SI/COMPARE event, so the CPU runs alone for long stretches. While the RSP runs, CPU and RSP alternate per instruction, which is what today's interpreter already does.

The RSP's horizon is the earliest landing time of any undecided SP DMA burst (`Ri::earliestLanding`). It never executes past a DMA write into DMEM that has not been decided, so DMEM reads and `SP_DMA_BUSY` reads are exact.

The horizon skip is an optimization and the design proves it is one. `--step-cap` forces `catchUp` before every instruction. Both runs must produce the same per-field stats and trace hash (sonnet's `maxActionsPerAdvance` test, grafted). That check runs in every plan unit from T5 on.

### Decision 2: one RI arbiter that owns RDRAM bytes and RDRAM time (#4, #14)

Every hardware client posts bursts (8-128 B, never crossing a 2 KiB row) to `ri.post`, each carrying a pointer to the client's bytes. At each decision time `d` (the next rclk edge at or after the channel is free and a request has arrived) the arbiter picks `argmin(rank, arrival, requester, sequence)` among arrived requests, charges the NEC wire time for the bank's row state (hit, clean retry 22 tc, dirty retry 30 tc, 4 tc per octbyte, post-transaction gap), adds the per-direction RI overhead fitted from SP DMA throughput, updates the bank, **copies the bytes between `rdram.ram` and the client's buffer**, and calls the client's `granted()`. So RDRAM content changes only inside the RI, at grants, in grant order, and every read sees exactly the writes granted before it. `Rdram::ram` data accessors are private to the RI, the debugger and the loader (friend list); a device that reads RDRAM directly fails to compile (sonnet, grafted). Refresh is a rank-0 request posted at each VI HSYNC that holds the channel 52 or 54 rclk (clean or dirty), clears dirty bits and leaves rows open.

Requesters: Refresh, VI fetch, CPU SysAD (uncached, fills, writebacks, in SysAD order), SP DMA, DP command, DP color, DP depth, DP texture, DP fill, PI, SI, AI. Their rank, request latency and response latency live in one `requesterSpecs` table built only from `Behavior::*` rows. Per-requester counters (bursts, bytes, row misses, wait units) feed the bench readout (fable, grafted).

Arbitration has no published source (#4 B4). The pick: refresh first, then VI, then everyone else first-come first-served (equal rank, ordered by arrival). This adds the fewest invented orderings: one inference (VI is the only hard real-time client) and no order among the others. Calibration changes it by editing `ri.rank.*` rows. Because rank is compared before arrival, a strict fixed-priority order (fable's list, sonnet's realtime-first) is the same mechanism with distinct ranks, so there is one arbitration rule, not two, and no presets in code. The spec row records both rejected lists as alternatives.

CPU-visible totals are hardware-measured (uncached read 32 pclk, D-fill 41). The SysAD fixed path is a derived row: measured total minus the modeled uncontended RI time for the measurement's row state. So the uncontended case reproduces the measurement by construction, and contention, row misses and refresh add on top. The nemu64 VI-same-bank case (36 pclk) is then a real test of the bank model, not a fitted number.

### Decision 3: one RDP engine, CPU-side, whose memory traffic is its pixel data (#13)

Pixels come from a C++ port of the cen64-jgemu RDP (`src/rdp`, 14,905 lines, BSD-3-Clause, MAME lineage by Ryan Holtz with snapper64-fitted DPS fixes by Rupert Carmichael; fact 2). The notice is retained in the ported files and recorded in the PR. Checked alternatives:

- angrylion-rdp-plus ships the old MAME non-commercial license (fact 1). Out.
- ares's own MAME RDP from before `5f9804fb6` is BSD-3 and compatible, but it is the older ancestor of the same lineage, lacks the DPS span-RAM model that fits snapper64 216/216, and was removed as "too slow to be usable". Rejected in favor of its maintained descendant.
- paraLLEl-RDP (MIT) computes write enables on the GPU and keeps only a per-pass union mask. Per-segment masks would need a GPU readback before each write-back is scheduled, and its RDRAM writes race CPU reads unless every read waits on the GPU. Both break determinism or cost a round trip per span.
- A command-stream-only predictor cannot know the write set (#12) and would be most of an RDP anyway.

The port changes one seam, the functions that touch `m_rdram`: `rdp_read_pixel*`, `rdp_write_pixel*`, `rdp_z_compare`, `rdp_z_store` (span data), the TMEM load source reads, `read_rdram_pair`, and the rect pre-state restore. They read span snapshots and write span-RAM halves (or, for TMEM loads, the Z half staging) instead of RDRAM. Edge walking (`rdp_render_spans` extents) stays as is and runs at primitive dispatch, because span extents depend only on the command and scissor. The port's seeded-hash noise (`rdp_core.c:58-89`, paraLLEl's) is replaced by our LFSR (#18).

The RDP actor follows the hardware dataflow:

- Command fetch posts `DpCommand` bursts while the FIFO has room; `DPC_CURRENT` advances at each grant. That is the fetch pointer MM's ucode throttles on (stalls B, C, D in `rsp-rdp-fifo.md`), so back-pressure emerges with no ucode-side code. `START`/`END` double buffering, `END_PENDING`, `DMA_BUSY`, `TMEM_BUSY` and the counters are modeled; the DP interrupt is raised when `SYNC_FULL` retires. The DPC register transitions are pure functions on a value type, unit-tested without a timeline (sonnet, grafted).
- Span prefetch posts `DpColor` (if `IM_RD`) and `DpDepth` (if `Z_CMP`) reads up to `prefetchLead` spans ahead; the grant fills a `SpanSnapshot`.
- The pipeline processes `Segment`s: the stream positions of one span inside one span-RAM half (`span-ram.md`). A segment starts only when its snapshot is ready and its half is free; otherwise the RDP clock runs with GCLK off. `PixelEngine::shade` computes the segment's pixels at that time, with the noise LFSR at the exact RDP clock of each pixel.
- A full half, or the end of a span or primitive, triggers write-back: one burst per contiguous written run, end-trimmed, split at 128 B and 2 KiB rows; a fully rejected half posts nothing (`rdp-write-granularity.md`). The half frees when its last burst is granted.
- `G_PM_1PRIMITIVE` is a barrier: the next primitive's prefetch waits for the previous primitive's write-backs, plus `rdp.atomic-dead`. Without it, a prefetch can be granted before an overlapping write-back, and the stale read that the SDK warns about happens on its own.

paraLLEl-RDP and the Vulkan path leave the N64 core and the fork's build. VI output is ares's existing software VI filter, fed from the bytes the VI fetch bursts copied at their grant times.

### CPU timing seam (#15, #5, #6, #26, #10)

The VR4300 is single-issue and in-order, and every interlock and memory stall freezes the whole pipeline. So a stage simulator is not needed to get stage-exact timing. Each instruction gets one EX timestamp; IC, RF, DC and WB are fixed offsets from it; `ex(i) = ex(i-1) + 1 + stalls`. This is sonnet's stage-time recurrence with the offsets folded in, and fable's issue-time scoreboard with the stage identity made explicit; the three candidates describe one model. A register scoreboard (`gprReady`, `fprReady`, `hiloReady`, unit-free times) yields LDI, MFC0-as-load, MCI and the FPU forwarding bubble as one `max()` each. The parts that do need stage identity are explicit offsets:

- Memory happens at DC (`pipeline.dc()`), through `SysAD`.
- Fetch happens at IC, three slots ahead, in `FetchWindow`, which makes the self-modifying-code cases execute the old word.
- Exceptions charge by detection stage (5, 6 or 7 pclk; FPU arithmetic first pays its own latency).
- CP0 writes become visible after per-register delays (`Cp0Writes`), which covers the COUNT write, the one-instruction interrupt-sampling lag and Wired.
- COUNT and Random are functions of time (`TimedCp0`), and COMPARE is one scheduled event at the exact crossing, not a check per sync.

Where things live: interlocks in `Pipeline::issue`; cache in the existing `ICache`/`DataCache` with hit cost folded into the issue cycle and misses going to `SysAD::fill`; write buffer in `SysAD`; COUNT in `TimedCp0`. The only cost tables are `opTiming[]`, built from the decoder's `OpInfo` masks plus behavior rows, and the behavior rows themselves.

The CPU blocks inside its own call (`Timeline::await`) rather than parking and retrying with a pure plan phase (sonnet). Blocking keeps the interpreter's execute functions as they are; park-and-retry would require every instruction to compute its first shared touch before executing. Both give the same order because the CPU is the outermost frame either way.

The recompilers leave the timing build, CPU and RSP both. The interpreter is the reference by map rule; fact 3 says today's interpreter runs the 600-field bench in 8.5 s against a 120 s budget; and a recompiler that is bit-identical under this model needs exits at every horizon crossing and every interaction, which is the interpreter's step size during the busy part of every MM frame. Removing them deletes the second cost table, `JitInterleaving`, `jitClockTarget` and the slow-path double-charge class of bug outright. If the budget measurement (plan T16) fails, a block executor comes back only in quiescent windows (`ex + block's worst static cost < horizon`, slow paths calling the same `CpuMemory` functions), gated by a lockstep checker that compares Clock traces with the interpreter.

### RSP seam (#28, #10)

The RSP interpreter and its existing `Pipeline` (GPR/VR read-after-write, load-store stalls) are the RSP cost model, unchanged. A halted RSP is `Parked` and costs nothing. Its interactions use the issue pair's start time: DPC accesses catch the RDP up first, `MTC0` to the DMA length registers starts `SpDma`, BREAK and `SP_STATUS` raise MI at that time. SP DMA is a bus client posting 128 B bursts, so its rate comes from the RI model and the fitted overhead rather than today's 8 B per rclk. The +1.7% RSP recompiler divergence of #28 disappears with the recompiler; its two suspected causes (per-block DMA stepping and block overshoot) are exactly the two things this design forbids.

### Where parameters live and how verification attaches (item 6)

`ares/n64/timing/behaviors.tsv` is the single source. Its columns are id, value, unit, basis, reference, verify and note. Basis is one of measured, vendor, datasheet, wiki, rtl, derived, fit or assumption. `tools/n64-timing/behaviors.py` generates:

- `behaviors.hpp` with `Behavior::*` constants, converted to `Clock` units exactly. A non-integer value fails unless the row is a fit.
- `docs/spec/n64-timing.md` with one row per behavior. This is the map's spec.
- A per-behavior results table when the harness runs (`--results`), which the final spec assembly (plan T17) commits.

It fails on an empty reference, an empty verify list, a verify id missing from `tools/n64-timing/checks.tsv` (check id to suite, ROM or scene, selector, expectation source), or a value-less row that code references. A lint rejects timing literals in `ares/n64` outside the generated header, and its error message names the TSV. The spec and the code therefore cannot drift, and "no unverified status" is a build failure instead of a review comment. Assumption rows (tie-break rank, client ranks, VI and SP burst sizes, FIFO depth) are allowed but printed as assumptions in the spec, so they stay visible as calibration targets. A check id of the form `pending:<gate>` names a corpus the program cannot run (gate `build-corpora`) and prints as pending.

### Determinism (#27)

All ordering is by timestamp with fixed tie-breaks, and there is no GPU thread and no host clock. The remaining host-entropy uses get fixed values: CP0 Random becomes a function of time; `SP_PC` reads return the RSP's PC; the RDRAM current-calibration thresholds use a fixed value; the entropy seed is pinned; the cartridge RTC epoch is a fixed header value. measure-27 (running) enumerates any source this list misses; T2 absorbs its findings.

Two identical runs must produce byte-identical per-field stats and trace hashes, including the framebuffer hash once pixels are CPU-side. That check runs in every plan unit.

### Interface depth

`Timeline` exposes `catchUp`, `await`, `horizon`, `schedule` and `cancel`; it hides ordering, tie-breaks, nesting and bus safety. `Ri` exposes `post`, `complete` and `earliestLanding`; it hides arbitration, bank state, wire costs, refresh, the byte copy and the single owner of RDRAM. A device implements `granted()` and, if stepped, `readiness()` and `step()`. No device knows another device's clock, and no device charges time to a caller's `Thread` (today's `Memory::RCP::read` steps whichever thread is passed). The RDP's public surface is still DPC register read/write; everything inside is private to `RDPTimed`.

### What it deliberately does not do

- No cothreads and no host threads in emulation. The pixel engine runs on the emulation thread; deterministic span-parallel shading is a later optimization that must not change any output, checked by `det`.
- No windowed or statistical bus charging.
- No toggle, no fast path, no presentation renderer other than the software VI.
- No per-tc channel scheduling finer than the RI's rclk-edge decisions. The wire time is in tc; grants land on rclk edges.
- No MI propagation latency parameter, no arbitration presets, no calibration overlay file. Calibration edits the TSV.

### Run budget (item 7)

Estimate for 10 s emulated MM (600 VI fields, about 200 rendered frames). The CPU and RSP lines are anchored on fact 3; the rest are operation-count guesses that plan T9, T13 and T16 replace with measurements.

| Part | Work in 10 s emulated | Assumed host cost | Host time |
|---|---|---|---|
| CPU + RSP interpreters today (measured, fact 3) | whole run | | 8.5 s |
| Pipeline scoreboard + horizon check per instruction | about 600 M instructions | +5 ns | 3 s |
| `catchUp` alternation while the RSP runs | about 400 M calls | 3 ns | 1.2 s |
| RDP pixels | about 300 k px per rendered frame x 200 = 60 M px | 50-150 ns/px (MAME lineage, single thread; unmeasured) | 3-9 s |
| RDP segments, spans, commands | about 15 k spans/frame x 200 | 300 ns/span | 1 s |
| RI decisions + byte copies | about 100 k bursts/frame = 20 M | 50-100 ns | 1-2 s |
| Software VI compose, AI, PI, SI | small | | under 1 s |
| **Total** | | | **about 19-26 s** (4.6x to 6.3x headroom to 120 s) |

What must be measured, in order of risk: (1) ported pixel engine ns/pixel single-threaded on the MM stream (T9); (2) `catchUp` overhead and the scoreboard's per-instruction cost (T5, T7a, each re-records the MM wall time); (3) RI decision cost once the RDP posts its traffic (T13). If the T16 total exceeds 120 s, the levers in order are horizon tuning, deterministic span-parallel shading (output checked byte-identical by `det`), then the quiescent-window block executor (T-L).

## Synthesis decision

**Base: candidate-opus** (judge score 28 of 30; fable 21, sonnet 24; `judge.md`). It alone satisfies facts 1 and 2, has the simplest correctness argument, and its budget is the one fact 3 supports.

**Grafted from candidate-sonnet.**

- The RI moves the bytes at grant and `Rdram::ram` accessors are private to the RI, debugger and loader at compile time. Replaces opus's "clients copy in `granted()`", which was split ownership of RDRAM bytes. `Burst` gains `data` and `hidden` pointers.
- `TraceHash` and `tools/n64-timing/determinism.sh`, and the `--step-cap` run mode (sonnet's `maxActionsPerAdvance`): a run that catches up before every instruction must hash equal to the horizon-skipping run. Turns the exactness claim into a check.
- DPC register transitions as pure functions on a value type with a host unit test.
- Per-cluster expected nemu64 deltas in the CPU plan units (C2+C8 214, C1 439, C3+C4 222, C5/C9/C10/C11 28, SMC 7).

**Grafted from candidate-fable.**

- Constant rows opus lacked: PI (page setup, block writeback, IO busy), SI (write64, read64 base), AI fetch bytes, RCP register read, PIF RAM read, pipeline depth for unsynced attributes, noise open rows, TMEM load rate with its conflict, setter conflict, FIFO refill threshold and fetch burst, span-RAM geometry. Merged into `behaviors.tsv` with basis labels; a `conflict` is a note on the row plus the chosen value, not a status.
- Per-requester bus counters (`Ri::Counters`) for the bench readout and the debugger.
- The module map with the three call chains a reader must hold (`sketch/module-map.md`).

**Rejected.**

- fable: angrylion-rdp-plus (fact 1). 187.5 MHz master tick with `ri.quantize_rclk` (a rounding knob with no hardware source; 750 MHz holds tc exactly). The observer table (opus's on-stack floor rule orders the same accesses with one concept). `TimedIrq` with `mi.irqLatency` (no source; opus samples raises at `ex` with no parameter). `BurstPlan::split` returning a vector and `function<>` callbacks on the span path.
- sonnet: restoring the pre-`5f9804fb6` MAME RDP (older ancestor; cen64-jgemu is the maintained BSD-3 descendant with the DPS fit). Keeping paraLLEl as presentation and oracle (a second renderer in the tree with GPU-dependent output; snapper64 console captures are the reference, and a frame-dump triage aid is captured once before deletion). Keeping the RSP recompiler with an eligibility rule (fact 3 removes the need; it is a second RSP path to keep bit-identical). Park-and-retry CPU with a pure plan phase (more reader load for the same order). `Mi` as an agent with `mi.propagate` (invented parameter). Arbitration presets and the calibration overlay file (one mechanism: TSV rank rows). "No Python on the build host" (false; the generator is Python like romgen).

**Divergences the brief named, resolved.**

1. Time unit: 750 MHz LCM units (opus, sonnet). Fable's 187.5 MHz cannot hold a tc and needed a quantization knob.
2. CPU model: EX-anchored scoreboard with fixed stage offsets (opus), which is sonnet's recurrence collapsed and fable's scoreboard with stage identity. CPU is the outermost frame and blocks on its own transaction; no park-and-retry.
3. RDP source: port of cen64-jgemu `src/rdp` (BSD-3, fact 2). Not angrylion (fact 1), not the old ares MAME RDP (ancestor, slower, no DPS fit).
4. Arbitration default: refresh, then VI, then first-come first-served, as rank rows; strict orders are the same mechanism with distinct ranks. No presets.
5. Recompiler fate: both deleted from the build in T1. The quiescent-window block executor is a contingency after T16, never built speculatively.
6. paraLLEl: deleted from the N64 core and the fork's build (T10). Before deletion, T9 captures paraLLEl MM frame dumps at 20 checkpoints into `C:\Users\Scott\n64-timing\` as a triage aid, not a pass criterion.

## Tradeoffs accepted

- We accept an exact time-ordered scheduler that alternates CPU and RSP per instruction while the RSP runs, in exchange for ordering that no sync setting can change. The cost is the same per-instruction alternation the interpreter already pays.
- We accept removing both recompilers from the timing build in exchange for one cost model and no parity bugs. Fact 3 (8.5 s today against 120 s) makes this a measured bet, not a hope; T16 confirms it after the RDP lands.
- We accept a port of about 15k lines of third-party C into the core in exchange for pixels and timing from one deterministic engine. Pixel output will differ from paraLLEl where the lineages disagree; snapper64 console captures, not paraLLEl, are the reference for those differences.
- We accept 750 MHz absolute time units, a mechanical rename of every `step(n*2)` and `*3`, in exchange for exact tc, pclk and rclk arithmetic and no subtract-at-sync bookkeeping.
- We accept first-come first-served arbitration below VI as an assumption, labeled as such in the spec, in exchange for the fewest invented orderings until calibration exists.
- We accept primitive-level attribute snapshots at first, which misses the unsynced-attribute corruption offsets, in exchange for a simpler first RDP. T15 replaces it.
- We accept RDP rendering on the emulation thread in exchange for determinism by construction. Parallelism comes later, only if T16 needs it.
- We accept that checks whose only corpus is gated (`build-corpora`) print as pending in the spec rather than blocking the unit, in exchange for a plan that runs today. Each such row names its gate.

## Alternatives considered

- **Windowed occupancy** (charge each window's bus demand as a share of channel time). Hides ordering entirely from callers and is cheap, but contention then depends on window size, so the interpreter and any block executor disagree, which is #10's core finding. It cannot express the VI-bank row-miss effect or a CPU read waiting behind one specific RDP burst. Rejected.
- **Cycle lockstep** (tick every device every rclk, cen64/MiSTer style). Simplest interface (each device has `tick()`), exact ordering. But the RDP would have to render per clock, and the CPU and RSP pay a call per rclk even when halted or idle. Hides less than the event timeline, which gives identical ordering while idle devices cost nothing. Rejected on cost, with no accuracy difference.
- **Cothread per actor on ares's generic `Scheduler`.** Exact, and the natural shape for actors that block. It exposes a switch on every interaction and a stack per device. Since only the CPU ever blocks and it is always outermost, the stackless timeline gets the same ordering. Rejected as unneeded machinery.
- **Timestamped bus with a CPU-first sync loop** (keep `CPU::synchronize`, add timestamps to bursts only). Smaller change, but lagging devices still run whole windows in fixed order, so their mutual interactions (RSP polling `DPC_CURRENT` while the RDP fetches) stay window-ordered. Rejected: it fixes the bus and leaves the RSP-RDP back-pressure wrong, and that back-pressure is structural in MM (#21).
- **paraLLEl-RDP with per-span write counters and readback** for pixels. Keeps GPU speed and upscaling, but exposes a GPU sync point to timing on every span and leaves RDRAM written by another thread. Rejected for determinism and coupling.

## Implementation reconciliation

(Empty until implementation starts. Each unit's worker records accepted deviations here with the acceptance source.)

## Open questions and risks

- Is the cen64-jgemu renderer pixel-exact enough? It is fitted to snapper64 captures in the cases it names; its general agreement on MM scenes is unmeasured. T9 measures it against the hydra and snapper64 ports and keeps paraLLEl dumps as a triage aid. If it falls short, does the program accept MAME-lineage pixels, or fund a clean-room port of the disagreeing paths?
- The port's RDRAM seam is wider than the four pixel functions: TMEM load sources, `read_rdram_pair` and the rect pre-state restore also touch `m_rdram` (verified in `rdp_core.c`). T9 must list every site and T13 must redirect every one; the compile-time private accessor is what catches a miss.
- Should the RI per-burst overhead be one global value per direction, or per requester? The only fits come from SP DMA (hcs64 for reads, n64brew memset for writes, which conflict by 17%). Using them for RDP and VI bursts is an assumption.
- Does a pipeline freeze also freeze the MULT/DIV and FPU iteration counters? The sketch assumes they keep running (`Pipeline::freezeUntil`). No reference was found either way; a romgen test (DIV, then a D-miss, then MFLO) would settle it on hardware only.
- The cen64 span law (`14 + sum(px*129/128 + 12)`) was measured with an unknown othermode and probably includes memory time (Thar0's all-fail data puts the +12 mostly in memory). This design models memory explicitly, so the law becomes a check (T13 reproduces Thar0's table) rather than a cost term. If the full model cannot reproduce it, which term is wrong?
- Command FIFO depth: n64-systemtest's author note (CURRENT reaches START+240, 30 dwords) against MiSTer's 64. The sketch takes 30 as the only hardware-side hint. Is an author's note enough to build from, given the map's rule?
- Span-RAM half capacity at 16 bpp (16 or 32 pixels per half) is unmeasured (`span-ram.md` question 1). It changes segment count and stall points.
- Equal-time tie-break order between RCP blocks is a convention. No test ROM can observe it except through an exact tie. Is it acceptable as a labeled assumption?
- snapper64's console captures are git-lfs objects that are not fetched (verified: 128-byte pointer files). Fetching 682 MB of MIT data is a download, not a build; if the classifier blocks it, the snapper64 checks go pending under a new gate.

## Next implementation step

T0 and T1 in `plan.md`: record the harness baseline (MM both scenes, romgen nemu64 port) three runs each, then delete both recompilers from the build and show the per-field stats and nemu64 counts unchanged.
