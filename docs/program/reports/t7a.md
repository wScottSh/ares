# T7a report: pipeline scoreboard

Status: done. Branch feat/t7a, head 1326f3f40afcdb650601d68ffa7b775939aef3d3, base master 826e1fb1b (T6 merged, fast-forward). PR: https://github.com/wScottSh/ares/pull/56 (ready, base master).

Raw outputs: C:\Users\Scott\n64-timing\results\t7a\{before,after,wall,wip-exp}. Builds: build\t7a-base, build\t7a.

## What changed

Every CPU timing cost now comes from one place. The decoder returns an `OpTiming` for each instruction word (`cpu/decoder.cpp`, replacing the unread `OpInfo` functions). `CPU::Pipeline` (`cpu/pipeline.hpp/.cpp`) holds a register scoreboard and charges stalls at issue and costs at retire. The `step()` calls in `interpreter-ipu.cpp` and `interpreter-fpu.cpp` are deleted.

- **LDI.** A load or MFC0/DMFC0 result read in the next issue slot stalls 1 pclk. The check compares raw register fields, as the hardware does (nemu64-test CPURegisterDependency, n64brew VR4300 load delay interlock). SPECIAL, REGIMM, I-type and COP0 check rs and rt. COP1 checks only rt (`LB $A0; MTC1` does not stall although rs = 4). COP2 also checks only rt, inferred from COP1. LWC1/LDC1/SWC1/SDC1 check only the base. J and JAL check nothing.
- **FPU forwarding.** An FPU result read as fs or ft by the next FPU operation costs +1 (COP1RegisterDependency). The fs and ft fields are checked even for one-operand ops (the "dependency via ft" rows).
- **MCI.** MULT/DIV and the FPU hold the whole pipe for their full latency. The nemu64-test HiLoInterlockTiming comment says "nothing executes in its shadow". Each op's cost is therefore one number. This deviates from the sketch's `mulDivFree`/`hiloReady`, and it settles the ADR's open question about freezes.
- **Trivial FPU operands** finish in 2 pclk (nemu64-test COP1 tables):
  - ADD/SUB and DIV: either operand is 0, Inf or NaN.
  - MUL: either operand has a zero mantissa (0, Inf, any power of two) or is NaN.
  - SQRT: the operand is 0, Inf, NaN or negative.
  - CVT.S/CVT.D from W/L: the integer is 0.
- **MTC0/DMTC0** to Random, EntryLo0/1, reg 7 or EntryHi costs 2 (SingleInstructionCPUTiming). This rule also fixes the 4 `LB; MTC0/DMTC0 $A3|$R0, _Unused7` values that verify-51 flagged as not LDI. Those values need the 2-pclk MTC0, plus the LDI only where rs or rt overlaps.
- **Nullified likely-branch slot.** A not-taken likely branch turns its slot into a 1-pclk bubble (LikelyBranchCycleCount). The plan lists this under T7b, but the T7a C8 target needs it.
- **DCB.** A cached hit in the slot right after a cached store costs +1 (NEC VR4300 UM s.4.6.7; cen64 `vr4300/pipeline.c:430-448` for the hit/miss order). Only the next instruction waits, which is what the Data cache Size loop requires.
- **Rows.** These legacy rows are replaced by measured rows: `legacy.cpu.instruction`, mult/div, and the fpu-* rows. The new rows are `cpu.issue`, `cpu.mult`, `cpu.dmult`, `cpu.div`, `cpu.ddiv`, `cpu.fpu-sqrt-s/d`, `cpu.fpu-convert` and `cpu.fpu-cvt-s-d`. 44 allowlist entries are gone. The save state is v153.7-pipeline.

## How verified

Base is feat/t6 9cb6723cc, which is identical to master 826e1fb1b (fast-forward). Head is this branch. Raw outputs are under `C:\Users\Scott\n64-timing\results\t7a\{before,after,wall}`. The driver is `results\t7a\suite.sh`, and `moves.py` lists every moved value.

