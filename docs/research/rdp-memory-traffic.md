# RDP memory traffic and stalls

Research for wScottSh/ares#3 (map: #1). Research date: 2026-10-04. Target: NTSC retail NUS-001 + Expansion Pak.

Companion (not repeated here): `mm-decomp-60fps/docs/research/n64-emulator-timing-model.md` (per-mode compute rates, MiSTer arbitration overview, DPC counter definitions, SDK peak figures).

Tags used below:

- **[src]**: read in the cited source at the stated commit/date.
- **[hw-doc]**: a source that documents hardware (Nintendo SDK, SGI/Nintendo patent, n64brew from hardware tests).
- **[inference]**: my reasoning from the cited sources; not stated by any of them.

## TL;DR

**Per-pixel traffic is set by four Set Other Modes bits, not by blend/AA flags.** In 1-cycle and 2-cycle mode:

- Color (and its 2-bit/3-bit coverage in the hidden 9th bits) is **read only if `IM_RD`** is set. AA (`AA_EN`), `FORCE_BL`, blending and `CLR_ON_CVG` do not cause a read by themselves. Without `IM_RD`, memory coverage is taken as 7 (full) and memory color is undefined.
- Z (with DZ in the hidden bits) is **read only if `Z_CMP`** is set.
- Color is **written for every pixel that survives** coverage rejection, alpha compare and the Z test. `CLR_ON_CVG` still writes (the memory color is written back when coverage does not overflow).
- Z is **written only if `Z_UPD`** is set and the color write happened.

So at 16 bpp:

| Mode | Bytes per drawn pixel |
| --- | --- |
| `G_RM_AA_ZB_OPA_SURF` | 8 B (2 color read + 2 color write + 2 Z read + 2 Z write) |
| `G_RM_ZB_OPA_SURF` | 6 B |
| `G_RM_AA_ZB_XLU_SURF` | 6 B |
| `G_RM_OPA_SURF` | 2 B |

At 32 bpp, double the color part.

**Fill mode** writes only: 64 bits per clock, straight to RDRAM, bypassing the span buffers. Reading color or Z in fill mode hangs the RDP. **Copy mode** writes only: 64 bits (4 px at 16 bpp) per clock, gated by alpha compare.

**Traffic is span-granular, not pixel-granular.**

- For read-modify-write, the memory interface (MI) prefetches the whole span row of color and/or Z into an on-chip **span buffer** as soon as the edge walker knows the span's x-range.
- Pixels are merged in the buffer, and the span is written back to RDRAM "as a block all at once" (SGI/Nintendo patent; SDK §12.2.3).
- The span-buffer RAM is **288 bytes**: 32 rows × 72 bits.
  - Rows 0x00–0x3F (16 rows, 128 B of data + 9th bits) hold color.
  - Rows 0x40–0x7F hold Z **and texture-load data**.
  - It has two color counters and two Z counters that count 16-byte segments and ping-pong. This size comes from n64brew, via the hardware span-test registers.
- RCP→RDRAM transactions are at most 128 B (16 octbytes).
- The exact per-span transaction sizes and the read/write overlap are **not published**.

**Stall mechanism.**

- When the MI is waiting on RDRAM, the RDP **gates its whole-pipeline clock (GCLK) off**. This is visible as `DPC_STATUS` bit 3. The patent calls it a status field for "stalled waiting for access to main memory".
- `TMEM_BUSY` stops counting during such stalls.
- The SDK says 1-cycle mode "is often stalled at MI, waiting for the framebuffer when accessing both color and z". 2-cycle mode "balances" two MI accesses per pixel. Small triangles (short spans) "often stall, pending memory access".
- The SDK recommends putting color and Z in different 1 MB RDRAM banks to cut latency.

**Texture loads** go through the same MI. They are staged in the span-buffer RAM, then shuffled into TMEM. `TMEM_BUSY` counts net load cycles.

**Commands** are fetched by a separate DMA controller into a command-buffer RAM (a FIFO), from RDRAM over the main bus or from DMEM over XBUS. MM uses RDRAM FIFO microcode, so every RDP command crosses RDRAM twice: RSP write, then RDP fetch.

**Measured magnitude.** No public Mpixel/s table exists. The only hardware-derived magnitudes found are:

- F3DEX3's GCLK sampling: RDP stalled on framebuffer/Z I/O "often half to two thirds of the total RDP time".
- SDK: "Z-buffer causes major penalty in fill rate"; `G_PM_1PRIMITIVE` loses up to 1–1.5 Mpixel/s.

**Not public anywhere found:**

- RDP-vs-other-master arbitration priority
- span-read latency in RCP clocks
- whether a span's write-back overlaps the next span's prefetch
- exact span-buffer count/size per mode
- command-buffer depth

