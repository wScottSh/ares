# systembench report

Status: done. Branch feat/systembench, head 6145930ba, base master 253e1c8ea. PR: https://github.com/wScottSh/ares/pull/83.
Worktree /home/wscottsh/repos/ares-wt/systembench. Build ~/n64-timing/build/systembench. Private home ~/n64-timing/systembench-home (corpora and scratch symlinked). Raw results ~/n64-timing/results/systembench/{first,before,after,wall}, plus before.log and after.log. No process of mine is running, and no libdragon container either.

Commits:
- de10c59c3 adds build-systembench.sh.
- 702f751e9 adds the boot-delay ROMs, run.sh and report.py.
- 38298c8ff adds compare.py, the rows.tsv notes and the README section.
- 9ed43d6ef wires checks.tsv, behaviors.tsv and behaviors.py and adds the standing.sh steps.
- 6145930ba regenerates the spec from the after run.

No timing value changed. behaviors.hpp changes only verify and note strings.

## 1. Toolchain

`tools/n64-timing/build-systembench.sh` pins three inputs:
- rasky/n64-systembench 845635c.
- libdragon preview cc490afe0, the last preview commit before 845635c.
- The libdragon preview toolchain image, `ghcr.io/dragonminded/libdragon@sha256:bbc66328...b21f`, GCC 16.2, built 2026-09-14.

It writes to $N64_TIMING_HOME/systembench, with the build tree in `<OUT>-stage`. Nothing goes into the repo.
- Trunk does not work, despite "any trunk version should work". main.c needs `PI_STATUS_DMA_BUSY` from dma.h, which only preview exports (measured: trunk e356bf3f5 fails to compile). main.c also includes `../libdragon/include/regsinternal.h`, so the script extracts libdragon into `stage/libdragon`.
- ghcr keeps no December 2025 image. The tags hold 2021-2022 commit images plus trunk/preview/latest. So the compiler is newer than the one 845635c was built with.
- The build is reproducible (measured). Two runs give z64 sha256 c1c85c13...f5f6 and elf 16366964...af43.
- Licenses: n64-systembench has no license file, so neither its source nor its ROM is committed. libdragon is the Unlicense (public domain).
- A parallel `make install-mk libdragon tools install tools-install` raced in tools/ once (mips_decomp_l2.bin empty). The script now runs the goals in the order libdragon's build.sh uses.

## 2. Running and capturing

The ROM prints its whole table through `debugf` to ISViewer. `n64-run` writes ISViewer text to stdout, so no OCR or RDRAM read is needed. One run takes 0.8 s of wall time. It finishes before the VI is enabled, and `--frames 2` stops right after.
- `systembench/report.py` parses each `*** NAME [QTY]` / Expected / Found block. It applies main.c's own rule: diff <= 1 CPU or 2 RCP cycles (main.c:17-18; 24 xcycles truncates to 2), or under 0.2 % (main.c:664-669). The self-test has 11 cases, including both edges of the 0.2 % rule.
- Phase spread (pref 27): there are 32 boot-delay ROMs, K = 1 + 63i, i = 0..31. Each step is 126 pclk, coprime to the 25/26 pclk polls, and the 32 steps span the 3944 pclk idle-VI grid.
  - The countdown sits in libdragon `_start`, padded so every later address moves by exactly 0x800 at every K. Measured: main 0x80012680 -> 0x80012e80, rambuf 0x8002de00 -> 0x8002e600.
  - So the delay ROMs share one layout, which is the unpadded layout moved by one RDRAM row.
- `systembench/run.sh` runs the unpadded ROM and all 32 delay ROMs (33 runs, 3 s with 4 runners).
  - Verdict: pass when every run passes, consistent-only when only some do, fail when none do.
  - standing.sh builds the ROMs (docker) into roms/systembench and runs them. Without docker the checks are pending:no-rom.

## 3. Original on the fork vs romgen port on the fork vs hardware

Offsets are from each side's own expected value. The port's net_pclk expected value is hardware less 2. "Rule" is the port's phase rule.

