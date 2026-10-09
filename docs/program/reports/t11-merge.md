# t11-merge: feat/t11 (PR #63) merged with master 0c7fd2d25 (T7d)

**Status:** done. No check that either parent passed breaks. Nothing was refit.
- Branch feat/t11, new head **020b1ce6dc897615bf7d5d01c4fa168f203c0158** (merge commit, pushed; feae47da8..020b1ce6d). PR https://github.com/wScottSh/ares/pull/63 (gh mergeable still UNKNOWN right after push).
- Worktree ares-wt/t11 was clean at feae47da8 before the merge.
- Builds: ~/n64-timing/build/t11-merge (merged head), ~/n64-timing/build/t11-merge-master (master 0c7fd2d25, worktree ares-wt/t11-merge-master, wall comparison only).
- Raw output: ~/n64-timing/results/t11-merge/{merged,wall,probe}. Drivers: standing.sh and wall.sh there (copied from verify-63b's).
- Parent numbers come from the verifiers' saved raw trees: master = ~/n64-timing/results/verify-65/head (tree 4be00e4a8, the same tree as master 0c7fd2d25, checked with git rev-parse); PR = ~/n64-timing/results/verify-63b/head (feae47da8). Diffs below are file-to-file, measured.

## Resolution
- The only conflict was docs/spec/n64-timing.md. I resolved it by running `python3 tools/n64-timing/behaviors.py` on the merged behaviors.tsv. The regenerated behaviors.hpp is byte-identical to git's auto-merge.
- behaviors.tsv has 142 rows and no duplicate ids. checks.tsv has no duplicate ids. T7d's rows are present: cpu.ifill-stall 45 and cpu.fetch-ahead-slots 2/fit, with both legacy I-fill rows gone. T11's rows are present: ri.overhead-vi 0, ri.overhead-write 0, sysad.rdram-(block-)write-period 11, and the 7 vi.* rows. `--check` ok, `--self-test` ok, lint-literals ok.
- Serialization: the merged SerializerVersion is "v153.9-vifetch" (T11's bump). It is newer than master's "v153.8-dma", so the bump also covers T7d's window[2]+head fields. The state round trip passes (below).
- Housekeeping slip: I ran `build.sh --help` once. The script has no help flag, so it started a build in the default dir ~/n64-timing/build/t11, and SIGPIPE from `head` killed it partway. That dir now holds a partial build of the merged tree. It does not affect any result here.

## Semantic interaction (I-fill path x T11 refit)
- **By construction (read from code and tsv):** IfillPath = cpu.ifill-stall − MeanEdgeWait − wire(Read, 4, CleanMiss). Its inputs are ri.read-hit, retry-clean, octbyte and request-latency, and T11 changes none of them. T11's 12→11 period refit and ri.overhead-write 1→0 reach only WritePath, BlockWritePath and the write trailer. So the uncontended I-fill stays 45 at a clean miss. T11 adds two things: VI bursts now contend with I-fills, and the I-cache Hit Write Back drain (32 B, BlockWritePath) gets 1 rclk cheaper.
- **Measured** with a scratch probe that records the cpu.clock delta from SysAD::fill entry to return, over 600 MM fields. It is not committed. The worktrees are ares-wt/t11-merge-probe-{master,merged} and the builds are build/t11-merge-probe-*. The probe changes no stats column: the cmp of fields.tsv against the unprobed run is identical.

| fill | master n / mean pclk | merged n / mean pclk |
|---|---|---|
| I-fill | 1,597,940 / 44.81 | 1,588,762 / **46.58** (+1.77) |
| D-fill | 2,593,987 / 45.73 | 2,590,320 / **47.31** (+1.57) |

  The histogram peaks stay at the same bins in both builds: 37-38 (row hit) and 45-46 (clean miss). Only the tail grows, which is VI contention. +1.77 pclk per I-fill matches verify-63b's non-preemptive FCFS estimate of about 1.8 pclk per CPU request. No check asserts I-fill latency (bench:ifill-isolated has no ROM), so this number is not verification.
- Effect on checks: nemu64:cycle (the SMC ordering tests that exercise I-fills) stays 0/13 with VI contention present.

## Standing set: raw numbers (master 0c7fd2d25 / PR feae47da8 / merged 020b1ce6d)

| Check | master | PR | merged |
|---|---|---|---|
| nemu64 timing failed | 11/1604 | 9/1604 | **9/1604** |
| nemu64 cycle failed | 0/13 | 7/13 | **0/13** |
| nemu64 cop0hazard failed | 0/5 | 0/5 | **0/5** |
| snapper | 2592/2592 | 2592/2592 | 2592/2592 |
| rdpstat (status/dpc/pixels) | 0/7 0/2 0/21 | same | same |
| thar0 | identical (merged vs both, wall lines stripped) | | |
| ctest incl. unit:rdram-private | 5/5 | 5/5 | 5/5 |
| behaviors --check / --self-test / lint | ok | ok | ok |
| det + stepcap nemu64 timing/cycle/cop0hazard | PASS | PASS | PASS (24/2/1 fields) |
| det + stepcap MM | PASS 27 files, 8146 fields | PASS 8177 | PASS 27 files, **8161** fields |
| state round trip 150/300/457 | PASS | PASS | PASS (600 fields) |
| TMEM poke | PASS field 31 | PASS field 31 | PASS field 31 |
| bench fail/pass/report | 10/11/19 | 8/13/19 | **8/13/19** |
| memset uncached pclk/SD (hw 18.38) | 18.277 | 17.717 | 17.718 |
| memset cached pclk/line (hw 71.24) | 71.011 | 72.744 | 72.737 |
| rspdma B/rclk (hw 6.5) | 6.473 fail | 6.499 pass | 6.501 pass |
| sp-dma wr-4096-off0 B/rclk (report) | 6.495 | 6.334 | **6.169** |
| dirty-miss-isolated dirty-single pclk | 48 | 46 | 46 |
| uncached-vs-hpos bank5 median | 36 | 36.0 | **34** |
| pi-dma cart-to-ram-8 rclk (hw 193) | 196.0 fail | 197.33 fail | 196.0 fail |
| MM vi_share / refresh_share | n/a | 0.0696 / 0.0125 | 0.0695 / 0.0125 |
| MM vi / refresh rclk per line | n/a | 293.39 / 52.64 | 293.22 / 52.61 |
| MM vi_tear fields | n/a | 0 | **0** |
| MM cpu_wait_rclk (600 f) | 7,278,044 | 12,812,593 | 12,979,360 |
| MM cpu_instructions (600 f) | 748,005,376 | n/a | 741,874,903 |

The nemu64 failing set equals the PR's set exactly: C7 Load Miss VI off x8 plus C6 20.0 same-bank uncached VI on (mean). values.tsv for timing is identical to the PR's. Against master, 18.0 and 18.1 Load Miss VI on go fail → pass. cycle and cop0hazard values.tsv are identical to master's.

## Values that differ from what a parent predicts, and why
- **20.0 same-bank mean:** PR 0xa2a0 = 41.600, merged 0xa2d6 = 41.686 (band 36.3 ± 4; it fails in both). The value is measured. The cause is a guess: T7d's cheaper boot I-fills shift where the loop sits in VI phase. I did not trace it.
- **C7 VI off 80400000:** PR 41001, merged 41000. This is the same 41001→41000 move T7d made on master (verify-65). The other seven are 41000 in all three builds.
- **MM fields 8161** sits between master's 8146 and the PR's 8177. Measured mmbench window starts (master / PR / merged): title 249/252/251, filesel 440/443/442, filesel-named 893/899/895, filesel-options 615/620/617, filesel-rotate 603/608/605, sct 304/308/307, field 322/327/324. T7d moves the windows earlier and T11 moves them later, so this is consistent. All 7 scenes reach their windows.
- **sp-dma wr-4096 (report row, single shot):** The 4096-byte write totals across all three builds take only the values 630.67, 646.67, 664.0 and 681.33 rclk, steps of about 16.7 rclk. That fits 0-3 VI bursts landing inside the DMA (the quantization is measured; the reading of the steps as VI bursts is inferred). The merge only reshuffles which offset catches how many bursts. off0 646.67→664.0 (6.334→6.169), off7c0 664.0→630.67 (6.169→6.495), and off7f8 stays 681.33 (6.012). This is phase noise, not a model change. The off0 row follows that noise and is not a measure of accuracy.
- **uncached-vs-hpos bank5 median** goes 36 → 34 (report row, no band). It moves with VI phase the same way (inferred). Several dirty-miss-isolated and dirty-row-sweep min/max cells also move. Those are report-only distribution extremes, and every check-kind status is identical to the PR's.
- **rspdma** 6.499 → 6.501, memset cached 72.744 → 72.737, pi cart-to-ram-8 197.33 → 196.0 (master's value, from T7d). All are small, and every status equals the PR's.

## MM 600-field wall (interleaved, 4 pairs, load 1.16-1.65)
- master 20.112 20.009 20.113 20.093 (median 20.10 s).
- merged 21.280 21.159 21.140 21.178 (median 21.17 s), **+5.3%**, above master in 4/4 pairs.
- ns/instruction goes 26.89 → 28.68, while emulated instructions go −0.8% (748.0 M → 741.9 M). So the cost is per-instruction host work from VI fetch modeling, not extra emulated work. verify-63b measured T11 alone at +4.2% against its base. This stays well under the 2-minute budget.

## Not done / caveats
- I did not rerun the C6 cause attribution or the verify-63b tear mutant. vi_tear is 0, and the counter was proven by mutation in verify-63b.
- The probe numbers come from a patched scratch build. They show the I-fill cost under contention, and no asserted check covers it.

## Housekeeping
- No process of mine is running (pgrep empty).
- Scratch for the coordinator to prune: worktrees ares-wt/t11-merge-master (clean, detached) and ares-wt/t11-merge-probe-{master,merged} (dirty probe patches, detached, never committed). Builds build/t11-merge-master, build/t11-merge-probe-*, and the partial build/t11.
