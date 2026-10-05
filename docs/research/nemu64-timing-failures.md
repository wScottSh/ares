# nemu64-test timing failure root causes on ares (fork)

Ticket: wScottSh/ares#5 (map #1). Target console: NTSC retail NUS-001 with Expansion Pak.

## TL;DR

- On this fork's **interpreter** (`master` @ `59158c28a`), nemu64-test @ `9a8b9f7` fails **924 / 1604 timing**, **9 / 13 cycle**, **5 / 5 cop0hazard** tests. The recompiler fails 1109 / 10 / 5. The often-quoted "1593 / 1604" was ares **v148 recompiler** (`docs/research/n64-emulator-accuracy.md` in mm-decomp-60fps). It is not the fork's interpreter figure.
- **COUNT is not the problem.** `Repeated MFC0 COUNT`, `Half cycle calibration` and `Just NOPs` all pass, so the harness's COUNT-based measurement works on ares. Every failure is a real cost-model gap.
- ares has no pipeline model. An instruction costs 1 cycle at fetch plus a fixed `step()` added inside the instruction. There are no conditional interlocks, exceptions cost nothing, and uncached loads cost nothing. All 924 timing failures fall into 11 root causes. The three biggest:
  1. Exceptions have zero entry cost (439 failures).
  2. Every cached load or store costs a flat +1 cycle instead of a conditional load-use interlock (204 failures).
  3. FPU latency is fixed per opcode, but on hardware it depends on the operands (172 failures).
- Fixing these needs a stage-accurate VR4300 pipeline (IC/RF/EX/DC/WB) with:
  - LDI, MCI and FPU-forwarding interlocks,
  - stage-dependent exception timing,
  - operand-dependent FPU latency,
  - CP0 write and interrupt-sampling latencies,
  - fetch running ahead of stores,
  - an RDRAM latency model for uncached and miss traffic.

## Failure clusters (interpreter, timing set unless noted)

The ares column gives paths under `ares/n64/cpu/` unless noted. "AvH" means ares cycles vs hardware-measured cycles, as the test reports them.

