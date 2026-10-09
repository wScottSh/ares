# verify-88: PR #88 (sysbench-era), PASS-WITH-NOTES

Head 7d70ee3a5073c525ccbcc92b74b03a8d3a36ec38 vs base master 1081af9f8. Worktree `ares-wt/verify-88`, build `~/n64-timing/build/verify-88`, private home `~/n64-timing/verify-88-home`. Raw: `~/n64-timing/results/verify-88/{standing,p-era-fix,p-era-unfix,p-gcc121,p-gcc162}`; builds, disassembly and `cmp.py` in the home dir. Load 2.5-6.4 (calib-kit-merge standing ran alongside). No process or container of mine is left running. I reused the worker's two toolchain images (a54ccd736, eed8ef3b7; ids match the report) and rebuilt everything else.

## Verdict
PASS-WITH-NOTES. Every numeric and objdump claim reproduced. The wiring is as described, standing is unchanged, and no timing value changes. Notes are about interpretation and labeling, none blocks landing.

## 1. Era attribution (reproduced)
- `git log -S` on each hardware value in main.c: C/U/RCP I/O R rows (CPU 3, 34, 37, 134, 136, 24) first appear in 3c6a0ee; PI DMA 193/1591/12168/777807 and PI I/O W 134 in de9d9dd; SI/JOY rows (4065, 2144, 1974, 2158, 15030..97890, 36834) in 50f5066. One miss in the report and README: PI I/O R 144 first appears in 8313bcb (2022-08-08), before de9d9dd. Same day, same GCC 12.1 era, so it changes nothing, but "PI values since de9d9dd" is not exact.
- 4e49cc7 only rescales macros (XCYCLE 2/3 to 6/9, ratio kept) and re-indents the table; values unchanged.
- Timed functions: extracted each of 15 bench functions at de9d9dd, 3c6a0ee, d12e8ea, 50f5066 and compared md5. bench_pidma, piiow, piior are byte-identical across all four; every function present in a commit is identical in every later commit. The TIMEIT/timeit_average macro block md5 is identical in all four (4b538eb rewrote it later). No timed function changed across the era (measured).
- Toolchain mapping (GCC 12.1 for 2022-08, 12.2 for 2023-01) is labeled inferred in the script header, README and report. The Makefile links the installed libdragon, so the hardware link layout is unknowable (labeled).

## 2. objdump (reproduced, own builds)
Built 50f5066 with GCC 12.2 (fixed), 50f5066 with GCC 12.1 (unfixed, image eed8ef3b7) and 845635c with GCC 16.2 (build-systembench.sh, z64 c1c85c13... and elf 16366964... identical to verify-83). Extracted bench_pidma, piiow, siiow, sidmaw_rom, sidmaw_ram, then compared first `mfc0 c0_count` through the first `bnez` plus delay slot (21-23 instructions) with registers renamed by first use and branch targets dropped (`cmp.py`):
- 12.2 vs 12.1: identical in all 5 functions.
- 12.2 vs 16.2: identical in piiow, siiow, sidmaw_rom, sidmaw_ram. bench_pidma differs only in the register numbering my normalizer gives it (GCC 16.2 reuses `v0` earlier); the mnemonic and immediate sequence is identical (23 of 23). Caveat: this is the span to the first branch, i.e. the first poll group; the rest of the poll chain I read by eye on piiow/pidma/sidmaw_rom (same `andi/beqz/move` structure), not diffed.
- Pre-span code differs (16.2 hoists `li s1,50` etc. and puts a `nop` before the first `sw`), outside the timed window.

