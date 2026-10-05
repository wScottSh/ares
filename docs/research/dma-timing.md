# DMA engine timing (SP, PI, SI, AI, VI) — ticket #7

Target: NTSC retail NUS-001 + Expansion Pak, running Majora's Mask (US).
ares baseline: `wScottSh/ares` master `a776c509b`. It already contains upstream PR #2583, the PI bus rewrite (`3c63fbcfb`).

Clock units used below:
- **RCP cycle** = 62.5 MHz = 16 ns.
- **CPU cycle** = 93.75 MHz.
- ares `Thread` clock = 187.5 MHz (`ares/n64/system/system.hpp:37`), so 1 RCP cycle = 3 ares clocks and 1 CPU cycle = 2 ares clocks.
- Peak RDRAM data rate is **8 B per RCP cycle (500 MB/s)**. This comes from n64brew RDRAM, which says a 64-bit write data packet occupies TCycles 4–7, i.e. RCP cycles 1–1.75 (4 TCycles per RCP cycle, 2 B per TCycle).

## TL;DR

- **SP DMA**
  - Hardware moves about **3.7 B per CPU cycle**, which is 5.55 B/RCP cycle or about **347 MB/s**. The fixed overhead is small. Source: the hcs64 hardware measurement (2002), repeated on n64brew.
  - ares charges **8 B/RCP cycle (500 MB/s, 100 % of the RDRAM peak)** with no setup time. That is **~44 % too fast**.
  - In ares, MM moves **386–793 KB of SP DMA per game frame** (3 VI). At the hardware rate that is 1.1–2.3 ms of DMA-engine time per frame. ares charges 0.77–1.59 ms.
- **PI DMA (cart → RDRAM)**
  - Fixed per transfer: one page-address phase of `14+LAT+1` RCP per 2^(PGS+2)-byte page.
  - Per byte: `(PWD+1+RLS+1)/2` RCP of bus time.
  - Per buffer: a **128-byte internal buffer** is written back to RDRAM at about 28 RCP per full block. Fill and writeback are serial within a block.
  - **MM's cart uses LAT=0x40, PWD=0x12, PGS=7, RLS=3** (ROM word 0 = `0x80371240`). That gives **≈11.87 RCP/B ≈ 5.27 MB/s**, matching n64-systembench (64 KiB = 777 807 RCP) to 0.02 %.
  - The RDRAM load from PI is tiny: 128 B per ~1 500 RCP, about 1–2 % of RDRAM time while a PI DMA runs.
- **ares PI today**
  - ares uses a one-shot formula: all data lands at the DMA start and the IRQ comes later.
  - It is within 1.5 % of systembench for 128 B–64 KiB.
  - It has two formula errors that n64_pi_dma_test hardware data exposes:
    - It **under-counts writeback buffers for full first/last pages**: −168 RCP at 1 KiB.
    - It **charges 1 RCP/byte writeback for any single-page transfer that isn't exactly 128 B**: +4–5 % for 130–510 B.
