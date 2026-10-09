# verify-85c (PR #85 at aba69902e)

PR comment: https://github.com/wScottSh/ares/pull/85#issuecomment-6079903174
Worktrees: /home/wscottsh/repos/ares-wt/verify-85c (head), verify-85c-base (master 5c2a9891f). Results: /home/wscottsh/n64-timing/results/verify-85c/{head,base,dry-run.txt}; scratch mutants in the session scratchpad.

**Verdict: PASS-WITH-NOTES. Recommendation: land.** Every verify-85b follow-up is closed and reproduced. The merge is clean against master 5c2a9891f, and no core emulation byte moved. Notes are minor (below).

Setup: own worktrees at head and at master, builds `verify-85c` / `verify-85c-base`, private N64_TIMING_HOME, ROMs rebuilt from the tree (pref 25), full `standing.sh` on both (head and master, interleaved). Load 0.9-7.3. Nothing of mine still running.

**1. Merges.**
- `git merge-tree --write-tree` head vs master: clean (tree c07f54ded, rc 0).
- behaviors.tsv vs master: 150 rows both sides, only the `verify` column differs (127 rows); every other column identical (cell-by-cell diff).
- `behaviors.py --check` ok on the committed tree (generated files equal behaviors.py output); worktree clean after.
- RUNNERS has `systembench` and `hw`. standing.sh diff vs master adds only `kit.py --self-test` and `calibration/run.sh`; the systembench suites remain.
- `--results` on my head run reproduces docs/spec/n64-timing-results.tsv exactly (only the provenance line differs).

**2. systembench reader.** My era build sha256 `fd5ec6c06acb...6823` (matches the question text). run.sh writes ext/systembench.txt from it. Question and docstring say pointwise for this binary. Ingest (--dry-run, own capture): unchanged fork log -> pass; PI I/O W Found 130->135 -> fail; log cut at 90 lines -> stays pending:calibration-16 ("none with 'Benchmarks done'").

**3. Watch split.** `cpu-watch` is its own question (cpu2-exc/watch-*, min fired, exact), closing item:fu.exc-entry and #87; no row names it. Fork cpu2 log with Watch fired=4 (footer recomputed): hw:cpu-watch -> fail, hw:cpu-exceptions -> pass, no cpu.issue/eret/irq-sample flip to fail (they flip to pass). Unedited log: both pass.

**4. Coverage rule.** `hardware_needs` iterates all 149 rows. Mutation (scratch tree): drop `hw:rdp-sync-setter` from rdp.sync-pipe -> `--check` error "`rdp.sync-pipe` is closed by hw:rdp-sync-setter, but its verify column does not name it" (1 mutation, 4 errors incl. 3 drifted generated files). Fit-only exception holds: cpu.ctc1-fpe-ce (fit-from nemu64:cycle/ctc1) is closed by hw:nemu64-cycle-console without naming it and passes; the self-test case for it is in the 61. Inventory: **224 entries, 208 with a question, 7 not hardware-decidable, 9 not decidable by this kit.** Row status vs master (computed with row_status on both trees, 149 rows): no status changed; 12 rows gained a `pending:calibration-16` token next to their existing gate, nothing else.

**5. Undecidable.** 8 legacy.cart.* + legacy.pif.boot-timeout read "not decidable by this kit: ... What would decide it: ..."; the other 7 keep "not-hardware-decidable". Counted separately in the inventory (7 / 9). Rule accepts both prefixes; self-test cases fire.

**6. Bounded waits.** Console builds only: rom-sha256 list (721 ROMs, suites bench/nemu64/etc.) byte-identical head vs master. Mutants built in a scratch tree from hwout.py (boot-1 kit ROMs):
- DP wait that never sees the interrupt (mask 0x20->0x40): kit-rdp finishes in 96 s wall with `#kit-timeout pi=0x0 rdp=0xf0`, valid footer. Ingested as a console capture: all 5 kit-rdp questions fail (cmd-fetch-burst, cmd-fifo-depth, rdp-atomic, rdp-rect-base, rdp-sync-setter); the 2 kit-span questions pass.
- PI wait that never idles: kit-rdp finishes in 271 s with `pi=0x985`, no hang. (kit-dma under this mutant ran >6 min and I killed my own PID; a bounded but slow run, not a hang. Unmeasured to the end.)
- Good logs print `#kit-timeout pi=0x0 rdp=0x0`; run.sh `--verify-run` requires zero.

**7. Standing (head vs master, my runs).**
- MM 600 --stats md5 `9629185039701bddcdbd90c248a4f38b` both.
- Byte-identical head vs master: nemu64 values.tsv timing (1605 lines), cycle (14), cop0hazard (6); systembench/results.tsv (35), systembench-845635c (35), bench/results.tsv (71), thar0/compare.tsv (101), mmbench/summary.tsv (8), rom-sha256.txt. Every results/compare/values/summary/frames tsv in the run dirs is identical. Differences are only wall/ns-per-instruction, stderr and the verify column copy.
- det and stepcap PASS: MM (29 files), nemu64 timing/cycle/cop0hazard; round trip PASS (600 fields, saves at 150/300/457; tmem poke control also differs as designed).
- `--check` ok, `--self-test` 61/0 failed, kit 15, romgen selftest 72/72, lint ok, pidma 5, systembench report 11, ctest 9/9.
- run.sh: `kit: 103 SRAM copies checked, 0 errors`.
- dry-run.sh: 76 hardware checks pass of 80, 26 behaviors flip; 0 non-pass transitions.

**Notes (not blocking).**
- The committed results header says "on 214c46421"; head is aba69902e (results-only commit). Cosmetic.
- PI-wait bound is slow when it triggers (kit-rdp 271 s), fine for a console but a user waits minutes.
- Carried from 85b: vi-first-line tolerance, small SP DMA, textured triangles, #86, #87; ri.max-burst -> sp-dma-direction link is an inference (worker disclosed).
- Not reproducible here: all hardware behavior.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
