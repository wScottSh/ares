# Build plan: timing core (synthesis)

Each unit is one branch in the linear stack (preferences line 12), started from the head of the previous unit's branch, delivered as a PR targeting that branch. Each unit is sized for one agent in roughly 3-6 hours and ends in a check that runs the built emulator or a generator self-test. Workers for units marked **hard** run on the program's strongest-judgment model (bus/scheduler, RDP engine, CPU pipeline core); the rest on the feature model; the verifier runs on a different model than the worker.

## Verification sources (fact 4, and nothing else)

| Prefix | Source | How it runs |
|---|---|---|
| `nemu64:<set>/<group>` | romgen's port of nemu64-test timing, cycle, cop0hazard (unit romgen, in flight) | `python tools/n64-timing/romgen/build.py --suite nemu64`, then the suite runner; per-test TSV and `Timing: Failed X of Y` |
| `bench:<name>` | romgen microbench suites added by this plan (unit R1) | same generator; each ROM prints its measurement through emux XLOG; expected value in `checks.tsv` |
| `thar0:<config>` | romgen port of Thar0/RDP-Timing-Tests (MIT), 100 fill-rect configs with hardware min/avg/max from `sample_results.txt` (unit R2) | per-config BUFBUSY/PIPEBUSY compared to `hw_data` |
| `snapper:<test>` | romgen port of snapper64 (MIT) test-mode and surface tests, console dumps from `assets/*.7z` (unit R3, needs `git lfs pull`) | framebuffer or DPS span-buffer bytes compared to the dump |
| `rdpstat:<test>` | romgen port of n64-systemtest `tests/rdp` (MIT) DPC status sequencing, and repeater64 no-sync references (unit R4) | self-checking ROM |
| `noise:<set>` | Thar0/RDP-Noise datasets A, B, C (arrays in `rdp_noise_lfsr.c`, Unlicense) | host unit test on the LFSR; plus a romgen 1016-px rect ROM |
| `pidma:logs` | prebuilt `rasky_n64_pi_dma_test/pi_dma_test.z64` and its 64 golden logs | ROM self-checks within 10%; harness replays logs against the model |
| `hydra:<test>` | six prebuilt `hydra-emu_rdp-tests/*.z64` | render and dump; triage aid only (its PNGs are emulator output, verified in its README) |
| `mm:<scene>` | mmbench (unit mmbench, in flight): file-select and South Clock Town, 600 fields, per-field TSV `frame origin width depth fb_hash cpu_cycles rsp_busy_clocks` plus `trace_hash` from T2 | `tools/n64-timing/mmbench/run.sh` |
| `det` | two runs of every `mm:` scene byte-identical (stats and trace hash) | `tools/n64-timing/determinism.sh` |
| `stepcap` | `n64-run --step-cap` run equals the normal run byte for byte (from T5) | same script, second mode |
| `unit:<name>` | host C++ tests under `tools/n64-timing/tests/` (CMake target `n64-timing-tests`) | `ctest` |
| `gen` | `behaviors.py --check` and `lint-literals.py` | CMake step |
| `pending:<gate>` | a check whose corpus is behind the `build-corpora` gate (libdragon or cargo builds) | prints as pending in the spec; never counts as verified |

Cited reference values from corpora we cannot run or copy (n64-systembench, no license) are used only as numbers in `checks.tsv` for romgen ROMs that make the same measurement.

Standing checks in every unit from the point they exist: `det`, `nemu64` counts not higher than the previous unit (each newly failing test listed with cause), `gen`, `stepcap` (from T5), MM wall time recorded.

## Phase 0: baseline and subtraction

