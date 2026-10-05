# G_PM_1PRIMITIVE (atomic_prim) cost per primitive

Ticket: wScottSh/ares#19 (map: #1). Research date: 2026-10-04.
Target: NTSC retail NUS-001 with Expansion Pak.

Builds on (not repeated here): `research/rdp-command-timing` (§3.4 primitive overlap / pipeline depth), `research/rdp-memory-traffic` (rule 8 span prefetch/write-back, rule 11, open question 4), `research/rdp-pixel-timing-coupling`.

Source snapshots read for this ticket:

- Nintendo SDK online manuals (ultra64.ca): pro-man 12.2.3 "Span Buffer Coherency", pro-man 24.4 "Raster Tuning", n64man `gDPPipelineMode` (revision 02/01/99)
- SGI "Nintendo Ultra64 RDP Command Summary", last modified 4/11/96 (hcs64.com/files/RDP_COMMANDS.pdf), Table 20
- US 6,166,748 (Van Hook et al.), description "Memory Interface 512 and Z Buffering" and claims 1/9/19/27/28/36/37 field (k)
- n64brew wiki, Reality Display Processor/Commands (rev 5941, Tharo, 2026-10-02) and /Pipeline, fetched 2026-10-04
- MiSTer N64_MiSTer `5725381` (2026-09-28); libdragon `e356bf3`; cen64 jgemu fork `2f8d7bc`; cen64 mainline `e0641c8`; angrylion-rdp-plus `9c8b9ed`; paraLLEl-RDP as vendored in ares; F3DEX3 `91a8528`
- MM decomp mm-decomp-60fps @ `56fa21dd0` (committed HEAD; the working-tree edits in that repo touch `z_play.c`, `graph.c`, `game.c`; those three were read from HEAD), and the US decompressed baserom

## TL;DR

