# Follow-ups (parked; fix only when they block the frontier, else bundle into a cleanup unit)
- lint-literals.py skips single-line `auto f(...) -> void { step(13); }` bodies (verify-40 note 1). No such line today.
- RBusDevice::ARES_JIT dead enum (n64.hpp:117, rdram.hpp:232); double blank line cpu.cpp:115 (verify-32).
- desktop-ui "Deterministic Entropy" hint now does nothing for N64 (verify-36).
- CPU::power never resets countClock; profile.cpuCycles not serialized (t2 report).
- MM GameState.gfxCtx reads 0 in title scene; bench uses fixed address (mmbench).
- nemu64 clock-vs-CPU test alignment-sensitive (.align 32 pin); bench routines alignment (tools-integrate).
- thar0 RUNS=1000 unmeasured (~18 min).
- repeater64 FillTri/UndefShade ports; rdpstat:1prim has no source (r4).
- rdp_hidden_read_row hardcoded 8 MB mask rdp.c:156 (verify-35) -> T13.
- AI power-on DACRATE truncation 1103 vs nearest 1104 (verify-44); priority-queue timeToNextEvent s32 dead code.
- clock-rebase.py lists removed ares/n64/vulkan skip path (stack report).
- (verify-56) behaviors.tsv labels: cpu.ldi row silent on two inferred extensions (COP2 checks rt only; LWC1/LDC1 FPR result uses LDI latency); cpu.dcb has no corpus case (say so); cpu.fpu-trivial reference narrower than implemented classes; BC1 rt-field check against pending GPR loads is unmeasured.
- (t7a) Load Miss mean: 9 values fail because the D-miss model lacks its tail (refresh while VI off / re-derive D-fill across rclk phases); exposed by correct LDI on harness LD;JALR. Also romgen DCB test (store then load next slot / slot after).
- (t7a) pi-dma-sizes cart-to-ram-8 196.0 rclk, still failing (T8 owns).
- (verify-57) RI rule "HSYNC adds no refresh while one waits/runs" (ri/bus.cpp:13-16) has no behaviors row: add model-choice row, no reference. PiEdgeWait 0.5 rclk and the PI row-hit assumption are code-only constants: add rows.
- (t8/verify-57) mi-memset-rspdma 6.473 B/rclk fails band (rclk-grid quantization: 19 or 20 rclk per 128 B, 19.7 unreachable); pi-dma-sizes 8 B 197.33 fails (poll phase, untested); pidma 8-31 B up to +15% (model ~12 rclk low, unreferenced); PI first block ending at RDRAM row end ~29 rclk short; no bench:si-dma ROM.

## From L0 (PR #60)
- pidma replay (~23.8k/24k on Windows) not rerun on Linux: needs a ROM built from the n64_pi_dma_test clone (external build forbidden). Gate or cite-only.

## From T7b (PR #61)
- romgen cases for unreferenced exceptions (store AdE / store TLB / TLB mod, charged 6 pclk by inference; interrupt entry, NMI, bus error, watch, fetch-stage exceptions, CTC1-raised FPU exception) and CACHE ops other than Data Index Load Tag.
- Isolated ERET measurement so cpu ERET 3 pclk stops being fit-only.
- T7c note: interrupts reach fault(FaultStage::None) with inFlight null; legacy interrupt-entry step still applies. Keep the issued record on CPU::instruction()'s stack (member cost 11% MM wall).
- verify-61 label notes (cleanup unit): cpu.exc-fpu-detect basis says measured but is read off its own check tables -> fit/verify-is-fit (same for cpu.fpu-trivial); to-L 2^53 boundary is an upper bound (data only 0.5 and 2^53), note it in spec; cpu.exc-ex basis measured while AdES/TLBS/Mod are inferred; exceptions.cpp "one address check serves both" asserts an unreferenced mechanism; pipeline.hpp comment says 10% vs measured 11%.

## From T7c (PR #62)
- cop0hazard 2/5 residual: IP7 left set after COUNT test wraps through Compare=0. Fix in romgen port test order/state, or find a power-on Compare reference. Pending verify-62 judgment.
- No reference for interrupt-entry cost or CTC1-raised FPE cost.
- T7d: cycle suite left = 7 SMC tests; keep interruptSampled at top of CPU::instruction(); CE peek should use FetchWindow word instead of readDebug.

