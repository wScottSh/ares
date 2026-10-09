# Plan: the remaining checks to green

This plan covers every check and behavior row that is not green on master `8d86b87cd`. It says what green can honestly mean, what blocks each item, and the ordered units that close each one.

Four read-only investigations produced the evidence. An adversarial review then checked the plan against them and against the master results, and this version applies its findings. The investigations are the appendices, and the review is the fifth file:

- [bus.md](green-plan/bus.md): RDRAM interface, SysAD, VI fetch, refresh, and the nemu64 failures.
- [pisi.md](green-plan/pisi.md): PI, SI, PIF, the systembench poll rows and the PI DMA replay.
- [rdp.md](green-plan/rdp.md): RDP memory, Thar0, rdpstat, and MM file select.
- [pending.md](green-plan/pending.md): pending and report-only checks, open issues, kit readiness, and the green predicate.
- [review.md](green-plan/review.md): the review's findings.

Each claim carries a label: measured (run on the built emulator during the investigation), cited (file and line, or URL), inferred, or guess. The appendices give the raw files behind each measured number.

## 1. What green means

Map #1's rulings bind this plan. "Accuracy is the only goal." "There is no unverified status; a behavior is either built from its references or not built." Standing order 21 adds that a check against a row's own fit data is not verification. So no unit may turn a check green by fitting a value to the data that checks it, and no unit may widen a band without a cited spread. Every pass rule a unit uses is fixed in this plan, before the unit runs.

The program reports three things:

```
SOFTWARE_COMPLETE  (the reachable software-only end state)
  every P0-P4 unit has landed or is closed with a stated reason
  AND every non-green check names the kit question or console condition that decides it
  AND no check is green through its own fit data or a fitted third-party threshold
  AND no check is dead (no ROM, no reader, or duplicate)

SOFTWARE_READY  (reported as "n of 6 clauses hold"; cannot hold without the console run)
  1. det and stepcap pass, and the 600-field MM run takes <= 120 s, re-timed on current master
  2. no check is fail
  3. no check is consistent-only or pass-conditional
  4. every pending check is pending:calibration-16 on a kit question a tool can compare
  5. no check is report-only, no-rom or no-corpus, except on excluded or out-of-kit rows
  6. every row that is not verified names a hardware question independent of its fit data

MAP_GREEN  (the map's destination)
  SOFTWARE_READY
  AND mm:filesel-empty and mm:filesel-named pass
  AND wScottSh/mm-decomp-60fps#1 is merged
  AND every hw:* check is ingested and passes
  AND every row that is not excluded or out-of-kit is verified
```

SOFTWARE_READY cannot hold without hardware. Clauses 2 and 3 stay false until the console run, because the failing checks in section 3 that only a console decides stay failing. So the software-only goal of this plan is SOFTWARE_COMPLETE, and SOFTWARE_READY is reported as a count of clauses.

Excluded rows are the 7 entries marked `not-hardware-decidable` in `tools/n64-timing/calibration/undecidable.tsv`. They can never be green, and the report names them. Out-of-kit rows are the 9 entries marked `not decidable by this kit`: the cartridge chips and the PIF boot timeout. A console could decide them, but this kit cannot. They block MAP_GREEN unless Scott rules them out of scope (decision D1).

The console run will not turn every hardware check green. At least 15 hardware checks are predicted to fail, because the emulator already misses a published value for the same quantity (pending.md section 2, inferred). Each of those failures becomes a P6 fix unit with the console value as its reference. MAP_GREEN therefore needs P6, not only P5.

### Where master stands (measured, `docs/spec/n64-timing-results.tsv`)

| Result | Checks |
|---|---|
| pass | 87 |
| fail | 23 |
| consistent-only | 4 |
| pass-conditional | 1 |
| pending:calibration-16 | 80 |
| pending:report-only | 14 |
| pending:no-rom | 1 |

Of the 149 behavior rows, 33 fail, 10 are fit only, 3 are model choices, and 33 are pending. One more failing datum sits outside the check list: `bench:mi-memset-repeat` reads 1.31 ms/MiB against n64brew's 3.8 in the standing run, and no check row asserts it (review S5, measured). Unit U-LBL wires it in.

## 2. What the investigations found

### Bus: no failing check can go green without hardware (bus.md)

