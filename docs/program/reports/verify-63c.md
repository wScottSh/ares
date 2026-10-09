# verify-63c: PR #63 merged head 020b1ce6d vs master 0c7fd2d25

Verdict: PASS-WITH-NOTES. Comment: https://github.com/wScottSh/ares/pull/63#issuecomment-6057125320

Worktrees ares-wt/verify-63c{,-base}; builds build/verify-63c-{head,base}; raw ~/n64-timing/results/verify-63c/{head,base,wall}; drivers standing.sh, wall.sh there. No process of mine remains (pgrep checked).

**Merge resolution (measured)**
- `behaviors.py` run on the head tree changes nothing (git status clean): docs/spec/n64-timing.md and behaviors.hpp equal the generator output. 142 rows, no duplicate ids. T7d rows present (cpu.ifill-stall 45, cpu.fetch-ahead-slots 2), T11 rows present (ri.overhead-vi/write 0, sysad.rdram-(block-)write-period 11, 7 vi.* rows).
- SerializerVersion is "v153.9-vifetch"; Pipeline::serialize writes window[].{vaddr,word,translated} and head (pipeline.cpp:179-180). State round trip PASS, 600 fields byte-identical, saves/loads at 150/300/457. TMEM poke first differs at field 31.

**Standing set (base / head)**
| check | master | merged head |
|---|---|---|
| nemu64 timing failed | 11/1604 | 9/1604 (C7 VI-off x8 + 20.0 mean) |
| cycle / cop0hazard | 0/13, 0/5 | 0/13, 0/5 (values.tsv identical to master) |
| snapper | 2592/2592 | 2592/2592 |
| rdpstat | 0/7 0/2 0/21 | same |
| thar0 | identical (wall lines stripped) | |
| ctest | 5/5 | 5/5 incl. unit:rdram-private |
| behaviors --check / --self-test / lint | ok | ok |
| determinism + stepcap nemu64 | PASS | PASS (24/2/1 fields) |
| determinism + stepcap MM | PASS 8146 fields | PASS 8161 fields (27 files) |
| bench fail/pass | 10/11 | 8/13 |
| memset uncached (hw 18.38) | 18.277 | 17.718 |
| memset cached (hw 71.24) | 71.011 | 72.737 |
| rspdma (hw 6.5) | 6.473 | 6.501 |

MM 600 fields, head: vi_share 0.0695, refresh_share 0.0125, vi_rclk_per_line 293.22, vi_tear fields 0.

**MM wall (4 interleaved pairs, load 1.06-1.26):** master 20.093 20.038 20.080 20.752 (median 20.09 s); merged 21.323 21.145 21.197 21.317 (median 21.26 s). +5.8%, merged above master 4/4. Under the 2 min budget. (Worker: +5.3%.)

**sp-dma wr-4096-off0 6.334 -> 6.169.** The totals are on a lattice, but the lattice is not VI bursts. The poll-only row in master has rclk 22.67, and master's small DMA totals run 22.67, 40.0, 57.33, 74.67, 92.0, 109.33 (steps of 17.33 rclk = 26 pclk) with no VI fetch on the bus. That step is the CPU status-poll loop period, which the bench cannot resolve past. So the worker's reading of the 16.7 rclk steps as VI bursts is not supported. What the data does support: the true DMA end moved by less than one poll period, and which side of a poll boundary it lands on depends on VI/refresh phase. Head rows: off0 664.0, off7c0 630.67, off7f8 681.33 (master 630.67, 646.67, 646.67); head's off7c0 reps span min 473 to max 537 (5 poll steps), so contention does vary by rep. No hardware value exists for these offsets; only off0 is asserted (6.5), and it fails in the PR and merge alike. Not a merge regression: all check statuses equal the PR's. Not isolated by experiment.

**Notes.** (1) The 20.0 same-bank mean cause (41.600 -> 41.686) is an untraced guess of the worker. (2) The sp-dma wr-4096-off0 failing band is inherited from verify-63b.

Nothing either parent passed breaks.


Judgment on item 3: worker's 'VI-burst phase quantization' is half right. Quantization and phase-dependence are real; the 16.7 rclk lattice is the CPU poll-loop period (master, with no VI fetch, has the same lattice: poll 22.67, then 40/57.33/74.67/92/109.33), so the steps are not VI burst lengths. Cause of the off0 move is phase of VI/refresh vs a poll boundary (inferred, not isolated by experiment).
Not reproduced/not run: worker's scratch I-fill probe (+1.77 pclk), MM window starts, 20.0 cause attribution, tear mutant (verify-63b did it).
Housekeeping: stray build-head.log initially written into worktree verify-63c, moved out; worktree clean.
