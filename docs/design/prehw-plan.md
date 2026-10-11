# Plan: everything before the console run (PREHW_COMPLETE)

This plan covers the work the program can still do before console hardware becomes unavoidable. It replaces `green-plan.md` as the active plan. The green plan reached SOFTWARE_COMPLETE on master `1e7c9bdd5` (after #142). Its sections 1, 3 and 8 still bind every unit here.

Six read-only investigations produced the evidence on master `1e7c9bdd5`. They covered the bus and CPU, PI and SI, the RDP, MM, the behavior rows and the kit, and tooling and docs. The planner reproduced four of their findings before this plan relied on them. Those four are the pidma row-crossing split, the merge of mm-decomp-60fps#1, the MI repeat path, and the kit's PIF terminate call. Each claim carries a label: measured (read from a run or the live state), cited (file and line, URL, or commit), inferred, or guess.

## 1. PREHW_COMPLETE

### Definition

Let N be the set of open items:

- every check in `docs/spec/n64-timing-results.tsv` whose result is not `pass`: fail, consistent-only, pass-conditional, and every pending result except `pending:calibration-16` on a `hw:*` check;
- every SOFTWARE_READY and MAP_GREEN clause that the closure draft reports as not holding;
- every behavior row that is not verified and not excluded (MAP_GREEN clause 5).

PREHW_COMPLETE holds when all of the following hold. `behaviors.py` computes clauses 1 to 5 from the repository (unit U-PREHW-PRED).

1. **Every open item has exactly one blocker row.** `tools/n64-timing/calibration/blockers.tsv` has one row per id in N, with columns `id`, `class`, `decider`, `separates` and `searched`. A row whose id is green is an error.
2. **No row is class A or B.** No software-doable work is left (section 2 defines the classes).
3. **Every class C row names a console measurement the kit can take and a tool can compare.**
   - Its `decider` is a `questions.tsv` id.
   - `comparable(kit, q)` holds (`behaviors.py:1108`).
   - The id appears in that question's `closes` column, or the check's `hw:*` twin does.
   - For a fit row, the question does not re-run its fit (`reruns_fit`, `behaviors.py:1114`).
   - `separates` says which fork value against which alternative the rule tells apart, with a citation.
   - `searched` lists the published sources and hardware recordings checked, each with its result.
   - An out-of-kit row instead names an `undecidable.tsv` id that starts `not decidable by this kit` and whose text says what would decide it. These stay open for decision D1.
4. **Every class D row is excluded.** Its `decider` is an `undecidable.tsv` id that starts `not-hardware-decidable`, or one excluded by target scope.
5. **SOFTWARE_COMPLETE clauses 2 to 4 hold, and the standing run is current.** The standing run names current master. `det` and `stepcap` pass. `dry-run.sh` moves all 89 `hw:*` checks from pending to pass, which proves wiring only (green-plan section 8).
6. **Every unit in section 4 has landed or is closed with a stated reason** (`units.tsv`, not computed). Every open issue on wScottSh/ares other than #1 and #16 is closed or named as a C decider.

Two parts of this cannot be checked by a machine. Clause 6 depends on the coordinator's ledger. The `searched` cell is honest only if the unit verifier re-checks it. Every unit that writes a `searched` cell gets that check from its verifier.

### Classes

| Class | Meaning | Ends when |
|---|---|---|
| A | Software-doable now, using a cited published reference or an existing hardware recording: a fix, a correct label, or a correct check | the unit lands; the item turns green or becomes C |
| B | Software-doable tooling (kit point, ROM, reader, question, comparator) that lets the console run decide the item | the unit lands; the item becomes C |
| C | Only console data decides it; the kit question exists, is emitted by a kit ROM, and has a reader | the console run (#16) |
| D | No console can decide it | never; excluded |

"A, then C" means an unexplored recording exists. The unit compares the model with it and records the result. If the item is still not green after that, the kit question is what remains. No A unit may fit a value to the recording it compares against (green-plan section 8, prefs 7, 21 and 31).

## 2. Every open item

Master `1e7c9bdd5` has 17 fail, 2 consistent-only, 1 pass-conditional, 18 report-only, 0 no-rom and 89 `pending:calibration-16` checks (measured, results tsv header `fix-137/run on d1874254e`). SOFTWARE_READY holds 1 of 6 clauses and MAP_GREEN holds 0 of 4 computed clauses (closure draft, measured).

### 2.1 Failing checks (SOFTWARE_READY clause 2)

| Check | Now | What blocks it | Class | Evidence | Decider or unit |
|---|---|---|---|---|---|
| bench:mi-memset-repeat | 2.184 ms/MiB vs 3.8 | The model sends MI repeat writes around the RI. `throughRi` is false while `mi.repeating()` (`ares/n64/cpu/sysad.cpp:9-11`, measured). Each iteration pays two register drains, about 16.7 rclk, and no RDRAM or VI cost. kit-dma reads vi-on 102377 against vi-off 102379 ticks (`results/fix-137/run/calib/boot-1/kit-dma.txt`, measured) | A | n64brew MIPS_Interface (repeat mode: the RI performs the RDRAM transfers, MI repeats the value); MiSTer `rtl/memorymux.vhd`@5725381 :326-336, :514-544 issues 8 B RDRAM requests. Hardware is about 29 rclk per iteration (3.8 ms/MiB / 8192, inferred; rdram-bus-arbitration.md B10) | U-REPEAT-RI, then C `memset-vi` |
| bench:mi-memset-uncached | 17.718 vs 18.38 pclk/SD | The table's VI state is unpublished (green-plan/bus.md Q1); the write periods are a fit | A, then C | rasky/n64-systembench PR #2 (hacktarux @7c2f96d4, `src/main.c:1497-1616`, cited) has U32W 46 against U32R 34 with the VI off. That is a write-drain value independent of the memset fit. Its provenance is inferred hardware (commit messages b786e39b, 03d7501b, d88864ed). Searched: n64brew MI rev 5278 and history, Talk page (404), Phire's edits, libdragon, MiSTer (no refresh model) | U-SB-PR2, then `memset-vi` after `vi-cpu-contention` |
| bench:mi-memset-cached | 72.682 vs 71.24 pclk/line | as uncached | A, then C | PR #2 DCACHE write-miss rows (35/39, invalid victims only) bound the fill part; no dirty-victim row exists anywhere (nemu64 `cache.rs:21-22` lists it as TODO) | U-SB-PR2, then `memset-vi` |
| nemu64:timing/load-miss-vi-off | phase mean 41.0 vs 42.0..43.0 | The model has no D-fill tail (bus.md E). The 42.5 reference was measured under nemu64-test's 2022 harness. The port runs the 2026 harness layout (`romgen/suites/nemu64/measure.py:1-5`). Commit 0603245f76 (2026-07-18) re-measured only the same-bank value when it changed the layout (cited, read via gh) | A, then C | nemu64-test 0f0eb0bf60 and 0603245f76 diffs; PR #2 DCACHE Miss W0 35 / row 44 (VI off) is a second D-fill recording. nemu64 publishes means and min..max envelopes, no distributions (`cache.rs:119-190`) | U-NEMU-2022, U-SB-PR2, then `nemu64-console` with D_HIST |
| nemu64:timing/load-from-uncached-vi-on-same-bank | phase mean 41.79 vs 32.3..40.3 | The VI-vs-CPU tail. On hardware the same quantity read 40.7 under the 2022 layout and 36.3 under the 2026 layout (cited, 0603245f76 `cache.rs`). bus.md's "VI cost about 2x too large" rests on 36.3 alone (inferred) | A, then C | as above | U-NEMU-2022, then `vi-cpu-contention`, `vi-fetch-modes`, `nemu64-console` |
| pidma:logs | 20913/20928 in scope, worst 0-31 B +5.91% | 15 points fail. 10 of them are 8-31 B DMAs that cross the 2 KiB RDRAM row. Crossing points average +2.24 ticks over the hardware midpoint, non-crossing ones -1.32 (216 and 1320 points, measured by the planner from `results/fix-137/run/pidma/points.tsv`; the research agent got the same split on verify-137b and verify-141). The crossing cost is the extra block write-back of `pi.block-writeback`, a fit. No reference says whether a clipped short block pays it. The kit's `pi-row-end` points (`sets.py:147`) have no small DMA with a non-empty first block | B | n64brew PI "Internal process" (clipping at the row, no cost); n64_pi_dma_test (README, 22 commits, golden logs min..max of 8 runs, `pi_dma_test.c:163-190`); MiSTer `PI.vhd`, gopher64 `pi.rs:172-193`, cen64 `pi/controller.c:33-48`, libdragon `dma.c:196`: no row-cross term. The u-dom2 per-access gap belongs to the bare BSD formula, not the model (size 8 non-crossing: mean -0.63 rclk, 56 of 61 inside the hardware window, measured) | U-PIROW-CROSS |
| systembench:pi-dma-8 | 196 vs 193 | One binary's poll grid plus the fitted drain (pisi.md item 2). The pidma recording says the model's 8 B cost is right (above) | C | rasky/n64-systembench: no README, issues #1 and #2 unrelated, no hardware notes | `systembench` (ext), `pi-dma-small` |
| mm:filesel-named | median 1.6789 vs 1.90..2.10 | No referenced mechanism separates the two file-select screens (section 3) | B | section 3 | U-GLYPH, U-FS-DETAIL, then `mm-filesel` and `filesel-glyph` |
| thar0:imrd-1cycle | +8.07% | F2, the stream overlap in `Port::eligible` (`timed.cpp:85-97`); no reference describes it | C | Thar0 RDP-Timing-Tests has 2 commits and one results file with the 100 configs already used (measured, local clone). Its README says transactions issue in the order color read, depth read, color write, depth write. That is issue order, not overlap, and strict order already measured worse (8.61% vs 5.16%, `behaviors.tsv:131`). n64brew RDP pages, MiSTer `RDP.vhd`, patents US6331856/US6239810/US6166748 and cen64 have nothing on overlap. The RDP RTL leak is not usable (Nintendo copyright) | `imrd-zcmp-slots`, `imrd-zcmp-slots-2cyc`, `span-width`, `thar0-console` |
| thar0:nozb-visep-imrd-1cyc | +4.01% | F2 and F5 | C | as imrd-1cycle | as imrd-1cycle, plus `vi-fetch-modes`, `vi-cpu-contention` |
| thar0:separate-bank | -0.19%, band 0.12% wide | F2 and F4 | C | as imrd-1cycle; the NEC datasheet is already used for `ri.*` | `ri-reorder`, `ri-priority`, `ri-priority-overlap`, `thar0-console` |
| thar0:zbrw-pass-zbsep-visep-noimrd-1cyc | -5.34% | F2 and F5 | C | as imrd-1cycle | `imrd-zcmp-slots`, `write-granularity`, `vi-fetch-modes`, `thar0-console` |
| thar0:zbrw-fail-zbsame-visame-imrd-2cyc | -4.69% | F3, F4, F5. U-SPANRAM's literal halves made it worse (-8.94%, `span-ram-attempt.md:9`) | C | no source covers 2-cycle Z read exposure | `zread-2cyc`, `imrd-zcmp-slots-2cyc`, `thar0-console` |
| thar0:nozb-visame-noimrd-1cyc | -4.91% | F1 and F5. #139 (U-RDP-DRAIN) moves it to -1.14%, still failing, and is held under D5 | C | n64brew Set Color Image is the only F1 reference; verify-139 | D5 for #139; `vi-fetch-modes`, `vi-cpu-contention`, `rdp-rect-base` |
| thar0:zcmp | +2.54% | A 1-cycle one-image read-only line costs 45.16 rclk per read against hardware 44.17. One rect size cannot split the post-to-grant hop, the fit constants and a per-rect term (`thar0-zcmp-residual.md`). No kit point is 1-cycle read-only: `reads_2cycle` (`zmem.py:175-189`) is 2-cycle, and `span_slots` and `span_width` also write | B | as imrd-1cycle | U-ZREAD-1CYC |
| thar0:ac-zbsame-vioff-imrd-1cyc | +2.55% | same model value as zcmp (108697) | B | as zcmp | U-ZREAD-1CYC |
| thar0:ac-zcmp-zbsep-vioff-imrd-1cyc | +2.43% | 1-cycle read-only, two streams | B | as zcmp | U-ZREAD-1CYC |

### 2.2 Weak checks (SOFTWARE_READY clause 3)

| Check | Now | What blocks it | Class | Evidence | Decider or unit |
|---|---|---|---|---|---|
| bench:mi-memset-rspdma | pass-conditional:#77, mean 6.509 | The idle VI's 0x800-VCLK step (#77) is a model choice | C | n64brew Video_Interface (TYPE=0 stops the VI) conflicts with RDRAM_Interface and Video_Interface on H_TOTAL defaults; MiSTer and nemu64 do not model it | `vi-first-line`, `vi-blank-counting` |
| systembench:u32r-banked | consistent-only, 134..135 vs 136 | No datasheet turnaround (`u32r-banked-turnaround.md:7`) | A, then C | PR #2 reads banked 135 and seq 134 at 1 pclk resolution. rasky main kept 136 through 50f5066, 4b538eb and 0caac1d (cited) | U-SB-PR2, then `cpu-reads`, `systembench` |
| bench:uncached-sizes-u32-banked | consistent-only, 131..133 vs 134 | as above | A, then C | as above | U-SB-PR2, then `cpu-reads` |

### 2.3 Report-only checks (SOFTWARE_READY clauses 4 and 5)

| Check | Now | What blocks it | Class | Evidence | Decider or unit |
|---|---|---|---|---|---|
| bench:sp-dma-sweep | wr 6.32, rd 5.184 B/rclk | Measures one DMA, not the memset rate (`expected.tsv:9`) | A | PR #2 SPDMAW 0x1000 = 623 and SPDMAR 0x1000 = 653 RCP cycles, timed trigger to poll exit like the sweep (`main.c:1373-1391`, 1613). Also bears on `ri.overhead-read` (fit to hcs64 5.55) | U-SB-PR2, then `sp-dma-direction` |
| bench:ifill-isolated | cold 42, cold-warm 36..38 | `cpu.ifill-stall` 45 is inferred | A, then C | PR #2 ICACHE Fill Hit 54, Miss 61, Begin 49/54 (`main.c:1521-1522`) | U-SB-PR2, then `ifill` |
| bench:dirty-row-sweep | dirty-clean 0/2/2 vs 3 | COUNT aliasing, no hardware value | A, then C | PR #2 U32W sw row 64 vs U32W 46; U32R rows 167 vs seq 134; DCACHE Miss row 44 vs 35 | U-SB-PR2, then `dirty-row` |
| bench:dirty-miss-isolated | clean 46, dirty 46 | No published dirty-victim cost | C | NEC VR4300 UM s.12.5.2 p.304 gives the order only; PR #2 has invalid victims only; nemu64 TODO | `dirty-miss` |
| bench:wb-fifth-store | sw-5 14..16 | NEC ("has a space") conflicts with R4300i ("emptied"), `vr4300-wb.md:37` | C | PR #2 RCP I/O R+W = 1 shows a read empties the buffer but does not time the 5th store (`main.c:189-201`) | `wb-release`, `wb-drain-target` |
| bench:pi-dma-sizes, bench:pi-dma-sizes-8 | report; 8 B 190.67..205.33 vs 193 | Poll sawtooth and codegen spread exceed ±1% (`checks.tsv:55-56`) | C | no phase recording exists | `pi-dma-small`, `systembench` |
| systembench:joy-2j, -3j, -4j | -2, +31, +50 RCP cycles | The hardware rig's pad count is unpublished; `pif.joybus-no-device` is fit from 2J assuming one pad | C | rasky/n64-systembench (no README, no rig notes), n64brew PIF-NUS, `hardware-corpora.md:23`, web search: nothing | `joybus-pads` |
| bench:si-dma-read64-2, -3, -4 | as JOY | as JOY | C | as JOY | `joybus-pads` |
| bench:rdp-rectn | 2076 / 77892 vs 2021 / 80287 | cen64's probe bracket, counter, othermodes and spread are unpublished (`rdp_core.c:5346-5362` @2f8d7bc says only "min-of-8") | C | cen64 history (commit 30c2459 has an empty body); author contact closed (pref 7) | `rdp-rect-base` |
| bench:rdp-loadsz-sweep | 0.703 clk/B vs 0.125 or 0.418 | MiSTer RTL and the reverted jgemu law conflict; neither is a hardware table | C | `jgemu-dpc-probe.md` (abc292f revert); libdragon, systembench, nemu64 have no TMEM timing | `tmem-load-rate`, `tmem-load-setup`, `loadtile-rows` |
| rdpstat:1prim-32px | 0 of 2 | The expectation is cen64's fitted threshold extrapolated (`checks.tsv:112`) | C | cen64 `rdp_core.c:4584-4601`, commit e6b58c6 (Diagnostic cartridge, test widths not public, dumping it is not allowed); snapper64, repeater64, Thar0 have no stacked IM_RD rects | `stale-read` |
| thar0:fill-mode | report-only, empty detail | The check is dead. `thar0_result` (`behaviors.py:1422-1427`) finds no `fill-mode` config in `compare.tsv` and returns nothing. Its source text at `checks.tsv:92` claims a report it never makes (measured) | A | Thar0 has no fill-mode config (results file read) | U-LABELS-2 deletes it; `rdp.fill-copy-rate` stays on `fill-copy-rate` |
| mm:south-clock-town | 3.0000 fields/frame | No hardware datum for mmbench's SCT state (human Link, day 1 12:00, map select). The BENCH ROM's SCT is a different state (standing Link at 10:00; verify-111) | B | `sct-cadence.md`; captures U and W; verify-103 notes the search did not cover human-Link day-1 RTA captures; two more web searches found nothing | U-SCT-MATCH |

### 2.4 SOFTWARE_READY clause 6

| Item | Now | What blocks it | Class | Evidence | Unit |
|---|---|---|---|---|---|
| rdp.mem-overhead-write | the only row with no hardware question independent of its fit | `behaviors.tsv:129` names no `hw:*` in its verify column. Its only question, `thar0-console`, re-runs the fit | B | `span-write-release` (q89, kit-span2, calib suite) times write-only 32 bpp lines. The fork reads a steady 29.0 rclk per 64 B half (the 19.5 fit plus wire) against 16 shading clocks (u-span-kit report, measured). A console half near 16 refutes 19.5, one near 29 confirms it (inferred). q90 `mem-overhead-pipelined` names the row but closes only the item | U-WRITE-HOLD-Q |

### 2.5 MAP_GREEN clauses

| Clause | Now | What blocks it | Class | Evidence | Decider or unit |
|---|---|---|---|---|---|
| SOFTWARE_READY | 1 of 6 | sections 2.1 to 2.4 | follows | | |
| mm:filesel-empty and mm:filesel-named pass | empty pass, named fail | section 3 | B | section 3 | U-GLYPH, U-FS-DETAIL |
| wScottSh/mm-decomp-60fps#1 is merged | "not computed" | Stale generator text. PR #1 merged 2026-10-10T18:16:59Z as 707602c6 (measured, gh). `mm_bench.py:26` pins bff939ca, which is ahead of it. `behaviors.py:705-710, 740, 837` hard-code "not computed" and "not done" | A | gh pr view; mm-decomp main `tools/bench/README.md` says the pin is gone | U-MAP-D3 |
| every hw:* check is ingested and passes | 0 of 89 | The console run. 87 of 89 are comparable today: the dry run on the standing calib run moves them to pass, which shows wiring only (measured). `hw:mm-bench` and `hw:mm-filesel` were not exercised because the standing home has no BENCH ROMs (`calib.txt:1`) | C, plus B for the two | dry run; reader verified in u-mmr-filesel | #16; U-INGEST-HARDEN builds or requires the BENCH ROMs |
| every non-excluded row is verified | 69 of 147 | section 2.6 | follows | | |

### 2.6 Behavior rows (MAP_GREEN clause 5)

Most rows that are not verified are decided by a check above or by a kit question that already separates them. The research found these exceptions:

| Rows | Now | Class | Evidence | Unit |
|---|---|---|---|---|
| legacy.cart.flash-mx-sector-erase, -chip-erase, -program; flash-mn63-sector-erase, -chip-erase, -program | legacy, out-of-kit | A (cite), then out-of-kit | n64brew Flash "Erase" and "Page Program" give exactly ares `flash.cpp:2-8` (MX29L1100 about 85 ms erase, about 3.5 ms program; MN63F8MPN under 280/300 ms and under 300 µs). ares reuses the L1100 values for MX29L0000, L0001 and L1101 (inferred). No datasheet found | U-LABELS-2 |
| legacy.cart.eeprom-write | legacy, out-of-kit | A (cite the conflict), then out-of-kit | n64brew Joybus_Protocol 0x05 says up to 6 ms (matches `joybus.cpp:48`). The SDK `osEepromLongWrite` page says about 15 ms. Record both; pick neither | U-LABELS-2 |
| legacy.cart.rtc-tick | legacy, out-of-kit | A (cite), then out-of-kit | n64brew Joybus_Protocol "RTC Block 2": updates once per second | U-LABELS-2 |
| legacy.pif.boot-timeout | legacy, out-of-kit | A (cite the 5 s vs 6 s conflict) and B | `undecidable.tsv` says the handshake runs in IPL3. That is false: the kit runtime sends terminate-boot itself (`romgen/runtime.py:163, 184-188`, read). n64brew PIF-NUS says about 5 s, as do libdragon `loader.c:108` and `runtime.py:183`; ares `hle.cpp:349` uses 6 s from the WaitTerminateBoot state | U-PIF-TIMEOUT |
| legacy.clock.vclk-pal | excluded | A (reason wording) | n64brew Clock_Timing gives 17.734475 MHz × 14 / 5 = 49.65653 MHz, equal to ares. It is decidable on a PAL console, so the reason is "outside the NTSC target", not "not hardware-decidable" | U-LABELS-2 |
| vi.unfetched-sample | model-choice, out-of-kit | A (cite), then out-of-kit (video capture) | n64brew Video_Interface says X_SCALE above 0x800/0xE00 "renders incorrect pixels". It does not say the samples read 0. MiSTer keeps a 3-line buffer (implementation, not hardware) | U-LABELS-2 |
| ri.refresh-latch | model-choice, out-of-kit | B | No short-H_SYNC kit point exists (grep of questions.tsv and items.tsv). `undecidable.tsv` names the deciding point | U-VI-SHORT-LINE |
| vi.fetch-overrun | model-choice, out-of-kit | B | as above | U-VI-SHORT-LINE |
| cpu.irq-sample | fit only | B | `hw:cpu-exceptions` irq-sw is a plain `mtc0 cause` (`cpu2.py:412`). The two rules differ only when IP is set and then cleared, so the point cannot separate them (inferred from the row note). `hw:nemu64-cop0hazard-console` re-runs the fit | U-IRQ-CLEAR |
| si.write64, si.write64-rom | pending | B | Their only question, `hw:systembench`, re-runs the binary whose reading the row cites. kit-dma already logs poll-walked write64 and write64-rom (min 3050/1607 ticks, measured) but only under `joybus-pads` | U-SI-POLL-Q |
| rdp.noise-alpha-dither, rdp.noise-dither-bits (noise questions) | pending | B | The exact-hash compare couples each question to the absolute RDP clock since reset. All 6 noise questions flip at every pad 1-7 against pad 0 (measured, kit.py --layout). A console mismatch cannot tell wrong bits from a wrong offset. The kit logs the pixels, so a reader can search the offset | U-NOISE-READER |
| scheduler.tie-rank, ri.request-latency, legacy.cpu.sysad-frozen-step, legacy.pif.step-quantum, item:fu.pif-ram-dword, legacy.cpu.nmi-entry | excluded | D | Emulator quanta or orderings with no console observable (`undecidable.tsv`). NMI follows a PIF-timed 500 ms grace at the 1.95 MHz PIF clock (n64brew PIF-NUS, Clock_Timing), so 1 pclk is unresolvable (inferred) | none |
| the other pending, fit-only and legacy rows (cpu.dcb, pi.io-busy, si.io-busy, rdp.cmd-fifo-dwords, rdp.cmd-fetch-burst, rdp.color-half-pixels-16bpp, legacy.cpu.interrupt-entry, legacy.pi.cart-read, legacy.ai.power-on-rate, clock.vclk, ri.post-read-gap, ri.post-write-gap, ri.overhead-read, sp.dma-burst, cpu.ifill-stall, cpu.dirty-miss-order, cpu.wb-release, pif.joybus-no-device, ai.fetch-bytes, vi.register-sample, vi.display-window, rdp.fill-copy-rate, rdp.tmem-load-rate, cpu.exc-fpu, cpu.exc-fpu-detect, cpu.fpu-trivial, cpu.eret, cpu.count-write-hold, cpu.fetch-ahead-slots, cpu.ctc1-fpe-ce, rdp.primitive-base, rdp.span-dead-pixels, rdp.span-line-gap, rdp.span-2cycle) | pending or fit only | C | Each has a non-fit kit question that the dry run compares (measured). Layout-sensitive questions need every pad 0-7 (`kit.py compare_layouts`) | their questions |

### Counts

The 39 check and clause-6 items in sections 2.1 to 2.4 split as follows.

| Class | Items |
|---|---|
| A | 11: mi-memset-repeat, mi-memset-uncached, mi-memset-cached, both nemu64 checks, both u32-banked checks, sp-dma-sweep, ifill-isolated, dirty-row-sweep, thar0:fill-mode |
| B | 7: pidma:logs, mm:filesel-named, thar0:zcmp, thar0:ac-zbsame-vioff-imrd-1cyc, thar0:ac-zcmp-zbsep-vioff-imrd-1cyc, mm:south-clock-town, rdp.mem-overhead-write |
| C | 21: systembench:pi-dma-8, the 6 F2/F3/F1 Thar0 checks, mi-memset-rspdma, dirty-miss-isolated, wb-fifth-store, pi-dma-sizes, pi-dma-sizes-8, the 3 JOY and 3 read64 reports, rdp-rectn, rdp-loadsz-sweep, rdpstat:1prim-32px |
| D | 0 |

Of the 5 MAP_GREEN clauses, 2 follow from other items, 1 is A (decomp #1), 1 is B (file select, the same work as mm:filesel-named), and 1 is C (ingestion, with a B part for the two BENCH checks). Of the row groups in section 2.6, 10 rows are A (labels only; all 10 stay out-of-kit or excluded after it), 7 rows are B (plus rdp.mem-overhead-write from section 2.4), 1 row is both A and B (pif.boot-timeout), 6 rows are D, and the rest are C.

No item is D except the 6 excluded rows. Every A item has an unexplored reference or recording. Four of them, the systembench PR #2 table, the nemu64 2022 values, the MI repeat mechanism and the pidma row-crossing split, did not appear in the repository, the reports or followups.md before this plan (grep by the research agents).

## 3. MM file select (#11): one mechanism for both screens

The plan's file-select rule is unchanged: each row is judged on its median over the mmbench phase sweep (green-plan section 3).

**What the model does now.** The following comes from the research agent's run of `framelog.py` on `results/plan-rdp/filesel/base4` (measured).
- In the named screen, 1-field and 2-field frames do the same RDP work: busy 15.48 vs 15.44 ms, with identical triangle, load, setter and sync counts. They differ in the gfx start offset after retrace (0.28 vs 0.47 ms) and in RSP audio overlap (1.60 vs 1.85 ms). The correlation of frame time with that offset is 0.80.
- So the model's named cadence is set by scheduling jitter at a margin of about 0.2 ms.
- Named does 0.53 ms more RDP busy than empty (15.45 vs 14.92 ms). Frame time spreads 0.87 ms (p10 to p90) in both screens.

**What only named draws.** Each file name draws 8 glyphs twice (shadow, then main). Each glyph is a `gDPLoadTextureBlock_4b` 16x16 I4 plus a `gSP1Quadrangle` with combiner TEXEL0×PRIM (mm-decomp `z_file_choose_NES.c:1393-1408`, cited). For 2 files that is 32 textured quads, 64 triangles and 32 loads. The measured delta is +70 triangles and +35 loads, with about 6 px per added span (measured).

**Why every tried mechanism failed.** A uniform cost moves both screens. A per-triangle constant has no window: +150 rclk fails empty at 1.0515 while named reads 1.8774; +200 gives 1.0847 and 1.9607 (measured, `plan-rdp/filesel/tri*.log`). U-RDP-DRAIN (#139) swaps which screen passes (empty 1.1513 fail, named 1.9383 pass; verify-139). The three u-93 arbitration readings move only the details (verify-137).

**The one mechanism that could pass both.** The named-only work is short textured triangle spans of about 6 px. A cost that applies to short textured spans, and not to the empty screen's work, is the one candidate selective enough. The model has no reference for spans under 16 px. cen64 confirms its span law's width independence only "for w>=16" (`rdp_core.c:5354-5355` @2f8d7bc, cited). The other path is less scheduling jitter (RSP audio and yield timing). That path changes the spread, not the work.

**What reference could ground it.** No published source gives short-span or textured-triangle cost. The research searched these:
- Thar0 (fill rects only);
- n64brew RDP and Pipeline (sync waits only, already modeled);
- cen64 (rects, w>=16);
- MiSTer, whose RTL is itself too fast on this screen (N64_MiSTer#27, "OoT and Majora's Mask Initial Menus Run Too Fast", open);
- the SDK autofill demo (no numbers);
- pro-man ch. 12 (no numbers);
- web searches for console cadence captures (none beyond captures U and W).

parallel-rdp, angrylion and libdragon were not checked. They are not timing sources, but that is inferred.

So the grounding must be a console measurement of the named-only work in isolation. The existing questions cannot provide it. `triangle-setup` (`questions.tsv:73`) builds only untextured 1 px types and does not close mm:filesel-named. The `mm-filesel` rule passes any console value inside the fork's per-frame range, which is about 1.8 ms wide on named, so a 0.3 ms shift still passes (u-mmr-filesel, inferred).

**Units.** U-GLYPH adds the isolated measurement. U-FS-DETAIL makes the BENCH comparison report the gap and the spread. After the console run, any model change is fit to the glyph kit data, and mm:filesel-named becomes its independent check. No unit tunes a constant toward 2.00 (green-plan section 8).

## 4. Units

Each unit is one PR with an independent verifier on a different model, as before. "MM" marks a unit that may change MM output: it lands alone and is followed by a full standing run recorded under reports/ (pref 33). Every unit updates its rows in `blockers.tsv` once U-PREHW-PRED has landed. No unit refits, widens a band, adds a one-point fit or invents a parameter. A unit that cannot meet its acceptance without doing so reports that and stops (pref 31).

### Q0. Predicate and harness trust (no model change)

| Unit | Scope | Acceptance | MM |
|---|---|---|---|
| U-143 (in flight) | Clause 1's `retimed` test (`behaviors.py:791-793`) is an `any()` over free-text `source`. Make it `all()` over each scene's current row, by commit column, or by an empty `git diff` of `ares` and `tools/n64-timing` between the row and run commits; with no git, it is not computed. Document the perf-stat wall basis (README.md:318) | a self-test case with one stale scene row fails today and passes after; a companion all-current case holds; clause 1 still holds on master through tree equality | no |
| U-PREHW-PRED | Add `calibration/blockers.tsv` and a PREHW_COMPLETE report (section 1, clauses 1-5) to `predicates()` (`behaviors.py:752-846`) and the closure draft. `--check` errors for a missing row, a stale green id, a bad decider, or a C row whose question is not comparable or does not close it. Seed the rows from section 2 of this plan | `--check` ok; at least 4 new self-test cases fail on a mutation and pass after; the closure draft prints "PREHW_COMPLETE: n of 5 computed clauses hold" with the A and B ids listed | no |
| U-INGEST-HARDEN | (1) pidma replay that reproduces 0 of 0 printed values reads not-run, not a vacuous pass (results line "reproduces 0/0", measured). (2) Identity check at ingest for thar0, systembench and snapper captures (`kit.py:427` EXT_IDENTITY has mm-bench only). (3) snapper `run.sh` `\|\| true` and a missing corpora dir fail loudly. (4) pidma reader rejects malformed and unknown lines by name. (5) `checks.tsv:5-6` point at real expected files or drop the pointer. (6) `standing.sh` rebuilds or stamps n64-run and exits non-zero when a script fails (tee at :85-88). (7) The standing home builds the BENCH ROMs, or `run.sh` fails without them | each item has a mutation self-test that fails today; a standing dry run moves all 89 hw checks | no |
| U-LAYOUT-RESIDUE | Close #100 citing #130 and the current layout table (37 sensitive, 9 with failing pads). Make the ROM version stamp fixed width so a dirty build does not shift kit layout by 6 B (`romgen/build.py:72`). Run one fork-only +76 B data-shift experiment on kit-dma to learn whether `sp-dma-direction` needs a data axis, and record the result | dirty and clean builds differ only in stamp bytes; the experiment's result is written in hardware-run.md | no |

### Q1. Class A: references and existing recordings

| Unit | Scope | Acceptance | MM |
|---|---|---|---|
| U-REPEAT-RI | Send MI repeat RDRAM writes through `ri.post` as RepeatCount+1 bytes in 8 B transfers (n64brew MIPS_Interface; MiSTer `memorymux.vhd` :514-544). No new parameter: the existing `ri.*` write rows apply. Update the `sysad.register-write` note, which cites repeat as its check | vi-on differs from vi-off in kit-dma; bench:mi-memset-repeat reports pass or fail as it falls, with no tuning; `--check` ok; mm600 md5 recorded before and after | MM if the md5 changes (libultra does not use repeat mode, inferred) |
| U-SB-PR2 | Port the PR #2 benches (hacktarux/n64-systembench @7c2f96d4, `main.c:1497-1616`) into the in-repo systembench port, as the build-corpora gate requires for external code. Check and record the license (pref 9). Add rows with a build column and report each against its `main.c` expectation and rule. The rows stay report-only until decision D7 | the systembench runner prints each PR #2 row with model, expected and verdict; the A items in section 2 record their comparison in their check source | no |
| U-NEMU-2022 | Port nemu64-test's 2022 averaged harness (separate uncached code buffer, old get_cycles, de30f2df) as a second nemu64 variant. Compare it with the 2022 expectations (42.5, 43.25, 40.7, 32.5, 32.54) under the existing nemu64 phase rule. Keep the 2026 variant and 36.3 as they are | values.tsv for both layouts, phase-mean verdict per value; bus.md's "about 2x" claim is re-stated against both | no |
| U-LABELS-2 | Delete the dead thar0:fill-mode check (`checks.tsv:92`, its verify and closes entries). Cite n64brew for the flash, EEPROM (with the SDK 15 ms conflict), RTC, PAL VCLK and vi.unfetched-sample rows. Fix the labels that misstate a basis: JOY 32B/56B/63B called independent (`behaviors.tsv:90-91`), `rdp.noise-step` basis, `cpu.exc-fpu-detect` fit-from, `ri.overhead-write` basis, `checks.tsv:3` line cite, `questions.tsv:12` sync loop text, count-write-hold rule text. Record Thar0's README order sentence in `hardware-corpora.md:65`. Name the u-93 arbitration reading as unreferenced in its row | `--check` and `--self-test` pass; results diff removes only thar0:fill-mode | no |
| U-MAP-D3 | Compute the decomp clause and the tools/bench destination row from pinned evidence (`mm_bench.py` COMMIT, the #1 merge 707602c6, the README pin sentence) instead of hard-coded text (`behaviors.py:705-710, 740, 837`). Retire the D3 and tools-bench gate entries | closure draft shows the clause as holding and the row as done; `--check` ok | no |
| U-DOCS | Stale text, each fact from its source: `mm-bench.md` wall table (regenerate with `report.py --wall` on the next standing run); green-plan sections 1 and 7 "9 out-of-kit" (12 now, `undecidable.tsv`) and the same in `pending.md`; green-plan section 1 counts table and section 6 predictions (mark historical, give actuals: 95/17/2/1/89/18/0); green-plan section 2 and P1 "74.67 untraced" (explained, `refresh-holdoff.md`); `rdp.md` section 4 "0.3%" (a fit residual; the spread is unpublished) and its stale 2069/77885; hardware-run.md time estimates labeled inferred; README PI I/O R provenance | each edit cites its source; no generated file is edited by hand | no |

### Q2. Class B: what the console run needs

Kit-ROM units shift code layout. Two units that edit the same kit ROM do not run in parallel, and each reruns `kit.py --layout`.

| Unit | Kit ROM | Scope | Acceptance | MM |
|---|---|---|---|---|
| U-ZREAD-1CYC | kit-zmem | `reads_1cycle`, a 1-cycle twin of `reads_2cycle`. Alpha-fail and Z-reject rects with mode none, IM_RD, Z_CMP and both; Z in a separate and the same bank; widths 8/32/64/128/320; 8 and 16 lines. New question `zread-1cyc`, tolerance derived the way `zread-2cyc`'s is. Closes thar0:zcmp, ac-zbsame-vioff-imrd-1cyc, ac-zcmp-zbsep-vioff-imrd-1cyc, `rdp.span-read-latency`, `rdp.mem-overhead-read` | `kit.py --self-test` 0 failed with a mutation that fails the rule; dry run passes the new check; the fork's per-read value at 320 px equals the u-thar0-zc trace's 45.16 rclk | no |
| U-GLYPH | kit-zmem, after U-ZREAD-1CYC | A point replaying the named-only work: N = 16 and 64 glyphs, each a 16x16 I4 block load, MM's syncs and a textured quad of about 11x12 px, 1-cycle, TEXEL0×PRIM. Metric rclk per glyph from the DPC_CLOCK slope. Add textured and shade-textured types to `triangle-setup`. The new question `filesel-glyph` closes mm:filesel-named; add mm:filesel-named to `triangle-setup` and `span-width` closes or record why not | self-test with a mutation; dry run prints rclk per glyph; `--check` ok | no |
| U-FS-DETAIL | none (mm_bench.compare) | Report, on both sides, the named-minus-empty median gap in rdp_ticks and dpc_pipebusy and each scene's p10 and p90. The pass rule does not change | a self-test case asserts the fields; a fork-vs-fork run shows gap 0 | no |
| U-WRITE-HOLD-Q | kit-span2 (no ROM change) | Promote release-b32's steady half to a compared metric of `span-write-release`. Derive its tolerance from cited instrument terms only (poll and refresh, as q90). First run a scratch mutation with `rdp.mem-overhead-write` at 15 and at 24 to show the metric leaves its band. Then add the row to q89's closes and `hw:span-write-release` to its verify column | the mutation leaves the band; closure clause 6 lists no row; `--check` ok | no |
| U-PIROW-CROSS | kit-dma | Add small row-crossing DMAs with a non-empty first block to the pi-row-end points: 16 and 19 B at 0x7f2, 26 B at 0x7f4, 12 B at 0x7fa, 39 B at 0x7f8, 24 B at 0x7ee (the worst pidma points). Note the pidma crossing split in the question text | the new points appear at every layout pad; the dry run lists them under `hw:pi-row-end` | no |
| U-SCT-MATCH | BENCH ROM (mm-decomp-60fps PR, pref 29) and mmbench | Make the BENCH SCT scene and mmbench's sct scene the same state, so `hw:mm-bench` decides mm:south-clock-town. Changing mmbench's scene is a change of the measuring scene, not of MM's emulation; record the old and new sct values | `hw:mm-bench` closes mm:south-clock-town; dry run compares it | no (the bench scene moves, the emulation does not) |
| U-PIF-TIMEOUT | new kit ROM | A ROM built without `pif_terminate_boot` that logs COUNT every 10 ms over ISViewer until the PIF halts the CPU. A question with an ingest rule whose tolerance covers the unknown power-on to IPL3 offset from a cited bound, or states none exists. Remove the row from `undecidable.tsv` | on the fork, the last COUNT is about 6 s after start; dry run passes the new check | no |
| U-VI-SHORT-LINE | kit-bus | Points with H_SYNC at about 0.25, 0.5 and 0.9 times the 52 rclk refresh holdoff, and one with H_SYNC below the line's fetch time, VI active. Count holdoffs and bursts per line from timed loads. Questions closing `ri.refresh-latch` and `vi.fetch-overrun`; remove both from `undecidable.tsv` | a scratch mutation (queued refresh instead of latch-one; no keep-fetching) changes the counts; dry run passes | no |
| U-IRQ-CLEAR | kit-cpu2 | Points that clear a pending interrupt 0, 1 and 2 instructions after setting it, on IP7 (COMPARE rewrite) and on an MI line. A question closing `cpu.irq-sample` | a scratch mutation using the delayed CP0 write rule flips `fired` on some point | no |
| U-SI-POLL-Q | none | Add si-dma write64 and write64-rom to `poll-phase`'s points and closes, and `hw:poll-phase` to both rows' verify | `--check` ok; dry run passes `hw:poll-phase` | no |
| U-NOISE-READER | none (kit.py) | A reader that, for each candidate noise bit mapping, finds any LFSR offset that reproduces the logged pixels. Gate `noise-alpha-dither` and `noise-dither-bits` on the mapping, not the hash | fork pixels at pads 0-7 all resolve to the same mapping with different offsets | no |
| U-KIT-LAST-POINTS | kit-cpu2, kit-bus (after the units above on those ROMs) | Watch edge points (byte in the same dword, KSEG1, sd, WatchHi, R/W mismatch, next dword, CACHE, EXL=1; `cpu2.py:410-411`). A question for the u-93 arbitration readings A/B/C. Split `count-write-hold`'s dmax into its own question so a divider-phase spread does not read as a hold failure. Make `hw:nemu64-console`'s model side the phase walk, not the single-phase ROM (`kit.py:53`, `behaviors.py:1279`) | each new point has a mutation that fails it; dry run passes | no |

### Q3. Close-out

| Unit | Scope | Acceptance |
|---|---|---|
| U-PREHW-CLOSE | A full standing run on master after the last unit, regenerating every spec file. Recompute PREHW_COMPLETE. Write the hardware-run checklist delta (new ROMs and pads) | PREHW_COMPLETE holds, or the closure draft lists each A and B item still open with its reason |

## 5. Order

```
Q0: U-143 (in flight); U-PREHW-PRED; U-INGEST-HARDEN; U-LAYOUT-RESIDUE
Q1: U-REPEAT-RI (alone if MM moves); U-SB-PR2; U-NEMU-2022; U-LABELS-2; U-MAP-D3; U-DOCS
Q2: kit-zmem   U-ZREAD-1CYC, then U-GLYPH
    kit-cpu2   U-IRQ-CLEAR, then U-KIT-LAST-POINTS
    kit-bus    U-VI-SHORT-LINE, then U-KIT-LAST-POINTS
    kit-dma    U-PIROW-CROSS
    other      U-FS-DETAIL; U-WRITE-HOLD-Q; U-SCT-MATCH; U-PIF-TIMEOUT; U-SI-POLL-Q; U-NOISE-READER
Q3: U-PREHW-CLOSE
```

- U-PREHW-PRED lands first in Q0 after U-143, so every later unit updates its own blocker rows.
- U-LABELS-2 runs after U-SB-PR2 and U-NEMU-2022 if they share check-source text.
- U-REPEAT-RI is the only unit that may change MM output. If its mm600 md5 changes, it lands alone and gets a standing run on the merged tree (pref 33).
- Q1 and Q2 have no dependency between them, except that kit-ROM units serialize per ROM.
- Every merge goes through the pref 36 gate (`behaviors.py --check` on the would-be merge), because most units edit `questions.tsv`, `checks.tsv` or the generated spec.

## 6. Decisions

| Id | Question | Default |
|---|---|---|
| D1 to D6 | as green-plan section 7 | as there; D3 is moot (#1 merged) |
| D7 | Assert the systembench PR #2 rows? Their hardware provenance is inferred from commit messages, never stated | Report-only. Each comparison is recorded in its check's source, and the item stays C on its kit question |
| D8 | A capture lacking a layout pad: fail or consistent-only? | fail (hardware-run.md, as now) |

## 7. What not to do

Green-plan section 8 binds unchanged. In addition:

- Do not fit the pidma row-crossing points or the PR #2 rows. They are comparison data, and any later model value fit to the kit's console data must keep pidma and PR #2 as independent checks.
- Do not add a per-triangle, per-load or per-span constant for file select. The measured triangle series has no window, and any value would be a file-select fit.
- Do not change `pi.block-writeback` for row-crossing DMAs before the kit's console data exists.
- Do not choose between the EEPROM 6 ms and 15 ms references, or between the PIF 5 s and 6 s references, without console data.
- Do not count the 87-check dry run as anything beyond wiring.
