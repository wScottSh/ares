# Recompiler timing parity (CPU and RSP)

Ticket: [#10](https://github.com/wScottSh/ares/issues/10), map [#1](https://github.com/wScottSh/ares/issues/1).
Code base: this fork at `59158c28a` (upstream ares `a776c509b` + agent config). All `file:line` refs are to that tree.

## TL;DR

**Yes for the CPU, conditionally for the RSP. Today they diverge, and the gaps are specific bugs plus one
structural choice (sync granularity).**

- **Three CPU-JIT timing bugs, confirmed on a purpose-built test ROM and on the MM bench:**
  1. The I-cache guard is skipped when a block is entered at a **mid-line internal/alias entry** (e.g. the
     return address after a `JAL`). Lines evicted by the callee are never refilled or charged. This is the whole
     **~17% I-cache miss deficit** of the recompiler.
  2. **Slow paths double-charge** the block's pending deferred cycles plus the instruction's own cycles. This
     happens on every D-cache miss, uncached/MMIO access, FPU slow path and DIV-by-zero slow path that isn't
     preceded by a flush. This bug is the +1 cycle on slow-path memory ops and the DIV 110 / DDIV 206 found
     by nemu64-test in #6.
  3. **The FPU cost tables disagree with the interpreter.** `ADD.S`/`SUB.S` cost 5 cycles in the JIT and 3 in
     the interpreter. All 32 `C.cond.fmt` cost 3 in the JIT and 1 in the interpreter.
- With diagnostic fixes for all three, the RSP interpreter, and per-block sync, the MM bench matches the
  interpreter **within run-to-run noise** (e.g. Mountain Village `game_ticks` +0.003%, `rsp_gfx_ticks`
  +0.013%). The microbenchmarks match to **±1 COP0 Count**. That ±1 is the fetch-charge ordering (row G
  below).
- **RSP JIT:** RSP tasks run **~1.7% longer** than under the RSP interpreter, in all 4 scenes. Two candidate
  causes are known: DMA progress advances only per block, and the main loop overshoots by a block. Neither
  was isolated, so the cause is open.
- **What bit-identical parity under a per-access cost model needs:**
  - Each variable cost (I/D miss, writeback, uncached, MMIO, contention) is computed by **one shared C++
    function** that the JIT reaches from a slow path. No inlined cost constants. The inline I-fill today
    bypasses `Bus`.
  - **One shared static cost table** for both cores.
  - The **clock is exact and charged in the same order** at every access.
  - **Contention resolves the same way regardless of sync granularity.** Either catch up the other bus masters
    at every bus access, or have devices compute their state lazily from timestamps.
  - **Interrupts are taken at the same instruction.** The JIT needs a precise exit at a predicted cycle; today
    it only exits at branch-dispatch checks.
- **ares is not run-to-run deterministic** in the interpreter either: two identical interpreter runs differ by
  up to 1% `game_ticks` in South Clock Town. So bit-identity can't yet be checked on the MM bench, only on
  deterministic microbenchmarks.

## How each core charges time today

**Interpreter (CPU).**
- `CPU::main` calls `synchronize()` after **every** instruction, because `instruction()` returns `true` on the
  interpreter path (`cpu/cpu.cpp:38-40`, `:177-184`).
- Each instruction charges `step(2)` in `fetch()` **before** it executes (`cpu/memory.cpp:157-164`).
- I-cache: hit = 0 extra, miss = `step(96)` (`cpu/cpu.hpp:162-171`, `:208-214`).
- D-cache: hit = `step(2)`, miss = `step(80)` (+80 if dirty writeback) (`cpu/dcache.cpp:6-19`, `:51-94`).
- RCP MMIO read = `step(40)` (`memory/io.hpp:3-8`).
- Multi-cycle ops `step((n-1)*2)` inside the op (`cpu/interpreter-ipu.cpp:289-647`, `cpu/interpreter-fpu.cpp:470+`).

**Recompiler (CPU).**
- A block is a linear window of up to 4 KiB with internal branches. Per-instruction cost goes into
  `emitDeferredCycles` and is flushed only at branches, helper calls, internal labels and line guards
  (`cpu/recompiler.cpp:743-750`, `cpu/recompiler-ipu.cpp:5-36`).
- I-cache guards are emitted only at the block's first instruction and at 32-byte line starts
  (`cpu/recompiler.cpp:721-736`). The miss slow path inlines `step(96)` and a raw `mov128` from `rdram.ram.data`
  (`:809-830`).
- D-cache hit is inline `step(2)` (`cpu/recompiler-ipu.cpp:160-170`). A miss, uncached access or MMIO goes to a
  slow path that calls the interpreter op (`:463`, `:830-837`).
- The dispatcher syncs only when `clock >= jitClockTarget`. The budget is `min(JitInterleaving=4096 clocks,
  timer, next queue event)` (`cpu/cpu.cpp:160-174`, `accuracy.hpp:10`). Inside a block, the exit check is at
  conditional-branch dispatch (`cpu/recompiler.cpp:634-635`).

**RSP.**
- Interpreter: one issue pair per `instruction()`, then `step(pipeline.clocks)`. `dmaStep` runs after every
  pair (`rsp/rsp.cpp:33-86`).
- JIT: the same pipeline model is evaluated at compile time. It is keyed by the entry `pipeline.hash()`, which
  is valid because the model depends only on the instruction stream (`rsp/rsp.hpp:163-233`,
  `rsp/recompiler.cpp:284-330`, `:435-485`). It runs a whole block (a basic block ending after the delay slot).
  `dmaStep` and the `clock < 0` loop test run once per block (`rsp/rsp.cpp:34-46`).

## Divergence table

| # | Area | Interpreter | Recompiler | Effect (measured unless marked) |
|---|---|---|---|---|
| A | I-cache guard at mid-line entries | Every fetch goes through `icache.fetch` (`cpu/memory.cpp:162`, `cpu/cpu.hpp:162-171`) | Guard only at `firstInstruction` or `(vaddr & 0x1f) == 0` (`cpu/recompiler.cpp:721`). Internal labels are bound at `:705-719`, and alias entries jump straight to them (`:673-679`, alias registration `:334-357`). JAL return addresses are made internal entries (`:529-533`) | Lines evicted by the callee are never refilled or charged. **−16.6…−17.6% I-cache misses** on the MM bench. Test ROM T5: 3549 vs 51526 Counts. A guard at internal entries closes the gap exactly |
| B | Slow-path cycle accounting | Base 2 + op-specific cost, once (`cpu/memory.cpp:158`, `cpu/dcache.cpp`) | The slow path flushes the pending `D` (`setupCallf`, `cpu/recompiler-ipu.cpp:29-36`), then adds `instructionCycles` (`cpu/recompiler.cpp:620`, `:838-839`). It then resumes into main code whose compile-time flush adds `D+own` again. If the main path flushed before the resume label (delay slot, branch or helper, `:750`), `instructionCycles` wraps to `-D` and the instruction's own 2 cycles are dropped | Overcharge of `D+2` clocks per slow path taken (D = deferred clocks since the last flush), or `D+2+c` for FPU slow paths. Undercharge of 2 in delay slots (code reading, not measured). Test ROM T4: +9 cycles/iteration, exactly the predicted `(6+2)+(8+2)` clocks. Also explains the nemu64-test results from #6 (next section) |
| C | FPU static costs | `ADD.S`/`SUB.S` 3 cycles (`cpu/interpreter-fpu.cpp:463-471`, `:966-974`). `C.cond.fmt` 1 cycle, no `step` (`:531-534` etc.) | `ADD.S`/`SUB.S` `(5-1)*2` (`cpu/recompiler-fpu.cpp:1075`, `:1092`). All 32 `C.cond.S/D` `(3-1)*2` (`:1386-1581`, `:1909-2104`) | +2 cycles per `ADD.S`/`SUB.S`/`C.cond`. Test ROM T2 and T3: exactly +2 cycles/iteration. All other FPU, MULT and DIV costs match (checked by script) |
| D | Sync granularity | `synchronize()` after every instruction: VI/AI/RSP/RDP/PIF advance per instruction (`cpu/cpu.cpp:39`, `:83-121`) | Sync every ≤4096 clocks, or at the timer/queue event (`cpu/cpu.cpp:164-173`). Device interrupts not in `queue` (VI, SP, DP, AI, MI) are seen up to the budget late. Exit is checked only at branch dispatch (`cpu/recompiler.cpp:634`) | Small on MM. Per-block sync (`interleave=0`) moved totals within noise (rows F, K vs J). Matters for any shared-bus contention model (see below) |
| E | RSP JIT block granularity | `dmaStep` and the `clock<0` test after each issue pair (`rsp/rsp.cpp:34-46`, `:49-86`) | Once per block. DMA busy/full read by `MFC0` mid-block (`rsp/io.cpp:51-59`) shows state as of block start, and RSP runs past the sync target by up to one block | **RSP task time +1.7…1.8%** (`rsp_gfx_ticks`), busy +0.2…0.5 pts. The cause among these two is inferred, not isolated |
| F | Idle loop charging | `beq zero,zero,.` costs 1 cycle + delay slot per iteration | `branchToSelf`/`jumpToSelf` charged 64 cycles (`cpu/recompiler.cpp:745-748`) | Interrupt taken up to ~63 cycles later than in the interpreter (code reading, not measured) |
| G | Charge ordering inside an instruction | Fetch `step(2)` **before** execute (`cpu/memory.cpp:158`) | Base cycles added **after** emit (`cpu/recompiler.cpp:743-750`). Helpers see the clock without the current instruction | The clock seen by `MFC0 Count`, MMIO and any future contention model is 2 clocks earlier in the JIT. Test ROM residual: ±1 Count |
| H | `CACHE` invalidating the executing line | Next fetch misses (`cpu/interpreter-ipu.cpp:120+`) | No re-guard until the next line boundary or block entry (`cpu/recompiler.cpp:721`, `CACHE` is a helper at `cpu/recompiler-ipu.cpp:973-976`) | Missed refill and charge (code reading, not measured) |
| I | I-fill path | `Line::fill` → `Bus::readBurst` → `MI::readRdramBurst` → `rdram.ram.readBurst` (`cpu/cpu.hpp:208-214`, `memory/bus.hpp:27-41`, `mi/bus.hpp:97-116`) | Inline `step(96)` + `mov128` from `rdram.ram.data` (`cpu/recompiler.cpp:814-830`) whenever `rdramMapIdentity` | Equal today. Any cost added in Bus/MI/RDRAM (contention, RDRAM row state, `ebusTestMode`) would be skipped by the JIT |
| J | Profile counters (non-timing) | `icacheHits` counted per instruction (`cpu/cpu.hpp:168`) | Counted per line entry, and only in homebrew mode (`cpu/recompiler.cpp:732-734`). `icacheFillLine` (non-identity map) doesn't count misses (`cpu/cpu.cpp:191-193`) | `ic_hit` isn't comparable across cores. `ic_miss` is (once A is fixed) |

## Measurements

### 1. Microbenchmark ROM (deterministic)

- Files: [`recompiler-parity/timing-test.s`](recompiler-parity/timing-test.s) and
  [`build-rom.py`](recompiler-parity/build-rom.py).
- The code runs from kseg0 RDRAM with interrupts disabled. Each test prints the COP0 Count delta (1 Count = 2
  CPU cycles) for a 10,000-iteration loop (1,000 for T5/T6).
- Binary: the fork built at `59158c28a` + [`diag.patch`](recompiler-parity/diag.patch). With no `DIAG_*`
  variables set, the patch is inert.

| test | interpreter | JIT | JIT + fixes A+B+C | JIT − interp |
|---|---|---|---|---|
| T1 ALU loop (control) | 0x7549 | 0x7549 | 0x7548 | 0 |
| T2 `ADD.S` | 0x9C59 | 0xC368 | 0x9C58 | +9999 Counts = **+2 cyc/iter** (bug C) |
| T3 `C.EQ.S` | 0x7548 | 0x9C58 | 0x7549 | +10000 Counts = **+2 cyc/iter** (bug C) |
| T4 2× D-miss per iter | 0x6F189 | 0x7A151 | 0x6F188 | +45000 Counts = **+9 cyc/iter** (bug B) |
| T5 callee evicts return line | 0xC946 | 0x0DDD | 0xC945 | −48000 Counts = **−2 misses/iter** (bug A) |
| T6 control for T5 | 0x1D95 | 0x1D95 | 0x1D96 | 0 |

The ±1 Count left after the fixes is divergence G (fetch-charge ordering). The JIT row with only the
alias-guard fix (`DIAG_ALIAS_GUARD=1`) gave T5 = 0xC946, identical to the interpreter.

### 2. MM bench (`tools/bench/bench.py`, 4 scenes, warmup 60, 120 frames, 1 run each; sums over 120 frames)

Rows are configs of the same diag binary:
- `cpu`: CPU core (jit or interp).
- `rsp`: RSP core (jit or interp).
- `guard`: fix A.
- `fix`: fixes A+B+C.
- `il0`: sync after every JIT block.

**`ic_miss`**

| config | Great Bay | Mtn Village | S. Clock Town | Termina |
|---|---|---|---|---|
| interp/interp (B) | 2,328,939 | 1,927,913 | 2,520,561 | 2,090,340 |
| interp/interp (B2, repeat) | 2,330,146 | 1,927,876 | 2,513,496 | 2,091,263 |
| jit/jit (A) | 1,922,352 | 1,588,346 | 2,091,706 | 1,743,802 |
| cpu interp / rsp jit (C) | 2,300,852 | 1,928,176 | 2,521,131 | 2,088,892 |
| cpu jit / rsp interp (D) | 1,940,275 | 1,589,755 | 2,092,393 | 1,745,206 |
| jit + guard (E) | 2,293,883 | 1,927,612 | 2,535,692 | 2,084,951 |
| jit + fix, rsp interp, il0 (K) | 2,328,944 | 1,927,993 | 2,518,848 | 2,090,133 |

**`game_ticks` (OS ticks)**

| config | Great Bay | Mtn Village | S. Clock Town | Termina |
|---|---|---|---|---|
| B interp | 164,971,769 | 109,332,659 | 143,290,643 | 136,580,040 |
| B2 interp (repeat) | 165,314,593 | 109,331,754 | 141,828,379 | 136,630,845 |
| A jit | 161,377,820 (−2.2%) | 106,678,841 (−2.4%) | 136,008,702 | 134,990,972 (−1.2%) |
| E jit + guard | 171,239,912 (+3.8%) | 112,999,815 (+3.4%) | 155,999,582 | 141,072,535 (+3.3%) |
| I jit + fix (rsp jit) | 164,301,562 | 109,312,095 | 144,924,763 | 136,382,448 |
| J jit + fix, rsp interp | 165,109,834 | 109,338,538 | 141,895,016 | 136,544,954 |
| K jit + fix, rsp interp, il0 | 165,064,568 | 109,336,329 (+0.003%) | 142,162,606 | 136,580,875 (+0.001%) |

**`rsp_gfx_ticks`**

| config | Great Bay | Mtn Village | S. Clock Town | Termina |
|---|---|---|---|---|
| B interp | 78,749,032 | 40,451,458 | 101,500,646 | 87,259,856 |
| A jit (rsp jit) | 80,180,739 (+1.8%) | 41,135,804 (+1.7%) | 103,293,935 (+1.8%) | 88,773,797 (+1.7%) |
| D cpu jit / rsp interp | 78,838,616 | 40,532,425 | 101,603,081 | 87,368,878 |
| K (rsp interp, il0) | 78,755,926 | 40,456,582 | 101,506,623 | 87,266,536 |

What the bench shows:

- **The I-cache miss gap is entirely CPU-JIT and entirely bug A.**
  - C (CPU interpreter + RSP JIT) ≈ B.
  - D (CPU JIT + RSP interpreter) ≈ A.
  - E (guard only) ≈ B.
- **Fixing A alone overshoots the interpreter by 3–4% (E).** The rest of the JIT's overcharges, B and C, then
  show through. Inference: earlier, the uncharged misses happened to mask them. That explains the prior "1–3%
  lower `game_ms`" on the recompiler.
- **D-cache misses agree within ±1.5% across all configs.** The D-cache is already modeled the same way, and
  misses go to the interpreter.
- **The RSP task-time difference follows the RSP core only.** Rows with the RSP JIT are +1.7%. Rows with the
  RSP interpreter match B.
- **Noise.** B vs B2 (identical interpreter runs) differ by up to 1.0% `game_ticks` (S. Clock Town) and by
  0.0008% (Mtn Village). So ares has a run-to-run nondeterminism source that is independent of the CPU core.
  It was not investigated. Mtn Village is the cleanest scene for A/B work.

### 3. nemu64-test cross-check (logs from closed ticket #6)

Ticket #6 found that the recompiler charges +1 cycle on slow-path memory ops (D-miss 42 vs 41, uncached 2 vs
1). It also found `DIV`/`DIVU` = 110 and `DDIV`/`DDIVU` = 206, where the interpreter and nemu expect 37 and 69
(`nemuruns/timing.recomp.log`). **All of these are bug B, not cost-table drift.** The JIT's MULT/DIV table
matches the interpreter: `cpu/recompiler-ipu.cpp:1337-1455` vs `cpu/interpreter-ipu.cpp:289-647`.

