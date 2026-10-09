# calib-kit-fix report

Status: done. Branch feat/calib-kit, head 17729ddfabea4d33e912e940a7a110844c7a71d9, PR https://github.com/wScottSh/ares/pull/85 (body updated). The merge of origin/master was a no-op: master is still at 253e1c8ea. Issue filed: https://github.com/wScottSh/ares/issues/86 (an RDP hazard tail that rejects pixels keeps the first pass's pixels; found by kit-tex).

Commits on top of 6febf9e7d:
- 40d55169c fixes the hw_out PI base, adds n64-run --dump-sram and kit.py --verify-run.
- 9a2021b08 makes ingest.py and kit.py executable, adds capture normalization and the kit self-test.
- 3a013a617 adds the full-coverage compare, the cmd-fetch burst metric, 4-pad runs, the SP DMA chain and the count-per-field note.
- 17729ddfa adds the coverage rule, 79 questions, kit-tex/zmem/cpu2/bus, the ext readers, the ipl3 pin and the doc.

Four helper agents wrote kit-tex, kit-zmem, kit-cpu2 and kit-bus. Each module is one file I specified. I wired them in, wrote the questions and checked every value on my own run.

Build: /home/wscottsh/n64-timing/build/calib-kit-fix. Private N64_TIMING_HOME: /home/wscottsh/n64-timing/calib-kit-fix-home. Results: /home/wscottsh/n64-timing/results/calib-kit-fix/:
- `after/` and `after2/`: run.sh twice, byte-identical.
- `dry-run.txt`.
- `standing/`.
- `step1/`: the first fixed run.
- `mutant/`: the old hw_out.

Scratch mutant build: build/calib-kit-fix-mut64 (RdpCmdFetchBurst 64).

## verify-85 items

**1. Blocking: hw_out stores went to PI_STATUS/DOM1_LAT/DOM1_PWD. DONE.**
- hw_out reloads the PI base before the three stores. hw_init clears all 32 KiB of SRAM, so no old save follows the log. hw_finish prints `#kit-pi` with the DOM1 registers.
- n64-run `--dump-sram FILE` writes the cartridge SRAM at the stop. kit.py `--verify-run` (run by run.sh) checks two things for every log: the SRAM copy equals the ISViewer copy byte for byte, and `#kit-pi` reads LAT 0x40 / PWD 0x12 / PGS 7 / RLS 3.
  - Measured on the fixed hw_out: 103 of 103 pass.
  - Measured on the old hw_out (mutant): 24 errors over 12 ROMs. Two examples: DOM1 lat 232 / pwd 143, and SRAM differs.
- Kit vs the standalone bench (pif-joy/after, all delays):
  - Fixed: every pi-dma-sizes, pi-io-read, pi-io-write, uncached-sizes, rcp-reg-read, pif-ram-read and si-io-write point has its kit min inside the bench's min range.
  - Old: all 4 pi-dma-sizes points were outside (cart-to-ram-8 kit 241..246 against bench 135..136). Fixed: 135..138.
  - Remaining differences: si-dma read64-1 (28486 vs 28494, an 8 rclk offset on the first frame) and 20 sp-dma-sweep points that are wider by one 26 pclk poll. Both kit and model run the same ROM, so neither affects a comparison.

**2a.1 cmd-fetch-burst metric. DONE.**
- New points: a frozen RDP's FIFO fills from a 512-NOP list while 64 polls record DPC_CURRENT offsets, over 16 phases of the first poll. burst_gcd is the gcd of the offsets below the full FIFO, rule exact. The old fields stay as report values.
- Fork: 0,128,240, so burst_gcd 128.
- Mutant fork with a 64 B burst: 0,64,128,192,240, so 64; compare fails "console [64] model [128]".
- With the spin before the END write (my first version), the mutant also read 128, a false pass. Moving the spin after the END write fixed it.

