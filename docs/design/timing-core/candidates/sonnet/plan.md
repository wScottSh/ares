# Build plan (candidate sonnet)

Every unit lands on a green base and ends in a check that runs the built emulator against a ROM, a bench or a unit test with a pass criterion. Ordering follows subtract-before-add, then scaffold, then one behavior cluster at a time with a monotone metric. "Baseline" means numbers captured in U0 on unmodified `master` (`59158c28a`).

Conventions. ROM paths: MM `C:\Users\Scott\PARA\3-Resources\Emulation\ROMs\N64\Legend of Zelda - Majora's Mask.v64`; nemu64-test at `C:\Users\Scott\n64-timing\nemu64-test` (`run-timing.bat` builds the ROM, `cycle` and `cop0hazard` via the same features); MM bench is `tools/bench/bench.py --scene N --runs 1` in mm-decomp-60fps with the bench build `build/n64-us-bench/mm-n64-us.z64`. Build host has no Python: tools in this plan are CMake C++ targets or `.sh`. Worker model policy from preferences: U4, U5a, U7, U8, U9 on fable, the rest on opus, verifier on a different model than the unit worker.

New manifest: `tests/timing/manifest.tsv` (`id, kind, command, criterion`). Created in U0 and extended by every unit; `params.def` rows may reference only ids present in it or `HW-ONLY:*`.

## U0. Baseline and trace hash (no behavior change)

- Add `Timing::TraceHash` (hash of CPU regs, RDRAM, DMEM/IMEM, TMEM, device regs at each VI frame boundary) behind `ARES_TRACE_HASH=<file>` and `tools/timing/determinism.sh <rom> <frames>`.
- Capture baselines on `master`: nemu64-test counts per group (expected 924/1604 timing, 9/13 cycle, 5/5 cop0hazard on the interpreter), n64-systembench numbers, MM bench `game_ticks` and host seconds for 4 scenes x 5 runs on interpreter and recompiler, and bytes per frame (`rdram_dp`, expected 136 to 273 KB medians).
- Check. Run determinism.sh twice on MM for 600 frames. Pass criterion for this unit is only that the tool runs and reports the first differing frame and agent for the known 1 percent South Clock Town difference (research recompiler-parity). That locates #27 instead of guessing. Record the baseline file in `tests/timing/baselines/`.
- Also measures (item 7 inputs): host seconds of the 600-frame bench on today's interpreter, which is the real "lockstep" cost since it already syncs every instruction (#9).

## U1. Remove host entropy (#27)

- Fixed seed in the savestate header, remove `random()` from RDRAM current calibration (rdram.cpp:43-44, 195-207), CP0 Random temporary fixed LFSR (the pure-tick version arrives in U6d), SP_PC read returns the real PC, RTC from a header epoch, run with "Deterministic Entropy" always on.
- Check. `determinism.sh` on MM 600 frames, interpreter, with GPU presentation on and off and with the process priority and affinity changed: all trace files identical. If the 1 percent source was not entropy, bisect with the hash (first differing frame, then agent) and fix it in this unit; the unit is not green until two runs match.

## U2. Subtract: delete the CPU recompiler

- Remove `cpu/recompiler*.cpp`, `Accuracy::CPU::JitInterleaving`, `jitClockTarget`, `forceSynchronize`, the JIT budget code in `CPU::main`, JIT-only `emux` hooks. Interpreter only.
- Check. Boots MM to the bench spawn point. nemu64-test group counts equal the U0 interpreter baseline exactly (924/9/5). Trace hash of MM 600 frames equals U1's interpreter hash. `bench.py` host time recorded (the recompiler is gone, so this is the new floor).

## U3. Tick base and parameter table (scaffold, no behavior change)

- Introduce `Tick` at 750 MHz (all existing constants x4), `Pclk/Rclk/Tc`, `ViClock` rational, `params.def`/`params.hpp`, `tools/timing/gen-spec` (CMake target) and `lint-literals`. Move the existing constants into `params.def` with refs; the lint fails the build on a timing literal outside `params.*`.
- Check. Trace hash of MM 600 frames equals U2's hash after dividing tick fields by 4 (the hash tool normalizes a tick scale factor for this one unit). Lint run on the tree is clean. nemu64 counts unchanged. `docs/timing/parameters.md` regenerated and diffed: no manual edit exists.

## U4. Timeline replaces CPU::synchronize (interpreter + RSP + devices on `Agent`)

Split so each part is green.

