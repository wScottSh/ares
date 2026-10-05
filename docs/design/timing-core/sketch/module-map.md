# Module map (synthesis)

Paths are under `ares/n64/` unless stated. New files are marked (new). Deleted files are listed at the end.

| Path | Owns | Reads from | Writes to |
|---|---|---|---|
| `timing/clock.hpp` (new) | `Clock` (750 MHz units), `tc/pclk/rclk`, `VclkAccumulator` | nothing | nothing |
| `timing/timeline.hpp/.cpp` (new) | `Timeline`, `Actor`, `Readiness`, `ActorId` tie rank, the event heap, `stepCap` | actors' `readiness()` | actors via `step()` |
| `timing/verify.hpp/.cpp` (new) | `TraceHash` | every step and grant | the `trace_hash` stats column |
| `timing/behaviors.tsv` (new) | every hardware constant with basis, reference, check, note | nothing | generates `behaviors.hpp`, `docs/spec/n64-timing.md` |
| `ri/bus.hpp/.cpp` (new) | `Ri`: pending bursts, grant order, bank state, refresh hold, wire costs, per-requester counters, the byte copy at grant. The only writer of `rdram.ram` among hardware clients | `Behavior::*`, `RI_REFRESH.En` | `rdram.ram`, clients' buffers, `granted()` |
| `rdram/rdram.hpp` | `ram` data accessors private; friends `RI::Ri`, `Debugger`, `Loader` | | |
| `cpu/pipeline.hpp/.cpp` (new) | `OpTiming`, `Pipeline` scoreboard, `FetchWindow`, `Cp0Writes`, `TimedCp0` | decoder `OpInfo`, `Behavior::*` | `pipeline.ex`, scoreboard |
| `cpu/sysad.hpp/.cpp` (new) | `SysAD`: write buffer and read port as one queue | `Ri` grants | RI bursts, RCP register writes at drain |
| `cpu/cpu.cpp` | `CPU::main`, `CPU::instruction` per `master.hpp`; `synchronize()` deleted | `timeline.horizon()` | `timeline.catchUp` |
| `cpu/interpreter-*.cpp` | pure execute functions; all `step()` calls removed | | |
| `rsp/actor.hpp/.cpp` (new) | `RSPActor`, `SpDma` | `rsp.pipeline`, SP registers, `ri.earliestLanding` | RI bursts naming DMEM/IMEM bytes, MI::SP |
| `rsp/interpreter-scc.cpp` | DPC and DMA COP0 accesses call `timeline.catchUp(time, RSP)` first | | |
| `rdp/timed.hpp/.cpp` (new) | `Dpc`, `CommandFifo`, `CommandFetch`, `Primitive/Span/Segment`, `SpanSnapshot`, `SpanRamHalf`, `NoiseLfsr`, `RDP` actor | `PixelEngine`, `Ri` grants | RI bursts (command, prefetch, write-back, TMEM, fill), MI::DP, DPC state |
| `rdp/engine/` (new, ported) | cen64-jgemu `src/rdp` as `PixelEngine`; reads snapshots and staging, writes halves and TMEM; never `rdram.ram` | snapshots, TMEM, mode state | halves, TMEM |
| `rdp/io.cpp` | forwards to `dpc.read/write` after `timeline.catchUp` | | |
| `rdp/render.cpp` | deleted: the decoder moves into `timed.cpp`; the empty primitive handlers go | | |
| `devices/events.hpp/.cpp` (new) | `EventKind`, `ViFetch`, `AiDma`, `PiDma`, `SiDma` | VI/AI/PI/SI registers | RI bursts, MI interrupts, VI line buffers |
| `vi/vi.cpp` | line timing on `VclkAccumulator`; software scanout from `ViFetch` line buffers | | |
| `n64.hpp` | `Thread` replaced by `Timing::Clock` on each device; nall `queue` removed | | |
| `cpu/emux.cpp`, `rsp/emux.cpp` | bench readout gains `Ri::Counters` per requester and per-behavior provenance | | |
| `tools/n64-timing/behaviors.py`, `checks.tsv`, `lint-literals.py`, `determinism.sh`, `codemods/`, `tests/` (new) | the levers: generator, check manifest, literal lint, determinism script, the clock-rebase codemod, host unit tests | | |

Deleted from the build: `cpu/recompiler*.cpp`, `rsp/recompiler.cpp`, `accuracy.hpp` JIT switches, `vulkan/` and the vendored `parallel-rdp` tree for the N64 core, `rdp/render.cpp`, `n64-run --cpu` and `--rdp` options.

## Call chains a reader must hold in their head

Three chains cover every timed interaction. No chain needs more than three files.

1. **CPU instruction.** `CPU::instruction` -> `Pipeline::issue` -> (`timeline.catchUp` if past the horizon -> other actors' `step` -> `Ri::step` grants -> `granted`) -> execute -> (`SysAD::read/store/fill` -> `timeline.await`) -> `Pipeline::retire`. Files: `cpu/cpu.cpp`, `cpu/pipeline.cpp`, `cpu/sysad.cpp`. The bus is a fourth only when the instruction misses or is uncached.
2. **RSP instruction with a DPC access.** `RSPActor::step` -> `RSP::instruction` -> `timeline.catchUp(time, RSP)` -> `RDP::step` up to `time` (may post bursts and block; `Ri::step` grants in order) -> `dpc.read(DPC_CURRENT, time)`. Files: `rsp/actor.cpp`, `rdp/timed.cpp`, `ri/bus.cpp`.
3. **RDP span.** `RDP::step` -> command processor dispatch -> `PixelEngine::dispatch` (edge walk) -> prefetch bursts (`ri.post` naming a `SpanSnapshot`) -> `Ri::step` copies the row and calls `granted` -> `PixelEngine::shade` into a half at pipeline time -> `writeRuns` posts write-back bursts naming the half's bytes -> `Ri::step` copies into `rdram.ram` -> `granted` frees the half. Files: `rdp/timed.cpp`, `rdp/engine/*`, `ri/bus.cpp`.

There is no second way to reach RDRAM (the compiler enforces it), no second clock, and no second cost table.
