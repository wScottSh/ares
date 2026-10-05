# Span RAM buffering and write-back overlap

Research for wScottSh/ares#20 (map: #1). Research date: 2026-10-04. Target: NTSC retail NUS-001 + Expansion Pak.

Builds on #3 ([rdp-memory-traffic.md](rdp-memory-traffic.md)), which covers which othermode bits cause reads and writes, the GCLK stall, and the 288 B size. This doc does not repeat those points.

Tags:

- **[hw-cap]**: a hardware capture I decoded myself for this doc.
- **[hw-doc]**: a source that documents hardware: Nintendo SDK, SGI/Nintendo patent, or n64brew written from hardware tests.
- **[emu-fit]**: an emulator model fitted to hardware captures. The fit is the emulator author's claim; I checked it against the raw data only where stated.
- **[src]**: code read at the stated commit.
- **[inference]**: my reasoning from the cited sources. No source states it.

## TL;DR

**Physical layout.**

- Span RAM is 32 rows × 72 bits (64 data bits plus 8 hidden 9th bits per row).
- Rows 0–15 (test address 0x00–0x3F) hold color. Rows 16–31 (0x40–0x7F) hold Z and texture-load staging.
- The patent's test-register figure (US 6,166,748 FIG. 21J, "DP MEMSPAN TEST REGISTERS") splits the address into BUFFER ADDRESS, DEVICE SELECT and DATA FIELD SELECT. That points to separate color and Z RAM devices. [hw-doc]

**Partition: neither "one span per 64 B slot" nor "128 B × 1".**

- Hardware captures (snapper64 "RDP Test-Mode - Span Tri", 216 console dumps, 1-cycle, 32 bpp, no `IM_RD`/Z) show the pipeline's output pixels land in a **16-slot window**: rows 0–7, which is 64 B at 32 bpp.
- After any draw, rows 8–31 read back as zero. [hw-cap: I decoded all 216 dumps; 216/216 show this pattern]
- The cen64 (jgemu) model fits all 216 captures exactly. In that model, pixels form **one continuous stream per primitive** (position S), not one buffer per span:
  - Each span starts at its 4-pixel phase (16 B at 32 bpp) and is padded out to the next 4-pixel boundary.
  - slot = S mod 16. The slot is CPU-visible only when ⌊S/16⌋ is even. [emu-fit]
- So the color half behaves as **two 64 B halves that alternate (ping-pong) every 16 stream positions**, packed across span boundaries, with 16 B granularity.
- This matches the `DPS_TEST_MODE` counters: `cspan0`/`cspan1` count 16-byte segments and always have opposite MSBs. [hw-doc + inference]
- A long span does not get its own slot. It streams through the alternating halves (16 px at 32 bpp per half; [inference] 32 px at 16 bpp per half).

**Overlap.**

- **Prefetch of the next span overlaps processing of the current one.** SDK §12.2.3: the RDP "would prefetch the first span into a span buffer while the pipeline starts processing this span. Then it would prefetch the next span into another span buffer." That is exactly why the coherency hazard exists. [hw-doc]
- So span N+1's read is issued **before** span N's write-back. The hardware "does have span buffer coherency, at the cost of some performance". `G_PM_1PRIMITIVE` adds 30–40 null cycles per primitive to serialize primitives.
- Write-back of one half overlapping fill of the other is what a ping-pong structure is for. No source states it directly. [inference]

**Latency.** No source gives a measured span-read latency, so it remains a model parameter. Bounds:

- RDRAM wire time for a 16 B row-hit read: about 4.5 RCP clocks (10 tc request-to-data plus 8 tc data, 4 tc per RCP clock).
- Clean row miss: about 8.5 RCP clocks.
- The CPU's uncached load totals 21.3 RCP clocks (nemu64-test), so the RCP-internal overhead is large. The RDP path's own overhead is unmeasured.
- Upper bound for pipeline plus write-back drain: 30–40 cycles (SDK, 1PRIMITIVE).

**TMEM loads.**