| # | Cluster | Count | Example tests (AvH) | Root cause in ares | VR4300 behavior required | References |
|---|---|---|---|---|---|---|
| C1 | Exception entry costs 0 cycles | **439** (135 `Exceptions` + 304 COP1 `JustFire`) | `BREAK` 2v5, `ADD` overflow 2v6, `LW` addr-err 2v6, `ADD.W` (unimpl.) 2v7, `ADD.S` overflow-exc 2v8, `DIV.S` inexact-exc 2v34, `BREAK` round-trip 9v15 | `exceptions.cpp:1-29` (`trigger`) charges no cycles. FPU ops return before their `step()` when they raise (`interpreter-fpu.cpp:462-469`: `CHECK_FPE` returns early). `ERET` (`interpreter-scc.cpp:291`) has no cost | Exception detection depends on the stage, followed by a pipeline flush and a refill from the vector. Measured costs: 5 cycles for decode-time exceptions (BREAK, SYSCALL, RI, CpU). 6 for EX/DC-time exceptions (Ov, Tr, AdEL/AdES). 7 for FPU unimplemented-operation. An FPU exception costs the op's own latency first, plus 5. ERET has its own refill cost | nemu64-test `src/tests/timing/mod.rs` `Exceptions`, `COP1Instructions32/64`. VR4300 UM ch. 4 (pipeline, exception stages) and ch. 6 (exception processing). cen64 `vr4300/fault.c` (`VR4300_SYSC/BRPT/TRAP/RI`, pipeline flush) |
| C2 | Cached load/store hit = flat +1 cycle | **204** | `LW (cached)` 2v1, `SW (cached)` 2v1, `LB; ADDIU` (indep.) 3v2, `LD; LW 0($V1)` 4v2, `LD; NOP; BEQ $T4` 5v4, `Data cache Size` | `dcache.cpp:61` and `dcache.cpp:90`: `cpu.step(1*2)` on **every** D-cache hit. That makes the *dependent* load-use cases (3 cycles) pass by accident and every independent case fail | A cached hit costs 1 cycle. **LDI (load delay interlock)** adds 1 cycle only when the next instruction reads the load's destination in RF/EX, which includes branch and JR operands and load/store base registers. Stores never interlock | nemu64-test `CachedLoadsAndStoreTiming`, `CPURegisterDependency`, `cache.rs::CacheSizeTest`. VR4300 UM ch. 4 (LDI). cen64 `vr4300/pipeline.c:162-169` (LDI check), `fault.c:433-441`. MiSTer `rtl/cpu.vhd` operand forwarding (`:1269-1272`, `:2076-2083`) |
| C3 | FPU latency fixed per opcode | **172** | `ADD.S (0.0,-1000)` 3v2, `MUL.S` trivial 5v2, `DIV.S` trivial 29v2, `MTC1, DIV.S (trivial)` 30v3, `MUL.S, DIV.S (both trivial)` 34v5 | `interpreter-fpu.cpp:470,875,810,…` call `step((N-1)*2)` with N fixed per opcode (3/5/8/29/58) | Operand-dependent FPU latency. When an input is a "trivial" special case (0, ±0, ±Inf, NaN), ADD/SUB/MUL/DIV/SQRT finish in 2 cycles instead of 3/5(8)/29(58) | nemu64-test value tables (expected count per operand pair). The VR4300 UM FPU latency table gives only one number per op. The fast path comes from nemu64-test's hardware measurements |
| C4 | FPU-to-FPU dependency not modeled | **50** | `ADD.S (fs)` dependent 6v7, `MOV.S (dependency)` 2v3, `CVT.W.S (dependency)` 10v11, `DIV.D (fs)` 116v117 | No FPU scoreboard. Latency is charged at issue (same `step()` lines), so the result is available with no forwarding penalty | When an FPU op consumes the previous FPU op's result there is **+1 cycle**: a forwarding/interlock bubble between the FPU result and the next FPU operand fetch | nemu64-test `COP1RegisterDependency`. MiSTer `rtl/cpu.vhd` `decFPUForwardUse` (`:1214`), `execute_unstallFPUForward` (`:2507-2512`) |
| C5 | MTC0/DMTC0 to some CP0 registers costs 2 | **14** | `MTC0 EntryHi` 1v2, `MTC0 Random` 1v2, `LB; MTC0 _Unused7` 3v4 | `interpreter-scc.cpp:316` (`MTC0`), plus `DMTC0`: no extra cost | MTC0/DMTC0 to Random, EntryLo0/1, EntryHi and reg 7 take 2 cycles. MTC0 also participates in LDI as an rt consumer | nemu64-test `SingleInstructionCPUTiming`, `CPURegisterDependency` |
| C6 | Uncached RDRAM read costs 0 | **11** | `Load from uncached` range 1..1 vs 32..93 (VI on/off) | `mi/bus.hpp:2-11` (`MI::readRdram`) and `memory.cpp` `busRead`: no `step()` for an SysAD uncached read | Uncached load = SysAD single-word read through RI/RDRAM: median about 32 cycles (36 when the VI is reading the same RDRAM bank), up to 93 | nemu64-test `cache.rs::LoadFromUncachedVI*`. n64brew RDRAM / RDRAM Interface pages. cen64 `vr4300/fault.h:17` (`MEMORY_WORD_DELAY 38`) |
| C7 | D-cache miss is a constant 40 | **10** | `Load Miss (VI disabled)` avg 41.0 vs 42.5±0.5, `Load Miss (VI enabled)` 41.0 vs 43.25±1 | `dcache.cpp:7` `cpu.step(40*2)` (fill), `dcache.cpp:16` (writeback) | A miss is RDRAM-timing-dependent: median 41, occasional long tails (RDRAM refresh, row/bank conflicts, VI contention). This needs an RDRAM/RI latency model, not a constant | nemu64-test `cache.rs::LoadMiss*`. cen64 `fault.h:15` (`DCACHE_ACCESS_DELAY`). n64brew RDRAM |
| C8 | Nullified likely-branch delay slot costs 0 | **10** (4 + 6) | `NOP; BEQL; NOP` 3v4, `NOP; LD; BxxL $T4` 4v5 | `cpu.hpp:76` `pipeline.skip()` (used by `interpreter-ipu.cpp:37-40` BEQL, etc.) advances PC with no cycle | A not-taken branch-likely turns its delay slot into a bubble that still takes 1 pipeline cycle. Inference: the 6 multi-instruction cases are the BxxL variants of the LD→branch table, assigned here because the ROM prints them as "unknown arguments" | nemu64-test `LikelyBranchCycleCount`, `CPURegisterDependency::VALUES_S`. VR4300 UM ch. 4 (branch-likely nullification) |
| C9 | MFC0 has no load-style interlock | **9** | `MFC0 $A2; ADDIU $A3,$A2` 2v3, `Compare (signalling 2)` loop iterations 0x31f vs 0x29a | `interpreter-scc.cpp:308` (`MFC0`) writes rt immediately | MFC0/DMFC0 results arrive late, like a load: the next dependent instruction stalls 1 cycle. The test comment says "SRL has a stall on MFC0" | nemu64-test `CPURegisterDependency`, `cop0/compare.rs:150-155` |
| C10 | CACHE op cost | **3** | `LD; CACHE (DataIndexLoadTag)` 3v7, 3v8 | `interpreter-ipu.cpp:120` (`CACHE`): no cost beyond fetch | The D-cache index ops take several cycles (about 5-6 for Index Load Tag after a load) | nemu64-test `CPURegisterDependency` |
| C11 | Random is a PRNG | **2** (+1 cop0hazard) | `Random (decrement)` 0x10 vs 0x1e, `Random (masking)` | `interpreter-scc.cpp:269-272` (`getControlRandom` = `random() % …`) | Random is decremented every cycle from 31 down to Wired, then wraps to 31. Writes to Random are ignored | nemu64-test `cop0/mod.rs` `RandomDecrement` (reference model in its doc comment), `Random (read early)`. VR4300 UM ch. 5 (Random register) |

