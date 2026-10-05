# Build plan: timing core (candidate: opus)

Each unit lands on a green base and ends in a check that runs the built emulator: a test ROM, the MM bench, or a measurement. "Green" means the unit's own check passes, and three standing checks have not regressed:

- **det.** Two identical 600-frame MM runs give byte-identical per-frame stats (frame index, clocks, framebuffer hash once pixels are CPU-side).
- **nemu.** nemu64-test timing, cycle and cop0hazard failure counts are not higher than the previous unit's. Every newly failing test is listed with its cause.
- **gen.** `tools/n64-timing/behaviors.py --check` and the literal lint pass (from U3 on).

The harness unit (in flight) provides the runner, the nemu64-test corpus and per-frame stats. Units marked **fable** are the hardest by the program's model policy (scheduler/bus, RDP engine, CPU pipeline core).

Check ids such as `nemu64:timing/...`, `bench:*`, `snapper64:*` and `systemtest:*` are the ids `behaviors.tsv` references. U3 creates their manifest.

## Phase 0: baseline and subtraction

**U0. Baseline measurement.**
- Change: none. Run through the harness on `origin/master`.
- Check: record
  - 600-frame MM bench wall time, interpreter only (CPU and RSP);
  - nemu64 924/9/5;
  - det, with the Vulkan RDP off and on. The difference names which fields paraLLEl makes nondeterministic.
- Output: `reports/u0-baseline.md` with raw commands and numbers. This number decides whether the recompiler removal (U1) stands; if CPU+RSP interpreter time alone exceeds 60 s, the quiescent-window block executor (U-L) is scheduled before U16.

**U1. Remove both recompilers from the timing build.**
- Change: delete the CPU and RSP recompiler paths from `ares/n64` dispatch, plus `JitInterleaving`, `jitClockTarget`, `forceSynchronize` and branch-to-self charging. Keep the files out of the build rather than behind a flag (no toggle).
- Check: nemu64 numbers equal U0's interpreter numbers exactly. MM per-frame stats equal the U0 interpreter run exactly.

**U2. Determinism floor.**
- Change:
  - pin the entropy seed;
  - make CP0 Random a time function (placeholder: the current decrement rule, fully replaced in U7c);
  - `SP_PC` read returns the RSP PC;
  - fixed RDRAM current-calibration thresholds.
- Check: det with Vulkan off (timing fields only). Report which nemu64 Random tests moved.

## Phase 1: scaffold

**U3. Behavior table, generator, check manifest, literal lint.**
- Change: add `ares/n64/timing/behaviors.tsv`, `tools/n64-timing/behaviors.py` (generates `behaviors.hpp` and `docs/spec/n64-timing.md`), `tools/n64-timing/checks.tsv`, and `lint-literals.py`.
- The lint starts with an allowlist of today's literals. Every later unit deletes the entries it replaces, and U13 ends with an empty allowlist.
- Add a microbenchmark ROM builder by extending `docs/research/recompiler-parity/build-rom.py`. It assembles MIPS test ROMs, so `bench:*` checks need no libdragon toolchain.
- Check: gen passes. Deliberately removing a reference, adding an unknown verify id, or adding a literal each fails with a message naming the fix.

**U4. Clock rebase: absolute 750 MHz units.** (codemod)
- Change: `Thread::clock` becomes an absolute `Timing::Clock`. `step(n*2)` becomes `pclk(n)` and RCP `*3` becomes `rclk(n)`. The VI keeps its exact VCLK accumulator, and the AI moves onto one. The codemod script is committed as the lever.
- Check: nemu64 identical to U2. MM per-frame stats identical to U2 apart from the documented AI period change (+33 ppm removed).

**U5. Timeline scheduler.** (fable)
- Change: `Timing::Timeline` replaces `CPU::synchronize` and the nall relative queue. VI, AI, PI, SI and timers become absolute-time events. RSP and RDP become actors (the RDP still renders synchronously). The CPU calls `catchUp` per instruction when past `horizon()`. Costs are unchanged.
- Check:
  - `unit:timeline` scripted-actor tests: ordering invariant, tie-breaks, nesting depth bound, no step past an on-stack actor, Parked actors never stepped.
  - nemu64 not worse; the queue-event skew fix may move PI/SI-timed tests, each listed.
  - det.
  - MM bench completes; wall time compared with U0.

