# verify-66b: PR #66 (labels-cpu) head 6fe477d2b vs master 4b6aa6a42

## Verdict: PASS. Zero behavior change vs master. Recommend landing.

## 1. Static (measured)
- Worktrees ares-wt/verify-66b (head), verify-66b-base (4b6aa6a42). Regenerating with `behaviors.py` on the head tree: `git status` clean (hpp + docs/spec/n64-timing.md equal generator output). `behaviors.py --check` ok.
- Duplicate ids in behaviors.tsv: 0.
- tsv diff vs master: 10 rows -/+ (cpu.cache-index-load-tag, dcb, dfill-total, exc-ex, exc-fpu-detect, fetch-ahead-slots, fpu-trivial, ifill-stall, issue, ldi). Nothing else.
- Diff vs master: 8 files, 53+/40-: cpu.cpp, decoder.cpp, exceptions.cpp, pipeline.hpp (read every +/- line: comments only, no code token changed), behaviors.{tsv,hpp}, spec, behaviors.py (Inferred basis + guard + self-test case). hpp non-cpu change: Basis enum only (Inferred inserted; no C++ consumer, as verify-66).
- `--self-test` rc 0 (all ok), lint-literals ok.

## 2. Runtime base vs head (measured)
- Builds: build.sh exit 0 both: ~/n64-timing/build/verify-66b-{base,head}. Runners cp'd to fresh files before running (pref 26).
- ROMs rebuilt privately per side with romgen into N64_TIMING_HOME=~/n64-timing/results/verify-66b/{base,head}; sha256 identical across sides: timing bd946fb1..., cycle ae9c83aa..., cop0hazard 9518d316... (as expected).
- run-nemu64.sh: timing 9/1604 failed, cycle 0/13, cop0hazard 0/5, both sides. values.tsv cmp identical x3 (timing sha 776f8ac4f70e7c58..., cycle f6783157d1c93e63..., cop0hazard d0282a9b2bb6b252...).
- MM `n64-run baserom.z64 --frames 600 --stats`: 601 lines both, sha256 86f33a7f7e627109a053008751ab1a697532b4214b1bb8b096098fd43fe23f59, cmp identical (equals labels-merge's hash).
- Raw: ~/n64-timing/results/verify-66b/{base,head}/. Load ~5.6 at end. Wall times not compared (no perf claim).

## Not reproduced / not run
- Nothing from labels-merge.md contradicted. Wall-time anomaly not investigated. det/stepcap/state-roundtrip not rerun (no code change).
- No processes of mine remain.
