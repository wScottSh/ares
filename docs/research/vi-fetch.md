# VI scanout fetch pattern — ticket #22

Target: NTSC retail NUS-001 + Expansion Pak, running Majora's Mask (US). Map: #1. Prerequisites: #7 (DMA engine timing, `research/dma-timing:docs/research/dma-timing.md`) and #4 (RDRAM arbitration, `research/rdram-bus-arbitration:docs/research/rdram-bus-arbitration.md`).

Units: 1 rclk = 1 RCP cycle = 16 ns (62.5 MHz). 1 tc = ¼ rclk (RDRAM channel cycle). NTSC line (H_TOTAL 3093) = 63.556 µs = 3 972 rclk.

## TL;DR

- **MM does not run its VI in AA_NEEDED ("fetch extra lines as needed").** `osViModeNtscLan1` sets AA_MODE = 1, but MM always follows `osViSetMode` with `osViSetSpecialFeatures(OS_VI_DITHER_FILTER_ON | OS_VI_GAMMA_OFF)`. libultra's `OS_VI_DITHER_FILTER_ON` sets the dedither bit **and clears AA_MODE to 0 = AA_ALWAYS ("always fetch extra lines")**.
  - Effective VI_CTRL = **0x00013016**: TYPE 16-bit, gamma-dither on, gamma off, divot on, AA_MODE 0, PIXEL_ADVANCE 3, dedither on.
  - Live check in ares (MM US, gdb read of 0xA4400000): VI_CTRL reads 0x3016. ares does not return bit 16, so the dedither bit is confirmed from code only.
  - n64brew independently says dedither only works with AA_ALWAYS or REPLICATE. That is why libultra forces AA_MODE 0.
- **Lines per output line: 3 framebuffer lines (best knowledge).**
  - The SDK says: *"Both antialiasing and dither filter video hardware require fetching 3 scan lines and filter down to produce a single scan line of video."*
  - The RCP patent says the VI reads a segment of line n, plus the same segment of lines n+1 and n+2, into a small double buffer. The buffer **does not hold a whole line**, so lines cannot be reused from one output line to the next.
  - Conflict: the hardware-matched software VIs (Angrylion, paraLLEl-RDP) read **4** framebuffer rows per output line (n−1…n+2). That is an upper bound.
- **Volume for MM: 3 × 640 B = 1 920 B per output line × 237 lines × 59.83 Hz ≈ 27.2 MB/s (5.4 % of 500 MB/s peak).** The upper bound with 4 rows is 36.3 MB/s (7.3 %).
  - This replaces #7's "9–18 MB/s" range, which assumed AA_NEEDED with 1 to 2 lines.
  - The 9th (coverage) bit rides on the same 9-bit channel transfer and costs no extra channel time.
- **Burst size: 128 B (64 px at 16 bpp) per segment (inference).**
  - Evidence: the n64brew REPLICATE erratum shows 64-pixel granularity ("first 64 pixels … then 64 pixels of garbage"), and 128 B is the RI's maximum burst.
  - That gives **15 bursts per output line** (5 segments × 3 lines).
- **When: during the active line, starting at H_START. There is no HBLANK prefetch.**
  - n64brew: after H_START *"the screen remains blanked for several pixels afterwards, while the VI loads values from RAM for filtering."*
  - Patent: reads happen *"in synchronism with the line scanning"* into a block double buffer.
- **Refresh uses the HBLANK slot.** RI issues one broadcast refresh per VI HSYNC, then holds the channel for 52 rclk (clean) or 54 rclk (dirty). That is 1.31–1.36 % of every line, on all 263 lines, and it sits outside the VI's active-line fetch window (n64brew RI_REFRESH: *"so it can't block VI scanout"*).
- **Channel occupancy for MM:**
  - Per output line, 15 × 128-B reads cost **285 rclk (all row hits) to 398 rclk (all dirty misses)**. That is 7.2–10.0 % of a line, or 8.7–12.1 % of the 3 287-rclk active window.
  - Averaged over the frame (237 of 263 lines active): **6.5–9.0 % VI, plus 1.3–1.4 % refresh ≈ 7.8–10.4 % of RDRAM channel time.**
  - With the 4-row upper bound: 8.6–12.0 % VI.
  - The SDK puts the cost of AA/dither-filter video bandwidth at *"a 5% to 10% fixed overhead"* on small polygons, which is consistent.

