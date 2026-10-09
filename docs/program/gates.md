# Gates

## land-stack

- Status: resolved
- Question: Merging PRs is blocked for agents (classifier: Merge Without Review). Land the stacked PRs yourself, bottom up, starting at #30?
- Options: land them as they verify | add a permission rule letting the coordinator merge verified PRs
- Default: stack keeps growing on branches; nothing reaches master until you land it
- Answer: Scott added allow rule Bash(gh pr merge:*) via /permissions (2026-10-05); coordinator lands verified PRs

## build-corpora

- Status: resolved
- Question: Building test ROMs from external source (nemu64-test via cargo, libdragon-based n64-systembench / Thar0 RDP-Timing-Tests) was blocked for agents (classifier: Code from External). Run tools/n64-timing/build-nemu64.sh yourself, or allow it?
- Options: run it yourself | allow agents to build external test ROMs | skip these corpora
- Default: verify with MM, prebuilt ROMs (pi_dma_test, hydra rdp tests, bigbass timing) and in-repo checks; behaviors whose only check is these corpora are marked verification-pending
- Answer: default taken: corpora ported into in-repo romgen (nemu64, Thar0, systemtest, repeater64, snapper64); n64-systembench numbers used as cited values only

## tools-bench

- Status: resolved
- Question: Map #1 lists 'point tools/bench at the fork and remove the func_80173B48 pin'. mm-decomp-60fps tools/bench is untracked, runs stock ares from PATH, and its BENCH build still pins func_80173B48. The fork's own mmbench (tools/n64-timing/mmbench) already runs the retail ROM unpinned and carries the acceptance checks. Do it, or retire tools/bench in favor of mmbench?
- Options: port tools/bench to the fork and drop the pin | retire it; mmbench is the bench of record
- Default: retire it: mmbench is the bench of record; the closure draft reports the item as not done until you rule
- Answer: port tools/bench to the fork and drop the pin (Scott, 2026-10-09, verbatim: "do the first two, skip 16 for now. Just make sure it's comprehensive once I have hardware to compare against.")

## systembench-build

- Status: resolved
- Question: To compare bench numbers with hardware point by point (instead of 'consistent-with' over a poll-phase range), we need the original n64-systembench ROM built with the libdragon toolchain and run in the fork. Building external code is blocked for agents (gate build-corpora). Allow an agent to install libdragon and build rasky/n64-systembench @845635c, or build it yourself?
- Options: allow agents to build it | you build it and drop the .z64 in ~/n64-timing/roms | skip; keep consistent-with labels
- Default: skip: consistent-with labels stay, with the mean verdict printed beside them
- Answer: allow agents to build it (Scott, 2026-10-09, verbatim: "do the first two, skip 16 for now. Just make sure it's comprehensive once I have hardware to compare against.")

## mm-bench-merge

- Status: open
- Question: wScottSh/mm-decomp-60fps#1 (bench on the fork, pin removed) passed verify-mm1. It commits your uncommitted bench harness to main, which will clash with your local uncommitted copy. Merge it yourself when ready (then the map #1 tools/bench row reads done)?
- Options: you merge it | coordinator merges it | leave open
- Default: leave open for you; coordinator does not merge in your decomp repo
