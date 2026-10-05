# RDP write granularity for rejected pixels

Ticket: wScottSh/ares#17 (map #1). Prerequisites: #12 (`research/rdp-pixel-timing-coupling`), #3 (`research/rdp-memory-traffic`). Target: NTSC NUS-001 with Expansion Pak.

Question: when some pixels of a span are rejected (Z fail, coverage 0, alpha compare), how does the RDP write color and Z to RDRAM? Options are one masked burst for the whole span, one write per 8-byte word, or one write per contiguous run of written pixels. Is a fully rejected span written at all? In copy mode with alpha compare, are rejected texels written as a masked word or skipped? Does RDRAM support byte-masked writes, and how does the RCP use them?

Tags: **[cited]** = stated in the referenced document. **[source]** = read in the referenced code or data at the given commit. **[measured]** = my own analysis of hardware-captured data, reproducible with the script in the appendix. **[inference]** = my reasoning, not stated anywhere.

## TL;DR

- **Content level (settled by hardware data): rejected pixels never reach RDRAM, even when they share an 8-byte word with a written pixel.**
  - Source: snapper64 "RDP Test-Mode - Span Tri" console dumps (216 tests, 1-cycle, no `IM_RD`).
  - The span buffer holds the final pixel image of *every* rasterized pixel, rejected ones included.
  - 113 rejected-and-staged pixels sit in the same octbyte as a written neighbor. In the same dump, RDRAM still holds the cleared value for each of them **[measured]**.
  - Without `IM_RD` the span buffer holds no old memory data. So the write-back cannot be a plain full-span block: it **must** be byte-masked below the octbyte, or split.
- **Protocol level: the RDRAM protocol has two kinds of byte masking. The RCP is documented to use only one.**
  - The protocol (NEC µPD488170L, 18 Mbit base RDRAM) offers:
    - **contiguous** masking: `Wseq`, where `Adr[2:0]` / `Count[2:0]` trim only the first and last octbyte of a burst. It costs no extra bus time.
    - **arbitrary** masking: `Wbns`, which sends one bytemask octbyte per 8 data octbytes plus serial addresses. `Bpb`/`Dpb`/`Mpb` add bit masking **[cited]**.
  - The RCP→RI request is documented only as *(address, byte count)*. RI maps it to `Count = NumBytes + Addr[2:0]`, i.e. contiguous masking only. n64brew describes no use of `Wbns` or of the bit-mask modes anywhere **[cited]**.
  - Hardware fill-mode captures show RDP writes as bursts with first/last-word byte trims. Rows split into several bursts, and some rows are blanked outright (cen64/snapper64) **[cited]**.
- **Judgement:**
  - The best-supported model is **one RDRAM write transaction per contiguous run of written pixels**, using `Wseq` with trimmed end words. A fully rejected span issues **no write**.
  - Runs may be further cut at fixed 16-byte or 64-byte segment boundaries **[inference]**. Grounds: the span counters count 16-byte segments, and the fill burst machine works on 64-byte blocks.
  - So per-pixel results **do reach timing**, through the *number of runs* (one request packet plus write latency per run). The number of written bytes matters too.
  - This is **inference** from the protocol, the RI interface and the fill captures. No source shows rejected-pixel write *timing* directly.
- **Fully rejected span:** never changes RDRAM (content fact). The SDK says Z-failed pixels are "read only (no write)" and that this "improves fill rate" **[cited]**, which implies no transaction. Judged: no write.
- **Copy mode + alpha compare:** rejected texels are never written (content fact, and libdragon relies on it for sprite transparency). Copy has no memory read, so masking is mandatory.
  - A 16-bpp copy word holds 4 texels with independent pass/fail, so masks are non-contiguous.
  - Under the RI model above, a word like pass/fail/pass/fail costs **two** transactions, unless copy writes are merged into runs across words first.
  - MiSTer issues one byte-masked write per word, even with an all-zero mask. That is an FPGA choice.
  - Hardware transaction behavior is not published.
- **Correction to #3:** MiSTer does *not* write one FIFO entry per pixel. It merges pixels into one byte-masked 64-bit DDR3 write per octbyte that has at least one written pixel (`RDP.vhd:1395-1404`, `DDR3Mux.vhd:341-350`) **[source]**.

## Behavior table