- **The memset table's video state is unknown (cited).** The table entered the n64brew MIPS_Interface page in revision 5278 (2023-11-13). No revision gives the loop code, the video state or a source. The bench data cannot separate two readings: the table was measured with the VI off, or the model's VI costs CPU traffic about twice what the nemu64 hardware means show (inferred). Only kit question `memset-vi` (q20), run after `vi-cpu-contention` (q24), decides it.
- **Refresh explains only part of the D-fill tail (measured).** T6's reason for keeping refresh off while the VI is blank is false on current master.
  - With refresh running while blank, the uncached VI-off reads get a +0.6 tail (hardware +0.54). The D-fill reads get only +0.47 (hardware +1.5).
  - It also pushes the hardware-era systembench uncached rows +2..+3 out of band. So the two hardware suites conflict under the model's refresh.
  - The model's D-fill mean is also a phase lottery: 41.0..42.03 across idle line lengths.
  - One model defect candidate remains untraced: a hpos report row shows a 74.67 rclk holdoff against the 52/54 rclk in the RI row (measured). Its cause is a guess. Unit U-REFRESH traces it.
- **The same-bank VI-on tail is VI waits, not row misses (measured).** The datasheet's 22 tc row miss reproduces the hardware median shift of +4. The model's tail (mean minus median) is 4.7 same-bank and 1.7 other-bank, against hardware's 0.3 and 0.5. Every lever with a reference was tried, and none fixes it. Retrying a row miss at 11 tc passes the test but breaks four other checks, so it is a circular refit.
- **`bench:sp-dma-sweep` measures the wrong quantity (inferred).** It times one DMA through setup and a busy-poll. Its reference is the 256-DMA memset rate, which the RSP-DMA port of the same rate already passes.
- **If the console shows no VI tail and no mechanism with a reference exists**, the VI cost to CPU traffic becomes a "not built" behavior, not a fit (bus.md).

### PI and SI: one model-choice value explains most failures (pisi.md)

- **The posted-write drain sets the poll grid (measured, era binary).** The first PI_STATUS or SI_STATUS read waits behind the posted register write, so the poll loop starts when that write drains. A busy time then moves the reading only in whole poll steps of about 15.3 rclk. PI I/O W can read only 112, 130, 145 or 161, so no busy value reaches hardware's 134. That is why refitting the busy rows could never work.
- **The drain value is a fit to five systembench rows (measured).** The value 100 Clock units (8.33 rclk) is where five rows' pass windows overlap: pi-io-w (76..128), si-io-w (100 and up), si-dma-w-rom (60..108), si-dma-w-ram (108 and below) and pi-dma-128. At 100 the rows read PI I/O W 134 (hardware 134), SI I/O W 2154 (2158), SI DMA W ROM 2146 (2144, passing in 33 of 33 runs instead of 1) and PI DMA 128 1590..1591 (1591). All five rows chose the value, so all five pass by construction. They are the fit's data, not verification.
- **One independent check agrees (measured).** The PI DMA replay (`pidma:logs`) is a different ROM with different hardware data. On the subset of points that run 4 times at every drain value, its failures go from 24 at master's value to 2 at 100. That places the drain at 84..108 units, overlapping the systembench window. The full-set count is confounded: at master's value the ROM hits its 8-failure cap and drops to one run per point.
- **PI DMA 8 stays out of band (measured).** At 100 it reads 196 against 193. No single drain value passes every row.
- **The PI DMA offset can be pinned without hardware (measured).** n64-run can log the ROM's own COUNT reads and pair them with each PI_WR_LEN store. That reproduces all 8 values the ROM prints. It also shows the old constant-offset calibration was wrong: the gap from store to DMA start varies per point (52, 108 or 228 units). The exact replay on master reads 23765 of 24000, outside the range 23776..23833 the old calibration reported.
- **The remaining replay failures cluster at row ends (measured).** RAM 0x7fc and 0x7fe account for 21 of the 40 failures left at a drain of 100. The model is 3-6% low there. Two mechanisms fit, and neither has been measured (pisi.md): a masked first burst, or ares posting no RDRAM write when the first block has 0 bytes.
- **Sizes 305-352 do not match the hardware build.** A cart page-phase difference between the hardware build and this binary makes those points unusable (pisi.md, inferred).

### RDP: separate mechanisms behind Thar0 (rdp.md)

