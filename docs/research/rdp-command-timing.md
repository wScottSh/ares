# RDP command and span duration rules

Ticket: wScottSh/ares#2 (map: #1). Research date: 2026-10-04.
Target: NTSC retail NUS-001 with Expansion Pak. RDRAM/memory stalls are out of scope here (separate ticket); every rate below is the RDP's *compute* rate in RCP cycles (GCLK) unless a source says it includes memory.

Builds on `mm-decomp-60fps/docs/research/n64-emulator-timing-model.md` (§2a MiSTer, §2b n64brew, §2d SDK). Not repeated: the gap inventory and the ares architecture.

Source snapshots read for this ticket:

- MiSTer N64_MiSTer `5725381` (2026-09-27): `rtl/RDP*.vhd`
- angrylion-rdp-plus `9c8b9ed` (2024-12-28)
- parallel-rdp-standalone `1cecd04` (2024-11-09)
- cen64 jgemu fork (gitlab.com/jgemu/cen64) `2f8d7bc` (2026-09-26, shallow clone: no history): `src/rdp/rdp_core.c`, `src/rdp/interface.c`
- nemu64-test `9a8b9f7`; libdragon `e356bf3`
- n64brew wiki raw wikitext and page history, fetched 2026-10-04
- Nintendo SDK online manuals man-v5-1 (ultra64.ca); SGI "Nintendo Ultra64 RDP Command Summary" v2.0, 1996-04-11 (hcs64.com/files/RDP_COMMANDS.pdf)
- US patent family US 6,239,810 / US 6,166,748 (identical description text; ¶ numbers below are paragraph positions in the Google Patents description text, not official column:line)

## TL;DR

- **Clock.** One RDP "cycle" = one RCP clock = one `DPC_CLOCK` tick, 62.5 MHz. The SDK `osDpGetCounters` man page says 60.85 MHz; that is the minority figure (see §1).
- **Span rates (vendor-stated, all sources agree):**
  - 1-cycle: 1 px/clk.
  - 2-cycle: 1 px per 2 clk.
  - Fill: 64 bits/clk, i.e. 8 / 4 / 2 px per clk at 8 / 16 / 32 bpp. 4 bpp crashes.
  - Copy: 64 bits/clk, i.e. 4 px/clk at 16 bpp and 8 px/clk at 8 bpp. 32 bpp is unavailable (crash).
  - Pixel size does not change the 1/2-cycle compute rate; it changes only memory traffic.
- **Measured per-primitive and per-span overhead.** The only hardware-measured figure found is in a code comment in the cen64 jgemu fork. It was measured in 1-cycle mode with the VI blanked; the raw data is not public:

  `cycles = 14 per primitive + Σ_spans (pixel_cycles × 129/128 + 12)`

  The `+12 per span` dwarfs the MiSTer RTL's ~2 clk/line and n64brew's "1 dead cycle per line". The measured figure is better grounded, but it most likely includes per-row span-buffer flush memory time.
- **Per-command setup.**
  - Attribute setters and NOPs: 1 cycle each (n64brew).
  - Primitives:
    - The cen64 measurement gives 14 cycles for a rectangle, including its 2-word fetch.
    - No source gives a triangle cost. MiSTer takes 1 clk per 64-bit command word (4–22 words).
    - Lines above the scissor cost 1 cycle each (n64brew).
- **TMEM loads.**
  - LoadBlock and LoadTile write 64 bits/clk into TMEM; this is TMEM_BUSY time.
  - LoadTLUT writes 1 entry/clk.
  - These rates come from MiSTer RTL and the Angrylion loader structure; no vendor figure exists.
  - LoadTile pays an extra per-line cost: one RDRAM request per row ("slower than Load Block").
- **Syncs.**
  - Pipe = 50, Tile = 33, Load = 25 GCLK, fixed and unconditional (n64brew, uncited, author Tharo).
  - The 1996 SGI/patent documents describe them instead as waiting on a condition. No vendor document gives cycle counts.
  - Sync Full = drain of all pipeline and memory work; no fixed number exists. A ~30–40-cycle pipeline drain is inferred from the SDK's G_PM_1PRIMITIVE text.
- **Mode changes.**
  - An attribute write costs 1 cycle and never stalls by itself.
  - Correct software inserts Sync Pipe (50) before it.
  - Unsynced writes land 0–29 cycles into the previous primitive's tail (n64brew corruption table), which also bounds the pipeline depth at about 29–30 cycles.
  - The next command starts as soon as the last pixel of the previous primitive *enters* the pipeline. MiSTer instead drains every primitive, which is not hardware-like.
