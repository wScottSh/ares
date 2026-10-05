# RDP noise generators: stepping, reset state, sharing, and MM usage

Ticket: wScottSh/ares#18. Map: #1. Follows #12 ([rdp-pixel-timing-coupling.md](https://github.com/wScottSh/ares/blob/research/rdp-pixel-timing-coupling/docs/research/rdp-pixel-timing-coupling.md)).
Target: NTSC NUS-001 + Expansion Pak. MM refs are to mm-decomp-60fps @ 56fa21dd0 (US retail ROM for binary scans).

Tags: **[hw-data]** derived here from Thar0's console dumps; **[source]** read in code; **[doc]** SDK/n64brew text; **[inference]** reasoning, not measured.

## TL;DR

- **Combiner NOISE comes from three Fibonacci LFSRs** (degrees 29/28/27, `x^29+x^2+1`, `x^28+x^3+1`, `x^27+x^5+x^2+x+1`). `NOISE = a<<8 | b<<7 | c<<6 | 0x20`. Re-ran Thar0's solver; it reproduces this. [hw-data]
- **Reset state: all ones, and the three step in lockstep.** New result from Thar0's data. Start a and b from all-ones (Thar0's register convention), step both exactly 256,586,636 times, and the next 1016 outputs match the dump bit-for-bit (0/1016 mismatches each). A chance match of both is about 1 in 2^28. In all four c captures, c sits at the same count +1. [hw-data]
- **Stepping: one step per pixel inside a span, and steps keep coming when no pixels are produced.**
  - Within a 1016-px 1-cycle span: exactly one step per pixel. Dropping or holding a single step anywhere makes Berlekamp-Massey complexity jump from 29 to 127–877. [hw-data]
  - The four c captures are exactly 1787 steps apart, about 771 steps more than their 1016 pixels. Something other than pixel output advances the LFSRs. [hw-data]
  - Best reading: **the LFSRs step on every RDP clock, memory-stall clocks included.** That is consistent with 256.6M steps ≈ 4.11 s at 62.5 MHz from reset to the test rectangle. [inference]
  - This contradicts the README's "switching to a new line eats 1 cycle". The data wins (see Conflicts).
- **Only combiner NOISE is characterized on hardware.** Alpha-dither noise (`G_AD_NOISE`), RGB noise dither (`G_CD_NOISE`) and the alpha-compare random threshold (`G_AC_DITHER`) have no hardware data.
  - Angrylion and paraLLEl feed `G_AD_NOISE` from the same 3 noise bits as the combiner. MiSTer uses a different single 23-bit LFSR.
  - `G_CD_NOISE` (9 bits, per channel) and `G_AC_DITHER` (8 bits) need more bits than a/b/c give per clock, so their source is open. [inference]
- **MM: noise changes write decisions in exactly two effects, both full-screen 320×240 XLU texrects in SETUPDL_64:**
  - mode: 2-cycle, `G_AC_THRESHOLD` + `G_AD_NOISE`, `alpha_cvg_sel=0`, no key
  - the sandstorm/blizzard overlay (`Environment_DrawSandstorm`)
  - the Song of Storms screen overlay (`OceffStorm_Draw2`)
  - A pixel is written iff `alpha + noise(0..7) ≥ blend alpha`. The frame default threshold is 8, so only pixels with compared alpha 1–7 are noise-gated (the threshold value at draw time is [inference]).
  - MM never uses `G_AC_DITHER` (source plus binary ROM scan). It never uses chroma key, so combiner NOISE (RGB only) and `G_CD_NOISE` never reach a write decision.
- **For the timing model:** exact noise needs the exact RDP clock count since reset, stalls included. It's circular (noise → writes → bus → stalls → noise) but bounded to those two effects and alpha 1–7 pixels. Whether a write-enable change alters bus traffic at all depends on #17 (write granularity).

## Behavior table