These need hardware measurement (see "How it can be verified").

## Behavior table

| # | Behavior | Rule (best available) | References | How it can be verified |
| --- | --- | --- | --- | --- |
| 1 | Color read | 1/2-cycle: read memory color + coverage iff `IM_RD` (othermodes bit 6). Not implied by `AA_EN`, `FORCE_BL`, blend mux, or `CLR_ON_CVG`. Without it: mem cvg = 7, mem color undefined (stale). | SDK pro-man 15.7 ("IM_RD enable color/cvg read/modify/write memory access"); patent US6166748A claim 1(G); n64brew RDP/Pipeline "Image Read"; angrylion `fbuffer.c:181-300` (all `fbread_*` gated by `image_read_en`); MiSTer `RDP.vhd:654-661` | Hardware: draw same tri with/without `IM_RD`, compare `DPC_CLOCK` delta and GCLK-sample ratio; check stale-color artefact pixels against angrylion. |
| 2 | Z read | 1/2-cycle: read Z+DZ iff `Z_CMP`. `Z_UPD` alone does not read. | SDK 15.7 ("Z_CMP condition color write enable on depth comparison"); US6166748A claim 1(E); angrylion `zbuffer.c:231` (`PAIRREAD16` only under `z_compare_en`); MiSTer `RDP.vhd:662-676`; patent "Memory Interface 512 and Z Buffering" (XLU reads Z without updating) | As #1, toggling `Z_CMP`, with Z buffer in same vs other 1 MB bank. |
| 3 | Color write | Written for each pixel that passes coverage (AA: cvg≠0; non-AA: cvbit), alpha compare and Z test. `CLR_ON_CVG` without overflow still writes (memory color re-written, coverage updated). | n64brew Pipeline ("Coverage Pixel Rejection", "Color Image Write"); angrylion `blender.c:259-315`, `rasterizer.c:543-546`; MiSTer `RDP_pipeline.vhd:944-967` | Pixel-exact tests already exist (angrylion conformance); timing effect needs hardware counters. |
| 4 | Z write | Iff `Z_UPD` and the color write happened ("enable writing of Z if color write enabled"). | SDK 15.7; US6166748A claim 1(F); angrylion `rasterizer.c:543-546`; MiSTer `RDP_pipeline.vhd:955` | As #1. |
| 5 | Hidden (9th) bits | Color coverage and Z DZ live in RDRAM's 9th bits and move with the same transfers: no extra transactions. 18-bit pixels ("5 bits each of RGB and a 3-bit coverage"). | SDK pro-man 12.8.1 ("9-bit DRAMs ... two extra bits per color or z pixel"); patent FIG. 32 text; n64brew span-buffer layout (72-bit rows) | n/a (format fact). |
| 6 | Fill mode traffic | Write-only, 64 bits/clk, committed straight to RDRAM bypassing span buffers. `IM_RD`/`Z_CMP` in fill mode hangs the RDP. | SDK 12.1.4 ("fill 64 bits per clock"; "Attempting to read Z when in fill mode can cause the RDP pipeline to hang"); n64brew Pipeline "Fill Pipeline"; angrylion `rasterizer.c:1816-1870` ("RDP crashed") | Hardware: fill-rect of N bytes, `DPC_CLOCK` vs N/8. |
| 7 | Copy mode traffic | No FB/Z read; write of texels passing alpha compare; "64 bits or 4 pixels per clock". | SDK 12.1.5; n64brew Pipeline "Copy Pipeline"; MiSTer skips FB read when cycleType = copy (`RDP.vhd:654`) | Hardware: tex-rect copy, `DPC_CLOCK`. |
| 8 | Span prefetch & write-back | MI prefetches the span row as soon as the span's X/Y is known, holds it in a span buffer, merges pixels, writes the whole span back as one block. Several span buffers exist. | Patent US6331856B1/US6239810B1 "Memory Interface 512 and Z Buffering"; SDK 12.2.3 "Span Buffer Coherency" | Hardware: vary span length L at fixed pixel count; cost should be a + b·L per span, not per pixel. |
| 9 | Span-buffer size | 288 B RAM = 32 rows × 72 bits; rows 0x00–0x3F color (16 × 72 bits = 128 B data), 0x40–0x7F Z + texture-load data. Counters cspan0/cspan1, zspan0/zspan1 count 16-byte segments; each pair ping-pongs (msb opposite) → two color and two Z span slots [inference from counter description]. | n64brew RDP/Interface `DPS_TEST_MODE`/`DPS_BUFTEST_*` (edits by Tharo, 2024-03/2024-10, from hardware); libultra `rcp.h` (`DPS_BUFTEST_ADDR [6:0]`, "Span buffer test access") | Read `DPS_TEST_MODE` counters after drawing spans of known width (already the method used). |
| 10 | Span burst size | Not published. RCP DMA/RI transactions are 1–16 octbytes (≤128 B). [inference] a 16-row color slot = 128 B of data = 64 px @16 bpp; spans longer than a slot need several transactions. | n64brew RDRAM ("RI only supports transfers with 1 to 16 Octbyte"); n64brew RDRAM_Interface "Count" | Logic-analyzer capture on the RDRAM bus during a long span; or `DPC_CLOCK` step at L = 32/64/65 px. |
| 11 | Span coherency penalty | Successive overlapping spans can read stale data; the RDP "does have span buffer coherency, at the cost of some performance". `G_PM_1PRIMITIVE` (atomic primitive) adds 30–40 null cycles after the last span of each primitive. Patent says "adding no cycles" — conflict; SDK better grounded (gives a number, later text, matches a real setting). | SDK 12.2.3; patent "Memory Interface 512"; US6166748A claim 1(k); MM uses `G_PM_1PRIMITIVE` in 6 DLs incl. file-select screen fill (`ovl_file_choose/z_file_choose_NES.c:26`) | Hardware: N small prims with/without `G_PM_1PRIMITIVE`, `DPC_CLOCK` delta / N. |
| 12 | Stall mechanism | When MI waits on RDRAM, GCLK (DPC_STATUS bit 3) drops and the whole pipeline pauses. `TMEM_BUSY` stops during RDRAM stalls. | n64brew RDP/Interface (GCLK, TMEM_BUSY); patent status field 536(2) "stalled waiting for access to main memory"; F3DEX3 `CFG_PROFILING_C` uses GCLK sampling as "waiting for framebuffer / Z buffer memory transactions" | Sample `DPC_STATUS` in a tight loop during draws (F3DEX3 method) → stall fraction. |
| 13 | 1-cycle vs 2-cycle MI balance | 1-cycle with color+Z RMW "often stalled at MI"; 2-cycle's two MI cycles per pixel are "balanced". Small tris: "pipeline is often stalled, pending memory access". | SDK pro-man 12.1.2 and 12.1.3 notes | Hardware: same tri, 1-cycle vs 2-cycle, AA_ZB_OPA vs OPA; if MI-bound, 1-cycle time ≈ 2-cycle time. |
| 14 | Bank placement | Color and Z in different 1 MB banks "improve the DRAM access latency". | SDK pro-man 12.8.1 | Hardware: move Z buffer between banks. MM: cfb/zbuffer addresses in `sys_cfb`. |
| 15 | TMEM load traffic | Loads use the MI (not the command DMA); data is staged in span-buffer rows 0x40+ then shuffled into TMEM. `TMEM_BUSY` = net load cycles. MiSTer: 256 B DDR3 bursts, 1 dword/clk into TMEM (FPGA choice; exceeds the 128 B RCP transaction limit). | Patent "DMA Controller" ("obtains data for its texture memory 502 ... using memory interface 512"); n64brew `DPS_BUFTEST` text; n64brew `DPC_TMEM_BUSY`; MiSTer `RDP.vhd:633-637` | Hardware: LoadBlock of N bytes, compare `TMEM_BUSY` vs `DPC_CLOCK` delta → stall share. |
| 16 | Command fetch | DMA controller fills command-buffer RAM (FIFO) from RDRAM (main bus) or DMEM (XBUS); 64-bit aligned; incremental via `DPC_END`; double-buffered start/end. Depth not published. RDP halts when buffer empty. `CMD_BUSY`/`BUFBUSY` counts cycles FIFO non-empty. MiSTer fetches ≤22 dwords per request (FPGA choice). | Patent "DMA Controller"/"Command Unit"; n64brew RDP/Interface "DMA transfers"; libultra `rcp.h` (`DPC_BUFBUSY_REG`); MiSTer `RDP.vhd:682-696` | Hardware: poll `DPC_CURRENT` while RDP runs long prims → fetch chunk size and FIFO depth from step pattern. |
| 17 | MM command path cost | MM uses `F3DZEX2 ..._fifo`: RSP DMAs commands into a 96 KiB RDRAM FIFO, RDP DMA reads them back → each command byte crosses RDRAM twice. | n64brew RDP/Interface ("double memory bandwidth impact"); SDK pro-man 25.2; companion doc (MM FIFO size) | Count bytes; no hardware needed. |
| 18a | Rejected pixels | A Z-rejected pixel costs its span read but no write: "the Z buffer test is a read only (no write) for obscured pixels"; "The Z-buffer test is a conditional write". Reduced-AA (`G_RM_RA_*`) drops `IM_RD`: "color and the pixel coverage are only written instead of the normal read/modify/write cycle". | SDK pro-man 12.7, 24.4; libdragon `rsp_rdpq.inc:221` (RA = AA blender `& ~SOM_READ_ENABLE`) | Hardware: front-to-back vs back-to-front draw of the same overdraw stack, `DPC_CLOCK` delta. |
| 18b | Row (span) locality | Buffering is per row only: "for single rows span buffers are employed to alleviate stalls ... there is no such buffering across multiple rows". Thin, tall triangles cost more per pixel than wide ones. | n64brew RDP/Commands (Set Color Image); SDK 12.1.2; SDK kantan 2-7 ("maximum bandwidth is rarely attained except with rectangles because the frame buffer is organized in row order") | Hardware: equal-area wide vs tall triangles. |
| 18c | Counters vs stalls | n64brew: `PIPE_BUSY` = gross time from first command to `SYNC_FULL`; GCLK and `TMEM_BUSY` stop on RDRAM stall. SDK `osDpGetCounters`: "PIPE counter ... incremented when the internal RDP pipeline is not stalled while waiting for memory accesses". **Conflict.** n64brew is better grounded (written from hardware tests by libdragon devs, 2024); the SDK text may describe an earlier RCP revision or be wrong [inference]. | n64brew RDP/Interface; SDK n64man `osDpGetCounters` | Hardware: read `DPC_PIPEBUSY` after an idle wait before `SYNC_FULL`. If it keeps counting, the n64brew reading holds. |
| 18d | Stall magnitude | F3DEX3 (Sauraen), measured via GCLK sampling on hardware: stall on FB/Z I/O "often half to two thirds of the total RDP time"; occlusion culling saves "3-4 ms" RDP time. SDK: "Z-buffer causes major penalty in fill rate. Antialiasing also causes some performance loss"; 512×240 no-AA/no-ZB beats 320×240 AA/no-ZB by >25 % in some cases (blockmonkey). | F3DEX3 `docs/Documentation/Configuration.md`, `docs/Code/Counters.md` (commit `91a8528`); SDK pro-man 24.4 | Reproduce with F3DEX3 `CFG_PROFILING_C` on MM scenes on hardware. |
| 18 | Arbitration vs CPU/RSP/VI/AI/PI | Not published. Patent: one sub-block at a time on shared buses; sub-blocks buffer to tolerate unavailability. MiSTer's order is an FPGA choice. | Patent "bus architecture" section; companion doc (MiSTer `DDR3Mux.vhd`) | Ticket #4. Hardware: CPU uncached-read latency while RDP draws. |