- **Command FIFO depth: no source states it.** Not in the patents, the SDK, n64brew or any emulator.
  - The MiSTer RTL uses 64×64-bit with refill at ≤32 used, fetched in bursts of ≤22 words.
  - It can be measured on hardware with `DPC_CURRENT` (§3.9).

## Behavior table

Legend for "references": **[HW-meas]** hardware-measured; **[vendor]** Nintendo/SGI doc or patent; **[wiki]** n64brew (method not stated unless noted); **[RTL]** MiSTer VHDL (an FPGA re-implementation, not Nintendo RTL); **[emu]** emulator source; **[inference]** mine, basis given.

| Behavior | Cycles / rule | References | How it can be verified |
|---|---|---|---|
| RCP/RDP clock | 62.5 MHz; 1 `DPC_CLOCK` tick = 1 RCP cycle. Alternative figure: 60.85 MHz (16.43 ns) | 62.5: [vendor] pro-man §3.7; [wiki] RDP/Interface; [RTL] `pll_0002.v`. 60.85: [vendor] `osDpGetCounters` man page. COUNT:DPC_CLOCK = 3:4 ±20/133k: nemu64-test `rsp_timing/mod.rs:48-50` [HW-meas, ratio only] | Count `DPC_CLOCK` ticks across N VI fields with known VI timing, or against a PI/SI event of known duration |
| 1-cycle span | 1 clk per pixel | [vendor] pro-man Table 12-1, intro manual 2-7, US 6,239,810 ¶493; [wiki] Pipeline; [RTL] `RDP_raster.vhd` DRAWLINE (1 px/state); [HW-meas] cen64 129/128 slope (≈1.008 clk/px, 1-cycle) | Rectangles of width W=16…320 in 1-cycle mode, no Z, no image read; `DPC_PIPEBUSY` or the GCLK-gated time vs W |
| 2-cycle span | 2 clk per pixel | [vendor] Table 12-1, ¶495 ("slows down the pipeline by a factor of two"); [wiki]; [RTL] DRAWLINE→DRAWLINESTEP2. Outliers: gDPSetCycleType man page "2 pixels per cycle" and the US 6,239,810 abstract "two-pixel-per-cycle" (wording errors, contradicted by their own body text) | Same as above, 2-cycle |
| Fill span | 64 bits/clk → 8 px (8 bpp), 4 px (16 bpp), 2 px (32 bpp); start/end align to 8-byte words; 4 bpp crashes. Bypasses span buffers, writes straight to RDRAM | [vendor] pro-man 12.1.4 ("64 bits per clock"), Table 12-1, ¶499; [wiki] Fill Pipeline; [RTL] FILLLINE (`line_posX + 8/4/2 − addr`); [emu] cen64 occupancy model | Fill rects sweeping width/alignment. Fill is memory-bound, so isolate the compute rate with `DPC_PIPEBUSY`/GCLK vs `DPC_CLOCK` |
| Copy span | 64 bits/clk → 4 px (16 bpp), 8 px (8 bpp); 32 bpp unavailable (crash). Only alpha-compare is active | [vendor] pro-man 12.1.5 ("64 bits or 4 pixels per clock"), ¶499-500, ¶530 (4×1 texel addressing); [wiki] Copy Pipeline / Set Color Image; [emu] Angrylion `render_spans_copy` (`fbadvance` 8/4, 32 bpp → crash); [RTL] 16 bpp only, step 4; libdragon `rdpq_mode.h` ("hardware crash" at 32 bpp). Conflict: gDPSetCycleType man page "2 pixels per cycle (32-bit mode)" | Copy texrect at 8 and 16 bpp, widths 4…320 |
| Pixel size in 1/2-cycle | No compute-rate effect | No source states a size-dependent rate; [RTL] step = 1 for all sizes [inference from absence + RTL] | Same rect at 16 vs 32 bpp; the difference should be all memory (GCLK-gated) |
| Per-span (scanline) overhead | **Measured: +12 clk per span**, plus 1 clk per 128 pixel-cycles. Pipeline view: 1 dead cycle at the end of every line | [HW-meas] cen64 `rdp_core.c:5346-5362` (RECTH increments 76.8 = 64×129/128 + 12, stable h=1..64; 1-cycle; VI blanked; min-of-8); [wiki] Pipeline (dead cycle); [RTL] LINEIDLE + PREPARELINE = 2 clk, edge walk overlapped | Repeat cen64's RECTH sweep (height 1..64, fixed W) with Z/image-read off and on. Read both `DPC_CLOCK` and the GCLK-gated count to split compute from memory |
| Edge walking | 4 sub-scanlines per scanline. RTL: 1 clk each (4 clk/line), overlapped with the previous span. Lines above the scissor: 1 clk each (wiki) | [wiki] Set Scissor ("spends one cycle advancing each line"); [RTL] `RDP_raster.vhd` EVALLINE; [vendor] ¶513/¶519 (no counts) | Triangle with a large off-scissor top portion: time vs number of clipped lines |
| Per-primitive fixed cost | **Measured: 14 clk per rectangle**, including its 2-word fetch. Triangles: no hardware number. RTL: 1 clk per command word (4 / 8 / 12 / 14 / 16 / 22 words) + 2 | [HW-meas] cen64 (RECTH h=1 vs h=2 offset); [RTL] `RDP_command.vhd` EVALTRIANGLE/SHADE/TEXTURE/ZBUFFER | Sweep many 1-px triangles of each type (fill/shade/tex/Z variants); slope vs count |
| Primitive→primitive overlap | The next command starts once the last pixel of the current primitive has entered the pipeline (no drain). MiSTer drains every primitive (not hardware-like) | [wiki] Pipeline/1-Cycle Rasterize; [vendor] ¶501, FIG. 114 (attributes read by "up to two preceding primitives"); [HW-meas-derived] cen64 hazard model (command processor leads by D = min(3L−2, 25), "three-deep span buffer"); [RTL] WAITPIXELWRITE | Unsynced attribute write after a rect; count corrupted pixels (snapper64 "RDPRectNoSync" captures already do this) |
| G_PM_1PRIMITIVE (atomic_prim) | +30–40 null cycles after the last span of each primitive | [vendor] pro-man 12.2.3; 24.4.1 (≤ 1–1.5 Mpixel/s lost); FIG. 86 bit 55 | Many small tris with atomic_prim on vs off |
| Attribute setter / NOP | 1 clk each; no stall by itself | [wiki] Pipeline ("NOPs and attribute setters execute in just 1 pipeline cycle"); Commands (NOP: "TOVERIFY"); [vendor] FIG. 114 (sync_pipe is what stalls; "if attributes change per primitive, performance will degrade slightly"); [RTL] 2 clk (IDLE→EVALCOMMAND) | 1000 NOPs or setters between two syncs; ΔCMD_BUSY / 1000 |
| Sync Pipe | 50 GCLK, fixed, waits on nothing | [wiki] Commands/Pipeline (Tharo, rev 5366 2024-03-14 and rev 5599 2025-04-05; no method given). Conflict: [vendor] SGI 1996 summary, FIG. 114: "stalls until the most recent primitive is past the last usage of any attribute" (conditional). F3DEX3 `gbi.h` agrees with "fixed" | N × (sync_pipe) with no primitive in flight → slope. Repeat after a long primitive: a conditional wait would add time, a fixed stall would not |
| Sync Tile | 33 GCLK fixed | [wiki] as above. [vendor] FIG. 116 semantics only | as above |
| Sync Load | 25 GCLK fixed | [wiki] as above. [vendor] SGI summary / FIG. 112: "stalls … until preceding primitives has completely finished" (labeled 0x31 there; libultra `gbi.h` and the wiki use 0x26) | as above |
| Sync Full | Waits for all pipeline + memory ops, then stops the counters and raises DP IRQ. No fixed value. Inferred drain ≈ 30–40 clk + last span flush | [wiki] Commands; [vendor] SGI/FIG. 110 ("until the last dram buffer is read or written"); [inference] from pro-man 12.2.3 (30–40 null cycles = drain); cen64 uses 50 (assumption, its own comment) | Time from the last primitive's end to the DP interrupt / `PIPE_BUSY` stop, vs primitive type and span width |
| Mode change (cycle type, combiner, blender, othermodes) | Cost = 1 clk setter + the required Sync Pipe (50). Unsynced, the change lands 0–29 cycles into the previous primitive's tail (table in §3.7). Pipeline depth ≈ 29–30 cycles | [wiki] Pipeline table "Effect of unsynced attribute changes"; [vendor] FIG. 114; [RTL] 10-stage pipeline (not hardware-like) | snapper64-style corruption captures |
| LoadBlock | 64 bits (one TMEM word) per clk + setup. Single RDRAM span | [RTL] `RDP_raster.vhd:1191-1197,1283-1340` (8 B/clk, refill per 256 B DDR3 burst); [emu] Angrylion `loading_pipeline` (one qword per step, `tiadvance` 8); [vendor] FIG. 59 (T increments "every 8 TMEM bytes"), pro-man 13.9.3 (more memory-efficient); [wiki] "fastest way". cen64 uses (bytes+7)/8 + 1 (wiki-derived, not measured) | LoadBlock of 64…4096 B; read `DPC_TMEM` (TMEM_BUSY, net of RDRAM stalls) |
| LoadTile | 64 bits per clk per row + per-row overhead (one RDRAM request per row) | [RTL] per row: LOADIDLE + LOADRAM (memory) + LOADRAM2 + n words; [wiki] "slower than Load Block"; QA speedup "fast in the horizontal direction" | Same bytes as w×h for several shapes; `DPC_TMEM` + `DPC_CLOCK` |
| LoadTLUT | 1 entry (16 bit) per clk, replicated ×4 into the upper TMEM banks | [RTL] `spanAdvance` 1 / `memAdvance` 2 for TLUT; [emu] Angrylion TLUT path (`tiadvance` 2, `spanadvance` 1, entry replicated); [inference]: one loop step = one clock | 16 vs 256-entry TLUT loads; `DPC_TMEM` |
| TMEM texel read rate | 4 texels/clk (4 banks), enough for 1 bilinear sample/clk; 2-cycle with 2 tiles fits in 2 clk | [vendor] ¶527, ¶535, pro-man 12.4 | n/a (structural) |
| Command fetch (DP DMA) | Fetched "in small batches"; DMA waits for FIFO space. RTL: ≤22 words per burst. cen64: 64 bits/clk | [wiki] Interface; [vendor] ¶192, ¶511 ("command buffer RAM 516 … acts as a FIFO"); [RTL] `RDP.vhd:682-692` | `DPC_STATUS.DMA_BUSY` sampling; covered by the memory ticket |
| **Internal command FIFO depth** | **Unknown on hardware.** RTL: 64 × 64-bit, refetch when <32 used. Distinct from the libultra non-FIFO DMEM buffer ("up to six RDP commands") | [vendor] ¶511 (exists, size not given); [wiki] Interface (exists, "not addressable"); [RTL] `RDP_command.vhd:94-99`; [vendor] pro-man 25.2 (DMEM buffer) | §3.9 experiment |
| Span buffers | 288 bytes on chip (color half and depth/texture half); "several" span buffers; ≈3-deep | [wiki] DPS_BUFTEST_ADDR (288 B, 72-bit rows); [vendor] ¶566-567 ("several span buffers"); [HW-meas-derived] cen64 hazard "3·L−2 is a three-deep span buffer" | DPS_BUFTEST readback; hazard captures |

