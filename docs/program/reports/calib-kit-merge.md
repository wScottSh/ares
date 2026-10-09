# calib-kit-merge report

Status: done. Branch feat/calib-kit, head aba69902e, PR https://github.com/wScottSh/ares/pull/85 (body updated). The worktree was clean at 17729ddfa at the start.

Build: /home/wscottsh/n64-timing/build/calib-kit-merge. Private home: /home/wscottsh/n64-timing/calib-kit-merge-home. It holds its own copies of the clones: the ipl3 stub, repeater64, and n64-systembench and libdragon under scratch/sb-clones. The pidma clone is the global one, used read-only. Results: /home/wscottsh/n64-timing/results/calib-kit-merge/, which holds calib1 (845635c model), calib2 (era model), dry-run.txt, dry-run2.txt and standing/.

## Commits
- 8e9cffa9b merges master #83. The 6 conflicts were resolved, and behaviors.tsv was merged row by row with a 3-way script (verify column = the union, the other columns from the side that changed). RUNNERS includes systembench and hw. The gen check needs the systembench report and kit.py self-tests. standing.sh runs both suites and calibration/run.sh. The systembench question also closes the systembench checks that are failing or consistent-only.
- f0963f632 holds items 2-6 (below).
- 214c46421 merges master #88 (coordinator mid-task). behaviors.tsv was merged the same way, and only the verify column differs from master (diff checked). ext:systembench now points at the era build: fd5ec6c0, 50f5066, GCC 12.2.0, tie fix, rambuf 0x800278c0.
- aba69902e has the results from the standing run on the merged head.

## Items
1. Merge: DONE. Generated files were only regenerated with behaviors.py, never hand-edited.
2. systembench reader: DONE.
   - kit.py ext_systembench compares the console ISViewer text with the fork run of the same file. calibration/run.sh writes that run to ext/systembench.txt from $SYSBENCH_ROMS, default $N64_TIMING_HOME/roms/systembench (the standing.sh era build).
   - Rule: main.c's rule for every one of the 34 rows.tsv rows, with the fork value as expected. The detail also counts the rows within the rule of the published value. The question text, the docstring and hardware-run.md all say the comparison is pointwise for that binary only (verify-83).
   - Measured: fork vs fork gives pass, "34/34 agree, 29 match published". PI I/O W +5 gives fail. A cut log gives pending, as cut or hung.
   - pidma-offset: no reader. The ROM prints no COUNT, and its source has no license.
   - mm-filesel: no reader. The fork side needs Scott's BENCH build run on n64-run, and no in-repo tool builds it. Both reasons are in kit.py and the doc.
3. Watch split: DONE. A new question cpu-watch reads cpu2-exc/watch-*, metric min and fired, rule exact. It closes item:fu.exc-entry and #87, and no row names it. cpu-exceptions now has explicit point patterns that exclude watch. Measured with a fork log edited to fired=4: cpu-watch fails, and cpu-exceptions passes with 36 values.
4. Referenced passing rows: DONE.
   - hardware_needs now takes every row.
   - New rule: if a comparable question (a kit ROM, or an ext with a reader) closes a row, the row must name hw:<q>. The exception is a question whose ROM is the source of the row's fit-from (pref 21). This keeps cpu.count-write-hold, fetch-ahead-slots and ctc1-fpe-ce as fit only.
   - The ext:-with-reader questions may now appear in verify columns.
   - A one-shot script linked the 43 unlinked rows. Examples: uncached-vs-hpos rows to vi-cpu-contention, sync rows to rdp-sync-setter, span-1/2cycle to thar0-console, span-ram to snapper64, noise-step to noise-pixel-offset, noise-reset to noise-reset, nemu64 measured rows to nemu64-console, interrupt-entry to the cop0hazard question, cpu.pi-io-read to cpu-reads, ri.max-burst to sp-dma-direction (an inferred link), and pif.joybus-byte to joybus-pads.
   - It also added hw: links for every row a comparable question closes: thar0-console's rdp.read-gate and ri.overhead-rdp, and the rows that systembench checks.
   - Coverage: 224 entries, 208 with a question.
   - No row status changed (diffed all 149).