## Details

### 1. Read-modify-write conditions

Four othermode bits gate memory traffic. The definitions agree across the SDK manual table (pro-man §15.7, "Mode Bit Descriptions"), the patent claims (US6166748A claim 1) and the reference renderer:

- `AA_EN`: "if no FORCE_BL set, allow blend enable - use cvgbit". This only affects blend enable and coverage rejection. It causes no memory access.
- `Z_CMP`: "condition color write enable on depth comparison". This reads Z.
- `Z_UPD`: "enable writing of Z if color write enabled".
- `IM_RD`: "enable color/cvg read/modify/write memory access". This reads color.

Angrylion-rdp-plus (`9c8b9ed`, used by paraLLEl-RDP as its bit-exact reference) is consistent with this [src]:

- Every `fbread*` function returns stale `memory_color` and `memcvg = 7` unless `image_read_en` is set (`src/core/n64video/rdp/fbuffer.c`).
- `z_compare()` only reads RDRAM under `z_compare_en` (`zbuffer.c:231`).
- `z_store()` only runs under `z_update_en` after a passed write (`rasterizer.c:543-546`).

The MiSTer core (`5725381`) has the same gates:

- The span request reads color only if `imageRead`, and Z only if `zCompare` (`RDP.vhd:654-676`).
- The pixel write requires `zUsePixel` plus coverage and alpha. The Z write additionally requires `zUpdate` (`RDP_pipeline.vhd:944-967`).