## 1. Clock

- 62.5 MHz:
  - pro-man §3.7 "RCP - 62.5 MHz" [vendor]
  - n64brew Interface: "DPC_CLOCK runs at the RCP frequency (which is 62.5 Mhz on standard N64, and 96 Mhz on iQue)" [wiki]
  - MiSTer PLL [RTL]
- 60.85 MHz: `osDpGetCounters` man page: "For NTSC systems, this counter increments at 60.85 Mhz and each counter tick represents approximately 16.43 nanoseconds" [vendor, verified by fetch].
- **Which is better grounded:** 62.5 MHz.
  - Three independent sources give it, and the CPU is specified at 93.75 MHz = 1.5 × 62.5.
  - nemu64-test's hardware test (COUNT runs at CPU/2; it expects `DPC_CLOCK = COUNT × 4/3 ± 20` over 100 000 counts) confirms the 3:2 CPU:RCP ratio. It cannot discriminate the absolute frequency.
  - [inference] 60.85 MHz equals 14.31818 MHz (NTSC color crystal) × 17/4. The man page may have derived the RCP clock from the wrong crystal.
  - The absolute frequency only matters when converting to wall time, so the clock ticket should settle it. Every cycle count in this document is in RCP clocks either way.

## 2. Counters that make every row measurable

