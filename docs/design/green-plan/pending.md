# Plan cluster: pending (everything non-green that is not a numeric failing check)

Investigator: plan-pending. Read-only on the repo. Master 8d86b87cd (core identical to aba69902e: `git diff aba69902e origin/master -- ares tools/n64-run` is empty, measured). Standing run of record: /home/wscottsh/n64-timing/results/calib-kit-merge/standing. Scratch: /home/wscottsh/n64-timing/results/plan-pending/.

Labels: **measured** (I ran it this session, or a named run's file I read), **cited** (file:line / report), **inferred** (reasoned from cited facts), **guess** (no evidence; names the experiment that would replace it).

## 0. What this cluster owns (counts measured from docs/spec/n64-timing-results.tsv and the spec status table)

Checks (211 total): 80 `pending:calibration-16` (all `hw:*`), 14 `pending:report-only`, 1 `pending:no-rom`, 4 `consistent-only`, 1 `pass-conditional:#77`. The 23 `fail` checks belong to the numeric cluster, except where a pending item here decides them.

Rows (149): 47 non-green non-fail rows: 7 `pending:calibration-16`, 2 `calibration-16 + no-corpus`, 10 `calibration-16 + report-only`, 13 `no-corpus`, 1 `report-only`, 10 `fit only`, 3 `model-choice`, 1 `consistent-only`. Plus 16 legacy rows (15 of them inside the pending counts above, plus `legacy.cpu.interrupt-entry` which reads pass). Plus open issues #77, #82, #84, #86, #87.

Experiments run this session:
- **#84 reproduced on master code (measured).** `n64-run vi-crash-repro.z64 --wall-seconds 60` (ROM sha256 dd48e26ff982e8c9..., runner = build/calib-kit-merge copied) segfaults, rc 139. gdb batch at the fault: `VI::compose` vi.cpp:163, `at = 4294967292` (2^32 - 4), `bpp = 4`, `dy = 110`. Record: results/plan-pending/vi84-gdb.txt.
- Code reads for #82, #86, #87, legacy rows, fill-rate charge (cited file:line below).
- Thin-margin scan over the standing bench results.tsv (measured, script inline in this session).
- systembench era vs 845635c row diff from standing/systembench{,-845635c}/results.tsv (measured).

## 1. The honest "all green" predicate (from map #1 rulings)

Rulings that bind (gh issue view 1 -R wScottSh/ares, Notes, cited): "Accuracy is the only goal." "There is no unverified status; a behavior is either built from its references or not built." "A one-time calibration run on someone else's console (flashcart owner) is an accepted hardware reference." Target "NTSC retail NUS-001 with Expansion Pak". Out of scope: "Consoles other than NTSC NUS-001 + Expansion Pak (PAL, iQue, 64DD)". Destination: deterministic, 600-frame MM bench run (mm-decomp-60fps `tools/bench`) <= 2 min, every behavior that can move MM frame time defined, built from cited references, paired with a verification method. Preference 21: a check against a row's own fit data is not verification. Preference 28c: #16 is human-only, and the program must be ready for it.

### 1.1 Definitions

- **verified(row)**: the row's status is `pass` under behaviors.py `row_status`, i.e. at least one check that is neither a guard (`~`) nor in the row's `fit-from` passes against an independent hardware reference under its phase rule, no check fails, and no check is weak (`consistent-only`, `pass-conditional:*`).
- **independent hardware reference**: a published console measurement (test-ROM expected values written from hardware, n64brew/SDK tables measured on hardware, Thar0, snapper64, systembench) or a #16 capture. Vendor/datasheet/RTL/wiki values with no measurement behind them are references to build from, and they verify a row only when a hardware check also agrees. The spec already works this way.
- **excluded(row)**: in `calibration/undecidable.tsv` with prefix `not-hardware-decidable:` (7 rows: scheduler.tie-rank, ri.request-latency, legacy.clock.vclk-pal, legacy.cpu.sysad-frozen-step, legacy.pif.step-quantum, legacy.cpu.nmi-entry, item fu.pif-ram-dword), cited undecidable.tsv. These can never be green. The predicate counts them apart and names the reason.
- **out-of-kit(row)**: prefix `not decidable by this kit:` (9 rows: legacy.pif.boot-timeout, 8 legacy.cart.*). A console could decide them, this kit cannot. They block `MAP_GREEN` unless Scott rules them out of scope (decision D1 below).

### 1.2 The predicates the program should report

```
SOFTWARE_READY  (reportable now, no hardware)
  det pass  AND  stepcap pass  AND  600-frame MM wall <= 120 s re-timed on current master (copied runner, pref 26)
  AND no check result is fail, consistent-only or pass-conditional
  AND every pending check is pending:calibration-16 whose question is mechanically comparable
      (kit ROM in KIT_ROMS, or ext: with a reader; model side produced by calibration/run.sh)
  AND no check is pending:report-only, pending:no-rom or pending:no-corpus, except on excluded/out-of-kit rows
  AND every non-verified row that is not excluded/out-of-kit names a hw:<question> that is
      independent of its fit data (pref 21)

MAP_GREEN  (the map's destination; needs #16)
  SOFTWARE_READY
  AND mm:filesel-empty pass AND mm:filesel-named pass (#11 acceptance)
  AND mm-decomp-60fps PR #1 (tools/bench on the fork, pin removed) merged by Scott
  AND every hw:* check ingested and pass
  AND verified(row) for every row not excluded and not out-of-kit
```

Report form: "SOFTWARE_READY: <n> of <m> conditions; MAP_GREEN: <k> of <N> in-scope rows verified; excluded 7 (not hardware-decidable); out-of-kit 9." Today SOFTWARE_READY is false on 4 counts: 23 fail checks plus 5 weak checks, 14 report-only checks, 1 no-rom check, and 4 hw questions that no tool can compare (measured from the results tsv and inventory.md). Sections 2, 3 and 6 table every pending check. Section 6.5 tables every pending row.

### 1.3 What cannot be green without hardware, and what cannot be green even with this kit

Never green without #16 (inferred from each row's checks; inventory.md lists the same set):
- The 19 `pending:calibration-16*` rows: clock.vclk, cpu.ifill-stall, cpu.dcb, cpu.dirty-miss-order, cpu.wb-release, sysad.register-write, pif.joybus-no-device, ai.fetch-bytes, vi.register-sample, vi.display-window, rdp.cmd-fifo-dwords, rdp.cmd-fetch-burst, rdp.fill-copy-rate, rdp.tmem-load-rate, rdp.color-half-pixels-16bpp, rdp.noise-alpha-dither, rdp.noise-dither-bits, legacy.pi.cart-read, legacy.ai.power-on-rate. Their only non-guard, non-fit checks are hw:* or report-only checks whose published value is missing, conflicting, or not a measurement (section 3).
- The 10 fit-only rows. No published corpus other than their own fit data measures them (cited: each row's verify-is-fit note in behaviors.tsv).
- vi.unfetched-sample and vi.fetch-overrun. Only a video capture decides them, and the kit has no video reader.
- The rows whose failing checks are decided only by a hw question: the consistent-only `si.write64-rom`, and every row behind `bench:mi-memset-rspdma` (#77). The fail rows belong to the numeric cluster.

Never green even with a clean console session of the current kit:
- 7 excluded rows (reason above).
- 9 out-of-kit rows (need retail cart chips or a modified IPL3).
- 3 fit-only rows whose only kit question re-runs their fit data: cpu.count-write-hold, cpu.fetch-ahead-slots, cpu.ctc1-fpe-ce (cited calib-kit-fix 2b; calib-kit-merge item 4 exempts them by design). They need a new independent kit point (unit U-FIT3).
- vi.unfetched-sample, vi.fetch-overrun (`none:` question, no reader).
- Any row behind `hw:mm-filesel` or `hw:pidma-offset` while those have no reader (U-MMR, U-PIDMA).

## 2. The 80 hw:* checks: kit readiness (dry-run evidence: results/calib-kit-merge/dry-run2.txt, 76/80 pending->pass fork-vs-fork, measured file)

A fork-vs-fork dry run proves wiring, not agreement. Each check is classed by what a clean console session will do. **Readiness**: R1 means one clean session of hardware-run.md flips the check mechanically. R2 means the same session plus a condition (extra controllers, a reset run, phase builds, an operator-built external ROM). R3 means no session can flip it today. **Expected outcome**: F means the fork already disagrees with a published value for the same quantity, so a fail is predicted if the console matches that value. U means no published value, so the outcome is unknown. G means the result cannot verify the model.

| hw check | kit | readiness | expected outcome (label) | closes (rows) | notes / closing action |
|---|---|---|---|---|---|
| dcb | kit-cpu | R1 | U | cpu.dcb | fork min sw-lw 24 vs nop-lw 16 (verify-85 §3, cited) |
| register-write | kit-cpu | R1 | U | sysad.register-write | MiSTer-only reference |
| ifill | kit-cpu | R1 | U | cpu.ifill-stall | research range 45-47 |
| wb-release | kit-cpu | R1 | U | cpu.wb-release, cpu.wb-block-entries | |
| dirty-miss | kit-cpu | R1 | F, partly: nemu64 load-miss-vi-off fails 41 vs 42.5 (cited results tsv) | cpu.dirty-miss-order, cpu.dfill-total | |
| dirty-row | kit-cpu | R1 | U (datasheet 3 vs model 2) | ri.retry-dirty | |
| cpu-reads | kit-cpu | R2 (phase builds recommended) | F: u32-banked 131 vs 134 fails (cited) | cpu.uncached-read-*, rcp-register-read, pif-ram-read, pi-io-read | |
| poll-phase | kit-cpu | R2 (phase builds) | U | pi.io-busy, si.io-busy | decides whether the systembench -4/-8 are poll phase |
| dom2-read | kit-cpu | R1 | U | legacy.pi.cart-read | |
| vi-first-line | kit-vi | R2 (phase builds) | U | #77, bench:mi-memset-rspdma | rule abs:24 never justified (verify-85 2a.4, calib-kit-fix "NOT DONE"). Before the run: derive the tolerance from the fork's spread over the 8 delays, or note why 24 |
| count-per-field | kit-vi | R1 | U; guess: a console crystal off by more than 100 ppm fails a correct model | clock.vclk | rule rel:0.01% is about crystal tolerance. Experiment: cite the NUS-001 X1 tolerance. If it exceeds 100 ppm, report the crystal error rather than fail |
| memset-vi | kit-dma | R1 | F: fork fails n64brew uncached (-3.6%) and cached (+2.1%) memsets (cited results tsv) | sysad.rdram-*, ri.write-hit, ri.overhead-write | also answers whether n64brew measured with the VI on |
| sp-dma-direction | kit-dma | R1 for 256-4096 B | F, inferred: sp-dma-sweep fails | ri.octbyte, post-read/write-gap, overhead-read, sp.dma-burst, ri.max-burst | 8-128 B undecided: no CPU-polled method resolves them (calib-kit-fix 2a.5). An RSP-timed point is not built (U-SPDMA) |
| pi-dma-small | kit-dma | R2 (phase builds) | F: pidma 8-31 B +15%, systembench pi-dma-8 -6 (cited) | pi.page-setup, halfword-bias, block-bytes, block-writeback | |
| pi-row-end | kit-dma | R2 | U | item fu.pi-row-end | |
| joybus-pads | kit-dma | R2 (4 controllers, second run) | U | pif.joybus-no-device, skip, escape, handshake, byte, si.read64-base | with one controller only, the 2J-4J fit stays open (hardware-run.md, cited) |
| vi-cpu-contention | kit-hpos | R1 | F, inferred: model about 2x the nemu64 VI-on means; same-bank nemu64 fails | ri.rank.vi, ri.arbitration, vi.aa-mode-lines, vi.burst, ri.refresh-* | |
| cmd-fifo-depth | kit-rdp | R1 | U (fork 240 = systemtest author's note) | rdp.cmd-fifo-dwords | |
| cmd-fetch-burst | kit-rdp | R1 | U | rdp.cmd-fetch-burst | caveat: the gcd may show multiples of the burst (verify-85b §4, inferred). The question text says "8 poll phases" while the build walks 16 (verify-85b 3d) |
| rdp-sync-setter | kit-rdp | R1 | U; jgemu setter 2.68 vs n64brew 1 conflict (jgemu-dpc-probe.md) | rdp.sync-*, rdp.setter | |
| rdp-atomic | kit-rdp | R1 | U | rdp.atomic-dead | |
| rdp-rect-base | kit-rdp | R1 | F, guess: fork rectn 2069 vs cen64 hardware 2021 (+2.4%), duty 77885 vs 80287 (-3.0%), rule rel:1 | rdp.primitive-base, span-dead-pixels, span-line-gap | the only independent decider of the three fit-only RDP rows |
| color-half-16bpp | kit-span | R1 | U | rdp.color-half-pixels-16bpp | |
| span-width | kit-span | R1 | U | rdp.span-read-latency, mem-overhead-read, span-slots | |
| noise-alpha-dither, noise-dither-bits, noise-pixel-offset, noise-idle, noise-2cycle, noise-stall | kit-noise | R1 (26-30 KB log: needs USB or SRAM, no photo) | U | rdp.noise-* | |
| noise-reset | kit-noise | R2 (reset run) | U | rdp.noise-reset | |
| stale-read | rdpstat-1prim | R1 | U: the fork fails 2/4, but the expectation is cen64 extrapolation (cited followups T13) | rdp.atomic-dead, rdpstat:1prim | the console replaces a non-hardware expectation |
| dpc-sequencing, unsynced-attrs, systemtest-rdp | rdpstat-* | R1 | U, inferred likely pass: fork passes rdpstat dpc/systemtest/unsynced | rdpstat checks | |
| nemu64-console | nemu64-timing | R1 | F: fork fails 11/1604 timing values (C6 1, C7 10; cited verify-66) | 46 cpu/ri/vi rows | rule `exact` on v0 over 1605 values. Inferred risk: a test whose hardware value varies by a tick fails exactly. Experiment: list the nemu64 cases whose expected value is a range, and use the range rule for those |
| nemu64-cycle-console, nemu64-cop0hazard-console | nemu64-cycle, -cop0hazard | R1 | U, inferred likely pass (fork 0/13 and 0/5 fail) | fit rows. pref-21 exempt: cpu.count-write-hold, fetch-ahead-slots, ctc1-fpe-ce stay fit only by design | |
| tmem-load-rate, tmem-load-setup, loadtile-rows | kit-tex | R1 | F, inferred: fork 0.703 clk/B + 7 disagrees with both published laws (MiSTer 0.125, jgemu 0.418) | rdp.tmem-load-rate | whichever law the console confirms, the fork's charge moves |
| fill-copy-rate, copy-passfail, copy-passfail-pixels | kit-tex | R1 | F or U, inferred: fork fill 6.69 B/clk (16 bpp) vs SDK 8 | rdp.fill-copy-rate | the code charges words*8/RdpFillCopyRate + line gap (rdp/timed.hpp:236, cited), so the kit's slope of 6.69 includes RDRAM write bandwidth (inferred). The metric conflates the pipeline rate with memory. A fail localizes nothing |
| attribute-stage | kit-tex | R1 | F: #86, fork 0 px vs n64brew 27/26 for z_mode pass-to-fail (cited #86) | rdp.attribute-stage, pipeline-depth | fix #86 first (U-86), or the console's answer is spent on a known defect |
| attribute-sync-cost | kit-tex | R1 | U | rdp.sync-full, attribute-stage | |
| write-granularity, write-granularity-pixels, atomic-contention, imrd-zcmp-slots, clobber, xbus-fetch-rate, rdp-hold, triangle-setup, pipebusy-stall | kit-zmem | R1 | U | rdp.write-run, atomic-dead, span-slots, xbus-fetch-rate, items | rule rel:15 on write-granularity is wide. The hypotheses differ by 2x or more (verify-85b, cited). Textured triangles are not built |
| cpu-exceptions, cache-ops, cache-ops-sum, load-interlock-cop, fpu-classes, wb-drain-target | kit-cpu2 | R1 | U | cpu.exc-*, eret, irq-sample, issue, cache-index-load-tag, ldi, fpu-trivial, exc-fpu-detect, wb-*, sysad.register-write | CU2/Watch console safety unverified (calib-kit-fix §4) |
| cpu-watch | kit-cpu2 | R1 | F: #87, the fork never raises Watch (VR4300 UM CP0 Watch, cited #87) | item fu.exc-entry, #87 (no row) | fix #87 before the run (U-87) |
| ri-priority, ri-priority-overlap, ri-reorder, vi-fetch-modes, vi-fetch-position, vi-blank-counting, refresh-all-banks, vi-intr-latency, vi-rcp-phase | kit-bus | R1 | U | ri.arbitration, rank.*, vi.*, refresh-* | vi-rcp-phase is not the first change after power-on (calib-kit-fix 2b, cited) |
| ai-rate | kit-bus | R1 | U | legacy.ai.power-on-rate | |
| ai-fetch | kit-bus | R1 | F, guess: fork 4 B steps vs patent "8 bytes at a time" | ai.fetch-bytes | whether AI_LEN readback shows fetch granularity is an inference. Neither result localizes |
| thar0-console | ext:thar0 | R2 (operator builds Thar0 a81ced93 with libdragon) | F: the fork's port already misses Thar0's published console by up to +8.07% in 10 configs, and the reader compares console vs fork within 1% (kit.py:262-296, cited) | rdp.span-read-latency, mem-overhead-*, read-gate, port-lookahead, ri.overhead-rdp, 10 thar0 checks | harness gap: the console runs the original ROM, the fork runs the romgen port (its --hw build hangs, cause unknown). A cross-binary compare. A pass on a reproduction of the published data cannot happen until the numeric cluster fixes the residuals |
| snapper64 | ext:snapper64 | R2 (operator runs snapper64) | G: the reader compares console dumps with the published dumps, not with the fork (kit.py:298-314, cited) | rdp.span-ram-half, span-ram-segment, pipeline-depth, span-slots, write-run | reclassify as a guard (`~hw:snapper64`) on those rows. It re-checks the reference, not the model. No row status moves today (measured: none flipped in dry-run2) |
| systembench | ext:systembench | R2 (docker era build, sha fd5ec6c0; 1 controller) | F, guess: the console reading of this binary is close to the published values, while the fork reads PI I/O W -4, SI I/O W -8, PI DMA 8 -6, PI DMA 128 -11 | pi.*, si.*, cpu.uncached-*, pif.joybus-* | see section 5 |
| pidma-offset | ext:pi_dma_test | **R3: no reader** | - | pidma:logs | U-PIDMA: the offset may be pinnable without hardware |
| mm-filesel | ext:mm-bench | **R3: no reader** | F, inferred: fork 1.694 fields/frame vs 2.00 in the public console recordings (#11) | mm:filesel-named, rdp.span-read-latency | U-MMR |
| vi-mid-field-blank | none | **R3: blocked by #84** | - | item fu.vi-mid-field-blank, #84 | U-84 then a kit point |
| vi-unfetched-video | none | **R3: needs a video capture** | - | vi.unfetched-sample, vi.fetch-overrun | U-VIDEO or reclassify |

Summary (inferred from the table): 76 of 80 flip mechanically on a full session as hardware-run.md describes it. 11 of those are R2. 4 are R3. At least 15 are predicted F: they will flip to fail if the console agrees with the published references the fork already misses, so for those #16 delivers localization, not green. 1 is G (snapper64).

Ingestion gap (inferred from grep of ingest.py/kit.py: the `#kit` header `sha` is stored in manifest.tsv but compared with nothing): a capture made from kit commit A is compared against `run.sh` output of commit B. If any kit asm changed between A and B, the console and fork ran different ROMs. Closing action: compare each log's ROM content hash (add ROM sha256 to the `#kit` header at build time) against the model-side ROM, and fail on mismatch. Small; no hardware.

## 3. Report-only, no-rom and no-corpus checks: what each could become

| check | detail today (measured, results tsv) | published value? | true blocker | closing action |
|---|---|---|---|---|
| bench:ifill-isolated | empty: no ROM | none (cited checks.tsv) | dead check. The kit's `ifill` point already measures it on the fork | delete the check; cpu.ifill-stall keeps hw:ifill. **Reclassify** |
| bench:wb-fifth-store | empty: no ROM | none (vr4300-wb.md) | dead check. kit-cpu `wb-stores` covers it | delete; cpu.wb-release keeps hw:wb-release, hw:wb-drain-target. **Reclassify** |
| bench:rdp-loadsz-sweep | empty: no ROM | two conflicting laws (MiSTer 0.125, jgemu 0.418 clk/B), neither a raw hardware table | dead check. kit-tex measures it | delete; hw:tmem-load-rate decides. Asserting either law would pick a side with no evidence |
| thar0:fill-mode | empty: Thar0 has no fill config | SDK 8 B/rclk: a vendor pipeline rate, not a measurement with stated conditions | no corpus | delete; hw:fill-copy-rate decides |
| bench:rdp-rectn | 2069 vs 2021; 77885 vs 80287 | cen64 dpc_probe on hardware, but counter, bracketing and othermodes are unpublished (jgemu-dpc-probe.md "Questions for the author" 2-3, cited). #25 closed not planned (pref 7) | the reference's conditions are unknown | keep as report. Fix the gate text: "conditions unpublished", not "no published value". Only hw:rdp-rect-base decides |
| bench:dirty-row-sweep | dirty-800 2 vs 3 | datasheet inference, no console | hardware only | keep; hw:dirty-row |
| bench:dirty-miss-isolated | clean 46 vs nemu64 41 (harness included) | nemu64 41 covers the clean fill, already asserted by nemu64:timing load-miss; no dirty value | hardware only | keep as report, or drop the clean point as a duplicate of nemu64; hw:dirty-miss |
| bench:si-dma-read64-2/3/4, systembench:joy-2j/3j/4j | +5, +38, +58 rclk (0.01-0.06%) | yes (systembench 57972/77924/97890) | pif.joybus-no-device is **fit** from read64-2/joy-2j, and the rig's controller count is unpublished (behaviors.tsv note, cited) | do not assert. That would be checking 3J/4J against a fit that assumed 1 pad. hw:joybus-pads with 1 and 4 pads decides. The duplicate pair (bench port and systembench original) can collapse to the systembench rows |
| mm:south-clock-town | 3.0 fields/frame, 1708022 RSP clocks/field | none (cited checks.tsv) | no MM console capture | keep as report. A reader for ext-mm-bench SCT closes it (U-MMR) |
| mm:file-select | not in results (no row names it) | none | the source text still names neither a value nor "none" (verify-74 note 3, cited) | fix the source text or delete the check (no row uses it) |
| rdpstat:current-prefetch | pending:no-rom | n64-systemtest TODO comment, not a result (cited) | duplicate of hw:cmd-fifo-depth; the guard on rdp.cmd-fifo-dwords has no ROM | delete it. The kit's kit-rdp fifo-depth point (fork 240) is the model side. **Subtract** |
| pending:no-corpus on the 13+2 legacy rows | - | see section 4 | - | section 4 |

None of the 14 report-only checks can be honestly asserted now (inferred from the table). Each has no published value, a value with unknown conditions, a value that is the row's own fit data, or two values that conflict. Five can be deleted as dead or duplicate (ifill-isolated, wb-fifth-store, rdp-loadsz-sweep, thar0:fill-mode, rdpstat:current-prefetch), plus mm:file-select's text fix. That moves no row status. The checks have no results, and each row keeps its hw question. That claim is inferred; verify with `behaviors.py --check` and a row_status diff after the deletion.

## 4. Legacy rows (16): what replaces each (code read, cited)

| row | code today (cited) | status | replaced by | honest end state |
|---|---|---|---|---|
| legacy.cpu.interrupt-entry 1 pclk | cpu.cpp:100-103 `step(pclk(1))` | **pass, overstated (inferred)**: its check nemu64:cop0hazard/softwareinterrupt is cpu.irq-sample's fit data, and per that row's reference it tests which instruction takes Int, not the cycle cost | kit-cpu2 `cpu-exceptions` measures irq entry (fork irq-sw 4, verify-85b §4, cited) but does not close this row; it names hw:nemu64-cop0hazard-console | U-LBL: make softwareinterrupt a guard, add hw:cpu-exceptions to its verify. Status becomes pending:calibration-16 |
| legacy.cpu.nmi-entry 1 pclk | cpu.cpp:107-110 | no-corpus | none | excluded (not-hardware-decidable, cited) |
| legacy.cpu.sysad-frozen-step 1 pclk | cpu.cpp:113-116, still live | no-corpus | note says "replaced by T6: SysAD port". **Stale**: the code still steps 1 pclk while frozen (measured by read) | excluded. A frozen SysAD is a hung console (Bus::freezeDualRead). Fix the note text (U-LBL) |
| legacy.pi.cart-read 250 pclk | pi/bus.hpp:66-68: domain 2 still `pclk(250)`; domain 1 uses CpuPiIoRead (T8) | cal-16 + no-corpus | T8 replaced domain 1 only | U-DOM2: derive a domain-2 read from the BSD DOM2 registers with the same model that gives domain 1 its 144 rclk (systembench PI I/O R, a measured pass), then hw:dom2-read verifies. Inferred: MM's flash saves use domain 2, so the row can move MM time on a save |
| legacy.pif.step-quantum | pif/hle.cpp:251-256 | no-corpus | none | excluded (emulator quantum) |
| legacy.pif.boot-timeout 6 s | pif/hle.cpp:349 | no-corpus | none | out-of-kit (modified IPL3) |
| legacy.ai.power-on-rate 44100 | ai/ai.cpp:92 | cal-16 + no-corpus | none | hw:ai-rate decides. Inferred: MM writes AI_DACRATE, so it does not move MM time. Drop `pending:no-corpus` because the kit is the corpus (label only) |
| legacy.cart.eeprom-write, rtc-tick, 6 flash-* | cartridge/*.cpp | no-corpus | none | out-of-kit. Decision D1: MM NTSC-U saves to flash. These rows can move MM time only on a save, and no bench scene saves (guess; check that no mmbench scene writes flash with an ARES flash-command log) |
| legacy.clock.vclk-pal | system.cpp:86-89 | no-corpus | none | out of target (map #1 Out of scope). Remove from the behaviors table or keep it excluded. It is not a behavior of the target console |

The 6 flash rows (out-of-kit) and the 7 excluded rows will never verify. With the map ruling "built from its references or not built", the closure draft's sentence "Every behavior is built: the code reads each value or implements each rule" (map-1-closure-draft.md line 5, cited) overstates for these rows. They are constants with no reference. Closing action (U-LBL): the closure draft names a third class, "charged with no hardware reference (legacy)", with its count, apart from built rows.

## 5. Open issues

**#84 (VI::compose segfault on a mid-field blank).** Root cause, measured with gdb: `at = 2^32 - 4` with `bpp = 4`. `compose()` reads the live `io.colorDepth`, which is 0 after the blank, so bpp = 4. But the fetch it composes was started at 16 bpp, with `fetch.line` and `fetch.pitch` latched at HSYNC (vi.cpp:146-167, 173-190). With a negative row offset, `base` wraps. The guard `at + bpp <= fetched` overflows in u32: at = 2^32-4 gives at+4 = 0 <= fetched, so the guard passes and `fetch.bytes + at` reads 4 GiB past the buffer. That the row offset is negative is inferred from `at`, because `base` is optimized out. Fix scope (vi.cpp only): (1) latch bpp, and the other compose inputs, in Fetch at startFetch, so a line composes with the geometry it fetched; (2) write the guard overflow-safe (`at < fetched && fetched - at >= bpp`). What the VI shows for a line blanked mid-fetch has no published reference. That makes it a model choice, recorded as a behaviors row. Acceptance: the repro ROM runs 60 s clean; MM 600 `--stats` md5 9629185039701bddcdbd90c248a4f38b unchanged, or the change explained; standing unchanged; a romgen regression ROM (the repro pattern, committed source) in the standing set. Then add the kit point (`k_vi_enable` mid-field variant), which turns hw:vi-mid-field-blank into a kit-vi question. Blocks: hw:vi-mid-field-blank and item fu.vi-mid-field-blank. Any game that blanks mid-field crashes. No hardware needed for the fix. Effort small.

**#86 (hazard tail keeps first-pass pixels).** Root cause, code read (cited rdp_core.c:306-369): `rdp_haz_publish` renders the whole primitive with the old state (line 322), then re-renders the tail from the change point with the new state (lines 358, 365). When the new state rejects a pixel, the old pixel stays. With IM_RD blend or Z update, a pixel blends twice. Fix scope: render [start, p) with the old state and [p, end) with the new state only. Non-overlapping ranges, as followups T15 suggests. Reference to assert now, with no hardware: n64brew "Effect of unsynced attribute changes" gives 27/26 px for z_mode pass-to-fail (cited #86). Build a romgen rdpstat check from the kit-tex attribute points with those expected values. Basis wiki. Coupling: rdpstat unsynced, snapper rect-nosync (20+40+20 match today, cited t17), and every unsynced change in MM. Pixel writes feed write-run timing, so MM md5 may move (inferred). Acceptance: z_mode both directions match the n64brew table in 1- and 2-cycle; snapper and rdpstat unchanged or explained; MM delta reported. Blocks: hw:attribute-stage (would fail on a known defect), item fu.rect-tail-twice. Effort medium.

**#87 (Watch never fires).** Root cause, code read: `CPU::Exception::watchAddress()` exists (exceptions.cpp:70, triggers 23), but nothing calls it. `grep watchAddress|trapOnRead|trapOnWrite` finds only the CP0 register read/write and serialization (measured). Fix scope: in the load/store path, compare the physical address bits 3-31 (WatchLo) and 32-35 (WatchHi) with trapOnRead/trapOnWrite, and raise at the DC-stage exception point (VR4300 UM, CP0 Watch, cited #87). The entry cost has no published value. It equals the other DC-stage exceptions (inferred), and hw:cpu-watch decides it. Acceptance: kit-cpu2 watch points fire 4/4 on the fork; nemu64 x3 values.tsv unchanged; MM md5 unchanged. Inferred: MM never sets WatchLo. Check with a WatchLo write counter on an MM 600 run. Blocks: hw:cpu-watch only. No behavior row names it (calib-kit-merge item 3, cited). Effort small.

**#77 (idle VI 0x800-VCLK grid sets the line phase).** Root cause, cited #77 and vi.cpp:121-131: the inactive branch steps 0x800 VCLK per call, so the first active line lands on a grid from power-on. No reference gives the hardware behavior. Not fixable without hardware. Making activation immediate is a model choice with no reference, and it moves bench values (#77: rspdma 6.422 everywhere at 1 VCLK, measured there). The deciders are hw:vi-first-line, which reads V_CURRENT at enable at 10 delays, and hw:vi-blank-counting, which closes #77. Blocks: bench:mi-memset-rspdma (pass-conditional:#77) and the phase spread of sp-dma-sweep. Do not pick a behavior to turn rspdma green. What not to do: the shipped boot delay is not a reference, so the conditional pass must not count as green.

**#82 (emux XPROFREAD 0x0201 RSP halted always 0).** Root cause, measured by grep: `rsp.profile.haltedCycles` is declared (rsp.hpp:324) and read (emux.cpp:168), but nothing increments it since 512acc926 (cited #82). Fix: when the RSP leaves halt, add the halted span to `haltedCycles`, or remove 0x0201 from the detect mask. Blocks no spec check: no tools/n64-timing consumer reads 0x0201 (measured by grep). It blocks mm-decomp tools/bench analyze.py's RSP busy %. Acceptance: on the BENCH ROM, rsp_halted + rsp_cycles equals the frame span within one quantum; MM md5 unchanged. No hardware needed. Effort small.

## 6. Weak checks in this cluster's reach

| check | state (measured, results tsv) | reference strength | path |
|---|---|---|---|
| bench:mi-memset-rspdma | pass-conditional:#77; 6.492..6.501, mean 6.498, band 6.49..6.515 | n64brew memset table, VI on, unknown phase. At layout pads 4-6 the mean was 6.491 (verify-79, cited): a 0.001 margin | stays conditional until hw:vi-first-line / vi-blank-counting. Do not count as green |
| bench:pi-dma-sizes, -8 | consistent-only; 8 B 180.0..194.67, mean 190 vs 193 | systembench one-binary reading (verify-83: codegen ±10 rclk) | hw:pi-dma-small + hw:systembench. Numeric cluster owns the 8-31 B model gap |
| systembench:si-dma-w-rom (row si.write64-rom) | consistent-only; 2140, rule holds 1/33 | single binary-phase reading | hw:systembench same-binary run. No refit (verify-83 supersedes the refit follow-up, cited) |
| systembench:u32r-banked | consistent-only; 134 vs 136 | era binary; 845635c build reads 133 (measured) | hw:systembench; -2 is one COUNT tick (verify-88, cited) |

**systembench 845635c vs era (measured from the two results.tsv files).** The same model, the same source, two builds. The rows that differ: c8r 4 vs 2; u32r-rand 151 (fail) vs 134; u32r-banked 133 vs 134; pi-dma-8 190 vs 187; pi-dma-128 1582 vs 1580; pi-dma-1024 12185 vs 12170 (+15); si-io-w 2151 vs 2150; si-io-r 1974 vs 1973. The build-to-build spread (up to 15 RCP, 17 CPU) is as large as the residuals the era build fails by (-4..-11). So the era build's pointwise systembench verdicts depend on codegen. That the era binary is the one that produced the published numbers is unproven: GCC 12.1 vs 12.2 moves rambuf, and u32r-rand reads 151 at 12.1 (verify-88, cited). Honest state: systembench pass and fail rows stand as checks of this binary. Only hw:systembench on the same binary turns them into model verdicts. The 845635c rows stay report-only (correct today). Do not refit to either build (verify-83).

**Loose rule (measured):** joy-empty-56b and -63b pass under main.c's 0.2% rule (21161 vs 21170 and 21178), while the model lacks the hardware's +7/+15 rclk over 8 B (verify-80, cited). Passing these rows does not test the 56/63 B effect. Closing action: mark them as not deciding pif.joybus-skip and pif.joybus-escape beyond the 5-channel cap (U-LBL). hw:joybus-pads (item fu.joybus-56-63) decides.

## 6.5 Every non-green, non-fail row: true blocker and closing action

| row | status (measured) | true blocker | closing action |
|---|---|---|---|
| clock.vclk | cal-16 + report-only | derived from the cited crystal; no measurement; mm:south-clock-town has no value | hw:count-per-field (R1; check the tolerance first) |
| cpu.ifill-stall | cal-16 + report-only | inferred 45 (range 45-47); bench check is dead | U-DEAD, then hw:ifill |
| cpu.dcb | cal-16 | vendor +1, no corpus case | hw:dcb |
| cpu.dirty-miss-order | cal-16 + report-only | vendor order, no console value | hw:dirty-miss |
| cpu.wb-release | cal-16 + report-only | NEC vs R4300i conflict | U-DEAD (wb-fifth-store), hw:wb-release, hw:wb-drain-target |
| sysad.register-write | cal-16 | MiSTer RTL only | hw:register-write, hw:wb-drain-target |
| pif.joybus-no-device | cal-16 + report-only | fit under an assumed pad count | hw:joybus-pads with 4 pads (R2). Do not assert the 2J-4J reports |
| ai.fetch-bytes | cal-16 + report-only | patent value; the fork reads 4 B steps | hw:ai-fetch (predicted F, guess) |
| vi.register-sample | cal-16 + report-only | model choice | hw:vi-fetch-modes |
| vi.display-window | cal-16 + report-only | model choice | hw:vi-fetch-modes, hw:vi-fetch-position |
| rdp.cmd-fifo-dwords | cal-16 | author's TODO note | U-DEAD (current-prefetch), hw:cmd-fifo-depth |
| rdp.cmd-fetch-burst | cal-16 | model choice | hw:cmd-fetch-burst (gcd caveat) |
| rdp.fill-copy-rate | cal-16 + report-only | SDK pipeline rate; the kit metric includes memory bandwidth | U-DEAD (thar0:fill-mode), hw:fill-copy-rate; read a fail with care |
| rdp.tmem-load-rate | cal-16 + report-only | two published laws conflict; the fork matches neither | U-DEAD (loadsz), hw:tmem-load-rate (predicted F) |
| rdp.color-half-pixels-16bpp | cal-16 | span-ram.md open question | hw:color-half-16bpp |
| rdp.noise-alpha-dither | cal-16 | Angrylion vs MiSTer conflict | hw:noise-alpha-dither |
| rdp.noise-dither-bits | cal-16 | none published | hw:noise-dither-bits |
| legacy.pi.cart-read | cal-16 + no-corpus | domain 2 still legacy 250 pclk | U-DOM2, U-LBL, hw:dom2-read |
| legacy.ai.power-on-rate | cal-16 + no-corpus | none published | U-LBL (drop no-corpus), hw:ai-rate |
| 10 fit-only rows | fit only | see section 8 | section 8 (3 need U-FIT3) |
| scheduler.tie-rank, ri.request-latency | model-choice | not hardware-decidable | reclassify: excluded |
| vi.fetch-overrun | model-choice | video only | D2 / U-VIDEO |
| vi.unfetched-sample | report-only | video only | D2 / U-VIDEO |
| si.write64-rom | consistent-only | one-binary, codegen-sensitive reading | hw:systembench, same binary |
| legacy.clock.vclk-pal | no-corpus | out of target | remove or exclude |
| legacy.cpu.nmi-entry, legacy.cpu.sysad-frozen-step, legacy.pif.step-quantum | no-corpus | not hardware-decidable | excluded; U-LBL fixes the sysad note |
| legacy.pif.boot-timeout, 8 legacy.cart.* | no-corpus | out-of-kit | D1 |
| legacy.cpu.interrupt-entry | pass (overstated, inferred) | its check is another row's fit data, functional only | U-LBL, then hw:cpu-exceptions |

## 7. Harness gaps that can make a green untrustworthy

1. **Code-layout phase is not walked** (cited followups labels-phase; standing.sh walks boot delays only, measured by reading lines 22-31 and grep for a layout pad: none). Four extra instructions moved rspdma min 6.422->6.492 and pi-dma-8 mean 189->190 (cited). Any bench verdict within about 0.1% of a band edge is one layout away from flipping. U-LAYOUT: add a code-layout pad axis (8 pads = one 32 B I-cache line period, per verify-79) to the bench phase rule over a subset of boot delays, and report the joint range. Acceptance: phases.tsv carries both axes, and every bench verdict states its joint range. Inferred cost: about 8x bench time on a reduced delay set.
2. **Thin margins (measured from standing/bench/results.tsv):** rspdma mean at 0.008 above its band floor (0.001 at pads 4-6); uncached-sizes u32-seq and u32-rand read 131 with band 131..133, exactly at the edge; si-dma write64 4058.67..4073.33 vs band 4056.87..4073.13. U-LAYOUT covers all of them. Do not widen bands.
3. **Stale ROM risk.** Standing rebuilds every suite ROM from the tree and records sha256 (standing.sh:22-31, measured by reading). External ROMs are pinned: pi_dma_test by sha in standing.sh; systembench era by sha fd5ec6c0 in provenance (cited). Residual risks: ad-hoc unit measurements outside standing (pref 25 already covers them), and the console-capture vs model-ROM mismatch above (section 2, ingestion gap).
4. **Standing run time:** about 13 min of suites (load-start 03:49:54 to load-end 04:02:41 in calib-kit-merge/standing, measured from file times), plus builds. Fine for iteration. U-LAYOUT multiplies the bench part.
5. **Textual "read" test** for `code`/not-built (cited verify-74 note 2): comments count as reads. A row can look built when it is not. Fix: strip comments before matching (U-LBL).
6. **Unrecorded MM wall re-time.** The Destination "<= 2 min" cites T16 medians on 6dfbf7166 (closure draft, cited). Master has changed the core since. SOFTWARE_READY requires a re-time on current master with copied runners (pref 26). No unit has done it since T16 (inferred from the reports read).
7. **thar0-console cross-binary compare** (section 2): the console runs the original ROM, the fork runs the port. Root-causing the port's --hw hang would make the comparison same-binary. Unknown effort (guess); not root-caused in two units.
8. **Watch, CU2 and DP-wait console safety** is unverified without hardware (calib-kit-fix §4, cited). This is acceptable. hardware-run.md handles a hang.

## 8. Fit-only and model-choice rows: what independent check moves each

| row | fit from | independent check today | independent check possible | unit |
|---|---|---|---|---|
| cpu.exc-fpu-detect, cpu.fpu-trivial | nemu64 cop1instructions32/64 | none | hw:fpu-classes samples unsampled classes (independent) | #16 only |
| cpu.eret | exception-roundtrip | none | hw:cpu-exceptions isolated ERET | #16 only |
| cpu.irq-sample | cop0hazard softwareinterrupt | none | hw:cpu-exceptions irq points | #16 only |
| cpu.count-write-hold | cop0hazard count | none | **none in kit**. Needs a new point: MTC0 COUNT then MFC0 at slots +1..+4 in a harness that does not reset COUNT | U-FIT3 then #16 |
| cpu.fetch-ahead-slots | smc-multiple/single | none | **none in kit**. Needs a store exactly 2 and exactly 3 slots before a line boundary with layout pinned (inferred: romgen can pin the boundary with .align) | U-FIT3 then #16 |
| cpu.ctc1-fpe-ce | cycle/ctc1 | none | **none in kit**. Needs CTC1-raised FPE followed by a non-coprocessor instruction and by COP0, whose CE the row infers from opcode bits | U-FIT3 then #16 |
| rdp.primitive-base, span-dead-pixels, span-line-gap | Thar0 alpha-fail 1/2-cycle | none (cen64 RECTN/DUTY conditions unpublished) | hw:rdp-rect-base | #16 only |
| scheduler.tie-rank, ri.request-latency | - | guards only | none: excluded, not hardware-decidable | reclassification is the end state |
| vi.fetch-overrun | - | guards only | video capture only (hw:vi-unfetched-video) | U-VIDEO or reclassify out-of-kit |

## 9. Units (path to SOFTWARE_READY for this cluster)

Each unit is no-hardware unless it says so. Effort: S = less than half a day of agent time, M = about one day. All are inferred estimates.

- **U-84** (S). VI compose latch plus an overflow-safe guard, a regression ROM, and the mid-field kit point. Files: ares/n64/vi/vi.cpp, vi.hpp, romgen calib asm (kit-vi), questions.tsv, behaviors.tsv (new model-choice row). Acceptance in section 5. Independent confirmation: hw:vi-mid-field-blank becomes R1.
- **U-87** (S). Raise Watch. Files: ares/n64/cpu memory access path and exceptions.cpp. Acceptance in section 5.
- **U-86** (M). Non-overlapping hazard ranges, plus an n64brew-table rdpstat check. Files: ares/n64/rdp/engine/rdp_core.c, romgen rdpstat set, checks.tsv. The pixel change can move MM, so a full standing run is required.
- **U-82** (S). haltedCycles accrual. Files: ares/n64/rsp/rsp.cpp. Blocks no spec check.
- **U-PIDMA** (M). Remove hw:pidma-offset's hardware dependency. The ROM's own self-check is already offset-free: it compares COUNT deltas against the golden tables inside the ROM, under its float32 0.1f band (pidma-replay.py:14, 123-130, 236, cited). Today the fork fails 8 points (capped) at sizes 3-4. Steps: (a) log the ROM's COUNT reads under ARES_PILOG (followups not-built) so the replay uses the fork's own offset; (b) make the verdict "ROM self-check SUCCESS and replay at the logged offset within 3%". Confirmation: the replay at the logged offset agrees with the ROM's self-check on which points fail. Then reclassify hw:pidma-offset as superseded (delete it from questions.tsv). Guess: (a) is possible because n64-run sees every COP0 COUNT read. Test it on a scratch build first.
- **U-MMR** (M; needs Scott's merge of mm-decomp-60fps PR #1, or a pinned commit of its bench/fork branch). An `ext_mm_bench` reader. Build the BENCH ROM in a separate worktree (pref 29), pin its sha (b58e49e9... unpinned build, tools-bench report), run it on n64-run in calibration/run.sh as the model side, and compare per-frame fields and DPC_CLOCK against a console capture under the pref-27 range rule. Closes the reader gap for hw:mm-filesel and mm:south-clock-town.
- **U-DEAD** (S). Delete bench:ifill-isolated, bench:wb-fifth-store, bench:rdp-loadsz-sweep, thar0:fill-mode, rdpstat:current-prefetch. Fix mm:file-select's source text. Fix rdp-rectn's gate text ("conditions unpublished"). Acceptance: `behaviors.py --check` ok; row_status diff over 149 rows shows no change (that no row moves is inferred, so verify it).
- **U-LBL** (S). Make legacy.cpu.interrupt-entry's softwareinterrupt a guard and add hw:cpu-exceptions; fix the sysad-frozen-step note; drop `pending:no-corpus` where a kit question exists (legacy.pi.cart-read, legacy.ai.power-on-rate); make hw:snapper64 a guard on its rows; add "does not decide 56/63 B" to pif.joybus-skip/escape; strip comments in the code-read test; add the third class "charged with no hardware reference" to the closure draft; report SOFTWARE_READY and MAP_GREEN in the closure draft. Acceptance: --check and --self-test pass, and the generated spec shows both predicates.
- **U-INGEST** (S). Add the ROM sha256 to the `#kit` header, and have ingest fail when the console ROM sha differs from the model-side ROM. Acceptance: a kit-self-test case with a mismatched sha fails.
- **U-LAYOUT** (M). Code-layout pad axis in the bench phase rule (section 7.1).
- **U-DOM2** (M). A derived domain-2 PI read from the BSD registers, validated by reproducing domain 1's measured 144 rclk with the same formula. If the formula cannot reproduce domain 1 without a fitted term, stop and leave the row legacy (pref 7).
- **U-FIT3** (M). Three new kit points (section 8) as new questions that close cpu.count-write-hold, fetch-ahead-slots and ctc1-fpe-ce independently.
- **U-SPDMA** (M). An RSP-timed SP DMA point for 8-128 B (calib-kit-fix 2a.5). The RSP reads its own clock, so no CPU poll quantum applies. Guess: RSP-side timing is console-safe. Verify with the existing RSP kit code.
- **U-VIDEO** (decision D2). Either build a video-capture question (test pattern, column-level compare of a captured frame) or reclassify vi.unfetched-sample and vi.fetch-overrun as out-of-kit. MM never reaches either path (row note, cited), so the reclassification costs MM nothing.
- **U-WALL** (S). Re-time 600-frame MM on current master with copied runners, interleaved, and record the load average (pref 22, 26). Update wall-budget.tsv.

Decisions for Scott (only he can make them; reversible defaults in brackets):
- **D1.** Are the 9 out-of-kit legacy rows (cart chips, boot timeout) in MAP_GREEN's scope? [Default: they are reported as "out-of-kit, open" and block MAP_GREEN. Scott could rule them out of scope, since MM benches never save (guess).]
- **D2.** Video capture for vi.unfetched-sample / vi.fetch-overrun: build it or reclassify? [Default: reclassify as out-of-kit.]
- **D3.** Merge mm-decomp-60fps PR #1 (Destination item 4 and U-MMR depend on it).

What not to do:
- Do not assert the joy-2j..4j / read64-2..4 reports. They are pif.joybus-no-device's fit data under an assumed pad count.
- Do not assert the cen64 RECTN/DUTY values. Their conditions are unknown.
- Do not pick a VI-activation behavior to make rspdma pass (#77).
- Do not refit pi.io-busy, si.io-busy, si.write64-rom or pi.block-writeback to either systembench build (verify-83).
- Do not count hw:snapper64 as model verification.
- Do not widen the vi-first-line, count-per-field or main.c rules to absorb a console result. Derive each tolerance from a cited spread first.
- Do not count a fork-vs-fork dry-run pass as readiness evidence beyond wiring.

## 10. Dependency order

1. U-DEAD, U-LBL, U-INGEST: labels and tooling only. No row value moves. They make the predicates reportable.
2. U-84, U-87, U-82: small core fixes. Each needs MM md5 and nemu64 unchanged, or the change explained.
3. U-86: an RDP pixel change. Run it after step 2 so its MM delta is attributable.
4. U-PIDMA, U-LAYOUT, U-WALL: harness. U-LAYOUT can turn passes into consistent-only or fail. Run it before claiming SOFTWARE_READY.
5. U-DOM2, U-FIT3, U-SPDMA: new behaviors and kit points.
6. U-MMR after D3. U-VIDEO after D2.
7. #16 session (human): hardware-run.md, then `ingest.py`, then `standing.sh` and `--results`.

Can reach a final state without hardware: #84, #86 (against the n64brew table), #87 (function only; its cost stays hw), #82, all dead and duplicate checks, all label fixes, the pidma verdict (if U-PIDMA's guess holds), and the predicates themselves. None of these turns a pending row green except through U-86's new check: rdp.attribute-stage already passes, so the #86 fix keeps that row honest rather than flipping it (inferred).

Only #16 decides them (kit question): the 19 calibration-16 rows (each row's question is in section 2), 7 of the 10 fit-only rows (fpu-classes, cpu-exceptions, rdp-rect-base), the weak checks (vi-first-line and vi-blank-counting for #77; systembench for the systembench rows; pi-dma-small for the pi rows), and every predicted-F hw check, where the console localizes the failure rather than greening it.

Honest end state is a reclassification: scheduler.tie-rank, ri.request-latency, legacy.clock.vclk-pal (out of target), legacy.cpu.nmi-entry, sysad-frozen-step and pif.step-quantum (excluded); the 9 out-of-kit rows (pending D1); hw:pidma-offset (superseded by U-PIDMA); hw:snapper64 (guard); vi.unfetched-sample and vi.fetch-overrun (pending D2); legacy.cpu.interrupt-entry (pass -> pending:calibration-16); the five dead checks (deleted).

No background process of mine is running (ps checked). Scratch: /home/wscottsh/n64-timing/results/plan-pending/vi84-gdb.txt.