| Behavior | Rule | References | How verified |
|---|---|---|---|
| Combiner NOISE value | 9-bit `abc100000`, a/b/c = current outputs of three LFSRs; the combiner clamps it like any 9-bit input | Thar0 README + `rdp_noise_lfsr.c`; n64brew RDP Commands (CC input 7) | [hw-data] Re-ran Thar0's `rdp_noise_lfsr.c` @ e7f6c7f: BM gives deg 29/28; brute force gives the c poly on all 4 c datasets |
| LFSR polynomials (Fibonacci recurrences) | a: `s[t]=s[t-2]^s[t-29]`; b: `s[t]=s[t-3]^s[t-28]`; c: `s[t]=s[t-1]^s[t-2]^s[t-5]^s[t-27]`. All primitive, periods 2^n−1 | Thar0 | [hw-data] reproduced |
| Steps within a span | Exactly 1 step per pixel in 1-cycle mode across 1016 consecutive px; no skips, no holds | Thar0 data | [hw-data] Deleting or duplicating one sample at px 100/300/508/700/900 raises BM complexity from 29→129…877 (a) and 28→127…873 (b). The real data has none |
| Steps outside pixel output | Consecutive c captures are exactly 1787 steps apart (4 sets, 3 gaps) for 1016 px each: ~771 non-pixel steps per capture interval | Thar0 c datasets | [hw-data] Phase search: a-phase (from A=1 ⇔ C unknown) and c-phase both step by −1787 from set 0→3. Capture geometry (consecutive lines vs. back-to-back rects) is not documented, so the cause of the 771 is [inference] |
| Clock domain of stepping | Every RDP clock, including memory-stall and inter-span clocks, not only pipeline-advance cycles | Above two rows; MiSTer `RDP_pipeline.vhd:473-474` also steps unconditionally per `clk1x` (different LFSR) | [inference] from the 771-step gap. Compare cen64-jgemu's hardware-fit formula (px×129/128+12, bpp unstated), which predicts ~1036 clk for a 1016-px span, and n64brew's "1 dead cycle per line". If those gaps were lines, the extra must be 32 bpp span flush time. Not tested whether it runs while the RDP is idle |
| Reset (power-on) state | a, b: register all ones (Thar0 window convention). c: all ones, +1 step offset. All three advance together | Thar0 data | [hw-data] `phase2.c` (below): all-ones + 256,586,636 `lfsr_cycle` steps reproduces A and B with 0 mismatches (±29 steps gives ~500). c captures: `c_phase ≡ a_phase + 1 (mod 2^27−1)` in 4/4. Which event loads all-ones (power-on, reset button, RDP init) is [inference]: elapsed 2.58 s and 4.11 s at 62.5 MHz fits "since console reset" |
| XNOR vs XOR | XOR feedback (complexity exactly n; XNOR output would not satisfy a linear recurrence) | BM result | [hw-data] |
| Alpha dither noise (`G_AD_NOISE`, `alpha_dither_sel=2`) | Added to combiner alpha before alpha compare when `alpha_cvg_select=0` and `key_en=0`; result clamped at 0xFF. Also added to blender shade alpha | Angrylion `combiner.c:263-285, 314-320`, `dither.c:87-90,107-109`; MiSTer `RDP_CombineAlpha.vhd:165-180`, `RDP_DitherFetch.vhd:90-94`; SDK `gDPSetAlphaDither` | [source] Angrylion: value `(noise>>6)&7` = same a,b,c bits as combiner NOISE, range 0–7. MiSTer: `random2 & '1'` ∈ {1,3,5,7}. paraLLEl: `seeded_noise&7`. Hardware source and range: no data |
| RGB noise dither (`G_CD_NOISE`) | 3 noise bits per channel, different per channel (9 bits/pixel) | n64brew RDP Commands; SDK 15.5.1 ("pseudo-random noise with a very long period") | [doc] Source bits on hardware: no data. Angrylion uses a separate `irand`, MiSTer `lfsr(8:0)` |
| Alpha compare random threshold (`G_AC_DITHER`, `dither_alpha_en=1`) | Write iff alpha ≥ 8-bit random threshold (1/2-cycle). 8-bit copy mode: threshold with per-pixel bit rotations | SDK 15.5.4, 15.7.8; n64brew Pipeline (copy); Angrylion `blender.c:72-90`, `rasterizer.c:1985-1997` | [doc]/[source]. Hardware bit source: no data. MM never uses it |
| Alpha compare rule | Write iff compared alpha ≥ threshold (blend alpha or random). In 2-cycle mode Angrylion compares the cycle-0 combiner alpha | Angrylion `blender.c:72-90`, `rasterizer.c:1135-1137`; MiSTer `RDP_BlendColor.vhd:210-240` | [source] |
| Combiner NOISE reaching alpha | Not possible. The alpha combiner has no NOISE input, and RGB enters alpha only through chroma key (`key_en`) | n64brew CC inputs; Angrylion `combiner.c:270-274` | [source] |
| Emulator noise | Angrylion: LCG `irand`, seed 3. paraLLEl: hash of (x,y,primitive), "not meaningful to exactly reproduce". MiSTer: 23-bit XNOR LFSR, reset 0. None match hardware | Angrylion `n64video.c:105-109,171,231`; paraLLEl `shaders/noise.h`, README; MiSTer `RDP_pipeline.vhd:281,473` | [source] |

