# sysbench-era report

Status: done. Branch feat/sysbench-era, head 7d70ee3a5 (standing run on 8c652711f; the later commit only changes a script comment). Base master 1081af9f8. PR: https://github.com/wScottSh/ares/pull/88.
Worktree /home/wscottsh/repos/ares-wt/sysbench-era. Build ~/n64-timing/build/sysbench-era. Private home ~/n64-timing/sysbench-era-home (scratch and corpora symlinked). Raw results are in ~/n64-timing/results/sysbench-era:
- `run-845635c`, `run-2023`, `run-2023-fix` and `run-2022` hold the 33-run results.
- `probe/` holds the per-build stdout and the PI logs.
- `after/` and `after.log` hold the standing run.
- `compare-era.tsv` and `compare-845635c.tsv` hold the comparisons.
- `build-*.log` holds the build logs.

Scratch variant builds are in ~/n64-timing/sysbench-era-home/variants (nm.txt and dis.txt per build). No process or container of mine is running. Two docker images are left: n64-timing/libdragon-toolchain:a54ccd736 and :eed8ef3b7, about 840 MB each, for reruns.

## Answer

The five pointwise fails are model-error candidates. They are not codegen or layout artifacts of the 845635c + GCC 16.2 build.
- The timed instructions are identical across compilers, apart from register names (objdump, measured). This covers the stretch from the first COUNT read through the poll loop's branch for bench_pidma, bench_piiow, bench_siiow, bench_sidmaw_ram and bench_sidmaw_rom. The compared builds are 845635c with GCC 16.2, 50f5066 with GCC 12.2, 50f5066 with GCC 12.1, and d12e8ea, 3c6a0ee and de9d9dd with GCC 12.1. The one exception is de9d9dd's bench_pidma, which has one extra `nop` after the length write and reads the same.
- The readings barely move (measured). PI I/O W reads 130 in all 7 builds. PI DMA 128 reads 1580..1582, PI DMA 8 186..190, SI I/O W 2150..2152 and SI DMA W ROM 2138..2140 (fixed 2140).
- Caveat (inferred): this assumes the hardware binary also came from a GCC 12. The libdragon toolchain of both dates was GCC 12.1 or 12.2. The author's actual toolchain is not recorded.

## 1. Which commit and toolchain (evidence)

- The PI values have been in main.c's table since de9d9dd (2022-08-08), under the names "PI DMA (default speed)" etc. (`git show de9d9dd:src/main.c`). The RDRAM and RCP values arrived in 3c6a0ee (2022-08-09). 4e49cc7 rewrote the table lines (blame shows 4e49cc7 for main.c:572-595 at 845635c) without changing a value. The SI and JOY values arrived in 50f5066 (2023-01-25, blame main.c:596-613). None changed afterwards.
- `git diff de9d9dd 50f5066` changes no line of an existing bench function. Only the table, macros, display and new functions change. So the timed source is identical across the era. 4b538eb (2024-05) rewrote TIMEIT_MULTI afterwards.
- The vendored libdragon is the subtree of upstream 49e6a7d (2022-05-31). Its tools/build-toolchain.sh pins GCC 12.1.0, binutils 2.38 and newlib 4.1.0. Upstream bumped the toolchain to GCC 12.2 / binutils 2.39 on 2022-09-01 (9c4a3d9dd). The last toolchain change before 2023-01-25 is a54ccd736 (2022-09-13), and binutils 2.40 arrived on 2023-01-26.
- Era map:
  - 2022-08 values: eed8ef3b7 (2022-07-13), GCC 12.1.
  - 2023-01 values: a54ccd736, GCC 12.2.
- Caveat: the Makefile links $(N64_INST)'s installed libdragon, not necessarily the vendored one, so the hardware build's link layout (rambuf) is not reconstructible exactly.

## 2. Build

- `tools/n64-timing/build-systembench-era.sh [2023|2022]` builds a toolchain image from that libdragon commit's own Dockerfile. It deletes the unpinned `# syntax` line and pins the base to ubuntu@sha256:152dc042...3c98. Then it builds the systembench commit with its vendored libdragon, plus 32 boot-delay ROMs padded after the vendored entrypoint's deadloop (measured: every address +0x800).
- Images:
  - a54ccd736 is sha256:17c00145e5497ecfd2eb6ca355b90d975e431cb12fee2fdc6628c607fda05b47 (GCC 12.2.0, ld 2.39).
  - eed8ef3b7 is sha256:ca27f7d12f64474625a2297212ccbb5b4176ef39768c5851ed27063be2ccebf1 (GCC 12.1.0, ld 2.38).
  - The apt packages and GNU tarballs are not pinned beyond their version numbers.
