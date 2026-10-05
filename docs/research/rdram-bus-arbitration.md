# RDRAM, RI and bus arbitration (NTSC NUS-001 + Expansion Pak)

Research ticket: wScottSh/ares#4 (map: #1). Research date: 2026-10-04.

Question: how does the RCP arbitrate RDRAM between CPU, RSP DMA, RDP (command, color, Z, texture), VI, AI, PI and SI, and what does each transaction cost? Covers priority and preemption, burst sizes, bank/open-row behavior, RDRAM device timing, refresh and its stall cost, and the RI/RDRAM register values on the target console.

Prior synthesis (not repeated): mm-decomp-60fps `docs/research/n64-emulator-timing-model.md` §1.1 (RDRAM/RI rows), §2a (MiSTer memory), §2b (n64brew).

Notation in this doc:

- **tc** = one RDRAM clock cycle (tCYCLE) = 4 ns at 250 MHz. The bus moves 2 bytes (2 × 9 bits) per tc, so 8 bytes per 4 tc.
- **rclk** = one RCP clock = 16 ns at 62.5 MHz = 4 tc. **pclk** = one VR4300 clock = 2/3 rclk (93.75 MHz).
- "Inference" marks anything I derived rather than read. Each one names what it was derived from.

## TL;DR

1. **The RI is a single, in-order RDRAM channel master.** Every client goes through one internal 64-bit bus (`D`/`C` bus) and one RI. The clients are VR4300 via the MI, RSP DMA, RDP command DMA, RDP memory interface (span color/Z, TMEM loads), VI, AI, PI and SI. The RCP patents say only one sub-block can use the shared bus at a time. Each sub-block buffers so it can tolerate waiting.
   - The client priority order is **not documented in any primary source found.** That covers patents, the SDK, n64brew, Rambus datasheets and IPL3.
   - n64brew's own Todo page lists "DMA Priority Arbitration" as unknown.
   - Best evidence on preemption: transactions are atomic bursts of 8–128 bytes (1–16 octbytes), and nothing is preempted mid-burst. This follows from the Rambus packet protocol, which has one request packet per data packet. Bursts serialize on the channel, so contention is decided per burst.
   - MiSTer's priority list is an FPGA/DDR3 design choice, not a hardware measurement.
2. **Transaction cost on the wire** (NEC µPD488170L datasheet, at the IPL3-programmed delays):
   - Row-hit read: request start to data start = **10 tc**, then 4 tc per octbyte.
     - 8 B = 14 tc (3.5 rclk). 16 B (D-cache line) = 18 tc. 32 B (I-cache line) = 26 tc. 128 B = 74 tc (18.5 rclk).
   - Row-hit write = **4 tc + 4 tc/octbyte**.
     - 8 B = 2 rclk. 128 B = 68 tc (17 rclk).
   - Row miss: the device NAcks, then retries after tRetrySensedClean = **22 tc** (5.5 rclk), or tRetrySensedDirty = **30 tc** (7.5 rclk) when the old row was written. So a clean read miss costs 32 tc to data start, and a clean write miss 26 tc.
   - Turnaround after a write to the same device: ≥ 4 tc. After a read: ≥ 2 tc.
3. **What the CPU actually sees is dominated by RCP/SysAD overhead, not the RDRAM wire.** Hardware-measured values:
   - Uncached 32-bit load: 32 pclk (21 rclk) with VI off, or with VI on in another bank. **36 pclk when the address is in the same 1 MiB bank as the VI front buffer** (nemu64-test).
   - D-cache miss: 41 pclk (VI off) / 42 pclk (VI on), with a measured range of 38–103.
   - n64-systembench: 34 pclk per uncached word, 37 per doubleword, 134 for 4 sequential, 136 for 4 in 4 different banks.
4. **Bulk DMA throughput** (hardware-measured):
   - RSP DMA memset: 1 MiB in 2.58 ms, which is ≈ 6.5 B/rclk ≈ 19.7 rclk per 128 B (n64brew MI page).
   - hcs64 (2002) measured RSP DMA at 3.7 B/pclk ≈ 5.55 B/rclk ≈ 23 rclk per 128 B, direction not stated.
   - Both sit above the wire minimum of 17 rclk (write) / 18.5 rclk (read) per 128 B. Inference: about 2–5 rclk of per-burst RI/RCP overhead.
5. **Banks and open rows.** Every retail RDRAM module is 2 MiB = two 1 MiB banks. Each bank holds one open 2 KiB row in its sense-amp cache. NUS-001 + Expansion Pak = 4 modules = **8 banks, bank = physical address bits [22:20], row = bits [19:11]**.
   - The RI shadows each bank's valid/dirty state (`RI_BANK_STATUS`). So it never blindly retries: it waits exactly the retry time and resends.
   - The SDK says to keep the color and Z buffers in different banks to cut latency.
6. **Refresh.**
   - When to refresh: one broadcast burst refresh (`SetRR`) per VI HSYNC. It refreshes 2 rows in each bank of every device.
   - What it costs: the RI then holds off the channel for `CleanRefreshDelay` = 52 rclk (832 ns) or `DirtyRefreshDelay` = 54 rclk (864 ns), depending on whether the bank's open row was dirty. The NEC datasheet gives tRetryRefresh = 213 / 221 tc (852 / 884 ns).
   - Net effect: ≈ 1.3–1.4 % of each 63.56 µs NTSC line is lost to refresh, during which every client stalls. The refresh also re-senses each bank's open row, so it leaves the row state unchanged except for clearing the dirty flag.