**T0. Baseline measurement.** normal. Depends on: romgen, mmbench.
- Goal: the numbers every later unit is compared with.
- Files: none in the repo. Writes `C:\Users\Scott\n64-timing\results\baseline\`.
- Check: MM both scenes, 600 fields, interpreter, 3 runs each, wall time per run (expect about 8.5 s, fact 3); `det`; romgen nemu64 counts (expect 924/9/5 or the romgen report's explained divergence); `pidma:logs` passes on today's core or its failures are listed; `hydra:*` dumps saved with `--rdp vulkan` as the triage aid for T9 (601 distinct fb hashes expected).

**T1. Remove both recompilers from the build.** normal. Depends on: T0.
- Goal: one CPU path and one RSP path.
- Files: delete `cpu/recompiler*.cpp`, `rsp/recompiler.cpp`, `accuracy.hpp` JIT switches, `JitInterleaving`, `jitClockTarget`, `forceSynchronize`, branch-to-self charging; `n64-run --cpu` option removed.
- Check: nemu64 counts equal T0 interpreter exactly; `mm:*` per-field TSV equal T0 interpreter byte for byte; `det`.

**T2. Determinism floor and trace hash.** normal. Depends on: T1, measure-27.
- Goal: no host-dependent input reaches emulated state, and a hash exists that proves it.
- Files: `system/system.cpp` (pinned seed), `rdram/rdram.cpp` (fixed cc thresholds), `cpu/interpreter-scc.cpp` (Random as a time function, placeholder rule until T7c), `rsp/io.cpp` (SP_PC), `cartridge/rtc.cpp` (fixed epoch); new `timing/verify.hpp/.cpp` (`TraceHash`); `n64-run` gains a `trace_hash` stats column; `tools/n64-timing/determinism.sh`.
- Check: `det` both scenes with the new column; every source measure-27 lists is addressed or listed as out of scope with reason; nemu64 Random tests that moved are listed.

## Phase 1: scaffold

**T3. Behavior table, generator, check manifest, literal lint.** normal. Depends on: T2.
- Goal: one source for every constant, the spec, and the check list.
- Files: `ares/n64/timing/behaviors.tsv` (the merged table in `sketch/timing/behaviors.tsv`), `tools/n64-timing/behaviors.py` (emits `behaviors.hpp`, `docs/spec/n64-timing.md`, `--check`, `--results`), `tools/n64-timing/checks.tsv`, `tools/n64-timing/lint-literals.py` with an allowlist of today's literals, CMake hook. Every existing cost moves into a row with basis `legacy` until its unit replaces it.
- Check: `gen` passes; removing a reference, adding an unknown verify id, adding a literal, and referencing a value-less row each fail with a message naming the fix (self-test in the script); the generated spec is committed and `--check` proves no manual edit.

**T4. Clock rebase to absolute 750 MHz units.** normal, codemod. Depends on: T3.
- Goal: one absolute `Clock` everywhere, exact tc/pclk/rclk arithmetic.
- Files: `n64.hpp` (`Thread::clock` becomes `Timing::Clock`), every `step(n*2)` becomes `pclk(n)`, RCP `*3` becomes `rclk(n)`, `vi/vi.cpp` and `ai/io.cpp` on `VclkAccumulator`; the codemod script committed under `tools/n64-timing/codemods/`.
- Check: nemu64 identical to T2; `mm:*` identical to T2 except the documented AI period change (+33 ppm removed), listed by field; `det`.

**T5. Timeline scheduler.** hard. Depends on: T4.
- Goal: `Timing::Timeline` replaces `CPU::synchronize` and the nall relative queue.
- Files: new `timing/timeline.hpp/.cpp`; `cpu/cpu.cpp` (catchUp per instruction past `horizon()`), VI/AI/PI/SI/timers as absolute events, RSP and RDP as actors (RDP still renders synchronously at `DPC_END`); `n64-run --step-cap`.
- Check: `unit:timeline` scripted-actor tests (ordering invariant, tie-breaks, nesting bound, no step past an on-stack actor, Parked never stepped); `stepcap` equal on both MM scenes and on the nemu64 ROMs; nemu64 not worse (the queue-event skew fix may move PI/SI-timed tests, each listed); `det`; MM wall time recorded against T0.

## Phase 2: memory system

**R1. romgen microbench suite.** normal. Depends on: romgen. Parallel with T3-T5.
- Goal: the `bench:*` ROMs the memory units check against.
- Files: `tools/n64-timing/romgen/suites/bench/` with `mi-memset-uncached`, `mi-memset-cached`, `mi-memset-rspdma`, `sp-dma-sweep` (8 B to 4 KiB, both directions, offsets around 2 KiB rows), `pi-dma-sizes` (8 B, 128 B, 1 KiB, 64 KiB), `uncached-vs-hpos`, `dirty-row-sweep`, `dirty-miss-isolated`, `rdp-sync-sweep`, `rdp-setter-sweep`, `rdp-atomic-sweep`, `rdp-rectn` (cen64 RECTN 320x6 and DUTY 320x240); expected values in `checks.tsv` with their citations.
- Check: each ROM builds deterministically (same bytes twice), runs on today's core, and prints its measurement through XLOG; the pass criterion for this unit is the measurement format, not the value.

**T6. RI arbiter and the SysAD port.** hard. Depends on: T5, R1.
- Goal: RDRAM has one owner of bytes and time; every CPU access leaves the caches through one in-order port.
- Files: new `ri/bus.hpp/.cpp` (`Ri`, banks, NEC wire costs, refresh posted at VI HSYNC, counters, byte copy at grant), new `cpu/sysad.hpp/.cpp` (4-entry write buffer, reads behind writes, fill-first dirty miss, posted register writes effective at drain); `rdram/rdram.hpp` accessors private with a friend list; DMA engines keep direct access until T8 as the one allowed exception (named friends); D-hit +1 removed.
- Check: `unit:ri-cost-table` (read hit 14/18/26/42/74 tc for 1/2/4/8/16 octbytes; write hit 8/12/20/36/68; clean and dirty miss columns from `rdram-bus-arbitration.md`); `nemu64:timing/Load from uncached (VI off)` 32; `nemu64:timing/Load Miss (VI off)` 41; `nemu64:timing/Cached loads and store` 19/19; `nemu64:timing/Uncached write buffer` 1 pclk each for 1-4 stores; `bench:mi-memset-uncached` 18.4 pclk per SD (n64brew 25.7 ms/MiB); `bench:mi-memset-cached` 71.2 pclk per line; `bench:dirty-miss-isolated` reports the stall (no hardware value; reported). VI-on same-bank 36 is expected-fail until T11 and listed.

**T7a. Pipeline scoreboard.** hard. Depends on: T6.
- Files: `cpu/pipeline.hpp/.cpp` (`OpTiming` from the decoder's `OpInfo`, `Pipeline::issue/retire`, LDI, DCB, MCI, FPU forwarding, trivial-operand FPU latency); `step()` deleted from `interpreter-*.cpp`.
- Check: nemu64 groups "CPU register dependency", "COP1 register dependency", "COP1 instruction (32/64 bit)" non-exception rows, "Individual instructions", "Data cache Size", "Cached loads and store" pass; timing failures fall by at least 214 (C2+C8) and 222 (C3+C4) against T6; MM wall time recorded (scoreboard cost).

**T7b. Exceptions and bubbles.** normal. Depends on: T7a.
- Files: `cpu/pipeline.cpp` (`fault` stage costs 5/6/7, FPU exception = latency + 5, ERET refill, nullified likely slot, CACHE op costs), `cpu/exceptions.cpp`.
- Check: nemu64 "Exceptions", "COP1 JustFire", "Likely branch", the CACHE cases pass; failures fall by at least 439 (C1).

**T7c. CP0 timing.** normal. Depends on: T7b.
- Files: `cpu/pipeline.cpp` (`Cp0Writes`, `TimedCp0`: COUNT write landing, Random as a time function, COMPARE as one event, one-instruction interrupt sampling lag, CTC1 CE from the following instruction).
- Check: `nemu64:cop0hazard` 5/5 pass; "Compare (signalling 2)", "Random (decrement)", "Random (masking)", the CTC1 cycle cases; failures fall by at least 28 (C5, C9, C10, C11).

**T7d. Fetch window and I-fills through SysAD.** normal. Depends on: T7c.
- Files: `cpu/pipeline.cpp` (`FetchWindow`), `cpu/cpu.hpp` (I-miss through `SysAD::fill`, no inline copy).
- Check: `nemu64:cycle` 13/13 (7 SMC cases); nemu64 timing reaches 0 failures, or each remaining failure is listed with cause and the missing reference; MM boots both scenes (overlay loads use DMA then `osInvalICache`).

**T8. DMA engines as bus clients.** normal. Depends on: T6. Parallel with T7a-d (disjoint files).
- Files: `rsp/actor.hpp/.cpp` (`SpDma`, 128 B bursts, fitted per-direction overhead), `pi/dma.cpp` (`PiDma` block by block with the BSD formula and the two known bugs fixed), `si/dma.cpp` (`SiDma`), `ai/ai.cpp` (`AiDma` at the rational DAC rate). The friend list on `Rdram::ram` shrinks to RI, debugger, loader.
- Check: `pidma:logs` (ROM self-check passes; harness replay within ±3% of min and max for sizes 8 to 382 B); `bench:pi-dma-sizes` 193/1591/12168/777807 RCP within 1% (cited from n64-systembench `main.c:572-608`); `bench:sp-dma-sweep` 6.5 B/rclk writes (n64brew memset) with the hcs64 5.55 conflict reported; `unit:rdram-private` (a test translation unit that reads `rdram.ram` from a device fails to compile); MM boots both scenes; `det`.

## Phase 3: one RDP

**R2. romgen port of Thar0 RDP-Timing-Tests.** normal. Depends on: romgen. Parallel with Phase 2.
- Files: `tools/n64-timing/romgen/suites/thar0/` (100 configs from `src/test_main.c`, VI forced NTSC, lone-FULLSYNC baseline subtracted as in the original), `hw_data` from `compare.py` into `checks.tsv`, MIT notice and commit `a81ced93b28d` in the suite README.
- Check: ROM builds deterministically; on today's core every config reports a value (all zero today, since the RDP has no time); the pass criterion is the format.

**R3. romgen port of snapper64 test-mode and surface tests.** normal. Depends on: romgen.
- Files: `tools/n64-timing/romgen/suites/snapper/` (RDP Test-Mode Span Tri, Test-Mode RW, Fill Mode Tri Sweep, RDPRectNoSync), a fetch script for the LFS assets into `C:\Users\Scott\n64-timing\corpora\snapper64\` (682 MB, MIT), `.7z` decode, MIT notice and commit `e1cd8a61fc43`.
- Check: assets fetched and decoded (7094 files) or the fetch is blocked and every `snapper:*` check becomes `pending:snapper-lfs`; the ROMs run and dump framebuffer or DPS bytes in the compare format.

**R4. romgen port of RDP status tests.** normal. Depends on: romgen.
- Files: `tools/n64-timing/romgen/suites/rdpstat/` (n64-systemtest `tests/rdp/mod.rs` START/END/STATUS sequencing, MIT; repeater64 `RDPNoSync1C` and fill-color latching with its 65 `.test` references, MIT headers), notices and commits in the README.
- Check: ROMs build and run; the sequencing tests report pass/fail counts on today's core (expected to fail on END_PENDING and DMA_BUSY; counts recorded).

**T9. Pixel engine port, synchronous.** hard. Depends on: T5 (call site only), T0 dumps.
- Goal: pixels on the CPU side from one deterministic engine.
- Files: port cen64-jgemu `src/rdp` (BSD-3, notice retained, license and commit `2f8d7bc` recorded in the PR) into `ares/n64/rdp/engine/`, called at `DPC_END` where paraLLEl is called today; in this unit it reads and writes `rdram.ram` directly as a named friend; the software VI output path is used; `n64-run --dump-frame N FILE`. The PR lists every `m_rdram` touch site in the port (pixel read/write, Z, TMEM load sources, `read_rdram_pair`, rect pre-state restore) because T13 must redirect each.
- Check: `hydra:*` dumps saved and compared with T0's paraLLEl dumps, every differing region attributed to a cause (triage, not a gate); `snapper:fill-tri-sweep` and `snapper:test-mode-rw` content dumps match the console (or pending); MM frame dumps at 20 fixed fields compared with T0's paraLLEl dumps, differences attributed; `det` including `fb_hash`; measured ns per pixel on the South Clock Town stream recorded (budget input, risk 1).

**T10. Remove paraLLEl and Vulkan from the N64 core.** normal, subtraction. Depends on: T9.
- Files: delete `ares/n64/vulkan/`, the vendored `parallel-rdp` tree and its build wiring for the N64 core; `n64-run --rdp` option removed.
- Check: the fork builds without Vulkan; `det` byte-identical over 600 fields with `fb_hash`, which is where #27's 1% run-to-run gap must be zero; `fb_hash` takes more than 4 distinct values per scene (pixels are drawn).

**T11. VI fetch on the bus.** normal. Depends on: T8, T10.
- Files: `devices/events.hpp/.cpp` (`ViFetch` posts 3 x ceil(width*bpp/128) bursts per active output line from H_START; refresh at HSYNC), `vi/vi.cpp` (compose from fetched bytes), `vi/io.cpp` (bit 16).
- Check: `nemu64:timing/Load from uncached (VI on, same bank)` 36 median; "Load Miss (VI on)" 42; `bench:uncached-vs-hpos` shows one about-53-rclk refresh holdoff per line in HBLANK; `Ri::Counters` for MM shows VI 6.5-9% of channel time and refresh 1.3-1.4% (reported against the research bands); MM `fb_hash` unchanged from T10 except fields where tearing is expected (listed).

**T12. Timed DPC front end.** hard. Depends on: T10, R2, R4.
- Files: `rdp/timed.hpp/.cpp` (`Dpc` as pure transitions, START/END double buffering, `END_PENDING`, `DMA_BUSY`, `TMEM_BUSY` with the `data == 7` read fixed, counters as time functions, `CommandFetch` as a `DpCommand` client into a 30-dword FIFO, setter/sync/primitive-base costs, DP IRQ at `SYNC_FULL` retire); primitives still render whole at dispatch with span compute clocks only.
- Check: `unit:dpc-regs` against the n64-systemtest expectations; `rdpstat:*` sequencing passes (`CBUF_READY|PIPE_BUSY|START_GCLK` idle pattern, START only if not pending); `nemu64:rsp_timing/Clock CPU vs RDP` (100,000 COUNT = 133,333 ± 20 DP_CLOCK); `thar0:alpha-fail-1cycle` exactly 77,772 and `thar0:alpha-fail-2cycle` exactly 155,052 (pure compute, min = avg = max on hardware); MM `ARES_DPLOG` trace: stall C/D loops iterate, `DPC_CURRENT` trails `DPC_END`, the DP IRQ lands after the gfx task ends, `START` written while `START_VALID` = 1 at least once per lap where the ring wraps.

**T13. RDP memory interface.** hard. Depends on: T11, T12, R3.
- Files: `rdp/timed.cpp` (snapshots, span-RAM halves, segments, write runs, TMEM loads through the Z half, fill bursts, atomic barrier); every `m_rdram` touch in the port redirected to snapshots and halves; `Rdram::ram` friend list shrinks to RI, debugger, loader; the literal-lint allowlist must be empty here.
- Check: `thar0:*` full table of 100 configs, each within the hardware min/max band (plain write 1-cycle min 80,462 BUF; IM_RD 1-cycle 163,436; FB+ZB same bank 274,646 vs separate 225,518), residuals reported, not tuned away; `snapper:span-tri` 216/216 DPS dumps; `rdpstat:1prim` stale-read cases (four stacked image-read rects, both cycle modes); `bench:rdp-rectn` reports the model's RECTN 320x6 and DUTY against cen64's 2021 and 80,287 (reported, not asserted; the law's provenance is doubted in `jgemu-dpc-probe.md`); `bench:rdp-atomic-sweep`, `bench:rdp-sync-sweep` 50/33/25; MM GCLK-off share per frame reported next to F3DEX3's "half to two thirds"; MM wall time recorded (risk 3).

**T14. Noise LFSR.** normal. Depends on: T13.
- Files: `rdp/timed.cpp` (`NoiseLfsr`, degrees 29/28/27, all-ones at reset, one step per RDP clock including stalls, GF(2) jump); the port's seeded-hash noise deleted; combiner NOISE and `G_AD_NOISE` read it at each pixel's RDP clock.
- Check: `noise:a`, `noise:b`, `noise:c` reproduce bit for bit from reset in `unit:noise-lfsr`; the romgen 1016-px rect ROM dumps the sequence and it matches dataset A up to the open pixel-clock offset row; `hydra:noise` renders and is deterministic across runs.

**T15. Unsynced attribute sampling.** normal. Depends on: T13.
- Files: `rdp/timed.cpp` (replace the per-primitive attribute snapshot with per-stage sampling offsets, n64brew table 0 to 29 clocks, `rdp.pipeline-depth`).
- Check: `rdpstat:nosync-1cycle` matches all 65 repeater64 references; `snapper:rect-nosync` captures (cen64's 7332/7332 hazard set) match or pending.

## Phase 4: budget, bench, spec

**T16. Run budget.** normal. Depends on: T14.
- Files: profile only unless the number fails. Levers in order: horizon tuning, deterministic span-parallel shading (output byte-identical by `det`), then T-L.
- Check: `mm:*` 600 fields at most 120 s wall per scene, three runs, median reported with the limiting component named (benchmark-checklist); `det` and `stepcap` still pass after any lever.

**T17. MM bench integration and spec assembly.** normal. Depends on: T15, T16.
- Files: `cpu/emux.cpp`, `rsp/emux.cpp` (per-requester bus counters and per-behavior provenance in the readout), `tools/n64-timing/mmbench/` (readout columns), `behaviors.py --results` run over every suite's results into `docs/spec/n64-timing.md` (one row per behavior with basis, reference, check, result or `pending:<gate>`), a closure comment draft for map #1 listing every pending row and its gate.
- Check: every TSV row has a result line or a named gate; `--check --results` passes; the spec is the generated file with no manual edit; the bench report lists per-scene field times and the provenance table.

**T-L. Lockstep checker and quiescent block executor.** hard. Only if T16 fails.
- Files: a block executor that runs only while `ex + block worst static cost < horizon()` and calls the same `CpuMemory` and `Pipeline` functions; a checker that runs the interpreter and the executor side by side.
- Check: per-instruction Clock traces equal over the nemu64 corpus and both MM scenes; any difference fails.

## Dependencies

```
romgen ---> T0 -> T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7a -> T7b -> T7c -> T7d
mmbench -/                              R1 -/     \-> T8 ----------------> T11 -> T13 -> T14 -> T16 -> T17
                                                  T5 -> T9 -> T10 -> T12 -/      T13 -> T15 -/
romgen -> R2, R3, R4 (parallel with Phase 2; R2 and R4 feed T12, R3 feeds T13)
```

T7a-d and T8 touch disjoint files after T6 and can run in parallel worktrees, as can T9 after T5 and R1-R4 after romgen. The linear stack still lands them one after another; the coordinator orders the stack by readiness.