- Load data is staged in the Z half of span RAM, then shuffled into TMEM (n64brew). [hw-doc]
- So loads and Z spans compete for the same rows. [inference] They cannot overlap.

**Emulators.**

- MiSTer prefetches a whole line into one of two line-parity buffers while the previous line draws, and writes each pixel separately. That gives the overlap, but not hardware granularity.
- ares, angrylion and paraLLEl model nothing here.

## Behavior table

| # | Behavior | Rule (best available) | References | How verified on hardware |
| --- | --- | --- | --- | --- |
| 1 | Physical span RAM | 32 rows × 72 bits = 288 B. Test words 4r+0/4r+1 hold 64 data bits, word 4r+2 holds 8 hidden bits, word 4r+3 is always 0. Rows 0–15 are color; rows 16–31 are Z and texture. The 7-bit test address wraps at 128 words. | n64brew RDP/Interface `DPS_BUFTEST_ADDR` (Tharo 2024-10-16); snapper64 "Span R/W" test expectations (`RDPTestModeRW.cpp` `maskValue`: word&3==2 → `&0xFF`, ==3 → 0; code-defined expectation, not a dump); libultra `rcp.h` | CPU write/read through `DPS_BUFTEST_*` with RDP idle (n64brew method; snapper64 R/W group runs the same check on console). |
| 2 | Address fields | The test address is {BUFFER ADDRESS, DEVICE SELECT, DATA FIELD SELECT}. Field widths are not drawn. [inference] DEVICE SELECT = color vs Z RAM (bit 6 per n64brew layout), BUFFER ADDRESS = row in device, DATA FIELD SELECT = word in row (bits 1:0). **Conflict:** the figure lists DEVICE SELECT between the other two fields. If the figure's order is literal, DEVICE SELECT would sit at bit 2, which contradicts n64brew's half split. The figure is schematic; n64brew is empirical. **Judged:** n64brew. | US 6,166,748 FIG. 21J ("DP MEMSPAN TEST REGISTERS"; sheet 32), text ¶ "mem span test registers 549(a), 549(b) and 549(c)" | Write distinct patterns to all 128 words, draw one Z-buffered span, see which rows the Z data lands in. |
| 3 | Color write stream | The 1-cycle pipeline writes each rasterized pixel to stream position S. S starts at 0 at the start of the primitive and runs **continuously across spans**, phase-locked S ≡ x (mod 4). A span with an odd start takes a head slot at x0−1, and the end is padded to phase 3. Skipped positions repeat the last value seen at that phase. Fully scissored spans use no positions. | cen64 jgemu `src/rdp/rdp_core.h` `rdp_dps_model_t` comment and `rdp_core.c:2877-3150` (@`2f8d7bc`), fitted "216/216 reference captures exact" to snapper64 "RDP Test-Mode - Span Tri" | snapper64 dumps from console (`assets/2A1ADF69_*`). I confirmed occupancy (row 4) but did not re-derive the per-slot law. |
| 4 | Visible window and halves | After a draw, color rows 0–7 (16 slots × 4 B = 64 B at 32 bpp) hold the write-stage pixel words `(r<<24)|(g<<16)|(b<<8)|((cvg−1)&7)<<5`. Rows 8–31 read 0 (prefill 0x55555555 is destroyed). Slot = S mod 16, visible when ⌊S/16⌋ is even. → **Two alternating 64 B (32 bpp) halves**, only one of which is test-visible at rows 0–7. Why rows 8–15 read 0 is not explained by any source. | [hw-cap] my decode of all 216 `2A1ADF69_*_02.test` span dumps: 214 show rows 0–7 data and rows 8–31 zero; 2 show prefill surviving in some of rows 2–7 (short streams); none show data in rows 8–31. cen64 `dps_materialize` ("words 32..127 read zero afterwards, as in every hardware capture (mechanism unadjudicated)") | Same captures. Open: repeat at 16 bpp, with `IM_RD`, and with Z on. |
| 5 | Partition answer | **Not "1 span per slot" and not "128 B × 1".** The color half works as 2 × 64 B halves that ping-pong along a per-primitive pixel stream at 16 B (4 px @32 bpp) granularity. Spans are packed back to back. Z (when enabled) has the same counter structure (`zspan0/1`) and [inference] the same scheme in rows 16–31. Supersedes #3's inference that there are "two slots, one span each". | Rows 3–4; n64brew `DPS_TEST_MODE` ("cspan0 … Increments … based on how many 16-byte segments a drawn primitive covers"; "cspan1 … if the other counter has the msbit unset this one has it set") | As row 4. Counter check: read `DPS_TEST_MODE` after spans of 1…20 segments and fit low bits / MSB. |
| 6 | Long spans (> one half) | No per-span split. A span wider than 16 positions (32 bpp; [inference] 32 px @16 bpp, 64 px @8 bpp if a slot is 4 B) flows into the other half and alternates. [inference] RDRAM write-back is issued per 64 B half (8 octbytes) or per 16 B segment. Neither is measured; both are ≤ the 128 B RI burst limit. | Rows 3–4; n64brew RDRAM_Interface (RCP bursts ≤ 16 octbytes) | `DPC_CLOCK` (and GCLK sampling) vs span width with `IM_RD` on: a step every 16 px (32 bpp) / 32 px (16 bpp) means per-half transactions; a step every 4/8 px means per-segment transactions. |
| 7 | Prefetch overlaps processing | For RMW, span N+1's framebuffer prefetch is issued while span N is still in the pipeline, into "another span buffer". So the read of N+1 precedes the write-back of N (that is the coherency hazard). | SDK pro-man §12.2.3 "Span Buffer Coherency" (quoted in TL;DR); patents US 6,331,856 / 6,166,748 ("pre-fetches a row of pixels … as soon as edge walker 504 determines the x, y coordinates of the span"; "enough on-chip RAM to hold several span buffers") | Hardware: two overlapping 1-px-tall spans in consecutive primitives with `IM_RD`/`Z_CMP`, NPRIMITIVE vs 1PRIMITIVE. Stale-read artifacts confirm the ordering (SDK says errors appear). |
| 8 | Write-back overlaps the next half | [inference] With two halves and a continuous stream, half A is written back while the pipeline fills half B. The pipeline stalls (GCLK off) only if B fills before A's write-back (and the next prefetch) finish. The SDK calls 2-cycle mode's two MI accesses per pixel "balanced" and says 1-cycle color+Z "is often stalled at MI". That only works if memory and compute overlap. | SDK pro-man §12.1 (one-/two-cycle notes); n64brew `DPC_STATUS` GCLK | GCLK sampling (F3DEX3 `CFG_PROFILING_C` method) on a wide 2-cycle Z rect: about 0 % stall means full overlap. |
| 9 | Coherency cost | Default (NPRIMITIVE): coherency is kept "at the cost of some performance". 1PRIMITIVE: +30–40 null cycles after each primitive's last span. Patent text says "adding no cycles". **Judged:** SDK (likely "null" mis-rendered; see #3/#19). | SDK §12.2.3; pro-man 24.4.1 (≤1–1.5 Mpixel/s lost); US 6,331,856 | Ticket #19. |
| 10 | Span read latency | **Not measured by any source.** Wire bounds per 16 B: row hit = request 10 tc to data + 8 tc data ≈ 4.5 RCP clk; clean row miss ≈ 32 tc to data ≈ 8 + 2 = 10 RCP clk; dirty miss +2 clk. The CPU uncached-load total is 21.3 RCP clk, about 18 clk above wire time, which shows that RCP-internal overhead dominates. [inference] Drain from last pixel to written-back is ≤ 30–40 clk (1PRIMITIVE null cycles). Model it as a parameter: latency L_rd = wire(hit/miss) + C_mi, with C_mi calibrated (#16). | n64brew RDRAM (`Delay`: ReadDelay 7 tc; RI 4 tc per RCP clk); #4 doc rdram-bus-arbitration.md (tReadHit 10 tc, retry 22/30 tc, uncached 32 pclk); SDK §12.2.3 | Hardware: 1-px-tall `IM_RD` rects, width 1 seg, N spans: `DPC_CLOCK`/N minus the no-`IM_RD` baseline gives exposed latency per span. Repeat with color and Z in the same vs different 1 MB bank. |
| 11 | Per-span overhead (measured) | 1-cycle: 14 + Σ(pixel_cycles × 129/128 + 12) per primitive. The +12/span probably includes span-buffer turnover. [inference] The 1/128 term is a periodic stall of unknown origin (one candidate is a half-switch or write-back bubble). | cen64 jgemu `rdp_core.c:5346-5362` (dpc_probe on console; raw data not public); #2 doc rdp-command-timing.md | Repeat the RECTH/RECTW sweep with `IM_RD`/Z on and off, at 16 and 32 bpp. |
| 12 | TMEM load sharing | Load data passes through span RAM rows 16–31 (the Z half) before the shuffle into TMEM. [inference] A load cannot overlap Z-buffered span traffic. The Z half must be free (written back) before load data enters. Sync Load (fixed 25 GCLK) "guarantees that the loading pipeline will be available". [inference] RDRAM bursts for loads are ≤ 128 B (the RI limit), matching a 128 B half. | n64brew RDP/Interface (`DPS_BUFTEST_ADDR` text); n64brew RDP/Commands (Sync Load); patent "obtains data for its texture memory 502 … using memory interface 512" | `DPS_BUFTEST` readback right after a LoadBlock (RDP idle): which rows hold the last texels shows staging size and position. `TMEM_BUSY` vs `DPC_CLOCK` for loads after a Z draw vs after a non-Z draw. |
| 13 | Fill / copy | Fill bypasses span buffers ("committed straight to RDRAM"). Copy: not stated. | n64brew RDP/Pipeline | DPS readback after a fill rect (expect prefill intact). |
| 14 | Emulator state | **MiSTer** (`5725381`): two whole-line FB buffers selected by y parity (`RDP.vhd:781-784` `RDRAM_fillAddr(9) <= FBoddSaved`; `RDP_FBread.vhd:62` `yOdd & …`). The line N+1 read is requested while line N draws (`RDP_raster.vhd:721-748`, WAITREADRAM → WAITLINE when `startLine`). One DDR3 burst per line; per-pixel masked write FIFO. Prefetch/process overlap is right; granularity and write-back are not hardware-like. **cen64 jgemu:** models DPS test contents and a measured span cost, not memory timing. **ares, angrylion, paraLLEl:** none. | Sources listed | n/a |

## Details

### Physical RAM and test port

- n64brew (Tharo, 2024) says span buffers are 288 bytes and "72 bits are accessed over 4 word addresses".
  - "The first half of the rows up to 0x40 only hold color data while the second half of the rows from 0x40 onwards hold depth and texture data."
  - "Texture data is held in spans as it is loaded from RDRAM before being shuffled into TMEM."
- The layout table shows the third word as `000000XX`. That is 8 hidden bits, so 32 + 32 + 8 = 72 bits per row.
- The patent figure for the same registers (FIG. 21J, sheet 32 of US 6,166,748) has three registers:
  - 549(a): ENABLE.
  - 549(b): BUFFER ADDRESS / DEVICE SELECT / DATA FIELD SELECT.
  - 549(c): BUFFER DATA.
  - "Device select" is the first primary-source hint that span RAM is more than one physical array.

### What the hardware captures show

snapper64 (Max Bebök, MIT, `e1cd8a6`) has a group "RDP Test-Mode - Span Tri" with 4 × 54 tests. Its references are dumped from a real console (README "Dumping References … requires … an actual N64 console").

Each test does the following:

1. Fills all 128 span words with 0x55555555.
2. Draws one shaded triangle in 1-cycle mode, 32 bpp, with `IM_RD`, Z and AA off.
3. Reads all 128 words back.

I downloaded the 432 LFS objects for that group (group hash `2A1ADF69`) and decoded the 216 span dumps (`*_02.test`, 4×32 RGBA32 = 128 words):

| Row pattern (D = drawn data, 5 = prefill, 0 = zero; rows 0..31) | Count |
| --- | --- |
| `DDDDDDDD000000000000000000000000` | 214 |
| `DD555555000000000000000000000000` | 1 |
| `DDDDDD55000000000000000000000000` | 1 |

Example: rows 0–1 of test `00E48291` are `0331ca80 0d00f040 c0c0c0c0 00000000` and `0e01eee0 0d06ebe0 c0c0c0c0 00000000`. These are pixel words with coverage in bits 7:5, and the hidden byte in word 2.

The conclusions:

- Rows 8–15 are part of the color half, yet they never hold drawn data and are cleared by a draw.
- Rows 0–7 hold the last pixels of the stream, placed by S mod 16.

cen64 (jgemu `2f8d7bc`) states the full placement law. It claims 216/216 exact; I checked occupancy only.

The law lists these as still provisional:

- non-1-cycle modes and non-32 bpp
- rectangles
- carryover from one primitive to the next
- fractional edge drop rules

### Why this answers "64 B × 2 vs 128 B × 1"

The prior inference in #3 was two color slots of 64 B, one per span. The captures refine it.

- **Slots alternate per 16 stream positions, not per span.** A span of 3 pixels and a span of 40 pixels both just advance S.
- **Granularity is a 4-pixel phase group: 16 B at 32 bpp.** This is the same "16-byte segment" unit that `cspan` counts.
- **Two counters with opposite MSBs** fit two halves: each counter tracks its own half, and the MSB marks which one is current. [inference]
- **Only one 64 B half is visible to the test port after a draw.** The other half's rows read 0. [inference] This is consistent with the second half being a separate array or bank behind DEVICE SELECT, or with it being cleared on hand-off. No source decides this.

At 16 bpp, "16 positions" could be 16 pixels (32 B) or 16 words (32 px, 64 B). If the RAM is filled in 64-bit rows, the half is 64 B = 32 px. [inference; needs a 16 bpp capture]

### Overlap: what is stated and what is inferred

Stated (SDK §12.2.3):

> "For RMW cycles, the RDP is smart enough to prefetch a row of pixels as soon as the X, Y coordinates of the span are determined … The RDP has enough onchip RAM to hold several span buffers. Therefore, if two spans in sequence happened to overlap the same screen area, the RDP would prefetch the first span into a span buffer while the pipeline starts processing this span. Then it would prefetch the next span into another span buffer. This is where the problems occur: the pixel data for the next span is not yet computed."

So: prefetch(N+1) overlaps processing(N) and precedes write-back(N).

Inferred:

- Write-back(N) overlaps processing(N+1) through the alternate half.
- The pipeline stalls (GCLK low) only when it needs a half that is still waiting for prefetch data or write-back.

Indirect support: SDK §12.1 calls 2-cycle "balanced" and 1-cycle color+Z "often stalled at MI". In 1-cycle mode, 16 bpp color+Z RMW needs 8 B per clock, which is about the whole RDRAM peak (500 MB/s ÷ 62.5 MHz = 8 B per clock). In 2-cycle mode it needs 4 B per clock. If memory and compute were serialized, both modes would stall heavily.

### Latency

No public source gives the request-to-data latency for span reads.

| Component | Value | Source |
| --- | --- | --- |
| RDRAM tc per RCP clock | 4 | n64brew RDRAM ("TCycle 4, RCP Cycle 1") |
| Row-hit read, request start → data | 10 tc (2.5 clk) | #4 doc (NEC tReadHit); ReadDelay 7 tc after a 3-tc request (n64brew RDRAM `Delay`) |
| 16 B data | 8 tc (2 clk) | 64 bits per 4 tc |
| Clean / dirty row miss → data | 32 / 40 tc (8 / 10 clk) | #4 doc (retry 22 / 30 tc) |
| CPU uncached LW total | 21.3 RCP clk | #4 doc (nemu64-test 32 pclk) |
| 1PRIMITIVE drain | 30–40 clk | SDK §12.2.3 |

Best model [inference]: L_rd = wire (4.5 clk on a hit, 10 on a clean miss, 12 on a dirty miss, for 16 B; +2 clk per extra 16 B) + C_mi. C_mi is the fixed RI/MI pipeline overhead for RDP requests; it is unmeasured and should be calibrated in #16. Exposed latency is zero whenever the prefetch was issued at least L_rd before the pipeline needs the span (row 8).

## Open questions (new, sharp)

1. Is the 64 B half a fixed byte size (32 px at 16 bpp) or a fixed 16 positions (16 px at 16 bpp)? Needs the snapper64 Span Tri test at 16 bpp.
2. Where do the odd-half pixels physically go, and why do rows 8–31 read 0 after a draw? Is it a DEVICE SELECT bank or a clear-on-hand-off?
3. With `IM_RD`/`Z_CMP` on, do prefetched RDRAM words appear in rows 0–7 / 16–23 at the S positions? That would show whether read and write share one stream.
4. RDRAM transaction unit for span read and write: per 16 B segment or per 64 B half? (`DPC_CLOCK` step pattern vs width.)
5. What is the 1-per-128 pixel-cycle stall in cen64's measured law, and does it scale with bpp (i.e. is it per N halves)?

## Sources

- n64brew, Reality Display Processor/Interface (`DPS_TEST_MODE`, `DPS_BUFTEST_ADDR`, `DPS_BUFTEST_DATA`, `DPC_STATUS`), rev. 2026-01-08 (span text by Tharo, 2024-03-21 and 2024-10-16). https://n64brew.dev/wiki/Reality_Display_Processor/Interface
- n64brew, Reality Display Processor/Commands (Sync Load/Pipe/Tile/Full, Set Color Image); /Pipeline (Color Image Write, Fill). https://n64brew.dev/wiki/Reality_Display_Processor/Commands
- n64brew, RDRAM (`Delay`, TCycle ↔ RCP cycle); RDRAM_Interface (16-octbyte bursts). https://n64brew.dev/wiki/RDRAM
- N64 Programming Manual §12.1 (cycle types, MI notes) and §12.2.3 "Span Buffer Coherency"; §24.4.1. ultra64.ca man-v5-1 pro-man/pro12/12-01.htm, 12-02.htm.
- US 6,166,748 (FIG. 21J "DP MEMSPAN TEST REGISTERS", sheet 32; "Memory Interface 512 and Z Buffering"); US 6,331,856 B1 and US 6,239,810 B1 (same description). https://patents.google.com/patent/US6166748A
- snapper64, HailToDodongo/snapper64 `e1cd8a6`: `src/tests/RDPTestModeSpan.cpp`, `RDPTestModeRW.cpp`, console-dumped references `assets/2A1ADF69_*` (Git LFS). https://github.com/HailToDodongo/snapper64
- cen64 jgemu fork `2f8d7bc`: `src/rdp/rdp_core.h` (`rdp_dps_model_t`), `src/rdp/rdp_core.c:144-170` (hazard), `2877-3150` (DPS stream), `5346-5362` (span law), `src/rdp/interface.c:359-410`. https://gitlab.com/jgemu/cen64
- N64_MiSTer `5725381`: `rtl/RDP.vhd:620-790, 1114-1205`; `rtl/RDP_raster.vhd:700-760`; `rtl/RDP_FBread.vhd:62`. https://github.com/MiSTer-devel/N64_MiSTer
- libultra `rcp.h` (DPS register comments), via HackerSM64 `include/n64/PR/rcp.h:363-377`.
- Map siblings: #3 [rdp-memory-traffic.md](rdp-memory-traffic.md); #4 [rdram-bus-arbitration.md](rdram-bus-arbitration.md); #2 [rdp-command-timing.md](rdp-command-timing.md); #17 (write granularity), #19 (1-primitive cost).