| Case | Write behavior (best available) | References | How verified on hardware |
|---|---|---|---|
| RDRAM byte-mask capability | Base RDRAM supports `Wseq` (contiguous masking via `Adr[2:0]`→ByteMaskLS on the first octbyte and `Count[2:0]`→ByteMaskMS on the last, intermediate octbytes all written, no extra data) and `Wbns` (arbitrary bytemasks sent in-band, 1 mask octbyte per 8 data octbytes, plus serial addresses on BusEnable). It also has bit-mask modes `Dpb`/`Mpb`/`Bpb` using MDReg or in-band masks. Max 32 octbytes. A transaction may not cross a 2 KB row. | NEC µPD488170L datasheet §5.2.2–5.2.5, Tables 5-2…5-7 [cited] | Datasheet only. The N64-specific command use is next row. |
| RCP / RI use of masks | RCP clients hand RI an address plus byte count. RI emits `Count[6:3]=NumBytes[6:3]`, `Count[2:0]=NumBytes[2:0]+Addr[2:0]` (carry from bit 2 dropped). Byte masking is therefore the RDRAM's first/last-octbyte contiguous trim. No documented path for `Wbns`/`Bpb`. RCP transactions are ≤128 B (16 octbytes). DBus is 64-bit data, and EBus carries the 9th bits. | n64brew RDRAM Interface "Count"; MIPS Interface "MI_MODE" (byte masking from `Addr[2:0]` + count, suppressed in repeat mode) [cited] | Hardware-tested by n64brew for PI misaligned DMA (dropped-carry bug) and MI repeat mode. Not shown for RDP requests: extending it to the RDP is **[inference]**. |
| Partially rejected span, 1/2-cycle, color (cvg/cvbit, alpha compare, Z fail) | Rejected pixels are not written, even inside a written octbyte. Granularity below the octbyte, so masked or split. Judged transaction form: one `Wseq` per contiguous written run, with end trims. | snapper64 Test-Mode Span Tri + cen64 DPS model ("coverage-0 included", 216/216) [source]; analysis below [measured]; SDK 12.7 "read only (no write)" [cited]; n64brew Pipeline "Pixels that are not rejected … are written to the span buffers" [cited] | **Content: yes.** Console dumps: 113 rejected staged pixels in 101 tests share an octbyte with a written neighbor and remain unwritten. **Timing: no published measurement.** |
| Partially rejected span with `IM_RD` set | The span buffer then holds old memory data, so a full-block write-back would be *content*-indistinguishable. The patent's "writes the entire span … as a block all at once" fits this case. The SDK's "no write … improves fill rate" contradicts it. Judged: same masked/run path as without `IM_RD` (one write datapath) **[inference]**. | US 6,166,748 [cited]; SDK 12.2, 12.7, 24.4 [cited] | Not measured. Discriminating test proposed below (span-coherency clobber test). |
| Z write | Only for pixels that pass and only if `Z_UPD`. Same masking requirement: the Z span is prefetched only when `Z_CMP`, and `Z_UPD` without `Z_CMP` has no old data. | #3 rows 2/4; Angrylion `rasterizer.c:543-546` [source]; MiSTer `RDP.vhd:1451-1471` (per-octbyte Z merge) [source] | Content via emulators matching hardware. Timing not measured. |
| Fully rejected span | No RDRAM change. Judged: no write transaction (SDK fill-rate statement). Reads still happen (span prefetch gated only by `IM_RD`/`Z_CMP`). | SDK 12.7, 24.4 [cited]; MiSTer flushes only words with ≥1 written pixel (`RDP.vhd:1395-1404`) [source] | Content yes. Timing not measured. |
| Rejected pixel 9th bits, 8-bpp color image | Angrylion models rejected pixels updating a staged 8-entry hidden-bit buffer (`rdram_hidden_old`), which later leaks into the 9th bit of a neighboring written byte. So the hidden-bit lane is not cleanly byte-masked at 8 bpp. | Angrylion-rdp-plus `rasterizer.c:190-267`, `rdram.c:139-245` @9c8b9ed [source] | Angrylion's behavior is hardware-derived (its stated purpose); I did not locate the original test. Content-only. |
| Fill mode | No rejection. Writes are 64-bit words with byte enables in bursts. Triangle rows split into first burst plus tail, end words trimmed, some rows blanked. Bursts work on a 64-byte block grid. | cen64 (jgemu) `rdp_core.c:1790-1866` @2f8d7bc; parallel-n64 commit b2bdf1c [cited/source] | snapper64 "RDP Fill Mode Tri (Sweep)" console dumps, 96960/96960 rows matched by the cen64 model [cited] |
| Copy mode, alpha compare | Rejected texels are never written (16-bpp: texel alpha LSB; 8-bpp: threshold/noise; 4-bpp: always fails). Transaction form not published. MiSTer: one 64-bit write per word with byte enables, including all-zero masks. Judged: masked, with non-contiguous masks needing split transactions under the RI model **[inference]**. | n64brew Pipeline "Copy Pipeline" [cited]; libdragon `rdpq_mode.h:315-326` [cited]; MiSTer `RDP_pipeline.vhd:410-426`, `RDP.vhd:1389-1394` [source] | Content: yes (used by commercial games and libdragon for sprite transparency; MM uses copy mode in `PreRender.c:808`, `z_visfbuf.c`). Timing not measured. |
| Run / segment boundaries | Unknown. Candidate cuts: 16-byte segments (cspan/zspan counters count 16-byte segments a primitive covers) and the 128-byte RCP transaction limit **[inference]**. | n64brew RDP Interface `DPS_TEST_MODE` [cited]; n64brew RDRAM Interface [cited] | Not measured. |