- Reproducible (measured):
  - 2023 unfixed z64 d1c3950e...57f7, twice.
  - 2023 fixed z64 fd5ec6c0...6823, matching the scratch variant built separately.
  - 2022 z64 d888b174...c0d, three times.
- Tie bug (measured): the era `timeit_average` sets min = max = 0 when every sample is equal. It then drops one sample and divides by n-2. The fork's samples are identical, so an unfixed 50f5066 reads PI DMA 1 KiB 13692 (fixed 12170) and JOY Empty 4B/8B/32B/56B 21071/21602 (fixed 20641/21161), and in the shifted layout PI DMA 64 KiB 875659 (= 9/8 x 778364).
  - The PI log shows the DMA itself takes the same 146060 units as in 845635c. So the inflation is in the averaging, not the model.
  - The script changes `>` to `>=` in the max test. objdump shows two instructions differ, and nm is identical. Hardware samples jitter, so on hardware the bug would only fire if all n samples were equal (inferred).
  - `ERA_TIE_FIX=0` builds the original.
- Nothing from systembench is committed.

## 3. Table (fork, 33 runs each, unpadded value with the boot-delay range)

| row | hw | era 50f5066+fix (checks) | 845635c (report) | romgen port, median offset | verdict |
|---|---|---|---|---|---|
| C8R/C16R/C32R/C64R | 3 | 2 (2..3) / 2 / 2 (2..4) / 4 (2..4) | 4 (2..4) / 2 / 2 / 2 | -1 | pass both (±1 rule) |
| U8R/U16R/U32R | 34 | 34 (34..35) | 34 | 0 | pass |
| U64R | 37 | 37 (37..38) | 37 | 0 | pass |
| U32R seq | 134 | 134 (134..135) | 133 | -1 | pass both |
| U32R rand | 134 | **134** (134..135) | 151 | -1 | **artifact** (rambuf row) |
| U32R banked | 136 | 134 (134..135), 32/33 | 133 | -3 | both disagree |
| RCP I/O R | 24 | 24 | 24 | 0 | pass |
| PI DMA 8 | 193 | 187 (186..187) | 190 | -3 | **both disagree** |
| PI DMA 128 | 1591 | 1580 | 1582 | -8 | **both disagree** |
| PI DMA 1 KiB | 12168 | **12170** | 12185 (..12186) | -5 | artifact (both pass the 0.2 % rule) |
| PI DMA 64 KiB | 777807 | 778364 | 778349 | +531 | pass (0.07 %) |
| PI I/O R | 144 | 144 | 144 | -1 | pass |
| PI I/O W | 134 | 130 | 130 | -1 | **both disagree** |
| SI DMA W RAM | 4065 | 4065 | 4065 | +1 | pass |
| SI DMA W ROM | 2144 | 2140 (2138..2140), 1/33 | 2140 (2139..2140), 1/33 | -1 | **both disagree** (consistent-only) |
| SI I/O R | 1974 | 1973 | 1974 | -1 | pass |
| SI I/O W | 2158 | 2150 (2150..2151) | 2151 | 0 | **both disagree** |
| JOY Empty 0B..63B, 1J, Accessory | | identical to 845635c | | | pass |
| JOY 2J/3J/4J | | 57977/77962/97948, identical | | | report |

The other builds were run once each, unpadded:
- 50f5066 with GCC 12.1 (unfixed): PI DMA 8 186, 128 1580, PI I/O W 130, SI I/O W 2152, SI DMA W ROM 2140.
- d12e8ea: 189 / 1580 / 130, U32R rand 150.
- 3c6a0ee: 187 / 1580 / 130, rand 151.
- de9d9dd: 186 / 1580 / 130.

Artifact rows (era agrees with hardware, 845635c does not):
- U32R rand: era rambuf 0x800278c0 stays inside a 2 KiB row; 845635c 0x8002de00 crosses one.
- PI DMA 1 KiB +17 vs +2: same cause, but both pass.
- C8R-C64R read 2 or 4 per binary. COUNT ticks every 2 pclk, and the fork's samples are identical, so each run reads one COUNT phase (inferred). The two-instruction timeit_average change alone flips C16R/C32R/C64R between 2 and 4 (measured). The hardware 3 is a mean over phases (inferred). This replaces verify-83's averaging explanation: U32R seq 133 vs 134 is layout or code (it reads 134 both fixed and unfixed in 50f5066, and 133 in 50f5066 built with GCC 12.1), not averaging.

Re-check of U32R rand and PI DMA 1 KiB: the hardware-era 2023 build has no rambuf row issue. In it both pass (134; 12170). The 2022 builds, from the era when the rand value was written, put rambuf at 0x80026580 and read rand 150/151. So rand depends on a layout the hardware build may or may not have had, and it stays unwired (rows.tsv note updated).

## 4. Wiring

