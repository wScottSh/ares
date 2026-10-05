# Stack report: land T1-T4, T9, T10

Status: done. Branch feat/stack, head 2564f6931. PR: https://github.com/wScottSh/ares/pull/45 (base master, open, not merged). GitHub reports it MERGEABLE/CLEAN. No CI checks ran: the fork has never run an Actions workflow (`gh run list` is empty for the whole repo), so "every check" means the local checks below.

## Commits
- aad1304a8 (previous agent): origin/master merged into origin/feat/t4. No conflicts.
- b5fa49fef: origin/feat/t10 merged. The previous agent had resolved the 4 files' content but had not staged them. I checked each against both sides before committing:
  - system/serialization.cpp: T4 had v153.1-clock750 and T10 had v153.2. The merge uses the new version v153.3-clock750.
  - vi/vi.cpp: T4's VclkAccumulator step, main and power (`vclk = {system.vclkPeriod()};`), plus T10's removal of all Vulkan blocks. vi.hpp has no clockFraction or gpuOutputValid left.
  - behaviors.tsv: T4's side. T10 only moved line numbers. Then `behaviors.py --fix-lines` rewrote 3 refs, and `behaviors.py` regenerated behaviors.hpp and the spec.
  - Afterwards: `clock-rebase.py --check` reported 0 to rewrite and 0 by hand. `lint-literals.py` ok. `behaviors.py --self-test --check` ok.
- 2564f6931: a semantic conflict that git did not flag. T1 removed n64-run's `--cpu` flag, and T10 removed its `--rdp` flag. The tools-lane runners (bench/run.sh, rdpstat/run.sh, run-thar0.sh) still passed them, so n64-run rejected every suite run. The runners now drop the flags, their output directories lose the -<cpu>/-<rdp> suffix, and the 4 READMEs are updated. This is outside a pure conflict resolution, but the suites could not run without it. n64-run has neither flag, and mmbench never passed them.

## Verification (measured; build C:\Users\Scott\n64-timing\build\stack; outputs C:\Users\Scott\n64-timing\results\stack\)
- nemu64 (romgen ROMs built into results\stack\home\roms): 922/1604, 9/13, 5/5 failed. values.tsv and tests.tsv are byte-identical to t4\after for all 3 sets.
- determinism.sh MM: PASS, 17 files byte-identical, 3807 fields with trace_hash.
- state-roundtrip.sh: PASS (round trip 600 fields; TMEM poke first diff at field 31, trace_hash only, on every later field), with 0 failed steps. The first attempt used OUT=/c/... and every save-state failed, because the native exe can't open an MSYS path in a script file. Rerun with OUT=C:/...; T10's runs must use a Windows path too.
- mmbench 4 scenes (det/run1): fields.tsv 2400 rows and gframes.tsv 1045 rows match T4 in every column, cpu_cycles and rsp_busy_clocks included. Per-scene stats cpu_cycles, rsp_busy_clocks, dpc_end, origin, cimg and zimg match T4 in every field. fb_hash distinct counts are filesel 637, sct 326, field 326, title 324 (T4 3 each; T10 the same as here), so pixels come from the software engine.
- MM 600 fields: every timing column matches t4\after\mm600.tsv. fb_hash matches T10 in 600/600 fields (234 distinct). trace_hash differs from T4 in 600/600, as expected because the engine state is in the hash. 3 runs share md5 492beb09135556ae151b464927d6368b.
- rdpstat: systemtest 0/7, repeater64 0/21, dpc 2/2 failed (expected; T12).
- thar0: 100/100 specs reported. The model is -1 on every spec, the same as the tools-lane result (no RDP timing yet).
- bench: 13/13 ROMs exit through emux-exit. pass 2, fail 19, report 19, the same counts as tools-integrate.
- snapper: skipped. #42 (feat/r3) is not on master.
- MM 600-field wall time: 11.16, 11.07, 10.86 s, sequential on a shared host. Engine render took 1.67-1.72 s of each (18.7-19.2 ns/px). T4 without pixels had a minimum of 8.84 s, so the gap is roughly the render time (inferred).

## Notes
- clock-rebase.py SKIP still lists ares/n64/vulkan/parallel-rdp/, which no longer exists. The entry is harmless dead config, and I left it because it is outside conflict scope.
- All included PRs (#32 #36 #40 #44 #35 #43) have heads that are ancestors of feat/stack.