A factorial decomposition of the 100 Thar0 configs (measured, `results/plan-rdp/thar0/factors.py`) separates the residuals:

- **F1. Write-only configs run 11 rclk per line fast.** A span that starts only after earlier write-backs have landed removes it. n64brew Set Color Image says "no such buffering across multiple rows" (cited). Reading that sentence as this rule is an interpretation (inferred). Thar0 selected this rule among seven variants, so Thar0 is its selection data. The one independent check is the cen64 probe data: DUTY minus RECTN cancels the unknown bracket and gives 334.47 rclk per line. Master gives 324.0, and the rule gives 334.08 (measured). That cancellation is inferred, because the probe's conditions are unpublished. The atomic sweep then needs the 1PRIMITIVE dead cycles to count after the last write lands, which keeps it at 34.67 and passing (measured).
- **F2. The order in which memory streams overlap is wrong.** This drives the IM_RD configs (+8%). Hardware fits a serial sum per 64 B half: 4 values solved on 4 configs predict 4 other configs within 5.1% (inferred, from hardware arithmetic alone). The model's per-operation costs already match those values. What is wrong is the ordering in `Port::eligible`. No reference describes that ordering, so it needs #16.
- **F3. 2-cycle Z reads run about 12% fast.** On hardware a 2-cycle Z read is partly exposed. The model shades a span only after its whole read window, up to 4 KiB, has landed. Hardware span RAM is 128 B per image (cited, `span-ram.md`), so hardware must stream reads through two halves. Fully serializing the reads overshoots, with a 17.8% mean residual (measured).
- **F4 and F5 belong to the bus.** Same-bank row conflicts cost 1.3-1.5 times what the model charges, and VI interference costs 2.5-3 times as much when the RDP is memory-bound.

The 10 failing named Thar0 checks map to these mechanisms (review S2, from rdp.md and `compare.tsv`):

| Check | Residual | Mechanism |
|---|---|---|
| thar0:imrd-1cycle | +8.07% | F2 |
| thar0:nozb-vioff-imrd-1cyc | +8.07% | F2; the same config as imrd-1cycle, a duplicate check |
| thar0:nozb-visep-imrd-1cyc | +4.05% | F2 and F5 |
| thar0:ac-zcmp-zbsep-vioff-imrd-1cyc | +2.43% | F2 |
| thar0:separate-bank | -0.19% | F2; fails because its VI-off band is only 0.12% wide |
| thar0:zbrw-pass-zbsep-visep-noimrd-1cyc | -5.28% | F2 and F5 |
| thar0:zbrw-fail-zbsame-visame-imrd-2cyc | -4.68% | F3, F4 and F5 |
| thar0:nozb-visame-noimrd-1cyc | -4.91% | F1 and F5; after the F1 rule it reads 80857, -1.1%, still failing |
| thar0:zcmp | +2.54% | unexplained: 1-cycle Z read only, in no family |
| thar0:ac-zbsame-vioff-imrd-1cyc | +2.55% | unexplained: alpha compare with IM_RD, same model value as zcmp |

The F1 rule turns none of these green. Three of them (ac-zbsame-vioff-imrd-1cyc, nozb-vioff-imrd-1cyc, ac-zcmp-zbsep-vioff-imrd-1cyc) belong to no behavior row, so they block no row. Thar0 progress is reported as the mean absolute residual per family, F1 to F5.

The other RDP findings:

- **rdpstat:1prim fails structurally (measured).** The model reads stale at every width from 8 to 256 px, because it snapshots the whole span's read. The 8 px expectation has indirect hardware backing: cen64 commit e6b58c6 ties its checksums to Nintendo's N64 Diagnostic cartridge (cited). The 32 px "fresh" expectation is cen64's fitted threshold of 25 px or more, extrapolated. So only the 8 px cases can count toward green.
- **No single mechanism passes all three file-select rows (measured).** The RDP is the critical path for about 92% of frame time, and audio RSP tasks cause the frame-to-frame jitter. The empty screen's slow tail and the named screen's fast tail sit about 0.1 ms apart, so no uniform slowdown passes both. Four mechanisms were tried, and each passes the named row but breaks the empty row. The F1 rule gives named 1.932 (pass) and empty 1.148 (fail). A single run near the empty row's edge also flips with phase alone (94.8% vs 95.6%).

### Pending checks and open issues (pending.md)