**2a.2 joybus-pads 4 pads. DONE.**
- kit-dma gains a status frame on 4 channels and a probe of the ports that answered and the accessories (mask, paks).
- run.sh runs kit-dma at every delay with `--controllers 4` into pads-4/. The flag already existed in n64-run; no change was needed.
- Ingestion groups captures by pads. A capture with a pak fails with its fix.
- Measured: read64-4 is 73461 rclk with 1 pad and 80143 with 4. A 4-pad log fails against the 1-pad model (5 of 17 values differ) and passes against pads-4.
- joybus-pads now also closes pif.joybus-skip, pif.joybus-handshake and item fu.joybus-56-63.

**2a.3 pi-dma-small / cpu-reads / poll-phase invalid. DONE** (see item 1).

**2a.4 vi-first-line first_ticks ±24 is wide. NOT DONE.** The rule and metric are unchanged. I did not investigate whether a tighter tolerance holds over the console's phase. The question still closes bench:mi-memset-rspdma only as a link.

**2a.5 sp-dma-direction 26 pclk quantum. DONE for 256-4096 B; small sizes NOT decided.**
- New sp-dma-chain: max(16, 4096/size) DMAs queued through SP_DMA_FULL, timed to busy clear.
- 256 B and up are DMA-bound: rd 4096 B is 645 ticks each, wr 451. The question uses those sizes, rule rel:1.
- 8-128 B chains run at the CPU's register-write rate (24.6 ticks each). A phase-walked single DMA ends before the first poll (min 2).
- So no CPU-polled method decides small SP DMAs. An RSP-timed point is the way; not built.

**2a.6 one boot delay on the console, no repeat guidance. DONE (doc).**
- Required: two power-cycled runs of every ROM.
- Recommended: the 7 other boot-delay builds of kit-cpu, kit-dma and kit-vi.
- Ingestion takes the range over all captures.
- Each log header now names its build (boot-K or single). The field is padded, so all 8 builds keep one layout (payload 15392 B each, measured).

**2a.7 count-per-field 783,516 vs ~782,031. DONE (investigated).**
- The kit's VI uses V_SYNC 0x20D progressive, which is 263 lines; vi.cpp ends the field at halfline 526.
- 263 x 3094 VCLK x 46.875/48.681812 = 783,520.9 ticks, and the fork reads 783,516-783,530.
- verify-85's 782,031 is 262.5 lines (interlaced). Recorded in the question.

**2a.8 a one-record log passes. DONE.** compare() fails a capture that lacks any value the model has. The kit self-test has 3 compare cases.

**2b Behavior rows without a question. DONE.** Every row is now closed by a question or listed as not hardware-decidable; behaviors.py --check enforces it.
- The 9 cpu fit rows are covered by nemu64-cycle and nemu64-cop0hazard (now in KIT_ROMS) and by kit-cpu2:
  - fpu-classes: unsampled FPU classes.
  - cpu-exceptions: isolated ERET, AdES/TLBS/Mod/fetch AdE/watch/IRQ/CTC1 FPE.
- Three fit-only rows are closed only by a console re-run of their own fit data: cpu.count-write-hold, cpu.fetch-ahead-slots, cpu.ctc1-fpe-ce. Per pref 21, they do not name the hw check, so their status stays "fit only" after a capture.
- Other closed rows:
  - pif.joybus-skip and pif.joybus-handshake: joybus-pads.
  - rdp.mem-overhead-write, rdp.port-lookahead and ri.overhead-rdp: thar0-console, which now has a reader.
  - Model-choice rows: ri.refresh-waits-for-burst (vi-cpu-contention, refresh-all-banks), vi.display-window (vi-fetch-modes), rdp.xbus-fetch-rate (kit-zmem), ri.rank.other (ri-priority).
  - Inferred rows: cpu.ldi (load-interlock-cop), cpu.issue and cpu.exc-fpu (cpu-exceptions), rdp.setter (rdp-sync-setter), rdp.attribute-stage (attribute-stage).
  - ai.fetch-bytes and legacy.ai.power-on-rate: ai-fetch and ai-rate.
  - legacy.pi.cart-read: dom2-read.
  - ri.retry-clean, ri.bank-of, ri.row-of: nemu64-console.
