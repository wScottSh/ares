# verify-85: PR #85 calib-kit (head 6febf9e7d8ba95cef9daa4227c42a8b71d48a20e, base 253e1c8ea)

## Verdict: FAIL (one blocking defect in the console output layer, plus comprehensiveness gaps against pref 28c)

The tooling around the kit is sound and reproduces. The console build has a bug that (a) never writes SRAM, (b) overwrites PI domain-1 timing registers on every output line. The ED64 X7 path therefore captures nothing, and every PI-timed point (pi-dma-small, cpu-reads/pi-io) is measured under garbage timing. Fix is small (below). Separately the kit does not cover everything hardware could decide: 8 questions have no ROM, 5 are manual-only, and about 20 behavior rows plus several #16 sub-items have no question.

## 1. Blocking defect: hw_out stores go to the wrong PI registers

tools/n64-timing/romgen/hwout.py, hw_out (about lines 239-247). `pi_wait("$a0", ...)` loads `$a0 = 0xA4600010` (PI_STATUS). The following `sw $t3,0($a0)`, `sw $t3,4($a0)`, `sw $t7,8($a0)` were meant for DRAM_ADDR, CART_ADDR, RD_LEN (base 0xA4600000). Disassembly of boot-1/kit-span.z64 at 0x37b8-0x37f4 (measured):
- sw 0($a0) = 0xA4600010 PI_STATUS (write of the RDRAM address; bit0/1 are 0 here, so a no-op)
- sw 4($a0) = 0xA4600014 PI_BSD_DOM1_LAT <- (0x08000000 + off) low byte
- sw 8($a0) = 0xA4600018 PI_BSD_DOM1_PWD <- len-1
- no store to RD_LEN, so no DMA is ever started: SRAM is never written (inferred from the disassembly; the fork runner cannot dump SRAM so the SRAM path was never exercised end to end, and dry-run.sh builds its .srm from the .txt log).