| Counter | Definition | Source |
|---|---|---|
| `DPC_CLOCK` | free-running RCP clock | Interface wiki; osDpGetCounters |
| `DPC_BUFBUSY` (CMD_BUSY) | "any RCP cycle in which the internal RDP command FIFO is not empty" | wiki (Rasky, rev 5421); osDpGetCounters "CMC counter" |
| `DPC_PIPEBUSY` | wiki: gross time, counts from the first DMA "until SYNC_FULL", even when idle. osDpGetCounters: "incremented when the internal RDP pipeline is not stalled while waiting for memory accesses" (net) | **conflict**, see below |
| `DPC_TMEM` | "1 while loading bytes to TMEM … 0 when idle (or stalled for RDRAM)"; the counter stops during RDRAM stalls | wiki; osDpGetCounters |
| `DPC_STATUS.GCLK` | gated clock, stopped "any time it is stalled for RDRAM" | wiki |

- **PIPE counter conflict.** The wiki text is newer and written by people who test on hardware, but it states no method. The man page is Nintendo's but older.
- [inference] Both can be true if hardware counts "pipe busy" with the gated clock only in some revisions. That is unlikely for retail. Test it directly: a long primitive with heavy Z traffic should show `PIPEBUSY < CLOCK` delta if the man page is right.
- This matters for verification. A gated (net) counter isolates compute time from memory stalls, which is exactly the split between this ticket and the memory ticket.