7. **Register values on the target console.** All of these come from IPL3 6105, verified by disassembling MM's own IPL3. **libultra never writes RI or RDRAM registers.**

   RI registers:

   | Register | Value |
   |---|---|
   | `RI_CONFIG` | 0x40 |
   | `RI_CURRENT_LOAD` | 0 |
   | `RI_SELECT` | 0x14 |
   | `RI_MODE` | 0x0, then 0xE |
   | `RI_REFRESH` | **0x007E3634** for 4 × 2 MiB modules. That is 0x63634 \| (0xF << 19). |
   | `RI_LATENCY` | never written; n64brew reset value 0xF |

   RDRAM registers:

   | Register | Value |
   |---|---|
   | `Delay` | AckWin 5 / Read 7 / Ack 3 / Write 1. Written as 0x18082838, rotated, through MI repeat mode. |
   | `RasInterval` | NEC non-low-latency parts: fields 1/7/10/4. Other or low-latency parts: 2/6/9/4. |
   | `Mode` | 0xC4000000 broadcast, then per-module DE + auto current control |
   | `RefRow` | 0 |

## Behavior table

| # | Behavior | Rule (best available knowledge) | References | How it can be verified |
|---|---|---|---|---|
| B1 | Single shared channel | All RDRAM traffic from CPU (MI), SP DMA, DP command DMA, DP memory interface, VI, AI, PI, SI is serialized through one RI/RAC onto one 9-bit Rambus channel. One sub-block owns the internal bus at a time. | US6166748 / US6331856 (Figs. 5–6, "only one of the subblocks can use these shared busses at a time"); n64brew RDRAM_Interface; US6155926 ("bus 106, the control of which is arbitrated by coprocessor 200") | Structural; consistent with all measurements below |
| B2 | Burst granularity | Every RDRAM transaction is 1–16 octbytes (8–128 B), 8-byte aligned (PI/SI may be misaligned; RI computes Count from NumBytes + Addr[2:0]). The RCP issues one request packet per burst. | n64brew RDRAM ("RI only supports transfers with 1 to 16 Octbyte"), RDRAM_Interface ("DMA bursts upto a maximum of 128 bytes"), MIPS_Interface (RI only 64-bit aligned) | MI repeat mode writes 8–128 B with one request (n64brew memset benchmark) |
| B3 | Client burst sizes | CPU: uncached 1–8 B → 1 octbyte. D-cache line fill/writeback 16 B. I-cache fill 32 B. PI DMA: blocks ≤ 128 B, split at 2 KiB RDRAM page boundaries. SI: 64 B PIF RAM. AI: 8 B at a time per patent. SP DMA: 8-byte units, length multiple of 8 (burst size per request not documented; inference: ≤ 128 B). RDP: span-buffer flushes of a span's pixels, fill mode writes 64 bits/clk straight to RDRAM, TMEM loads via span buffers. VI: blocks of a line segment plus next-line segments. | SysAD_Interface (n64brew); Parallel_Interface (n64brew); US6166748 (AI "8 bytes at a time", SI "64-byte", VI blocks, RDP span buffer); RSP Interface (n64brew); RDP Pipeline (n64brew) | PI block rule is hardware-tested (n64_pi_dma_test, cited on n64brew). Others: microbenchmarks that vary length across 128 B and 2 KiB boundaries |
| B4 | Arbitration priority | **Not documented.** No primary source states the order among clients. Best evidence: (a) VI is real-time and would need priority (inference from patent VI double-buffering and the n64brew RI_LATENCY note naming VI as "high-priority device"; speculative there). (b) MiSTer N64 RTL ordering (RSP DMA write FIFO > PI write > DD > VI > AI > CPU > SI > PI > RDP reads > RSP reads > RDP writes > VI) is chosen for its DDR3 back end, not measured. | n64brew Todo ("DMA Priority Arbitration" listed as needed); n64brew RDRAM_Interface (RI_LATENCY speculation); MiSTer `DDR3Mux.vhd:245-375` (prior doc §2a) | Hardware experiment needed: CPU uncached-load latency distribution while each DMA client saturates the bus (one at a time, then pairs) |
| B5 | Preemption | No mid-burst preemption: a burst is one Rambus request + one data packet. Contention is resolved between bursts; a waiting client's worst-case wait is one in-flight burst (≤ 128 B ≈ 17–19 rclk + overheads), plus refresh holdoff if refresh is pending. | Rambus protocol (NEC µPD488170L §§ packet/ack; US5606717); n64brew RDRAM_Interface Count encoding | nemu64-test D-cache miss range 38–103 pclk is consistent with waiting behind one or more bursts or a refresh (inference) |
| B6 | RDRAM geometry | All retail modules are 2 MiB (2 Mx9), 2 banks × 512 rows × 2 KiB. NUS-001 + EP = 4 modules = 8 banks. Bank = addr[22:20], row = addr[19:11], column/octbyte = addr[10:3]. RI tracks only the bottom 8 MiB as 8 banks; no address swapping. | n64brew RDRAM ("All known retail units use 2 MiB RDRAM modules"), RDRAM_Interface (address mapping, bank tracking); NEC µPD488170L ("1M-word × 9-bit × 2-bank", "2 Kbyte RowSenseAmpCache"); IPL3 geometry check (BNK=1, ROW=9, COL=11) | Read DeviceType of each module (ares fork already emulates 0xB4190010) |
| B7 | Open-row policy | Each bank keeps its last row open (sense-amp cache) until another row in the same bank is accessed or (no other close source documented). Hit → Okay ack and data. Miss → NAck; device writes back (if dirty) and senses the new row; RI waits the retry time and resends. RI keeps a shadow valid/dirty per bank (RI_BANK_STATUS) so it knows the wait. | NEC µPD488170L §8 (Nack/tRETRY); n64brew RDRAM_Interface "Bank Status Tracking"; US6166748 Fig. 37H text | nemu64-test uncached load: 32 vs 36 pclk depending on sharing the VI frame buffer's bank |
| B8 | Hit / miss cost (device) | tReadHit = 10 tc (request start → data start); tWriteHit = 4 tc; data 4 tc/octbyte. tRetrySensedClean = 22 tc, tRetrySensedDirty = 30 tc; tReadMiss = 32 tc, tWriteMiss = 26 tc (clean). Post-write same-device gap 4 tc, post-read gap 2 tc. These assume the IPL3 values Delay = 5/7/3/1 and RasInterval minimums 1/7/10/4 (NEC). | NEC µPD488170L "Hit, Retry and Miss Delay Characteristics", "Transaction Timing Characteristics", Table 8-1 | Datasheet; cross-check against RI refresh delay fields (B11) |
| B9 | CPU-visible cost | Uncached LW: 32 pclk median (VI off; VI on, other bank), 36 pclk median (same bank as VI front buffer). Uncached LD 37 pclk; 4 sequential LW 134; 4 LW in 4 banks 136. D-cache miss (16 B fill): 41 (VI off) / 42 (VI on) pclk median, range 38–103. Uncached SD throughput (memset): ≈ 12.3 rclk per 8 B. 4-entry uncached write buffer: up to 4 stores retire at 1 pclk each. | nemu64-test `src/tests/timing/cache.rs:193-380`, `timing/mod.rs:8617-8656`; n64-systembench `src/main.c:572-584`; n64brew MIPS_Interface memset table | These are the hardware references themselves; run both suites on the fork |
| B10 | DMA throughput | RSP DMA memset 1 MiB = 2.58 ms → 6.5 B/rclk. hcs64: 3.7 B/pclk = 5.55 B/rclk + ~41 pclk fixed (includes poll loop). MI repeat 128 B write ≈ 29 rclk each including CPU issue. PI DMA: systembench 8 B 193, 128 B 1591, 1 KiB 12168, 64 KiB 777807 rclk (bound by the PI bus, not RDRAM). | n64brew MIPS_Interface; https://hcs64.com/dma.html; n64-systembench `main.c:589-592` | Re-run systembench; add an SP DMA length sweep (both directions) to the fork's harness |
| B11 | Refresh trigger | RI broadcasts one `SetRR` burst refresh per VI HSYNC when `RI_REFRESH.En` = 1. One burst refreshes 2 rows per bank (NEC: "a burst of four rows" per 2-bank device). 512 rows/bank → 256 HSYNCs → 16.27 ms at NTSC H_TOTAL = 3093 (n64brew states 15.6 ms). Before VI is configured (H_TOTAL = 0x7FF): ≈ 42 µs per line → 10.8 ms. | n64brew RDRAM_Interface (RI_REFRESH), RDRAM (MinInterval SetRR), Video_Interface (H_TOTAL); NEC µPD488170L §8.2.2, tREF ≤ 17 ms | Measure uncached-load latency vs. VI_V_CURRENT / position in line: a periodic ~0.85 µs spike once per line |
| B12 | Refresh stall cost | After the refresh command, RI holds off all traffic for CleanRefreshDelay = 52 rclk (832 ns) or DirtyRefreshDelay = 54 rclk (864 ns), chosen by whether the open row was dirty. Device-side: tRetryRefresh = 213 tc clean / 221 tc dirty (852 / 884 ns). Fraction of an NTSC line: ≈ 1.31–1.36 %. Open rows are re-sensed (state preserved, dirty cleared). | n64brew RDRAM_Interface (52/54 = tRETRYREFRESH/4); IPL3 `RI_REFRESH(0,1,1,0,54,52)`; NEC µPD488170L Eq 8-5/8-6 and table | Same as B11. RI's 52/54 ×4 = 208/216 tc sits 1 tc under OKI MSM5718B70's 209/217 and 5 tc under NEC's 213/221 (§4) |
| B13 | Refresh placement | Triggered at HSYNC, i.e. during horizontal blanking, so it does not collide with VI active-line fetches. The `Bank` bit toggles 0/1 during operation (meaning undocumented). `Opt` bit = 1, meaning undocumented. | n64brew RDRAM_Interface | Logic-analyzer capture of the RDRAM channel (not found published) |
| B14 | MultiBank field | `RI_REFRESH[22:19]` flags which modules are 2-bank ("multibank"); n64brew: affects shared-resource timing between a module's two banks; exact effect "Research Needed". | n64brew RDRAM_Interface; IPL3 6105 | Toggle bits on hardware with a bank-ping-pong benchmark |
| B15 | RI_LATENCY | Reset value 0xF; never written by IPL3 or libultra. Patent: "DMA latency/overlap". n64brew speculates it caps burst length (0xF = 16 octbytes = 128 B). | US6166748 Fig. 37E text; n64brew RDRAM_Interface | Hardware: write smaller values, measure burst-split behavior via SP DMA throughput |
| B16 | Bank conflicts in rendering | The RDP alternates color and Z traffic. Same bank → row miss per switch; different banks → both rows stay open. SDK: "By keeping the color and z-buffers on different banks, you can improve the DRAM access latency." | N64 Programming Manual §12.8 (MI) | RDP fill/1-cycle Z benchmark with Z in same vs. different bank (needs DPC counters on hardware) |
| B17 | RDP stalls are counted | DPC_CLOCK counts all cycles; TMEM_BUSY and the GCLK-based counter stop while "stalled for RDRAM". So `CLOCK − PIPE/TMEM` exposes memory stall time on hardware. | n64brew RDP Interface; US6166748 (status field "stalled waiting for access to main memory") | Calibration ROM reading DPC counters (prior doc §3.5) |
| B18 | Who has the ninth bit | Only RDP and VI read/write the 9th (hidden) bit, over the EBus. It does not change transfer length on the channel (the channel is always 9 bits wide). | n64brew RDRAM, MIPS_Interface; US6166748 | n/a (functional) |
| B19 | Register init (target) | See §6 table. Values are fixed by IPL3 6105; libultra never touches RI/RDRAM regs. | MM `extracted/n64-us/incbin/ipl3` disassembly; decompals/N64-IPL `src/ipl3.s`; MM `src/libultra` grep | ares fork boots through IPL3 already (3cac8a186); compare register dump after boot |