The SDK states the practical consequence: in non-Z, non-AA modes "Only the transparent surface mode requires the reading of the frame buffer at render time. The opaque modes simply overwrite the color and zap the coverage" (pro-man §15.7).

**Per-pixel byte table [inference: arithmetic from the gbi.h flag sets in MM `include/PR/gbi.h:627-815` and rules 1–4]:**

| Render mode (16-bpp color, 16-bit Z) | Flags | Color R/W | Z R/W | Bytes/pixel |
| --- | --- | --- | --- | --- |
| `AA_ZB_OPA_SURF`, `AA_ZB_TEX_EDGE`, `AA_ZB_OPA_INTER` | AA, Z_CMP, Z_UPD, IM_RD | 2/2 | 2/2 | 8 |
| `RA_ZB_OPA_SURF` (reduced AA) | AA, Z_CMP, Z_UPD | 0/2 | 2/2 | 6 |
| `AA_ZB_XLU_SURF`, `AA_ZB_OPA_DECAL` | AA, Z_CMP, IM_RD | 2/2 | 2/0 | 6 |
| `ZB_OPA_SURF` | Z_CMP, Z_UPD | 0/2 | 2/2 | 6 |
| `AA_OPA_SURF` | AA, IM_RD | 2/2 | 0 | 4 |
| `XLU_SURF`, `CLD_SURF` | IM_RD | 2/2 | 0 | 4 |
| `OPA_SURF` | none | 0/2 | 0 | 2 |

