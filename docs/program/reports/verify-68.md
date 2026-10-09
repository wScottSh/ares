## Verification of PR #68 (T14 noise LFSR), head 8fdf76eb5, base e096b194a

**Verdict: PASS-WITH-NOTES.** Independent rebuild of base and head (own worktrees, private N64_TIMING_HOME, ROMs rebuilt from head romgen). Every claim in the worker report that I rechecked reproduced.

### 1. ctest and test strength
- ctest head 9/9 (unit:noise-lfsr, noise:a, noise:b, noise:c included); base 5/5.
- noise:a and noise:b assert all 1016 pixels equal the LFSR output from power-on at clock 256,586,636, and that clock+1 (a) / clock-1 (b) gives >300 mismatches. noise:c: for each of four sets the test requires a == hidden mask at every pixel (a=1 exactly where c is `x`), then c == every known bit (~520 per set) at the same clock, c being one step ahead by construction.
- Circularity: the four clock constants were found from a's hidden mask only, never from c. c is then an independent prediction with ~520 known bits per set and 0 mismatches (chance ~2^-520 each). The only free parameter c has, its reset phase relative to a, is tested: with `rdpClock` instead of `rdpClock + 1` I get 259+ mismatches per set. noise:c is strong for c's polynomial and reset phase. It does not test c in the stepping path (at() uses jump() for each capture start, then steps up to 64), but unit:noise-lfsr checks jump == stepping at 10 clocks. Weakness to note: the c clocks are hardcoded constants (found by a), so the test does not re-derive them.
- Mutants (own build, header-only edit of rdp/timed.hpp in a scratch worktree): (1) a tap x^2 -> x^3 : unit 1 fail, dataset-a 1 fail, dataset-c 4 fail, dataset-b 0 (b untouched, as expected). (2) skipped step in at()'s stepping loop at clock 256,586,636+500: dataset-a 2 fail, dataset-b 1 fail. (3) c reset without +1: unit 1 fail, dataset-c 4 fail (259 known pixels differ in C3). All caught.

### 2. Provenance and license
Header of noise-datasets.hpp, import-noise-datasets.py, romgen/suites/noise/README.md, spec and checks.tsv all record Thar0/RDP-Noise e7f6c7f `rdp_noise_lfsr.c`, Unlicense. docs/research/hardware-corpora.md row 7 records that the repo has no LICENSE file and the source file's header is Unlicense. Unlicense is public domain, compatible with ares ISC (pref 9). The import script only does `Path.read_text()` plus regex; nothing from the clone runs. Datasets are data, no code imported. No ROM or SDK binaries added.

### 3. noise:rect-1016 ROM
ROM sha256 4c23f2bf2907677c21fff015e4e19c7c9adf9bd1ce40c82d58fdfe2a22324ee7 (matches worker). Head: pass, 0 failures, first pixel at RDP clock 10,819,771, output bits sha256 identical across two runs (3008d276...). Base runner: FAIL (a 475, b 535, c 299 mismatches), identical bits across two runs (e01c5db2...). The absolute offset to dataset A (245,766,865 clocks) is printed only, not asserted: confirmed in `rect()` in noise-lfsr.cpp, which derives `first` from the ROM's own a bits and asserts only one clock per pixel. The open row `rdp.noise-pixel-offset` stays model-choice.

### 4. hydra:noise
Not run (ROMs absent). The spec/checks.tsv have no hydra:noise row marked passed. The plan's T14 check item "hydra:noise renders and is deterministic" is therefore still open; recorded as pending in the worker report. Not a pass.

### 5. Model-choice labels
`rdp.noise-alpha-dither` (model-choice, cites Angrylion combiner.c:263-285, records MiSTer conflict, check pending:no-corpus), `rdp.noise-dither-bits` (model-choice, G_CD_NOISE / G_AC_DITHER source, pending:no-corpus), `rdp.noise-pixel-offset` note (2-cycle samples first clock; span start rounded up to an rclk edge). Spec counts model-choice 19 -> 21, consistent. Labeled honestly.

### 6. Standing (base vs head, own runs)
- nemu64: Timing 9/1604, Cycle 0/13, CP0 0/5 on both; tests.tsv cmp identical for all three sets.
- rdpstat 0/7, 0/2, 0/21, 1prim 2/4 on both, output identical. bench: fail 7 / pass 14 / report 19, rows identical. thar0 100/100 identical. snapper 2592/2592 on head (sum of match lines), output identical to base.
- det and stepcap PASS on both: nemu64 x3 and MM (27 files, 8219 fields). Round trip at 150/300/457 PASS, TMEM poke PASS.
- behaviors --check, --self-test, lint-literals ok. mem_misses=0 in 28 reported lines.
- MM scene comparison (det-mm run1, every tsv, columns other than fb_hash/trace_hash): fb_hash differs only in title 621/852, filesel 362/1043, filesel-named 362/1510, filesel-options 362/1220, filesel-rotate 362/1764; power-on 600 fields: 369/600 (plain, roundtrip, poke). sct and field: 0 fb_hash diffs. Every other column (cpu_cycles, rsp_busy, dpc_start/end, origin, cimg, zimg, rdp_pixels) identical in all scenes including fields.tsv (4757 rows) and gframes.tsv. rdp.txt differs only in wall-time/ns fields (render_calls and pixels equal). trace_hash differs on all rows (serializer layout and version).
- The worker's counting build showing only G_CD_NOISE / G_AD_NOISE run in title and filesel was not re-run by me (inference from the data above: fb_hash-only change in those scenes is consistent with it). Wall time was not re-measured by me.

### 7. Merge with PR #69 (feat/t15 57f995de7)
`git merge-tree --write-tree` of origin/feat/t14 and origin/feat/t15: clean, no textual conflicts (tree 1e4c0d02e). I also merged locally in a scratch worktree (not pushed): builds, ctest 9/9, behaviors --check and lint ok, noise:rect-1016 pass with identical first pixel (10,819,771). Semantic points: T15 deletes nothing T14 uses; T15 only still contained the pre-existing `rdp_seeded_noise`/`m_primitive_offset` references that T14 removes, and those sites were not touched by T15, so the merge drops them cleanly. T15 changes `dispatch()` (`pipe.time` advance), which changes when spans start; T14's noise clock is computed from `start` inside `startSpan`, so it follows automatically. T15 does not touch serialization.cpp or add RDP_STATE lines, so only T14 bumps SerializerVersion (v153.11-noise); no double bump. `rdp_render_init` gains a parameter in T15; engine.cpp merged cleanly.

### Diff notes
- Scope is as stated; comments are why-comments with references. Nit: `rdp_noise` is a mutable global function pointer in the engine and `m_noise_clock/step` are unserialized (safe because spans run immediately after startSpan; round trip passes).
- Open items (not blockers): hydra:noise pending; 2-cycle sampling clock, dither bit sources, and pixel offset remain model choices needing calibration.

Raw output: ~/n64-timing/results/verify-68/{before,after,noise-*}.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
