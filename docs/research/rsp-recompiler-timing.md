# RSP recompiler timing divergence

Ticket: [#28](https://github.com/wScottSh/ares/issues/28), map [#1](https://github.com/wScottSh/ares/issues/1), follow-up to [#10](https://github.com/wScottSh/ares/blob/research/recompiler-parity/docs/research/recompiler-parity.md).
Code base: `origin/feat/harness` at `c8592d16a`. The RSP sources there are unchanged from master `59158c28a`, so every `file:line` below holds for both.

## Answer

RSP tasks run longer on the RSP recompiler for two reasons. A third difference changes no task length but moves CPU-visible timing. All three are measured, and together they account for the whole difference: with the first two fixed in the recompiler and the third reproduced in the interpreter, the two cores produce byte-identical stats and task logs over 600 Majora's Mask fields.

| Cause | Share of the extra RSP busy time (CPU interpreter, 600 fields) | Evidence |
|---|---|---|
| A. The block context cache ignores the entry pipeline state | 1,429,071 ticks, 69% | measured |
| B. SP DMA advances once per block, not once per issue pair | 636,204 ticks, 31% | measured |
| C. A block runs past the sync target | 0 ticks with the CPU interpreter; 7,410 ticks with the CPU recompiler. With the CPU interpreter it changes `cpu_cycles` in 224 of 600 fields by up to 40 PClocks | measured |
| Cost tables | 0 | measured: the two cores share one `Pipeline` model, and the outputs are identical once A, B and C are matched |
| Dropped DMA row overshoot (`dma.cpp:67`) | −11,730 ticks if it were carried | measured; it is not a cause of the gap |

Overall, the recompiler adds 2,065,275 ticks (+1.157%) of RSP busy time. Graphics tasks take +1.845% and audio tasks +0.052% (measured). This matches #10's "+1.7…1.8% `rsp_gfx_ticks`".

Recommendation: take the RSP recompiler off the timing path and use the RSP interpreter as the timing reference. Exact parity is possible, but it needs a per-pair budget exit in every block, and per-pair DMA stepping while a DMA is in flight. With the CPU interpreter as the reference, the sync window is one CPU instruction, so a parity-exact RSP block would exit after about one issue pair, which is interpreter granularity at JIT entry cost. The RSP interpreter cost 0.13 to 0.57 s more wall time per 600 fields than the RSP recompiler in this build (measured, noisy, see [Host cost](#host-cost)), against the 2-minute budget.

Units: "ticks" are the core's scheduler clocks, 187.5 MHz, 3 per RCP cycle (`ares/n64/system/system.hpp:37`). `rsp_busy_clocks` and the task log use ticks.

## Mechanisms

### A. Context cache keyed by address only

`RSP::Recompiler::block` hashes the IMEM bytes, the start address and `self.pipeline.hash()` to find a block in the `blocks` set (`ares/n64/rsp/recompiler.cpp:308-317`). Before that it checks the direct-mapped `context[]` array, which is indexed by PC only (`:285-287`, `:305-306`):

```cpp
u32 index = contextIndex(address, callInstructionPrologue);
if(auto block = context[index]) return block;
```

The first block compiled at an address is therefore reused for every later entry, whatever the entry pipeline state. The compiled code bakes in the stall and dual-issue decisions for the state it was compiled with. `emit()` copies `self.pipeline` (`:355`), evaluates the same `Pipeline` model at compile time, and decides dual issue from `pipeline.singleIssue` (`:455`). `Block::execute` then overwrites `self.pipeline` with the end state of the block that ran (`ares/n64/rsp/rsp.hpp:617`), so a wrong entry state also propagates to the next block.

The entry state differs between entries of the same address mainly through `singleIssue`. A taken branch to an address with bit 2 set forces single issue for the first pair at the target (`ares/n64/rsp/rsp.cpp:98`). A fall-through entry does not. The interpreter evaluates this per pair (`ares/n64/rsp/rsp.cpp:63`).

Measured on MM, CPU interpreter, 600 fields (audit mode, which compiles the correct block for comparison and still runs the stale one):

- 9,773,487 context hits, 756,009 of them (7.7%) with an entry state different from the one the block was compiled for.
- Static clocks of the stale block minus static clocks of the correct block, summed over those hits: +1,435,326 ticks. Of that, +1,105,230 ticks come from hits where `singleIssue` differs, and the rest from the `previous[]` hazard state.
- Keying the context cache on the entry state (`M28_CTX_PIPE=1`) removes 1,429,071 ticks of the 2,065,275-tick gap.

### B. DMA stepped per block

`RSP::main` calls `dmaStep(Thread::clock - clock)` once per `instruction()` call (`ares/n64/rsp/rsp.cpp:34-45`). In the interpreter, one call is one issue pair. In the recompiler, it is one block (`:49-52`). `dmaStep` completes at most one row per call (`ares/n64/rsp/dma.cpp:5-12`). So with the recompiler:

- A row that becomes due mid-block lands at the end of the block.
- A `MFC0` of `SP_DMA_BUSY` or `SP_DMA_FULL` mid-block (`ares/n64/rsp/io.cpp:51-59`) sees the state as of the block's start.
- The ucode's DMA wait loops spin until the next block boundary after completion.

Measured: per-task DMA latency (DMA start to busy clear, summed) rises by 709,287 ticks on graphics tasks. Running the interpreter with DMA stepped only at the recompiler's block boundaries (`M28_INTERP_BLOCKDMA=1`) adds exactly the 636,204 ticks that remain after fixing A. Every task's busy time, DMA latency and row count then equals the fixed recompiler's.

Carrying the overshoot of each row into the next (`M28_DMA_CARRY=1`) changes the recompiler's total by −11,730 ticks and the interpreter's by −258. The dropped overshoot at `ares/n64/rsp/dma.cpp:67` is a separate modeling question (#7), not a parity cause.

### C. Block overrun past the sync target

`RSP::main` loops while `Thread::clock < 0`, but the recompiler checks this only between blocks, so it runs up to one block past the target (`ares/n64/rsp/rsp.cpp:34`). The overshoot carries into the next window, so the RSP's own busy count does not change. It changes when the CPU sees RSP state: with the CPU interpreter, which syncs after every instruction, the RSP is up to one block ahead of the CPU.

Measured with the interpreter forced to run whole blocks before checking the clock (`M28_INTERP_BLOCKLOOP=1`):

- CPU interpreter: task busy times unchanged (0 ticks). 224 of 600 fields end at a different `cpu_cycles`, by up to 40 PClocks. 70 tasks are first seen running at a CPU time shifted by −181 to +3 PClocks. The final `cpu_cycles` is unchanged.
- CPU recompiler: 7,410 ticks of busy time, the whole residual between the fixed recompiler and the interpreter with block-granular DMA.

### Isolation result

| Run | CPU core | RSP | Final `rsp_busy_clocks` | Final `cpu_cycles` |
|---|---|---|---|---|
| `ii` | interpreter | interpreter | 178,662,558 | 986,787,919 |
| `ij` | interpreter | recompiler | 180,727,842 | 986,787,919 |
| `ij_ctx` | interpreter | recompiler + A fixed | 179,298,621 | 986,787,865 |
| `ii_bdma_ctxsame` | interpreter | interpreter + B + C emulated | 179,298,621 | 986,787,865 |
| `ji` | recompiler | interpreter | 178,396,857 | 987,121,179 |
| `jj` | recompiler | recompiler | 180,449,304 | 987,120,574 |
| `jj_ctx` | recompiler | recompiler + A fixed | 179,038,089 | 987,121,148 |
| `ji_bdma_bloop` | recompiler | interpreter + B + C emulated | 179,038,089 | 987,121,148 |

All measured. `ij_ctx` and `ii_bdma_ctxsame` have byte-identical stats files (600 fields) and task logs (994 tasks). So do `jj_ctx` and `ji_bdma_bloop`. Two runs each of `ii` and `ij` were byte-identical to each other.

Per task type, CPU interpreter (task logs `ii` vs `ij`, measured):

| OSTask type | Tasks | Interpreter busy | Recompiler busy | Change |
|---|---|---|---|---|
| 1 (graphics) | 464 | 111,091,362 | 113,141,043 | +1.845% |
| 2 (audio) | 529 | 30,075,909 | 30,091,521 | +0.052% |
| other (boot, 1 task) | 1 | 37,356,183 | 37,356,165 | −18 ticks |

## What bit-identical RSP timing requires

If the RSP recompiler stays on the timing path, all of these are needed. Each was checked as a measured emulation, not as a recompiler implementation:

1. **Key the context cache on the entry pipeline state.** A hit must verify the block's entry `Pipeline::hash()`, or the cache must hold one block per (address, entry state). The measurement build checked a stored entry hash on each hit and fell back to the `blocks` set lookup.
2. **Step DMA per issue pair while a DMA is in flight.** The simplest exact rule is that a block runs only when no SP DMA is busy or pending. An `MTC0` to `SP_RD_LEN` or `SP_WR_LEN` must end the block after its pair, the same way `MayHalt` ops check for an exit. While `dma.busy` or `dma.full` is set, `RSP::main` interprets pair by pair. This also covers inline DMEM and IMEM loads, which would otherwise read data before or after a row lands at a different pair than the interpreter. DMA was in flight for about 9% of graphics busy time and 8.5% of audio busy time (inferred from the summed DMA latency over busy time in the `ii` task log).
3. **Exit at the sync target with pair granularity.** After each pair, the block must test `clock + deferred >= 0` and exit with the committed PC and that pair's compile-time pipeline state. The deferred-clock scheme (`ares/n64/rsp/recompiler.cpp:367-395`) allows the test without a flush. With the CPU interpreter, the RSP's window per sync is one CPU instruction, so most blocks would exit after one pair.
4. **Exit states at halt.** A halt exit after `BREAK` or an `MTC0` to `SP_STATUS` leaves `self.pipeline` at the block's end state, because `Block::execute` sets it before the code runs (`ares/n64/rsp/rsp.hpp:617`). It should hold the state at the exiting pair. This is code reading only. It had no measured effect on MM, because the byte-identical runs above did not emulate it.

Items 1 and 2 are enough for equal task busy times with the CPU interpreter. Item 3 is needed for equal CPU-visible timing and for equal busy time under the CPU recompiler.

Any future SP DMA model that depends on other bus masters (#4, #7) widens item 2: DMA progress then depends on the CPU and other devices at sub-block granularity. That is a further reason to keep the RSP recompiler off the timing path.

## Host cost

Wall time for 600 MM fields, CPU recompiler, `--rdp none`, instrumented RelWithDebInfo build with homebrew metrics on, three sequential runs each (measured):

| RSP | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| recompiler (`jj`) | 2.595 s | 2.372 s | 2.215 s |
| recompiler + A fixed (`jj_ctx`) | 2.919 s | 2.472 s | 2.376 s |
| interpreter (`ji`) | 3.169 s | 2.503 s | 2.368 s |

The run-to-run spread (up to 0.8 s) is larger than the differences between cores, so these numbers only show that the RSP core choice moves wall time by under a second per 600 fields. The 2-minute budget is not at risk either way. The harness report measured 1.44 s for `jj` on the uninstrumented build. These runs were not repeated on that build.

## Method

Instrumentation lived only in the measurement worktree and is not delivered. The patch is kept at `C:\Users\Scott\n64-timing\results\measure-28\instrumentation.patch` (282 lines, against `c8592d16a`). It adds these environment switches to `ares/n64/rsp`:

| Switch | Effect |
|---|---|
| `M28_RSP=i` or `j` | Force the RSP interpreter or recompiler regardless of `--cpu` |
| `M28_TASKLOG=FILE` | One line per RSP task (halt-to-halt): OSTask type (DMEM 0xFC0), busy ticks, DMA count, rows, summed DMA latency |
| `M28_CTX_PIPE=1` | Context cache hits must match the entry pipeline hash (fix A) |
| `M28_CTX_AUDIT=1`, `M28_CTXLOG=FILE` | Count context mismatches and the stale-minus-correct static clocks, while still running the stale block |
| `M28_INTERP_BLOCKDMA=1` | Interpreter calls `dmaStep` only at recompiler block boundaries (emulates B) |
| `M28_INTERP_BLOCKLOOP=1` | Interpreter checks `clock < 0` only at recompiler block boundaries (emulates C) |
| `M28_DMA_CARRY=1` | `dmaStep` carries row overshoot |

The interpreter's block boundary follows `RSP::Recompiler::measure` (`ares/n64/rsp/recompiler.cpp:133-147`): a block ends after the pair that follows a branch pair, after an `EndBlock` op, or at a halt.

Commands, from a Git Bash shell, with the patch applied and built through `N64_BUILD_DIR=C:/Users/Scott/n64-timing/build/measure-28 bash tools/n64-timing/build.sh`:

```sh
bash docs/research/rsp-recompiler-timing/run.sh ii  interpreter M28_RSP=i
bash docs/research/rsp-recompiler-timing/run.sh ij  interpreter M28_RSP=j
bash docs/research/rsp-recompiler-timing/run.sh ij_ctx interpreter M28_RSP=j M28_CTX_PIPE=1
bash docs/research/rsp-recompiler-timing/run.sh ii_bdma_ctxsame interpreter M28_RSP=i M28_INTERP_BLOCKDMA=1 M28_INTERP_BLOCKLOOP=1
bash docs/research/rsp-recompiler-timing/run.sh ij_audit interpreter M28_RSP=j M28_CTX_AUDIT=1 M28_CTXLOG=<dir>/ij_audit.ctx
bash docs/research/rsp-recompiler-timing/run.sh jj_ctx recompiler M28_RSP=j M28_CTX_PIPE=1
bash docs/research/rsp-recompiler-timing/run.sh ji_bdma_bloop recompiler M28_RSP=i M28_INTERP_BLOCKDMA=1 M28_INTERP_BLOCKLOOP=1
python docs/research/rsp-recompiler-timing/cmp.py <dir>/ii.tasks.tsv <dir>/ij.tasks.tsv
cmp <dir>/ij_ctx.stats.tsv <dir>/ii_bdma_ctxsame.stats.tsv
```

`run.sh` runs MM for 600 fields with `--rdp none` (the runner default) and prints the final `cpu_cycles`, `rsp_busy_clocks` and stop line. `cmp.py` aligns two task logs by index and sums busy time, DMA latency and rows per OSTask type. Both runs always produced 994 tasks with the same type sequence. Raw outputs are under `C:\Users\Scott\n64-timing\results\measure-28\`.

## Open questions

- Whether the interpreter's pipeline rules themselves match hardware (taken-branch stall, the `branch.pc & 4` single-issue rule, the hazard distances) is outside this ticket. This doc only establishes parity with the interpreter.
- The workload is boot to 600 fields with no input. The MM bench scenes (Great Bay, Mountain Village, South Clock Town, Termina) were not rerun here. #10's measured +1.7…1.8% on those scenes matches the +1.845% graphics-task figure, but the A/B split per scene is not measured.