- **Memory slow path with nothing pending (D = 0).**
  - The slow path flushes 0, the interpreter charges the miss, then the path adds `instructionCycles` = 2.
  - The main path then adds the same 2 again.
  - Result: exactly +2 clocks = **+1 cycle**.
- **DIV slow path (divide-by-zero branch, `cpu/recompiler-ipu.cpp:1361-1371`).**
  - `deferSlowPath` is recorded *before* `emitDeferredCycles += 72`, so the op cost lands in
    `instructionCycles` (74).
  - The slow path charges the interpreter's own `step(72)` (`cpu/interpreter-ipu.cpp:315`) + 74, and the main
    path adds 74 again.
  - That is 220 clocks = **110 cycles**. DDIV: 136+138+138 = 412 clocks = **206**. Both match the measurement
    exactly.
  - Inference: nemu's DIV case divides by zero. The 110/206 values can only come from the slow path.
- **The same triple charge applies to every FPU slow path** (NaN, subnormal or exception inputs). In
  `emitFpuOpcode`, `deferSlowPath` also comes before `emitDeferredCycles += cycles`
  (`cpu/recompiler-fpu.cpp:436-447`).
- `DIAG_SLOW_FIX` restores P+2+(interpreter cost) for all of these: one charge, as in the interpreter. Checked
  on T4 only. Rerunning nemu64-test with the patch was not done.