## 3. Details

### 3.1 Span rates per cycle type

All vendor documents agree on the peak compute rates: pro-man Table 12-1, 12.1.4/12.1.5, intro manual 2-7, and the patents ¶493-¶500. pro-man Table 12-1 adds: "These are theoretical peak performances … Triangles have variable short and long spans and these numbers degrade rapidly."

- **Fill writes are 64-bit aligned words.** A span costs `ceil((x_end_byte − x_start_byte_aligned_down)/8)` clocks, not `px/4` [RTL FILLLINE; wiki "64-bits … at a time"]. The fill pipeline bypasses the span buffers ("Writes are committed straight to RDRAM", wiki), so its real rate is the RDRAM write rate (memory ticket). The SDK warning "do not send more than eight or nine consecutive full-screen rectangles" (gDPFillRectangle man page) is a memory-starvation hint, not a compute rule.
- **Copy has the same 64-bit granularity.** Texels are "sampled 64-bits at a time irrespective of tile format/size" (wiki). Angrylion steps `fbadvance` = 8 px at 8 bpp and 4 px at 16 bpp, and crashes at 32 bpp. Copy at 32 bpp is unavailable: wiki, libdragon "hardware crash (!)", and Angrylion all agree. The gDPSetCycleType man page's "2 pixels per cycle (in 32-bit mode)" contradicts this; it is a translated man page, and three hardware-tested sources outweigh it.
- **2-cycle** is ½ px/clk everywhere except in two wording errors (patent abstract; gDPSetCycleType "you can write 2 pixels per cycle").
  - The SDK QA "speedup" answer says 2-cycle with Z shows "virtually no decrease in speed". The same answer admits "We haven't actually measured, but we've heard…".
  - [inference] This is consistent with 1-cycle+Z being memory-bound (pro-man 12.1.3: "In one-cycle mode, the pipeline is often stalled at MI, waiting for the framebuffer when accessing both color and z"). It belongs to the memory ticket, not to the compute rule.

### 3.2 Per-scanline overhead: the three sources disagree in kind

| Source | Per-line rule | What it measures |
|---|---|---|
| cen64 (jgemu) comment `rdp_core.c:5346-5361` | `pixel_cycles×129/128 + 12` per span, 14 per primitive | hardware DPC probe, 1-cycle, VI blanked, min-of-8 runs; RECTW, RECTH, RECTN, SPAN, DUTY sweeps; e.g. "RECTN 320x6 (2021.4 measured / 2021 predicted)", "320x240 DUTY primitive (80287 measured / 80294 predicted)" |
| n64brew Pipeline | "1 dead cycle at the end of every line in a primitive where the pipeline is cycled but no pixel is output" | pipeline slot position (pixel-corruption counting) |
| MiSTer RTL | LINEIDLE + PREPARELINE = 2 clk per line; edge walk (4 sub-lines × 1 clk) overlapped with the previous span; plus a whole-span DDR3 read before each line when Z or image-read is on | FPGA design, not Nintendo RTL |

**Best available knowledge:** the cen64 law, for throughput. It is the only hardware-measured number, its fits are tight (≤ 0.02 % on 80k cycles), and it was cross-checked on several shapes.

Caveats:

- **Missing configuration.** The comment does not say which counter was read or the othermodes used (Z, image-read, framebuffer size). The raw `dpc_probe` data is not public.
- **Unexplained 129/128 factor.** [inference] It is probably RDRAM refresh or memory-side, since "VI blanked" removes VI traffic but not refresh.
- **The 12 cycles/span is probably not edge-walk compute.** [inference] It most likely includes the per-row span-buffer flush to RDRAM. n64brew Set Color Image: "for single rows span buffers are employed to alleviate stalls … there is no such buffering across multiple rows". That makes it partly a memory term, with a value that would change with Z/image-read/bpp. The "dead cycle" (wiki) and this term are different quantities, and no source reconciles them.
- **Other cycle types are not measured.** cen64 applies the same 14 + 12/span to 2-cycle, copy and fill "as a same-silicon assumption" (its own words).