## Details

### 1. Topology and arbitration

What the primary sources say:

- RCP patent family (US6166748, US6331856, US6239810, US6556197, US6593929, US6342892; Van Hook et al., Nintendo + SGI, priority 1995-11-22):
  - "Memory interface 212 provides access to main memory 300 for main processor 100, signal processor 400, display processor 500, video interface 210, audio interface 208, and serial and parallel interfaces 204, 206. Each of these various processors and interfaces may be active at the same time."
  - "Although each of the coprocessor 200 sub-blocks can independently access main memory 300, they all share common busses 214C, 214D in this example--and only one of the subblocks can use these shared busses at a time. ... the coprocessor 200 sub-blocks may buffer or "cache" information to minimize the frequency of different bus accesses by the same sub-block and to make the subblocks more tolerant of temporary bus unavailability."
  - Internal bus: 32-bit address C bus, 64-bit data D bus. A private X bus lets the RDP fetch commands from DMEM without the main bus.
  - DRAM controller "includes ... a conventional RAM controller 212b ... provided by Rambus Inc." (the RAC).
- US6155926 (Nintendo, Mario 64 family): RDRAM "coupled to coprocessor 200 via a unified nine bit wide bus 106, the control of which is arbitrated by coprocessor 200."
- n64brew Todo: "A page for hardware timings is desperately needed ... DMA Priority Arbitration".

