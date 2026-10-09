# labels-merge report

Status: done. Branch feat/labels-cpu, PR https://github.com/wScottSh/ares/pull/66.
New head: 6fe477d2bf30bf8e7346e6731d9d0b1e3f6c727f (merge commit, parents fece75c6f + 4b6aa6a42). Pushed fece75c6f..6fe477d2b, no force. gh reports PR #66 headRefOid = 6fe477d2b (mergeable UNKNOWN at query time, GitHub still computing).

## Merge resolution
- `git merge --no-edit origin/master`: behaviors.tsv, behaviors.hpp, behaviors.py auto-merged; only docs/spec/n64-timing.md conflicted.
- behaviors.tsv: 0 conflict markers; both sides present. Took master's spec side as a placeholder, then regenerated hpp + spec with `python3 tools/n64-timing/behaviors.py` (no hand edits).
- Duplicate ids: `cut -f1 behaviors.tsv | sort | uniq -d` -> none.
- Diff merged tsv vs master: only the 10 cpu rows #66 relabels (dfill-total, ifill-stall->inferred, ldi, dcb, exc-ex, exc-fpu-detect->fit, fpu-trivial->fit, issue, cache-index-load-tag, fetch-ahead-slots). So every T11 row is intact.
- Diff merged tsv vs fece75c6f: T11's rows (ri.overhead-vi/write/rdp, sysad.rdram-(block-)write-period 11, vi.burst, vi.vclk-per-pixel, vi.register-sample, vi.fetch-overrun, vi.unfetched-sample, vi.aa-mode-lines, vi.display-window) present.
- Code diff vs master (`git diff origin/master HEAD`): cpu.cpp, decoder.cpp, exceptions.cpp, pipeline.hpp are comment-only; plus behaviors.{tsv,hpp}, spec, behaviors.py (Inferred basis).

## Zero behavior change vs master 4b6aa6a42 (measured)
Builds: head = worktree -> /home/wscottsh/n64-timing/build/labels-merge; master = `git archive 4b6aa6a42` to /home/wscottsh/n64-timing/scratch-labels-merge/master-src -> /home/wscottsh/n64-timing/build/labels-merge-master. Both build.sh exit 0, RelWithDebInfo g++ -O2.
- run-nemu64.sh (own N64_TIMING_HOME per side, shared romgen ROMs), values.tsv cmp identical: timing (sha256 776f8ac4f70e7c58...), cycle (f6783157d1c93e63...), cop0hazard (1c47580e70039f45...). Summaries equal minus wall_s: timing 9/1604 failed (C6 1, C7 8), cycle 0/13, cop0hazard 2/5 on both sides. (verify-66 saw timing 11/1604, cop0hazard 0/5 on its pre-T11 base; I did not investigate the delta, it is master's and equal both sides.)
- MM `n64-run baserom.z64 --frames 600 --stats`: 601 lines both, sha256 86f33a7f7e627109a053008751ab1a697532b4214b1bb8b096098fd43fe23f59 both, cmp clean (rerun also identical).
- behaviors.hpp row (id, value, unit) lists: 141 rows each, cmp identical to master's.
- Object code: objdump -d of all 30 n64/tool .o files identical between the two builds; linked .text same address and size, only rodata string offsets differ (+0x40 rodata).
- behaviors.py --check: ok. --self-test: ok (all cases). lint-literals.py: ok.
- Raw outputs: /home/wscottsh/n64-timing/scratch-labels-merge/{master,head}/ (results/nemu64, mm-stats.tsv, load.txt), build logs build-{head,master}.log.

## MM wall time: anomaly, not a code effect (measured)
- Interleaved 600-frame: master 21.57 s / head 34.31 s (load 7.3 / 5.6); rerun head 34.14 / master 21.61 (load 2.3 / 1.8); 4-way: labels-cpu 21.33, labels-cpu-base 20.65, labels-merge 30.78, labels-merge-master 17.97.
- Byte-identical copy (cmp) of the head binary: 17.97 / 18.12 s, vs master copy 18.46 / 18.08. Same-dir, same-length-name copy (rundir/bin/n64-rux) 200 frames: 5.64 s user vs original n64-run 9.78 s. Same-length path elsewhere: fast. Env padding: no effect. Syscall profile (strace -c) equal.
- Conclusion: the slowdown follows the original file instance, not its bytes, path, or the code (identical object code). Cause unproven; guess = page-cache/file-backed text placement (e.g. THP) of the linker-written file. Follow-up for coordinator: MM wall comparisons across units can be skewed ~1.7x by this; time a fresh `cp` of each runner, or interleave several runs, before attributing a wall delta to code.

## Housekeeping
- No processes of mine left running (pgrep shows only the query shell). Temp copies in scratch-labels-merge/{swap,L}; n64-rux removed.
- Not done: determinism/stepcap/state-roundtrip not rerun (no code change, identical outputs).