Reads happen for **every pixel of the span**, including pixels later rejected by Z. Writes happen only for surviving pixels, but see §2: the write-back is per span block, so what goes on the bus for rejected pixels inside a span is not established. Angrylion models 8-bit-mode hidden-bit side effects for rejected pixels (`rejected_hbwrite_1cycle`, `rasterizer.c:190-267`, and `rdram_hidden_old[8]` in `rdram.c`), which hints that writes go out in whole memory words with merge logic. [inference]

### 2. Span buffers, granularity and bursts

**Patent** (US6331856B1 and US6239810B1 share the description; section "Memory Interface 512 and Z Buffering"):

> "For RMW operations, memory interface 512 ... pre-fetches a row of pixels from frame buffer 118 a as soon as edge walker 504 determines the x, y coordinates of the span. Memory interface 512 includes an internal "span buffer" 512 a used to store this span or row of pixels ... Span buffer 512 a is also used to temporarily store blended (modified) pixel values so that display processor 500 need not access main memory 300 each time a new pixel value is blended. In general, memory interface 512 writes the entire span worth of pixels into main memory 300 as a block all at once."

> "Memory interface 512 has enough on-chip RAM to hold several span buffers."

Overview section: "Memory interface 512 has one or more pixel caches to reduce the number of accesses to main memory 300."

**SDK** pro-man §12.2.3 says the same in near-identical words, and adds: "The RDP does have span buffer coherency, at the cost of some performance. If errors are objectionable ... use gsDPPipelineMode (G_PM_1PRIMITIVE) to cause all primitives to add between 30 to 40 null cycles after the last span of a primitive is rendered."

**Conflict.** The patent says the atomic-primitive mode works "by adding no cycles after the last span". The SDK says "30 to 40 null cycles".

- The SDK is better grounded: it is the shipped programmer documentation, it gives a number, and it is tied to the actual `G_PM_1PRIMITIVE` bit.
- The patent wording reads like a dropped number. [inference]

**Physical size.** n64brew RDP/Interface, `DPS_BUFTEST_ADDR`/`DPS_TEST_MODE`, written by Tharo in 2024 from hardware access via the span test registers:

> "Span buffers are 288 bytes of memory while a 7-bit word index can address up to 512 bytes ... 72 bits are accessed over 4 word addresses ... The first half of the rows up to 0x40 only hold color data while the second half of the rows from 0x40 onwards hold depth and texture data. Texture data is held in spans as it is loaded from RDRAM before being shuffled into TMEM."

The `DPS_TEST_MODE` read fields are:

- `cspan0`/`cspan1`: "Increments ... based on how many 16-byte segments a drawn primitive covers"
- `zspan0`/`zspan1`: the same, "only when depth read or write is enabled"
- Within each pair: "if the other counter has the msbit unset this one has it set and vice-versa"

libultra `rcp.h` independently names the registers "Span buffer test access enable" and "span buffer test address [6:0]".

The span buffer thus holds:

- 16 × 72-bit color rows = 128 B of color data plus 9th bits, which is 64 px at 16 bpp or 32 px at 32 bpp
- the same for Z (or texture)

The paired counters with opposite MSBs indicate **two slots each for color and Z (ping-pong)**. That would give 64 B = 32 px @16 bpp per slot, so that one span can be in flight to/from RDRAM while the pipeline works on another. [inference: from the counter description; slot size not directly stated]

**Bus transaction size.** RCP DMA/RI transfers are 1–16 octbytes, i.e. ≤128 B (n64brew RDRAM, RDRAM_Interface "Count"). Whatever the slot size, a span read is a short RDRAM burst whose fixed cost (packet plus read latency) is amortized over only a few to a few dozen pixels. That is the mechanism behind the SDK statement that small triangles stall. [inference]

**Not public:**

- whether a span read covers exactly [xmin, xmax] rounded to 8-byte words
- whether partial-coverage pixels are written with byte masks or a full word
- whether span write-back and next-span prefetch overlap
- RDRAM page-hit behavior for successive scanlines

