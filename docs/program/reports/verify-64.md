# verify-64 report

Verdict: PASS. PR comment: https://github.com/wScottSh/ares/pull/64#issuecomment-6054754695

Head 0df9ede75cb748ae346ce0603e22eca9beae64b2, base a1c92f1b9 (merge-base = master). Independent builds: master emulator `build/verify-64-head`, pre-T7c emulator a86d40886 `build/verify-64-pre`; private N64_TIMING_HOME per run under `results/verify-64/home-*`. Everything below measured.

**Upstream fidelity (nemu64-test clone, read only).** `src/tests/testlist.rs:588` CountHazards, `:589-591` the three Compare tests, `:740-750` the SW interrupt tests. Compare (past) ends `set_compare(target)` with target = count-2 (`src/tests/cop0/compare.rs:206-209`). Upstream's only other Compare writes are the other two Compare tests (`compare.rs:38`, run earlier); `set_compare` has no callers outside `src/tests/cop0/compare.rs`. So the last Compare write before the SW tests is Compare (past)'s; replaying it is faithful for IP7. Not replayed (inferred harmless, test passes): the Compare tests' `preset_cause_to_copindex2` Cause.CE=2 residue and the other tests between :592 and :740 (icache tag, reserved-COP). Citation paths in the comment drop the `src/tests/` prefix; line numbers are right.

**Behavior.**
| ROM | emulator | result |
|---|---|---|
| new | master | `CP0-hazards: Failed 0 of 5` |
| old (base romgen) | master | `Failed 2 of 5`, both `a=0x8100 b=0x100. Cause` |
| new | pre-T7c | `Failed 5 of 5` |

Pre-T7c with new ROM: Random read early a=0x1f b=0x1d; COUNT hazards Second readback a=0x1 b=0x0; SW1 hazard ExceptPC a=0x800013c8 b=0x800013cc; SW1 disable-right-away unexpected Int; SW12 ExceptPC off by 4. The SW cases fail on timing/ExceptPC, not Cause, so the added write does not mask the checks. The diff changes no assertion.

**Bytes.** romgen all 5 suites (24 ROMs) at head and base: only `nemu64/nemu64-cop0hazard.z64` differs (5ef4ed47... -> 9518d316...); `.tests.tsv` files identical. Two head builds: sha lists identical (deterministic). Master emulator, old vs new ROM: timing (Failed 11 of 1604) and cycle (Failed 7 of 13) `values.tsv` and timing `categories.tsv` cmp-identical.

**Diff** (2 files, +18/-1): no dead code, no scope creep, no timing constants. Comment explains a why and cites upstream lines. Notes: README says "the first software interrupt test"; in this port that is SW1 enabled-hazard, since upstream's SoftwareInterrupt1Enabled is not in the set. Wording only.

Recommendation: land. Follow-up already implied: the `cpu.irq-sample` note about the red softwareinterrupt check is now stale and can be dropped if present.


Not reproduced: nothing. Worker's '48 files' = 24 ROMs + 24 .tests.tsv (I hashed ROMs and diffed tests.tsv). Process: kicked off only my own builds/runs. No classifier denials. Raw: ~/n64-timing/results/verify-64/ (sha-*.txt, run-*.txt, home-*/results).