Searched and not found, in every source above and in the SDK manuals:

- a priority order
- a round-robin or fixed scheme
- any statement about the CPU being favored or starved

**Status of priority.** This is the largest gap in this ticket. The best-grounded model available is:

- per-burst serialization (B1, B2, B5)
- VI given precedence (inference: VI is the only hard-real-time client and has a small double buffer)
- everything else in an order that must be measured

MiSTer's order is the only concrete implementation. It is an FPGA DDR3 mux designed for its own back end, and its author states its memory timings are not hardware-accurate (prior doc §2a). So it is a weaker reference than a hardware experiment, and it is not evidence of the real order.

**Hardware-measured hint about VI interaction.** nemu64-test measures an uncached load at a median of 36 pclk when the address shares the VI front buffer's 1 MiB bank, and 32 pclk otherwise (VI on or off). The test source notes the measurement is "pretty unstable" with a wide epsilon. Two inferences follow:

- VI fetches reopen their own row often enough that a majority of CPU loads in that bank see a row miss.
- The extra cost (≈ 4 pclk ≈ 2.7 rclk ≈ 11 tc) is about half of tRetrySensedClean (22 tc). That fits a partial overlap of the RI's retry wait with the fixed SysAD/MI overhead, rather than a fully serialized miss.

### 2. Transaction cost model

Device timing comes from the NEC µPD488170L 18 Mbit (1M × 9 × 2-bank) datasheet. Quoted values:

- tCYCLE: 4 ns (-A50).
- tReadDelay: 7 tc. tWriteDelay: 1 tc.
- tReadHit: 10 tc ("Start of request packet to start of read data packet for row hit").
- tWriteHit: 4 tc.
- tRetrySensedClean: 22 tc. tRetrySensedDirty: 30 tc.
- tRetryRefresh: 213 tc clean, 221 tc dirty.
- tReadMiss: 32 tc. tWriteMiss: 26 tc.
- tPostMemWriteDelay: 4 tc (same device). tPostMemReadDelay: 2 tc. tPostRegWriteDelay: 6 tc.
- Retry components (Table 8-1), each written as fixed + RasInterval field = total tc:

  | Component | Fixed | Field | Total tc |
  |---|---|---|---|
  | tRowOverHead | 7 | – | 7 |
  | tRowPrecharge | 6 | 1 | 7 |
  | tRowSense | 1 | 7 | 8 |
  | tRowImprestore | 5 | 10 | 15 |
  | tRowExprestore | 4 | 4 | 8 |
  | tRefRequestIdleOverHead | 14 | – | 14 |
  | tLessRowRefreshOverHead | 20 | – | 20 |

  tRetrySensedClean = 7 + 7 + 8 = 22. tRetrySensedDirty = 22 + 8 = 30. Both match the table.
