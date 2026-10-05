# RSP→RDP FIFO back-pressure in Majora's Mask

Ticket: wScottSh/ares#8 (map #1). Target: NTSC retail NUS-001 + Expansion Pak, MM US (`n64-us`).

## TL;DR

- MM's graphics ucode is **F3DZEX2.NoN fifo 2.08I** (ID string `RSP Gfx ucode F3DZEX.NoN  fifo 2.08I Yoshitaka Yasumoto/Kawasedo 1999.`). Its text/data MD5s (`ca0a31df…`, `d31cea0e…`) are byte-identical to the `F3DZEX_NoN_2.08I` build of Mr-Wiseguy's matching F3DEX2 disassembly. So that source is MM's ucode, not just a relative of it.
- It runs in **FIFO (RDRAM ring) mode**, not XBUS. It clears `DPC_STATUS.XBUS` at task init. It stages RDP commands in two DMEM buffers: `0x0BA8` and `0x0DB0`, each 0x158 B plus 0xB0 B of slack. When the active buffer passes 0x158 B, the ucode DMAs it (0x160–0x208 B) into a ring in RDRAM.
- The ring is MM's `gGfxSPTaskOutputBuffer`: **0x3000 × 8 B = 96 KiB**, `malloc`'d once from the system heap in `Graph_ThreadEntry`. Low-res and high-res share it. `OSTask.output_buff_size` holds the **end pointer**, not a size.
- **Back-pressure.** Before each chunk DMA, the ucode publishes the *previous* chunk with `DPC_END ← rdpFifoPos` (one-chunk lag). It then busy-polls `DPC_CURRENT` while the RDP's fetch pointer lies inside the region about to be overwritten (`0 < CURRENT − pos ≤ len`).
- **Wrap.** At the ring end it spins on `DPC_STATUS.START_VALID` (a previous wrap is still pending), then on `CURRENT == base`. Only then does it queue `DPC_START ← base`, using the hardware's START/END double buffer. There is no timeout, no yield inside the stall, and no fallback.
- **ares today.** A `DPC_END` write calls `flushCommands()`, which renders synchronously and sets `current = end` in zero emulated time (`ares/n64/rdp/io.cpp:78-87,195-209`, `vulkan/vulkan.cpp:143-146`). Every ucode wait loop therefore exits on its first iteration, so **MM's RSP never stalls on the RDP in ares**.
- ares also has no END_PENDING / END_NEXT double buffer, `DMA_BUSY` reads as 0, and the `DPC_TMEM_BUSY` read is dead code (`if(data == 7)`, `io.cpp:58`, same upstream).

## Behavior table

