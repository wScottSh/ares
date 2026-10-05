# RDP pixel-timing coupling

Ticket: wScottSh/ares#12 (map #1). Target: NTSC retail NUS-001 with Expansion Pak.

Question: which RDP internal results does command duration depend on, can a CPU-side model fed only the command stream compute exact duration without rendering pixels, and what would paraLLEl-RDP or Angrylion have to expose?

Tags: **[cited]** = stated in the referenced document; **[source]** = read in the referenced code at the given commit; **[inference]** = my reasoning from those, not stated anywhere.

## TL;DR

- **No. Exact duration cannot be computed from the command stream alone.** The fixed-function part *can* be: span count, span x-extents, pipeline cycles per span, color/Z span **reads**, texture loads, sync and atomic-primitive dead cycles, and every RDRAM address. All of these depend only on command fields, mode bits and scissor, never on pixel values.
- **Write traffic is the coupling.** Nintendo's own manual says the Z test is a *conditional write*. It says obscured pixels are "read only (no write)" and that this improves fill rate (SDK Programming Manual ch. 12-07 and 24-04) [cited]. MiSTer implements writes per pixel, gated by the per-pixel write enable (`RDP_pipeline.vhd:944-967`) [source]. That write enable is computed per pixel from:
  - coverage
  - `cvg_x_alpha`
  - alpha compare: combiner alpha, i.e. texture, shade, prim/env, chroma key and alpha-dither noise
  - the Z compare against the Z buffer contents and the memory coverage bits stored in the color buffer

  So the color and Z write traffic of each span depends on rendered results and on prior framebuffer/Z contents.