- The other IPL3 RasInterval set, `RASINTERVAL(8,12,18,4)` (= 2/6/9/4), is bit-for-bit the OKI MSM5718B70 programming strings (01000/01100/10010/00100, OKI p21) and LG's "Normal 500MHz" column. OKI is checked here in the extracted datasheet text. LG is from a scan, read by a sub-agent.
- The table's RasInterval field defaults (1/7/10/4) are exactly IPL3's NEC values (`RASINTERVAL(16,28,10,4)` in bit-reversed field order = 1/7/10/4; libdragon `RDRAM_REG_RASINTERVAL_MAKE(1,7,10,4)` uses BITSWAP5 and agrees).
- tREF: 17 ms max (NEC 1996 revision, OKI, LG). The 1995 NEC revision and the Toshiba TC59R1809 say 32 ms. The N64's ~16.3 ms full cycle meets the stricter 17 ms.
- The device itself allows 1–32 octbytes (8–256 B) per transaction, but may not cross a 2 KiB row (NEC p15). The RI caps transfers at 16 octbytes (n64brew).
- Other vendors' hit/miss figures:
  - OKI MSM5718B70 (as seen by the channel master, including bus overhead): tREADHIT 10–17, tWRITEHIT 4–11, tRETRYSENSEDCLEAN 22, DIRTY 30, tREADBURST32 26, tWRITEBURST32 20.
  - Toshiba TC59R1809: retry 21 / 29; clean miss read 124 ns / write 100 ns; dirty miss read 156 ns / write 132 ns.
  - LG low-latency grade: retry 18 / 18.
  - Retail N64 module vendors vary, so per-vendor retry timing differs by ±1 tc. The model should use the NEC values, which IPL3's NEC branch programs.

Derived per-transaction wire time (inference: datasheet arithmetic; 8 B per 4 tc):

| Transfer | Read hit | Write hit | Read miss (clean / dirty) | Write miss (clean / dirty) |
|---|---|---|---|---|
| 8 B (uncached, AI) | 14 tc = 3.5 rclk | 8 tc = 2 rclk | 36 / 44 tc | 30 / 38 tc |
| 16 B (D-cache line) | 18 tc = 4.5 rclk | 12 tc = 3 rclk | 40 / 48 tc | 34 / 42 tc |
| 32 B (I-cache line) | 26 tc = 6.5 rclk | 20 tc = 5 rclk | 48 / 56 tc | 42 / 50 tc |
| 64 B (SI) | 42 tc = 10.5 rclk | 36 tc = 9 rclk | 64 / 72 tc | 58 / 66 tc |
| 128 B (max burst) | 74 tc = 18.5 rclk | 68 tc = 17 rclk | 96 / 104 tc | 90 / 98 tc |

Add the post-transaction gap (2 tc after a read, 4 tc after a write to the same device). Peak channel rate is 500 MB/s = 8 B/rclk.

**Gap between wire time and what clients see.**

- Uncached LW: 32 pclk = 21.3 rclk, against a wire time of 3.5 rclk. Inference: ≈ 18 rclk of SysAD + MI + RI + RAC pipeline latency, not modeled by any datasheet. The model should use the hardware-measured totals for CPU accesses (B9), with contention added on top, not the wire time.
- RSP DMA memset at 6.5 B/rclk means ≈ 19.7 rclk per 128 B, against a 17 rclk write wire time. hcs64's 5.55 B/rclk means ≈ 23 rclk per 128 B, against an 18.5 rclk read wire time.
  - The two hardware sources conflict by ~17 %.
  - hcs64 has a ~41 pclk loop overhead in its fit (R² = 0.975), does not state the transfer direction, and polls the busy flag.
  - The n64brew figure is a bulk 1 MiB memset (RDRAM writes), timed end to end.
  - The n64brew figure is better grounded for writes. hcs64 is the only source for an unlabeled direction. A two-direction length sweep would settle it.
  - Inference: if hcs64 measured reads, the two agree once the 1.5 rclk extra read latency per burst plus RI overheads are counted.

### 3. Banks, rows and the RI shadow state