- standing.sh builds the era ROM (`build-systembench-era.sh 2023`) into roms/systembench, which `systembench:*` reads. It builds 845635c into roms/systembench-845635c and runs it into results/systembench-845635c (copied into the standing out dir) as a report with no checks.
- checks.tsv `systembench:*` source names 50f5066 + GCC 12.2 + the tie fix, with 845635c as a report. rows.tsv cites 50f5066 line numbers (845635c's less 15, verified on the table).
- Notes:
  - The four poll-row notes now say "runs the hardware-era build ... timed instructions are the same in every build measured (GCC 12.1, 12.2 and 16.2), its reading moves by at most 2 rclk across those builds and every boot delay ... One to three nops added to each poll step move the reading by up to 10 rclk (verify-83), so the check holds for that instruction sequence only."
  - This is stronger than verify-83's suggested "codegen-sensitive ±10" because the era build shows the codegen does not differ.
- README rewritten for the n64-systembench section: provenance, the tie bug, the objdump finding replacing "very likely the same", rambuf per build, C rows and seq.
- run.sh: with no boot-delay ROMs, `[ -f ] && echo` as the last command of the brace group made the pipeline fail under pipefail. It now uses `if`.
- Results, master to head:
  - systembench:u32r-banked fail -> consistent-only (134..135).
  - pi-dma-1024 stays pass (12185 -> 12170).
  - Values change on pi-dma-8 (190 -> 187), pi-dma-128 (1582 -> 1580), si-io-w (2151 -> 2150), si-io-r (1974 -> 1973) and u32r-seq (133 -> 134).
  - Row status counts unchanged: 69 pass / 33 fail / 1 consistent-only.
- No behavior value touched, no refit, no reorder. Edits to behaviors.tsv are confined to the note column of pi.io-busy, si.io-busy, si.write64 and si.write64-rom. Refs citing "@845635c main.c:NNN" were left, since they cite the same hardware numbers and editing them would collide with calib-kit-fix.

## Standing (before = PR #83 after run on the same master core, ~/n64-timing/results/systembench/after; after = mine)

- MM 600 `--stats` md5 9629185039701bddcdbd90c248a4f38b on both.
- nemu64 timing, cycle and cop0hazard `values.tsv`: byte-identical. thar0 compare.tsv, bench results.tsv and mmbench summary.tsv: byte-identical.
- det and stepcap PASS (MM 29 files / 8219 fields; nemu64 x3), round trip PASS, TMEM poke PASS, ctest 9/9.
- `--check` ok, self-test 50/0, lint ok, pidma 5/0, report.py 11/0.
- systembench era 2 consistent-only / 4 fail / 25 pass / 3 report; 845635c 1 / 6 / 24 / 3. Both byte-identical to standalone runs.
- Load 4.9 at start, 1.7 at end.
- MM wall time not re-timed (the core differs from master only in strings).

## Deviations

- I did not capture a separate "before" standing run on master. Before is PR #83's after run, whose core equals master's (#83 merged with no later core change). Every standing artifact compared byte-identical.
- I added a source edit to the era build (the tie fix). It is the honest comparison on a deterministic emulator; the unfixed build reads 9/8 or 49/48 high on tied rows. It can be switched off with ERA_TIE_FIX=0.
- A sibling script instead of a `--era` flag. The era build differs in toolchain source, libdragon source and padding anchor, so the two flows share little.
- There is a `2022` era (d12e8ea) beside `2023`. The checks use 2023, the only era commit with every row.

## Model-error candidates for a separate fix unit (numbers at the hardware-era code, era build on the fork vs hardware)

1. PI I/O W 130 vs 134 (-4), constant in 7 builds and 33 boot delays.
2. SI I/O W 2150 (2150..2151) vs 2158 (-8). 845635c reads -7.
3. SI DMA W ROM 2140 (2138..2140) vs 2144 (-4), 1/33 pass. SI DMA W RAM is exact (4065).
4. PI DMA 128 1580 vs 1591 (-11). These are pi.block-writeback fit data; the fit holds at the port phase median (-8) but not at the original's code.
5. PI DMA 8 187 (186..187) vs 193 (-6). This is independent, not fit.
6. U32R banked 134 (134..135) vs 136 (-2), now consistent-only.

The poll-row fix would re-solve pi.io-busy, si.io-busy and si.write64-rom so that this code's reading lands on the total. That is a fit (pref 21), so its independent check must come from elsewhere. verify-83's caution still holds: the reading depends on the poll-step instruction sequence. The era build only removes the compiler and layout as explanations.

## Follow-ups

- #16 calibration: a hardware run of the fixed 2023 era ROM (fd5ec6c0) gives a same-binary comparison for every row, including U32R rand. rambuf is at 0x800278c0 in its ELF.
- verify-80's joybus wording note (still open, untouched).