**Emulator/RTL state** [src]:

- MiSTer reads the whole span as one DDR3 burst before rendering the line and blocks the raster until done (`RDP_raster.vhd:720-742`, `RDP.vhd:638-676`).
- MiSTer writes each pixel as a separate byte-masked 64-bit FIFO entry (`RDP.vhd` `fifoout`; `DDR3Mux.vhd:341-346`). This is not hardware-like on either side.
- ares, gopher64, simple64, mupen64plus and cen64 model no RDP memory traffic (companion doc).

### 3. Stalls waiting for memory

- **GCLK.** n64brew RDP/Interface `DPC_STATUS` bit 3: "This bit is the main gated clock for the whole RDP pipeline; when it is 0, the pipeline is paused. The RDP stops this clock any time it is stalled for RDRAM."
  - The patent's status register lists a field for "whether the display processor is stalled waiting for access to main memory 300 (field 536(2))".
  - libultra's name for bit 3 is `DPC_STATUS_START_GCLK`, with a commented-out older `DPC_STATUS_FROZEN` at the same bit (`rcp.h`).
  - F3DEX3's `CFG_PROFILING_C` samples this bit per display-list command "to get an approximate measurement of the percentage of time the RDP was doing useful work, as opposed to waiting for framebuffer / Z buffer memory transactions to complete".
  - So the stall is **a whole-pipeline freeze**, not a per-stage bubble.
- **Counter conflict.**
  - SDK `osDpGetCounters`: "PIPE counter. This counter is incremented when the internal RDP pipeline is not stalled while waiting for memory accesses to occur."
  - n64brew: `PIPE_BUSY` counts gross time until `SYNC_FULL`.
  - See row 18c. If the SDK reading were true, `CLOCK − PIPE` would directly give stall cycles.
- **TMEM_BUSY** "is stopped during cycles in which the RDP is stalled for RDRAM" (n64brew).
- **SDK, pro-man 12.1.2** (1-cycle): "Reaching peak bandwidth is difficult. The framebuffer memory is organized in row order. In small triangles, it is rare to have long horizontal runs of pixels on a single scanline. In these cases, the pipeline is often stalled, pending memory access for read or write cycles."
- **SDK, pro-man 12.1.3** (note under the 2-cycle table): "MI0 and MI1 represent two cycles of the MI that access color and z framebuffer cycles, respectively ... The MI does not need to run two cycles to perform color and Z-buffer access. One cycle per pixel mode can also perform color and Z-buffer accesses. The reason for this representation is to show that two MI access cycles are balanced in the two-cycle mode. **In one-cycle mode, the pipeline is often stalled at MI, waiting for the framebuffer when accessing both color and z.**"
- **SDK, pro-man 12.8.1**: "The DRAM has dual banks, one on each 1 MB. By keeping the color and Z buffers on different banks, you can improve the DRAM access latency when the RDP is seeking DRAM bandwidth for rendering."
  - On the Expansion Pak console there are 8 such 1 MB regions. RI maps bank N to megabyte N (n64brew RDRAM: "It expects Bank zero to be in the first megabyte of address space, Bank one in the second megabyte").

Back-of-envelope [inference]:

- 1-cycle `AA_ZB_OPA_SURF` at 16 bpp needs 8 B/px × 62.5 Mpx/s = 500 MB/s.
- That is roughly the whole RDRAM peak (RCLK = 250 MHz per n64brew Clock_Timing; Rambus transfers on both edges → 500 M transfers/s × 8 data bits ≈ 500 MB/s; the patent says only "on the order of 240 MHz", "9-bit-wide"), before any per-transaction overhead, VI scan-out or CPU/RSP traffic.
- So the SDK's "often stalled at MI" for color+Z in 1-cycle mode follows from the byte counts alone.
- 2-cycle mode halves the demand to ~250 MB/s.

**Measured magnitude.** These are the only hardware-derived numbers found:

- F3DEX3 Configuration doc: "A counter enabling a rough measurement of how long the RDP was stalled waiting for RDRAM for I/O to the framebuffer / Z buffer (spoiler: often half to two thirds of the total RDP time!)".
- SDK pro-man 24.4: "Z-buffer causes major penalty in fill rate", and the blockmonkey resolution comparison.
- SDK `gDPPipelineMode`: the atomic-primitive loss "will be no greater than 1.5M pixels per second".
- An anecdotal Hacker News comment (user mips_r4300i, item 39829383) claims Z "only get[s] 8 pixel chunks at a time ... will torpedo your effective fill rate by 20 to 40 percent". It is unsourced, so I list it only as a pointer, not as evidence for burst size.

### 4. Texture loads