- **D-cache hit = 2 cycles in both cores.** The cores agree, but nemu expects 1 ("LW (cached)": actual 2,
  expected 1, in both logs). That is a hardware-accuracy item, not a parity item.

## What exact parity requires once costs are per-access

1. **One cost function per event, shared by both cores.**
   - Today D-miss, writeback, uncached and MMIO already route through the interpreter's C++ in the JIT
     (slow path → `callf(&CPU::LW…)`). This is the right shape.
   - The I-miss must do the same: call `icacheFillLine` or an equivalent through `Bus`, not inline `step(96)` +
     `mov128` (row I). Contention or RDRAM state then can't be skipped.
   - Hit paths must stay constant-cost. If the model adds hit-path variability (load-use interlocks, write
     buffer, uncached write queue: `DefaultWriteCycles = 0` "until we implement the CPU write queue",
     `memory/io.hpp:4`), the JIT must either emit identical logic or leave the fast path for those cases.
2. **One static cost table.** Rows C and B are table and bookkeeping drift between two hand-maintained
   implementations. Both cores should take per-op cycles from one place (e.g. an `OpInfo` cycles field already
   decoded for both via `decoderEXECUTEInfo`). Slow-path bookkeeping needs the RSP JIT's
   `slowPathFlushedClocks` pattern (`rsp/recompiler.cpp:379-396`) or the correction in `diag.patch`.