Sum: 439 + 204 + 172 + 50 + 14 + 11 + 10 + 10 + 9 + 3 + 2 = **924**.

### Cycle set (9 / 13 interpreter)

| Cluster | Count | Example | Root cause in ares | VR4300 behavior required |
|---|---|---|---|---|
| Fetch runs ahead of stores (self-modifying code) | 7 | `icache: Self-modifying code within basic block (single write)` (6,8), (7,8): ares executes new `0x2222`, hardware executes old `0x1111`. Also the HitWriteBack, implicit WB, i-cache-invalidation and "multiple writes" variants | `cpu.cpp:136-171` + `memory.cpp:157-163`: fetch happens at execute time, after earlier stores are visible | Instruction N+k is fetched (IC stage) before store N reaches DC/WB or drains from the write buffer. A store fewer than about 2-3 slots ahead of the target is not seen |
| CTC1-raised FPE: Cause.CE taken from the *following* instruction | 2 | `Fire exception through CTC1 (followed by MFC1/MFC2)`: CE=0 vs 1/2 | `interpreter-fpu.cpp:430-433` → `setControlRegisterFPU` → `exception.floatingPoint()` (`exceptions.cpp`, CE=0) | Inference from the expected values: the FPE caused by CTC1 is taken while the next instruction is in the stage that latches CE, so CE gets that instruction's coprocessor number |

The recompiler also fails `BGEZAL: Within delay slot of BEQ`, which is a recompiler-only control-flow bug.

### cop0hazard set (5 / 5)

| Test | ares vs hw | Root cause | VR4300 behavior required |
|---|---|---|---|
| `MTC0/MFC0 COUNT hazards` | 2nd readback +1 vs +0 | `interpreter-scc.cpp:171-173`: an MTC0 COUNT write takes effect immediately and keeps counting | The COUNT write lands at a late stage. The next 4 MFC0s read `value, value, value, value+1`. Inference: counting resumes only after the write retires |
| `SoftwareInterrupt1 (enabled, hazard)`, `SoftwareInterrupt12 (… after one nop)` | ExceptPC 4 bytes early | `interpreter-scc.cpp:218-222` (Cause write → `interruptPoll`) + `cpu.cpp:137-142`: the interrupt is taken before the very next instruction | Interrupt sampling lags MTC0 Cause/Status by 1 instruction |
| `SoftwareInterrupt1 (enable but disable right away)` | ares takes Int, hw doesn't | Same | An IP bit set and then cleared by back-to-back MTC0s is never sampled |
| `Random (read early)` | 0x16 vs 0x15 | C11. Inference: the MTC0 Wired write latency is also involved | Per-cycle Random plus the Wired-write latency |

## Details

### The measurement harness and why COUNT isn't at fault

`measure_cycles_codegen` (`src/tests/timing/mod.rs`) builds one contiguous, I-cache-aligned program:

