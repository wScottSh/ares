## Verification of PR #62 (T7c CP0 timing): PASS-WITH-NOTES

Head e0be4dfd4 vs base a86d40886. Own worktrees `ares-wt/verify-62{,-base}`, own builds `build/verify-62-{base,head}` (gcc RelWithDebInfo via `tools/n64-timing/build.sh`), ROMs rebuilt by `romgen/build.py` (all 48 ROMs byte-identical base vs head). Raw: `~/n64-timing/results/verify-62/{base,head,wall,compare.txt}`, experiments in `~/n64-timing/scratch/verify-62`. Host loaded (T11 running): load average 2.9 to 15 over the session.

### Verdict on the open question (cop0hazard 3/5)
The residual is a port-isolation artifact, not a model defect. It should NOT block landing; it goes to a follow-up (romgen/tools) unit.
- Upstream full-run order: `testlist.rs:588` CountHazards, then `:589-591` the three Compare tests, then `:740-750` the SW interrupt tests. Compare (past) ends with `set_compare(target)` (`cop0/compare.rs:209`); MTC0 Compare clears IP7 (ares `interpreter-scc.cpp:185-188` `setInterruptPending(Timer,0)`).
- The SW tests assert the exact Cause word, so IP7 must be clear: `exception_instructions/mod.rs:398` `soft_assert_eq(exception_context.cause, cause, "Cause")` with `Cause::DEFAULT.with_interrupt_sw1(true)`. Upstream never sets Compare anywhere else (grep of `set_compare` in src: compare tests only).
- Port: `romgen/suites/nemu64/sets.py:26` builds the set with `base=0`, and `cop0hazard.py:71-79` has the 5 tests in a row with no Compare write between. Its own docstring (`cop0hazard.py:34-35`) already names the IP7 carry-over from 0xFFFFFFFx.
- Upstream does support an isolated build (`Cargo.toml` features, `--no-default-features --features cop0hazard`, which research/nemu64-timing-failures.md:127 used), but then IP7 on hardware depends on the unknown power-on Compare. The default config is `default=["base"]` plus extras, i.e. the Compare tests run. So hardware expectations are only guaranteed to be Compare-cleared in the combined run (inferred; I did not see a hardware log).
- Reproduced (measured, my own ROMs built from a copy of romgen):
  - A: CountHazards moved last. base 0/5 pass (Failed 5 of 5), head 5/5 (Failed 0 of 5).
  - B: a `mfc0 count; addiu -2; mtc0 compare` step (the Compare (past) effect) inserted after CountHazards, order otherwise as upstream. base Failed 5 of 6 (stand-in passes), head Failed 0 of 6.
- Caveat: the shipped `nemu64:cop0hazard/softwareinterrupt` check stays red for 2 of its 3 values until the port gets a Compare write (or the Compare tests) before the SW tests. The behaviors.tsv note for `cpu.irq-sample` does not mention this; worth a line.

### Item 1: the "28" (measured)
On base, `categories.tsv` has only C6 x1 and C7 x10 (11 of 1604); C5/C9/C10/C11 are 0. Random (decrement), Random (masking), Compare (signalling 2) pass on base. Timing `values.tsv` and `categories.tsv` are byte-identical base vs head (cmp). So "fall by 28" is vacuous on today's base; the plan Check line is stale, not the PR.

### Item 2: cycle (measured)
Base Failed 9 of 13, head Failed 7 of 13. Changed: both `Fire exception through CTC1` (MFC1, MFC2) fail->pass. The 7 left are the SMC (`icache:`) tests, T7d's.

### Item 3 (numbers): cop0hazard (measured)
Base Failed 5 of 5, head Failed 2 of 5. fail->pass: Random (read early), COUNT hazards; exception->pass: SoftwareInterrupt1 (enable but disable right away). Left: SW1 enabled-hazard, SW12, both `a=0x8100 b=0x100. Cause`, as the worker said.