### 3.3 Edge walking and setup

- The edge walker produces spans at sub-scanline resolution (4 per line) [vendor ¶513/¶519 describe the structure, no counts; RTL EVALLINE 1 clk per sub-line].
- Lines above the scissor are not free: "for every line for which a primitive extends above the scissor region the RDP spends one cycle advancing each line, since it must update the attribute start values for each line" (wiki, Set Scissor). Left/right/bottom scissor rejection is "at no cost in time".
  - MiSTer spends 4 clk per such line (one per sub-line). The wiki statement is more specific and comes from the documenter who produced the hardware-derived corruption tables. Neither states a method.
  - Hardware probe: a primitive with K lines above the scissor.
- **Triangle setup: no measured or vendor number.**
  - [RTL] Command words are consumed at 1 per clk: tri 4 words, +8 shade, +8 tex, +2 Z, so 4–22 clk plus ~2 state transitions.
  - [inference] The hardware command path is 64 bits wide (patent ¶192 and wiki: commands are 64-bit words), so ≥ 1 clk per word is a floor. cen64's 14 clk per 2-word rectangle suggests a fixed ~10+ clk start cost beyond the words. Both are inferences; triangles need their own probe.

### 3.4 Primitive overlap and pipeline depth

- n64brew: "Only once the last pixel in the primitive has been enqueued into the first stage of the rest of the pipeline are any new RDP commands executed."
- SGI/patent FIG. 114: attributes may be "read by up to two preceding primitives".
- The cen64 hazard model is fitted 7332/7332 to HailToDodongo's snapper64 hardware captures:
  - span clocks `L = max(cyc·W + cyc − 1, 4)`
  - command-processor lead `D = min(3L − 2, 25) + OFF`
  - "3·L − 2 is a three-deep span buffer; 25 is one fixed pixel-pipeline latency, the SAME constant in both cycle modes"
- Conclusion [best available]:
  - Primitives pipeline back to back.
  - The command processor runs up to ~25 clocks (or 3 spans) ahead of pixel output.
  - The pipeline latency is ~25–30 clocks.
  - MiSTer's per-primitive drain (`WAITPIXELWRITE`, `RDP_command.vhd:672-675`) adds a full drain per primitive, which hardware does not do.
- The SDK confirms the order of magnitude: G_PM_1PRIMITIVE adds "30 to 40 null cycles after the last span of a primitive" (pro-man 12.2.3). A forced drain is therefore ≈ 30–40 cycles.

### 3.5 Syncs

- **n64brew, Commands** (verified in the raw wikitext): "Stalls the RDP pipeline for exactly 25 GCLK cycles … The stall is always 25 cycles and does not wait on any particular internal signal(s)". It gives 50 for pipe and 33 for tile.
  - GCLK is the gated clock, so in `DPC_CLOCK` terms a sync takes ≥ 25/33/50 if an RDRAM stall overlaps it [inference from the GCLK definition].
  - Provenance from the page history: added by Tharo, rev 5366 (2024-03-14) and Pipeline rev 5599 (2025-04-05). There is no citation. The values are consistent with the corruption table, whose longest entry is 29 < 33 < 50.
  - The wiki itself speculates that "There is no known attribute that takes more than 33 cycles to sync".
- **Vendor documents** (SGI 1996 summary, patents FIG. 110-116, SDK 12.2.2, man pages) give semantics only and phrase pipe/load sync as conditional waits ("stalls until …"). No vendor document gives a number.
- **Which is better grounded:** the fixed counts, for timing.
  - They are specific, consistent with the hardware corruption table, and repeated independently by F3DEX3's author ("These syncs do NOT wait until something is finished being used", `gbi.h` ~L4185).
  - A fixed stall long enough to cover the pipeline depth is also exactly how a "conditional" description would behave from software's point of view.
  - Still, no published measurement exists for the counts. The verification in the table (sync throughput with and without a long primitive in flight) settles both the value and fixed-vs-conditional.
- **Sync Full** has no fixed cost. It ends when "all currently staged pipeline and memory operations" complete (wiki), i.e. pipeline drain plus the final span-buffer write-back.
  - cen64 charges 50, explicitly as a stand-in.
  - [inference] A model should charge pipeline drain (≈ 25–40) plus the memory write of the last spans (memory ticket).

### 3.6 TMEM loads