- **The kit flips 76 of 80 hardware checks in a dry run, but that proves only wiring.** 65 would settle in one clean session, 11 need conditions, and 4 cannot settle at all.
- **Ingestion never compares a capture's ROM build with the model side (inferred from grep).** A capture from a different commit would be compared silently.
- **None of the 14 report-only checks can honestly be asserted now.** The JOY 2J-4J and read64 reports are a fit's data under an assumed pad count. The cen64 RECTN and DUTY absolutes have unpublished conditions. The rest have no published value.
- **Issue #84 is reproduced, with a known fix (measured with gdb).** `compose()` reads the live color depth (0 after the blank) for a fetch that started at 16 bpp, and the guard `at + bpp <= fetched` then overflows in u32.
- **Issue #86 has a known fix (from reading the code).** `rdp_haz_publish` (`rdp_core.c:306-369`) renders the whole primitive with the old state, then overdraws the tail with the new state.
- **Issue #87 (from grep).** `exceptions.cpp watchAddress()` is never called.
- **Issue #82 (from grep).** `haltedCycles` is never incremented. No spec check depends on it.

## 3. Every non-green check: disposition

"Fit only" means the check passes but verifies only the fit's arithmetic, so it does not count as green.

| Check | Now | End state | Unit or kit question |
|---|---|---|---|
| systembench:pi-io-w | 130 vs 134 | passes as fit data of `sysad.register-write`, fit only | P2 U-DRAIN; confirmed by pidma:logs and #16 `register-write`, `wb-drain-target` |
| systembench:si-io-w | 2150 vs 2158 | same | P2 U-DRAIN |
| systembench:si-dma-w-rom | consistent-only, 2140 vs 2144 | same | P2 U-DRAIN |
| systembench:pi-dma-128 | 1580 vs 1591 | same; it is also `pi.block-writeback`'s fit data, and that row stays fit only | P2 U-DRAIN |
| systembench:pi-dma-8 | 187 vs 193 | still fails after U-DRAIN (196) | #16 q `systembench` (same binary) |
| pidma:logs | 23765 / 24000 (exact replay) | green only under the fixed rule below | P0 U-PIDMA-EXACT, P2 U-DRAIN, P2 U-ROWEND |
| bench:pi-dma-sizes, bench:pi-dma-sizes-8 | consistent-only | report-only: systembench:pi-dma-* runs the original code | P0 U-LBL |
| systembench:u32r-banked, bench:uncached-sizes-u32-banked | 134 vs 136, 131 vs 134 | one COUNT tick; needs hardware | P1 U-RES, then #16 q18, q35 |
| bench:mi-memset-uncached | 17.717 vs 18.38 | needs hardware; no refit | #16 q24, then q20 |
| bench:mi-memset-cached | 72.736 vs 71.24 | needs hardware; no refit | #16 q24, then q20 |
| bench:mi-memset-repeat (unasserted) | 1.31 vs 3.8 | asserted, then needs hardware | P0 U-LBL wires it; #16 q20 |
| bench:mi-memset-rspdma | pass-conditional:#77 | needs hardware | #16 q77, q12 |
| bench:sp-dma-sweep | 6.35 vs 6.5 | report-only (wrong quantity) | P0 U-LBL; #16 q21 is the real check |
| nemu64:timing/load-miss-vi-off (8 values) | every miss 41, hardware mean 42.5 | phase-mean check, then hardware | P0 U-NEMU-PHASE; #16 q34 with D-fill histogram |
| nemu64:timing/load-from-uncached-vi-on-same-bank | mean 41.6 vs 36.3 ± 4 | needs hardware | #16 q24 with per-load histogram, q44 |
| thar0 F2 checks (6, table above) | +8.07% .. -5.28% | needs hardware | #16 `imrd-zcmp-slots`, the new 2-cycle points, `thar0-console` |
| thar0:zbrw-fail-zbsame-visame-imrd-2cyc (F3) | -4.68% | structural fix, then hardware | P3 U-SPANRAM; #16 |
| thar0:nozb-visame-noimrd-1cyc (F1, F5) | -4.91% | improves to -1.1% with U-RDP-DRAIN, still fails; F5 needs hardware | P2 U-RDP-DRAIN (behind D5); #16 q24 |
| thar0:zcmp, thar0:ac-zbsame-vioff-imrd-1cyc | +2.54%, +2.55% | unexplained | P1 U-THAR0-ZC investigation; #16 `thar0-console` |
| rdpstat:1prim, 8 px cases | pass | stay pass | none |
| rdpstat:1prim, 32 px cases | fail | report-only: the expectation is a fitted cen64 threshold, extrapolated | P0 U-LBL |
| mm:filesel-named | 1.6941 vs 1.90-2.10 | needs hardware; no constant tuned to 2.00 | #16 `mm-filesel`, `triangle-setup` |
| systembench:joy-2j/3j/4j, bench:si-dma-read64-2/3/4 | report-only | stay report-only (fit data under an assumed pad count) | #16 `joybus-pads` |
| rdpstat:current-prefetch | no-rom | delete (duplicates hw:cmd-fifo-depth) | P0 U-DEAD |
| bench:ifill-isolated, bench:wb-fifth-store | report-only, no ROM | get ROMs (they measure what kit q14, q15 measure on hardware) | P4 U-ROMS |
| bench:rdp-loadsz-sweep, thar0:fill-mode | report-only | stay report-only (rdp.md); loadsz gets a ROM | P4 U-ROMS |
| bench:dirty-miss-isolated, bench:dirty-row-sweep | report-only | stay report-only until hardware | #16 q16, q17 |
| bench:rdp-rectn | report-only | the per-line slope becomes an asserted check if U-RDP-DRAIN lands; absolutes stay report-only | P2 U-RDP-DRAIN |
| mm:south-clock-town | report-only | a coarse cadence check from existing hardware captures, if research finds one; else stays report-only | P1 U-SCT |
| 80 hw:* checks | pending:calibration-16 | ingested after #16 | section 4, P5 |