- Geometry: n64brew RDRAM says "All known retail units use 2 MiB RDRAM modules, both within the console and within the expansion pak". IPL3 accepts DeviceType BNK=1, ROW=9, COL=11. NEC µPD488170L has 2 banks, each with a "2 Kbyte RowSenseAmpCache".
- Mapping (n64brew RDRAM_Interface): Adr[28:20] = (addr >> 20) & 0x3F, Adr[19:11] = row, Adr[10:0] = byte in row. RI hardwires 8 banks of 1 MiB at 0–8 MiB. Address swapping (AddressSelect) is unusable because bank tracking does not follow it.
- Miss protocol (NEC §8.2.1): "If an initiating device requests a region of memory space in an RDRAM slave which is not currently held in the RowSenseAmpCache, the RDRAM will respond with a Nack ... During the RowMiss, the RDRAM will Nack any request it is given."
- RI policy (n64brew): "RI doesn't have any retry logic. Instead, RI tracks the current status of the state machine for each bank ... With this state tracking, RI always knows which requests will cause a miss and how long it needs to wait before resending the request packet."
- RI_BANK_STATUS: valid bit set when a row opens; dirty bit set when the open row is written.
- Open-page policy: rows stay open. The Rambus base patent allows "precharge the sense amps if they are not accessed for a selected period" (US5606717). No source says the RI or IPL3 enables that, and IPL3 writes no such field. Best model: rows stay open until displaced, and refresh re-senses them (§4).
- SDK §12.8 (MI): "The DRAM has dual banks, one on each 1 MB. By keeping the color and z-buffers on different banks, you can improve the DRAM access latency when the RDP is seeking DRAM bandwidth for rendering."
- MM placement (from decomp, for the model's later use):
  - Lo-res framebuffers are `gHiBuffer.framebuffer` (inside 0x80780000–0x807FFFFF, bank 7) and `gLoBuffer.framebuffer` (0x80000500, bank 0). `include/buffers.h`, build map.
  - The Z buffer is `malloc`ed from the system heap (`src/code/graph.c:385`), so its bank is decided at run time.
  - So whether MM's RDP color and Z share a bank depends on which framebuffer is current. That is an open question (§8).

### 4. Refresh

- Trigger (n64brew RDRAM_Interface): "The automatic refresh operation, when enabled, is triggered by VI HSYNC timing. This forces the refresh operation to happen during HBLANK so it can't block VI scanout."
- Mechanism (n64brew RDRAM, MinInterval): "The N64 implements refresh by broadcasting one SetRR command whenever VI emits a horizontal sync pulse." SetRR = "Manual refresh. The device immediately preforms a single a burst refresh of two rows per bank".
- Device (NEC §8.2.2): "a refresh burst will first restore the currently accessed row if it is dirty ... A burst of four rows are precharged/sensed/restored ... and the current row is precharged/sensed so the RDRAM is left with its RowSenseAmpCache state unaltered (except the row's dirty flag will be cleared)". Four rows per two-bank device equals n64brew's "two rows per bank", so the sources agree.
- Holdoff:
  - RI_REFRESH Clean = 52, Dirty = 54. n64brew: "tRETRYREFRESHCLEAN / 4", i.e. in rclk.
  - NEC gives 213 / 221 tc = 53.25 / 55.25 rclk.
  - Other datasheets for the same class of part give different values:
    - OKI MSM5718B70: tRETRYREFRESH 209 / 217 tc, "Start of request that performs a burst refresh (SetRR) until the start of a request that will not have a Nack".
    - LG GM73V1892 (normal grade): 213 / 221 tc.
    - The 1995 NEC revision: 191 / 199 tc.
  - RI's 52/54 rclk = 208/216 tc. That is 1 tc under OKI and 5 tc under NEC.
  - Inference: Nintendo picked the RI values to cover the vendors' worst cases at a 1-rclk granularity (OKI's 209 rounds to 52.25 rclk), possibly with request-packet slack. The datasheets disagree with each other by up to ~2 %, so the RI field (52/54) is the better-grounded number for the model, because it is what the controller actually waits. Stall ≈ 52–54 rclk.
  - Because the command is a broadcast, all four modules refresh at once. So the whole channel is unavailable for that window, not just one bank. This is an inference from the broadcast semantics. Whether the RI uses per-module dirty state when it picks 52 vs. 54 is not documented.
- Rate:
  - NTSC H_TOTAL = 3093 (n64brew VI), so a line is (3093 + 1) / 4 VI pixels at a 48.68 MHz VI clock = 63.56 µs.
  - 256 HSYNCs cover 512 rows: 16.27 ms (my arithmetic). n64brew states 15.6 ms. Both are under the 17 ms tREF.
  - Bandwidth lost: 0.832–0.864 µs / 63.56 µs = 1.31–1.36 %.
  - MM's NTSC VI modes (LAN1, HPF1, HPN1) all set `HSYNC(3093, 0)` (`src/libultra/vimodes/vimodentsc*.c:14`), so the refresh rate is the same in lo-res and hi-res.
- Before VI init: H_TOTAL = 0x7FF, so a line is ≈ 42 µs and refresh is ≈ 2 % (n64brew: "noticeable memory bandwidth reduction until the VI is configured"). This only matters before osViSetMode.

### 5. Client-side behavior that sets traffic shape

- **CPU** (SysAD → MI → RI):
  - D-cache line = 16 B. Writebacks are 128-bit aligned, full line.
  - I-cache fill = 32 B, sent as 8 × 32-bit words on SysAD.
  - Uncached accesses are 1 octbyte. MI byte-masks writes; reads always return 64 bits.
  - The CPU is stalled for the entire access (n64brew Memory map: "Effectively, all reads and writes are synchronous (blocking)"). The only exception is the 4-entry uncached write buffer (nemu64-test).
- **RSP DMA**:
  - 8-byte aligned, length a multiple of 8. Registers are double-buffered, so one DMA can be pending.
  - "fastest DMA engine" (n64brew).
  - Per-request burst size is not documented. Inference: 128 B bursts, matching the RCP maximum and the measured ~20 rclk per 128 B.
- **RDP**:
  - Command DMA pulls from RDRAM (or DMEM via XBUS) into an internal FIFO "in small batches".
  - The memory interface reads a span's color (and Z) into span buffers, then writes the whole span back as a block ("writes the entire span worth of pixels into main memory 300 as a block all at once"; patent).
  - Fill mode writes 64 bits per clock directly.
  - SDK ch. 12.1:
    - "In small triangles, it is rare to have long horizontal runs of pixels on a single scanline. In these cases, the pipeline is often stalled, pending memory access for read or write cycles."
    - "In one-cycle mode, the pipeline is often stalled at MI, waiting for the framebuffer when accessing both color and z."
  - SDK ch. 24: atomic-primitive mode (G_PM_1PRIMITIVE) "inserts a delay into the pipeline between each primitive" so that read-modify-write spans don't overlap; worst case "about 1-1.5Mpixels/sec of lost fillrate".
  - TMEM loads stage through span buffers. Span buffers hold 288 B (n64brew).
  - "for single rows span buffers are employed to alleviate stalls ... there is no such buffering across multiple rows" (n64brew RDP Commands).