## Phase 2: memory system

**U6. RI arbiter and the SysAD port.** (fable)
- Change: `RI::Ri` with banks, NEC wire costs and refresh posted at VI HSYNC. `SysAD` with the 4-entry write buffer, reads behind writes, fill-first dirty miss, and posted register writes that take effect at drain. The D-hit +1 is removed. DMA engines still copy directly; that is the one allowed exception, until U8.
- Check:
  - `nemu64:timing/Load from uncached` (VI off 32, VI on other bank 32, VI on same bank 36 needs U11 and is recorded as expected-fail until then);
  - `nemu64:timing/Load Miss` (41, 42);
  - `nemu64:timing/Cached loads and store` (19/19);
  - `nemu64:timing/Uncached write buffer`;
  - `bench:mi-memset-uncached` (18.4 pclk/SD) and `bench:mi-memset-cached` (71.2 pclk/line) against n64brew's hardware memset.

**U7a. Pipeline scoreboard.** (fable)
- Change: `OpTiming` table from the decoder's `OpInfo`; `Pipeline::issue/retire`; LDI, DCB, MCI, FPU forwarding, trivial-operand FPU latency.
- Check: nemu64 groups "CPU register dependency", "COP1 register dependency", "COP1 instruction (32/64 bit)" (non-exception cases), "Individual instructions", "Data cache Size" all pass.

**U7b. Exceptions and bubbles.**
- Change: `Pipeline::fault` stage costs, the FPU exception = latency + 5 rule, ERET refill, nullified likely slot, CACHE op costs.
- Check: nemu64 "Exceptions", "COP1 JustFire", "Likely branch", the `CACHE` cases.

**U7c. CP0 timing.**
- Change: `Cp0Writes` per-register visibility, `TimedCp0` (COUNT write landing, Random, COMPARE as one event), the one-instruction interrupt sampling lag, CTC1 CE from the following instruction.
- Check: cop0hazard 5/5, "Compare (signalling 2)", "Random (decrement)", "Random (masking)", the cycle-set CTC1 cases.

**U7d. Fetch window and I-fills through SysAD.**
- Change: `FetchWindow`; the I-miss goes through `SysAD::fill` (no inline copy).
- Check: cycle-set self-modifying-code cases (7). nemu timing total reaches 0 failures, or each remaining failure is listed with cause and missing reference.

**U8. DMA engines as bus clients.**
- Change: `SpDma` (128 B bursts, fitted per-direction overhead), `PiDma` block by block with the BSD formula and its two known bugs fixed, `SiDma`, `AiDma` at the rational DAC rate. The last direct `rdram.ram` access by a hardware client is removed.
- Check:
  - `n64_pi_dma_test` golden logs (min/max ticks per size);
  - systembench PI 8 B/128 B/1 KiB/64 KiB and SI values;
  - `bench:sp-dma-sweep` (both directions, lengths 8 to 4096 across 2 KiB rows) against hcs64 and n64brew;
  - n64-systemtest SP DMA and PI groups;
  - MM boots and reaches the bench scenes;
  - det.

## Phase 3: one RDP

**U9. Pixel engine port, synchronous.** (fable)
- Change: port cen64-jgemu `src/rdp` (BSD-3-Clause, notice retained, license recorded in the PR) into `ares/n64/rdp/`, called at `DPC_END` exactly where paraLLEl is called today. Memory seam: in this unit, read and write `rdram.ram` directly (the snapshot redirect comes in U13).
- The VI uses ares's software output path.
- Check:
  - snapper64 reference dumps (`snapper64:*`, all groups the harness can run) with pass counts;
  - MM frame dumps at 20 fixed checkpoints compared with paraLLEl output, every differing region attributed to a cause;
  - det including the framebuffer hash.

**U10. Remove paraLLEl and Vulkan from the N64 core.** (subtraction)
- Change: delete the Vulkan RDP path and its build wiring for the N64 core.
- Check: build without Vulkan; det byte-identical over 600 frames with the framebuffer hash. This is the unit where #27's 1% run-to-run gap must be zero.