| row | hw | original (33 runs) | orig offset | main.c rule | port range | port median offset | port verdict |
|---|---|---|---|---|---|---|---|
| C8R/C16R/C32R/C64R | 3 | 4 (2..4) / 2 / 2 / 2 | +1/-1/-1/-1 | pass | 2 | -1 | report |
| U8R-U32R | 34 | 34 | 0 | pass | 32 | 0 | pass |
| U64R | 37 | 37 | 0 | pass | 35 | 0 | pass |
| U32R seq | 134 | 133 | -1 | pass | 131 | -1 | pass |
| U32R rand | 134 | **151** | **+17** | **fail** | 131 | -1 | pass |
| U32R banked | 136 | 133 | -3 | fail | 131..132 | -3 | fail |
| RCP I/O R | 24 | 24 | 0 | pass | 22 | 0 | pass |
| PI DMA 8 | 193 | 190 | -3 | fail | 180..194.67 | -3 | consistent-only |
| PI DMA 128 | 1591 | 1582 | **-9** | **fail** | 1574.67..1592 | -8 | pass |
| PI DMA 1 KiB | 12168 | 12185 (..12186) | +17 | pass | 12156..12169.33 | -5 | pass |
| PI DMA 64 KiB | 777807 | 778349 | +542 (0.07 %) | pass | 778332..778348 | +531 | pass |
| PI I/O R | 144 | 144 | 0 | pass | 143 | -1 | pass |
| PI I/O W | 134 | 130 | **-4** | **fail** | 125.33..142.67 | -1 | pass |
| SI DMA W RAM | 4065 | 4065 | 0 | pass | 4058.67..4073.33 | +1 | pass |
| SI DMA W ROM | 2144 | 2140 unpadded, 2139 shifted | -4/-5 | consistent-only (1/33) | 2136..2149.33 | -1 | pass |
| SI I/O R | 1974 | 1974 | 0 | pass | 1973 | -1 | pass |
| SI I/O W | 2158 | 2151 | **-7** | **fail** | 2149.33..2166.67 | 0 | pass |
| JOY Empty 0B..63B, 1J, Accessory | | identical to the port at every point | | pass | | | pass |
| JOY 2J/3J/4J | | 57977/77962/97948, identical to the port | | report | | | report |

All values are measured, from after/systembench and after/bench.

Why the two sides differ:
- **Boot phase decides nothing.** In 31 of 34 rows the original reads the same value in all 33 runs. The 3 that move, by 1-2 units, are C8R (2..4), PI DMA 1 KiB (12185..12186) and SI DMA W ROM (2140 vs 2139). In each the unpadded ROM differs from the shifted layout, so that is layout, not boot phase. That fits the original's poll loops (bench_piiow disassembly: `mfc0` then `sw`, then 8 x {`mfc0`, `lw` PI_STATUS}): the poll's phase relative to the write is fixed by the code (measured as constant; the mechanism is inferred from the disassembly). The port's nop jitter walks a phase that the original never varies.
- **U32R rand and PI DMA 1 KiB come from layout.** In this build rambuf sits at 0x8002de00, 0x200 below a 2 KiB RDRAM row. So U32R rand alternates rows (+12 is in row 0x2d800, the other three in 0x2e000), and the 1 KiB DMA spans two rows. I tested this with a scratch build where rambuf is `aligned(2048)` (0x8002e800): U32R rand reads 133 (pass) and PI DMA 1 KiB reads 12170 (+2), against 151 and 12185 (measured). Where the hardware build's rambuf was is not known. U32R rand is therefore not wired to any behavior.
- **The poll rows are a model offset at the hardware's phase, not phase noise.** Inferred, with the caveat below. PI I/O W -4, SI I/O W -7, SI DMA W ROM -4 and SI DMA W RAM 0 are single readings at the original's own poll phase. The port's consistent window (±8 to 11 rclk) hid the first three.
  - The values pi.io-busy 134, si.io-busy 2158 and si.write64-rom 2144 are the hardware poll totals written in as busy times. The original's code samples the status some pclk after the busy ends, so a busy time equal to the total reads short at this phase.
  - A fix would solve each busy time so that the original's reading lands on the total. That is a separate unit, and it needs pref 21 fit labeling.
- **PI DMA 128 -9 and 8 -3 are model errors at the original's phase.** The 128 B point is fit data for pi.block-writeback (fit to the port), so the fit does not hold pointwise.
- **U32R banked -3 is confirmed pointwise.** The original and the port agree, so it is a model error (cause still untraced).
- **C*R: hardware 3, fork 2 on the same code.** COUNT ticks every 2 pclk. Hardware's 3 is a mean of 1.5 ticks over the reps, and the fork reads 1 tick every rep. The `mfc0; lw; mfc0` window or the rep's parity differs by about 1 pclk (inferred). The rule passes it (±1).

Do the consistent-rule rows hold up pointwise? These pass or are consistent on the port, but the original on the fork fails main.c's rule: PI DMA 128, PI I/O W, SI I/O W and U32R rand (layout). PI DMA 8 was already consistent-only and fails pointwise. SI DMA W ROM passes unpadded and fails shifted. Every other consistent row lands inside the hardware band pointwise: U8-U64, seq, RCP, PI DMA 1 KiB and 64 KiB, PI I/O R, SI DMA W RAM, SI I/O R, and all JOY checks.

Caveat on "same code": the hardware numbers come from 2022-08 builds (most rows) and a 2023-01 build (SI DMA, JOY), with GCC 12 and the vendored 2022 libdragon. Also, 4b538eb (2024-05, hacktarux) rewrote the TIMEIT_MULTI averaging after the numbers were taken and left the expected values unchanged.
- The timed instructions are pinned by volatile accesses and `TICKS_READ`, so the instruction sequence is very likely the same (inferred, not compared; no 2022 binary or GCC 12 image is available).
- The addresses differ, as rambuf shows.