- The 10 thar0 failing checks are now closed by thar0-console.
- not-hardware-decidable (calibration/undecidable.tsv, 16 entries, each with its reason):
  - scheduler.tie-rank and ri.request-latency.
  - legacy.clock.vclk-pal (PAL, outside the target).
  - legacy.cpu.sysad-frozen-step and legacy.pif.step-quantum (emulator quanta).
  - legacy.pif.boot-timeout.
  - The 8 legacy.cart.* rows: a flashcart emulates the chip, and a kit ROM cannot run from a retail cart.
  - legacy.cpu.nmi-entry: a Reset press has no timestamp.
  - item fu.pif-ram-dword. Measured: an LD from PIF RAM froze the fork's CPU (Bus::freezeDualRead), so the point was removed as console-unsafe.
- vi.unfetched-sample and vi.fetch-overrun get a `none:` question: it needs a video capture.

**2b #16 sub-items and follow-ups. DONE** (calibration/items.tsv, 48 items, all closed). Each sub-item is in the inventory's Coverage table with its question, including:
- PIPEBUSY stall (pipebusy-stall, rdp-rect-base).
- Triangle setup: fill, Z, shade and shade-Z built. Textured types are not built: they need TMEM setup and an unchecked encoder.
- LoadTile vs LoadBlock.
- Refresh in all 8 banks.
- Write-buffer drain per target, PI included.
- VI interrupt latency and the VI/RCP phase. The phase point runs after hw_init, the header and vi_init, so it is not the first change after power-on.
- Noise: stall (new IM_RD case), reset (new reset-capture question), bits, 2-cycle. The G_AD_NOISE range is covered by one threshold only.
- #17: comb, copy pass/fail, clobber. #19: atomic contention. #20: slot overlap.
- MM scenes: ext mm-bench.
- Follow-ups: RDP hold, exception entries, isolated ERET, RI HSYNC refresh (vi-cpu-contention), PiEdgeWait (pi-dma-small), PI first block at a row end (new pi-dma-rowend), pidma offset, systembench same binary, power-on COMPARE (cop0hazard), hpos holdoff.
- #84: vi-mid-field-blank, `none:` blocked by #84.

**2c The 8 none: questions. DONE.** All 8 have kit points:
- write-granularity, triangle-setup and xbus in kit-zmem.
- ri-priority, ri-reorder and vi-fetch-modes in kit-bus.
- tmem-load-rate and fill-copy-rate in kit-tex.
- cpu-exceptions and cache-ops in kit-cpu2.

**2c The 5 ext: questions. PARTIAL.**
- Stored by ingest.py as `ext-<rom>` captures. Thar0 is also detected by its BUF/PIPE blocks.
- With a reader:
  - thar0-console: against the fork's run of the port, which run.sh now makes. Each config's pruned average BUFBUSY and PIPEBUSY must be within 1%, and the detail counts how many are within 1% of Thar0's console.
  - snapper64: byte-for-byte against the published dumps.
- No reader:
  - systembench: PR #83 is not landed. The doc says to run report.py from that branch by hand and to record rambuf from the ELF.
  - pi_dma_test: cannot log COUNT without its source, which has no license.
  - mm-bench: compared by hand against tools/n64-timing/mmbench.
- Their hw rows stay pending, with a detail saying so.

**2c Structural: --check forces only calibration-16 rows. DONE.** The coverage rule is described under 2b. Three self-test cases fire it: a model-choice row with neither a question nor a reason, an undecidable entry without its reason, and an item no question closes. Rows a kit question closes now name its hw check, 91 rows, added by a script. The only status changes were 7 pending rows gaining the calibration gate; no pass or fail row moved.