- **What the bit does.** Set Other Modes bit 55 (`G_PM_1PRIMITIVE` = othermode-H bit 23) serializes primitives at the memory interface. With it set, the RDP finishes a primitive, including writing its span buffers back to RDRAM, before it reads (prefetches) the spans of the next primitive. Without it, the next primitive's span prefetch can overtake the previous primitive's write-back, so a read-modify-write of the same pixels can read stale data. All vendor sources and n64brew agree on this.
- **Cost.** Best available number: **30–40 RDP clocks of dead time after the last span of every primitive drawn while the bit is set** (SDK pro-man 12.2.3). The SDK also states the effect at system level: "no greater than 1.5M pixels per second" of lost fill rate (man page) or "about 1-1.5Mpixels/sec" worst case (pro-man 24.4).
- **The patent conflict.** The patent's "adding no cycles after the last span" contradicts the SDK. **Judgement: SDK wins.** Three separate Nintendo documents agree on a nonzero delay. The patent clause is self-contradictory ("by adding no cycles" is offered as the *means* of avoiding the hazard). Its own claims and the 1996 SGI table describe a forced write-before-read, which cannot be free when the pipeline normally overlaps primitives. [inference: the patent text most likely dropped a number]
- **Mechanism of the 30–40.** [inference] The figure matches one pipeline drain: the pipeline is about 25–30 clocks deep (n64brew unsynced-attribute table: 0–29; cen64 hardware fit: 25), plus the last span's write-back. Under contention the wall time can be longer, because RDRAM stalls gate the RDP clock.
- **No hardware timing measurement of this bit is public.** The only hardware-adjudicated evidence is *functional*: the cen64 jgemu fork matches captured checksums for stacked image-read rectangles, where non-atomic stacks lose blends and atomic stacks do not (see Behavior).
- **MM.** Six display lists set the bit. On the file-select screen (ares #2320) exactly **one** primitive per frame is atomic: the full-screen 320×240 1-cycle `G_RM_CLD_SURF` fill at the end of `FileSelect_Main`. Its atomic cost is at most ~40 clk ≈ 0.64 µs per frame, which is noise. **G_PM_1PRIMITIVE does not explain the #2320 slowdown.** The full-screen read-modify-write primitive itself does matter: ≈ 80,300 clk ≈ 1.28 ms of pipeline time before memory stalls, by the cen64 law, every frame and even at alpha 0.
- Elsewhere in MM, at most 80 primitives per frame are atomic (VisMono desaturation in cutscenes). That is 2,400–3,200 clk ≈ 38–51 µs per frame. The tile transition (140 triangles) is unreachable in MM.

## Behavior

| Rule | References | How verified on hardware |
|---|---|---|
| **Bit location.** Set Other Modes (0x2F) word bit 55 = othermode-H bit 23 = `G_MDSFT_PIPELINE`. `G_PM_1PRIMITIVE` = 1, `G_PM_NPRIMITIVE` = 0. | SGI RDP Command Summary Table 20 ("k: atomic_prim 0 55"); n64brew Commands; libultra/MM `gbi.h:519-523`; libdragon `SOM_ATOMIC_PRIM` (`rdpq_macros.h:520`); MiSTer `RDP_command.vhd:303`; ares `render.cpp:363` | Encoding is undisputed across all sources. No test needed. |
| **Function.** It forces a primitive's pixels to be written to the frame buffer before the following primitive's spans are read. This gives span-buffer coherency for overlapping read-modify-write primitives (image-read/blend or Z). | SGI Table 20: "Force primitive to be written to frame buffer before read of following primitive." Patent claims field (k): "force writing a primitive to a frame buffer before reading a following primitive". Patent "Memory Interface 512": "forces memory interface 512 to write one primitive to frame buffer 118a before starting the next primitive". n64brew: "forces active span segments to be written to the frame buffer before reading new span segments". SDK man: "the second span process waits for the result of the RMW … of the first span". libdragon: "serialize command execution". | **Functional, hardware-adjudicated (indirect):** cen64 jgemu `rdp_core.c:4584-4601`. Four identical back-to-back 1-row rects with `image_read_en`, both 1- and 2-cycle. Without atomic, "repeated blends of one pixel advance only every other primitive". With atomic, or with wide spans (D ≤ L), all four blends land. Adjudicated against "PRDP 12:15 and 12:16 48-bit checksums". The cen64 author names these as reference captures elsewhere in the file. The capture set itself is not public, and its provenance is not stated in the source. |
| **Hazard window without the bit.** The command processor leads pixel output by D = min(3L−2, 25) clocks (L = clocks per span). The next primitive's span prefetch can therefore precede the predecessor's commit, but only when D > L (narrow spans). | cen64 jgemu hazard model (`rdp_core.c:145-185`, fitted 7332/7332 to snapper64 RDPRectNoSync captures); n64brew Pipeline (next command starts once the last pixel has entered the pipeline); SDK pro-man 12.2.3 (several span buffers, next span prefetched while the pipeline still processes the first) | Functional evidence as above. [inference] For full-width spans (L ≥ 320 clk) D < L. A 320-wide primitive cannot be overtaken, so in MM's full-screen fills the bit buys nothing functionally. |
| **Is it unconditional?** Yes. The delay is paid after every primitive drawn with the bit set, whether or not the next primitive overlaps. | SDK 12.2.3: "cause **all** primitives to add between 30 to 40 null cycles". SDK 24.4: "inserts a delay into the pipeline **between each primitive**". Patent/SGI: "write one primitive … before starting the next" (no overlap test described). | No hardware test found. Probe: atomic-on rects that do not overlap vs. ones that do. Same ΔDPC_CLOCK means unconditional. |
| **Cost: 30–40 dead clocks after the last span of each atomic primitive.** | SDK pro-man 12.2.3 (verbatim: "use gsDPPipelineMode(G_PM_1PRIMITIVE) to cause all primitives to add between 30 to 40 null cycles after the last span of a primitive is rendered. These dead cycles can be expensive in terms of fill rate"). Bound: man page "no greater than 1.5M pixels per second"; pro-man 24.4 "about 1-1.5Mpixels/sec" worst case. | **No public hardware measurement.** No emulator charges time for the bit: cen64 jgemu uses the bit only for the stale-read function, mainline cen64 / Angrylion / paraLLEl do not decode it, ares decodes it and never uses it, and MiSTer decodes it and ignores it. Probe: N small 1-cycle image-read rects, bit on vs off, ΔDPC_CLOCK / N. Repeat with Z on and with heavy CPU/RSP RDRAM traffic to see whether the delay grows with memory latency. |
| **Conflict: patent "adding no cycles".** | US 6,166,748, "Memory Interface 512 and Z Buffering": "…thereby avoiding this potential problem by adding no cycles after the last span of a primitive is rendered." | **Judged wrong/garbled** [inference]. (1) Three Nintendo texts (12.2.3, 24.4, man page rewritten 02/01/99) give a nonzero delay and a fill-rate loss. (2) The patent sentence is near-verbatim the SDK 12.2.3 sentence with "between 30 to 40 null" replaced by "no". (3) Writing a primitive out before the next one's reads necessarily removes the normal overlap (D ≤ 25 clocks of lead plus write-back time), so zero cost is physically implausible. |
| **What the 30–40 is made of.** A pipeline drain (≈ 25–30 clk) plus the final span-buffer write-back, during which nothing new enters the pipeline. | Pipeline depth: n64brew "Effect of unsynced attribute changes" (0–29 clk offsets); cen64 latency constant 25 ("SAME constant in both cycle modes"). Write-back: patent/SDK span buffer. GCLK stops during RDRAM stalls: n64brew RDP/Interface `DPC_STATUS`. | [inference] This decomposition is not stated by any source. It predicts that the cost (a) is roughly the same in 1- and 2-cycle modes and (b) stretches under RDRAM contention in wall time, not in GCLK counts. Probe: compare `DPC_CLOCK` (wall) with the `DPC_BUFBUSY`/`PIPEBUSY` deltas. |
| **Consistency check of the SDK's two numbers.** | — | [inference, arithmetic] 1.5 Mpx/s at 1 px/clk is 1.5 M clk/s. At 35 clk per primitive that is ≈ 43 k primitives/s (≈ 1,430 per 30-fps frame), a plausible "worst case" scene rate for 1999. The two SDK statements are therefore mutually consistent. |
| **Fill / copy mode.** Not documented. | n64brew Pipeline: fill-mode writes are "committed straight to RDRAM without passing through the span buffers". | [inference] The bit is likely irrelevant in fill mode (no span buffer, no reads). Copy mode is unknown. All MM uses are 1-/2-cycle, so this does not affect MM. |
| **Persistence.** The bit is RDP state. It applies to every 1-/2-cycle primitive until the next full othermode write. | F3DEX2 `G_SETOTHERMODE_H` (partial: `gDPSetCycleType`, `gDPSetTextureFilter`…) merges into the cached othermode and re-emits the full word, so partial writes preserve bit 23. F3DEX2 boot value of othermode-H is `0x080CFF` (`mw_f3dex2/f3dex2.s:157`, bit 23 clear). | Source fact (ucode). F3DEX2 `f3dex2.s` `G_SETOTHERMODE_H_handler` (mask-merge into `otherMode0`, then re-send full `0xEF`) confirms it. In MM every other full `gDPSetOtherMode`/`gsDPSetOtherMode` write in `src/` either names `G_PM_NPRIMITIVE` (≈100 sites, incl. all `z_rcp.c` presets) or omits the bit (= 0). Every MM draw list also starts with `setupBuffers` → `sFillSetupDL` (`z_rcp.c:840-850`, `G_PM_NPRIMITIVE`), so the bit never leaks into the next list. |

### How it is used / not used elsewhere

- libdragon defines `SOM_ATOMIC_PRIM` but rdpq never sets it. The only references are the define and the debugger's flag print (`rdpq_debug.c:437,600`).
- F3DEX3 `gbi.h:596-600`: under `KAZE_GBI_HACKS`, `G_PM_1PRIMITIVE` is redefined to `G_PM_NPRIMITIVE`, i.e. a hack that strips the bit from vanilla display lists. This is practitioner evidence that the bit is treated as a pure performance cost. It is not a measurement.
- MiSTer: it decodes `atomicPrim` and never reads it, but *every* primitive waits in `WAITPIXELWRITE` (`RDP_command.vhd:667-675`) until all pixel/Z write FIFOs are empty (`RDP.vhd:1605-1607`). MiSTer therefore behaves as if the bit were always set, which is functionally coherent but too slow for non-atomic primitives.

## Timing-model rule (for the ares fork)

For each 1-/2-cycle primitive with `atomic_prim = 1`:

1. Do not let the next primitive's command execution or span prefetch overlap this one. Treat the end of the primitive as a barrier.
2. After the last span, add **35 clk (range 30–40)** of pipeline dead time, then the RDRAM write of the final span through the memory model (GCLK-gated). Calibrate once on hardware with the probe above.
3. For `atomic_prim = 0`, keep the overlap model from `rdp-command-timing` (lead D = min(3L−2, 25)).

## MM usage

All sites that set the bit, found by grep of `src/` and `extracted/n64-us/assets` for `G_PM_1PRIMITIVE`/`G_MDSFT_PIPELINE`/`gDPPipelineMode`. A binary scan of the US decompressed ROM for 8-byte-aligned `0xEF` words with bit 23 set, framed by valid GBI opcodes, found exactly the 6 data-resident DLs below (code+0x119ED8, code+0x12B1E0, code+0x12B200, ovl_file_choose+0x10510, ovl_fbdemo_triforce+0x5E0, ovl_fbdemo_wipe1+0xE18). Its other hits were vertex data in scene files. VisMono builds its DL at runtime, so it is found by source only. No `0xE3` (`G_SETOTHERMODE_H`) command setting bit 23 exists.

Primitive counts are RDP primitives per frame while the effect is active. Triangles are counted as submitted to the RSP; clipping/culling can change the RDP count. "Cost" uses 30–40 clk per primitive at 62.5 MHz.

| file:line | What's drawn | When | Atomic primitives / frame | Atomic cost / frame |
|---|---|---|---|---|
| `src/overlays/gamestates/ovl_file_choose/z_file_choose_NES.c:21-29` (DL), used at `:2402-2405` | Full-screen black fill: `fillRect` = `gDPFillRectangle(0,0,gCfbWidth,gCfbHeight)` (`z_rcp.c:1520-1524`), 1-cycle, `G_RM_CLD_SURF` (image read + blend), prim color alpha = `screenFillAlpha` | **Every file-select frame**, unconditionally (also at alpha 0) | **1** (320×240, 240 spans) | 30–40 clk ≈ 0.5–0.64 µs. Primitive itself by the cen64 law: 14 + 76,800 + 600 + 12×240 ≈ 80,294 clk ≈ 1.28 ms, plus RDRAM RMW stalls |
| `src/code/z_parameter.c:152-160` (DL), used at `:6748-6753` | Same full-screen fill in OVERLAY | Gameplay, only while `interfaceCtx->screenFillAlpha != 0` (game over etc.) | 1 | 30–40 clk |
| `src/code/z_fbdemo_fade.c:21-29` (DL), used at `:116-125` | Full-screen `fillRect`, 1-cycle `G_RM_CLD_SURF` | While a fade transition is active with alpha ≠ 0 (`TransitionFade` as `transitionCtx` fade types, plus `play->unk_18E48`, `z_play.c:1233, 2284-2287` (HEAD)) | 1 per active fade instance (≤ 2) | 30–80 clk |
| `src/code/z_vismono.c:79-84`, loop `:90-…` | Desaturation: 80 texture rects of 320×3 (`VISMONO_CFBFRAG_HEIGHT` = 2048/640 = 3), 2-cycle, `G_RM_CLD_SURF2` | Cutscenes while `gPlayVisMonoColor.a != 0` (set by `z_demo.c:232,239`) | **80** | 2,400–3,200 clk ≈ 38–51 µs |
| `src/code/z_fbdemo.c:20-28`, `TransitionTile_Draw` `:190-203` | 10×7 grid of textured quads = 140 tris, 1-cycle `G_RM_AA_OPA_SURF` | Only when `gTransitionTileState == TRANS_TILE_READY`. **Unreachable in MM:** no code sets `TRANS_TILE_SETUP` (grep of `src/`, `include/`), and `PROCESS` is only set from the `SETUP` branch (`z_play.c:1384-1401`) | 0 in practice (140 if reached) | 0 (4,200–5,600 clk if reached) |
| `extracted/n64-us/assets/overlays/ovl_fbdemo_triforce/ovl_fbdemo_triforce.c:14-16`, used by `z_fbdemo_triforce.c:104-140` | Triforce wipe, 1-cycle `G_RM_AA_OPA_SURF` | `TRANS_TYPE_TRIFORCE` transitions | 3 (fill-out) / 8 (fill-in) / 2 (fill-in done) | ≤ 320 clk |
| `extracted/n64-us/assets/overlays/ovl_fbdemo_wipe1/ovl_fbdemo_wipe1.c:21-23`, used by `z_fbdemo_wipe1.c:89-100` | Wipe, 12 tris, 2-cycle `G_RM_AA_ZB_TEX_EDGE2` | `TRANS_TYPE_WIPE` / `WIPE_FAST` transitions | 12 | 360–480 clk |

**Leakage check.** The bit persists until the next full othermode write.

- File select: the atomic fill is the last primitive in POLY_OPA (`z_file_choose_NES.c:2405`). The file-select overlay draws nothing into POLY_XLU/OVERLAY (grep count 0). Every list starts with `setupBuffers` → `sFillSetupDL` (`G_PM_NPRIMITIVE`, `z_rcp.c:1540-1543`). So exactly one atomic primitive per frame. The RDP state does carry into the next frame, but the next frame's first list also starts with `setupBuffers`.
- Transitions and VisMono run in an OVERLAY sub-list (`z_play.c:1214-1242`, HEAD). [inference, not traced per call site] They are followed by Interface draws that begin with `Gfx_SetupDL*` presets, all of which carry `G_PM_NPRIMITIVE`.

**Bottom line for ares #2320.** File select pays ≤ 40 clk per frame for the bit. That is ~0.002 % of a 33 ms frame and ~0.05 % of the fill primitive it is attached to. The unconditional full-screen 1-cycle read-modify-write fill under it is the real hardware-only cost: ≈ 1.28 ms of pipeline time plus 320×240×(2 B read + 2 B write) ≈ 300 KiB of span traffic per frame (`rdp-memory-traffic`, open question 4). That cost should be modeled. The atomic bit can be modeled for completeness, but it cannot account for a ~2× frame-rate gap.

## Open questions

1. **Hardware value of the dead time** and whether it depends on cycle mode, span width, Z, or RDRAM contention. Probe: `DPC_CLOCK` delta per primitive, bit on vs off, many small 1-cycle image-read rects. Repeat in 2-cycle, with Z, and with a concurrent RSP DMA load.
2. **Is the barrier unconditional or overlap-triggered?** Probe: atomic rects that never overlap vs. ones that do.
3. **Does cen64's measured 14 clk/primitive overhead already include an atomic drain?** The `dpc_probe` source and its othermode are not public. If the probe ran with the bit set, the non-atomic per-primitive overhead is smaller than 14.
4. **Provenance of the "PRDP" capture set** cited by cen64 jgemu for the atomic stale-read behavior.

## Sources

- N64 Programming Manual 12.2.3 "Span Buffer Coherency": https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro12/12-02.htm (also /man/pro-man/pro12/12-02.html)
- N64 Programming Manual 24.4 "Raster Tuning (Fillrate)", "Disable Atomic Primitives": https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro24/24-04.html
- n64man `gDPPipelineMode` (rev. 02/01/99): https://ultra64.ca/files/documentation/online-manuals/man-v5-1/n64man/gdp/gDPPipelineMode.htm
- SGI, "Nintendo Ultra64 RDP Command Summary", 4/11/96, Table 20 (p. 27): https://hcs64.com/files/RDP_COMMANDS.pdf
- US 6,166,748 (description "Memory Interface 512 and Z Buffering"; claims field (k)): https://patents.google.com/patent/US6166748A/en
- n64brew, Reality Display Processor/Commands (Set Other Modes bit 55), rev 5941: https://n64brew.dev/wiki/Reality_Display_Processor/Commands
- n64brew, Reality Display Processor/Pipeline (fill bypasses span buffers; unsynced-attribute table): https://n64brew.dev/wiki/Reality_Display_Processor/Pipeline
- n64brew, Reality Display Processor/Interface (GCLK gating): https://n64brew.dev/wiki/Reality_Display_Processor/Interface
- cen64 jgemu fork `2f8d7bc`, `src/rdp/rdp_core.c:145-185` (hazard model), `:4584-4680` (atomic stale-read), `:5346-5362` (measured span law), `:4015` (decode): https://gitlab.com/jgemu/cen64
- MiSTer N64 `5725381`, `rtl/RDP_command.vhd:303,667-675`, `rtl/RDP.vhd:1605-1607`, `rtl/RDP_package.vhd:144`: https://github.com/MiSTer-devel/N64_MiSTer
- libdragon `e356bf3`, `include/rdpq_macros.h:520`, `src/rdpq/rdpq_debug.c:437,600`: https://github.com/DragonMinded/libdragon
- angrylion-rdp-plus `9c8b9ed`, `src/core/n64video/rdp.c:623-` (bit 55 not decoded): https://github.com/ata4/angrylion-rdp-plus
- cen64 mainline `e0641c8`, `rdp/n64video.c` (bit 55 not decoded): https://github.com/n64dev/cen64
- paraLLEl-RDP (ares vendored), `rdp_device.cpp:474-` `op_set_other_modes` (bit 55 not decoded); ares `ares/n64/rdp/render.cpp:363` (decoded, unused)
- F3DEX3 `91a8528`, `gbi.h:591-600` (`KAZE_GBI_HACKS`): https://github.com/HackerN64/F3DEX3
- F3DEX2 disassembly (`f3dex2.s:155-157`, othermode boot value)
- MM decomp @ `56fa21dd0`: files and lines in the MM usage table; `include/PR/gbi.h:519-523`; `src/code/z_rcp.c:840-850,1451-1553`; `src/code/graph.c` (list order work→opa→xlu→overlay→debug); `src/code/z_play.c:1214-1250` (HEAD)
- ares-emulator/ares#2320 (file menu runs faster than hardware): https://github.com/ares-emulator/ares/issues/2320
- Prior tickets: `research/rdp-command-timing`, `research/rdp-memory-traffic`, `research/rdp-pixel-timing-coupling` (wScottSh/ares branches)
