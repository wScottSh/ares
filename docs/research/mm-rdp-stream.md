# MM RDP command stream per frame

Ticket: wScottSh/ares#21 (map #1). Prerequisite: #8, [rsp-rdp-fifo.md](https://github.com/wScottSh/ares/blob/research/rsp-rdp-fifo/docs/research/rsp-rdp-fifo.md) (ring protocol, stalls B–D). Target: NTSC MM US (`n64-us`), F3DZEX2.NoN fifo 2.08I.

## TL;DR

- **Bytes per frame.** MM's gfx task pushes **136–273 KB of RDP commands per frame** (medians) through the 96 KiB (98,304 B) ring. The maximum seen is 280 KB. That is **1.4–2.8 ring laps per frame**.
- **The ring wraps every frame, in every bench scene.** Each scene wraps the ring 1–2 times in the middle of the frame, on top of the forced wrap to the ring base at task start. The ring never holds a whole frame.
- **Back-pressure is structural on hardware.** Each frame's stream is larger than the ring. So for MM's RSP gfx task to finish, the RDP must already have fetched at least `bytes − 96 KiB` of that frame. That is about 64% of the frame in Clock Town and Great Bay, and 28% in Mountain Village (inference from the ring protocol in #8, see below).
- **Byte counts are independent of the emulator.** Every frame's count is identical across 5 runs and across two ares builds, and it matches the XPROF `rdram_dp` counter byte for byte.
- **No overlap between frames on the gfx side.** MM's scheduler never starts frame N+1's gfx task while frame N's RDP work is still running. A new (non-yielded) gfx task is dispatched only when **both** `curRSPTask` and `curRDPTask` are NULL. `curRDPTask` is cleared only by the DP interrupt from the frame's `gDPFullSync` (`sched.c:286`, `:532-534`, `:663`). The CPU-side submit also blocks until frame N completes on both SP and DP (`graph.c:156` @HEAD, `sched.c:322-326`).
- **Audio does overlap the RDP.** An audio task needs only the RSP (`audio_thread_manager.c:30`, `sched.c:269-275`), so it runs while the RDP is still executing gfx commands. This happens in two places:
  - the RDP tail after the gfx RSP task has finished;
  - every audio-forced **yield** of the gfx task (`sched.c:411-414`, `228-238`), measured at 1–2 per frame.

  A yielded gfx task resumes with only the RSP free (`sched.c:277-285`). Its RDP stream continues in the same ring.

## Method

- **Instrumentation.** Patched this fork (base `59158c28a`; the patch is in this commit) with an env-gated event log. Setting `ARES_DPLOG=<file>` logs:
  - every `DPC_START`/`DPC_END` write (value, `START_VALID`, `CURRENT`, writer CPU/RSP);
  - `SyncFull` (DP IRQ);
  - RSP task starts with the DMEM OSTask header (`type`, `flags`, `output_buff`, `output_buff_size`);
  - `SP_SET_SIG0` yield requests;
  - RSP `BREAK`;
  - VI interrupts.

  Timestamps are absolute ares thread clocks. Files: `ares/n64/{n64.hpp,cpu/cpu.cpp,rdp/io.cpp,rdp/render.cpp,rsp/io.cpp,rsp/interpreter-ipu.cpp,mi/mi.cpp}`.
- **Bench runs.** `tools/bench/bench.py --scene N --runs 1` on `build/n64-us-bench/mm-n64-us.z64` (mm-decomp-60fps `56fa21dd0` + bench hooks), using the recompiler, warmup 120, 600 measured frames, seed 0x12345678. Link stands at the spawn point, with no input.
- **Frame definition.** A frame runs from one fresh gfx task start (`type=1`, `OS_TASK_YIELDED` clear) to the next. Yielded resumes (`flags&1`) count toward the same frame. The analysis window is the 600 frames that line up with the bench CSV's measured frames.
- **Bytes.** Bytes are the sum of `DPC_END` advances: `END − CURRENT`, or `END − START` when a START is pending. Chunks are the `DPC_END` writes that advance.
  - **Wraps** = RSP `DPC_START` writes equal to `output_buff`, minus the one forced wrap at task start. #8 row 7 explains why a fresh task always initializes at `START=END=output_buff_size` and then wraps to the base on its first flush.
- **Cross-checks.**
  - Per-frame bytes equal the bench CSV `rdram_dp` column (ares XPROF RDP command-DMA bytes) in every frame, in all 4 scenes.
  - The 5-run baseline `bench-results/20261004-165034-baseline-recomp` (ares `a776c509b`) gives identical median, min and max in all 5 runs.
- **Ares RDP is instantaneous**: each `DPC_END` renders synchronously and sets `CURRENT=END` (#8). So the trace shows *what* is emitted and in what order, but not RDP/RSP overlap timing.
  - In ares, `CURRENT` is always equal to `END` at a wrap, and no `DPC_START` was ever written while `START_VALID=1` (0 occurrences). This is expected in ares and says nothing about hardware.
  - The overlap section below is derived from the scheduler code, not from ares timing.

## Per-scene results (600 frames each, 20 fps, divisor 3, 3.00 VI per frame)

| scene | RDP bytes/frame med / p95 / max | ring laps (med / max) | chunks/frame med / max | mid-frame wraps/frame | gfx yields/frame | audio tasks/frame |
|---|---|---|---|---|---|---|
| 0 South Clock Town | 273,008 / 276,880 / 280,352 | 2.78 / 2.85 | 717 / 736 | 2 (600/600 frames) | 2 (600) | 3 |
| 1 Termina Field | 172,104 / 249,360 / 278,608 | 1.75 / 2.83 | 461 / 734 | 1 (508), 2 (92) | 1 (508), 2 (92) | 3 |
| 2 Mountain Village (winter) | 135,988 / 143,992 / 145,928 | 1.38 / 1.48 | 361 / 386 | 1 (600) | 1 (600) | 3 |
| 3 Great Bay Coast | 260,472 / 267,560 / 272,824 | 2.65 / 2.78 | 686 / 716 | 1 (30), 2 (570) | 1 (35), 2 (565) | 3 |

- **Chunk sizes, all scenes.** Median 352 B (0x160), max 520 B (0x208), min 8 B. The 8 B minimum is the task-end publish of a short tail. This matches the `[0x160, 0x208]` mid-stream flush range in #8 row 3, so the ring is about 279 median-size chunks deep.
- **Who writes the DPC registers.** The CPU wrote no `DPC_*` registers at all. Every START/END write comes from the RSP ucode.
- **Bench build caveat.** In retail, `func_80173B48` scales rain, snow and dust counts by the previous frame's RDP time. The bench build disables this (tools/bench/README.md). Inference: on hardware, retail Mountain Village could emit fewer snow commands than measured here when the RDP runs slow.
- **Address caveat.** The bench build's system heap is 66.7 KiB smaller than retail, so the ring sits at a different address (bench: `0x3DF5D0..0x3F75D0`). Its size is the same.

### What "bytes > ring" forces on hardware (inference from #8 stall D)

- The ucode will not DMA a chunk into `(pos, pos+len]` while the RDP's fetch pointer is inside it (#8 row 5). So the RSP can never be more than one ring lap (+ ≤ 2 × 0x208 B staged in DMEM) ahead of the RDP's fetch pointer.
- So the gfx RSP task cannot finish until the RDP has fetched about `frame_bytes − 98,304` B of that frame:

| scene | median bytes RDP must fetch before RSP gfx can finish | share of frame |
|---|---|---|
| South Clock Town | ~174,700 | 64% |
| Termina Field | ~73,800 | 43% |
| Mountain Village | ~37,700 | 28% |
| Great Bay Coast | ~162,200 | 62% |

- Whether stalls C/D actually spin depends on the RDP's per-command cost compared with the RSP's per-command cost. Neither is measurable in ares. If the RDP is slower than the RSP for the first `bytes − 96 KiB`, the RSP waits.
- The RDP-only tail after the RSP finishes is at most about one ring (≤ 96 KiB + the RDP's internal prefetch) of commands.

## Scheduler task-ordering rules (hardware behavior, from source)

`src/code/sched.c` and `src/boot/irqmgr.c` are unmodified from HEAD `56fa21dd0`. `graph.c` lines are cited at HEAD, because the working tree carries bench hooks.

| # | Rule | Source |
|---|---|---|
| 1 | The SP-done and DP-done interrupts become scheduler messages: `OS_EVENT_SP` → `RSP_DONE_MSG`, `OS_EVENT_DP` → `RDP_DONE_MSG`. The VI retrace reaches the scheduler through the IrqMgr client queue as `OS_SC_RETRACE_MSG`. | `sched.c:662-664`; `irqmgr.c:198-208, 268, 276` |
| 2 | The gfx task is a single combined SP+DP task: `scTask->flags = OS_SC_RCP_MASK \| OS_SC_SWAPBUFFER \| OS_SC_LAST_TASK`, where `RCP_MASK = NEEDS_RSP\|NEEDS_RDP`. The DL ends with `gDPPipeSync; gDPFullSync`. | `graph.c:206, 292-293`; `include/PR/sched.h:17-24` |
| 3 | The audio task needs only the RSP (`flags = OS_SC_NEEDS_RSP`). It is submitted once per VI retrace: 3 per frame at divisor 3, as measured. | `audio_thread_manager.c:12, 28-38, 109-110` |
| 4 | **Audio priority.** If the RSP is free and an audio task is queued, the audio task runs first, regardless of the RDP's state. | `sched.c:269-275` |
| 5 | **Fresh gfx task gate.** A non-yielded gfx task that needs the RDP is dispatched only if `state == (OS_SC_SP\|OS_SC_DP)`, i.e. `curRSPTask == NULL && curRDPTask == NULL`. It also needs `Sched_TaskFramebuffersValid`: no swap pending, and the target FB is not the one being scanned out. | `sched.c:276, 286-294, 243-253, 417, 508, 539` |
| 6 | `curRDPTask` is set when the gfx task starts on the RSP, and cleared **only** in `Sched_HandleRDPDone` (DP IRQ = `FullSync` retired). The other path is `Sched_HandleGfxCancel`, which `bzero`s the ring and fakes RDP_DONE. | `sched.c:388-391, 532-534, 191-199` |
| 7 | **Yield.** If an audio task is queued while any RSP task runs, the scheduler calls `osSpTaskYield` (SIG0) on the gfx task. Audio tasks are never yielded. | `sched.c:411-414, 228-238` |
| 8 | **Yielded resume.** On RSP_DONE with a yield, the gfx task is pushed back to the head of the gfx list with `OS_SC_YIELDED`. It resumes as soon as the **RSP alone** is free: no DP check, and `curRDPTask` stays set to it. | `sched.c:493-500, 277-285` |
| 9 | The task is completed (msg to `gfxCtx->queue`, framebuffer swap) only when both its SP and DP bits are cleared. | `sched.c:322-331, 503-504, 534-536` |
| 10 | **CPU pipelining.** `Graph_ExecuteAndDraw` runs `GameState_Update`, which builds frame N+1's DL into the other `gGfxPools[idx%2]`, while frame N's RCP work runs. Only then does `Graph_TaskSet00` block on `gfxCtx->queue` until frame N completes (rule 9), with a 3 s timeout → cancel. | `graph.c:264-270, 300, 332, 150-160` |
| 11 | Retrace and notify both run `Sched_HandleNotify`: enqueue → yield-if-audio → schedule. RSP_DONE and RDP_DONE re-run `Sched_Schedule`. Frame N+1's task is not even queued at frame N's DP IRQ, because the CPU submits only after receiving N's completion message (rules 9, 10). So it starts on the CPU's `Sched_SendNotifyMsg`. If the RSP is then busy with audio, or the FB check fails, it starts on the next RSP_DONE or retrace instead. | `sched.c:400-421, 423-450, 507-511, 538-542, 552-554` |

### Overlap answer

- **Gfx N+1 RSP vs RDP N: never** (rules 5, 6). The ucode's "RDP still busy, append at `DPC_END`" init branch (#8 row 7) is therefore unreachable for a fresh MM gfx task. Every frame starts from the ring base. This matches the trace: every fresh task writes `START=END=output_buff_size`, then `START=output_buff`.
- **Audio RSP vs RDP N: yes**, in two windows.
  - (a) The RDP tail after gfx RSP done. The SP is free and DP is busy, and rule 4 dispatches audio.
  - (b) Each yield (rule 7). The ucode publishes all staged commands before yielding (#8 row 8). The RDP keeps draining while audio runs, and the resumed task continues at the saved `rdpFifoPos` (no ring reset).
  - Measured yields per frame: 1–2. Inference: on hardware, back-pressure stretches the gfx RSP task, so more retrace-driven audio tasks land inside it. That would raise the yield count above what ares shows.
- **CPU vs RCP: yes.** Frame N+1's game logic and DL build overlap frame N's RSP+RDP (rule 10). Submission waits on N's DP IRQ.

## Sources

- **MM decomp** `~/repos/mm-decomp-60fps` @ `56fa21dd0`:
  - `src/code/sched.c` (lines above);
  - `src/code/graph.c` (HEAD lines via `git show HEAD:src/code/graph.c`);
  - `src/code/audio_thread_manager.c`, `src/boot/irqmgr.c`;
  - `include/PR/sched.h`, `include/PR/sptask.h:8-10`, `src/libultra/io/sptask.c:30-36`;
  - `tools/bench/{bench.py,README.md}`, `src/code/bench.c`.
- **#8**: `docs/research/rsp-rdp-fifo.md` on `research/rsp-rdp-fifo` (ring layout, DMEM staging, stalls B–D, task-init rule).
- **This branch**: the instrumentation patch (above) on `59158c28a`. Logs and analyzer (`dpanalyze.py`) were kept in the session scratchpad; the analyzer logic is reproduced in the Method section.
- **Bench data**: `bench-results/20261004-165034-baseline-recomp` (5 runs, ares `a776c509b`), used for the `rdram_dp` cross-check.