### Conflicts

- **Line switch "eats 1 cycle"** (Thar0 README, motivating the 1016×1 capture) **vs. 1787-step spacing of the c captures.** No multi-line data backing the README remark is in the repo. The c data shows ≥771 non-pixel steps per interval. Judged in favor of the data. The README's remark may describe a different setup; if the c sets were separate back-to-back rectangles, the data says nothing about line switches, but it still shows steps without pixels.
- **#12 summary said "step per RDP clock (Thar0)".** Thar0 never measured that; the README says "per clock cycle" loosely. This doc's data-based inference agrees with #12's wording, but with a different basis.
- **Alpha-dither range:** Angrylion 0–7 vs. MiSTer odd values 1–7. Neither has hardware evidence. This decides whether alpha = threshold−8+1 … threshold−1 are all noise-gated, and with what probabilities.

### Reproduction (Thar0 repo @ e7f6c7f)

```c
// phase2.c — #include "rdp_noise_lfsr.c" with main renamed; run: ./phase2 256586636
uint st=(1u<<29)-1;                                    // all ones
for (D steps) lfsr_cycle(&st, (1u<<1)|(1u<<28), 29);   // a(x)
// compare st's 29 bits (MSB first) + next 987 outputs to A_dataset: 0 mismatches
// same for b: mask (1u<<2)|(1u<<27), deg 28, B_dataset: 0 mismatches
```

Phase search: generate each m-sequence from the all-ones window and find the 1016-sample capture (unknown bits wildcarded). Run time ≈ 5 s.

## MM usage table

Condition for noise to affect a write: `alpha_compare_en && (dither_alpha_en || (alpha_dither_sel==NOISE && !alpha_cvg_select && !key_en))`.