3. **Exact clock at each access, charged in the same order.**
   - Pick one convention, either fetch charge before execute or after, and use it in both cores (row G).
   - Flush deferred cycles before every slow path, as the JIT already does via `setupCallf`.
4. **Sync-granularity independence for contention.** With the interpreter syncing every instruction and the
   JIT every ≤4096 clocks, any cost that depends on other masters' state differs between cores. Two designs
   make the outcome independent of granularity:
   - (a) Catch up the RCP devices to the CPU's current clock at every RDRAM or MMIO access. All such accesses
     are already slow paths in the JIT.
   - (b) Time-stamped bus arbitration, where each master posts transactions with timestamps and costs are
     resolved by timestamp, not by who ran first.

   Either way, the interpreter's per-instruction sync should be governed by the same rule. Otherwise it is a
   different model, not a reference.
5. **Interrupts at the same instruction.**
   - The JIT can exit only at branch-dispatch checks and block ends (`cpu/recompiler.cpp:634`, `:799-800`).
   - Each device's next interrupt cycle must be known in advance and fed to `jitClockTarget`. The timer and
     `queue` events already are; VI, AI, SP, DP and MI are not.
   - The JIT then needs a precise stop: either a clock check after each instruction in blocks that can cross
     the target, or falling back to the interpreter for the final stretch.
   - The RSP and RDP are run lazily, so their interrupt time isn't known before they run. This is the hardest
     piece for bit-identity.