- **Where references conflict.** The RCP patent says the memory interface "writes the entire span worth of pixels into main memory as a block all at once" (US 6,166,748) [cited]. Taken literally, write cost would be mask-independent. **Judgement:** the SDK statement is specific and performance-oriented. The patent sentence is a high-level description of buffering, and both can be true if the "block" covers only the written ("active", per n64brew's `atomic_prim` wording) segments. So treat write cost as result-dependent. The granularity is not documented: per pixel, per 8-byte word, or per contiguous segment.
- **When writes matter.** Only when the memory interface, not the pipeline, is the bottleneck. 1-cycle Z+AA at 16 bpp needs ~8 B/pixel (color R+W, Z R+W). At 62.5 Mpx/s that is ~500 MB/s, about the RDRAM peak, so the main MM render modes are memory-bound and write skipping changes duration [inference].
- **What a timing model needs beyond the command stream:** per span (primitive × scanline), the set of 8-byte color words and Z words that receive at least one write. Getting it needs the full per-pixel write-enable path, which means rendering:
  - Angrylion already computes it on the CPU (`wen` in its span loops) [source].
  - paraLLEl computes it on the GPU, but only keeps a per-render-pass union mask, not per span [source].
- **Hard limit.** With alpha-dither noise or combiner NOISE feeding the alpha compare, the write enable depends on three hardware LFSRs that step once per RDP clock (Thar0/RDP-Noise) [cited]. That makes writes depend on timing itself, which is a circular coupling. Neither Angrylion (software `irand`) nor paraLLEl (hash of x, y, primitive) reproduces the hardware LFSR [source]. MM's C source never sets `G_AC_DITHER` (grep: only `include/PR/gbi.h`), but it does use `G_AD_NOISE` (`z_kankyo.c:2927`, `z_rcp.c:17`) [source].

## Dependency table

| Internal result | Affects duration? | How | References |
|---|---|---|---|
| **Span x-extents / count** (edge walk, 4 sub-scanlines, scissor, interlace keep-odd, all-invalid/over/under lines) | Yes, **computable** | Pipeline cycles = span pixels × cycle-type rate. Lines with no valid sub-scanline are skipped. Extents depend only on edge coefficients and scissor, with the exact fixed-point walk. | MiSTer `RDP_raster.vhd:622-736` (min/max over 4 sub-lines, skip on `allinval/allover/allunder/scissorNow`) [source]. Angrylion `rasterizer.c:2390-2400` (`validline`, `scfield`) [source] |
| **Per-pixel coverage = 0 inside the span** | Compute: **no**. Reads: **no**. Writes: **yes** | Every pixel from xstart to xend takes a pipeline slot whatever its coverage (Angrylion loop `rasterizer.c:416-547`; MiSTer `DRAWLINE` steps every x). Zero-coverage pixels are rejected at output, so they are not written. | Angrylion `blender.c:272` (`antialias_en ? cvg : cvbit`) [source]. MiSTer `RDP_pipeline.vhd:965-967` [source]. n64brew Pipeline: "Pixels that are not rejected … are written to the on-chip span buffers" [cited] |
| **AA coverage value** (incl. `cvg_x_alpha`, `alpha_cvg_select`) | Writes: **yes**. Reads: mode-only | `cvg_x_alpha` scales coverage by combiner alpha, so texture alpha can zero the coverage and reject the pixel. `RM_AA_ZB_TEX_EDGE` sets `CVG_X_ALPHA | ALPHA_CVG_SEL` (`include/PR/gbi.h:682-685`) [source]. AA itself doubles framebuffer traffic (adds the color read), and that is mode-determined. | Angrylion `combiner.c:254-277` [source]. SDK kantan 4-2-5: AA "needs to … read the frame buffer, and write the update … memory access … increases by a factor of two" [cited] |
| **Z-compare outcome** | Writes: **yes**. Reads: **no** | Z is read for the whole span when `z_compare_en` is set. Color and Z writes are suppressed for failed pixels. SDK: "the z-buffer test is a read only (no write) for obscured pixels" and front-to-back order "improves fill rate". The outcome depends on Z buffer contents, `dz`, `z_mode`, and the memory coverage from the color buffer's hidden bits. | SDK ch. 12-07 and 24-04 [cited]. Angrylion `zbuffer.c:219-320`, `rasterizer.c:535-544` [source]. MiSTer `RDP.vhd:663-666,730-733` (Z span read gated only by `zCompare`) and `RDP_pipeline.vhd:955` (Z write gated by `zUsePixel and zUpdate`) [source]. n64brew Commands: `z_compare_en` = "Enable z-buffer reading and depth comparison" [cited] |
| **Alpha compare** (threshold = blend alpha, or noise if `dither_alpha_en`) | Writes: **yes** | Rejected pixels are not written. The input is combiner alpha (texture, shade, prim, env, key alpha) plus alpha-dither noise (`adseed`). | Angrylion `blender.c:72-90,264`, `combiner.c:263-268` [source]. MiSTer `RDP_pipeline.vhd:960-963` (`blend_alphaIgnore`) [source] |
| **Blend decision** (`blend_en`, `color_on_cvg`, coverage wrap, `force_blend`) | **No** | It picks *which* color is written, not *whether* a write happens. `color_on_cvg` still writes (memory color verbatim). | Angrylion `blender.c:272-290` [source]. n64brew Commands `color_on_cvg` [cited] |
| **Texture contents** | Indirectly, writes only | Only through alpha → alpha compare / `cvg_x_alpha` / chroma key. TMEM sampling is fixed-rate. No data-dependent texture stall is documented in any reference checked. Load durations depend on size and address, not contents. | SDK ch. 12-04/05 [cited]. MiSTer texture path has no data-dependent stall (`RDP_raster.vhd` stall only from write FIFOs, `RDP.vhd:1377`) [source] |
| **Copy-mode alpha compare** | Writes: unclear | n64brew says only texels that pass are written [cited]. MiSTer writes every 64-bit word with a byte-enable mask, so its cost is independent of alpha (`RDP_pipeline.vhd:795-816`) [source]. Hardware granularity is undocumented. | n64brew Pipeline "Copy Pipeline" [cited] |
| **Fill mode** | **No** (computable) | Unconditional 64-bit writes that bypass the span buffers. | n64brew Pipeline "Fill Pipeline" [cited]. MiSTer `RDP_raster.vhd:1112-1166` [source] |
| **Color buffer contents** | Writes: **yes, via coverage bits only** | The memory coverage (hidden/9th bits) feeds the Z compare overflow test and `cvg_dest` save. RGB contents never gate a write. | Angrylion `zbuffer.c:292` [source]. SDK ch. 12-08 (9-bit DRAM, extra bits per pixel) [cited] |
| **Color/Z span reads** | Yes, **computable** | Prefetched for the whole span "as soon as the X, Y coordinates of the span are determined", gated by `image_read_en` / `z_compare_en`. Not per-pixel. | SDK ch. 12-02 "Span Buffer Coherency" [cited]. Patent US 6,166,748 [cited]. MiSTer `RDP.vhd:638-670` (one burst of span length per enabled buffer) [source] |
| **Atomic primitive / syncs / per-line dead cycle** | Yes, **computable** | `G_PM_1PRIMITIVE` adds "30 to 40 null cycles after the last span of a primitive" (SDK 12-02). Pipe/tile/load sync = 50/33/25 cycles, and there is 1 dead cycle per line (n64brew). The patent text says "adding no cycles", which conflicts. Judgement: the SDK (more specific, and backed by 24-04's "lost cycles … 1-1.5 Mpixels/sec") wins. | SDK 12-02, 24-04 [cited]. n64brew Pipeline [cited]. Patent [cited]. MM file select uses `G_PM_1PRIMITIVE` (`z_file_choose_NES.c:26`) [source] |
| **RDRAM bank/page state, refresh, other bus masters** | Yes, not pixel-dependent | Addresses are computable. Latency depends on bank placement ("keeping the color and z-buffers on different banks … improve[s] the DRAM access latency", SDK 12-08) and on CPU/VI/AI/PI traffic. This is a system-state coupling, not an RDP-result coupling. | SDK 12-08 [cited]. n64brew Commands Set Color Image: span buffers relieve stalls within a row, "no such buffering across multiple rows" [cited] |
| **Noise LFSR state** | Writes: **yes** in noise-alpha modes | Three LFSRs (degrees 29/28/27) step per RDP cycle. A line switch "eats 1 cycle". The noise therefore depends on the exact cycle timeline, which makes this a circular dependency. Whether the LFSRs step during memory stalls is not documented. | Thar0/RDP-Noise README [cited]. paraLLEl `noise.h:29-36` hash, README "not particularly meaningful to exactly reproduce noise" [source/cited]. Angrylion `blender.c:82` `irand` [source]. MiSTer uses a different 23-bit LFSR (`RDP_pipeline.vhd:473-474`) [source] |

## What a CPU-side model can and cannot do

**From the command stream alone** (replicate the edge walker bit-exactly; ares's `rdp/render.cpp` already decodes the fields):

- spans per primitive and x-extents
- pipeline cycles (1-cycle 1 clk/px, 2-cycle 2 clk/px, copy 4 px/clk, fill 8 B/clk; prior synthesis, `n64-emulator-timing-model.md` §2)
- read bursts per span (color if `image_read_en`, Z if `z_compare_en`)
- texture-load bursts
- sync and atomic dead cycles
- all addresses for the bus model

This gives an exact **lower bound** on write traffic (fill mode, plus spans with no conditional rejection). It also gives an **upper bound**: all pixels in [xstart, xend] written.

**Not from the command stream:** the actual write set in 1-/2-cycle modes with Z compare, AA, alpha compare or `cvg_x_alpha`. That set depends on the Z buffer and coverage-bit contents, which are the accumulated result of every earlier draw and of CPU writes, and on texture and shade alpha. Computing it means running the per-pixel combiner, alpha compare, coverage and Z-compare path, which is rendering minus only the final color math [inference].

**Granularity:** what the bus model needs per span is the number and placement of RDRAM write transactions. The hardware granularity is not documented. Candidates, ordered by how much they need:

- (a) a count of 8-byte words with any written byte. This is MiSTer's behavior: `pixel64` coalescing in `RDP.vhd:1398-1402`.
- (b) contiguous written segments, the reading that fits the patent's "block" plus n64brew's "active span segments" [inference].
- (c) a full per-pixel mask.

Producing (c) also covers (a) and (b).

## What paraLLEl-RDP / Angrylion would need to expose

**Angrylion (CPU, `ata4/angrylion-rdp-plus` 9c8b9ed):**

- The span loops already compute `wen` for each pixel, in order, per primitive and scanline (`rasterizer.c:535-547` and the 2-cycle/copy equivalents).
- Exposing it is a callback or counter at the `fbwrite_ptr` / `z_store` call sites, keyed by (primitive, y). It emits written-word bitmaps for color and Z.
- Its rendering order matches the command stream, so the timing model can consume results synchronously.
- Cost: a full CPU software renderer running alongside paraLLEl. ares removed the MAME CPU RDP for being "too slow to be usable" (`5f9804fb6`) [cited, prior synthesis].
- Its noise (`irand`) does not match hardware, so noise-alpha modes stay inexact.

**paraLLEl-RDP (GPU, vendored `1cecd042b`):**

- The per-pixel write decision is made in `depth_blend()` (`shaders/depth_blend.comp`, `ubershader.comp:90-95`).
- The only persistent record is a per-render-pass RDRAM write mask used for resolve (`masked_rdram_resolve.comp`, `update_upscaled_domain_resolve.comp:193-202`). That mask is a union over all primitives, with no primitive or span identity.
- **Needed additions:**
  - (1) A per-(primitive, y) counter or bitmap of written color and Z words, filled with atomics in the depth/blend stage.
  - (2) A CPU readback of that buffer before the timing model retires the corresponding commands. This adds a GPU→CPU sync point per batch: either the timing model lags rendering, or `DPC_CURRENT`/the DP IRQ wait on the GPU.
  - (3) Hardware-LFSR noise if noise-alpha modes must be exact (its README says noise is intentionally not reproduced).
- paraLLEl aims to be bit-exact with Angrylion "where possible" (README), so in non-noise modes its write sets should match Angrylion's [cited].

**Replicating rather than sharing:** a "write-predictor" that runs only coverage + alpha + Z compare (no texture filtering, no color blend) still needs:

- texture sampling (for alpha)
- the combiner alpha path
- a private shadow copy of the Z buffer and color coverage bits, kept in sync with every CPU/DMA write to those regions

That is most of an RDP [inference]. Sharing results from the renderer that already runs is the more faithful route.

## New sharp questions

1. **Hardware write granularity.** Does a span with partially rejected pixels issue (a) one masked RDRAM burst of full span length, (b) bursts only for 8-byte words containing written pixels, or (c) contiguous segments? Is a fully rejected span written at all? This decides whether coupling matters at all, and no source settles it. A hardware ROM could tell: draw an identical Z-failed vs Z-passed triangle and compare `DPC_CLOCK`/`PIPE_BUSY`.
2. **Do the noise LFSRs advance during memory stalls**, and what is their power-on state? This determines whether noise-alpha write sets are reproducible even with a perfect renderer.
3. **Atomic-primitive cost.** Is it 30-40 null cycles (SDK) or "no cycles" (patent)? This matters for MM's file-select menu (#2320), which sets `G_PM_1PRIMITIVE`.
4. **Copy-mode alpha-compare writes:** masked full word (MiSTer) or skipped?

## Sources

- US 6,166,748 (Van Hook et al., Nintendo), "Interface for a high performance low cost video game system…": memory interface / span buffer / depth comparator / atomic-space paragraphs. https://patents.google.com/patent/US6166748A/en
- N64 SDK Programming Manual (Nintendo of America, 1999), via ultra64.ca:
  - ch. 12-02 RDP Global State, "Span Buffer Coherency": https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro12/12-02.html
  - ch. 12-07 BL: https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro12/12-07.html
  - ch. 12-08 MI: https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro12/12-08.html
  - ch. 24-04 Raster Tuning: https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro24/24-04.html
  - Introduction to N64 Programming 4-2 (AA / Z-buffering tips): https://ultra64.ca/files/documentation/online-manuals/man/kantan/step2/4-2.html
- n64brew wiki (fetched 2026-10-04; Pipeline page last edited 2025-10-09):
  - https://n64brew.dev/wiki/Reality_Display_Processor/Pipeline
  - https://n64brew.dev/wiki/Reality_Display_Processor/Commands (Set Other Modes, Set Color Image)
- Thar0/RDP-Noise (LFSR reverse engineering from hardware captures): https://github.com/Thar0/RDP-Noise
- MiSTer N64 core `rtl/RDP_raster.vhd`, `RDP_pipeline.vhd`, `RDP.vhd` @ 5725381 (2026-09-27): https://github.com/MiSTer-devel/N64_MiSTer
- Angrylion-Plus `src/core/n64video/rdp/{rasterizer,blender,combiner,zbuffer}.c` @ 9c8b9ed (2024-12-28): https://github.com/ata4/angrylion-rdp-plus
- paraLLEl-RDP @ 1cecd04 (README; `shaders/noise.h`, `depth_blend.comp`, `ubershader.comp`, `masked_rdram_resolve.comp`, `update_upscaled_domain_resolve.comp`), vendored in ares `ares/n64/vulkan/parallel-rdp`: https://github.com/Themaister/parallel-rdp
- Prior synthesis: mm-decomp-60fps `docs/research/n64-emulator-timing-model.md`.
- MM decomp grep (`G_AC_DITHER`, `G_AD_NOISE`, `G_PM_1PRIMITIVE`), mm-decomp-60fps @ 56fa21dd0.
