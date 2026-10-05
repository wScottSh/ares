# CPU memory access costs (VR4300 on NUS-001)

Ticket: wScottSh/ares#6. Map: wScottSh/ares#1. Research date: 2026-10-04.

Target: NTSC retail NUS-001 with Expansion Pak.

Units:

- **CPU cycle** = VR4300 PClock, 93.75 MHz.
- **RCP cycle** = 62.5 MHz (SysAD SClock / MasterClock). 1 RCP cycle = 1.5 CPU cycles.
- ares counts in half-CPU-cycles (`step(N * 2)`, `queueInsert(..., clocks)` at 187.5 MHz). Every ares number below is converted to CPU cycles.

Snapshots:

- this fork `59158c28a` (branch `master`)
- nemu64-test `9a8b9f7`
- rasky/n64-systembench `845635c`
- N64_MiSTer `5725381`
- gopher64 `1ab3793`
- cen64 `e0641c8`
- NEC VR4300 User's Manual U10504EJ7V0UM00 (7th ed., the copy hosted on n64brew)

This doc builds on `docs/research/n64-emulator-timing-model.md` §1 in the mm-decomp-60fps repo (not published). That doc's CPU rows are not repeated here, only corrected or extended.

## TL;DR

- **The best data comes from two hardware-measured suites, and they agree.**
  - nemu64-test times single instructions with a half-cycle-calibrated COUNT loop.
  - n64-systembench times C-level accesses and includes about 2 cycles of harness overhead. That figure comes from its cached-read baseline of 3 against nemu64-test's 1.
  - Both give an **uncached RDRAM word read of 32 CPU cycles** (VI off, or a bank the VI isn't reading). Both give a **clean D-cache line fill of 41 cycles** in total for the load.
- **This fork, measured by running nemu64-test `timing` on a build of `59158c28a`:**
  - **Every cached load/store hit costs 2 cycles instead of 1.** This fails 19/19 warm-cache tests. It is also the likely cause of about 150 "CPU register dependency" failures.
  - **Uncached RDRAM reads cost 1 cycle (interpreter) or 2 (recompiler) instead of 32.**
  - A clean D-miss costs 41 (interpreter) or 42 (recompiler). That matches the hardware median but has no contention tail.
- **Code-derived (not run) mismatches:**
  - A dirty D-miss is charged 81, serial.
  - The I-miss charge of 49 sits a few cycles above the hardware hint of about 43–47.
  - A PI cart read is charged 271 CPU cycles, against about 214 on hardware with retail BSD timings.
  - A PIF-RAM read is charged 21 cycles, against about 2960 on hardware.
  - There is no write buffer: stores never stall.
  - A RCP-register read is charged 21, against about 22 on hardware. That one is correct.
- **The "38–103" spread is an acceptance envelope, not a measured distribution.**
  - The pass condition is that measured min and max fall inside it.
  - Measured medians and means show a small tail: VI off, median 41 and mean 42.5. VI on, median 42 and mean 43.25.
  - The envelope stays at 103 even with VI disabled. So part of the tail is not VI. RDRAM refresh is the obvious remaining source [inference].
- **The open gaps no reference measures:**
  - the dirty-miss (writeback) cost and its ordering
  - the write-buffer drain rate and the stall when a 5th store arrives
  - RCP-register write latency
  - I-cache fill as a direct measurement

## Behavior table

"Total" means the whole instruction, including its own 1 issue cycle. That is the quantity nemu64-test reports.

| Operation | Hardware cost (best available) | References | ares today (file:line) | How verified |
|---|---|---|---|---|
| Cached load/store, **D-cache hit** | **1** total. | nemu64-test `Cached loads and store (with warm cache)`: all 19 L*/S* expect 1 (`timing/mod.rs:2297-2360`). Manual §4.6.7 DCB: +1 only when the *next* instruction also uses the D-cache after a store. systembench C8/16/32/64R = 3 including about 2 overhead (`main.c:572-575`). | **2**. Fetch `step(1*2)` (`cpu/memory.cpp:158`) plus hit `step(1*2)` (`cpu/dcache.cpp:61`, `:90`). Recompiler: instruction 1 + `emitCpuStep(2)` (`cpu/recompiler-ipu.cpp:167`). | **Ran** nemu64-test timing on this fork: 19/19 fail "Actual: 2, expected 1", in interpreter and recompiler. |
| Load-use after cached load (LDI) | 2 for `LW r; ADDIU x,r` (1 + 1 interlock). The interlock fires on register-field overlap even when the value isn't used (n64brew VR4300 §Load Delay Interlock). | Manual §4.6.5. nemu64-test `CPU register dependency`. | No LDI modeled. The +1 hit cycle makes independent pairs cost 3. | **Ran**: 170 of 199 register-dependency failures involve a load or store. The dominant deltas, "3 vs 2" (80) and "4 vs 3" (46), match the extra hit cycle [inference from deltas]. |
| **D-cache line fill, clean** (16 B) | **41 total** (VI off, median; mean 42.5). **42** (VI on; mean 43.25). Envelope 38–103. Same in all eight 1 MiB banks 0–7 MiB, Expansion Pak included. | nemu64-test `cache.rs:193-286`. Manual Table 11-1: stall = 1+1+(1–2)+2+**M**+2+1, so M ≈ 31–32 PClocks [derived]. Critical-doubleword-first restart (manual §11.3.2). | 1 + `step(40*2)` (`cpu/dcache.cpp:7`) = **41** interpreter. **42** recompiler (slow path, cause not traced). | **Ran**: interpreter 41.0 every bank, so it fails the mean check, which expects 42.5±0.5. Recompiler 42 passes VI-off and fails VI-on (43.25±1). |
| **D-cache line writeback** (dirty victim on miss) | **No hardware measurement found.** Manual §4.9/§11.3.2: the dirty line goes to the write buffer, the fill is requested, and the buffered line is written *after*. The pipeline restarts on the critical doubleword, so the writeback should mostly overlap execution [inference from manual]. | Manual §4.9, §11.3.2. Emulators disagree (see Details). | 1 + 40 writeback + 40 fill = **81**, serial (`cpu/dcache.cpp:16`, `:53-58`, `:82-87`). | Code-derived. No test exists. |
| CACHE D-op writeback (Hit/Index WB[I]) | Not measured. The only CACHE timing data is `LD; CACHE DataIndexLoadTag` = **7–8** total (`timing/mod.rs:10799-10816`), so the op itself is about 5–6 cycles. | nemu64-test. Manual §4.6.8 COp. | Dirty: `step(40*2)` via `line.writeBack()` (`cpu/interpreter-ipu.cpp:177,204,224,236`). Clean/no-op: 1. | **Ran**: LD+CACHE measured **3** vs expected 7/8 (3 failures × 2 modes). |
| **I-cache line fill** (32 B) | About **43–47** stall. nemu64-test notes that an evicted vector line costs "~43 extra cycles" (`timing/mod.rs:376-379`; a source comment, not an assertion). Manual Table 11-2 gives 1+1+(1–2)+2+M+8+1. With M = 31–32 from the D-fill, that is 45–47 [derived]. The pipeline restarts only after the whole line (§4.6.3). | nemu64-test, manual. | `step(48*2)` (`cpu/cpu.hpp:209`). JIT `emitCpuStep(96)` (`cpu/recompiler.cpp:825`). Total **49**. | Code-derived. No asserting test exists. |
| **Uncached RDRAM read**, 8/16/32-bit | **32** total (VI off, or a bank other than the VI framebuffer's). **36** (same bank as the VI framebuffer, mean 36.3). The same in all eight banks. | nemu64-test `cache.rs:288-382`. systembench U8/U16/U32R = 34, so 32 + about 2 overhead (`main.c:577-579`). n64brew Memory map: CPU "stalled while the RI communicates". | **1** interpreter / **2** recompiler. `MI::readRdram` → `rdram.ram.read` charges nothing (`mi/bus.hpp:2-12`, `rdram/rdram.hpp` `Writable::read`). | **Ran**: "Seen range 1..=1" (interpreter) and "2..=2" (recompiler) against a 32..=93 envelope. All 10 uncached cases fail. |
| Uncached RDRAM read, 64-bit | About **35** (systembench U64R = 37, so 35 + overhead). Two SysAD data beats instead of one [inference: 32-bit SysAD]. | systembench `main.c:580`. | 1 / 2. | Code-derived, plus the ran-uncached result above. |
| Uncached RDRAM reads, 4 back-to-back | **~33 each**. Sequential (+0/+4/+8/+12) and random offsets in one 1 MiB region: 134 per 4. Four different 1 MiB banks: 136 per 4. No visible RDRAM row-miss penalty for the CPU. | systembench `main.c:582-584`, `270-292`. | 1 or 2 each. | Code-derived. systembench was not run (no libdragon toolchain here). |
| Uncached store (RDRAM or RCP), ≤4 in a row | **1** each. The 4-entry write buffer accepts them without stalling. | nemu64-test `UncachedWriteBufferTest` (SB/SH/SW/SD × 1–4, `timing/mod.rs:8617-8661`). Manual §4.9: 4 entries, each up to 64 bits. | 1. Store cost is `DefaultWriteCycles = 0` (`memory/io.hpp:4`), and RDRAM writes have no step (`mi/bus.hpp:84`). | **Ran**: passes (trivially, since there is no cost). |
| Uncached store, 5th and later in a burst / load behind pending stores | Pipeline stalls until an entry frees (manual §4.9). **Drain rate per entry: no measurement found.** nemu64-test drains with a 70-iteration (about 140-cycle) loop for 4 entries (`timing/mod.rs:328-334`). So its author expects ≤ about 35 cycles per entry [weak inference]. MiSTer: one 4-deep FIFO carries *all* CPU bus traffic (stores, writebacks, reads) in order. It blocks at 4 (`rtl/cpu.vhd:807`, `:826-850`). | Manual, MiSTer RTL. | **Not modeled.** There is no queue and no stall, and reads never wait behind stores. | Code-derived. |
| **RCP register read** (VI/PI/SI/AI/SP/DP regs) | About **22** total. systembench `VI_CONTROL` read = 24, minus about 2 overhead (`main.c:586`). | systembench. n64brew Memory map says "5-6 PClock (MI about 2)". **Conflict**: systembench is the better grounded of the two, being an executable measurement with a hardware-expected value. n64brew probably means internal RCP time [inference]. MiSTer floor: 9 RCP (MI 2) plus SysAD overhead (`rtl/memorymux.vhd:351-449`). | 1 + `DefaultReadCycles = 20` = **21** (`memory/io.hpp:3,8`) for every RCP device, MI included. | Code-derived. Within the systembench 1-cycle error. MI and RSP-DMEM differences (MiSTer: MI 2, SP RAM 13) are not measured on hardware. |
| RCP register write | **Not measured.** It goes through the write buffer, so 1 at issue. systembench's `RCP I/O W` (expected 193) is commented out with "FIXME: flush buffer" (`main.c:587`). | systembench, manual §4.9. | 1. `DefaultWriteCycles = 0` (`memory/io.hpp:4,37`). | Code-derived. |
| RDRAM register read (0x03F0'0000+) | No hardware number. MiSTer floor is 15 RCP. | MiSTer `memorymux.vhd:343-350`. | 21 (RCP default, through `rdram.read`) (`mi/bus.hpp:9`). | Code-derived. |
| **PI bus I/O read** (cart ROM, DOM1) | **144 RCP ≈ 216 CPU** including overhead, so about **214 CPU** for the access. It depends on the BSD registers. Retail header `0x80371240` gives LAT=0x40, PWD=0x12, PGS=7, RLS=3. The bus protocol sum is ALE address phase about 14 + (LAT+1) + 2×(PWD+1) + (RLS+1) ≈ 125–130 RCP, plus a SysAD round trip [derived from n64brew PI bus timing, using the gopher64/Dillonb DMA formula with length 4]. | systembench `main.c:594`. n64brew Parallel Interface (LAT/PWD/RLS, ALE ≥ 7/14 cycles), ROM Header. MiSTer: fixed floor 137 RCP (`memorymux.vhd:427-433`). gopher64 uses the BSD formula (`src/device/cart/rom.rs:33`, `pi.rs:172-196`). | 1 + 20 + `step(250*2)` = **271 CPU = 181 RCP**, fixed and independent of BSD (`memory/io.hpp:8`, `pi/bus.hpp:63`). | Code-derived. **About 26 % over** hardware. |
| **PI bus I/O write** | CPU sees 1 (posted). IO_BUSY stays set for **134 RCP**. While it is busy, reads return the latched value and further writes are ignored (n64brew Memory map). | systembench `main.c:595`. n64brew. | 1. `queueInsert(PI_BUS_Write, 400)` = 200 CPU = **133.3 RCP** (`pi/bus.hpp:77`). A read while busy *stalls* for the remainder (`pi/bus.hpp:58-61`). | Code-derived. Busy time matches. The stall-on-read behavior differs from n64brew's description, which says nothing of a stall. |
| SI/PIF RAM read | **1974 RCP ≈ 2961 CPU**. | systembench `main.c:599`. MiSTer floor 1910 RCP. gopher64 3000 CPU (`src/device/pif.rs:36`). | 1 + 20 = **21** (`memory/io.hpp:8`, `si/io.cpp:8`). | Code-derived. About **140× too cheap**. |
| SI/PIF RAM write | Busy for **2158 RCP**. | systembench `main.c:600`. | Busy for 2150 RCP (`si/io.cpp:67`). | Code-derived. Matches. |
| Uncached instruction fetch (KSEG1 code) | Not measured. cen64 charges the same as an uncached load (`MEMORY_WORD_DELAY 38`, `vr4300/fault.h:17`). The uncached-load figure (about 32) is the best proxy [inference]. | cen64. | 1 (`cpu/memory.cpp:163`). | Code-derived. |

## Details

### What nemu64-test measures and how to read "38–103"

`assert_averaged_cycles_with_codegen` (`cache.rs:160-191`) runs the access 1000 times and checks three things:

1. **Envelope.** `soft_assert_range_contained_within_expected` (`soft_asserts.rs:223-236`) requires the *measured* min and max to lie inside the expected range. So `38..=103` (load miss, VI on), `41..=103` (load miss, VI off) and `32..=93` (uncached) are tolerances. They are not observed extremes.
2. **Median** within ±1.
3. **Mean** within an epsilon: ±1.0 VI on, ±0.5 VI off, ±4.0 or ±1.0 uncached.

The cycle unit is a full PClock. COUNT ticks every 2 PClocks, so the harness runs each body twice with a one-instruction phase shift and sums the two readings (`effective_cycles`, `timing/mod.rs:562-568`). It also subtracts the JALR/JR/MFC0 overhead.

The precondition for the miss test loads the same index 8 KiB away. That evicts with a **clean** victim, so the test never exercises writeback.

Reading the numbers:

- **Contention tail.** VI-off mean − median = 1.5. VI-on = 1.25 on top of a median that is 1 higher. That is a light tail: most fills see no conflict, and a few see a long one. The upper envelope is 103 in both cases, so the source is not only the VI. RDRAM refresh (RI_REFRESH, n64brew RDRAM Interface) is the plausible other source [inference].
- **The odd lower bound.** The VI-on lower bound (38) is below the VI-off median (41), which no model explains. It could be a tolerance choice rather than an observation [inference].
- **Bank effect on uncached loads.** In the VI framebuffer's 1 MiB bank: median 36, mean "re-measured (very stably) at ~36.3" (`cache.rs:301-306`). In any other bank: 32. That is a deterministic bank-conflict cost of about 4 cycles, not a random tail. A row-buffer conflict with the VI's open row is the likely mechanism [inference: per-bank RDRAM row state, n64brew RDRAM_Interface `BankValidBits`].
- **Measurement method.** The tests are not stated to be hardware results in the README. But the comments ("re-measured… very stably", unstable measurements "will need to revise") and the sub-integer means read as console measurements [inference].

ares cannot produce any of these effects. RDRAM accesses have no cost model, and the VI is not a bus master in the CPU's timing.

### The +1 on every D-cache hit is the largest single CPU-timing error in this fork

- **The code.** `DataCache::read`/`write` call `cpu.step(1*2)` on a hit (`cpu/dcache.cpp:61,90`), on top of the 1-cycle fetch step (`cpu/memory.cpp:158`). The recompiler mirrors it with `emitCpuStep(2)` in the inline hit path (`cpu/recompiler-ipu.cpp:165-167`). The line dates to invertego's `ffcce5823` ("track cpu clocks at system rate", 2023), which rescaled an older `step(1)`.
- **Hardware disagrees.** Hardware is 1 for every load and store size (nemu64-test, 19 cases). The VR4300 does the cache access in its DC stage without a stall (manual §4.6.6-4.6.7). The only extra cycle is DCB: a store followed immediately by another D-cache access.
- **It cascades into other failures.**
  - It breaks `Data cache Size`. That test expects a 6-instruction loop containing one SW to advance COUNT by exactly 3 per iteration (`cache.rs:47-86`). A 7-cycle loop yields 3/4 alternation [inference from the loop].
  - It explains most load/store register-dependency failures: 170 of 199 failures involve a load or store, and most are exactly +1.
- **Removing it alone is not enough.** The real LDI (+1 on a dependent next instruction, using the n64brew over-approximation rule) and DCB (+1 store-then-memory) are not modeled.

### D-cache dirty miss: three different models, no measurement

| Source | Dirty-miss model |
|---|---|
| NEC manual §11.3.2, §4.9 | Address goes out and the dirty line moves to the write buffer "at the same time". The fill is served (critical doubleword first), then "the data in the write buffer is written to the main memory". The pipeline continues while the write buffer drains. |
| MiSTer `cpu_datacache.vhd:376-383, 488-520` | Writeback first (two 64-bit FIFO entries), then the fill request is queued *behind* them in the single in-order FIFO (`cpu.vhd:826-850`). The fill waits for the writeback. |
| ares | Synchronous 40 + 40 (`dcache.cpp:7,16`). |
| gopher64 | Synchronous `31 + 16/3` = 36, then fill 7 + 4×9 = 43 (`src/device/cache.rs:82,101`; `rdram.rs:175`). |
| cen64 | Writeback is free; fill 44 stall (`vr4300/fault.c:300-316`, `fault.h:15`). |

Which is better grounded:

- The **manual** describes the chip's intent.
- MiSTer is a working reimplementation tuned to pass the test suites. But the suites contain no dirty-miss test, so its ordering is unconstrained by measurement.
- gopher64's `31 + len/3` comes from hcs64's **RSP DMA** rate measurement (hcs64.com/dma.html: "3.7 bytes per cycle… base 41 cycles"). It is borrowed by analogy, not measured on the CPU.

This matters for MM. Every `osWritebackDCache` and `osInvalDCache` path, and every dirty eviction during display-list building, pays it.

### Why a line fill costs about 9 more cycles than a word read

The data:

- An uncached word read: 31 stall cycles (32 − 1).
- A clean D-fill: 40 stall cycles (41 − 1).
- Manual Table 11-1 adds only "2" for transferring the line and restarts on the critical doubleword.

Two readings fit [inference]:

- The RCP returns the 16-byte block only after the whole RDRAM burst arrives, so there is no early restart on N64.
- Or block reads take a slower RI path.

Either way, a model should use measured totals per access type (word / doubleword / 16 B / 32 B) rather than derive fills from a word latency.

The systembench "U32R seq vs rand vs banked" result (134/134/136 per 4) shows the CPU sees no row-hit benefit for adjacent uncached words. So there is no cheap "same-row" fast path to model for CPU uncached reads [inference from the equal seq/rand numbers].

### Write buffer

The manual (§4.9) describes:

- 4 entries, each a 32-bit address, a size and up to 64 bits of data.
- Uncached stores and dirty-line writebacks both go through it.
- The pipeline stalls only when a load or store "requiring external resources" finds it full.

On N64:

- Every RCP register write and every uncached RDRAM write is posted.
- An uncached *read* must wait behind pending writes, since SysAD is in order. MiSTer enforces this with one FIFO [inference from MiSTer RTL and the SysAD protocol, manual §12.7.2 "Processor Write Request Followed by Processor Read Request"].
- The common libultra idiom of writing a register and then reading it back to flush the buffer depends on exactly this.

ares has none of it: `DefaultWriteCycles = 0` with the comment "not implemented until we implement the CPU write queue" (`memory/io.hpp:4`).

Missing numbers needed to model it:

- per-entry drain time for an RDRAM target vs an RCP-register target
- whether one block-writeback occupies 2 entries (as MiSTer stores it) or 4 words' worth

### RCP registers, PI and SI direct I/O

- **RCP register reads.** ares's flat 20 + 1 fits systembench's single measured register (VI) within 1 cycle. The per-device spread is unmeasured on hardware: MI faster per n64brew and MiSTer, SP DMEM/IMEM slower per MiSTer.
- **PI cart reads are the clear error.** ares ignores the BSD registers and charges a constant 270 that is about 56 CPU cycles too slow for retail timings. gopher64 and Dillonb compute the PI time from LAT/PWD/RLS/PGS, which is the protocol-grounded approach (n64brew PI bus pins: "/RD… has the same timing constraints as /WR"; LAT/PWD/RLS are counted in RCP cycles minus one). MM reads the cart directly only rarely (most traffic is PI DMA, see the DMA ticket), so this is low-impact but easy to make exact.
- **PIF RAM direct reads** are about 2960 CPU cycles on hardware and 21 in ares. libultra uses SI DMA for controller I/O, so MM rarely does direct PIF reads [inference; not counted in MM].

## How this was verified here

1. **Ran** nemu64-test `timing.z64`, built from `9a8b9f7` (`nemu64-test/out/timing.z64`), on an ares build of this fork's HEAD `59158c28a`, in both modes:
   - `Developer/ForceInterpreter=true`: **924 / 1604 failed**.
   - recompiler: **1109 / 1604 failed**.
   - The companion doc's 1593 / 1604 was for upstream v148 in Docker, not this fork.
   - The run used `xvfb-run` and finished in about 1 s of emulated test time.
   - Excerpts:
     ```
     Cached loads and store … ("LW (cached)", 1, …) failed: Actual: 2, expected 1.
     Load Miss (with VI disabled) '80400000' failed: Actual: 41.0 but expected: 42.5 (+/- 0.5). Average cycle count
     Load from uncached (with VI disabled) 'a0000000' failed: Seen range 1..=1, which was expected to be within range 32..=93.
     LD $T4; CACHE (DataIndexLoadTag) $V1 … Actual: 3, expected 7.
     ```
   - Recompiler: miss = 42 and uncached = 2.
   - Write-buffer tests pass.
   - The ROM prints the tuple's integer fields in hex: "(true, 24, 36.3)" is median 0x24 = 36.
2. **Read** every cited ares line at `59158c28a`. Code-derived rows add the per-instruction `step(1*2)` and convert from half-cycles.
3. **Read** the NEC VR4300 manual text (extracted with Ghostscript from n64brew's PDF): §4.6, §4.9, §11.3.2-11.3.3 (Tables 11-1/11-2), §12.7, §12.10.
4. **Not run:**
   - n64-systembench: no libdragon toolchain on this host. Its numbers are expected values read from source.
   - Any real console.

## Sources

- NEC VR4300 User's Manual U10504EJ7V0UM00, https://n64brew.dev/wiki/File:VR4300-Users-Manual.pdf. §4.6.3-4.6.8 (ICB, LDI, DCM, DCB, COp), §4.9 (Write Buffer), §11.3.2 Table 11-1, §11.3.3 Table 11-2, §12.7, §12.10.
- n64brew:
  - https://n64brew.dev/wiki/Memory_map: RDRAM/RCP/PI/SI access behavior, the "5-6 PClock" claim, PI/SI posted writes.
  - https://n64brew.dev/wiki/Parallel_Interface: LAT/PWD/RLS/PGS, ALE timing.
  - https://n64brew.dev/wiki/ROM_Header: `0x80371240` → LAT 0x40, PWD 0x12, PGS 7, RLS 3.
  - https://n64brew.dev/wiki/VR4300: load delay interlock rule.
  - https://n64brew.dev/wiki/RDRAM_Interface: refresh, bank valid bits.
- nemu64-test `9a8b9f7`, https://github.com/thelemmy/nemu64-test:
  - `src/tests/timing/cache.rs:24-382`
  - `src/tests/timing/mod.rs:242-347` (harness), `562-568`, `2297-2360`, `8617-8661`, `10799-10816`
  - `src/tests/soft_asserts.rs:223-236`
  - `Cargo.toml:18-29`
- rasky/n64-systembench `845635c`, https://github.com/rasky/n64-systembench: `src/main.c:65-127` (TIMEIT), `163-292`, `571-613` (expected values).
- N64_MiSTer `5725381`: `rtl/memorymux.vhd:280-500` (per-region latency floors), `rtl/cpu.vhd:680-850` (4-deep write FIFO, in-order bus), `rtl/cpu_datacache.vhd:376-520` (writeback-then-fill).
- gopher64 `1ab3793`: `src/device/rdram.rs:44-52,175-177`, `src/device/cache.rs:27-105`, `src/device/pi.rs:172-196`, `src/device/pif.rs:36`, `src/device/cart/rom.rs:27-34`.
- cen64 `e0641c8`: `vr4300/fault.h:15-17`, `vr4300/fault.c:240-390`.
- Dillonb/n64 `fb98289`: `src/common/timing.c:30-45` (PI formula). No CPU memory costs.
- hcs64, "RSP DMA Transfer Rate", https://hcs64.com/dma.html: the origin of gopher64's `31 + len/3`. It measures RSP DMA, not CPU accesses.
- This fork `59158c28a`:
  - `ares/n64/cpu/{memory.cpp:158-193, dcache.cpp:6-20,53-93, cpu.hpp:150-220, recompiler.cpp:735-850, recompiler-ipu.cpp:5-13,149-170, interpreter-ipu.cpp:170-240}`
  - `ares/n64/memory/{io.hpp:1-60, bus.hpp}`
  - `ares/n64/mi/bus.hpp:1-90`
  - `ares/n64/pi/bus.hpp:55-91`
  - `ares/n64/si/io.cpp:1-9,67`
  - commit `ffcce5823`

## New sharp questions

1. **Dirty D-miss.** What do the stall, and the bus occupancy after the restart, cost on hardware? Is the order fill-then-writeback (manual) or writeback-then-fill (MiSTer)? A nemu64-style test with a dirty victim would settle it. No suite has one.
2. **Write buffer.** What is the per-entry drain time (RDRAM vs RCP register vs PI)? What is the stall on the 5th store? How long does an uncached read wait behind N pending stores?
3. **Recompiler slow path.** Why does the recompiler charge +1 over the interpreter on slow-path memory ops (D-miss 42, uncached 2)? Found by measurement. The cause was not traced in `recompiler.cpp:800-840`.
4. **D-cache hit cycle.** Can the +1 hit cycle (`dcache.cpp:61,90`, `recompiler-ipu.cpp:167`) be removed together with adding LDI and DCB? That would turn about 170 timing failures into passes without breaking the miss medians.