- **No vendor or hardware-measured load rate exists.** The best available rule comes from two implementations whose structure matches the vendor description (64-bit TMEM words, ¶535; DxT "every 8 TMEM bytes", FIG. 59):
  - MiSTer `RDP_raster.vhd`: `spanAdvance` 8/4/2 texels (8/16/32 bpp) with `memAdvance` = 8 bytes per clk; TLUT 1 entry with 2 bytes per clk; DDR3 refill every 32 words.
  - Angrylion `loading_pipeline` (`tex.c:487`): `tiadvance` 8 and `spanadvance` 8/4/2; TLUT `tiadvance` 2 and `spanadvance` 1, entry replicated into 4 halfwords; 4 bpp loads crash ("rdp_pipeline_crashed").
- Rule [RTL + emu; inference that one loop step = one clock]:
  - LoadBlock ≈ `ceil(bytes/8)` clk + start.
  - LoadTile ≈ Σ rows (`ceil(row_bytes/8)` + per-row start + RDRAM row fetch).
  - LoadTLUT ≈ entries clk + start.
- Vendor statements are relative only:
  - LoadBlock is "more memory-bandwidth efficient … allows the MI to transfer the maximum amount of data for each transfer" (pro-man 13.9.3).
  - "Load Tile is slower than Load Block" (wiki).
  - Loads share the edge walker and span buffers with rendering. The wiki says "Texture data is held in spans as it is loaded from RDRAM before being shuffled into TMEM", and the loading pipeline "cannot be executed in parallel" with rendering.
- Direct verification: `DPC_TMEM` counts load cycles net of RDRAM stalls, so `ΔDPC_TMEM / bytes` gives the compute rate with memory removed.

### 3.7 Mode-change pipeline costs (n64brew corruption table)

Cycles of the previous primitive affected by an *unsynced* change, 1-cycle / 2-cycle. These are the clock offsets at which each attribute is sampled after the command processor, which gives the pipeline position of each unit:

- 0/0: color image, image_read_en, z_compare_en, z_update_en
- 7/4: persp_tex_en
- 13/10: tile settings
- 13/12: tex_lod_en
- 17/14: sample_type
- 18/16: tlut_en
- 20/18: tlut_type
- 21/18: mid_texel
- 24/22: combiner, convert
- 25/24: alpha_cvg_select, cvg_x_alpha, key_en, z_source_sel, alpha_dither_sel
- 26/24: blender
- 27/26: z_mode, force_blend, antialias_en
- 28/28: cvg_dest, color_on_cvg
- 29/28: rgb_dither_sel, alpha_compare_en

Timing consequences:

- (a) Correct code pays the sync (50) plus 1 per setter.
- (b) No change triggers an implicit drain.
- (c) The pipeline is ~29–30 stages deep in 1-cycle terms, against MiSTer's 10-stage `RDP_pipeline.vhd`.
- (d) Patent FIG. 114: "If attributes change per primitive, performance will degrade slightly". The degradation is the syncs.
- Four attributes need no sync: prim color, prim depth, scissor, tile size (wiki; SDK gDPPipeSync man page lists the first three).

### 3.8 Pixel size

No source gives a size-dependent rate for 1/2-cycle spans. Size changes bytes per span, so it changes the memory term and the per-span constant that cen64 measured at an unstated size. Fill and copy are size-dependent through the 64-bit word rule (§3.1).

### 3.9 Command FIFO depth: proposed hardware measurement

- What the sources say:
  - The patents (¶511) say only that "command buffer RAM 516 … acts as a FIFO" and that the RDP halts when it is empty.
  - The wiki says the DMA fetches "in small batches" and "will then wait for space to become available".
  - The libultra DMEM buffer ("up to six RDP commands", pro-man 25.2) is the RSP-side XBUS buffer, not this FIFO.
  - MiSTer's 64-word, nearfull-at-32 FIFO is a design choice.
- Measurement:
  1. Queue a very long primitive (a full-screen 2-cycle rect) followed by N ≫ 64 NOPs from RDRAM.
  2. While the rect renders (`CMD_BUSY` set), read `DPC_CURRENT`.
  3. `DPC_CURRENT − end_of_rect` is the prefetched byte count, an upper bound on the FIFO depth.
  4. Sample repeatedly to see the refill granularity (how far `DPC_CURRENT` jumps), which gives the fetch batch size.
- This matters for MM. The `_fifo` microcode throttles on `DPC_CURRENT`, so the RSP-side back-pressure depends on this depth.

## 4. Implications for the ares timing model

These are inferences for the downstream implementation tickets; they are not hardware facts.

