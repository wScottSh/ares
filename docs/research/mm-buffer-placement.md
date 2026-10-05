# MM framebuffer, Z buffer and DMA-target bank placement

Ticket: wScottSh/ares#23 (map #1). Prerequisite: #4 [rdram-bus-arbitration.md](rdram-bus-arbitration.md) (bank and row model). Target: NTSC MM US 1.0 (`n64-us`), Expansion Pak (8 MiB).

Source: zeldaret/mm `56fa21dd0031a17cfc9e355f609542617598a265` (US 1.0 is the matched version). All `file:line` references below are at that commit. Retail symbol addresses come from `tools/disasm/n64-us/variables.txt`, which the matching build reproduces.

## TL;DR

- **Color and Z never share a bank in normal (lo-res) play.**
  - Color framebuffer 1 is at `0x80000500` (bank 0). Color framebuffer 0 is at `0x807DA800` (bank 7).
  - The Z buffer is at `0x80383AC0` (bank 3).
  - Under the #4 model (bank = addr[22:20], one open 2 KiB row per bank), color/Z alternation inside a span costs **0 row misses**. Each buffer misses only when it walks into a new 2 KiB row. For full-width 320-pixel lines that is about 76 misses per buffer per full-screen pass, or 0.32 per line per buffer.
- **The Z buffer shares bank 3 with the RDP's own command ring.** The ring (`gGfxSPTaskOutputBuffer`, 96 KiB) is at `0x803CEB10..0x803E6B10`. Every RDP command fetch and every RSP chunk DMA into the ring opens a ring row in bank 3, so the next Z access misses. That is 136–273 KB of RDP fetch plus the same volume of RSP writes per frame (#21). This is the main row-miss source for Z, not color.
  - Bank 3 also holds the top 520 KiB of the audio heap, the lo-res work buffer (pause background save) and the start of the Play arena.
- **VI and the RDP's color target are always in different banks.** Double buffering puts the front buffer in the other color bank (0 vs 7). The VI collides instead with CPU and texture traffic in that bank:
  - **Bank 0** (fb1 is front): the hot code text (`z_actor`, `z_bgcheck`, `z_camera`, `z_collision_check`, effects, `z_lib`), boot/libultra text, and the 361 KiB skybox texture buffer.
  - **Bank 7** (fb0 is front): the top of the Play arena. The first tail allocation there is the Kaleido area, which holds `ovl_player_actor` code every unpaused frame (inferred placement). Bank 7 also holds the picto/pause scratch buffers in `gHiBuffer`.
- **Placement is fixed.** The framebuffers are linked at fixed addresses. The Z buffer and the ring are the 2nd and 3rd `malloc` calls on a fresh system heap, made once in `Graph_ThreadEntry`. They never move. MM has no 4 MiB path: it halts without the Expansion Pak (`sys_initial_check.c:106-117`).

## Method

- I read the decomp spec, the buffer declarations, and the code that assigns buffers at run time (`SysCfb_*`, `Graph_ThreadEntry`, `Main`, `GameState_Realloc`, `Play_Init`).
- Static addresses come from the US symbol list. Heap addresses come from replaying the `__osMalloc` allocator on the system heap. I ran a small script for that (appendix).
  - Each node is a 16 B header, sizes are rounded up with `ALIGN16`, and the first node sits at `ALIGN16(heap)` (`src/boot/libc64/__osMalloc.c:113,170-199`; `include/libc64/os_malloc.h:26`, ArenaNode = 0x10 on US).
- **Cross-check against a run-time measurement.** #21 measured the ring in the bench build at `0x3DF5D0..0x3F75D0` and said that build's system heap is 66.7 KiB smaller. My retail chain puts the ring at `0x3CEB10`. The difference is 0x10AC0 = 68,288 B = 66.69 KiB.
  - Replaying the same chain from a heap start 0x10AC0 higher gives the RegEditor node, a 64-aligned Z, and a ring at exactly `0x3DF5D0`.
  - I did not verify independently how #21 derived "66.7 KiB". If #21 derived it from the ring offset, this check is circular. The retail addresses therefore still need the run-time read below.