| Check | Before | After |
|---|---|---|
| nemu64 timing failed | 909 | **453** |
| C2+C8 | 195+21 | 0+0 (fall 216, target 214) |
| C3+C4 | 172+50 | 0+0 (fall 222, target 222) |
| C5 / C9 | 18 / 9 | 0 / 0 |
| C7 | 1 | 10 (see below) |
| cycle / cop0hazard failed | 9 / 5 | 9 / 5 |
| T6's 158 broken values | fail | all 158 pass |
| stepcap nemu64 x3, MM | PASS | PASS (8158 fields) |
| det | PASS | PASS (27 files, 8158 fields) |
| state-roundtrip + TMEM poke | PASS | PASS |
| gen (`--check`, lint) | ok | ok |
| bench | fail 12 / pass 9 | fail 12 / pass 9 (same rows) |
| filesel_check | named-files FAIL | unchanged |

Moved values: timing has 465 fixed and 9 broken. The fixed values break down as follows:
- CPU register dependency 221;
- COP1 32-bit 82;
- COP1 64-bit 81;
- COP1 register dependency 59;
- Individual instructions 10;
- Compare (signalling 2) 7;
- Likely branch 5.

The named groups pass except for the T7b CACHE rows. These groups pass: CPU register dependency (3 CACHE rows remain, C10), COP1 register dependency, the non-exception rows of COP1 instruction 32/64, Individual instructions, Data cache Size, and Cached loads and store.

**The 9 broken values are all Load Miss (VI off x7, VI on x2), on the mean check only.** The miss model gives 41 or 42 pclk depending on the rclk-edge phase. On the base the harness loop sat at the 42 phase (sum 41999). Hardware's mean of 42.5 comes from a tail the model lacks. The harness's preconditions call is `LD $S3; JALR $S3`, and that is an LDI, measured by the `LD; JR` rows. The stall moves the loop to the 41 phase (sum 41000, which still passes the median). I tested this: a build that skipped the LDI on JALR alone restored the base result (sum 41999 everywhere, with the same one bank-4 failure). The fix belongs to the D-fill and refresh model, not to LDI.

**MM wall time.** I ran 600 fields interleaved, 5 runs on each side, on a shared host:
- before: 11.37, 13.57, 10.91, 11.58, 10.82 s (median 11.37 s, 15.3 ns per instruction);
- after: 12.21, 12.71, 11.85, 14.56, 11.96 s (median 12.21 s, 16.6 ns per instruction).

Render time is equal on both sides (about 1.9-2.0 s), so the scoreboard and decode cost is about +1.3 ns per instruction. The ADR budgeted 5 ns. The sct run was too noisy on this host to read (27-37 s on both sides).

## Deviations

1. The scoreboard is part of `CPU::Pipeline`, which still holds the branch state, and `ex` is `Thread::clock`. There is no second clock.
2. There is no `mulDivFree`/`hiloReady`/`fpuFree`, because the hardware stalls the whole pipe for these ops (see MCI).
3. The issue slot stays where it was charged, at fetch (`memory.cpp`), now as `Behavior::CpuIssue`. Moving it after fetch would shift every I-fill by 1 pclk, and T7d owns fetch.
4. These files are outside the plan's list:
   - `exceptions.cpp` has one line, `pipeline.fault()`. An exception skips retire, and T7b charges exceptions.
   - `dcache.cpp` gains the DCB hook.
   - `memory.cpp`, `serialization.cpp`, the behaviors table and spec, and the allowlist also changed.
5. The nullified likely slot was pulled in from T7b for the C8 target.
6. Two behaviors are inferred because the corpus has no test for them: COP2 checks rt like COP1, and LWC1/LDC1 FPR results use the LDI latency for FPU readers.
7. DCB has a vendor reference but no case in the corpus exercises it.

## Follow-ups

- Load Miss mean: the miss model needs its tail (refresh with VI off, T6 deviation 6), or a D-fill re-derivation across phases.
- A romgen case for a cached store followed by a load in the next slot (DCB) and one in the slot after.
- `pi-dma-sizes cart-to-ram-8` moved from 189.33 to 196.0 rclk (still failing). The cause is poll-phase quantization, inferred, and T8 owns it.


## For the next unit
- T7b: `Pipeline::fault()` is called from Exception::trigger. It sets `faulted`, so retire charges nothing and records no late result. Put the stage costs there. The issue() stall has already been charged when an exception fires mid-instruction.
- An FPU exception op's cost: the fast/normal cost is computed in issue() (`Issued::extra`) and is skipped on fault. T7b's 'latency + 5' can use `issued.extra + CpuIssue`.
- CACHE op costs (C10, 3 rows) and C1 (439) remain. The cop0hazard and cycle sets have not moved.
- Interrupt, NMI and sysad-frozen steps in cpu.cpp are still legacy rows.