6. **RSP JIT.**
   - Make DMA state a function of time, so a mid-block `MFC0 SP_DMA_BUSY` sees the same state as the
     interpreter. That means computing it lazily from `dma.clock` on read, or calling `dmaStep` at helper
     boundaries.
   - Make block overshoot past the sync target either exact or invisible: RSP effects time-stamped, not applied
     at block end.
   - The +1.7% must be attributed before a model is built on the RSP JIT.
7. **Idle and loop shortcuts must be exact or removed.** The 64-cycle branch-to-self (row F) must end at the
   same cycle the interpreter would.
8. **A lockstep checker.** A deterministic ROM suite, like `timing-test.s` but broader, compared on Count
   deltas, plus making ares itself run-to-run deterministic. Then "bit-identical" can be asserted on real
   games, not only microbenchmarks.

## Reproduce

```bash
# fork build (see ticket notes), then apply the diagnostic hooks
git apply docs/research/recompiler-parity/diag.patch && ninja -C build
# env switches (all default off): DIAG_CPU_JIT=0|1  DIAG_RSP_JIT=0|1  DIAG_JIT_INTERLEAVE=<clocks>
#                                 DIAG_ALIAS_GUARD=1 DIAG_SLOW_FIX=1 DIAG_FPU_COST=1
cd ~/repos/mm-decomp-60fps
ARES=<fork>/build/rundir/bin/ares DIAG_ALIAS_GUARD=1 DIAG_SLOW_FIX=1 DIAG_FPU_COST=1 DIAG_RSP_JIT=0 DIAG_JIT_INTERLEAVE=0 \
  tools/bench/bench.py --scene 0,1,2,3 --runs 1 --warmup 60 --frames 120 --jobs 4 --label K
```