**§3 Kit tests.** dcb, fifo-depth and color-half are unchanged. cmd-fetch-burst: see 2a.1. vi-first-line: see 2a.4.

**§4 Console safety.**
- The emux scan was not rerun on the new ROMs. hwout.transform still raises if any emux mnemonic survives, and every new ROM built through it.
- The SC64 ISViewer presence magic at 0x13FF0000 is NOT DONE. The listener path does not need it (inferred; not verifiable without hardware).
- Every poll in the new modules is bounded, per the helpers. Exception: the shared k_rdp MI_INTR wait used by kit-tex has no timeout, as for every existing kit-rdp point.
- kit-cpu2's COP2 points set CU2 only for themselves. That this is safe on hardware is not verified (the helper relies on memory of n64-systemtest).

**§5 Ingestion.**
- ingest.py and kit.py are executable.
- kit.normalize undoes byte-swapped SRAM, UTF-16 LE/BE, a BOM, CRLF and CR, and ANSI color codes. A leading banner is accepted.
- kit.py --self-test has 14 cases. The old reader fails 5 of them. The self-test joins the gen check.

**§6 --check rules.** The rules verify-85 tested are unchanged and still fire (self-test 56/56).

**§8 Procedure doc.** hardware-run.md is rewritten:
- ipl3_compat: pinned, how to get it, and build.py refuses another stub for a console build.
- SC64: `upload --save-type sram`, `debug --isv 0x03FF0000` and `download save`, with "confirm the option names with --help" because they are not verified. A menu-path note.
- ED64: the SRAM path now works.
- Power cycles before every ROM: Reset is a warm boot. The doc names the boot-state ROMs.
- Repeats and the boot-delay builds.
- Pak removal, the 4-pad run and the reset run.
- Photo fallback: only for logs of 2 KB or less, marked in a table generated by `kit.py --table`. 18 ROMs, with their run times and sizes.
- External ROMs and their locations.
- CRLF handling.

## Standing (head build, private N64_TIMING_HOME)

- MM `--frames 600 --stats` md5 is 9629185039701bddcdbd90c248a4f38b, and the same with `--dump-sram` (MM has no SRAM: "no SRAM written").
- nemu64 values.tsv for timing (1605 lines), cycle (14) and cop0hazard (6) is byte-identical to pif-joy/after. ROM sha256: bd946fb1, ae9c83aa, 9518d316.
- MM wall time was not compared: one run took 27.5 s, not interleaved. The core change is verify strings only, and --dump-sram acts after the stop.
- `--check` ok, `--self-test` 56/56, kit self-test 14/14, romgen self-test 72/72, lint ok.
- run.sh twice: `diff -r` of all logs, SRAM dumps and ROMs is empty.
- dry-run: 74 of 79 hw checks go pending to pass, and 26 behaviors flip. The remaining 5 are systembench, pidma-offset and mm-filesel (no reader) and vi-mid-field-blank and vi-unfetched-video (none).

## Deviations

- `--controllers` existed already, so only `--dump-sram` was added to n64-run.
- The helpers' measured fork findings, recorded in the questions:
  - The fork's fill rate is 6.7 B/clk and its copy rate 2.2, against the SDK's 8.
  - TMEM loads take 0.703 clk/B + 7.
  - The fork never raises Watch.
  - A cartridge read does not wait for a pending PI write.
- The derived metrics are in a new calibration/derived.py, called by kit.derive.

## Follow-ups

- #86, the hazard tail defect.
- The fork never raises the Watch exception.
- An RSP-timed SP DMA point for 8-128 B.
- Textured triangles in zmem-tri.
- vi-first-line tolerance (2a.4).
- Readers for systembench (after PR #83 lands) and mm-bench.
- Why the thar0 --hw build hangs, still not found.
- After a capture, three fit-only rows stay fit only by design (2b).

No background processes of mine are left: ps checked, and the helper agents finished.