## Hardware evidence: rejected pixels inside written octbytes

snapper64 (HailToDodongo/snapper64 @e1cd8a6) group "RDP Test-Mode - Span Tri" (`src/tests/RDPTestModeSpan.cpp`) works as follows:

- It fills the span buffer with `0x55555555` through `DPS_BUFTEST`, then draws one shaded triangle. The mode is 1-cycle, no AA, `IM_RD` off, no Z, into a cleared 76×64 RGBA32 surface.
- It then dumps both the surface and the span buffer.
- Its reference files are console dumps (README "Dumping References": "requires … an actual N64 console"). Console region/model is not stated.

cen64's DPS model, fitted to these captures, states that the span buffer holds one word per rasterized pixel, "coverage-0 included" (`rdp_core.h:252-279`).

My analysis of the 216 reference pairs (script in the appendix):

- 3440 staged pixel words. 334 of their RGB values appear nowhere in the RDRAM surface. Those are rasterized pixels that were rejected (non-AA cvbit rejection).
- I localized 225 of them via a staged neighbor that is in the surface. **113 of them, in 101 tests, share an 8-byte octbyte with a written pixel.** 32 bpp, 64-byte-aligned buffer (`surface_alloc` → `malloc_uncached_aligned(64,…)`), stride 304.
- Example, test "Tri 0 | 0": the span buffer holds `0301f960` (x=8, y=53) then `0402f8a0` (x=9). RDRAM has `0402f8a0` at (9,53) and `00000000` at (8,53).

Since `IM_RD` is off, the span buffer has no old value to write back for x=8. The hardware therefore writes with a byte mask finer than 8 bytes, or starts the write at x=9. Either is consistent with contiguous `Wseq` trimming. This dataset cannot tell them apart, because cvbit rejection only occurs at span ends.

## Reasoning on transaction form

- **Masked full-span burst (one `Wbns` per span):** the protocol allows it, but no N64 source mentions `Wbns`. The documented RI request interface has no per-byte enables. Rejected **[inference, weak]**.
- **Full-span block with old data:** impossible without `IM_RD` (shown above) and for Z with `Z_UPD` but no `Z_CMP`. Possible only in RMW modes, where the SDK contradicts it. Rejected as the general mechanism.
- **Per contiguous run with end trims (`Wseq`):** fits:
  - the RI count/address mapping
  - the fill-mode captures (bursts, end-word trims, rows split into several bursts or blanked)
  - the patent's "block" (each run is a block)
  - the SDK's "no write"

  **Judged most likely.**
- **Per octbyte:** fits the content data too. It would make bursts pointless and contradicts the patent/SDK emphasis on span-block writes. Less likely.

What reaches timing under the judged model: for each (primitive, scanline), the number of maximal written runs and their byte extents, per buffer (color, Z). Each run costs about one RDRAM write request plus data at 2 ns/byte. A run never crosses a 2 KB RDRAM row or 128 bytes **[inference]**.

## Conflicts

- **Patent vs SDK.** US 6,166,748: "writes the entire span worth of pixels into main memory … as a block all at once". SDK 12.7: obscured pixels are "read only (no write)". Judged for the SDK: it is specific, performance-oriented, and the snapper64 data proves masking exists. The patent sentence is about buffering, and a "block" per run satisfies both.
- **MiSTer vs judged model.** MiSTer issues one DDR3 beat per written octbyte, and in copy mode even all-zero-mask words. That is shaped by DDR3, not by RDRAM. It is not evidence for hardware.
- **#3 description of MiSTer** ("each pixel as a separate byte-masked 64-bit FIFO entry"): wrong. MiSTer merges pixels per octbyte (`pixel64filled`/`pixel64Addr`, `RDP.vhd:1395-1404`).

## Hardware tests that would settle it (none run)

1. **Run-count sweep (timing).** Pre-fill a Z buffer with a comb: near/far alternating every N pixels, N = 1, 2, 4, 8, 16, 32. Draw the same full-screen rect in 1-cycle `Z_CMP|Z_UPD`, no `IM_RD`. Read `DPC_CLOCK`/`DPC_BUFBUSY` deltas. Predictions:
   - cost rises with runs per row → per-run `Wseq`
   - flat → single masked burst
   - steps at N<4 vs ≥4 (16 bpp) → per-octbyte

   Also include all-pass and all-fail baselines.