- **VI** (SDK ch. 24, Raster Tuning): "Both antialiasing and dither filter video hardware require fetching 3 scanlines and filter down to produce a single scanline of video." The same section says a larger framebuffer without AA costs "a 5% to 10% fixed overhead due to additional video bandwidth" on small polygons. That is a vendor statement that VI traffic measurably slows the RDP.
  - Per the patent, it reads blocks for the current line segment plus the next one or two lines (for filtering), into a double buffer. Fetch size and count per line are not documented. n64brew notes a per-scanline fetch allocation: X_SCALE above 0x800/0xE00 "exceed[s] the number of VI fetches allocated per scanline".
- **AI**: "writes this audio sample data, 8 bytes at a time" into a FIFO of 64-bit buffers (patent). It has no sample RAM (n64brew).
- **PI**: 128 B internal buffer. Fills from the PI bus, then writes to RDRAM. Blocks are ≤ 128 B and split at 2 KiB page ends (n64brew, hardware-tested by n64_pi_dma_test).
- **SI**: 64 B blocks (patent, n64brew).

### 6. RI / RDRAM register values on NUS-001 + Expansion Pak

Source: MM's IPL3 (CIC-6105, `extracted/n64-us/incbin/ipl3`, md5 `ff22a296e55d34ab0a077dc2ba5f5796`), disassembled here with `mips-linux-gnu-objdump`. Cross-checked against decompals/N64-IPL `src/ipl3.s` (X105 build, commit 928f590), which assembles to matching binaries per its README.

| Register | Value written | Where (MM IPL3 VA) | Notes |
|---|---|---|---|
| RI_CONFIG | 0x40 (AutoCC) | 0xA400010C | then wait 8000-loop |
| RI_CURRENT_LOAD | 0 | 0xA4000124 | latch CC |
| RI_SELECT | 0x14 (TSEL=1, RSEL=4) | 0xA400012C | RMC "Option A" per n64brew |
| RI_MODE | 0x0, then 0xE (STOP_R, STOP_T, OP_MODE=10) | 0xA4000130, 0xA400014C | |
| MI_MODE | 0x10F (repeat 16 B) for the Delay write | 0xA4000160 | |
| RDRAM Delay (bcast) | 0x18082838 (rot16 of 0x28381808: AckWin 5, Read 7, Ack 3, Write 1) | 0xA400016C | |
| RDRAM RefRow (bcast) | 0 | 0xA4000170 | |
| RDRAM DeviceId (bcast) | 0x80000000 (→ 0x2000000) | 0xA4000178 | temporary park |
| RDRAM RasInterval (per module) | 0x101C0A04 (= 1/7/10/4) if manufacturer NEC and not low-latency; else 0x080C1204 (= 2/6/9/4) | 0xA4000298–0xA40002B0 | fields bit-reversed |
| RDRAM Mode (bcast) | 0xC4000000 (X2, CE, AS) | 0xA40002D4 | then per-module WriteCC with DE + auto CC |
| RI_REFRESH | 0x00063634 \| (2MB_bitmask << 19). NUS-001 + EP has 4 modules, so the mask is 0xF and the value is **0x007E3634** | 0xA40003EC | Opt = 1, En = 1, Dirty 54, Clean 52 |
| RI_LATENCY | not written. n64brew reset = 0xF | – | |
| osMemSize | 0x800000, stored at 0x800003F0 (6105) | | MM re-probes with `osGetMemSize` (`src/libultra/os/getmemsize.c`) |

- **libultra never writes RI or RDRAM registers.** A grep of MM's `src/libultra`, `src/boot` and `include` finds only the `rcp.h` definitions.
- The "4 modules" count uses n64brew's statement that all retail modules are 2 MiB. Board revisions with two 18 Mbit chips (2 modules) or one 36 Mbit chip (2 modules; libdragon `boot/rdram.c`: "4 MiB chips" are "actually two different 2 MiB chips in the same package") both give 2 modules on the board, plus 2 in the Expansion Pak.
- **Emulator defaults differ.** cen64, gopher64 and MiSTer reset RI_REFRESH to 0x63634, without the multibank bits. That is an HLE shortcut, not the post-IPL3 value. The ares fork runs the real IPL3, so it produces the real value.

### 7. What emulators and the FPGA core do (for contrast)

- ares fork: RI/RDRAM registers emulated functionally, including current calibration and the hidden bits (`ares/n64/rdram/rdram.cpp`, commits 3cac8a186 and 45c229126). There is no timing: no arbitration, rows or refresh. Per-client byte counters exist (`RBusDevice`).
- gopher64: a DMA/cache-miss cost of `31 + len/3` (`src/device/rdram.rs:175-176`), citing hcs64 and systembench. No contention.
- MiSTer: DDR3 mux priority and latency floors (prior doc §2a). RI registers have no timing effect.
- None of these models refresh, rows or priority.

### 8. Open questions this ticket surfaced

