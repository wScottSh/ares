# labels-cpu report

Status: done. Branch feat/labels-cpu. Head fece75c6fcd472439b2100bf25261b9a4fd540df (pushed, equals origin). Base master 0c7fd2d25. PR https://github.com/wScottSh/ares/pull/66 (base master).

## Rows changed (before -> after basis)
- cpu.ifill-stall: derived -> inferred. Note: no asserting check (bench:ifill-isolated reports, no ROM). Research range 45-47. nemu64 "~43" is a source comment. The formulas read jointly with the 41 D-fill (40 = 7+x+M) give 46. 45 is the low corner.
- cpu.exc-fpu-detect: measured -> fit. fit-from cop1instructions32/64. verify-is-fit. To-L 2^53 is an upper bound (data 0.5 and 2^53 only). W 2^32 and from-L 2^55 are bracketed (per verify-61's table read).
- cpu.fpu-trivial: measured -> fit. fit-from and verify = cop1instructions32/64 (was 32 only). verify-is-fit. Reference lists the implemented classes: ADD/SUB/DIV 0,-0,Inf,NaN; MUL mantissa 0 (incl. power of two), Inf, NaN; SQRT 0,-0,Inf,NaN,negative; CVT.S/D from int 0. Unsampled class members are inferred.
- cpu.fetch-ahead-slots: fit -> fit. Now verify-is-fit. smc-single-write moves into fit-from. Lint rejects verify-is-fit next to an independent deciding check, and single-write passes for both 2 and 3.
- cpu.ldi: vendor -> vendor. Note added: COP2 rt-only and LWC1/LDC1 FPR result at LDI latency are inferred with no case; BC1 rt check vs GPR load unmeasured.
- cpu.dcb: vendor -> vendor. verify adds pending:no-corpus. Note: no case puts a cached access right after a cached store; cpu-register-dependency (384 pass) and Data cache Size (pass) only show the stall does not fire elsewhere.
- cpu.exc-ex: measured -> measured. Note: the measured basis covers Ov, traps, AdEL and TLBL only; AdES/TLBS/Mod inferred. Annotated, not split, because a split row needs a code change.
- cpu.dfill-total: measured -> measured. Note: with the VI off the model charges exactly 41, and load-miss-vi-off expects mean 42.5 and fails. The ~1.5 pclk tail is attributed to refresh off while the VI is off; that is a hypothesis.
- cpu.cache-index-load-tag: measured -> measured. Note: other CACHE ops costing only their issue slot is a policy, not a reference. I-cache Hit Write Back lost its 48 pclk under it and now costs its slot plus the write-buffer wait.
- cpu.issue: measured -> measured. Note: a fetch fault is charged the issue slot before the exception (T7d change, +1 pclk vs pre-T7d, confirmed by reading 1a6a9de57 cpu.cpp). Inferred; no test.

behaviors.py: new basis `inferred` (enum Inferred, between Derived and Fit; Basis has no C++ user outside behaviors.hpp). --check rule: an inferred row needs a note. Self-test case added.

Comments (no code change): exceptions.cpp rewords "one address check serves both" as an inference with no reference. pipeline.hpp 10% -> 11% (t7b.md: 19.5 vs 21.6 s). cpu.cpp: the fetch fault is charged the issue slot, inferred. decoder.cpp: LWC1/LDC1 LoadFt inferred, BC1 rt check unmeasured.

## Acceptance (all measured)
1. behaviors.py --check ok; --self-test rc 0 (20 ok lines incl. new case); lint-literals ok.
2. The spec regenerated. The basis table has an inferred row (1). The `fit only, no independent check` label count went from 11 to 14 (exc-fpu-detect, fpu-trivial, fetch-ahead-slots).
3. Byte-identical base vs head. nemu64 timing/cycle/cop0hazard values.tsv, stdout.txt, frames.tsv and tests.tsv are all identical. Failures on both sides: timing 11/1604, cycle 0/13, cop0hazard 0/5. MM 600-field --stats is identical (601 lines, emulated_s 10.634109 both). Builds: ~/n64-timing/build/labels-cpu-base (master 0c7fd2d25) and ~/n64-timing/build/labels-cpu. ROMs come from one romgen run at ~/n64-timing/results/labels-cpu/roms.
4. git diff origin/master touches only ares/n64/cpu/{cpu.cpp,decoder.cpp,exceptions.cpp,pipeline.hpp}, ares/n64/timing/{behaviors.tsv,behaviors.hpp}, docs/spec/n64-timing.md, tools/n64-timing/behaviors.py. No vi/ri/sysad/rdp row or dir. Row order is unchanged.

MM wall (one run each, back to back, not a perf claim): base 20.95 s at load 4.42, head 20.14 s at load 3.79. T11's mmbench det runs were live on the host.

Raw: ~/n64-timing/results/labels-cpu/{before,after}/ (results/nemu64/*, mm-stats.tsv, mm-stderr.txt, mm-load.txt).

## Deviations
- The brief names tools/n64-timing/behaviors.tsv. The table is at ares/n64/timing/behaviors.tsv. The generated behaviors.hpp changes with it.
- I-fill writeback and fetch-fault items are documented in the existing rows (cache-index-load-tag, issue) plus comments. I added no new rows.
- cpu.fetch-ahead-slots: smc-single-write went into fit-from to satisfy the lint rule (see above).
- Skipped deslop/no-comments subagent passes for time. The comment diff is 9 lines and was reviewed by hand. No independent review has run.

## Merge note for T11 (#63)
Generated files (behaviors.hpp enum and row table, spec basis-count table) will conflict textually with T11. Resolve by regenerating with behaviors.py after taking both tsv sides. The tsv rows themselves do not overlap.

## Follow-ups
- cpu.rcp-register-read is labeled measured but its value is 24 minus "about 2" of harness overhead, an estimated subtraction. Possibly derived or fit. Not changed.
- cpu.fpu-convert is measured while ROUND/TRUNC/CEIL/FLOOR are "assumed" (said in its reference). It could split or move to inferred.
- A romgen DCB case would decide cpu.dcb.
- An ifill-isolated ROM would decide 45 vs 46.

No background processes of mine remain. I removed the temp base worktree ares-wt/labels-cpu-base.