2. **Copy-mode comb.** Same idea with texel alpha bits alternating per texel versus per word, in 16-bpp copy.
3. **Coherency clobber test (content, no timer needed).** Draw two consecutive primitives with overlapping same-row spans, `G_PM_NPRIMITIVE`, `IM_RD` set. Make the second primitive's pixels in the overlap fail alpha compare. If the first primitive's pixels are erased there, the write-back is a full block with stale data. If they survive, it is masked/run-based.

## Sources

- NEC µPD488170L 18M-bit Rambus DRAM preliminary data sheet, §5.2 request packet fields, Tables 5-2 to 5-7 (local copy `scratchpad/rambus/nec170.txt`).
- n64brew wiki: RDRAM Interface ("Count"), MIPS Interface (MI_MODE byte masking, EBus), RDRAM (commands), Reality Display Processor/Interface (`DPS_TEST_MODE`, `DPS_BUFTEST_*`), /Pipeline (Color Image Write, Fill, Copy alpha compare). https://n64brew.dev/wiki/RDRAM_Interface, https://n64brew.dev/wiki/MIPS_Interface, https://n64brew.dev/wiki/Reality_Display_Processor/Interface, https://n64brew.dev/wiki/Reality_Display_Processor/Pipeline
- US 6,166,748 (Van Hook et al.), "Memory interface 512" paragraph. https://patents.google.com/patent/US6166748A/en
- N64 Programming Manual ch. 12-02 (Span Buffer Coherency), 12-07 (Blender: "read only (no write)"), 24-04 (conditional write, Reduced Aliasing). https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro12/12-07.html, https://ultra64.ca/files/documentation/online-manuals/man/pro-man/pro24/24-04.html
- snapper64 @e1cd8a61 (`src/tests/RDPTestModeSpan.cpp`, `src/tests/RDPFillTriSweep.cpp`, README, LFS reference dumps `assets/2A1ADF69_*`). https://github.com/HailToDodongo/snapper64
- cen64 (jgemu) @2f8d7bc, `src/rdp/rdp_core.h:252-279` (DPS span model), `src/rdp/rdp_core.c:1790-1866` (fill burst model), `:5941`, `:6970` (copy). https://gitlab.com/jgemu/cen64
- libretro/parallel-n64 commit b2bdf1c "angrylion: write FILL-mode triangles the way the hardware does". https://github.com/libretro/parallel-n64/commit/b2bdf1c65990ffb4b149c0c36b1d5b599cd6514e
- angrylion-rdp-plus @9c8b9ed (`rasterizer.c:190-267, 530-563`, `rdram.c:139-245`).
- N64_MiSTer @5725381 (`rtl/RDP.vhd:1373-1471, 1530-1560`, `rtl/RDP_pipeline.vhd:410-430, 780-820`, `rtl/DDR3Mux.vhd:341-365`).
- libdragon @e356bf3 `include/rdpq_mode.h:307-330`.
- Prerequisites: `research/rdp-pixel-timing-coupling` (#12), `research/rdp-memory-traffic` (#3) in this repo.

## Appendix: analysis script

Reference files fetched from `https://media.githubusercontent.com/media/HailToDodongo/snapper64/main/assets/2A1ADF69_*.test.7z` (group hash = crc32("RDP Test-Mode - Span Tri"), test hash = crc32("Tri {type} | {i}"), `_01` = surface 76×64, `_02` = span dump 4×32, big-endian RGBA32), extracted with py7zr.

```python
import struct, zlib
def ld(n):
    d = open('snx/assets/' + n, 'rb').read(); return struct.unpack('>%dI' % (len(d)//4), d)
W = 76; cases = shared = 0
for typ in range(4):
  for i in range(54):
    h = '%08X' % zlib.crc32(f'Tri {typ} | {i}'.encode())
    s = ld(f'2A1ADF69_{h}_02.test'); t = ld(f'2A1ADF69_{h}_01.test')
    pos = {}
    for k, v in enumerate(t):
        if v: pos.setdefault(v >> 8, []).append((k % W, k // W))
    seq = [s[y*4 + x] for y in range(32) for x in (0, 1)]
    for k, w in enumerate(seq):
        if w in (0, 0x55555555) or (w >> 8) in pos: continue      # written or filler
        loc = None
        if k+1 < len(seq) and len(pos.get(seq[k+1] >> 8, [])) == 1:
            x, y = pos[seq[k+1] >> 8][0]; loc = (x-1, y)
        elif k > 0 and len(pos.get(seq[k-1] >> 8, [])) == 1:
            x, y = pos[seq[k-1] >> 8][0]; loc = (x+1, y)
        if not loc or not 0 <= loc[0] < W or t[loc[1]*W + loc[0]]: continue
        cases += 1
        if t[loc[1]*W + (loc[0] ^ 1)]: shared += 1                 # 32bpp octbyte partner written
print(cases, shared)   # -> 225 113
```