1. Client priority order and whether the CPU can be starved by RSP or RDP DMA streams. Needs a hardware run: uncached-load latency histograms while each DMA client saturates.
2. What does the RI do when two requests target the same bank at different rows back to back? Does it reorder, or serve strictly in order? The RI shadow state allows either.
3. The meaning of RI_REFRESH `Opt`, `Bank` and `MultiBank`. Does the 52/54 holdoff block all banks or only the refreshing module?
4. The 36 vs. 32 pclk VI-bank effect: how often does VI fetch, and in what sizes? This needs a per-line VI fetch schedule, which also decides VI's share of bandwidth.
5. SP DMA rate per direction (hcs64 vs. n64brew memset disagree by ~17 %).
6. In MM, which bank does the Z buffer land in, relative to each framebuffer? Read `gZBufferLoRes` at run time in the fork. This decides how many RDP color/Z switches are row misses.
7. RI_LATENCY's effect (burst cap?). Unused by software, so it matters only if it changes the reset-default behavior.

## Sources

Primary hardware documentation

- NEC µPD488170L 18M-bit Rambus DRAM preliminary data sheet (M10801EJ4V0DSU1). https://datasheet.datasheetarchive.com/originals/library/Datasheet-048/DSA0080865.pdf . Used: pp. 15, 37–40 (Nack, tRETRY, Table 8-1), pp. 44–45 (timing tables).
- NEC 1995 and 1996 Application Specific Memory databooks (earlier and later revisions of the same part). http://www.bitsavers.org/components/nec/_dataBooks/
- OKI MSM5718B70 18 Mbit RDRAM. https://www.datasheetarchive.com/pdf/download/distributors/Datasheets-23/DSA-447500.pdf (pp. 15, 20–23, 28–30)
- Toshiba TC59R1809. https://datasheet.datasheetarchive.com/originals/scans/Scans-99/DSAIHSC000106080.pdf
- LG Semicon GM73V1892AH. https://datasheet.datasheetarchive.com/originals/scans/Scans-060/DSA2IH0077762.pdf
- US5606717A (Rambus, priority 1990-04-18): request packets, access-time registers, sense-amp-as-cache, retry. https://patents.google.com/patent/US5606717A/en
- US6166748A, US6331856B1, US6239810B1, US6556197B1, US6593929B2, US6342892B1 (Nintendo / SGI RCP family). https://patents.google.com/patent/US6166748A/en
- US6155926A (Nintendo): 9-bit bus "arbitrated by coprocessor 200", RDRAM chain init. https://patents.google.com/patent/US6155926A/en
- US6310814B1 (Rambus, 1998, cited by n64brew Clock Timing): generic Concurrent/Direct RDRAM refresh. Not N64-specific; not used for values.
- N64 Programming Manual (ultra64.ca mirror, man-v5-1):
  - §12.1, RDP pipeline stalls at MI. https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro12/12-01.htm
  - §12.8, "MI: Memory Interface" (bank placement). https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro12/12-08.htm
  - §24.4, Raster Tuning (VI 3-scanline fetch, video bandwidth overhead, atomic primitive). https://ultra64.ca/files/documentation/online-manuals/man-v5-1/pro-man/pro24/24-04.htm

Hardware-measured test suites and measurements

- nemu64-test `9a8b9f7`: `src/tests/timing/cache.rs:193-380` (load miss and uncached, VI on/off, same/other bank), `src/tests/timing/mod.rs:8617-8656` (write buffer).
- rasky/n64-systembench `845635c`: `src/main.c:230-293` (bench bodies), `:572-613` (expected values).
- n64brew MIPS_Interface memset benchmarks (1 MiB): uncached SD 25.7 ms, cached 49.8 ms, RSP DMA 2.58 ms, MI repeat 3.80 ms. https://n64brew.dev/wiki/MIPS_Interface
- hcs64, "RSP DMA Transfer Rate" (2002). https://hcs64.com/dma.html

n64brew (raw wikitext saved at scratchpad `n64brew/`)

- https://n64brew.dev/wiki/RDRAM_Interface (RI registers, bank tracking, refresh, Count encoding)
- https://n64brew.dev/wiki/RDRAM (Delay, Mode, MinInterval/SetRR, init sequence)
- https://n64brew.dev/wiki/Video_Interface (H_TOTAL, fetch allocation)
- https://n64brew.dev/wiki/Parallel_Interface, …/Serial_Interface, …/Audio_Interface
- https://n64brew.dev/wiki/Reality_Signal_Processor/Interface, …/Reality_Display_Processor/Interface, …/Reality_Display_Processor/Pipeline, …/Reality_Display_Processor/Commands
- https://n64brew.dev/wiki/SysAD_Interface, …/Memory_map, …/Clock_Timing, …/Todo

Boot code and libultra

- MM decomp: `extracted/n64-us/incbin/ipl3` (6105), `src/libultra/os/getmemsize.c`, `include/PR/rcp.h`, `include/buffers.h`, `src/code/sys_cfb.c`, `src/code/graph.c:385`
- decompals/N64-IPL `928f590`: `src/ipl3.s:100-490` (RI/RDRAM init, X105). https://github.com/decompals/N64-IPL
- libdragon `e356bf3`: `boot/rdram.c` (open IPL3 RDRAM init; RasInterval and refresh values agree with Nintendo IPL3)

Emulator and FPGA source (contrast only)

- ares fork (this repo) `ares/n64/rdram/*`, `ares/n64/ri/*`
- gopher64 `1ab3793` `src/device/rdram.rs`, `src/device/ri.rs`
- cen64 `ri/controller.c`
- MiSTer N64_MiSTer `5725381` `rtl/RI.vhd`, `rtl/DDR3Mux.vhd`, `rtl/VI_linefetch.vhd`, `rtl/RDP.vhd`