| # | Behavior | Rule (hardware / ucode) | References | ares today (file:line @ `59158c28a`) | How verified |
|---|---|---|---|---|---|
| 1 | Output mode | FIFO: RSP DMAs commands into an RDRAM ring and RDP fetches from RDRAM (`DPC_STATUS.XBUS = 0`). XBUS variant: RDP reads DMEM directly. "dram" variant: one-shot RDRAM list started later by the CPU via `osDpSetNextBuffer`. MM uses FIFO. | ucode init `task_init` (f3dex2.s:798-823, binary IMEM 0x10C4-0x111C writes `DPC_STATUS ← 1` = CLR_XBUS); SDK microcode page; `sys_ucode.c:10-11` | `command.source` selects RDRAM/DMEM in `render.cpp:56`, `vulkan.cpp:104-119`. Functionally correct. | Disassembled MM's own binary (MD5 match to matching source) |
| 2 | Ring buffer size/placement | `u64[0x3000]` = 96 KiB, `malloc`'d in the system heap; `output_buff` = start, `output_buff_size` = **end address** | mm `src/code/graph.c:372-375,198-199` (HEAD 56fa21dd0); `src/code/sys_cfb.c:12-13,19-27,47-48,64-65`; `include/sys_cfb.h:25,30`; libultra `sptask.c:19-20` converts `output_buff_size` with `_osVirtualToPhysical`, so it is an address | n/a (game memory) | Read decomp source; ucode compares `OSTask+0x2C` (0xFEC) against DPC addresses (binary 0x1274-0x1280) |
| 3 | DMEM staging | Two buffers, swapped with `xori 0x208`: buf1 0x0BA8..0x0D00 (+0xB0 → 0x0DB0), buf2 0x0DB0..0x0F08 (+0xB0 → 0x0FB8). Flush when `ptr > end`, so `dmaLen ∈ [0x160, 0x208]` mid-stream. ovl0 flushes any non-empty remainder. | f3dex2.s:567-581, 990-1031; binary 0x108C/0x1094 (`li $23,0xBA8`, `li $22,0xD00`), 0x12CC (`xori $22,$22,0x208`) | RSP side is emulated exactly: the ucode runs | Binary disasm |
| 4 | Publish lag | Order per flush: wait `SP_DMA_BUSY == 0` (previous chunk landed) → `DPC_END ← rdpFifoPos` (end of **previous** chunk) → check ring space → `rdpFifoPos += len` → start DMA of the **current** chunk. The RDP is always told about data that is already in RDRAM, one chunk late. The final chunk is published in ovl0 after `while_wait_dma_busy` (f3dex2.s:2066-2073, binary 0x2000-0x201C). | f3dex2.s:997-1003 | Same, because the ucode runs as-is. ares then renders immediately on that `DPC_END` write (`io.cpp:85`). | Binary disasm |
| 5 | Overlap stall (main back-pressure) | Spin while `0 < DPC_CURRENT − pos ≤ len`, i.e. while the RDP's fetch pointer is inside `(pos, pos+len]`. If `CURRENT ≤ pos` (RDP is behind in the same lap) or `CURRENT > pos+len` (still in old-lap data beyond the chunk), proceed. | f3dex2.s:1018-1023 (`f3dzex_000012A8`); binary 0x12A8-0x12B8 | `current == end == pos` after every `DPC_END` write, so the first read gives `CURRENT − pos ≤ 0` and the loop never iterates | Binary disasm + ares source read |
| 6 | Wrap | If `pos + len > OUTBUFF_END`: (a) spin while `START_VALID` (a pending START from the previous wrap has not been consumed); (b) spin while `CURRENT == OUTBUFF`; (c) `DPC_START ← OUTBUFF` (queued, pending); `pos ← OUTBUFF`. The next flush's `DPC_END` write commits it. Chunks never straddle the ring end. | f3dex2.s:1004-1016; binary 0x1280-0x12A4 | `startValid` is cleared by every `DPC_END` write (`io.cpp:81-84`) and `current` never equals the ring base at wrap time, so (a) and (b) never spin | Binary disasm + ares source read |
| 7 | Task init / continuation | If `rdpFifoPos ≠ 0` (G_LOAD_UCODE or yield resume), keep the current position. Otherwise, if `XBUS = 0`, `OUTBUFF ≤ DPC_END`, `CURRENT ≠ 0`, `CURRENT < OUTBUFF_END` and `CURRENT ≠ END` (RDP still busy in this ring), **continue appending at `DPC_END`**. Else wait for `START_VALID = 0`, clear XBUS, and set `START = END = OUTBUFF_END`, so the first flush wraps to the ring base. | f3dex2.s:787-823; binary 0x109C-0x111C | Runs as-is. The "RDP still busy" branch is never taken in ares because `CURRENT == END` always | Binary disasm |
| 8 | Yield / G_LOAD_UCODE | ovl0 flushes, waits for DMA and writes `DPC_END` on every exit path (task end, yield, ucode swap). S2DEX2 fifo 2.08 (MM's other gfx ucode) uses the identical protocol with the same `rdpFifoPos` (DMEM 0xF0) and OSTask offsets. Its staging buffers are 0x320 B (`xori 0xC00`, buf1 0x4C0..0x7E0). | f3dex2.s:2065-2077; MM S2DEX2 binary 0x1654-0x16C4, 0x2000-0x201C | Runs as-is | Binary disasm of both MM ucodes |
| 9 | `DPC_START` write | Latches the address only if `START_VALID = 0`; always sets `START_VALID`. Reads return the last latched value. | n64brew RDP/Interface; MiSTer `RDP.vhd:545-549` (comment: n64-systemtest proves the "only if not pending" rule); n64-systemtest `tests/rdp/mod.rs:72-131` | `io.cpp:72-76`: matches | RTL + HW-test source read |
| 10 | `DPC_END` write | If `START_VALID = 0`, extend the current transfer (`END ← v`, DMA busy). If `START_VALID = 1` and the DMA is idle, `CURRENT ← START`, `END ← v`, clear START_VALID. If `START_VALID = 1` and the DMA is busy, set **END_VALID (END_PENDING)** and queue `END_NEXT ← v`; when `CURRENT` reaches `END`, swap `CURRENT ← START_NEXT`, `END ← END_NEXT` and clear both pending bits. A `DPC_END` read returns the last written value (END_NEXT). | n64brew; MiSTer `RDP.vhd:551-566, 595-605, 497-498` | `io.cpp:78-87`: always loads `current = start` immediately. No END_PENDING (the `endValid` field exists, `rdp.hpp:88`, but is never set). The difference is invisible today only because the RDP is never busy. | RTL + ares source read |
| 11 | `DPC_CURRENT` meaning | Fetch (DMA) pointer into the RDP's internal command buffer, not a retire pointer. It advances by 8 per dword copied, so the RSP may overwrite RDRAM as soon as commands are fetched. Internal buffer depth is not documented. MiSTer fetches bursts of ≤ 22 dwords (one max-size triangle) only when its cmd FIFO is empty. n64-systemtest's TODO says CURRENT advances "up to START+240" while frozen (author's note, no test). | n64brew; MiSTer `RDP.vhd:533-535, 682-699`, `RDP_command.vhd:123-131`; n64-systemtest `mod.rs:21-23` | `render.cpp:58-61` advances while executing. Vulkan path sets `current = end` at once (`vulkan.cpp:146`). | Docs + RTL read. The exact HW prefetch depth is an open question. |
| 12 | `DPC_STATUS` bits | 0 XBUS, 1 FREEZE, 2 FLUSH, 3 START_GCLK, 4 TMEM_BUSY, 5 PIPE_BUSY (set at first DMA, held until SYNC_FULL), 6 CMD_BUSY (cmd FIFO non-empty), 7 CBUF_READY, 8 DMA_BUSY, 9 END_VALID, 10 START_VALID | n64brew; MiSTer `RDP.vhd:500-511`; n64-systemtest `mod.rs:150-197` (idle-but-unsynced = `CBUF_READY\|PIPE_BUSY\|START_GCLK`; after SYNC_FULL = `CBUF_READY`) | `io.cpp:23-37`: bit 8 hardwired 0, bit 9 never set. `flushCommands` sets bufferBusy=1 then 0 (`io.cpp:197,207`). pipeBusy stays 1 until `syncFull()` (`render.cpp:617-624`), which matches the HW-test pattern. | Source reads |
| 13 | Counters | `DPC_CLOCK`: 24-bit, counts at RCP clock (62.5 MHz). `BUFBUSY`/`CMD_BUSY`: cycles with the cmd FIFO non-empty. `PIPEBUSY`: first command → SYNC_FULL. `TMEM`: cycles loading TMEM, paused on RDRAM stalls. STATUS write bits 6-9 clear TMEM/PIPE/BUF/CLOCK. | n64brew RDP/Interface | `CLOCK` = scheduler time / 3 (`io.cpp:39-44`, `rdp.cpp:29-35`). BUFBUSY and PIPEBUSY return 0/1 flags, not counts (`io.cpp:46-56`). **TMEM read never executes**: `if(data == 7)` (`io.cpp:58`, same in upstream ares-emulator master). | Source read |
| 14 | MM's ucode does not read counters | F3DZEX2 2.08I and S2DEX2 2.08 touch only `DPC_START/END/CURRENT/STATUS` (no `CLOCK/BUFBUSY/PIPEBUSY/TMEM` reads) | grep of disassembly of both MM binaries | n/a | Binary disasm |
| 15 | DP interrupt / cancel | The frame's DL ends with `gDPFullSync`. The DP IRQ fires when the RDP retires SYNC_FULL. On task cancel MM `bzero`s the whole FIFO and fakes RDP_DONE. | mm `graph.c:293`, `sched.c:197` | `syncFull()` raises `MI::IRQ::DP` during the RSP's final `DPC_END` write, i.e. at SP time, not RDP time (`render.cpp:617-619`, `vulkan.cpp:135-138`) | Source read |

## The RDP-output routine (MM binary, annotated)

Disassembled from `extracted/n64-us/incbin/gspF3DZEX2_NoN_PosLight_fifoText` (load address IMEM 0x1080), using a small scalar-only RSP decoder in the scratchpad (`rspdis/dis.py`). Labels and register names come from Mr-Wiseguy `f3dex2.s`, which matches byte-for-byte. Register roles: `$23` rdpCmdBufPtr, `$22` rdpCmdBufEnd, `$24` DRAM addr, `$19` dmaLen, `$20` DMEM addr. DMEM `0xF0` = rdpFifoPos, `0xFE8` = OSTask.output_buff, `0xFEC` = OSTask.output_buff_size (end ptr).

```
check_rdp_buffer_full_and_run_next_cmd:
1258  addi  $31,$0,0x1194          ; ra = run_next_DL_command
check_rdp_buffer_full:
125C  sub   $11,$23,$22            ; overflow = ptr - end
1260  blez  $11,return_routine     ; still <= 0x158 B staged: no flush
flush_rdp_buffer:
1264  mfc0  $12,SP_DMA_BUSY        ; [stall A] previous chunk DMA still running?
1268  lw    $24,0xF0($0)           ;   $24 = rdpFifoPos (end of data already in RDRAM)
126C  addiu $19,$11,0x158          ;   dmaLen = bytes staged (0x160..0x208)
1270  bne   $12,$0,1264            ;   spin until RSP DMA idle
1274  lw    $12,0xFEC($0)          ;   $12 = ring END address
1278  mtc0  $24,DPC_END            ; publish PREVIOUS chunk to RDP
127C  add   $11,$24,$19            ; newEnd = pos + len
1280  sub   $12,$12,$11
1284  bgez  $12,12A8               ; fits before ring end -> overlap check
1288  mfc0  $11,DPC_STATUS         ; --- wrap path ---
128C  andi  $11,$11,0x400          ; [stall B] START_VALID still pending?
1290  bne   $11,$0,1288
1294  lw    $24,0xFE8($0)          ;   pos = ring base
1298  mfc0  $11,DPC_CURRENT        ; [stall C] spin while CURRENT == ring base
129C  beq   $11,$24,1298
12A0  nop
12A4  mtc0  $24,DPC_START          ; queue START=base (commits on next DPC_END write)
12A8  mfc0  $11,DPC_CURRENT        ; --- overlap check --- [stall D]
12AC  sub   $11,$11,$24            ; d = CURRENT - pos
12B0  blez  $11,12BC               ; d <= 0: RDP not ahead of pos in ring -> go
12B4  sub   $11,$11,$19            ; d - len
12B8  blez  $11,12A8               ; 0 < d <= len: RDP still fetching region -> spin
12BC  add   $11,$24,$19
12C0  sw    $11,0xF0($0)           ; rdpFifoPos = pos + len
12C4  addi  $19,$19,-1             ; DMA length-1
12C8  addi  $20,$22,-0x2158        ; DMEM src = buffer start, negative => write
12CC  xori  $22,$22,0x208          ; swap staging buffers (0xD00 <-> 0xF08)
12D0  j     dma_read_write         ; [stall E] spins on SP_DMA_FULL, then SP_WR_LEN
12D4  addi  $23,$22,-0x158         ; ptr = start of other buffer
```

Task-end tail (ovl0, executes at IMEM 0x1000; offset 0x2000 in the text blob):

```
2000  sub   $11,$23,$22
2004  addiu $12,$11,0x157          ; any bytes staged?
2008  bgezal $12,flush_rdp_buffer
2010  jal   while_wait_dma_busy    ; last chunk must land
2014  lw    $24,0xF0($0)
2018  bltz  $1,taskdone_and_break
201C  mtc0  $24,DPC_END            ; (delay slot: all exit paths) publish last chunk
```

Every stall is an unbounded busy-poll of a COP0 register. The ucode never yields from inside it. A CPU yield request (SIG0) is only checked between DL commands. So while the RDP is the bottleneck, the RSP spends its time in stalls C/D (or B at wrap). The RSP task's wall time then stretches to roughly the RDP's time minus the ring's slack.

## Details

### How far ahead can the RSP get?

- The bound is the ring (96 KiB) minus whatever the RDP has not yet fetched, plus up to 2 × 0x208 B in DMEM.
- Because `DPC_CURRENT` is a fetch pointer (row 11), the RDP may still be executing commands whose RDRAM bytes the RSP is already overwriting. That is safe by design, because the RDP has copied them internally.
- The prefetch depth sets how close the RSP can follow. MiSTer uses ≤ 22 dwords per fetch. The real depth is not documented (n64brew: "no size specified").

### Why the CURRENT == base guard (stall C)?

- The source (f3dex2.s:1012-1015) gives no rationale.
- **Inference:** with `START` pending at `base`, a `CURRENT` equal to `base` cannot be told apart from "the RDP already switched to the new lap". The guard avoids queuing a START equal to the live fetch pointer.
- In MM's steady state, the wrap happens while `CURRENT` is in the high part of the ring, so this loop is expected to fall through. That is an inference from the ring layout. No trace has been taken.

### Why START_VALID polling (stall B) is the double-buffer limit

- The hardware holds at most one pending START/END pair (MiSTer `DPC_START_NEXT/DPC_END_NEXT`, `end_pending`). libdragon's rdpq uses the same rule ("the RDP DMA can hold two buffers in total … wait for END_VALID to become 0", `rsp_rdpq.inc:92-103`).
- F3DZEX2 polls START_VALID instead of END_VALID. Within one lap, F3DZEX2 only ever appends (END writes with START_VALID = 0), and a START is queued only at a wrap. So START_VALID set at the next wrap means the RDP has not yet *finished the previous lap's DMA*.
- With a 96 KiB ring this needs the RDP to be more than one full lap behind, which stall D already prevents. **Inference:** stall B is effectively a safety net in MM.

### Interaction with yields and the next frame

- On a yield, ovl0 publishes everything and the RDP keeps draining while the audio task runs. On resume, `rdpFifoPos` comes back with the DMEM yield image (`task_yield`, f3dex2.s:2118-2145).
- A new gfx task that starts while the RDP is still fetching from the same ring continues at `DPC_END` instead of resetting (row 7). On real hardware, frame N+1's RSP work can therefore overlap frame N's RDP tail, subject to MM's scheduler. Scheduler policy is outside this ticket.

### ares, concretely

- RSP `MFC0/MTC0` with `rd & 8` goes to `rdp.readWord/writeWord` (`ares/n64/rsp/interpreter-scc.cpp:1-11`). RSP-side DPC accesses do not force any thread sync (only CPU-side ones do, `io.cpp:8,14,20…`).
- A `DPC_END` write runs `flushCommands()` (`io.cpp:195-209`), which calls `render()`. With Vulkan, `Vulkan::render()` enqueues to parallel-RDP and sets `current = end` (`vulkan.cpp:82-147`). Otherwise the software loop runs `while(current < end)` (`render.cpp:192`). Both run to completion inside the RSP's `MTC0`, at zero emulated cost.
- `RDP::main()` only ticks `command.clock` (`rdp.cpp:29-35`).
- Consequences for MM:
  - All of stalls B, C and D read a `CURRENT` equal to the just-written `END` (or a cleared START_VALID), so they iterate zero times.
  - RSP gfx time in ares is ucode compute plus RSP-DMA time only.
  - The DP interrupt arrives during the RSP's last instruction, not when the RDP would actually finish.
- Two incidental defects to carry into the timing model:
  1. `DPC_TMEM_BUSY` read is gated on `data == 7` instead of `address == 7` (`io.cpp:58`), so it always reads 0. The same line exists on upstream `ares-emulator/ares` master.
  2. There is no END_PENDING / END_NEXT state, and `DMA_BUSY` is hardwired 0 (`io.cpp:33-34,78-87`). A time-stepped RDP must add both, or a wrap `DPC_END` arriving mid-transfer will jump `CURRENT` early.
- The Vulkan partial-command path sets `current = end` while keeping the tail buffered (`vulkan.cpp:124-128`). F3DZEX2 never publishes a partial command (chunks are whole commands), so MM does not hit it.

### What a timed model needs here (derived from the above)

- An RDP thread whose fetch pointer `CURRENT` advances only when its internal command buffer has room (depth: open question).
- Retirement at modeled cost.
- START/END double buffering with START_VALID/END_VALID/DMA_BUSY.
- `CMD_BUSY`/`PIPEBUSY`/`TMEM` counting.
- DP IRQ at SYNC_FULL retire time.
- RSP reads of `DPC_CURRENT`/`DPC_STATUS` must see RDP progress at the RSP's current timestamp, so the RSP and RDP threads have to be synchronized on those reads, as is already done for CPU reads.
- No ucode-side change is needed: back-pressure emerges from stalls B–D.

## Sources

- Mr-Wiseguy, *f3dex2* matching disassembly, https://github.com/Mr-Wiseguy/f3dex2 @ `bd31393f` — `f3dex2.s` (lines cited), `ucodes_database.mk:247-257` (F3DZEX_NoN_2.08I = "Majora's Mask", MD5_CODE `ca0a31df36dbeda69f09e9850e68c7f7`, MD5_DATA `d31cea0e173c6a4a09e4dfe8f259c91b`).
- MM decomp (`~/repos/mm-decomp-60fps` @ `56fa21dd0`): `extracted/n64-us/incbin/gspF3DZEX2_NoN_PosLight_fifo{Text,Data}` (md5sum equals the above), `gspS2DEX2_fifoText`, `src/code/{graph.c,sys_cfb.c,sys_ucode.c,sched.c}`, `include/sys_cfb.h`, `src/libultra/io/sptask.c`.
- n64brew, *Reality Display Processor/Interface*, https://n64brew.dev/wiki/Reality_Display_Processor/Interface.
- Nintendo 64 SDK online manual, *Microcode* (fifo/dram/xbus, "buffer should be greater than 1K"), https://ultra64.ca/files/documentation/online-manuals/man/n64man/ucode/microcode.html; *OSTask*, https://ultra64.ca/files/documentation/online-manuals/man/n64man/os/OSTask.html.
- MiSTer N64 core, https://github.com/MiSTer-devel/N64_MiSTer @ `5725381706` — `rtl/RDP.vhd:116-139, 497-605, 682-699`, `rtl/RDP_command.vhd:110-131`.
- n64-systemtest (hardware-validated tests), https://github.com/lemmy-64/n64-systemtest @ `196f5421` — `src/tests/rdp/mod.rs`, `src/rdp/rdp.rs`.
- libdragon, https://github.com/DragonMinded/libdragon @ `e356bf3f` — `include/rsp_rdpq.inc:60-130`, `include/rsp_queue.inc:740-840`.
- gopher64 @ `1ab37933` — `src/device/rdp.rs:80-125` (also processes synchronously at `DPC_END`, but schedules the DP interrupt with a timer).
- ares fork, this branch @ `59158c28a`: `ares/n64/rdp/{io.cpp,rdp.cpp,rdp.hpp,render.cpp}`, `ares/n64/vulkan/vulkan.cpp`, `ares/n64/rsp/interpreter-scc.cpp`.
- Prior synthesis: `mm-decomp-60fps/docs/research/n64-emulator-timing-model.md` (rows on RSP→RDP FIFO and DPC counters).