| file:line | Mode | Effect on writes |
|---|---|---|
| `src/code/z_kankyo.c:2925-2928` (`Environment_DrawSandstorm`) + `src/code/z_rcp.c:733-740` (SETUPDL_64) + `extracted/n64-us/assets/objects/gameplay_field_keep/gameplay_field_keep.c:559-572` (`gFieldSandstormDL`) | 2-cycle, `G_AC_THRESHOLD`, `G_AD_NOISE`+`G_CD_NOISE`, RM `G_RM_PASS`/`G_RM_CLD_SURF2` (no ALPHA_CVG_SEL, `G_CK_NONE`). Full-screen texrect `0,0`–`320,240` | **YES.** Per-pixel write iff cycle alpha + noise ≥ blend alpha. Active when `sandstormState≠OFF`: Object_Kankyo params 2 (`Z2_10YUKIYAMANOMURA2` room 0, winter Mountain Village blizzard, `z_object_kankyo.c:347`), sandstorm transitions (`z_play.c:833-867`), `CS_MISC_SANDSTORM_FILL` (`z_demo.c:270-273`) |
| `src/overlays/actors/ovl_Oceff_Storm/z_oceff_storm.c:179-189` (`OceffStorm_Draw2`) + `extracted/.../ovl_Oceff_Storm/ovl_Oceff_Storm.c:14` (`sSongOfStormsMaterialDL`) | Same as above (SETUPDL_64 + `G_AD_NOISE`, `G_RM_PASS`/`G_RM_CLD_SURF2`). Full-screen texrect | **YES.** Song of Storms effect |
| Threshold source for both: `src/code/z_rcp.c:849` (`sFillSetupDL`, blend A=8, loaded per frame at `z_rcp.c:1467`). Other setters: `z_actor.c:2997` (A=0), `:3014` (8), `PreRender.c:235` (8), `z_fbdemo_circle.c:21` (1) | — | With A=8: alpha 0 never written, 1–7 noise-gated, ≥8 always written. The value at draw time is [inference]. The XLU list order is runtime state |
| `src/code/z_rcp.c:17` (SETUPDL_0), `:702` (SETUPDL_61) | `G_AD_NOISE|G_CD_NOISE`, `G_AC_NONE` | No (colors/fog alpha only) |
| `src/code/z_rcp.c:337` (SETUPDL_29) | Combiner NOISE (cycle-1 RGB), `G_AC_NONE` | No |
| `src/code/PreRender.c:98-100`, `src/overlays/fbdemos/ovl_fbdemo_wipe5/z_fbdemo_wipe5.c:109-111` | `G_AD_NOISE|G_CD_NOISE`, `G_AC_NONE`, CLD_SURF | No |
| `extracted/.../ovl_En_Gakufu/ovl_En_Gakufu.c:16` | `G_AD_NOISE|G_CD_NOISE`, `G_AC_NONE` | No |
| `src/overlays/actors/ovl_En_Tanron2/z_en_tanron2.c:657-662`, `src/overlays/effects/ovl_Effect_Ss_G_Ripple/z_eff_ss_g_ripple.c:96-101` | SETUPDL_60 (`G_AC_NONE`, `z_rcp.c:685-692`) + `G_AD_NOISE` | No |
| `src/overlays/actors/ovl_Oceff_Storm/z_oceff_storm.c:202-207`, `src/overlays/actors/ovl_Eff_Stk/z_eff_stk.c:88-97`, `src/overlays/actors/ovl_En_Fall/z_en_fall.c:849-873, 918-921` | SETUPDL_25 (`G_AC_NONE`, `z_rcp.c:290-296`) + `G_AD_NOISE`. Material DLs only change render mode, which doesn't touch the AC bits (`G_MDSFT_RENDERMODE=3`) | No |
| `src/code/z_lights.c:435`, `ovl_En_Invadepoh/z_en_invadepoh.c:5277`, `ovl_En_Zoraegg/z_en_zoraegg.c:706`, `ovl_En_Ot/z_en_ot.c:1087`, `ovl_En_Invadepoh_Demo/z_en_invadepoh_demo.c:678`, `ovl_En_Osk/z_en_osk.c:631` | `G_AD_PATTERN|G_CD_NOISE` | No (RGB only) |
| `extracted/.../object_open_obj/object_open_obj.c:210`, `object_gi_ghost/object_gi_ghost.c:138`, `object_uch/object_uch.c:15` | Combiner NOISE in RGB | No (no `G_CK_KEY` anywhere in MM) |
| `G_AC_DITHER` | Not used. Source grep: 0 hits outside `gbi.h`. ROM scan of `E2001E01` (SetAlphaCompare): 32×NONE, 41×THRESHOLD, 0×DITHER, matching the 73 source sites. `E3001A01` (SetAlphaDither): only value 0 | — |