## Behavior table

| Behavior | Rule (best available knowledge) | References | How verified on hardware |
|---|---|---|---|
| MM's effective AA mode | AA_MODE 0 (AA_ALWAYS) with dedither on. `OS_VI_DITHER_FILTER_ON` clears `VI_CTRL_ANTIALIAS_MASK`. MM applies it at boot, at every game-state init and on every `osViSetMode` through the scheduler. VI_CTRL = 0x13016. | decomp `src/libultra/io/visetspecial.c` (`features &= ~VI_CTRL_ANTIALIAS_MASK`), `src/boot/idle.c:33,105`, `src/boot/viconfig.c:23-24`, `src/code/game.c:229-230`, `src/code/graph.c:232-233`, `src/code/sched.c:52-53`; SDK `osViSetSpecialFeatures` ("osViSetMode returns … to their default values", dither filter default ON for 16 bit); n64brew VI_CTRL DEDITHER_ENABLE (needs AA_ALWAYS or REPLICATE) | Not measured on hardware. ares runtime read of VI_CTRL from MM = 0x3016 (AA bits 0). ares drops bit 16 on readback (`ares/n64/vi/io.cpp:5-16`). |
| AA mode semantics | 0 = AA + resample, always fetch extra lines. 1 = AA + resample, fetch extra lines only if needed. 2 = resample only (all pixels treated as fully covered). 3 = replicate. | SDK `rcp.h` header comment; n64brew VI_CTRL; Angrylion `vi.c:29-32`; MiSTer `VI.vhd:107` | Text only. Inference: in mode 1 the VI skips the extra lines when a segment is fully covered. n64brew reports that dedither in mode 1 produces "vertical streaks", which fits the dedither filter finding the neighbor lines missing. |
| Lines fetched per output line | 3 framebuffer lines (segment of n, n+1, n+2). Two AA filters (lines n and n+1) feed a vertical lerp. | SDK pro-man §24.4 Raster Tuning; US 6,166,748 (FIG. 34/34A text: "reads out a block … of the current line n … next video line n+1 … also reads a further block … line n+2"); US 5,742,277 (AA neighborhood: the rows above and below the center pixel, 6 neighbors) | No published bus measurement. **Conflict:** Angrylion `vi.c:151-231` and paraLLEl-RDP `vi_fetch.frag` use rows y−1…y+2 (4 rows) for the two filters. Judged: SDK and patent are the vendor statements, so 3 is the best value and 4 is the upper bound. Inference: the hardware may hold the n−1 neighbors from an earlier segment pass, or the patent's "n" is the up-neighbor row. |
| Line reuse across output lines | None. The VI buffer holds blocks of line segments, not whole lines, so every output line refetches all of its lines. | US 6,166,748: "buffer 902 does not store the pixel color values corresponding to an entire line … stores a plurality of blocks … each block corresponding to a portion of a line"; n64brew VI_TEST_ADDR (7-bit line-buffer word address, i.e. 128 words) | Structural (patent). MiSTer reuses lines (3-line ring, one new line per output line, `VI_linefetch.vhd:172-186`). That suits its DDR3 back end and is not hardware behavior. |
| Segment / burst size | 128 B = 64 px at 16 bpp (inference). The per-scanline fetch allocation is finite: X_SCALE > 0xE00 (16 bpp) or > 0x800 (32 bpp) breaks output. | n64brew VI_X_SCALE errata (64-px good / 64-px garbage pattern; "exceeding the number of VI fetches allocated per scanline"); n64brew RDRAM_Interface (RCP burst max 16 octbytes); RI_LATENCY note | Erratum observed on hardware (n64brew, libdragon #759). The burst size itself is not measured. |
| Fetch timing in the line | Fetch begins at H_START and runs through the active line in segment order. Output stays blanked for a few pixels after H_START while the first blocks load. No fetch in HBLANK. | n64brew VI_H_VIDEO ("blanked for several pixels afterwards, while the VI loads values from RAM"); US 6,166,748 ("in synchronism with the line scanning", double-buffered blocks) | The blanking after H_START is visible on hardware (n64brew). Fetch cadence is not measured. |
| Horizontal extent | Each line's fetch covers WIDTH × bpp = 640 B, plus a few edge pixels for the AA (±2 px) and divot (±1 more px) neighborhoods. | Angrylion `video.c:63-85` (to_left/to_right ±2); paraLLEl `video_interface.cpp:376` (+2+4, +2 divot) | Functional match only (these renderers are pixel-compared against hardware). |
| 9th (coverage) bit | Carried on the 9-bit channel with the color data. No extra transfers. | n64brew RDRAM; #4 doc B18 | Structural. |
| RDRAM refresh | One broadcast `SetRR` per VI HSYNC, then 52 / 54 rclk holdoff (clean / dirty). This happens in HBLANK, so it does not collide with VI fetches. | n64brew RDRAM_Interface RI_REFRESH; IPL3; #4 doc B11–B13 | Not measured. Refresh period follows H_TOTAL (n64brew: the default H_TOTAL gives a 10.5 ms refresh cycle and "noticeable memory bandwidth reduction"). |
| VI priority vs other clients | Not documented. Inference: highest or near-highest (hard real-time, small double buffer). | n64brew RI_LATENCY (speculation); #4 doc B4 | nemu64-test: uncached CPU load = 36 pclk in the VI front buffer's bank vs 32 elsewhere. That fits VI bursts reopening their row often. |
| Emulator charging | ares, cen64, gopher64, Dillonb, mupen64plus and simple64 charge VI 0 bus time. MiSTer fetches 1 line (0xB0 × 8 B = 1 408 B "hack") per output line. | `ares/n64/vi/vi.cpp:196,214`; #7 doc; MiSTer `VI_linefetch.vhd:123-141` | n/a |

## MM bus-occupancy estimate

Inputs:
- `osViModeNtscLan1`, effective AA_MODE 0.
- WIDTH 320, 16 bpp, so 640 B per line.
- H_START 108–748, which is 640 of 773.5 px.
- V_START 37–511, which gives 237 active lines per field.
- VSYNC 525, so 263 lines and 59.83 Hz.
- Y_SCALE 1.0, so 1 framebuffer line advance per output line. This is set by `gViConfigYScale = 1.0` (`src/boot/idle.c:107`).

Line timing:
- Line = 3 972 rclk.
- Active window ≈ 640/773.5 × 3 972 ≈ 3 287 rclk.
- HBLANK ≈ 686 rclk.

Burst costs come from the #4 doc (NEC µPD488170L arithmetic): a 128-B read costs 74 tc (hit), 96 tc (clean miss) or 104 tc (dirty miss), plus a 2-tc post-read gap.

| Case | B / output line | B / field | MB/s | % of 500 MB/s | rclk / line (hit … dirty miss) | % of line | Frame average (VI only) |
|---|---|---|---|---|---|---|---|
| 1 line (#7 base, MiSTer-like reuse) | 640 | 151 680 | 9.07 | 1.8 % | 95 … 133 | 2.4–3.3 % | 2.2–3.0 % |
| **3 lines (best knowledge: SDK + patent)** | **1 920** | **455 040** | **27.2** | **5.4 %** | **285 … 398** | **7.2–10.0 %** | **6.5–9.0 %** |
| 4 lines (Angrylion/paraLLEl neighborhood) | 2 560 | 606 720 | 36.3 | 7.3 % | 380 … 530 | 9.6–13.3 % | 8.6–12.0 % |

Add refresh: 52–54 rclk on every one of the 263 lines = 1.31–1.36 %.
- Best-knowledge total of fixed display traffic: **≈ 7.8–10.4 % of RDRAM channel time**.
- It comes as 15 bursts of ~19–26 rclk spread across the active part of each line, plus one ~53-rclk refresh holdoff in each HBLANK.
- VBLANK lines (26 of 263) carry only refresh.

Row behavior (inference):
- Lines n, n+1, n+2 span 1 920 contiguous bytes. They sit in one 2 KiB row or straddle two, so VI's own sequence is mostly row hits.
- MM's two 320×240 framebuffers are double-buffered. Whether the RDP's back buffer and Z sit in the same 1 MiB bank as the front buffer decides how often VI bursts miss. The nemu64-test 36-vs-32-pclk result says misses are common in the front buffer's bank.
- Mapping MM's framebuffer and Z-buffer banks is a follow-up for the arbitration model.

Bomber's Notebook (hi-res custom mode, 576×454):
- It goes through the same `viFeatures` path, so AA_MODE is also forced to 0 (inference from code; not traced at runtime).
- Volume scales with WIDTH and the lines per field. It is not quantified here.

Model guidance for the ares fork (inference):
- Charge VI as 15 × 128-B reads per active output line, evenly spaced from H_START to H_END.
- Address them as line segments n…n+2 of the current Y position at ORIGIN + y·WIDTH·2.
- Charge refresh as one 52/54-rclk channel holdoff at each HSYNC.

## Sources

- n64brew, Video Interface (VI_CTRL AA_MODE and DEDITHER_ENABLE, VI_H_VIDEO, VI_X_SCALE errata, VI_TEST_ADDR, H_TOTAL refresh note). https://n64brew.dev/wiki/Video_Interface (snapshot in scratchpad `n64brew/Video_Interface.txt`)
- n64brew, RDRAM Interface (RI_REFRESH, RI_LATENCY, 128-B burst cap). https://n64brew.dev/wiki/RDRAM_Interface
- N64 SDK Programming Manual §24.4 "Raster Tuning" (3 scan lines, 5–10 % overhead). https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro24/24-04.htm
- N64 SDK `osViSetSpecialFeatures` man page; `rcp.h` VI_CTRL comment ("always fetch extra lines" / "fetch extra lines if needed").
- US 6,166,748 (Nintendo/SGI), Video Interface FIG. 34/34A description (DMA controller 900, buffer 902, filters 906a/b, vertical interpolator 910). https://patents.google.com/patent/US6166748A
- US 5,742,277 (SGI), "Antialiasing of silhouette edges" (neighborhood, above/below rows). https://patents.google.com/patent/US5742277A
- mm-decomp: `src/libultra/io/visetspecial.c`, `src/libultra/io/visetmode.c`, `src/libultra/vimodes/vimodentsclan1.c`, `src/boot/idle.c`, `src/boot/viconfig.c`, `src/code/sched.c`, `src/code/graph.c`, `src/code/game.c`, `src/code/sys_cfb.c`, `src/code/z_vimode.c`.
- Angrylion-RDP-Plus `src/core/n64video/vi.c`, `vi/video.c`, `vi/fetch.c`, `vi/restore.c` (commit 9c8b9ed).
- paraLLEl-RDP `parallel-rdp/video_interface.cpp`, `shaders/vi_fetch.frag` (commit 1cecd04).
- MiSTer N64 `rtl/VI_linefetch.vhd`, `rtl/VI_videoout_sync.vhd`, `rtl/VI.vhd` (commit 5725381).
- ares (wScottSh fork, master 59158c2): `ares/n64/vi/io.cpp`, `ares/n64/vi/vi.cpp`. Runtime VI register dump: ares v148 build (`ares-n64:v148` container) + gdb-multiarch, MM US ~45 s after boot.
- #4 RDRAM arbitration doc (burst costs, refresh, nemu64-test bank result); #7 DMA timing doc (prior VI estimate).
