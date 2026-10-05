# Cross-judge: timing core candidates

Judge: design-synth (Fable 5.1). I wrote candidate-fable in an earlier run and scored it by the same rubric as the others. Every candidate was read end to end (rationale, plan, every sketch file). Facts 1-4 from the brief are binding. Items I checked first-hand this session are marked (verified); the rest is read from the candidate text.

Checks run this session:

- cen64-jgemu clone at `2f8d7bc`: `LICENSE` is BSD-3 (Stachecki 2015, Carmichael 2025-2026). `src/rdp` is 14,905 lines across 19 files. `rdp_core.c` touches `m_rdram` at the pixel read/write and Z functions (lines 1127-1300, 5723-5940) and also in the TMEM load paths (about lines 4069-4410), a rect pre-state restore (4638) and `read_rdram_pair` (1392). Its noise is paraLLEl's seeded hash (`rdp_core.c:58-89`), not the hardware LFSRs. (verified)
- ares `5f9804fb6` removed the MAME RDP and 32 lines of `LICENSE`; the commit message says "too slow to be usable". (verified)
- Python 3.14.4 is on PATH (`python --version`). Candidate sonnet's plan assumes "Build host has no Python"; that is wrong. (verified)
- Harness today: MM 600 fields, interpreter, `--rdp none`, 8.4-8.5 s wall, byte-identical stats across runs; recompiler 1.44 s (`reports/harness.md`, fact 3). (read)
- Available ROMs in `C:\Users\Scott\n64-timing\scratch\r29\clones`: prebuilt `rasky_n64_pi_dma_test/pi_dma_test.z64`, six `hydra-emu_rdp-tests/tests/*/*.z64` (reference PNGs are emulator output per its README), `bigbass1997_n64-tests/Timing/ReadsWrites/Timing-ReadsWrites-Test.z64`. snapper64 `assets/*.7z` are git-lfs pointer files (128 bytes each), not fetched. Thar0 RDP-Timing-Tests and RDP-Noise are source only. (verified)

## Scores

Scale 1-5 per row. One line of reason per cell.