Caveats:
- Every `gSetupDLs` entry and `sFillSetupDL` does a full `gsDPSetOtherMode` (74 in `z_rcp.c`).
- An XLU draw that follows the two YES sites without reloading a setup DL inherits `G_AD_NOISE` and `G_AC_THRESHOLD`. Static grep can't rule that out. It needs the per-frame RDP stream (#21). [inference]
- Full-word `gsDPSetOtherMode` was checked from source only. A raw `EF` ROM scan is swamped by false positives in texture/audio data.

## Implications for the timing model

- Colors (`G_CD_NOISE`, combiner NOISE, fog-alpha dither) never change bus traffic. Noise matters only through the two write-enable sites.
- To be exact:
  - (1) Model the three LFSRs from an all-ones reset, stepping per RDP clock, with c offset +1.
  - (2) Know which clock each pixel samples. That's a fixed pipeline offset (unknown); in 2-cycle mode, which of the two clocks is also unknown.
  - (3) Count every RDP clock since reset exactly, stalls included.
  - (4) Know the `G_AD_NOISE` bit mapping and range.
- Items 2 and 4 have no hardware data. Without them, the noise-gated pixel set in those two effects can't be exact. Every other MM draw is noise-independent for writes.

## Open questions (sharp)

1. Does the LFSR step while the RDP is idle (no commands), and during memory stalls inside a span? Test: two 1016×1 noise rects separated by a known idle delay and by a forced stall (image read + Z). Compare the phase delta with `DPC_CLOCK`/`DPC_BUFBUSY` deltas.
2. Which event loads all-ones: power-on, reset button (NMI), or something software-triggerable? Test: dump right after a cold boot vs. after a reset-button press, at a fixed delay.
3. Which bits feed `G_AD_NOISE`, `G_CD_NOISE` and `G_AC_DITHER`? Test: Thar0-style dumps with alpha compare + `G_AD_NOISE` on alpha ramps, and with `G_CD_NOISE` on a 32 bpp flat fill.
4. 2-cycle mode: two steps per pixel? Which step's value does each cycle see?

## Sources

- Thar0/RDP-Noise @ e7f6c7f (README, `rdp_noise_lfsr.c`, `fb2data.py`, `rdp_noise.c`): https://github.com/Thar0/RDP-Noise
- n64brew Reality Display Processor/Commands (Set Other Modes, CC inputs), Pipeline (copy-mode alpha compare): https://n64brew.dev/wiki/Reality_Display_Processor/Commands
- N64 SDK manual: `gDPSetAlphaCompare`, `gDPSetAlphaDither`, `gDPSetColorDither` man pages; Programming Manual 12.7 (BL alpha compare), 15.5.1 (dither), 15.5.4 (alpha compare), 15.7.8 (PCL_SURF): http://ultra64.ca/files/documentation/online-manuals/man-v5-1/
- angrylion-rdp-plus @ 9c8b9ed (`n64video.c`, `rdp/dither.c`, `rdp/combiner.c`, `rdp/blender.c`, `rdp/rasterizer.c`, `rdp.c:555-566`)
- parallel-rdp @ 1cecd04 (`shaders/noise.h`, `shading.h`, README "A note on bitexactness")
- N64_MiSTer @ 5725381 (`rtl/RDP_pipeline.vhd`, `RDP_DitherFetch.vhd`, `RDP_CombineAlpha.vhd`, `RDP_CombineColor.vhd`, `RDP_BlendColor.vhd`)
- Patent US6166748 (blender "compare against a dithered value"; VI "random" block 914, separate from the RDP)
- wScottSh/ares research: #12 rdp-pixel-timing-coupling; rdp-command-timing.md (cen64-jgemu per-span measurement)
- MM decomp mm-decomp-60fps @ 56fa21dd0; US retail `baserom-decompressed.z64` scan