**U11. VI fetch on the bus.**
- Change: `ViFetch` posts 3 x 5 x 128 B per active output line from H_START; the software VI composes from the fetched bytes; refresh is posted at HSYNC.
- Check:
  - `nemu64:timing/Load from uncached (VI on, same bank)` = 36 median and mean within epsilon;
  - "Load Miss (VI on)" = 42;
  - `bench:uncached-vs-hpos` shows one ~53-rclk refresh holdoff per line, in HBLANK;
  - MM framebuffer hashes unchanged from U10, except frames where tearing is expected (listed).

**U12. Timed DPC front end.** (fable)
- Change:
  - `Dpc` START/END double buffering, `END_PENDING`, `DMA_BUSY`, `TMEM_BUSY` (fixes the `data == 7` read), counters as time functions;
  - `CommandFetch` as a `DpCommand` client into a 30-dword FIFO;
  - command costs (setters, syncs, primitive base);
  - DP IRQ at `SYNC_FULL` retire.
  - Primitives still render whole at dispatch, with span compute clocks only.
- Check:
  - n64-systemtest RDP group (status sequencing, START/END rules);
  - `nemu64:rsp_timing/Clock CPU vs RDP`;
  - MM `ARES_DPLOG` trace (reuse the #21 patch): stall C/D loops iterate, `DPC_CURRENT` trails `DPC_END`, the DP IRQ comes after the gfx RSP task ends, `START` is written while `START_VALID` = 1 at least once per lap where the ring wraps.

**U13. RDP memory interface.** (fable)
- Change: snapshots, span-RAM halves, segments, write runs, TMEM loads through the Z half, fill bursts, the atomic barrier. The pixel engine's read/write seam is redirected to snapshots and halves. The literal-lint allowlist must be empty here.
- Check:
  - snapper64 "RDP Test-Mode - Span Tri" span-buffer dumps 216/216;
  - "RDP Fill Mode Tri (Sweep)" rows;
  - the 1PRIMITIVE stale-read cases (four stacked image-read rects, both cycle modes);
  - `cen64law:*`: the full model reproduces cen64's published RECTN 320x6 = 2021 and 320x240 DUTY = 80287 under 1-cycle, VI blanked, no Z, no image read (tolerance and any residual reported, not tuned away);
  - `bench:rdp-atomic-sweep`, `bench:rdp-sync-sweep`;
  - MM GCLK-off share per frame reported next to F3DEX3's "half to two thirds" (reported, not asserted).

**U14. Noise LFSR.**
- Change: `NoiseLfsr` with GF(2) jump; combiner NOISE and `G_AD_NOISE` read it at each pixel's RDP clock.
- Check: Thar0 RDP-Noise datasets A, B, C reproduce bit for bit from reset.

**U15. Unsynced attribute sampling.**
- Change: replace the per-primitive attribute snapshot with per-stage sampling offsets (n64brew table, 0 to 29 clocks).
- Check: snapper64 RDPRectNoSync captures (cen64's 7332/7332 hazard set).

## Phase 4: budget and bench

**U16. Run budget.**
- Change: profile only, unless the number fails. Levers in order: horizon tuning, a deterministic multi-threaded pixel engine whose output is checked byte-identical by det, then the quiescent-window block executor (U-L).
- Check: 600-frame MM bench at most 120 s wall, three runs, median reported with the limiting component named (`benchmark-checklist`).

**U17. MM bench integration.**
- Change: point mm-decomp-60fps `tools/bench` at the fork, remove the `func_80173B48` pin, emit per-behavior provenance from `behaviors.tsv`.
- Check: bench report with per-scene frame times, plus a provenance table generated from the TSV.

**U-L. Lockstep checker and quiescent block executor.** (only if U0 or U16 requires it)
- Change: a block executor that runs only while `ex + block worst static cost < horizon()` and calls the same `CpuMemory` and `Pipeline` functions.
- Check: a checker that runs the interpreter and the executor side by side and compares the per-instruction Clock trace over the nemu64 corpus and 600 MM frames. Any difference fails.

## Dependencies

```
U0 -> U1 -> U2 -> U3 -> U4 -> U5 -> U6 -> U7a -> U7b -> U7c -> U7d
                                     U6 -> U8 -> U9 -> U10 -> U11 -> U12 -> U13 -> U14 -> U15
                                                                                  U13 -> U16 -> U17
```

U7a-d and U8-U9 touch disjoint files after U6 and can run in parallel worktrees. U9 can start its port as soon as U5 lands, because it only needs the synchronous call site.