- No run-time read of retail MM was made in this unit. The headless harness is not ready, and no ares build or ares container is on this machine.

## Allocation chain (source)

1. `Main` sets `sysHeap = SEGMENT_END(buffers)` = `0x803824C0` and `fb = FRAMEBUFFERS_START_ADDR` = `0x80780000`, then `SystemHeap_Init(sysHeap, fb - sysHeap)` (`src/code/main.c:66-71`; `include/buffers.h:53-56`; `variables.txt:2294` gSystemHeap = 0x803824C0, size 0x3FDB40).
2. `Regs_Init` does the first `malloc`: `RegEditor`, 0x15D4 B (`src/code/z_debug.c:10`; `include/regs.h:25`). No other thread allocates before the graph thread. Sched, AudioMgr and PadMgr do not call `malloc`, and audio uses the static `gAudioHeap`.
3. `Graph_ThreadEntry` makes the 2nd allocation, Z + work buffer: `malloc(0x25800 + 0x25800 + 63)`, aligned up to 64 B. The work buffer follows Z (`src/code/graph.c:367-370`).
4. The 3rd allocation is the RDP ring: `malloc(u64[0x3000])`, 96 KiB, shared by lo-res and hi-res (`src/code/graph.c:372-375`).
5. `SysCfb_Init` assigns lo-res fb1 = `gLoBuffer.framebuffer` and fb0 = `gHiBuffer.framebuffer`. Hi-res fb1 = `gLoBuffer.framebufferHiRes` and fb0 = `gHiBuffer.framebufferHiRes` (`src/code/sys_cfb.c:103-115`).
   - `gZBufferHiRes` is never assigned (only `sys_cfb.c:62` reads it). So in hi-res mode (Bomber's Notebook, `z_play.c:1451-1468`) the Z pointer is NULL. `func_8012CF0C` then points the depth image at the color buffer and skips the Z clear (`src/code/z_rcp.c:1469-1473,1487-1488`).
6. Per frame, `Graph_SetNextGfxPool` picks `curFrameBuffer = gFramebuffers[framebufferIndex % 2]` and `zbuffer = gZBufferPtr` (`src/code/graph.c:70-73`). The master DL sets `SETCIMG` to segment 0x0F (current fb) and `SETZIMG` to the Z buffer (`src/code/z_rcp.c:1468-1472`).
7. On Play entry, `GameState_Realloc(state, 0)` takes the largest free system-heap block, which runs up to `0x80780000`, as the two-head arena (THA) (`src/code/game.c:196-218`; `src/code/z_play.c:2150`).
   - Every Play allocation is a THA tail allocation, so they stack downward from `0x80780000` in call order. The first is the Kaleido area, sized to the larger of `ovl_kaleido_scope` and `ovl_player_actor` (`src/code/z_kaleido_manager.c:58-70`). Then come the sram buffer, the message textbox (0x13C00), effects, the scene (object space 1380–1580 KiB, `z_scene.c:47-53`), rooms, collision, interface, the matrix stack, and finally the ZeldaArena, which gets all the remaining space (`z_play.c:2306-2309`).
   - Exact Play addresses depend on the scene. They are not computed here.

## Placement table (8 MiB, lo-res play)

Bank = addr[22:20] and row = addr[19:11], per #4 B6. "Row offset" is the start address mod 2 KiB. Physical address = KSEG0 & 0x1FFFFFFF.

| Buffer | KSEG0 range | Size | Bank | Rows | Row offset | Source (mm `56fa21dd0`) | How derived |
|---|---|---|---|---|---|---|---|
| Lo-res color fb1 (`gLoBuffer.framebuffer`) | 0x80000500–0x80025D00 | 0x25800 | 0 | 0–75 | 0x500 | `spec/spec:8-12` (address 0x80000500); `include/buffers.h:10-16`; `src/code/sys_cfb.c:105` | linked |
| Skybox texture buffer (`gLoBuffer.skyboxBuffer`) | 0x80025D00–0x80080060 | 0x5A360 | 0 | 75–256 | 0x500 | `include/buffers.h:14`; `src/code/z_vr_box.c:250` | linked |
| boot + code text/data/bss | 0x80080060–0x80208EA0 | 0x188E40 | 0–2 | | | `spec/spec:22-24`; `tools/disasm/n64-us/files_code.csv` (code text 0x800A5AC0..) | linked |
| `gGfxSPTaskYieldBuffer` | 0x80208EA0–0x80209AA0 | 0xC00 | 2 | 17–19 | 0x6A0 | `src/buffers/gfxbuffers.c:3`; `variables.txt:2290` | linked |
| `gGfxSPTaskStack` | 0x80209AA0–0x80209EA0 | 0x400 | 2 | 19 | 0x2A0 | `variables.txt:2291` | linked |
| `gGfxPools[0]` (display lists) | 0x80209EA0–0x8022A1B0 | 0x20310 | 2 | 19–84 | 0x6A0 | `src/buffers/gfxbuffers.c:7`; `include/gfx.h:33-42`; `variables.txt:2292` | linked |
| `gGfxPools[1]` | 0x8022A1B0–0x8024A4C0 | 0x20310 | 2 | 84–148 | 0x1B0 | same | linked |
| `gAudioHeap` | 0x8024A4C0–0x803824C0 | 0x138000 | 2 (0x8024A4C0–0x802FFFFF), 3 (0x80300000–0x803824BF) | 148–260 | 0x4C0 | `src/buffers/audio_heap.c:3`; `spec/spec:788-795`; `variables.txt:2293` | linked; internal layout not mapped |
| `RegEditor` (heap #1) | 0x803824D0–0x80383AA4 | 0x15D4 | 3 | 260–263 | 0x4D0 | `src/code/z_debug.c:10` | allocator replay |
| **Z buffer** (`gZBufferLoRes`) | **0x80383AC0–0x803A92C0** | 0x25800 | **3** | 263–338 | 0x2C0 | `src/code/graph.c:367-368` | allocator replay; consistent with #21 bench offset |
| Work buffer (`gWorkBufferLoRes`; pause bg `fbufSave`, picto fallback, fault fb) | 0x803A92C0–0x803CEAC0 | 0x25800 | 3 | 338–413 | 0x2C0 | `src/code/graph.c:370,378`; `src/code/z_play.c:81,2250` | allocator replay |
| **RDP command ring** (`output_buff`..`output_buff_size`) | **0x803CEB10–0x803E6B10** | 0x18000 | **3** | 413–461 | 0x310 | `src/code/graph.c:198-199,372-375` | allocator replay; consistent with #21 |
| Gamestate instance + Play THA (objects, rooms, ZeldaArena actors, Kaleido/Player code at the top) | ≈0x803E6B20–0x80780000 | ≈0x3994E0 | 3–7 | | | `src/code/game.c:196-218`; `src/code/z_play.c:2150,2306-2309`; `src/code/z_kaleido_manager.c:58-70` | inferred bound; scene-dependent inside |
| `gHiBuffer.pictoPhotoI8` | 0x80780000–0x80784600 | 0x4600 | 7 | 256–264 | 0x000 | `spec/spec:797-802`; `include/buffers.h:30`; `variables.txt:2295` | linked |
| `gHiBuffer.D_80784600` (pause `cvgSave`, VisFbuf scratch) | 0x80784600–0x807DA800 | 0x56200 | 7 | 264–436 | 0x600 | `include/buffers.h:31`; `src/code/z_play.c:1121,1395,2252-2254` | linked |
| **Lo-res color fb0** (`gHiBuffer.framebuffer`) | **0x807DA800–0x80800000** | 0x25800 | **7** | 437–511 | 0x000 | `include/buffers.h:32`; `src/code/sys_cfb.c:106`; `variables.txt:2297` (gFramebuffer0) | linked |
| Hi-res fb0 (notebook, 576×454) | 0x80780000–0x807FFB00 | 0x7FB00 | 7 | 256–511 | 0x000 | `include/buffers.h:28`; `sys_cfb.c:111` | linked |
| Hi-res fb1 (notebook) | 0x80000500–0x80080000 | 0x7FB00 | 0 | 0–255 | 0x500 | `include/buffers.h:11`; `sys_cfb.c:110` | linked |

Notes:

- Rows are per bank (512 per 1 MiB bank). A range that crosses a bank boundary lists its first and last row, each in its own bank.
- The Z buffer and work buffer start 64-aligned, at row offset 0x2C0. The ring is 16-aligned (0x310). Neither is 2 KiB aligned, and MM does nothing to row-align any heap buffer.
- Framebuffer row crossings, for a 640 B line (320 × 16-bit). 16 lines = 10,240 B = 5 rows, so the pattern repeats every 16 lines.
  - fb0 and fb1 (row offset a multiple of 0x80) have 60 of 240 lines straddling a row boundary.
  - Z (offset 0x2C0) has 75 of 240.
  - Each buffer touches 75–76 rows per full pass.

## Shared-bank answer and row misses per span

- **Shared bank? No.** Z is in bank 3. The current color buffer is in bank 0 or bank 7, alternating each frame. Both pairs differ. The SDK placement advice ("keeping the color and Z buffers on different banks", pro-man 12.8.1, quoted in #4) is satisfied.
- **Color/Z alternation misses per span, #4 model.** A Z-buffered span does color read, Z read, color write and Z write (#3 rows 2 and 8). Bank 3 keeps the Z row open and bank 0/7 keeps the color row open, so none of the three color↔Z switches per span causes a miss.
  - Misses come only from row changes inside each buffer. A span that straddles a 2 KiB boundary costs 1 extra miss for that buffer. Moving to the next line misses when the line starts in a new row. Over a full-width pass that is 76 rows per buffer, i.e. ≈ 0.32 misses per line per buffer (computed).
  - If color and Z shared a bank, the same span would miss on every switch: up to 3 per span plus the switch from the previous span. MM avoids this.
- **The real bank-3 conflicts are RDP-internal.**
  - The RDP fetches commands from the ring in bank 3 (rows 413–461) while drawing with Z in bank 3 (rows 263–338). Every command-fetch burst between Z accesses costs a ring-row miss, and the next Z access then costs a Z-row miss.
  - The RSP's SP DMA writes into the same ring: 361–717 chunks of 0x160–0x208 B per frame (#21). Each write also displaces the bank-3 open row.
  - The count of fetch bursts per frame depends on the RDP command-DMA burst size, which is not published (#8 row 11, #3 row 16). At the RI's 128 B cap, 136–273 KB/frame is at least 1,060–2,130 bursts (arithmetic). Each burst that lands between two Z accesses costs up to 2 misses.
  - Audio RSP DMA into the upper audio heap (bank 3 part) and the pause-background copy into the work buffer add more bank-3 traffic. Which audio structures sit above 0x80300000 is not mapped here.
- **Color target vs. texture source.** When the RDP draws into fb1 (bank 0), skybox texture loads from `skyboxBuffer` (bank 0, rows 75–256) ping-pong with color rows 0–75. When it draws into fb0 (bank 7), no linked texture source shares bank 7. Object textures are in the Play arena, scene-dependent.

## CPU-heavy regions in VI scanout banks

VI scans the front buffer, which is always the color buffer the RDP is *not* drawing. VI_ORIGIN = physical fb + 640 (`ORIGIN(640)`, `src/libultra/vimodes/vimodentsclan1.c:23,31`; `src/libultra/io/viswapcontext.c:16`). With AA_MODE 0 (#22 vi-fetch), VI reads lines n..n+2. All of those lie inside one 1 MiB bank.

| Front buffer | VI bank | CPU / DMA traffic in the same bank | Evidence |
|---|---|---|---|
| fb1 `0x80000500` | 0 | **Code text** `0x800A5AC0..0x800FFFFF`: `z_actor`, `z_bgcheck`, `z_bg_collect`, `z_camera`, `z_collision_check`, `z_effect*`, `z_eff_*`, `z_draw`, `z_demo`, `z_eventmgr`, `z_kankyo`, `z_lib`, `z_horse`, `z_jpeg`. These are I-cache fills on every frame. | `files_code.csv` (vram < 0x80100000) |
| | 0 | **boot/libultra text** `0x80080060..0x800A5AC0`: thread switch, message queues, `z_std_dma`, `yaz0`, `__osMalloc`, interrupt handlers | `files_boot.csv`; `spec/spec:22-24` |
| | 0 | **Skybox buffer** `0x80025D00..0x80080060`: DMA writes at load, RDP TMEM loads every frame with a skybox | `z_vr_box.c:250` |
| fb0 `0x807DA800` | 7 | **Top of the Play THA**, ≈`0x80700000..0x80780000`. The first tail allocation is the Kaleido area (size = the larger of `ovl_kaleido_scope` and `ovl_player_actor`; player ROM image 0x35060 B), which holds **Player code** in normal play. Below it sit the sram buffer (0x4000), message textbox (0x13C00), effect tables, and so on, in Play_Init order. | `z_kaleido_manager.c:41-45,58-70`; `game.c:196-218`; `file_addresses.csv`. **Inferred placement**, confirm at run time. |
| | 7 | `gHiBuffer` scratch `0x80780000..0x807DA800`: picto photo, pause coverage save, VisFbuf. Busy only in pause, picto box and some transitions. | `z_play.c:251,1121,1395,2251-2254` |

Not in a VI bank: the display-list pools and RSP yield/stack buffers (bank 2), the lower audio heap (bank 2), the Z buffer, ring and work buffer (bank 3), and the middle of the Play arena (banks 4–6, scene-dependent).

## Run-time confirmation recipe

Once the headless harness can read RDRAM and log RDP commands (MM US 1.0, 8 MiB, in any lo-res Play scene):

1. **Pointers.** Read these big-endian words from RDRAM:

   | Symbol | Address | Expected |
   |---|---|---|
   | `gFramebuffers[0]`, `[1]` | 0x801FBB80, 0x801FBB84 | 0x807DA800, 0x80000500 |
   | `gZBufferPtr` | 0x801FBB8C | 0x80383AC0 |
   | `gWorkBuffer` | 0x801FBB90 | 0x803A92C0 |
   | `gGfxSPTaskOutputBufferPtr` / `End` | 0x801FBB94 / 0x801FBB98 | 0x803CEB10 / 0x803E6B10 |
   | `gZBufferLoRes` / `gWorkBufferLoRes` | 0x801FBBA4 / 0x801FBBA8 | 0x80383AC0 / 0x803A92C0 |
   | `gGfxSPTaskOutputBufferLoRes` | 0x801FBBAC | 0x803CEB10 |
   | `sKaleidoAreaPtr` | 0x801D0BA8 | ≈0x8074xxxx–0x8077xxxx (bank 7 expected) |
   | `sZeldaArena` (Arena, head node at +0) | 0x801F5100 | ZeldaArena start; gives the bank of actor instances |
   | `malloc_arena` (head at +0) | 0x8009CD20 | 0x803824C0 |

   Also read `play->state.tha` (`TwoHeadArena {size, start, head, tail}`) from the PlayState. That gives the Play arena bounds.
2. **RDP stream.** In the command log for one frame:
   - `G_SETZIMG` (opcode 0x3E, first byte 0xFE) address = 0x00383AC0.
   - `G_SETCIMG` (0x3F, 0xFF) alternates between 0x00000500 and 0x007DA800 on successive frames. A brief `SETCIMG` = 0x00383AC0 appears for the Z clear (`z_rcp.c:1490`).
   - The first gfx-task `DPC_START` = 0x003CEB10, and `DPC_END` stays within 0x003CEB10..0x003E6B10.
3. **VI.** `VI_ORIGIN` (0xA4400004) alternates 0x00000780 and 0x007DAA80, in phase opposite to `SETCIMG`. That shows the front buffer is never the RDP target.
4. **OSTask.** At each gfx task start, OSTask `output_buff` (DMEM 0xFE8) = 0x803CEB10 and `output_buff_size` (0xFEC) = 0x803E6B10.

If 1 to 4 match, every row of the placement table except the Play arena interior is confirmed. Bank = (phys >> 20) & 7.

## Open questions

1. Exact Play-arena layout per bench scene (Kaleido/Player, object space, ZeldaArena). This needs the run-time read in step 1. It decides how much CPU traffic hits bank 7 while fb0 is front.
2. Audio heap internal layout: which pools (AI output buffers, sample cache, synthesis buffers) fall in the bank-3 part above 0x80300000 and so contend with Z and the ring.
3. RDP command-fetch burst size (#8 row 11). It sets how many bank-3 ring/Z row switches occur per frame. Hardware-only.
4. Whether the RI reorders same-bank requests (#4 open question 2). If it batches, the ring/Z conflict shrinks.

## Appendix: allocator replay

Run with `python layout.py`. It prints the table rows and the row-crossing counts above.

```python
A16=lambda x:(x+15)&~15
NODE=0x10                           # ArenaNode, US
heap=0x803824C0                     # gSystemHeap = SEGMENT_END(buffers)
n0=A16(heap); reg=n0+NODE           # Regs_Init: malloc(0x15D4)
n1=reg+A16(0x15D4); zraw=n1+NODE    # graph.c:367 malloc(2*0x25800+63)
z=(zraw+63)&~63
n2=zraw+A16(0x25800*2+63); ring=n2+NODE   # graph.c:372 malloc(0x18000)
bank=lambda a:(a>>20)&7; row=lambda a:(a>>11)&0x1FF
print(hex(z), hex(z+0x25800), hex(ring), hex(ring+0x18000))
def crossings(base,stride=640,lines=240):
    return sum(((base+y*stride)>>11)!=((base+y*stride+stride-1)>>11) for y in range(lines))
for n,a in [("fb1",0x80000500),("fb0",0x807DA800),("Z",z)]:
    print(n, bank(a), crossings(a), ((a+0x25800-1)>>11)-(a>>11)+1)
```

Output: `0x80383ac0 0x803a92c0 0x803ceb10 0x803e6b10`, then `fb1 0 60 76`, `fb0 7 60 75`, `Z 3 75 76`. Setting `heap=0x803824C0+0x10AC0` gives `ring=0x803df5d0`, which matches #21's bench measurement.

## References

- zeldaret/mm `56fa21dd0031a17cfc9e355f609542617598a265`: `spec/spec`, `include/buffers.h`, `include/gfx.h`, `include/regs.h`, `include/libc64/os_malloc.h`, `src/buffers/{gfxbuffers,audio_heap,framebuffer_lo}.c`, `src/code/{main,graph,sys_cfb,game,z_play,z_rcp,z_kaleido_manager,z_debug,z_scene,z_vr_box,sys_initial_check}.c`, `src/boot/libc64/__osMalloc.c`, `src/libultra/vimodes/vimodentsclan1.c`, `src/libultra/io/viswapcontext.c`, `tools/disasm/n64-us/{variables.txt,files_code.csv,files_boot.csv,file_addresses.csv}`. https://github.com/zeldaret/mm
- #4 `research/rdram-bus-arbitration` (bank/row geometry B6, open-row policy B7, SDK bank advice B16).
- #8 `research/rsp-rdp-fifo` (ring protocol, fetch-pointer semantics).
- #21 `research/mm-rdp-stream` (bytes and chunks per frame, bench ring address).
- #22 `research/vi-fetch` (VI_CTRL, lines fetched per output line).
- #3 `research/rdp-memory-traffic` (span read/write pattern, command fetch).