5. Undecidable: DONE. The 8 legacy.cart.* rows and legacy.pif.boot-timeout now read "not decidable by this kit: ... What would decide it: <retail/dev cartridge with the chip | modified IPL3>". The rule accepts both prefixes, and the inventory counts them apart: 7 not hardware-decidable, 9 not decidable by this kit.
6. Bounded waits: DONE, in console builds only (hwout.py).
   - pi_wait stops after 2^20 polls ($t1 counts).
   - transform bounds krd_wait, kfd_done, kff_done and kcm_poll after 2^22 polls ($a0 counts; a0 is unused after the kernels read their args). If a wait's shape changes, the build raises an error.
   - An abandoned wait increments DATA+0xEC (PI) or 0xF0 (RDP). hw_finish prints `#kit-timeout pi= rdp=`.
   - Ingestion fails the questions of a ROM whose log counts a timeout, and verify_run fails a fork run that counts one.
   - The longest fork kit point is 124,517 COUNT ticks (2.7 ms, measured), so the 1.07 s bound leaves about 400x margin.
   - Mutants: a DP wait that never sees the interrupt makes kit-rdp finish with rdp=0xf0, a valid footer, and all 5 kit-rdp questions failing. A PI wait that never idles makes rdpstat-dpc finish with pi=0x80.
   - Doc: an empty save means the ROM stopped before its first line, and a truncated one means it stopped after the last saved record. Run the ROM once more from a power cycle, keep both captures, and report the last record.
   - Controllers: only kit-dma's second run needs four. With one pad, skip that run.

## Acceptance (measured on the merged head)
- --check ok. --self-test 61/61 (4 new). Kit self-test 15/15, romgen self-test 72/72, lint ok, pidma 5/5, systembench report 11/11.
- run.sh: 103 SRAM copies checked, 0 errors (also with the era model).
- dry-run: 76 of 80 hw checks pending to pass, including systembench, cpu-exceptions and cpu-watch, and 26 behaviors flip. The 4 left: pidma-offset, mm-filesel, vi-mid-field-blank and vi-unfetched-video.
- MM 600 --stats md5 9629185039701bddcdbd90c248a4f38b, equal to master (verify-83 head).
- nemu64 values.tsv timing (1605 lines), cycle (14) and cop0hazard (6) are byte-identical to verify-83 head (master core).
- Byte-identical to master's sysbench-era/after run: systembench results.tsv, bench results.tsv, thar0 compare.tsv, mmbench summary.tsv and rom-sha256.txt. So non-hw ROMs are unchanged.
- det/stepcap MM and nemu64: PASS. Round trip: PASS. ctest: pass.
- --results gives every check the same result as master's run (only the provenance line differs). Load: 1.1-6.6.
- Not done: MM wall time, because the core did not change (md5 and stats are identical).

## Deviations
- I added hw: links for every row that a reader-backed ext question closes, as the new rule requires. thar0 rows fit from thar0 are exempt.
- I also bounded kfd_done and kff_done, which the brief did not name, because they are the same kind of DP wait.
- The bounds are applied by a transform in hw builds, so that bench and other non-hw ROMs stay byte-identical. Editing bench asm.py would have changed the bench poll cadence.
- calib1/dry-run.txt used the 845635c model. calib2/dry-run2.txt and the standing run used the era build after #88.

## Follow-ups
- #87 (Watch), #86, vi-first-line tolerance, small SP DMA, textured triangles: unchanged.
- The ri.max-burst to sp-dma-direction link is an inference: the 256-4096 B chain slope reflects the 128 B RI split.

No background process of mine is running. The obsolete first standing run was killed by its own PID tree before the #88 merge.