The `diag.patch` fixes are diagnostic, not production fixes:
- The FPU change and the slow-path correction assume the interpreter's values are the reference.
- The guard is also emitted at backward-branch targets, where it always hits.

## Sources

- Fork source at `59158c28a`: `ares/n64/cpu/{cpu.cpp,cpu.hpp,memory.cpp,dcache.cpp,recompiler.cpp,recompiler-ipu.cpp,recompiler-fpu.cpp,interpreter-ipu.cpp,interpreter-fpu.cpp}`,
  `ares/n64/rsp/{rsp.cpp,rsp.hpp,recompiler.cpp,dma.cpp,io.cpp}`, `ares/n64/memory/{bus.hpp,io.hpp}`,
  `ares/n64/mi/bus.hpp`, `ares/n64/rdram/rdram.hpp`, `ares/n64/accuracy.hpp`, `ares/n64/system/system.cpp`.
- MM bench harness: `mm-decomp-60fps/tools/bench/{bench.py,README.md}`, `src/code/bench.c` (XPROF columns).
- Raw bench CSVs were in the session scratchpad and are not committed. The tables above are 120-frame sums
  over the per-frame records.
- Cycle values for the VR4300 itself (e.g. whether `C.cond` is 1 cycle) were **not** checked against the NEC
  VR4300 manual in this ticket. This doc treats the interpreter as the reference only for parity, not for
  hardware truth.