## 3. Tie fix
- Built the 2023 era from the script: fixed z64 fd5ec6c06acb686608c53554950c8b6b12b011dca5b30bf22bd7277a8d986823 (elf e5373a22...), unfixed (ERA_TIE_FIX=0) d1c3950ed7ea25c41e3f2bc9aef3a0dea85de28b6af7d1c9183e26dbab4057f7 (elf 939b12b5...). Both byte-identical to the report. The standing run's pristine z64 (built with the 32 boot-delay loop) is the same fd5ec6c0. 
- Whole-ELF objdump diff fixed vs unfixed: exactly 2 lines in `timeit_average` (`sltu a2,a2,v0; bnez` becomes `sltu a2,v0,a2; beqz`), `nm -n` identical.
- Fix scope, my pristine runs, hw vs fixed vs unfixed (50f5066 GCC 12.2): C16R 3/2/4, C32R 3/2/4, C64R 3/4/2 (C8R 2/2); PI DMA 1 KiB 12168/12170/13692; SI DMA W ROM 2144/2140/2138; JOY Empty 4B 20644/20641/21071, 8B 21163/21161/21602, 32B same, 56B 21170/21161/21602. No other row differs in the 12.2 layout. In the GCC 12.1 layout (unfixed) the tie also fires on PI I/O R 147 (144 x 49/48), SI I/O R 2015 and PI DMA 64 KiB 875643 (9/8): the bug is layout dependent.
- Judgment: patching is fair, and the hardware numbers themselves are the evidence, which is stronger than the report's "samples rarely tie on hardware". Hardware PI DMA 1 KiB 12168 sits on the fixed value (12170), not 13692 (+12.5 %); JOY Empty 4B/8B/32B hardware 20644/21163/21163 sit on 20641/21161, not 21071/21602 (+2 %). So on every row the unfixed code disagrees with hardware, the hardware sample set did not tie. The labeling is present: script header comment, README (tie bug bullet), checks.tsv source, ERA_TIE_FIX=0 switch. No row is more faithful unfixed: C16R-C64R flip between 2 and 4 either way (hardware 3 is a phase mean); SI DMA W ROM unfixed is 2 farther from 2144 (and only consistent-only either way). Residual: where the fork ties and hardware also tied (cached C rows, quantized by COUNT) we cannot tell; those rows pass under the +-1 rule at both phases. Suggest adding the "hardware values sit on the fixed numbers" argument to README; it is currently only "inferred".

## 4. Table (reproduced)
Standing run (33 runs each; value, min..max over runs), hw / era-fix / 845635c:
C8R 3 / 2 (2..3) / 4 (2..4); C16R 3 / 2 / 2; C32R 3 / 2 (2..4) / 2; C64R 3 / 4 (2..4) / 2; U8R..U32R 34 / 34 / 34; U64R 37/37/37; U32R seq 134 / 134 (134..135) / 133; U32R rand 134 / 134 (134..135) / 151 (0/33); U32R banked 136 / 134 (134..135, 32/33) / 133 (0/33); PI DMA 8 193 / 187 (186..187) / 190; 128 1591 / 1580 / 1582; 1 KiB 12168 / 12170 / 12185 (..12186); 64 KiB 777807 / 778364 / 778349; PI I/O W 134 / 130 / 130; SI DMA W RAM 4065 / 4065 / 4065; SI DMA W ROM 2144 / 2140 (2138..2140, 1/33) / 2140 (2139..2140, 1/33); SI I/O R 1974 / 1973 / 1974; SI I/O W 2158 / 2150 (2150..2151) / 2151. All equal the report.
- rambuf (nm): 0x800278c0 (50f5066/12.2, row offset 0xc0, +1024 stays inside 2 KiB), 0x8002de00 (845635c, offset 0x600, +1024 crosses), and a build the report did not list: 50f5066 with GCC 12.1 puts it at 0x80027c00 (offset 0x400, +1024 = next row) and reads U32R rand 151 (measured). So the era "pass" of U32R rand holds with the 12.2 link only; with 12.1 on the same source it fails like 845635c. The README says the 2022 builds read 150-151 and the address is unknown, so the labeling is fair, but the u32r-rand and pi-dma-1024 passes should not be read as confirmations.
- C8R-C64R by COUNT phase: instruction swap alone flips C16R/C32R/C64R (above, measured). COUNT-parity explanation itself stays inferred (consistent with `sll 1; addu` ->x12 xcycles per tick = 2 cpu cycles; hardware 3 is the mean of 2 and 4).