## 4. Wiring

- **New runner `systembench`.** It has a `systembench:*` suite row over `systembench/rows.tsv` (key `row`, 34 rows; 2J-4J are report rows, as before). The reader shows the unpadded value, the range, the offset and the runs that pass. The ROM gate is `./systembench/n64-systembench.z64`. A behaviors self-test case (50 cases) checks that a row failing at every run reads fail with its value and offset; the gen check now also requires the report.py self-test.
- **Replaced, 4 checks.** pi.io-busy, si.io-busy, si.write64 and si.write64-rom now name systembench:pi-io-w, si-io-w, si-dma-w-ram and si-dma-w-rom. The four bench checks.tsv rows are deleted; the bench ROM still runs them. Evidence: the port passed all four by construction inside a phase window. The original reads one fixed phase, at every run, at the hardware's own code. Its notes are rewritten to say that.
- **Beside, everything else.** The original was added next to the port check:
  - cpu.uncached-read-total: u8r, u16r, u32r, seq and banked, not rand.
  - u64r, rcp-io-r, si-io-r and pi-io-r on their rows.
  - pi-dma-* on pi.page-setup, halfword-bias and block-writeback. On block-writeback, 128/1K/64K go in fit-from, since they are the same hardware numbers.
  - The JOY rows on si.read64-base and pif.joybus-*. fit-from gets the systembench twins of the existing fit points. pif.joybus-no-device stays verify-is-fit.
- **Row status, master to head.** pi.io-busy pass -> fail. si.io-busy pass -> fail. si.write64-rom pass -> consistent-only. Rows: 72 pass / 31 fail -> 69 pass / 33 fail / 1 consistent-only. Checks: 3 consistent-only, 24 fail, 87 pass, 1 pass-conditional:#77, 15 pending.

## Standing (before = master core with this harness; after = head)

- MM 600 `--stats` md5 9629185039701bddcdbd90c248a4f38b on both, equal to the brief's 96291850.
- These are byte-identical before vs after and also against verify-80/head:
  - nemu64 timing, cycle and cop0hazard `values.tsv` (x3);
  - thar0 `compare.tsv`.
- Byte-identical before vs after:
  - mmbench `summary.tsv`;
  - bench `results.tsv`;
  - systembench `measurements.tsv`;
  - `rom-sha256.txt`: 688 ROMs, the 655 suite ROMs plus 33 systembench ROMs; list sha256 f3c63c4bacb0.
- PASS on both: det and stepcap (MM 29 files / 8219 fields; nemu64 x3), the state round trip, the TMEM poke and ctest 9/9.
- after: `--check` ok, `--self-test` 50 cases 0 failed, lint ok, pidma 5/5, systembench report 11/11. The before run's gen check failed only because the results file lacked the new check ids. It was regenerated from that run, then from the after run.
- Load: 5.4-8.1 before, 5.2-7.1 after.
- MM wall (copied runners, interleaved, 3 rounds, load 2.6-5.3): base 22.92/22.68/25.58 s, head 23.31/24.64/22.72 s. The medians are 22.92 and 23.31 s, within noise. The core differs only in strings.

## Deviations

- The default output is $N64_TIMING_HOME/systembench, and the build tree goes to `<OUT>-stage`. standing.sh builds into $roms/systembench, so the ROMs reach rom-sha256 and the gate.
- libdragon is the preview branch, not trunk (trunk does not compile main.c).
- Boot-delay ROMs patch libdragon `_start` (a sed in the container) and move the layout by 2 KiB. The unpadded ROM is the one built from unmodified sources.
- The C*R rows are checks in rows.tsv, but no behavior names them, and U32R rand is not wired (layout).
- mm-bench.md is regenerated with a note saying this branch changes no timing value.

## Follow-ups

1. Poll-total rows (separate unit): re-solve pi.io-busy, si.io-busy and si.write64-rom so that the original's reading at its own phase gives 134 / 2158 / 2144. They now read -4 / -7 / -4, and si.write64 reads 0. That is a fit (pref 21), and its independent check would have to come from another phase or bench.
2. pi.block-writeback: the fit holds at the port's phase median but not pointwise (128 B -9, 8 B -3). Refit against the original's readings.
3. U32R banked -3 (both sides) is still untraced.
4. A hardware-era build needs a ruling extension: n64-systembench 50f5066 (2023-01, the last commit before the TIMEIT_MULTI rewrite) with its vendored libdragon and a GCC 12.x toolchain built from libdragon's Dockerfile at a54ccd736. It would show how much codegen and layout move the poll rows. Pref 28b allows 845635c only, so I did not build it.
5. For #16 (calibration): one hardware run of the 845635c ROM from build-systembench.sh, plus a read of `rambuf`'s address from its ELF, would make every row a same-binary comparison. The ingestion path is report.py on the ISViewer/USB log.
6. verify-80's wording note on pif.joybus-skip/-escape (32B/56B/63B are not independent checks) is still open; this unit did not touch it.