- **The revert of `bea395b24` (PR #2139) by `807ef0300` (PR #2147)**
  - The only public reason is Luke Usher's PR body: *"This exposed some shortcomings in the pi_dma testrom and caused some compatibility issues; an updated testrom is required"*.
  - No issue, comment or game name is linked anywhere public. I searched the PR timelines, review comments, cross-references and issues created 2025-08-07…31.
  - The behavioral change that plausibly caused the regressions is inferred from the diff: data started landing in RDRAM block by block over the transfer, instead of all at DMA start.
- **SI DMA**
  - 64-byte write to PIF: **4 065 RCP (65 µs)**.
  - 64-byte read: dominated by the PIF joybus run, **~38 k RCP (0.61 ms) for 1 controller command up to ~98 k RCP (1.57 ms) for 4**.
  - RDRAM traffic is only 64 B each way, which is negligible. ares uses these systembench numbers (`si/io.cpp:87,104`, `pif/hle.cpp:195-240`).
- **AI DMA**
  - Reads RDRAM as the DAC consumes samples (no sample RAM).
  - MM requests 32 000 Hz, which libultra realizes as 48 681 812/1521 = **32 006 Hz** × 4 B = **128 KB/s** (0.026 % of peak). MiSTer fetches 8 B per request, so about 16 k requests/s.
- **VI scanout**
  - MM gameplay uses **`osViModeNtscLan1`**: 320×240, 16 bpp, AA "fetch extra lines as needed", progressive, H_TOTAL 3093, V_SYNC 525.
  - Base fetch is **640 B per active line × 237 lines × 59.83 Hz ≈ 9.1 MB/s (1.8 % of peak)**. The upper bound with an extra line fetched for every line is about 18 MB/s.
  - No hardware measurement of VI fetch burst size or extra-line policy exists. ares, cen64, gopher64, Dillonb, mupen64plus and simple64 all charge VI zero bus time. MiSTer over-fetches 1 408 B/line as a functional hack.

## Behavior table

| Engine | Latency / rate / burst (hardware best knowledge) | RDRAM bandwidth (MM) | References | ares today (file:line) | How verified |
|---|---|---|---|---|---|
| **SP DMA** | ~3.7 B/CPU cycle = 5.55 B/RCP ≈ 347 MB/s. Small fixed overhead (hcs64 measured a 41-CPU-cycle intercept that it attributes mostly to the polling loop). 8-byte granularity, double-buffered registers, rows of LEN+1 with SKIP. Burst ≤128 B (RI max). | 386–793 KB per game frame in four MM scenes (ares byte counters). That is 7.7–15.8 MB/s average, or 1.5–3.2 % of peak. | hcs64.com/dma.html; n64brew RSP Interface; n64brew RI "Count"; gopher64 `rdram.rs:175` (`31 + n/3` CPU cycles, i.e. 3 B/CPU cycle); MiSTer `RSP.vhd:601-611` (128-B bursts, no timing) | `rsp/dma.cpp:20,67` = `(len+8)/8*3` ares clocks per row, i.e. 8 B/RCP. Data copied at end of each row (`:24-62`). No setup or contention. | Checked the hcs64 page text and the n64brew text; computed the ratio. MM byte counts are from `bench-results/20261004-165142-baseline-interp/*.run0.csv` (`rdram_sp_dma`). |
| **PI DMA cart→RDRAM** | Per page: `14+LAT+1` RCP. Per halfword: `PWD+1+RLS+1` RCP. Per 128-B block: fill, then about 28 RCP writeback (the block is clipped at the RDRAM 2 KiB row end). Odd/misaligned first-block quirks are documented on n64brew. | MM DOM1 (`0x40/0x12/7/3`): 11.87 RCP/B = 5.27 MB/s. RDRAM busy ≈ 28/1 520 ≈ 1.8 % while active. DmaMgr 8 KiB chunk ≈ 97 264 RCP = 1.56 ms. | n64brew Parallel Interface; n64-systembench `main.c:589-592`; n64_pi_dma_test golden logs (hardware); MiSTer `PI.vhd:598,682,741-747`; gopher64 `pi.rs:172-196` | `pi/io.cpp:110,119` schedules `dmaDuration()` (`pi/dma.cpp:72-112`). Data is written immediately (`pi/dma.cpp:16-64`). | Re-ran the ares formula and the reverted formula against systembench and the decoded n64_pi_dma_test min/max ticks (see Details). |
| **PI DMA (MM flash, DOM2)** | Same structure. MM sets LAT 5, PWD 0x0C, PGS 0xF, RLS 2, giving 16 RCP per halfword = 8 RCP/B ≈ 7.8 MB/s (formula applied; DOM2 timing is not hardware-tested). | Save I/O only. | decomp `include/PR/os_flash.h:11-14`, `src/code/osFlash.c:58-63` | same formula | Formula only. |
| **PI DMA RDRAM→cart** | n64brew: "expected" to behave like writes, "not … fully tested". | MM: flash page writes only. | n64brew PI | `pi/dma.cpp:1-14`, same duration formula | None on hardware. |
| **SI DMA** | WR64B 4 065 RCP. RD64B = PIF joybus time + transfer: 37 987 RCP (1 cmd) … 97 890 RCP (4 cmds). RDRAM: 64 B per direction (MiSTer 8×8 B). | 128 B per poll, negligible. | n64-systembench `main.c:597-613`; n64brew SI; MiSTer `SI.vhd:89,162`, `PIF.vhd:655,775` | `si/io.cpp:87` (`pif.estimateTiming()`: 13 600 + 22 000/18 000 per channel cmd + 1 420/short cmd, `pif/hle.cpp:195-240`), `si/io.cpp:104` (4 065×3) | systembench constants read from source; ares 1-cmd estimate = 38 440 (+1.2 %). |
| **AI DMA** | No sample RAM; the DMA streams to the DAC at DACRATE. IRQ at buffer start. 8 KiB carry bug. MiSTer fetches 8 B per request. | 32 006 Hz × 4 B = 128 KB/s. | n64brew AI; MiSTer `AI.vhd:104-106`; decomp `aisetfreq.c`, `session_config.c:103` | `ai/ai.cpp:35-48`: 4-B read per sample at the DAC rate, no bus time | Arithmetic from libultra source. |
| **VI scanout** | Fetches framebuffer lines during the active line. Burst size and extra-line policy are not measured on hardware. RI refresh is tied to HSYNC (during HBLANK). | Lan1: 640 B × 237 lines × 59.83 Hz ≈ 9.1 MB/s (1.8 %), ≤ ~18 MB/s with AA extra-line fetches. Notebook hi-res mode ≈ 15–16 MB/s (inference). | n64brew VI (`AA_MODE`, H_TOTAL refresh note), n64brew RI (refresh); decomp `sys_cfb.c:56`, `vimodentsclan1.c`; MiSTer `VI_linefetch.vhd:123-141` | `vi/vi.cpp:88-96` (frame snapshot at vstart); `vi/vi.cpp:200,218` (software path reads, no time charged) | Arithmetic from VI register values; no hardware bandwidth source exists. |

## Details

### SP DMA

**Hardware.**
- The only direct measurement is HCS's 2002 test (hcs64.com/dma.html). He polled DMA_BUSY with COP0 Count and doubled the count to get CPU cycles. Quote: *"the rate is about 0.27 cycles per byte, or 3.7 bytes per cycle … When length=0 … the base value for the transfer time, 41 cycles, is probably the loop overhead"* (R² = 0.9752).
- n64brew's RSP Interface page repeats this: *"about 3.7 bytes per VR4300 (PClock) cycle (plus some small fixed overhead)"*.
- n64brew also notes that DMA_FULL clears *"a few clock cycles before the previous DMA transfer is finished"*, so queued DMAs pipeline.
- gopher64 and simple64 use `31 + n/3` CPU cycles (+9) for SP DMA (`gopher64/src/device/rdram.rs:175-176`, `rsp_interface.rs:212-216`). They cite hcs64 and systembench, but the formula is a shared RDRAM-access cost also used for CPU uncached/cache fills. That makes it less specific than hcs64's direct SP-DMA fit (3.0 vs 3.7 B/CPU cycle).
- **Better grounded: hcs64's 3.7 B/CPU cycle.** The R² of 0.975 leaves room for row/bank effects. Inference: RDRAM row (2 KiB) crossings and refresh are the likely scatter sources. Nobody has published a row-aware SP DMA measurement.

**ares.**
- `dmaQueue((length+8)/8*3)` (`rsp/dma.cpp:20,67`) is 8 B per RCP cycle. That equals the raw RDRAM data-packet rate, with zero request/ack overhead, so it is 1.44× hardware speed.
- The data for a whole row is copied when the row's time expires (`rsp/dma.cpp:24-62`).

**MM volume.** These are ares byte counters in the fork's bench (emux `0x0340`). The volume is set by software, so it should equal hardware; I infer this, because ares is functionally exact for DMA lengths.

| Scene | SP DMA bytes per game frame (median) |
|---|---|
| South Clock Town | 793 420 |
| Great Bay Coast | 706 736 |
| Termina Field | 546 884 |
| Mountain Village (winter) | 386 464 |

- At 347 MB/s the 793 KB case is 2.29 ms of DMA-engine time per 50.1 ms frame. ares charges 1.59 ms.
- Whether that 0.70 ms delta reaches the frame time depends on how much F3DZEX/audio ucode overlaps DMA with compute. That is a question for the RSP ticket.

### PI DMA

**Hardware process** (n64brew Parallel Interface, "DMA Transfers"):
- The transfer is split into blocks of at most 128 bytes (the internal buffer), also clipped at the RDRAM 2 KiB row end.
- Each block first fills from the PI bus (16-bit accesses), then writes back to RDRAM: *"it can be first seen PI_CART_ADDR moving forward, and then PI_DRAM_ADDR catching up with a leap"*.
- The PI issues a new address once per PGS page.

**Domain registers** (n64brew; 1 RCP cycle = 16 ns):
- LAT = cycles − 1 between ALE and the first /RD.
- PWD = cycles − 1 of /RD low.
- RLS = cycles − 1 of /RD high between halfwords.
- PGS: page = 2^(PGS+2) bytes.
- *"All official ROMs set LAT = 64 … PWD = 18 … PGS = 7 … RLS = 3."*

**MM's cartridge.**
- `baseroms/n64-us/baserom.z64` bytes 0–3 are `80 37 12 40`.
- libultra `osCartRomInit` (`src/libultra/io/cartrominit.c:47-51`) decodes them as latency = 0x40, pulse = 0x12, pageSize = 7, relDuration = 3.
- MM's DmaMgr and audio both DMA through this handle: `src/boot/z_std_dma.c:70,87`, `src/audio/lib/load.c:96,1294`.
- DmaMgr splits ROM loads into 0x2000-byte chunks (`include/z64dma.h:28`).
- Flash (DOM2) uses `FLASH_LATENCY 5, PULSE 0x0C, PAGE_SIZE 0xF, REL_DURATION 2` (`include/PR/os_flash.h:11-14`).

**Rate for MM DOM1:**
- 23 RCP per halfword (bus).
- 79 RCP per 512-B page (address).
- About 28 RCP per 128-B block (writeback).
- Total = 11.5 + 0.154 + 0.219 = **11.87 RCP/B**.
- n64-systembench's hardware expectation for 64 KiB is 777 807 RCP = 11.87 RCP/B (`n64-systembench/src/main.c:592`).

**Hardware data check.** I decoded rasky/n64_pi_dma_test golden logs:
- Record = 512 B buffer, then big-endian u16 min/max COP0 ticks. 1 tick = 2 CPU cycles = 4/3 RCP.
- Measured at DOM1 0x40/0x12/7/3 for RAM offsets 0x780–0x7FE (that is, distance to row end 128…2 B), sizes 1–383.
- A linear fit over the aligned case (offset 0x780, even sizes 2–382) gives **23.69 RCP per halfword** plus ~112 RCP constant. The constant includes the measurement loop overhead (`dma_wait` polling).

Selected sizes, RCP cycles. ares formula evaluated assuming a page-aligned PI address; the test's ROM-side offset is not recorded in the logs.

| bytes | hardware min–max (0x780) | ares today | reverted `bea395b24` |
|---|---|---|---|
| 8 | 211–220 | 179 (−15 %) | 182 (−13 %) |
| 64 | 861–883 | 879 (+2 %) | 836 (−3 %) |
| 128 | 1605–1623 | 1579 (−2 %) | 1583 (−1 %) |
| 256 | 3117–3131 | 3279 (+5 %) | 3089 (−1 %) |
| 382 | 4673–4695 | 4854 (+4 %) | 4586 (−2 %) |

Against systembench (PI address 0x10000000):

| bytes | systembench | ares today | reverted |
|---|---|---|---|
| 8 | 193 | 179 (−7.3 %) | 182 (−5.5 %) |
| 128 | 1 591 | 1 579 (−0.8 %) | 1 583 (−0.5 %) |
| 1 KiB | 12 168 | 11 990 (−1.5 %) | 12 081 (−0.7 %) |
| 64 KiB | 777 807 | 777 944 (+0.02 %) | 768 166 (−1.2 %) |

Two specific errors in today's `PI::dmaDuration` (`pi/dma.cpp:72-112`):
1. **Full first/last pages count as one 128-B buffer, not pageSize/128 buffers** (`:97,99`). With PGS 7 that misses 3 buffers × 28 RCP per full edge page. Correcting it moves 1 KiB to 12 158 (−0.08 %) and 64 KiB to 778 112 (+0.04 %).
2. **Any single-page transfer that is not exactly 128 B charges `partialBytes = len` at 1 RCP per byte** (`:90-92,110`) instead of about 28 RCP per 128-B block. This is the +4–5 % on 130–510-byte transfers. MM's audio sample/sequence DMAs and small DmaMgr files fall in this range; I infer this from the transfer sizes and have not measured MM's PI size histogram.
3. The small-transfer floor is about 15 % short at 8 B. The extra cost on hardware (setup, first-block masked writes) is what `bea395b24` modeled with `+4` initial and `+21` masking.

MiSTer charges `LAT` per page, `PWD+RLS+2` per halfword and 28 per block (`PI.vhd:598,682,741-747`). It omits the `14+1` per page that systembench supports, and it delays only the busy/IRQ (data moves at DDR3 speed).

**Bandwidth.**
- A full 128-B block costs 64×23 + 28 ≈ 1 500 RCP, of which RDRAM is busy about 28.
- The PI therefore uses about 1.8 % of RDRAM time while streaming, and ≤ 5.3 MB/s.
- MM's per-frame PI volume was not captured in the bench CSVs; the fork has emux counter `0x0350` for it.

### Why upstream reverted `807ef0300` (PR #2139 → revert PR #2147)

- **`bea395b24`** (rasky, 2025-08-07, merged 2025-08-12, PR #2139):
  - Made PI DMA writes run block by block: `Queue::PI_DMA_Write` re-arms `pi.dmaWrite()` per block (`cpu/cpu.cpp`).
  - Each block's data lands in RDRAM only when its time elapses, so `PI_DRAM_ADDR`/`PI_CART_ADDR` advance during the transfer.
  - Per-block cost:
    - first block +4;
    - page select `14+LAT+1`;
    - `PWD+1+RLS+1` per halfword;
    - +21 for masked (misaligned) writes;
    - +6 row-open when starting a new 2 KiB row;
    - +6 burst setup;
    - writeback at 350 MiB/s.
  - It passed n64_pi_dma_test at 10 % tolerance. rasky's test repo enabled timing tests by default the same day (`fea460b06`, 2025-08-07).
- **Revert `807ef0300`** (Luke Usher, 2025-08-13, PR #2147), with the body *"This exposed some shortcomings in the pi_dma testrom and caused some compatibility issues; an updated testrom is required."* That is the entire public record:
  - The PR #2139 timeline has no comments besides one nitpick from invertego on `nall/priority-queue.hpp`.
  - There are no cross-references besides #2147.
  - No issue was filed 2025-08-07…31 that mentions PI.
  - n64_pi_dma_test has had no commit since 2025-08-07.
  - So the affected games and the testrom "shortcomings" are not documented publicly.
- **Inference from the diff (not stated by upstream):** the reverted code changed *when* data appears in RDRAM. The pre-/post-revert code copies the whole transfer at DMA start and delays only the IRQ, which is what ares had done since `91f3dfaf3` (2022, "run PI DMA immediately, and delay only the interrupt").
  - Games that read the destination before the PI interrupt (racing their own DMA, or polling `PI_STATUS` less strictly) see stale data under the incremental model. With the immediate model they happen to work.
  - The reverted model also made every block a separate queue event, interacting with `PI_STATUS` reset (`queue.remove`) and the busy check in `ioWrite`.
  - The testrom only checks timing at DMA completion and final RDRAM content, so it could not catch intra-transfer visibility problems. That is consistent with "shortcomings in the testrom".
- Since the revert, `3c63fbcfb` (PR #2583, 2026-07) rewrote the PI bus as 16-bit device accesses but kept the one-shot timing.
- For MM: libultra waits for the PI interrupt before using the data. Inference: that comes from the `osEPiStartDma` → `__osPiDevMgr` message-queue design, so incremental visibility should not affect MM functionally.

### SI DMA

- n64-systembench hardware expectations, all in RCP cycles (`main.c:597-613`):
  - SI DMA write to PIF RAM: 4 065.
  - Write with a PIF-ROM address: 2 144.
  - Joybus RD64B: empty 15 030–21 178; 1 command 37 987; 2: 57 972; 3: 77 924; 4: 97 890.
- The PIF runs joybus only when the RD64B arrives (n64brew SI), so the read DMA's duration is mostly PIF/controller time, not bus time.
- RDRAM traffic is 64 B per direction (MiSTer: eight 8-B accesses, `SI.vhd:89`).
- ares:
  - write = `4065*3` ares clocks (`si/io.cpp:104`), exact to systembench;
  - read = `pif.estimateTiming()` = 13 600 + 22 000 per connected-channel command (18 000 if empty) + 1 420 per short command (`pif/hle.cpp:195-240`). That gives 38 440 for systembench's 1-command case (+1.2 %) and 104 440 for 4 connected (+6.7 % vs 97 890, if the systembench rig had 4 pads, which the source doesn't state).
- MM polls on every VI retrace: `PadMgr_HandleRetrace` calls `osContStartReadData` (`src/code/padmgr.c:632-636`), so one WR64B + RD64B pair per field (~60 Hz). Bandwidth is about 7.7 KB/s; the per-poll latency (~0.6–1.6 ms) matters only for input timing.

### AI DMA

- n64brew AI: *"The AI does not have an internal RAM holding samples: the DMA is directly connected to the DAC"*. The IRQ fires when a buffer **starts**. There is an 8 KiB-boundary carry bug.
- MiSTer fetches 8 B (2 stereo samples) per request (`AI.vhd:104-106`).
- MM:
  - `session_config.c:103` requests 32 000 Hz.
  - `osAiSetFrequency` (`src/libultra/io/aisetfreq.c`) sets `dacRate = (s32)(48 681 812/32 000 + 0.5) = 1521`, so the real rate is 32 006.4 Hz.
  - Bandwidth 4 B × 32 006 = 128 KB/s, which is 0.026 % of 500 MB/s.
- ares reads 4 B per sample at the DAC period (`ai/ai.cpp:35-48`, rate set in `ai/io.cpp:59-62`). It charges no bus time.

### VI scanout

**MM's mode.**
- `SysCfb_SetLoResMode` sets `gActiveViMode = &osViModeNtscLan1` (`src/code/sys_cfb.c:56`). Gameplay runs in this mode.
- `osViModeNtscLan1` (`src/libultra/vimodes/vimodentsclan1.c`):
  - ctrl = TYPE_16, AA_MODE_1 (AA_NEEDED), gamma/dither, divot.
  - WIDTH 320, X_SCALE 0x200, H_START 108–748.
  - V_START 37–511 (half-lines), Y_SCALE 1.0, VSYNC 525, HSYNC 3093.
- Boot additionally sets `OS_VI_DITHER_FILTER_ON | OS_VI_GAMMA_OFF` (`src/boot/idle.c:33`).
- The Bomber's Notebook uses a 576×454 hi-res custom mode (`sys_cfb.c:59-99`, `include/macros.h:12-13`).

**Arithmetic** (from register values):
- Line period = (3093+1)/48.681 812 MHz = 63.556 µs ≈ 3 972 RCP.
- 263 lines per field (VSYNC 525 → 526 half-lines, progressive) → 59.83 Hz.
- Active lines = (511−37)/2 = 237.
- Bytes per line = 320 × 2 = 640.
- So **151 680 B per field ≈ 9.07 MB/s ≈ 1.8 % of 500 MB/s**.
- Per active line, 640 B is ≥ 80 RCP of raw data-packet time out of 3 972. Five 128-B bursts is my inference from the RI 128-B maximum.

**AA_NEEDED** is documented as *"only fetches extra lines as needed"* (n64brew VI_CTRL), but the policy and cost are not measured. Fetching one extra line per output line would double this to about 18 MB/s, so treat 9–18 MB/s as the range.

**Notebook.** About 1 152 B/line. If it is interlaced at about 227 lines per field, that is ≈ 15.6 MB/s. This is inference: ViMode_Configure's interlace choice was not traced here.

**Refresh.** n64brew RI says refresh is triggered by VI HSYNC and runs during HBLANK, *"so it can't block VI scanout"*. One refresh per line covers 2 rows on all banks. The delay after refresh is `CleanRefreshDelay`/`DirtyRefreshDelay` (IPL3: 52/54, "tRETRY…/4"); the units in RCP cycles have not been established.

**Emulators.**
- None charges VI bus time: ares `vi/vi.cpp:88-96,200,218`, plus cen64, gopher64, Dillonb, mupen64plus and simple64 per their source.
- MiSTer fetches a whole line per burst, 0xB0 beats = 1 408 B for 16 bpp when X_SCALE > 0x200, labeled `-- hack for 320/640 pixel width` (`VI_linefetch.vhd:123-128`). That is functional, not a hardware cost.

### Arbitration and contention

- No hardware source gives the RCP's RDRAM arbitration order or per-request overhead.
- MiSTer's order is an implementation choice on DDR3: RSP write FIFO > PI write FIFO > DD > VI > AI > CPU > SI > PI > SS > RDP > RSP-read > RDP color/Z > VI-FB (`DDR3Mux.vhd:244-376`). It has no RDRAM row model and no hardware citations.
- n64brew's `RI_LATENCY` "DmaLatencyOverlap" default 0xF is speculated to cap DMA bursts at 16 octbytes (128 B) for latency to high-priority devices like VI. It is labeled speculation on n64brew.

### Other emulators

These were surveyed from source in the scratchpad clones.

| Emulator | SP DMA | PI DMA | SI | AI | VI |
|---|---|---|---|---|---|
| cen64 | instant (`rsp/interface.c:19-100`) | `len/2+100` RCP, no domain regs (`pi/controller.c:328,343`) | instant | `62.5e6/freq × len/4` | none |
| gopher64 | `31+n/3+9` CPU cycles | `((14+LAT)·pages + (PWD+RLS)·len/2 + 5·pages + rand%16)×1.5` (`pi.rs:172-196`) | WR 6 000 CPU, RD 24 000 + 30 000/channel | `len·93.75e6/(4·freq)` | none |
| simple64 | `(9+31+n/3)/2` Count | same as gopher64, no rand | half of gopher64's numbers (cites systembench) | `len·46.875e6/(4·freq)` | none |
| Dillonb | instant | gopher formula, but `INSTANT_DMA` on by default (`CMakeLists.txt:46`) | 131 072 CPU (off by default) | per-sample read, ×1.037 fudge | none |
| mupen64plus | `count·len/8` Count | `len/8 + rand%64` Count | 0x900 Count | len·rate | none |

The gopher64/simple64/Dillonb PI formula is the same structure as ares's. It differs in using `+5·pages` rather than 28 per 128-B block, so it under-charges RDRAM writeback.

## Open questions this raised

1. Is the SP DMA rate row-dependent? hcs64 R² = 0.975 suggests scatter. A row-crossing sweep on hardware (SP DMA lengths 8–4096 at offsets around 2 KiB row ends) would settle it and give the true setup overhead.
2. What does VI AA_NEEDED actually fetch per line, in what burst size, and when within the line? This decides whether VI bandwidth is 9 or 18 MB/s for MM, and when VI preempts other masters.
3. What is the RCP's RDRAM arbitration order and the per-request turnaround? (No source at all; MiSTer's order is not hardware-derived.)
4. Which games broke under `bea395b24`? Asking LukeUsher/rasky directly is the only route; nothing is public.
5. MM's PI transfer-size histogram per frame (emux counters exist; not yet captured) decides how much the single-page +1 RCP/B bug matters.

## Sources

- n64brew wiki, raw wikitext fetched 2026-10-04 (copies under the session scratchpad `webresearch3/`):
  - Reality Signal Processor/Interface: https://n64brew.dev/wiki/Reality_Signal_Processor/Interface
  - Parallel Interface: https://n64brew.dev/wiki/Parallel_Interface (DMA Transfers, domain registers)
  - Serial Interface: https://n64brew.dev/wiki/Serial_Interface
  - Audio Interface: https://n64brew.dev/wiki/Audio_Interface
  - Video Interface: https://n64brew.dev/wiki/Video_Interface (VI_CTRL AA_MODE, VI_H_TOTAL)
  - RDRAM: https://n64brew.dev/wiki/RDRAM (write packet timing, line 377)
  - RDRAM Interface: https://n64brew.dev/wiki/RDRAM_Interface (RI_REFRESH, RI_LATENCY, "Count")
- HCS, "RSP DMA Transfer Rate" (2002): https://hcs64.com/dma.html
- rasky/n64-systembench `845635c`, `src/main.c:571-613`: https://github.com/rasky/n64-systembench
- rasky/n64_pi_dma_test `fea460b06`, `pi_dma_test.c`, `data/pidma_ram*_rom0.log`: https://github.com/rasky/n64_pi_dma_test
- ares upstream:
  - PR #2139 / `bea395b24`: https://github.com/ares-emulator/ares/pull/2139
  - revert PR #2147 / `807ef0300`: https://github.com/ares-emulator/ares/pull/2147
  - PI bus rewrite PR #2583 / `3c63fbcfb`: https://github.com/ares-emulator/ares/pull/2583
  - earlier commits `91f3dfaf3`, `7812cc181`, `4c15ed753`
- ares fork `a776c509b`: `ares/n64/{rsp/dma.cpp, pi/dma.cpp, pi/io.cpp, si/io.cpp, pif/hle.cpp, ai/ai.cpp, ai/io.cpp, vi/vi.cpp, rdram/rdram.hpp, cpu/emux.cpp, system/system.hpp}`
- MiSTer N64 core `5725381`: `rtl/{RSP,PI,SI,PIF,AI,VI_linefetch,DDR3Mux,memorymux}.vhd`
- gopher64 `1ab3793`: `src/device/{rdram,rsp_interface,pi,si,ai,vi}.rs`; cen64, Dillonb n64, mupen64plus-core, simple64 (scratchpad clones)
- MM decomp (mm-decomp-60fps `56fa21dd0`):
  - `baseroms/n64-us/baserom.z64` header
  - `src/libultra/io/cartrominit.c`, `src/libultra/io/aisetfreq.c`, `src/libultra/vimodes/vimodentsclan1.c`
  - `src/code/sys_cfb.c`, `src/boot/idle.c`, `src/boot/z_std_dma.c`, `src/code/osFlash.c`, `src/audio/session_config.c`
  - `include/PR/os_flash.h`, `include/z64dma.h`
- MM SP DMA volumes: `mm-decomp-60fps/bench-results/20261004-165142-baseline-interp/*.run0.csv` (ares `a776c509b`, interpreter, 600 frames per scene)
