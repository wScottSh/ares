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