### Pass rules fixed now

These rules are set before the units that use them, so no rule is chosen after its result is known:

- **pidma:logs.** Every point at sizes 8-382, except 305-352, is within the golden min..max ±3%, and the ROM's own self-check reports 0 failures. The excluded sizes and their reason are named in the check. No point count stands in for this rule.
- **nemu64 phase walk.** For each averaged test, the hardware mean must lie within the test's own published tolerance of the model's mean over the VI phases. The phase range is reported beside it.
- **MM file select.** Each row is judged on its median over the mmbench phase sweep, using the row's existing criterion. The minimum and maximum are reported. A row passes only if its median passes.
- **Bench layout pads.** A bench verdict holds only if it is the same at every layout pad, or the check reports consistent-only with its range.

## 4. Units

Each unit is one PR with an independent verifier, as in the rest of the program. "No hardware" means the unit needs nothing from Scott. Effort estimates are guesses.

### P0. Harness trust and labels (no timing value changes)

| Unit | Scope | Acceptance |
|---|---|---|
| U-DEAD | Delete rdpstat:current-prefetch; fix the mm:file-select and rdp-rectn source text | `--check` ok; no row status changes |
| U-LBL | Every label fix in pending.md section 9 (U-LBL), plus: relabel bench:sp-dma-sweep, bench:pi-dma-sizes and -8, and rdpstat:1prim 32 px as report-only; wire bench:mi-memset-repeat as a failing check; relabel ri.overhead-vi as model-choice; correct the ri.refresh-trigger note (its "+2" is measured +0.3); add a model-choice row for the refresh latch; make legacy.cpu.interrupt-entry pending on hw:cpu-exceptions; make hw:snapper64 a guard; fold the duplicate thar0:nozb-vioff-imrd-1cyc into thar0:imrd-1cycle; report SOFTWARE_COMPLETE, the SOFTWARE_READY clause count and MAP_GREEN in the closure draft | `--check` and `--self-test` pass; the spec shows the three reports |
| U-INGEST | Put the ROM sha256 in the `#kit` header; ingest fails when the console ROM differs from the model side | a kit self-test with a mismatched sha fails |
| U-RULES | Pre-run hygiene: derive the tolerances of vi-first-line, count-per-field and nemu64-console from a cited spread, or state that none exists | each rule cites its spread, or its check says why it uses its own published tolerance |
| U-PIDMA-EXACT | Log the ROM's COUNT reads under ARES_PILOG; replace the constant-offset calibration with the exact per-point replay; apply the pidma rule above; retire hw:pidma-offset | the replay reproduces the ROM's 8 printed values; master reads 23765 / 24000 |
| U-LAYOUT | Add a code-layout pad axis to the bench phase rule | every bench verdict follows the layout rule above |
| U-NEMU-PHASE | Walk VI phase for the nemu64 averaged tests; apply the nemu64 rule above | the C7 and same-bank checks report their phase range and verdict |
| U-MM-PHASE | Add a phase sweep to mmbench; apply the file-select rule above | each file-select row reports median, minimum and maximum |
| U-WALL | Re-time the 600-field MM run on current master with copied runners | `wall-budget.tsv` updated; repeated at the end of P3 |

