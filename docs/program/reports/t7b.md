# T7b report: exceptions and bubbles

Status: done. Branch feat/t7b, head 964ef15749c0a837d2251b2ca7dfb41c94f0b641, base master 8889b93b1. PR: https://github.com/wScottSh/ares/pull/61 (base master). Builds: ~/n64-timing/build/t7b-base (master) and build/t7b. Raw outputs: ~/n64-timing/results/t7b/{before,after,wall}. Driver: results/t7b/standing.sh. after-389037de1 and wall-389037de1 hold the first commit's slower runs.

## Check
- nemu64 "Exceptions": PASS (135 values were failing). "COP1 JustFire": PASS. COP1 instruction 32 and 64 bit pass as whole groups (304 values were failing). "Likely branch": PASS on master and on head. T7a built the nullified slot (cpu.likely-nullified), and T7b does not charge it twice. The CACHE cases (nemu64:timing/cache, C10, 3 values): PASS.
- Timing failures fall by at least 439 (C1): PASS. 453 to 11 is a fall of 442 (C1 439 + C10 3). No value broke. The per-value diff over all 1604 values is 442 fail->pass and nothing else.
- Remaining 11. C7 Load Miss VI off x8 and VI on x2, which fail the mean check because the D-fill model has no refresh tail (T7a follow-up). C6 Load from uncached VI on same bank x1, expected-fail until T11. Their values are byte-identical to master.

## Standing checks (master -> head)
- nemu64 cycle 9/13 and cop0hazard 5/5 failed on both sides, with values byte-identical.
- snapper 2592/2592; rdpstat 0/7, 0/2, 0/21; thar0 84,92 = 77,772 and 85,93 = 155,052: same on both sides.
- bench: fail 10 / pass 11 / report 19. results.tsv is identical.
- ctest 5/5. behaviors --check, --self-test and lint-literals: ok.
- det and stepcap: PASS on both sides. MM: 27 files, 8158 fields. nemu64: 3 ROMs.
- state round trip and TMEM poke: PASS on both sides.
- MM output changes, as expected: ERET runs on every interrupt return. sct rsp_busy per field moved from 1310046.6 to 1315212.8. The fields-per-gframe distributions are unchanged.

## MM 600-field wall
5 runs on each side, interleaved, at load average 5.6 falling to 1.6:
- master: 19.56-19.73 s (median 19.65, 26.2 ns per instruction);
- head: 19.77-20.13 s (median 19.85, 26.5 ns per instruction).

That is +1%. The first commit was +11% (19.5 vs 21.6 s). perf stat measured +3.4e9 host instructions over 300 fields, because the commit stored `Issued` as a Pipeline member. The fix keeps it on the instruction() stack, and the cost recovered to within 1% under perf stat.

## Model
- `fault(stage)` charges stage total - 2 x CpuIssue. JustFire counts both issue slots, and fetch already charges both.
- RF 5: Sys, Bp, RI, CpU.
- EX 6: Ov, Tr, AdEL, TLBL. AdES, TLBS and Mod are inferred to share the EX stage, with no test.
- FPU: detection latency + 5. An FPE raised from the result takes the op's latency, fast operands included. An FPE raised from the operands takes min(latency, trivial 2):
  - a denormal or NaN operand;
  - a conversion to W of |x| >= 2^32 or Inf, where 2^31..2^32 is late (measured at 0x41efffffffffffff vs 0x41f0000000000000);
  - a conversion to L of |x| >= 2^53, or from L of |x| >= 2^55;
  - a W/L format op with an S form, at the S latency (ADD.W 7, _F16.W 6).
- ERET 3 pclk: a fit from the Roundtrip value 15, with verify-is-fit. CACHE D Index Load Tag: 6 pclk.
- Mutation checks: ERET=2 breaks both Roundtrip values. A W exponent limit of 31 breaks 16 values.

## Deviations
1. Files outside the plan list:
   - pipeline.hpp and cpu.cpp, for the in-flight pointer;
   - decoder.cpp, for the ERET, CACHE and W/L-S-form costs in opTiming/fpuTiming, the one cost table;
   - memory.cpp, to remove the legacy address-error step;
   - behaviors.tsv, checks.tsv (new nemu64:timing/exception-roundtrip) and literal-allowlist.tsv.
2. The sketch's CpuExcFpuUnimpl row is removed, because 7 = trivial + 5. cpu.exc-fpu-arith-extra is renamed to cpu.exc-fpu. cpu.cache-index-op becomes cpu.cache-index-load-tag with value 6 total, where it was 5. The faulted flag is replaced by `inFlight` (null outside an instruction).
3. Not built, no reference: interrupt entry (T7c), NMI (legacy.cpu.nmi-entry stays, note updated), bus errors, watch, emux, a CTC1-raised FPE, fetch-time exceptions, other CACHE ops.
4. The cpu.exc-fpu-detect rule is read off the same COP1 tables that check it, as cpu.fpu-trivial is (basis measured).

## Follow-ups
- romgen cases for AdES/TLBS/Mod, I-fetch AdEL/TLB, a CTC1-raised FPE, and the other CACHE ops.
- An ERET-only measurement to make cpu.eret independent of its fit data.
- C7 Load Miss mean (from T7a) and C6 (T11) are the only nemu64 timing failures left.

## For the next unit
- T7c: interrupts reach `fault(FaultStage::None)`. They are taken before fetch, and `inFlight` is null then. The interrupt entry cost is still legacy.cpu.interrupt-entry in cpu.cpp. CTC1 FPE CE timing is T7c's, and a CTC1-raised FPE currently charges nothing in fault().
- `Pipeline::inFlight` points at the `Issued` on CPU::instruction()'s stack between issue() and end(). Do not make it a member: that cost 11% of MM wall time, measured.