- U4a. `Timeline` with CPU and RSP agents and the existing `queue` wrapped as one Agent. Devices keep their lag logic behind adapters. `plan/commit` not yet used. Hot pair loop in place.
- U4b. VI, AI, PI, SI, PIF, MI become Agents; delete the lag counters, `queue`, `Thread::clock`. COUNT/COMPARE become pure plus one event.
- U4c. RDP is a stub Agent that still renders at `DPC_END` (behavior unchanged).
- Check (each part). `Timeline::maxActionsPerAdvance = 1` and `0` give identical trace hashes on MM 600 frames and on the nemu64 ROMs (this is the sync-independence criterion of #14). Tie-order test: permuting the order of Vi and Ai at equal ticks changes no hash (they are independent); permuting Rsp and Cpu does change a crafted ROM, proving the test can fail (`tests/timing/tie-order`). nemu64 counts must not get worse than U2 by more than the expected change from event time fixes; any change is explained in the unit's PR. Record host seconds of the pair loop (budget input).

## U5. Bus and RDRAM timing

- U5a. `Channel`, `Bank`, `busCost`, `ArbPolicy`, refresh, `splitBurst`, with no clients. Unit tests: `busCost` vs the derived datasheet table (14, 18, 26, 42, 74 tc read hits; 8, 12, 20, 36, 68 tc write hits; clean/dirty miss columns), refresh holdoff 52/54 rclk, arbitration by rank with synthetic requests, burst chaining equals unchained.
- U5b. CPU becomes a client via `CpuPort`: I fill, D fill, uncached read/write, RCP register and PIF accesses with fit latencies, dirty victim after fill, remove the flat 40+40 and uncached-0 charges. Write buffer comes in U6e; here writes drain synchronously through the port.
- U5c. SP DMA (agent), PI, SI, AI, VI cost-only, DP command fetch stub, all through `Channel`. Make `Rdram::ram` accessors private; delete the direct calls (rsp/dma.cpp, pi/dma.cpp, ai/ai.cpp, vi/vi.cpp, vulkan.cpp:106-107).
- Check. nemu64-test cache group: `Load from uncached` median 32 (VI off), D-cache miss median 41, I-fill in 43 to 47; n64-systembench uncached word 34, doubleword 37, 4 sequential 134, RCP reg and PIF rows within its tolerance; SP DMA length sweep (new ROM in `tests/timing/rom`) shows 6.5 B/rclk on writes vs the 5.55 hcs64 figure and the report states which one the fit follows; PI DMA matches systembench for 8 B, 128 B, 1 KiB, 64 KiB (193, 1591, 12168, 777807 rclk) and `n64_pi_dma_test`. Bank-sharing: uncached load latency with the address in the VI front buffer bank vs elsewhere (expected 36 vs 32 pclk); if it does not emerge, record it as calibration finding C6a. Source-level check: a device including `rdram.hpp` data accessors fails to compile.

## U6. CPU pipeline model, one nemu64 cluster at a time

The check for every sub-unit is the same: nemu64-test `timing`, `cycle`, `cop0hazard` counts, which must fall by at least the cluster's count and must not rise elsewhere.

- U6a. `Pipe::plan/commit` skeleton plus load-use interlock and the removal of the flat D-hit +1 and the nullified-slot bubble (clusters C2, C8; expected -214).
- U6b. Exceptions by stage and ERET refill (C1; expected -439), including `Pipe::raise` and `interruptTakenBefore` (`cop0hazard` interrupt tests).
- U6c. Operand-dependent FPU latency and FPU-FPU forwarding bubble (C3, C4; expected -222).
- U6d. CP0 costs, MFC0 bubble, CACHE op cost, pure-tick Random (C5, C9, C10, C11; expected -28).
- U6e. Write buffer (4 entries, weights), reads behind writes, fill-first dirty miss, `StoreVisibility` for fetch-ahead-of-store (cycle group SMC, expected -7), 5th-store policy enum.
- Gate for the whole unit. nemu64 timing group at 0 failures, or a written table of each remaining failure with its reference-based reason and the experiment that would settle it. Not "unverified": each remaining row is `HW-ONLY` with a named experiment. MM bench: `game_ticks` change per scene reported with the per-sub-unit contribution.

## U7. Software RDP core (functional, instant time) and oracle

- First step is license verification: read and record the license text of the MAME-derived code in ares history (parent of `5f9804fb6`) and of angrylion-rdp-plus; write the result in `docs/third-party.md` and restore the `LICENSE` notice. If angrylion-rdp-plus is not ISC-compatible, port paraLLEl shader stages instead and record that.
- Add `Rdp::Core` behind the existing command decoder. Rendering stays synchronous inside `DPC_END` for this unit only; `Vulkan::render` stays as the oracle.
- Harness: dump the RDP stream for a frame range (`ARES_DPLOG` exists) and run both renderers over it, comparing color and Z buffers per SyncFull.
- Check. On the 600-frame MM stream: zero differing pixels in every non-noise frame, a listed set of frames in the two noise texrects (z_kankyo.c:2925, z_oceff_storm.c:179). Rdp test ROMs (n64-systemtest rdp group, libdragon rdpq tests, snapper64 span tri output compared to core) pass. Measured ns per pixel recorded: gate G1 for the budget (below).

## U8. Timed RDP: DPC registers, command fetch, FIFO, executor, DP interrupt

- Remove `Vulkan::render`, `flushCommands` synchronous render, `command.current = end`; presentation reads a VI snapshot.
- Implement `DpcRegs` (pure), `CmdFetcher` on `Client::DpCmd`, FIFO, `Executor` with state/sync/primitive overheads and span compute time from `Core::plan` (no memory stalls yet; prefetch and write-back are instant at this unit), DP interrupt at SYNC_FULL retire.
- Check. Unit test `dpc.regs` against the n64-systemtest `tests/rdp/mod.rs` expectations (START only if clear, END_NEXT, idle-but-unsynced status `CBUF_READY|PIPE_BUSY|START_GCLK`, after SYNC_FULL `CBUF_READY`). Rectangle width sweep W=16..320 in 1-cycle and 2-cycle: `DPC_PIPEBUSY` slope 1.008 clk/px and 2 clk/px against the jgemu formula `14 + Σ(px*129/128 + 12)` (report residuals; open question 4). Sync costs 50/33/25 by ROM. MM trace: `DPC_CURRENT` advances monotonically, the RSP ucode stalls B to E occur (count them in `ARES_DPLOG`), ring laps per frame 1.4 to 2.8 unchanged, DP IRQ lands after the RSP task end.

## U9. RDP memory behavior

- Prefetch Requests (IM_RD, Z_CMP), span RAM halves with `freeAt`, write-back runs per `rdp.writeGranularity`, fill/copy paths, TMEM loads on `DpMem`, GCLK stall accounting, `Noise` via GF(2) jump, `G_PM_1PRIMITIVE` barrier.
- Check. snapper64 span-tri 216 dumps: slot occupancy and content equal the dump (the content check does not need timing); a fully rejected span issues no write Request (counter); `STATUS` bit 3 and counters: `DPC_CLOCK - PIPE/TMEM` rises when color and Z share a bank (SDK 12.8) in a crafted ROM; 1prim ROM: per-primitive dead cycles 30 to 40; noise: LFSR state equals the reference sequence for clock n at n = 0, 1, 2^k, and a long run (unit test against a stepped reference); MM trace: color/Z bank placement from #23 reproduced (Z shares bank 3 with the ring), RDP stall fraction between 0.5 and 0.67 of RDP time on a GCLK sample (F3DEX3 measurement reference). Bench: bus stats per client reported per scene.

## U10. RSP shared-touch protocol and SP DMA agent

- `RspTouch` classification, `SpDma` agent, halted RSP at `next() = max`, DPC accesses through the port, RSP recompiler eligibility rule and blocks ending before touches.
- Check. RSP interpreter vs recompiler trace hash identical on MM 600 frames and on a touch-dense microbenchmark (the #28 isolation: report which candidate cause the old +1.7 percent came from by running the old and new code on the same scene). `maxActionsPerAdvance = 1` hash equals unlimited. Report the share of RSP blocks that were eligible.

## U11. VI and AI traffic, refresh calibration surface

- Real VI fetch pattern (3 lines, 15 x 128 B per output line from H_START), underrun counter, AI 8 B requests with exact period, VI_CONTROL bit 16 returned.
- Check. Channel occupancy for MM within the research bands (VI 6.5 to 9 percent, refresh 1.3 to 1.4 percent of channel time) on all scenes; VI underruns zero in MM scenes; nemu64 load tail with VI on shows the 43 to 103 envelope.

## U12. Budget gate and levers

- Run 600 frames on all four bench scenes, 5 runs, with `benchmark-checklist` discipline: limiter, spread, relevance. Pass: at most 120 s host on this machine for every scene. Report the profile split (CPU, RSP, channel, RDP core).
- If over: apply levers in order (span-parallel shading with in-order join, SIMD core, fill/copy fast paths, chain coalescing), re-run the determinism script after each, and re-admit the gated CPU block cache only if still over. Each lever is its own PR with its before/after.

## Gates between units

- G0 (after U0): the determinism tool works and the 1 percent difference is located.
- G1 (after U7): software RDP at or above 3 Mpx/s on the MM stream. Below that, the design needs lever 1 before U9, or the RDP decision is revisited.
- G2 (after U5): `maxActionsPerAdvance` invariance holds with bus clients active.
- G3 (after U9): total host time of the 600-frame bench within 1.5x of the 120 s limit before tuning; otherwise start the levers early.

## Out of scope for this core plan

Calibration run (#16), author contact (#25), MM bench integration last leg (point `tools/bench` at the fork, remove the `func_80173B48` pin), PAL/iQue/64DD.