1. Calibrate with `MFC0 COUNT; NOP; NOP; MTC0 COUNT`.
2. Run the body twice, offset by one instruction, to recover half-cycles.
3. Report `ticks1 + ticks2 - 5`.

The calibration tests (`HalfCycleExactCalibration`, `RepeatedMFC0Count`, `PreciseMeasureJustNOPs`) pass on ares. That holds because ares keeps COUNT at half-PClock resolution (`cpu.hpp:42-43` `pendingCount/effectiveCount`) and `MTC0 COUNT` resets the phase (`interpreter-scc.cpp:171-173` stores `data << 1`). Integer MULT/DIV→MFLO interlock (`HiLoInterlockTiming`) also passes, because ares stalls for the full HI/LO latency at issue (`interpreter-ipu.cpp:289-366`), which matches hardware for that pattern. The uncached write-buffer test and all RSP timing tests pass too.

### How ares charges time (interpreter)

| Event | ares cost | Source |
|---|---|---|
| Any instruction | 1 cycle at fetch | `memory.cpp:158` |
| I-cache miss | +48 | `cpu.hpp:209` |
| D-cache hit (load *or* store) | +1 | `dcache.cpp:61, 90` |
| D-cache miss / writeback | +40 / +40 | `dcache.cpp:7, 16` |
| MULT/DIV family | +4..+68 at issue | `interpreter-ipu.cpp:289-366, 640-647` |
| FPU arithmetic | +(N-1) at issue, fixed N | `interpreter-fpu.cpp:470-1023` |
| Uncached load/store, CP0 ops, CACHE, exceptions, ERET, nullified slots | 0 | — |

Nothing depends on the *next* instruction, so no interlock can be conditional. The interpreter executes one instruction at a time (`cpu.cpp:136-171`), so stage-relative effects cannot be expressed either: fetch-ahead, late CP0 writes, delayed interrupt sampling.

### Exception cost by detection stage (C1)

These are the nemu64-test expected values (JustFire = cycles from issue to the first handler instruction):

- **5**: BREAK, SYSCALL, reserved instruction (`_I28`), coprocessor-unusable (MFC1/MTC1/DMFC1/DMTC1/LWC1/SWC1/SDC1/LDC1 and all COP1 ops with CU1=0), MFC2.
- **6**: integer overflow (ADD/ADDI/DADD/DADDI/SUB/DSUB), all traps, address errors on every load/store kind, LDC1 misalign, invalid COP1 function codes (`_F16/_F31/_F34/_F35/_F38/_F47` in every fmt).
- **7**: COP1 ops on the W/L formats that raise unimplemented-operation (`ADD.W`, `MUL.L`, `CVT.W.W`, …).
- FPU arithmetic exceptions: own latency + 5. For example `ADD.S` overflow 3+5=8, `MUL.S` inexact 5+5=10, `DIV.S` inexact 29+5=34, `ROUND.W.S` inexact 5+5=10, NaN/denormal unimplemented 2+5=7.
- Round-trip (BREAK/SYSCALL + handler + ERET): 15.

Inference: the 5/6/7 split matches the VR4300 detecting these exceptions in RF, EX/DC and the FPU respectively, then flushing and refetching from the vector. Exact stage attribution should be checked against the VR4300 UM exception-priority table and cen64 `fault.c`.

### Operand-dependent FPU latency (C3)

From the nemu64-test tables (hardware-measured):

- ADD/SUB.S/D: 3, or 2 when either operand is 0/−0/±Inf/qNaN.
- MUL.S: 5 (MUL.D 8), or 2 when trivial.
- DIV.S/SQRT.S: 29 (D: 58), or 2 when trivial.
- In a dependency chain the trivial fast path still applies per op. `MUL.S, DIV.S (both trivial)` = 5 = 2 + 1 + 2.

ares implements only the non-trivial number. The NaN/denormal/overflow cases that raise exceptions are counted under C1.

### Recompiler-only divergence (not counted above)

The recompiler fails 185 more timing tests than the interpreter. It has its own cost tables:

- `DIV` 110 vs 37, `DDIV` 206 vs 69.
- `ADD.S` 5 vs 3.
- `C.cond.S` 3 vs 1.
- 16 uncached write-buffer failures.

It passes the 8 `Load Miss (VI disabled)` cases that the interpreter fails. The cause of that difference was not traced. A timing model has to live in one place that both execution paths share. Otherwise the recompiler needs to be fenced off for timing work.

## Raw-result summary

Build:

- ares fork `master` @ `59158c28a`, `RelWithDebInfo`, `-DARES_CORES=n64`.
- Binary `build/rundir/bin/ares`.
- Run with `tools/ares/ares-headless.sh` (mm-decomp-60fps) and `--setting Developer/ForceInterpreter=true --setting Developer/HomebrewMode=true`. The ROM exits itself via emux, and ISViewer output goes to stdout.

ROMs: nemu64-test @ `9a8b9f7`, built with `cargo run --release --no-default-features --features {timing|cycle|cop0hazard}` (nightly-2026-07-16, nust64 0.4.1, `rust:1-bookworm` Docker).

| Set | Interpreter | Recompiler | ares v148 recompiler (earlier run) |
|---|---|---|---|
| Timing | **924 / 1604** fail | 1109 / 1604 | 1593 / 1604 |
| Cycle | **9 / 13** | 10 / 13 | 5 / 13 |
| CP0-hazards | **5 / 5** | 5 / 5 | 5 / 5 |

Interpreter timing failures per test group:

| Group | Fail |
|---|---|
| COP1 instruction (64 bit) | 244 |
| COP1 instruction (32 bit) | 223 |
| CPU register dependency | 199 |
| Exceptions | 135 |
| COP1 register dependency | 59 |
| Cached loads and store | 19 |
| Individual instructions (CPU) | 10 |
| Load from uncached (VI off / on) | 9 / 2 |
| Load Miss (VI off / on) | 8 / 2 |
| Compare (signalling 2) | 7 |
| Likely branch | 4 |
| Data cache Size, Random (decrement), Random (masking) | 1 each |

Passing groups: Repeated MFC0 COUNT, Half cycle calibration, Just NOPs, MULT/DIV→MFLO interlock, 4-element uncached write buffer, Count (overflow), all RSP Timing tests.

The ROM prints failures only, so per-group totals are not shown.

## Sources

- nemu64-test (hardware-measured expected values), https://github.com/thelemmy/nemu64-test @ `9a8b9f7`:
  - `src/tests/timing/mod.rs`: harness `emit_measurement_loop`, `effective_cycles`, all timing tests.
  - `src/tests/timing/cache.rs`.
  - `src/tests/cop0/mod.rs`: Random, COUNT hazards.
  - `src/tests/cop0/compare.rs`.
  - `src/tests/exception_instructions/mod.rs`: SW interrupt hazards.
  - `src/tests/cop1/mod.rs`: CTC1 FPE.
  - `src/tests/cache/icache.rs`: SMC cycle tests.
  - `Cargo.toml`: feature meanings.
- ares fork, https://github.com/wScottSh/ares @ `59158c28a`: `ares/n64/cpu/{cpu.cpp,cpu.hpp,memory.cpp,dcache.cpp,exceptions.cpp,interpreter-ipu.cpp,interpreter-scc.cpp,interpreter-fpu.cpp}`, `ares/n64/mi/bus.hpp`.
- NEC VR4300 / VR4305 / VR4310 User's Manual (U10504EJ):
  - ch. 4 Pipeline (stages, interlocks LDI/MCI/DCM/ICB, branch-likely nullification, exception stages).
  - ch. 5 CP0 (Random/Count/Compare).
  - ch. 6 Exception processing.
  - ch. 7 FPU (per-instruction latency table).
  - The chapter mapping is from the manual's structure. Behavior numbers in this note come from nemu64-test measurements unless stated otherwise.
- cen64 (MarathonMan/cen64 @ `e0641c8`): `vr4300/pipeline.c:162-169` (LDI check), `vr4300/fault.c` (DCM `:243`, ICB `:364`, LDI `:434`, exception faults), `vr4300/fault.h:15-17` (cache and memory delays).
- MiSTer N64 core (`N64_MiSTer` @ `5725381`): `rtl/cpu.vhd` (stall1-4 `:134-140`, `:682`; GPR forwarding `:1269-1272`, `:2076-2083`; FPU forward stall `:1214`, `:2507-2512`), `rtl/cpu_cop0.vhd:129,390` (33-bit COUNT, read `>>1`).
- n64brew wiki: VR4300, RDRAM, RDRAM Interface pages (uncached/miss latency context), https://n64brew.dev/wiki/VR4300.
- Earlier ares v148 numbers: mm-decomp-60fps `docs/research/n64-emulator-accuracy.md`.
