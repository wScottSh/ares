# verify-66: PR #66 (labels-cpu cleanup), head fece75c6f, base 0c7fd2d25

## Verdict: PASS-WITH-NOTES. Recommend landing. No code change moves a value.

## 1. No behavior change (measured)
- Builds: ~/n64-timing/build/verify-66-{base,head} (worktrees ares-wt/verify-66, verify-66-base). ROMs: one romgen run from head; sha256 equal to the worker's (timing bd946fb1, cycle ae9c83aa, cop0hazard 9518d316).
- run-nemu64.sh both sides: timing 11/1604 (C6 1, C7 10), cycle 0/13, cop0hazard 0/5. `diff -r` of base vs head result trees: values.tsv, tests.tsv, frames.tsv, stdout.txt, failures.txt, categories.tsv identical. Only stderr/summary wall_s and ns_per_instruction differ (host noise); cpu_instructions and emulated_s equal (25760522 / 0.807370 timing).
- MM, n64-run --frames 600 --stats: both 601 lines, sha256 88f5e9b2...37ed5 identical (cmp clean). Load 16.1 / 13.9 at start (T11 host load).
- behaviors.hpp: only non-row line changed is the Basis enum (Inferred inserted before Fit). Normalized (id, value, unit with basis stripped) row lists hash-equal base vs head (md5 15b877c1...). Basis is used only in behaviors.hpp and behaviors.py; no C++ consumer, so the enum renumbering has no effect.

## 2. Requested items (verify-56, verify-61, verify-65 notes)
All addressed in the spec rows:
- ifill-stall: inferred, note states 45-47 range, joint 46, nemu64 ~43 is a comment, no asserting check. Honest. (I rederived 46 in verify-65; unchanged.)
- ldi COP2/LWC1/LDC1/BC1 inferred and unmeasured: noted. dcb: `pending:no-corpus` plus note. fpu-trivial: reference now lists implemented classes, fit + verify-is-fit.
- exc-fpu-detect: fit + verify-is-fit; to-L 2^53 upper bound stated; to-W 2^32 and from-L 2^55 "bracketed" matches my verify-61 table read.
- exc-ex: annotated, not split. Adequate: split needs two code constants. Weakness: the basis column still reads measured for the whole row; the note is the only guard. Acceptable.
- exceptions.cpp "one address check serves both" removed. pipeline.hpp 10% -> 11% (matches t7b 19.5 vs 21.6 s as I read it earlier).
- dfill-total: VI-off exactly 41, load-miss-vi-off expects 42.5 and fails, refresh stated as hypothesis. Matches verify-65 finding.
- cache-index-load-tag: I-cache writeback policy, 48 pclk drop stated. issue: fetch-fault issue slot stated, inferred; cpu.cpp:123-124 comment is accurate (step(CpuIssue) is at :118).
- fetch-ahead-slots into verify-is-fit with single-write moved to fit-from: sound. Single-write checks a store 1 and 2 ahead of the boundary, both expect the old value, which a 3-slot read also gives. That is reasoned (verify-65 read the ROM source and ran a readFirst=false mutation), not measured at 3 slots; I did not build a 3-slot variant (ring is two-slot, not a one-line change). Lint also demands this form.
- Not changed, and the worker lists them as follow-ups: cpu.fpu-convert (row text already says ROUND/TRUNC/CEIL/FLOOR assumed), cpu.rcp-register-read estimate. Neither was in the requested items except fpu-convert as a verify-56 aside. Note it stays measured.
- No row looks weaker or stronger than its evidence. Basis counts: measured 35, derived 5, inferred 1, fit 16 (fit-only label 14).

## 3. behaviors.py (measured)
- --check ok; --self-test rc 0, 20 ok lines incl. "an inferred row without its inference" ; lint-literals ok.
- Mutation: replaced the `basis == "inferred" and not row["note"]` guard with `if False:` in a scratch edit (restored; git status clean). --self-test then FAILED that case ("no error contains `inferred row ...`"), rc 1. The case detects what it claims.

## 4. Diff scope
Exactly the 8 files named (cpu/{cpu.cpp,decoder.cpp,exceptions.cpp,pipeline.hpp}, timing/{behaviors.tsv,behaviors.hpp}, docs/spec/n64-timing.md, tools/n64-timing/behaviors.py), 53+/40-. Comment edits (cpu.cpp, decoder.cpp x2, exceptions.cpp, pipeline.hpp) each state a why or an inference label; no narration. Worker skipped deslop/no-comments passes; I found nothing they would flag.

## Notes / not reproduced
- Spec and tsv notes are long (ifill-stall, fetch-ahead-slots); readable but dense. No fix needed.
- T11 merge: generated hpp/spec conflict is expected; resolve by regenerating (worker's note is right).
- Not rerun: MM wall comparison (worker's one-run each is not a perf claim; identical stats and zero code change make it moot). det/stepcap not rerun: no code change.
- No process of mine remains (builds and runs completed; ps shows none for verify-66).