### P1. Core bug fixes and investigations (no hardware)

| Unit | Scope | Acceptance |
|---|---|---|
| U-84 | Latch VI geometry at HSYNC; make the compose guard overflow-safe; add a regression ROM and the mid-field kit point | the repro ROM no longer crashes; hw:vi-mid-field-blank gets a model side; MM and nemu64 outputs unchanged |
| U-87 | Call `watchAddress()` on loads and stores | the kit's watch points fire on the fork; MM and nemu64 unchanged or each difference explained |
| U-86 | Render hazard tails as disjoint ranges; add an rdpstat check against the n64brew 27/26 table | the new check passes; snapper 2592 / 2592; rdpstat and Thar0 unchanged; MM difference explained pixel by pixel |
| U-82 | Accrue `haltedCycles` | emux 0x0201 reads non-zero in MM; no other output changes |
| U-RES | Read the NEC datasheet's different-device read turnaround | a cited value for u32r-banked, or a statement that none exists |
| U-REFRESH | Trace the per-access refresh cost in the model (the 74.67 vs 52/54 rclk holdoff) | the holdoff is explained with code, or filed as a defect with a reproduction |
| U-THAR0-ZC | Assign thar0:zcmp and ac-zbsame-vioff-imrd-1cyc to a mechanism | a measured attribution, or "unexplained" in their check source |
| U-SCT | Look for a coarse South Clock Town cadence check in existing hardware captures | an asserted check with a cited source, or a written "none found" |

Run U-86 after U-84 and U-87, so its MM change can be attributed to it.

### P2. Model fixes backed by references (no hardware)

| Unit | Scope | Selection data | Independent check | Acceptance | Risk |
|---|---|---|---|---|---|
| U-DRAIN | Set `sysad.register-write` to 100 Clock units, basis fit, fit-from the five systembench rows; rewrite the busy-row notes (each check pins its busy only to a 15-17 rclk window); rerun `joybus-fit.py` (its offset moves from 36 to about 46) | pi-io-w, si-io-w, si-dma-w-rom, si-dma-w-ram, pi-dma-128 | pidma:logs; then #16 `register-write`, `wb-drain-target` | the five rows pass on all 33 era runs; pidma exact replay at least 23950 / 24000 with the ROM's self-check at most 1 failure (pisi.md acceptance); nemu64 unchanged; det and stepcap pass | MM output changes; mi-memset-repeat moves 1.31 to 2.18 (still failing); sp-dma-sweep's mean drops to 6.23; mi-memset-rspdma moves 6.498 to 6.494, and at layout pads 4-6, where master already reads 6.491, it likely drops below 6.49 (inferred) |
| U-ROWEND | Find a mechanism with a reference for the row-end replay points (masked first burst, or no write for a 0-byte first block) | none | the pidma row-end points | 0x7f8..0x7fe within ±3% at every size, no other point moves; if no reference exists, record the behavior as not built and leave the points failing (standing order 7) | a one-point fit is not allowed |
| U-RDP-DRAIN | A span starts only after earlier write-backs land; 1PRIMITIVE dead cycles count after the last write lands | Thar0 write-only configs | the cen64 DUTY-minus-RECTN slope, 334.47 rclk per line | the slope within a tolerance derived from the probe's spread (rdp.md); atomic sweep 30-40; snapper 2592 / 2592; nozb-visame-noimrd-1cyc moves toward band; no named Thar0 check goes green | R1 below |
| U-RDP-KIT | Add 2-cycle Z_CMP and IM_RD width points to kit-zmem (all current points are 1-cycle) | none | none (kit only) | the new points run on the fork | none |

