# cop0order report

Status: done. Branch feat/cop0order. Head 0df9ede75. PR https://github.com/wScottSh/ares/pull/64 (base master).

## Change
tools/n64-timing/romgen/suites/nemu64/cop0hazard.py: new step `step_compare_past_effect` (mfc0 count; addiu -2; mtc0 compare), the port of Compare (past)'s set_compare(count()-2) (cop0/compare.rs:206-209). It runs as the first step of the first SW test, SoftwareInterrupt1 (enabled, hazard). The comment cites testlist.rs:588-591 and :740-750. romgen/README.md gets a port note. The test count stays 5.
checks.tsv and behaviors.tsv are unchanged. No row said the softwareinterrupt check stays red.

## Acceptance (all measured; raw output in ~/n64-timing/results/cop0order/)
1. Master emulator (a1c92f1b9, build/cop0order) with the new ROM: `CP0-hazards: Failed 0 of 5 tests`. With the old ROM: Failed 2 of 5, both `a=0x8100 b=0x100. Cause` (run-head-before, run-head-after1).
2. Pre-T7c emulator (a86d40886, my own build at build/cop0order-base) with the new ROM: `Failed 5 of 5`. Read early: a=0x1f b=0x1d. COUNT hazards: Second readback a=0x1 b=0x0. SW1 hazard: ExceptPC a=0x800013c8 b=0x800013cc. Instantly: unexpected Int. SW12: ExceptPC off by 4. The SW cases now fail on timing, not Cause. Old ROM on the same emulator: also 5/5 fail (run-base-*).
3. sha256 over all 48 files from all 5 suites (nemu64, bench, thar0, rdpstat, snapper), before vs after: only nemu64-cop0hazard.z64 differs (5ef4ed47... -> 9518d316...). Files: sha-before.txt, sha-after1.txt.
4. Determinism: built twice after the change. sha-after1.txt and sha-after2.txt are identical (cmp).
5. timing (Failed 11 of 1604, C6 x1, C7 x10) and cycle (Failed 7 of 13): values.tsv is cmp-identical between the old and new ROM sets on the master emulator. summary.txt differs only in wall_s.

## Deviations
- The scope asked for upstream's own inter-test state. I replayed only the effect of the last Compare write. I did not port the three Compare tests. They are Level BasicFunctionality/Timing, not part of this set, and they would change the test count from 5. Their final CP0 effect is this one write (inferred from reading the source: upstream calls set_compare only in the compare tests, per verify-62). Count also advances during those tests, but no SW test reads Count.
- Each run-nemu64.sh run used a private N64_TIMING_HOME under results/cop0order/run-* so that it did not overwrite the shared ~/n64-timing/roms and results/nemu64.

## Follow-ups
None. The temporary base worktree has been removed. Build dir ~/n64-timing/build/cop0order-base remains.
