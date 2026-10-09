# T7c report: CP0 timing

**Status:** partial. Two Check items fall short of the plan:
- cop0hazard fails 2/5 where the plan says 5/5.
- The "fall by 28" target has nothing left to fall on today's base (see the reconcile section).

Everything else passes.

**Branch:** feat/t7c, head e0be4dfd46cb69695bd7ab21fc8b8bdeff181108, base master a86d40886. PR: https://github.com/wScottSh/ares/pull/62.

**Builds:**
- ~/n64-timing/build/t7c-base (master, from worktree ares-wt/t7c-base)
- ~/n64-timing/build/t7c (head)
- ~/n64-timing/build/t7c-mut (mutations)

**Raw output:** ~/n64-timing/results/t7c/{before,after,wall}. Drivers: results/t7c/standing.sh and compare.sh.

## Reconciling the 28 (measured on master unless noted)

The clusters come from research/nemu64-timing-failures, measured on the 59158c28a interpreter. All four count in the timing suite:
- C5 MTC0 slow regs: 14
- C9 MFC0 interlock: 9, of which 7 are Compare (signalling 2)
- C10 CACHE: 3
- C11 Random: 2

14 + 9 + 3 + 2 = 28. C11 also has +1 in cop0hazard, Random (read early).

On master, C5, C9, C10 and C11 already show 0 timing failures (categories.tsv). Random (decrement), Random (masking) and Compare (signalling 2) pass (tests.tsv). Which units landed them, inferred from the row checks:
- C5 and C9 in T7a (cpu.mtc0-slow-regs, cpu.mci)
- C11 in T2 (per-instruction Random)
- C10 in T7b

So on today's base the target for T7c's clusters is:
- timing: no further fall; 11 stays 11 (C6 x1, C7 x10, not mine)
- cop0hazard: 5 to 0
- cycle: the 2 CTC1 tests

## Check
- **nemu64:cop0hazard: 5 to 2 failed (FAIL against the 5/5 target).**
  - Pass now: Random (read early), MTC0/MFC0 COUNT hazards, SoftwareInterrupt1 (enable but disable right away).
  - Still failing: SoftwareInterrupt1 (enabled, hazard) and SoftwareInterrupt12. Both fail at Cause, 0x8100 vs 0x100. Cause: the now-passing CountHazards runs v = 0xFFFFFFFF, so COUNT passes 0. That equals Compare, which ares powers on at 0, so IP7 stays set for the later tests.
  - Evidence: a scratch ROM with CountHazards moved last (scratch/t7c/exp) passes 5/5 on head and fails 5/5 on master (measured).
  - In nemu64-test's testlist.rs, the timing-set Compare tests run between CountHazards (588) and the SW tests (741+), and those tests write Compare. The hardware expected values therefore probably come from a full run (inferred).
  - I did not choose a power-on Compare value, because I found no reference.
- **Compare (signalling 2), Random (decrement), Random (masking): pass on both sides.**
- **CTC1 cycle cases: both pass now** (they failed on master). The cycle set goes from 9/13 to 7/13 failing; the 7 left are SMC tests, which belong to T7d.
- **Failures fall by 28: n/a on today's base** (see above). Timing values.tsv is byte-identical before and after.

## Standing checks (master to head, measured)
- snapper 2592/2592; rdpstat 0/7, 0/2, 0/21; thar0 77,772 / 155,052; bench fail 10, pass 11, report 19. results.tsv and the text outputs are identical.
- ctest 5/5. behaviors --check, --self-test and lint: ok.
- det and stepcap: PASS on MM (27 files, 8158 fields) and on the 3 nemu64 ROMs. State round trip and TMEM poke: PASS on head.
- MM stats move slightly, as expected, because interrupts are now taken one instruction later. sct rsp_busy per field went from 1315212.8 to 1309175.6. The fields-per-gframe distributions are unchanged.
- MM 600-field wall: 5 interleaved pairs, load average 2.8 to 6.2.
  - master: 19.79, 19.82, 19.97, 20.07, 20.85 s (median 19.97)
  - head: 20.18, 20.23, 20.04, 20.35, 21.59 s (median 20.23), +1.3%
  - perf stat over 300 fields: host instructions +0.53% (about 2 per emulated instruction), host cycles -0.07%.

## Model (behaviors.tsv)
- **cpu.count-write-hold: 2 pclk, fit, verify-is-fit.** Fit from cop0hazard CountHazards, which reads v, v, v, v+1. Its doc comment says the read "returns the just written value a couple of times". `countResume` makes `effectiveCount` clamp, and `scc.count` is offset by -2, so COMPARE and `profile.cpuCycles` stay exact. Mutation: a 1 pclk hold fails CountHazards and 988 timing values. The timing harness sees only the hold's parity.
- **cpu.wired-write-latency: 2 instr, fit from timing/random.** The independent check is cop0hazard/random-read-early. Until the write lands, Random keeps the previous Wired and epoch. Mutation: setting it to 1 fails read-early, decrement and masking.
- **cpu.irq-sample: rule, fit, verify-is-fit.** Int is taken only if the condition held at the previous instruction boundary as well. A one-instruction CP0-write delay fails "disable right away". The rule applies to every IP bit, which is inferred.
- **cpu.ctc1-fpe-ce: rule, fit, verify-is-fit.** Cause.CE = bits 27-26 of the following instruction. The word is read through `readDebug` at `pipeline.pc`. Using the same bits when that instruction is not a coprocessor op is inferred.
- **cpu.random-rule:** the value was `decrement-per-pclk` (vendor), which contradicted the code. It is now `decrement-per-instruction`, fit, with an independent check.
- **Save state layout changed:** `wired.previousIndex/previousEpoch`, `countResume`, `interruptSampled`. SerializerVersion is unchanged (T7a precedent).

## Deviations
1. No `Cp0Writes` or `TimedCp0` struct in `pipeline.cpp`. Each rule sits with its state in interpreter-scc.cpp, cpu.cpp/hpp, interpreter-fpu.cpp and serialization.cpp. The three rules are different kinds: a time hold, an instruction landing and a boundary sampler. A generic queue would cost time on every instruction. COMPARE was already one event before T7c.
2. Interrupts use two-boundary sampling instead of the sketch's "CP0 write visible one instruction late", which the tests rule out.
3. Sketch rows replaced or renamed:
   - cpu.count-write-latency became cpu.count-write-hold.
   - cpu.irq-sample-lag became cpu.irq-sample.
   - New: cpu.wired-write-latency and cpu.ctc1-fpe-ce.
   - New checks: nemu64:cop0hazard/random-read-early and nemu64:cycle/ctc1.
   - The legacy.cpu.interrupt-entry note now says "no plan unit", because no reference for the entry cost was found.
4. cop0hazard is 3/5 passing, not 5/5. The cause is above.

## Follow-ups
- The standalone cop0hazard ROM lacks the full run's inter-test state, so IP7 is left set by CountHazards. Either the romgen port clears it before the SW tests (a tools decision), or a reference for power-on Compare is found.
- Interrupt entry cost and CTC1-raised FPE cost: no reference found (unchanged).

## For the next unit (T7d)
- The cycle set has only the 7 SMC tests left.
- Interrupts are now sampled one boundary late in `CPU::instruction()` via `interruptSampled`. That flag updates on every `instruction()` call, including the NMI, sysadFrozen and fetch-fail early returns. Keep it at the top of the function if the fetch path moves.
- The CTC1 CE peek uses `readDebug<Word>(pipeline.pc)`. If FetchWindow holds the next word, use that word instead.