- Patent ("DMA Controller"): "display processor 500 obtains data for its texture memory 502 by passing texture load commands to command unit 514 and using memory interface 512 to perform those commands." Loads therefore use the MI, not the command DMA.
- n64brew: load data is staged in span-buffer rows (Z/texture half) "before being shuffled into TMEM". The loading pipeline "appears to share some resources with the rendering pipelines as they cannot be executed in parallel" (n64brew Pipeline).
- `TMEM_BUSY` counts net load time (n64brew).
- SDK pro-man 13.9: LoadBlock "allows the MI to transfer the maximum amount of data for each transfer", so it is more bandwidth-efficient than LoadTile, which fetches per texture row. n64brew: "Load Tile is slower than Load Block".
- TMEM itself is 4 banks × 256 × 16-bit words, giving 4 texels/clk (patent; SDK 12.4).
- RDRAM side [inference]: a LoadBlock/LoadTile line is a sequential read of the source; transaction size is bounded by the span-slot size and 128 B.
- MiSTer uses 256 B DDR3 bursts per line, then writes 1 dword/clk (`RDP.vhd:633-637`). That burst size cannot be hardware's (exceeds the 128 B limit).
- The per-line rate is the subject of #2.

### 5. Command fetch

- Patent:
  - "DMA controller 518 reads data over main coprocessor bus 214 if registers 518 a, 518 b specify a main memory 300 address, and it reads data from the signal processor's data memory 404 over private "x bus" ... DMA controller 518 is uni-directional ... can only write from bus 214 into RAM 516."
  - "Display processor 500 halts if its command buffer RAM 516 is empty ... which buffer acts as a FIFO."
- n64brew RDP/Interface:
  - The RDP "will start fetching commands in small batches into an internal FIFO queue ... the DMA will then wait for space to become available".
  - Addresses are 8-byte aligned.
  - `DPC_END` can be extended incrementally.
  - One pending transfer is double-buffered.
  - `CMD_BUSY` (`DPC_BUFBUSY` in libultra) counts cycles with the FIFO non-empty.
- FIFO depth and batch size are not published.
- MiSTer requests ≤22 dwords (176 B, "max length for tri with all options on") per fetch (`RDP.vhd:682-696`). This is an FPGA convenience, and larger than the 128 B RCP transaction limit [inference].
- MM path: the SDK (pro-man 25.2) describes FIFO microcode writing "all the commands to a larger FIFO buffer in RDRAM ... to prevent the RSP from stalling when the RDP gets bound by processing large triangles".
  - n64brew notes the libultra path causes "a double memory bandwidth impact".
  - MM's FIFO is 96 KiB (companion doc).
  - The SDK (old manual, pro-man 25.4) says XBUS microcode has "I/O to RDRAM ... smaller than with FIFO (around 1/2)", and so can counteract "slowdowns caused by competition on the RDRAM bus". It cannot overlap RDP work with audio tasks.

### 6. What this means for an ares timing model [inference]

Per span, charge in this order:

1. If `IM_RD` and/or `Z_CMP`, prefetch requests of ⌈span bytes⌉ rounded to 8 B, split at the slot/128 B size, for the color and Z images.
2. Pipeline cycles at the mode rate.
3. A write-back of the covered range for color, and for Z if `Z_UPD`.

Then:

- Gate the RDP clock while a needed prefetch has not completed, or while no free slot exists for write-back.
- Fill and copy write directly, at 8 B per clock.
- TMEM loads and command fetches are further RDRAM requesters from the same RDP.
- Add 30–40 cycles per primitive under `G_PM_1PRIMITIVE`.

The unknowns flagged above (slot size, overlap, arbitration, latency) are the calibration parameters.

## New questions surfaced