- Use vendor peak rates for the per-pixel term.
- Use cen64's measured `14 + Σ(px·cyc·129/128 + 12)` as the 1-cycle throughput baseline. Treat the 12/span and 129/128 as parameters to re-measure per mode, because they likely contain memory time that the memory model would otherwise double-count.
- Do not drain between primitives. Do charge 1/clk per setter and 25/33/50 per sync.
- Charge loads at 8 B/clk (TLUT at 1 entry/clk) plus per-row start.
- Model Sync Full as drain plus write-back.

## Sources

Hardware-measured:

- cen64 jgemu fork `src/rdp/rdp_core.c` (span law comment L5346-5362; hazard model L144-170; fixed-cost table ~L4930-4990) and `src/rdp/interface.c` (L71-96, L129-133: "The FIFO depth is undocumented"). https://gitlab.com/jgemu/cen64 @ `2f8d7bc`. The dpc_probe tool and raw data are not public.
- snapper64 hardware captures (pixel output, used by the cen64 hazard fit): https://github.com/HailToDodongo/snapper64
- nemu64-test `src/tests/rsp_timing/mod.rs:33-80` (COUNT vs DPC_CLOCK ratio), `src/tests/rdp/mod.rs:260-345` (DPC status sequencing). https://github.com/thelemmy/nemu64-test @ `9a8b9f7`.

Vendor (Nintendo/SGI):

- N64 Programming Manual (man-v5-1): ch.12 index Table 12-1; 12-01 (12.1.2-12.1.5); 12-02 (12.2.2-12.2.3); 12-04; 13.9; 24-04; 25-02; §3.7. https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro12/index.htm (and siblings)
- Man pages: gDPSetCycleType, gDPPipeSync, gDPTileSync, gDPLoadSync, gDPFullSync, gDPPipelineMode, gDPFillRectangle, osDpGetCounters. https://ultra64.ca/files/documentation/online-manuals/man-v5-1/n64man/
- N64 intro manual 2-7 (kantan) and N64 Q&A "speedup" (ultra64.ca).
- SGI "Nintendo Ultra64 RDP Command Summary" v2.0, 1996-04-11, pp. 41-44. https://hcs64.com/files/RDP_COMMANDS.pdf
- US 6,239,810 B1 ¶116, ¶131, ¶168, ¶192, ¶370, ¶493-501, ¶508-513, ¶519-520, ¶527-540, ¶566-567. https://patents.google.com/patent/US6239810B1/en
- US 6,166,748 A (same description); drawings FIG. 55, 57, 59, 63, 86-87, 98, 110-118. https://patents.google.com/patent/US6166748A/en ; https://patentimages.storage.googleapis.com/74/31/d3/a9a9ce55b2c104/US6166748.pdf
- Also checked (same spec, no extra timing): US 6,331,856; 6,342,892; 6,556,197; 6,593,929. Not relevant: US 5,949,421; 5,854,631; 6,002,406.

n64brew (fetched 2026-10-04; authorship from MediaWiki history):

- https://n64brew.dev/wiki/Reality_Display_Processor/Pipeline (rev 5599, Tharo)
- https://n64brew.dev/wiki/Reality_Display_Processor/Commands (sync text rev 5366, Tharo)
- https://n64brew.dev/wiki/Reality_Display_Processor/Interface (CMD_BUSY text rev 5421, Rasky; span buffer rev 5377, Tharo)

RTL / emulator source:

- MiSTer N64_MiSTer `5725381`: `rtl/RDP_command.vhd` (FIFO L94-111; state machine L163-688), `rtl/RDP_raster.vhd` (poly L555-760; line L885-1170; load L1185-1345), `rtl/RDP_pipeline.vhd` L149-160, `rtl/RDP.vhd` L470-520, L682-692. https://github.com/MiSTer-devel/N64_MiSTer
- angrylion-rdp-plus `9c8b9ed`: `src/core/n64video/rdp.c` L595-620 (syncs are no-ops), `rdp/tex.c` L487-560 (loading pipeline), `rdp/rasterizer.c` L1879-1925 (copy).
- parallel-rdp-standalone `1cecd04`: no timing model (grep).
- libdragon `e356bf3`: `include/rdpq.h`, `include/rdpq_mode.h`, `src/rdpq/rdpq.c` (no cycle figures).
- F3DEX3 `gbi.h` (sync comment), Counters.md, https://hackern64.github.io/F3DEX3/performance.html
- MM decomp: `include/PR/gbi.h:120-123` (sync opcodes 0xE6-0xE9 = 0x26-0x29 | 0xC0).