| Row | opus | fable | sonnet |
|---|---|---|---|
| 1 Exactness | **5**. Conservative discrete-event timeline, one invariant, fixed tie rank, request latency >= 1 unit so a decision never races an equal-time post. No window anywhere. | **4**. I1-I3 give the same order-by-timestamp property. Loses a point for `ri.quantize_rclk`, a knob with no hardware source that rounds every wire cost, and for 187.5 MHz units that cannot hold a tc. | **5**. Earliest-timestamp-first with no quantum, plus a test hook (`maxActionsPerAdvance` 1 vs 0 must hash equal) that turns sync independence into a runnable check. |
| 2 Coverage | **5**. Every map decision has a named structure and a plan unit: #2 command costs, #3 segments/GCLK, #4 Ri, #5/#6/#26 pipeline+SysAD, #7 clients, #8 CommandFetch/DPC_CURRENT, #12/#17 write runs, #18 NoiseLfsr, #19 atomic barrier, #20 halves, #22 ViFetch, #24 Clock, #27 det, #28 RSPActor, unsynced attributes U15. | **5**. Same breadth, and the fullest constants table (94 rows incl. PI/SI/AI, pipeline depth, noise open rows, MI latency). | **4**. Broad, but unsynced-attribute sampling (#2 s.3.7, `pipelineDepthClk`) has no plan unit, and Mi gets a propagation-latency parameter the research never asked for. |
| 3 Interface depth, ownership | **4**. Small surfaces (`Timeline`: 5 calls; `Ri`: 3 calls; device: `granted`). Red flag: clients copy bytes to and from `rdram.ram` inside `granted()`, so RDRAM bytes have N writers, not one. `Ri::cpuCompletion` "at most one at a time" is a special case. | **4**. `Actor` (3 virtuals), `Bus::request`, `observe`. Red flags: observer table is a second ordering concept next to horizons; `Bus::peek/poke` plus "the bus moves no bytes for DP_DRAW"; `BurstPlan::split` returns a `vector` per request and `renderSpan` takes a `function<>` per span, both on the hot path. | **5**. The channel applies the payload at grant, so RDRAM bytes have one writer. `Rdram::ram` accessors private to the channel, debugger and loader, so a bypass fails to compile. `busCost` is pure and unit-testable. `DpcRegs` pure transition functions. Cost: plan/park makes the CPU interpreter carry a pure plan phase before execute, which is real reader load. |
| 4 Plan quality | **4**. 18 units, subtraction first (U1 removes both recompilers), three standing checks (det, nemu, gen) per unit, literal-lint allowlist that must reach empty. Several checks name corpora fact 4 does not provide (n64-systembench, n64-systemtest ROMs, snapper64 ROM) without saying how they get built. `bench:*` via "extend build-rom.py" ignores the romgen unit that exists for exactly this. | **3**. 14 units, well ordered, but sweep ROMs are "built with libdragon" (blocked, fact 4), systembench rows are cited as checks, and unit 1 bundles the timeline skeleton, both recompiler deletions and the Vulkan removal into one PR. | **3**. Sub-units with per-cluster expected deltas are the best-specified CPU checks of the three. But the plan is built on "no Python" (false), uses libdragon rdpq tests and systembench, keeps the RSP recompiler and then spends a unit proving it (U10), and G1 (3 Mpx/s) gates on a number no unit measures before U7. |
| 5 License, provenance | **5**. cen64-jgemu BSD-3, confirmed by fact 2. angrylion correctly rejected on its MAME license. Notice retention and PR record named. | **1**. Picks angrylion-rdp-plus on the README's MIT claim. Fact 1: the repo ships the old MAME non-commercial license. Out. The fallback (MAME RDP, BSD-3) is mentioned in one clause. | **3**. Restores ares's own MAME RDP (BSD-3, compatible), so no violation. Admits "I did not verify any of these licenses". Dismisses cen64-jgemu as "license not verified" when its LICENSE is one file. The restored code predates the snapper64-fitted DPS fixes and was removed as "too slow". |
| 6 Budget realism vs fact 3 | **5**. Estimate 15 s total, CPU line 6 s at 10 ns/instr. Fact 3 measured 8.5 s for today's whole interpreter run, so the CPU line is in the right range. Names the three measurements in risk order. | **4**. Estimate 30 s (range 30-90) with CPU at 30 ns/instr, about 2x pessimistic against fact 3 but with the right gate (unit 0 first). | **4**. Estimate 60 s (range 35-110). Channel at 120-200 ns per request and RDP at 100-300 ns/px are pessimistic, and the RSP recompiler is kept for a gain that fact 3 makes unnecessary. Correctly identifies the 12x budget. |
| **Total** | **28** | **21** | **24** |

## Base

**candidate-opus.** It is the only candidate that satisfies facts 1 and 2 as written, it has the highest exactness and coverage, and its budget estimate is the one fact 3 supports. The arena procedure says to pick the base a maintainer can extend without breaking invariants; opus's single invariant (catch everyone up to `t` before interacting at `t`) is the shortest correctness argument of the three.

Where opus is weaker than a loser, the loser's piece is grafted (see `rationale.md`, Synthesis decision). The two grafts that matter: sonnet's single-writer RDRAM (channel copies the bytes, accessors private at compile time) fixes opus's one real red flag, and sonnet's trace hash plus step-cap invariance test turns opus's exactness claim into a check the harness runs. From fable: the missing constant rows, per-requester bus counters for the bench readout, and the module map with the three call chains a reader must hold.

## Convergence

All three converge on: one absolute timeline with timestamp-ordered bus grants (no windows, no cothreads); a scoreboard-style CPU model rather than per-cycle stage simulation; a CPU-side software RDP whose per-pixel write masks drive the bus; dropping the CPU recompiler; one TSV as the single source of constants with reference and check columns; RSP pipeline model unchanged. That is a strong agreement signal and the consensus shape ships.

They diverge on six points the brief names. Resolutions, one line each, are in `rationale.md`.

## Disagreements with my own earlier candidate

candidate-fable loses on license (fatal, fact 1) and on the time unit. Its 187.5 MHz choice was made to avoid multiplying constants by 4; the cost is a quantization knob with no hardware source, which is exactly the kind of parameter the map forbids. I score it as the rubric says, 21.