Effect measured on the fork (the fork's PI DMA time reads bsd.latency/pulseWidth, ares/n64/pi/dma.cpp:24,29): I NOPed the three stores in a scratch copy of boot-1/kit-dma.z64 (results/verify-85/kit-dma-nopatch.z64):

| point | shipped kit-dma | stores NOPed | standalone bench (pif-joy/after) |
|---|---|---|---|
| pi-dma-sizes cart-to-ram-8 min rclk | 242 | 135 | 135 |
| pi-dma-sizes cart-to-ram-1024 min rclk | 8084 | 9117 | n/a |

So the kit's PI DMA numbers are not the retail-timing numbers the model is fitted to. On a console the same writes hit the real DOM1 registers (retail LAT 0x40 / PWD 0x12 / RLS 3 from the ROM header word 0x80371240, which cpu.pi-io-read 214 says it was measured at), so pi-dma-small, cpu-reads (pi-io-read) and systembench-style PI points are invalid, and the registers end each run in an arbitrary state. The doc's ED64 X7 path (SRAM only, no ISViewer) yields an all-zero save.
Fix: `li $a0, 0xA4600000` after each pi_wait (or use a separate base register) before the three stores; add a fork test that the DOM1 registers equal the header values after the run (peek cannot read PI regs; a ROM-side readback line in the log can). Re-run kit-dma, rerun dry-run.

## 2. Comprehensiveness (central question)

Method: enumerated every behaviors.tsv row with basis fit / model-choice / inferred or a verify-is-fit note, every pending gate, every failing/weak check in the generated inventory, followups.md (whole file), issues #16, #77, #82, #84, and the closure draft; diffed against questions.tsv closes and kit column (script in this session, output reproduced below).

### 2a. Entries in questions.tsv whose kit test would not decide them
1. `hw:cmd-fetch-burst` (kit-rdp cmd-fetch). Rule `exact` on changes, min_step, max_step, first_step. These are properties of a CPU polling DPC_CURRENT, not of the burst size. The fork reads max_step 288 (rects) and 376 (NOPs) while the model burst is 128 B, and min_step 8. Same on all 8 boot delays, but a console with the same burst and a different RDP rect rate will change `changes` and `first_step`. Result is likely a spurious fail, and a pass would not pin 128 B. Needs a metric the poll cadence cannot move (e.g. DPC_CURRENT quantization with the poll slowed below the burst period, or the step histogram's GCD).
2. `hw:joybus-pads` closes pif.joybus-no-device (4 pads) but the doc tells the user to connect exactly one pad, and run.sh runs the fork with the default 1 controller. A 4-pad capture would be compared against a 1-pad model and fail. Followup is acknowledged in the worker report, but nothing in the procedure, run.sh or ingest handles it. The 2J-4J fit stays undecidable.
3. `hw:pi-dma-small`, `hw:cpu-reads` (pi-io-read), `hw:poll-phase` (pi-io-write): invalid until the section 1 bug is fixed.
4. `hw:vi-first-line`: sound as a V_CURRENT-at-enable test (fork 524 for delays <=1314, 0 from 2000). first_ticks is compared within +-24 against the model range over 8 boot delays, which is wide; the question closes bench:mi-memset-rspdma only as a link.
5. `hw:sp-dma-direction` rule range:rel:1 on a bench whose end is quantized to the 26 pclk status-poll period (followups verify-63c): small DMAs will not resolve. The finer poll or counter-based end was not built.
6. Console runs one boot delay (boot-1) against 8 model delays (K = 1,165,...,1149, period 1313). #77 shows narrow dips (K=1300..1316) that the 8 delays can miss, and the console phase is unknown. Overlap-with-model-range is the right rule per pref 27, but a console value outside the model range can be a phase miss. The doc does not tell the user to repeat each ROM across several power cycles (ingest handles several logs per ROM; it uses min/max over them).
7. `hw:count-per-field`: fork reads 783516..783530 COUNT/field. Back-of-envelope from the kit's H_SYNC 0xC15 (3094 VCLK/line, 525 lines, VCLK 48.681812 MHz, COUNT 46.875 MHz) gives about 782031 (+0.19% on the fork). Not investigated; inferred only. If real, the fork's field length is off by far more than the rule's 0.01%, and the test would fail on any console, which is informative but should be understood first.
8. Partial-coverage hole (measured, scratch capture with a valid footer holding one `dcb nop-nop` record): hw:dcb passes on 1 compared value. Realistically only reachable by a hand-edited log, because the footer is written last, but compare() does not require every model point to appear in the console log.

### 2b. Hardware-decidable items with no entry in questions.tsv
Behavior rows (basis fit / model-choice / inferred / verify-is-fit), none named by any question's closes:
- fit-only, 7 rows: cpu.exc-fpu-detect, cpu.fpu-trivial, cpu.eret, cpu.count-write-hold, cpu.irq-sample, cpu.fetch-ahead-slots, cpu.ctc1-fpe-ce. Plus fit rows cpu.random-rule, cpu.wired-write-latency. Cheapest close: nemu64-timing is already a kit ROM; add the nemu64:timing/cop1instructions32/64, exception-roundtrip, random checks to nemu64-console's closes. But the checks for count-write-hold, irq-sample, random-read-early (nemu64-cop0hazard) and fetch-ahead-slots, ctc1 (nemu64-cycle) need nemu64-cop0hazard.z64 and nemu64-cycle.z64 added to KIT_ROMS (16 KB each, 5 and 13 values, built by the same --hw path). Not in the kit at all today.
- pif.joybus-skip, pif.joybus-handshake (fit): si-dma points are in kit-dma; not in joybus-pads closes.
- rdp.mem-overhead-write, rdp.port-lookahead (fit), ri.overhead-rdp (derived, copies a superseded fit): only reachable via thar0-console, which is ext-only (no ingest).
- model-choice: ri.refresh-waits-for-burst, ri.request-latency, vi.unfetched-sample, vi.display-window, rdp.xbus-fetch-rate (XBUS vs DMEM command source rate; hardware-decidable by DPC_CLOCK of an XBUS list), ri.rank.other (ri-priority has no ROM). scheduler.tie-rank is internal, not hardware-decidable.
- inferred/unreferenced rows in notes: cpu.ldi (COP2 rt-only check; LWC1/LDC1 FPR result reaching an FPU reader), cpu.issue (extra pclk before a fetch-fault exception), rdp.setter, rdp.attribute-stage (texture, blender, z_mode, dither stage rows built only from the n64brew table; T15 says they need console captures), cpu.exc-fpu (CTC1-raised FPE cost).
- legacy.* pending:no-corpus rows that a console could decide: legacy.cpu.sysad-frozen-step, legacy.pi.cart-read (250), legacy.ai.power-on-rate (44100; followup: DACRATE truncation 1103 vs 1104), legacy.pif.boot-timeout, legacy.cart.eeprom-write / rtc-tick / flash-mx-* / flash-mn63-* (need cartridges with those peripherals), legacy.clock.vclk-pal (PAL console, outside the NUS-001 NTSC target; say so).
- ai.fetch-bytes (report-only): no AI question at all (DAC rate, DMA length/next-address behavior, fetch granularity).

Issue #16 sub-items not in any question:
- DPC_PIPEBUSY includes memory stall? (CLOCK-PIPE as stall counter): bufbusy/pipebusy are logged by span-width/rectn but no question or metric compares them.
- Triangle setup per type (many 1-px triangles); LoadTile vs LoadBlock per-row overhead via DPC_TMEM (tmem-load-rate, kit none, covers the rate only).
- Whether the 52/54-clock refresh holdoff blocks all banks (hpos reports holdoff_rclk_max but only for the VI's bank and one other).
- Write-buffer drain per target (RDRAM / RCP reg / PI) and load wait behind N=0..4 buffered writes per target: wb-release covers RDRAM only; PI target absent.
- VI vs RCP clock-domain phase/jitter at power-on and VI interrupt sync latency (#24).
- Noise (#18): what loads the all-ones LFSR state (cold boot / reset), G_AD_NOISE range, noise stepping during in-span stalls (noise phase vs DPC_CLOCK/BUFBUSY).
- #17: copy-mode pass/fail/pass/fail word cost, the IM_RD-on atomic-off clobber test (stale-block vs masked write-back), whether runs are cut at 16 B / 64 B boundaries (write-granularity is only the Z-comb run-count sweep, and has no ROM).
- #19: growth of the atomic cost with Z/RDRAM contention (rdp-atomic uses plain rectangles).
- #20: whether IM_RD/Z_CMP prefetch share the same stream slots.
- #16 "MM bench scenes": only mm-filesel is listed; mm-bench scenes behind mm:south-clock-town (report-only for vi.register-sample, vi.unfetched-sample, vi.display-window, clock.vclk, ai.fetch-bytes) have no console question.
- followups: RDP hold (command appended after the rectangle is in flight), fetch-stage / bus-error / watch exceptions and interrupt entry cost (cpu-exceptions lists only store AdE, TLB, interrupt, NMI, CTC1 FPE), isolated ERET, RI HSYNC refresh rule, PiEdgeWait 0.5 rclk and the PI row-hit assumption (code-only constants with no behaviors row), PI first block ending at an RDRAM row end.
- #84: what real hardware does on a blank/re-enable mid-field is untested because k_vi_enable blanks only in vertical blank (workaround, legitimate; list it as an open hardware question).
Failing thar0 checks not closed by any question: thar0:zcmp, ac-zbsame-vioff-imrd-1cyc, ac-zcmp-zbsep-vioff-imrd-1cyc, nozb-vioff-imrd-1cyc, nozb-visame-noimrd-1cyc, nozb-visep-imrd-1cyc, separate-bank, zbrw-pass-zbsep-visep-noimrd-1cyc (thar0-console closes only two of 10).

### 2c. Questions without a kit ROM or ingest (pref 28c(c) "drops straight into the spec")
- 8 none: (write-granularity, ri-priority, ri-reorder, tmem-load-rate, fill-copy-rate, vi-fetch-modes, cpu-exceptions, cache-ops). They have a procedure sentence but no ROM, so there is no "ready-to-run hardware procedure". hardware-run.md defers them to "a follow-up unit".
- 5 ext: (thar0-console, systembench, pidma-offset, mm-filesel, snapper64): compared by hand, no ingest, so their hw: rows stay pending:calibration-16 forever and the rows they close (rdp.span-read-latency, mem-overhead-*, pi.* checks) cannot flip. thar0-console is the biggest residual (+8%, -5%); its romgen port hangs on the fork (root cause not found), the original ROM is the fallback.
- structural: --check forces only rows that say pending:calibration-16 to name a hw: check. It does not force every fit-only / model-choice / failing row to have a question (7 fit-only rows show "no kit question" in the generated inventory and --check still passes). Nothing keeps the inventory comprehensive as rows are added.

## 3. Five kit tests end to end
Ran all 12 console builds on the fork (calibration/run.sh, 20.0 s at load 3-5; ROM sha256s and every log identical to the worker's, so the build is reproducible across worktrees).
1. dcb (kit-cpu): output `#bench dcb sw-lw pairs=16 reps=8 min=24 max=101` (5 variants), question compares `min` of each variant, range:abs:1. Fork min: sw-lw 24, nop-lw 16, nop-nop 16, sw-sw 32. Decides +1 pclk if the console totals differ. OK.
2. fifo-depth (kit-rdp): current_minus_start=240 at 64 and 512 NOPs, exact. Decides 240 B vs 64 dwords. OK.
3. color-half-16bpp (kit-span): half_px derived from the DPC_CLOCK jump (w31 648 -> w32 804). exact. derive() is applied identically to console logs. Decides 32 vs 16. OK.
4. vi-first-line (kit-vi): v_at_enable 524/0, first_ticks; abs 24. Decides the V_CURRENT-hold question; see 2a.4.
5. cmd-fetch-burst (kit-rdp): see 2a.1, does not decide.
Rule check: kit.compare uses overlap of the console's [min,max] with the model's [min,max] across the 8 boot delays, plus slack (abs/rel); `exact` requires console values to be a subset of the model's across delays. That is the phase-range rule of pref 27 and not a single point. The console contributes one boot-delay point.

## 4. Console safety
- emux: scanned every word of all 12 console ROMs for COP0-CO words with the emux functs (0x20,0x25,0x27,0x28,0x29,0x2a,0x2c): 5 hits, every one inside ASCII strings (e.g. 0x433d0020 = "C= "), 0 instructions. Control: the non-hw nemu64-cycle and nemu64-timing builds give 8 and 16 hits, so the scan detects emux words; hwout.transform also raises if any emux mnemonic survives in the asm.
- IPL3: libdragon ipl3_compat.z64 (Unlicense text in the clone, sha256 f522db2e...a068, libdragon commit e356bf3f), signed for CIC 6102. Retail NUS-001 runs it; EverDrive and SC64 select CIC 6102 by default (cannot verify here). Public domain, so legal under pref 9; the binary is not committed. Header check: entry 0x80000400, size word 0x10 = payload length (0x8000), as the libdragon README says ipl3_compat reads. ROMs need the Expansion Pak (stack 0x80480000, log buffer 0xA0488000); documented.
- Save type: header bytes 0x3C-0x3F = 45 44 00 30 ("ED", SRAM 256 Kbit per the n64brew advanced-homebrew header). Format correct as written; whether ED64 and the SC64 menu honor it and where saves land cannot be verified without hardware. The SRAM write itself is broken (section 1).
- Cannot verify without hardware: the ISViewer path on SC64 (libdragon writes a magic to 0x13FF0000 for presence detection; this ROM does not), `sc64deployer debug --isv` option name, ED64 write-back on Reset, DOM2 SRAM timings, console behavior of the PI writes.
- The joybus bench frames use control byte 1 and command 0xFF/0x01/0x04 or 0x03 (read/status): benign. write64-rom DMAs to PIF ROM address (ignored by hardware per systembench).

## 5. Ingestion
- dry-run.sh on my own run: 32 hw checks pending -> pass, 15 behaviors flip, 63 lines; identical to the worker's output (diff empty except the scratch path line). Cut log stored INCOMPLETE and not compared, byte-swapped .srm parses (it is synthesized from the .txt, so it does not test the real SRAM path).
- Tamper cases (scratch captures, --dry-run): value edited with old footer -> `INCOMPLETE ... not compared`, 0 checks changed. Value edited with recomputed footer -> hw:dcb fail, cpu.dcb pending -> fail. Partial log with a valid footer (1 record) -> other questions fail "capture lacks the points", but hw:dcb passes on 1 value (2a.8).
- New finding: a capture with CRLF line endings (Windows tee / PowerShell redirect / text-mode copy) is flagged INCOMPLETE and silently not compared (kit-vi.isviewer.log case). A leading junk line before `#kit rom=` is accepted. Normalize \r\n in kit.read_logs or say so in the doc.
- tools/n64-timing/calibration/ingest.py is mode 100644: the doc's `tools/n64-timing/calibration/ingest.py capture/ ...` fails with Permission denied (measured). Run via `python3` or chmod +x.
- Spec regeneration: `behaviors.py --check` ok at head; `--self-test` 53 cases, 0 failed.

## 6. --check rules (mutations in a scratch copy of ares/n64, tools/n64-timing, docs/spec, docs/calibration)
- bare `pending:calibration-16` on cpu.dcb -> `waits on pending:calibration-16 with no kit test. Name the hw:<question>`; fails.
- cpu.dcb pointing at hw:cache-ops (kit none) -> `names hw:cache-ops, whose kit is none ... not an in-repo kit ROM` and `closes column does not list it`; fails.
- closes entry renamed to a non-row -> `closes cpu.dcbX, which is no behavior row, check or #issue`; fails.
- kit-noise removed from KIT_ROMS, and an appended line in inventory.md -> fail (generated-file drift).
All rules fire. Limit: they only guard rows that already name pending:calibration-16 or hw:; see 2c structural.

## 7. Standing checks (head vs base 253e1c8ea, my own builds, private N64_TIMING_HOME)
- MM `--frames 600 --stats` md5: 9629185039701bddcdbd90c248a4f38b on both (matches standing).
- nemu64 values.tsv identical base vs head for timing (1605 lines), cycle (14), cop0hazard (6). ROM sha256 prefixes bd946fb1 (timing), ae9c83aa (cycle), 9518d316 (cop0hazard).
- Standing was not timed (only verify strings in behaviors.hpp changed; diff of behaviors.hpp has only verify-string changes).

## 8. hardware-run.md: could a person follow it
Mostly yes for SC64 USB, with these gaps:
1. ingest.py not executable (section 5).
2. libdragon ipl3_compat: "the path romgen/README.md names" is a path under a private scratch dir, with no instruction to obtain or pin the file (git clone DragonMinded/libdragon at e356bf3f, boot/bin/ipl3_compat.z64, sha256 above).
3. SC64: no command to load the ROM and set CIC/save type from the PC (`sc64deployer upload` path); it relies on the menu and says the ISV listener must be started first, with no evidence the menu path enables IS-Viewer.
4. ED64 X7: no ISViewer, SRAM only, and the SRAM write is broken (section 1); only the photo fallback would work today.
5. One run per ROM only; no repeat guidance (2a.6).
6. Reset-chaining ROMs: the doc says press Reset after each ROM. Resets give a warm boot (COUNT, RDRAM refresh, VI and RI state are not at power-on), while the model's boot and #77's question are about a fixed power-on time. The header logs RI/MI registers but not cold vs warm; the doc should say to power-cycle for kit-vi, kit-dma, kit-hpos or label the boot type.
7. Joybus: states one pad and nothing about removing a Controller Pak / Rumble Pak (the accessory point reads port 1), and the 4-pad setup has no kit step.
8. Photo fallback for a 26 KB kit-noise or 25 KB nemu64-timing log is impractical; say which ROMs need USB.
9. External-ROM section depends on PR #83 (draft, unmerged) and on a Thar0 ROM and README with no location.
10. CRLF (section 5).

## Recommendation
Do not land as is. Required before landing: fix the PI base register in hw_out and re-run (small), make ingest.py executable, normalize CRLF. Then either land with the missing-question list filed as a follow-up unit (my preference given the stack), or extend questions.tsv first: add nemu64-cycle and nemu64-cop0hazard to KIT_ROMS and close the seven fit-only rows through them (cheapest, biggest comprehensiveness gain), fix cmd-fetch-burst's metric, handle the 4-pad case, add a repeat/power-cycle instruction. The 8 `none:` ROMs, the AI and attribute-stage questions, and an `--check` rule that every fit-only/model-choice/failing row has a question or an explicit "not hardware-decidable: reason" are the remaining work for pref 28c.

## Reproduction
Worktrees /home/wscottsh/repos/ares-wt/verify-85 (head), verify-85-base; builds /home/wscottsh/n64-timing/build/verify-85{,-base}; results /home/wscottsh/n64-timing/results/verify-85 (calib/, dry-run.txt, kit-dma-nopatch.z64, kit-dma-patched.txt, nemu64-head/, mm600-{head,base}.tsv). No background processes left (ps checked).
Not reproduced / not verifiable: all hardware behavior; the SRAM write (fork cannot dump SRAM; claim rests on disassembly); worker's "61 fork runs in 16.9 s" (mine: 20.0 s, same count).