1. **Span slot size and double-buffering.** Is a color/Z slot 64 B (two per kind) or 128 B (one)? Does the next span's prefetch overlap the previous write-back? Measure with `DPS_TEST_MODE` counters plus a `DPC_CLOCK` sweep over span width.
2. **Rejected-pixel write traffic at the bus level.** The SDK says obscured pixels are "read only (no write)". The patent says spans are written back "as a block all at once". Is a span with some rejected pixels written as one masked burst, or as several bursts split at the rejected runs? This changes the transaction count, though not bytes/pixel.
3. **Arbitration priority of RDP MI vs VI/CPU/RSP** (feeds #4). The SDK only implies the RDP waits.
4. **MM file-select full-screen RMW pass (feeds #11).** `FileSelect_Main` ends every frame, with no condition on alpha, with a 1-cycle `G_RM_CLD_SURF` fill (`IM_RD`, `FORCE_BL`, `G_PM_1PRIMITIVE`) over the whole framebuffer:
   - `sScreenFillSetupDL` + `D_0E000000.fillRect` = `gDPFillRectangle(0,0,gCfbWidth,gCfbHeight)`; see `z_file_choose_NES.c:2402-2405` and `z_rcp.c:1520-1522`.
   - By rules 1, 3 and 8, that is 320×240 px × (2 B read + 2 B write) ≈ 300 KiB of span RMW traffic plus ≥76,800 pipeline cycles (≥1.23 ms) per frame, even when `screenFillAlpha` is 0. [inference: assumes 320×240 16-bpp cfb]
   - ares charges it zero. It is a concrete, hardware-only cost to include when quantifying the file-menu slowdown (ares #2320).

## Sources

Primary hardware documentation:

- Nintendo 64 Programming Manual (SDK 5.1 online), ch. 12 "RDP Programming": §12.1.2–12.1.5, §12.2.3, §12.4, §12.8.1. https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro12/12-01.htm, `.../pro12/12-02.htm`, `.../pro12/12-08.htm`
- Same manual, §15.7 (render-mode bit table, IM_RD/Z_CMP/Z_UPD): `.../pro15/15-07.htm`; §25.2 (FIFO microcode): `.../pro25/25-02.htm`
- US6331856B1, US6239810B1, US6556197B1, US6593929B2 (Van Hook et al., SGI/Nintendo, priority 1995-11-22): sections "Memory Interface 512 and Z Buffering", "DMA Controller", "Command Unit", "Texture Memory Loading". https://patents.google.com/patent/US6331856B1/en, https://patents.google.com/patent/US6239810B1/en
- US6166748A claims 1, 7, 8 (Set Other Modes fields): https://patents.google.com/patent/US6166748A/en
- US5742277A (SGI, VI antialiasing; Z not read by VI for bandwidth): https://patents.google.com/patent/US5742277
- Same manual: §12.7 (front-to-back Z), §13.8–13.9 (LoadBlock efficiency), §24.4 (fill-rate tips, blockmonkey), §9.10 (cfb/Z on different MB banks), §3.7 (RDRAM 250 MHz, 500 M/s); man pages `gDPPipelineMode`, `gDPSetCycleType`, `osDpGetCounters` (`.../n64man/gdp/`, `.../n64man/os/`); old manual pro-man 25.4 (XBUS vs FIFO): https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro25/25-04.html
- libultra `PR/rcp.h` (DPC/DPS register names): decompals/N64-IPL `928f590` `include/PR/rcp.h:316-377`

Community hardware documentation:

- n64brew, Reality Display Processor/Interface (DMA, DPC_STATUS GCLK, counters, DPS span-buffer layout; revisions by Rasky 2023–24, Tharo 2024-03-21 and 2024-10-16): https://n64brew.dev/wiki/Reality_Display_Processor/Interface
- n64brew, Reality Display Processor/Pipeline: https://n64brew.dev/wiki/Reality_Display_Processor/Pipeline
- n64brew, RDRAM and RDRAM Interface (≤16-octbyte transactions; bank per MB): https://n64brew.dev/wiki/RDRAM, https://n64brew.dev/wiki/RDRAM_Interface
- n64brew, Reality Display Processor/Commands (atomic_prim, Set Color Image row note, Load Block vs Load Tile, sync cycle counts): https://n64brew.dev/wiki/Reality_Display_Processor/Commands
- n64brew, Clock_Timing (RCLK 250 MHz, RCP 62.5 MHz): https://n64brew.dev/wiki/Clock_Timing
- F3DEX3 `91a8528`, Configuration (stall share): https://github.com/HackerN64/F3DEX3/blob/91a85284821181af627d838e47d245718804f388/docs/Documentation/Configuration.md
- libdragon `e356bf3`: `include/rdpq_macros.h` (`SOM_READ_ENABLE`, auto-set for MEMORY_RGB/CVG), `include/rsp_rdpq.inc:221`, `include/rdpq_mode.h`, `src/rdpq/rdpq.c` (RDRAM vs XBUS)
- Hacker News item 39829383 (anecdotal; pointer only)
- F3DEX3 docs, Counters (GCLK sampling as memory-stall proxy): https://hackern64.github.io/F3DEX3/counters.html

Source code:

- angrylion-rdp-plus `9c8b9ed`: `src/core/n64video/rdp/{fbuffer.c,zbuffer.c,rasterizer.c,blender.c,rdram.c}`
- MiSTer N64_MiSTer `5725381`: `rtl/RDP.vhd`, `rtl/RDP_raster.vhd`, `rtl/RDP_pipeline.vhd`, `rtl/DDR3Mux.vhd`
- MM decomp: `include/PR/gbi.h:592-815`, `src/overlays/gamestates/ovl_file_choose/z_file_choose_NES.c:20-28`, `src/code/z_parameter.c:152-160`