## From T7d / verify-65 (PR #65), label cleanup
- cpu.ifill-stall 45: relabel inferred (research formulas jointly give 46; independent range 45-47; nemu64 comment ~43); no asserting check (bench:ifill-isolated has no ROM).
- Dropped 48-pclk I-cache writeback charge: label as policy (unmeasured CACHE ops cost issue slot), no hardware reference.
- cpu.fetch-ahead-slots 2: add verify-is-fit note (smc-single-write passes for 2 and 3).
- C7 VI-off missing tail = refresh is a hypothesis; say so in the row.
- instruction() steps CpuIssue before a fetch fault (one extra pclk vs master); unplanned, no value moves; document or justify.

## From T11 / verify-63b (PR #63)
- Relabel ri.overhead-vi 0 as model-choice (vi-fetch.md silent on RI overhead); ri.overhead-write 0 is effectively a fit (rspdma can't tell VI on/off); mark cached sysad period 11-over-10 as inference.
- 20.0 same-bank VI-on mean tail and VI-vs-CPU interaction strength (~2x nemu64 means): genuinely unmeasured (B5 atomic bursts; ri.rank.vi refuted as lever). Needs calibration #16.
- sp-dma off7f8 6.334 -> 6.012 (no asserted band).
- MM wall +4.2% from T11 (T16 budget item).
- T13: ri.overhead-rdp (20 units) copies the superseded VI-off fit; refit, don't inherit.
- (verify-63c) bench sp-dma totals quantized to the 26 pclk CPU status-poll period; the bench cannot resolve a DMA end finer than that. Consider a finer poll loop or a counter-based end.

## From T13 / verify-67 (PR #67) -> unit t13-fix (queued after T14/T15 land; all touch rdp/timed.cpp)
- Perf: RDP::readiness / dispatchable / rdp_render_span_peek re-peek the span pool on every Timeline::advance (~2,300 of 2,807 extra perf samples; MM +35%). Cache them; re-record MM wall.
- Delete rdp_async_fence*, m_async_*, redundant dp branch ri/bus.hpp:129-130.
- Add behaviors rows: Slots=4 (rdp.hpp:99), Port::eligible 8-entry lookahead (timed.cpp:83), TMEM loads reuse span-read costs (assumption).
- Fit text: fit-from configs fit at +8.1/+2.6/+2.4% (grid on 60-config mean); VI-on named checks are residuals not passes; ri.overhead-rdp=0 and the single interface were chosen looking at VI-on slowdowns (VI-on not a clean independent check). Split filesel selection rows (empty, Options) from independent named-files row.
- Amend ADR 0001 Decision 3: halves never stall (rests on one data point 675 vs 681 rclk), one memory interface, 1PRIMITIVE from last span.
- Residuals: 2-cycle Z reads -11.8%; VI-same-bank Z -11..-13%; 32 px stale read (rdpstat-1prim expectation is cen64 extrapolation, not hardware); filesel rotation row 0-field game frame; trace 70/600 fb_hash diffs.

## From T15 (PR #69)
- Texture, blender, z_mode, dither attribute-stage rows built from the n64brew table only; need console captures. Triangles out of scope (cen64 fit rectangles only).
- Hold sees only commands already in the FIFO; later writes never reach the rectangle (predates T15).
- Rectangle tail drawn twice: with IM_RD blend or Z update a pixel can blend twice / fail its own Z compare (predates T15; new stages inherit). Fix: draw non-overlapping ranges.
- Plan text "65 repeater64 references" is stale: RDPNoSync1C has 20.

## From T14 (PR #68)
- hydra:noise not run on qwen: hydra-emu/rdp-tests prebuilt ROMs (repo @ 0761d3af176f, visual) were on the Windows machine only. Fetch prebuilt release ROMs (no building from clone) or mark pending permanently.
- Calibration #16 questions (rdp-noise.md 1, 3, 4): pixel offset; 2-cycle sampling; G_AD_NOISE/G_CD_NOISE/G_AC_DITHER bit sources; whether noise steps while RDP idle.
- (verify-69) 2-cycle unsynced case can't tell 22 from 24 (only 1-cycle pins depth); cycle type/atomic/detail-sharpen/bi_lerp per-primitive choice undocumented in rows; dispatch() pipeline-entry shift for held primitives has no row; stale derivation comment rdp_core.c:158.

## From t13-fix (PR #70)
- rdp.port-lookahead 8 may be an unrecorded fit (thar0 8.61% at 1, 5.16% at 8, 6.24% at 16); rdp.span-slots 2 scores better than 4 (4.96%). Not refit.
- TMEM COW ring (m_tmem_pool, m_tmem_cows) only uses slot 0; rdp_wq_busy has no caller. Deleting changes state format (separate unit).
- Perf headroom: bool-only span-pending query (~170 samples), per-access RDRAM debugger calls on window traffic (~130).
- Invariant: state read by RDP::nextStep() changed outside RDP::step must call rdp.changed().
- (verify-70) Relabel rdp.port-lookahead as fit + verify-is-fit (3.5 pt swing on thar0 fit data). power() calls changed() before dpc reset; move to end. Stray blank line rdp.c:166-170. compare.sh det-mm "DIFF" false positive (cat $(ls) hits subdirs).
- (t16) filesel-rotate has 14% headroom on the 120 s budget (102.9 s); re-time after core units. Per-field state hash is 7-11% of wall.

## From T17 (PR #72)
- 14 no-rom rows: write ROMs uncached-sizes, rcp-reg-read, pif-ram-read, pi-io-write, si-dma, rdpstat current-prefetch (closes 14 rows if published references exist; verify-72 to say which).
- Commit an emux XPROFREAD ROM test; cover the RSP path.
- rdpstat:* and snapper:* suite rows point at expected.tsv files that don't exist.

## From not-built / verify-74 (PR #74)
- --check "read" test is textual: a comment `//Timing::Behavior::X` counts as a read; pointer resolves if symbol appears anywhere in file. Strip comments / match real uses.
- ri.refresh-waits-for-burst static_assert guards nothing (flag no one reads).
- mm:file-select report source names neither a published value nor "none".
- pidma: log the ROM's COUNT reads in ARES_PILOG to pin the offset; until then a SUCCESS run can't pass the every-offset rule.
- Build pi.io-busy (134 rclk), cpu.pif-ram-read (1974), cpu.uncached-read-dword-total (37) from n64-systembench; each needs its bench ROM (plus si-dma ROM closes 5 checks).

## From sysbench / verify-75 (PR #75)
- pi-io-write ROM reads 140 because ares lands on one poll phase (sawtooth 125.3..141.3 rclk over 0..42 nops, period 25; mean 133.4 in band). Make the ROM average over poll phase with per-rep nop jitter; do NOT refit sysad.register-write or PiIoBusy.
- si.read64-base 1.3% over (38477 vs 37987) from pif.estimateTiming: real.
- LD from PIF RAM calls readWord twice (pays 2959 twice): unmeasured, decide.
- Orphan comment ri/bus.hpp:134; "its's" x4 in bench/expected.tsv; interim commits 4ef5c2e09, f70b7bda5 don't build (--check).
- Unported systembench benches: PI I/O R (144 rclk; ares 181), U32R seq/rand/banked, SI DMA W ROM, SI I/O W, JOY empty/accessory.

## From labels-phase (PR #79)
- 32 boot delays don't cover code-layout phase (4 extra instructions in shared bench runtime moved rspdma min 6.422->6.492, pi-dma-8 mean 189->190). Walk a code-layout pad as well as boot delay.
- hpos holdoff_rclk_max 42.67->74.67 from window starting on a refresh (report-only, not root-caused).
- (verify-79) rspdma mean margin thin: 6.491 vs band 6.49 at layout pads 4-6 (layout period 8 words = icache line).

## From pif-joy / verify-80 (PR #80)
- Wording: genuinely independent checks are Empty 1B and Accessory (escape minus byte only); 32B/56B/63B check the 5-channel cap, not the fit. Hardware 56B/63B are +7/+15 rclk over 8B, uncaptured. Fix spec + pif.joybus-skip/escape check columns.
- Unplanned behavior changes (labeled): cart channel charged by presence (was always 20000); 0xC0-flag handshake = skip. 1 ms reset and ~520 us flag delays uncharged. Channel order 4..0 ignored.
- 36 rclk ares-side offset varies 29.5..42 across JOY points.
- mmbench/report.py needs PYTHONPATH=tools/n64-timing (ModuleNotFoundError romgen).