### Item 4: standing checks (all base = head, measured)
- snapper 2592/2592 both. rdpstat Failed 0 of 7, 0 of 2, 0 of 21 both. thar0 rows identical.
- bench: `fail 10, pass 11, report 19`, `results.tsv` cmp identical.
- ctest 5/5 (head). `behaviors.py --check` ok, `--self-test` ok, `lint-literals.py` ok.
- determinism and step-cap: PASS on MM (27 files, 8158 fields) and the 3 nemu64 ROMs (24, 2, 1 fields). State round trip PASS (saves/loads at 150, 300, 457); TMEM poke PASS.
- MM 600-field wall, 5 interleaved pairs, load 3.6 to 6.3: base 19.592 19.566 19.597 19.450 19.390 (median 19.566 s); head 19.776 19.705 19.678 19.557 19.667 (median 19.678 s) = +0.57% (worker said +1.3%; both small, budget 120 s). Head above base in 5/5 pairs. MM fb_hash identical on all 600 fields; cpu_cycles sum differs by 862 over 3.16e11.

### Item 5: provenance
- `cpu.count-write-hold`: fit, verify-is-fit. Accurate; the sole check is its own data. Good.
- `cpu.wired-write-latency`: fit from timing/random, independent check Random (read early) (different Wired, 10-instruction span). Mutation rerun: latency 2->1 on head: cop0hazard fails read-early (a=0x14 b=0x15), timing fails Random (decrement) and Random (masking) (Failed 13 of 1604, 11 + 2). Reverted, rebuilt, back to Failed 2 of 5. Worktree clean at the PR head.
- `cpu.irq-sample`: fit, verify-is-fit; "every IP bit" labeled inferred. Good. I did not rerun "delaying the CP0 write by one instruction instead takes the third" (not reproduced).
- `cpu.ctc1-fpe-ce`: fit, verify-is-fit; non-coprocessor-instruction case labeled inferred. Good.
- `cpu.random-rule` relabel vendor->fit/decrement-per-instruction matches the code (`getControlRandom` uses `instructionIndex`). Read-early is a fair independent check.

### Item 6: deviations
- No `Cp0Writes`/`TimedCp0`: sound. The three rules (time hold, instruction landing, boundary sampler) are different shapes; state and rule colocated, compare already one event. Cost: spread over cpu.cpp, interpreter-scc.cpp, interpreter-fpu.cpp, serialization.cpp.
- Two-boundary sampling replaces the sketch's one-instruction-late: sound as a fit to three tests, labeled fit, disclosed. I traced `scheduleCompare` with the -2 offset: remaining is computed mod 2^33 on even values, so no spurious early match during the hold.
- CE peek: `pipeline.pc` is the next executed address (begin() sets `pc = nextpc`, so it is the branch target in a delay slot). Correct.
- Save-state layout changed, `SerializerVersion` ("v153.8-dma") unchanged: not a problem here. Old states would misload silently, but the fork has no compatibility constraint, the MM bench uses no save states (mmbench README:5), and T7a set the precedent. Note it for the coordinator.

### Item 7: diff hygiene (9 files, read in full)
No dead code. Comments explain a why and cite a behavior id. Constants live in behaviors.tsv with references. Notes:
1. `interpreter-fpu.cpp:175` `readDebug<Word>(pipeline.pc)` reads through the D-cache, not the I-cache; a stale I-cache line (SMC) would give different bits. Worker flagged it for T7d. Fine for now; no test.
2. Back-to-back Wired writes inside the 2-instruction window keep only one level of history (`previousIndex/Epoch` takes the unlanded value). Untested edge; Random reads 31 until landing.
3. `legacy.cpu.interrupt-entry` row still carries the old entry cost with no plan unit; consistent with the worker's disclosure.
4. spec/behaviors row for `cpu.irq-sample` should say the softwareinterrupt check is red for 2 of 3 values pending the port fix.

### Not reproduced
Nothing in the worker's report failed to reproduce. Wall delta differs (+0.57% vs +1.3%), within noise. Hardware log for the full-run order is not available, so "hardware values came from a full run" stays inferred.

### Recommendation
Land. Follow-up unit (tools/romgen): add the Compare (past) effect or the Compare tests before the SW tests in `cop0hazard.py` (upstream order), so `cop0hazard` reads 5/5 and the irq-sample check goes green. No power-on Compare value should be invented.