**Risk R1: U-RDP-DRAIN breaks an acceptance row.** With the rule applied, filesel-empty reads 1.148 against its 1.05 limit (measured on master before U-DRAIN). That row passes today. The rule improves the cen64 slope and one Thar0 residual, but merging it alone trades a passing MM acceptance row for no green check. So U-RDP-DRAIN lands only under decision D5. Its R1 baseline must be re-measured after U-DRAIN and U-MM-PHASE, because both move MM.

### P3. Structural RDP change (no hardware, high risk)

| Unit | Scope | Acceptance | Risk |
|---|---|---|---|
| U-SPANRAM | Model span RAM as two literal 64 B halves per image (cited span-ram.md) and stream reads through them; replace `rdp.span-slots` with the cited size | thar0:zbrw-fail-zbsame-visame-imrd-2cyc moves toward band; rdpstat:1prim 8 px stays stale; the snapshot no longer covers a whole span; snapper 2592 / 2592; Thar0 per-family residuals reported before and after | Two to four days. It touches every RDP memory path, so snapper, rdpstat, Thar0 and MM must all be rerun |

U-SPANRAM does not depend on U-RDP-DRAIN. It is developed on master. If D5 lands U-RDP-DRAIN first, U-SPANRAM rebases its measurements on that.

### P4. Kit and ROM additions

| Unit | Scope |
|---|---|
| U-HIST | Add a D-fill histogram (D_HIST, for q34) and a per-load latency histogram (for q24) to the kit output, so the console records distributions, not means |
| U-FIT3 | Add three kit points that test cpu.count-write-hold, cpu.fetch-ahead-slots and cpu.ctc1-fpe-ce independently of their fit data |
| U-SPDMA | Time SP DMA of 8-128 B from the RSP's own clock |
| U-ROMS | ROMs for bench:ifill-isolated, bench:wb-fifth-store and bench:rdp-loadsz-sweep |
| U-DOM2 | Derive a domain-2 PI read from the BSD registers; it must reproduce domain 1's measured 144 rclk with the same formula, or stop (standing order 7) |
| U-MMR | An `ext_mm_bench` reader for the BENCH ROM. It builds from a pinned commit of the `bench/fork` branch, so it does not wait for D3 |
| U-VIDEO | A video-capture question for vi.unfetched-sample and vi.fetch-overrun, or reclassify them (decision D2) |

### P5. The console run (#16, Scott)

The console run needs only P0's U-INGEST, U-RULES and U-PIDMA-EXACT, and P4's kit units. It does not wait for P2 or P3: a console capture does not depend on the model, so ingestion compares it against whatever master is current, and every later model change is re-scored against the same capture.

Prerequisites (pending.md section 2):
- an NTSC NUS-001 with Expansion Pak, and an EverDrive-64 X7 or SummerCart64;
- four controllers, for the second kit-dma run only;
- the reset run and the boot-delay builds that `hardware-run.md` lists;
- libdragon builds of Thar0 and snapper64, which Scott makes;
- USB logging or SRAM saves, because the noise logs are too long to photograph.

Run order, because the bus questions decide later fixes (bus.md):
1. q77 and q12: first VI line after enable, and the idle VI. These decide #77 and mi-memset-rspdma.
2. q24 and q44: VI-vs-CPU contention, with the per-load histogram.
3. q20: memset with the VI on and off. This decides the memset table's video state.
4. q18 and q35: banked reads.
5. Everything else in kit order, including the era systembench binary `fd5ec6c0`, which gives a same-binary comparison for every systembench row, PI DMA 8 included.

### P6. After the console run

Each console result that disagrees with the model becomes a fix unit with the console value as its reference. Expected units, depending on the results:

- the VI cost to CPU traffic (q24, q44), then the memset write periods with the VI state settled (q20);
- refresh while the VI is blank, with the D-fill tail (q34);
- the RDP stream ordering in `Port::eligible` (F2), from the IM_RD and 2-cycle points;
- the file-select rows, re-measured after each of these.

## 5. Order and dependencies

```
P0: U-DEAD, U-LBL, U-INGEST, U-RULES, U-PIDMA-EXACT, U-LAYOUT, U-NEMU-PHASE, U-MM-PHASE, U-WALL
P1: U-84, U-87, then U-86; U-82; U-RES; U-REFRESH; U-THAR0-ZC; U-SCT
P2: U-DRAIN (after U-PIDMA-EXACT and U-LAYOUT); U-ROWEND (after U-DRAIN);
    U-RDP-DRAIN (after U-DRAIN and U-MM-PHASE, and only under D5); U-RDP-KIT
P3: U-SPANRAM (after P1; independent of U-RDP-DRAIN)
P4: U-HIST, U-FIT3, U-SPDMA, U-ROMS, U-DOM2, U-MMR; U-VIDEO after D2
P5: console run (needs U-INGEST, U-RULES, U-PIDMA-EXACT and P4; not P2 or P3)
P6: fix units from console results; U-WALL again
```