## 5. Wiring
- `standing.sh` builds `build-systembench-era.sh 2023` into roms/systembench (checks read it) and 845635c into roms/systembench-845635c (run to results/systembench-845635c, no checks). `run.sh` `if` fix correct (no-boot-delay ROM set otherwise failed under pipefail; my four pristine-only runs worked).
- rows.tsv: all 34 rows' `main.c:NNN @50f5066` line numbers checked against `git show 50f5066:src/main.c`; each points at its row. checks.tsv source text updated and names the tie fix and the report-only 845635c.
- Four poll-row notes (behaviors.tsv, mirrored in behaviors.hpp strings, 8 lines) now say "this instruction sequence only" with the nop sensitivity; behaviors.hpp diff is strings only; no value touched, no refit, fit-from column unchanged.
- Result changes: `behaviors.py --results` over my standing run regenerates docs/spec/n64-timing-results.tsv byte-identical except the one-line provenance header. Status counts pass 87, fail 23, consistent-only 4, report-only 14, pending:no-rom 1, pass-conditional 1 (file-wide count, includes other suites). systembench: era 2 consistent-only / 4 fail / 25 pass / 3 report; 845635c 1 / 6 / 24 / 3. u32r-banked fail -> consistent-only (32/33), as claimed.
- `--check` ok, `--self-test` 50/0 (behaviors.txt), lint ok, pidma 5/0, report.py 11/0.
- README: "readings move by at most 4 rclk" (across seven builds, all poll rows incl. PI DMA 8) and the notes' "at most 2" (the four noted rows) are both true for their row sets (PI DMA 8 186..190).

## 6. Standing (reproduced, own build)
MM 600 `--stats` md5 9629185039701bddcdbd90c248a4f38b. nemu64 timing/cycle/cop0hazard `values.tsv`, thar0 compare.tsv, bench results.tsv, mmbench summary.tsv byte-identical to verify-83's head run. det PASS (MM 29 files / 8219 fields; nemu64 x3), stepcap PASS (same), round trip PASS (600 fields, saves/loads at 150/300/457), TMEM poke PASS (first diff field 31), ctest 9/9. MM wall time not re-timed (core is strings-only).

## Diff findings
- No dead code, no committed third-party code, no timing constants added. `build-systembench-era.sh` header comment is long but explains whys. 
- README/script: "PI values date to de9d9dd" omits PI I/O R 144 (8313bcb); cosmetic.
- The "hardware binary likely GCC 12" premise is the one inferred link behind "this is the hardware's instruction sequence"; stated as inferred everywhere I looked.
- Not reproduced: worker's 2022-era (d12e8ea) and 3c6a0ee/de9d9dd variant reads (not rebuilt; I rebuilt 50f5066/12.1 instead). The worker's 7-build PI I/O W = 130 claim: I confirmed 12.2, 12.1 (50f5066), 16.2 = 130 (3 of 7). 

## Model-error candidates (my read)
Context: these now compare the model with hardware at one verified instruction sequence (compiler and layout excluded for 12.1/12.2/16.2). The remaining unknown is whether the hardware binary's poll cadence equals this one (inferred yes). verify-83's nop sensitivity (up to 10 rclk) means a poll reading error smaller than the poll step (~17 rclk) says the write-to-first-poll offset or busy end is off by about that amount, but not by which parameter (guess).
1. PI I/O W -4, SI DMA W ROM -4, SI I/O W -8: worth one fix unit, treated as a group. All are `measured` basis rows with no fit-from, all misses are multiples of 4 rclk, so one shared cause (write-issue to first-poll visibility, or I/O busy end) is plausible (guess). SI DMA W RAM (exact 4065), PI I/O R, SI I/O R are the regression guards but come from the same poll code, so the unit still needs an independent check (pref 21): the #16 same-binary hardware run, or the bench:* poll walks (+-8 only). Do not refit before the unit says which parameter moves.
2. PI DMA 8 -6: independent (not in fit-from), so worth a fix, but inside the existing PI DMA track (pidma:logs fails independently, pi.block-writeback is fit). Bundle with 3.
3. PI DMA 128 -11: this is fit data (pi.block-writeback). The fit holds at the port's poll phase (-8 median) and fails at the original code's: the fit absorbed poll phase. Fixing it by refit is a fit with no independent check except pidma:logs and the 8 B point; do it only as a re-solve in the PI DMA unit, labeled fit only.
4. U32R banked -2: lowest value. -2 is one COUNT tick (2 cpu cycles), 32 of 33 runs already pass at 135, and seq/rand/U8-64R match. A sub-tick bank-switch cost (guess); defer to the #16 same-binary run.
Priority: 1, then 2+3 together; 4 not worth a unit.

## Recommendation
Land. Optional follow-ups: README sentence that hardware numbers sit on the fixed values; mention the 50f5066/GCC 12.1 rand = 151 data point; 8313bcb attribution.