Within P0, U-LAYOUT and U-MM-PHASE both edit phase rules, so they must not run in parallel. U-DRAIN, U-86, U-RDP-DRAIN and U-SPANRAM each change MM output, so they land one at a time, each followed by a full standing run.

## 6. Predicted counts

These are guesses, each based on the measured experiments in the appendices. "Failing or weak" counts fail, consistent-only and pass-conditional checks.

| After | Failing or weak | What changes |
|---|---|---|
| master | 28 | |
| P0 | 24 | sp-dma-sweep, pi-dma-sizes and pi-dma-sizes-8 leave as report-only (-3); the duplicate Thar0 check folds into its twin (-1); rdpstat:1prim passes on its 8 px cases once the 32 px cases are report-only (-1); mi-memset-repeat joins as a failing check (+1) |
| P1 | 24 | the bug fixes change no current check |
| P2 | 20 | pi-io-w, si-io-w, si-dma-w-rom and pi-dma-128 pass as fit data; pidma:logs is likely still failing under its fixed rule (inferred); mi-memset-rspdma may drop from pass-conditional to fail at some layout pads |
| P3 | unknown | U-SPANRAM is expected to move one F3 check toward band; no basis yet for a count |
| P5 and P6 | depends on the console | every remaining item has its deciding measurement |

SOFTWARE_COMPLETE is reachable at the end of P4. SOFTWARE_READY is not, because about 20 checks only the console decides are still failing: memset, banked reads, the nemu64 tails, the Thar0 F2, F4 and F5 checks, PI DMA 8 and file select.

## 7. Decisions for Scott

Each decision has a default the program uses if Scott does not rule.

| Id | Question | Default |
|---|---|---|
| D1 | Are the 9 out-of-kit rows (cartridge chips, PIF boot timeout) in MAP_GREEN's scope? | They stay open and block MAP_GREEN |
| D2 | Build a video capture for vi.unfetched-sample and vi.fetch-overrun, or reclassify them? | Reclassify as out-of-kit; MM never reaches either path (cited, row note) |
| D3 | Merge wScottSh/mm-decomp-60fps#1 | Left open for Scott; MAP_GREEN needs it, U-MMR does not |
| D4 | Contact the author of the n64brew memset table (user Phire) to ask its video state? | No contact; q20 decides it |
| D5 | Land U-RDP-DRAIN if it improves the cen64 slope and one Thar0 residual but fails filesel-empty? | Do not land until filesel-empty passes under the file-select rule with a referenced mechanism |
| D6 | Approve the reclassifications in section 3 that move failing checks to report-only (sp-dma-sweep, pi-dma-sizes, rdpstat:1prim 32 px)? | Proceed; each is reversible and its reason is stated in the check |

The drain value, the pidma rule and the phase rules are technical choices with measured grounds, so this plan fixes them rather than asking.

## 8. What not to do

- Do not refit pi.io-busy, si.io-busy, si.write64-rom or pi.block-writeback to either systembench build. A 1-3 instruction change in the poll step moves those rows by up to 10 units (measured, verify-83).
- Do not count the five systembench rows as verified after U-DRAIN. They chose the drain value.
- Do not refit the memset write periods again, or retry the row miss at 11 tc. Each passes its own check and breaks others (measured).
- Do not turn on refresh while the VI is blank. It pushes the systembench uncached rows out of band (measured).
- Do not pick a VI-activation behavior to make mi-memset-rspdma pass (#77).
- Do not tune a constant to reach 2.00 fields per frame on file select.
- Do not fit the row-end replay points from one point.
- Do not assert the JOY 2J-4J or read64 reports, the cen64 RECTN and DUTY absolutes, or the 32 px stale-read cases.
- Do not widen a band to absorb a console result. Derive each tolerance from a cited spread first.
- Do not count a fork-against-fork dry run as evidence of anything beyond wiring.
