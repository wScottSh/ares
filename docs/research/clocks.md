# NUS-001 (NTSC) clock frequencies

Ticket: wScottSh/ares#24 (map #1). Target: NTSC NUS-001 + Expansion Pak.

## TL;DR

- Two crystals. **X1 = 315/22 MHz = 14.318182 MHz** (4 x NTSC colorburst) feeds the AV clocks; **X2 = 250/17 MHz = 14.705882 MHz** feeds everything else. Each goes into a Macronix PLL synthesizer (MX8330MC / MX9911MC at U7+U15 on early boards, single MX8350 at U17 on late boards) with a fixed x17 multiplier. [n64brew Clock_Timing]
- **RDRAM channel clock RCLK = X2 x 17 = 250 MHz exactly** (tCycle = 4 ns, data on both edges = 500 MT/s on a 9-bit bus). **RCP clock (MasterClock) = RCLK / 4 = 62.5 MHz.** **VR4300 PClock = MasterClock x 3/2 = 93.75 MHz** (DivMode -> Config.EC = 0b111 = 1:1.5). **COUNT = PClock / 2 = 46.875 MHz** = OS_CPU_COUNTER.
- **VCLK = X1 x 17 / 5 = 48.681818 MHz** (VI clock; one VCLK = 1/4 pixel; AI sample/bit clocks divide it). It is *asynchronous* to the 62.5 MHz domain (different crystal, ratio irrational for modelling purposes: 48.681818/62.5 = 0.778909...).
- **62.5 MHz is correct; 60.85 MHz is an SDK documentation artifact.** 60.85 MHz = 14.318182 x 17 / 4 = 60.852 MHz exactly, i.e. what the RCP would run at if RCLK were synthesized from the colorburst crystal (X1) instead of X2 (inference: an early/pre-production clock plan). Survives in the osDpGetCounters man page and in the ROM-header "clock rate" field (0x03A07F5F) of some 2.0D-2.0I games; never the retail hardware rate.
- **ares**: master tick = 187.5 MHz = 2 x PClock = 3 x RCP (`ares/n64/system/system.hpp:37`). CPU = 2 ticks, RCP = 3 ticks, COUNT = tick/4, VCLK converted with a 48'681'818 rational accumulator. All nominal ratios match hardware. Gaps: AI rate integer-truncated, no MPAL, libultra uses a different (rounded) VCLK constant than ares.

## Clock table (NTSC NUS-001)

| Clock | Frequency (exact) | Derivation | References | ares today (file:line) |
|---|---|---|---|---|
| X1 crystal | 315/22 MHz = 14.318181818 MHz | 4 x f_SC; f_SC = 455/2 x f_H, f_H = 2.25 MHz/143 | n64brew Clock_Timing (X1 table, CCIR Rep. 624-4) | not modelled (only VCLK) |
| FSC (colorburst) | 315/88 MHz = 3.579545 MHz | X1 / 4 | n64brew Clock_Timing | not modelled |
| VCLK (VI clock) | 315/22 x 17/5 = 48.681818182 MHz | X1 x 17 / 5 (FSEL=high -> x17) on U7/U17 FSO/5 or VCLK pin | n64brew Clock_Timing (MX8330/MX8350 datasheets); MiSTer `N64.sv:252` VCLK_DSM_NTSC "48.6818181818 MHz"; MiSTer `rtl/pll2.v:72` 48.68 | `system.hpp:38`, `system.cpp:101,109` = 48'681'818; used by `vi/vi.cpp:10-14` (fractional conversion) |
| Pixel rate | VCLK/4 = 12.170 Mpix/s | VI_H_TOTAL is in 1/4-pixel units = VCLK cycles | n64brew Video_Interface (H_TOTAL, "roughly 12.3 megapixels/sec") | `vi/vi.cpp:120-123` steps (H_TOTAL+1) VCLKs per line |
| NTSC line rate | VCLK / 3094 = 15734.27 Hz | H_TOTAL=3093 -> 3094 VCLK = 227.5 f_SC x 13.6 | n64brew Video_Interface | derived |
| Field rate | VCLK / (3094 x 262) = 60.0544 Hz progressive (V_TOTAL 524); /(3094 x 262.5) = 59.9401 Hz interlaced | VI_V_TOTAL | arithmetic from above | `vi/vi.cpp:123` (refresh hint hardcoded 60, `vi/vi.cpp:30`) |
| AI sample rate | VCLK / (DACRATE+1) | e.g. 32 kHz request -> DACRATE 1520 -> 32006.46 Hz | n64brew Audio_Interface (AI_DACRATE, AI_BITRATE: VCLK/2/(BITRATE+1)); libultra `src/libultra/io/aisetfreq.c:5-19` | `ai/io.cpp:61-62`: integer freq then integer period -> 32007.51 Hz for the same case (+1.05 Hz, +33 ppm) |
| AI bit clock | VCLK / 2 / (BITRATE+1) | | n64brew Audio_Interface | not modelled |
| X2 crystal | 250/17 MHz = 14.705882 MHz | chosen so x17 = 250 MHz | n64brew Clock_Timing (MX8350 datasheet: RCLK 250 MHz, x17) | not modelled |
| RCLK (RDRAM channel) | 250 MHz; tCycle 4.000 ns; 500 MT/s x 9 bit | X2 x 17 (RSL output FSO / RCLK pin) | n64brew Clock_Timing; SDK Programming Manual ch. 3-07 "RDRAM - 250 MHz (9 bit bytes at 500 M/sec)"; Toshiba RDRAM datasheet tCYCLE min 4 ns; n64brew RDRAM ("TCycle 4 = RCP Cycle 1") | not modelled as a clock; RDRAM timing expressed in RCP/master ticks |
| MasterClock / RCP / RSP / RDP / DPC_CLOCK | 62.5 MHz | RCLK / 4 (RCP-internal); fed to CPU as MasterClock | n64brew Clock_Timing, SysAD_Interface, RDP Interface (DPC_CLOCK "62.5 Mhz on standard N64"); SDK pro-man ch.3 "RCP - 62.5 MHz"; libultra `include/PR/os_convert.h:6` OS_CLOCK_RATE 62500000; libdragon `n64sys.h:47`; MiSTer `rtl/pll.v:75` clk_1x 62.5 | RSP 3 ticks/cycle `rsp/rsp.hpp:214,221`; RDP `rdp/rdp.cpp:30-34` (clocks/3), DPC_CLOCK read `rdp/io.cpp:41`; RSP DMA `rsp/dma.cpp:20` (x3) |
| SysAD / SClock / TClock | 62.5 MHz | = MasterClock (VR4300 SClock = TClock = MasterClock) | VR4300 UM sec. 1 (Clock Generator), n64brew SysAD_Interface | implicit (bus costs in RCP units x3) |
| VR4300 PClock | 93.75 MHz | MasterClock x 1.5 (DivMode pins; Config.EC = 0b111 -> 1:1.5) | VR4300 UM Table 1-1 & Config EC field; n64brew VR4300; SDK pro-man "CPU - 93.75 MHz"; libdragon `n64sys.h:52`; MiSTer `rtl/pll.v:84` clk_93 | `system.hpp:37` (93'750'000*2), CPU step 2 ticks `cpu/cpu.cpp:140,148,153`; EC=7 `cpu/cpu.hpp:665`, read `cpu/interpreter-scc.cpp:95` |
| COP0 COUNT | 46.875 MHz | PClock / 2 ("incrementing at a constant rate - half the PClock speed") | VR4300 UM 6.3.3; libultra `os_convert.h:7` OS_CPU_COUNTER = 62.5M*3/4; libdragon TICKS_PER_SECOND = CPU_FREQUENCY/2 (`n64sys.h:233`); MiSTer `rtl/cpu_cop0.vhd:622,390` (33-bit counter on clk93, read bits 32:1) | `cpu/cpu.hpp:42-43,609` (33-bit half-count from tick>>1), read `cpu/interpreter-scc.cpp:39` (>>1) -> tick/4 |
| SI clock | 15.625 MHz | MasterClock / 4 | n64brew Clock_Timing | SI costs in RCP cycles x3 (`si/io.cpp:67,87,104`) - no separate clock |
| PIF / cartridge clock | 1.953125 MHz | SI / 8 | n64brew Clock_Timing | not modelled as clock |
| PI | no separate clock | PI bus timing is in RCP cycles via PI_BSD_DOMx registers | n64brew Peripheral_Interface | RCP x3 |
| Expansion Pak | 250 MHz channel | same Rambus channel/RCLK as on-board RDRAM (no separate clock source) | n64brew RDRAM; inference from single RCLK source on the board | n/a |

Fixed ratios that hold regardless of crystal tolerance (all derived from X2): PClock : RCP : COUNT : RCLK = 3/2 : 1 : 3/4 : 4. The only free ratio is X1/X2 (VCLK vs everything else); each crystal is +-30 ppm grade (n64brew, KDS AT-49), so the VI/AI-vs-CPU ratio on a specific console can deviate by up to ~60 ppm from nominal.

Useful exact constants: COUNT ticks per progressive NTSC field = 46.875e6 / 60.0544 = 780541.67; RCP cycles per VCLK = 62.5 / 48.681818 = 1.28385; master (187.5 MHz) ticks per VCLK = 3.85155.

## Conflicts and judgements

1. **RCP 62.5 MHz vs 60.85 MHz.** Judged: **62.5 MHz.**
   - For 62.5: SDK Programming Manual ch. 3 hardware table (CPU 93.75 / RDRAM 250 / RCP 62.5); libultra OS_CLOCK_RATE 62500000 (MM decomp `include/PR/os_convert.h:6`); MX8350 datasheet RCLK = 250 MHz (n64brew); n64brew DPC_CLOCK page; libdragon and MiSTer (which must match hardware cycle-for-cycle to pass timing tests) use 62.5 / 93.75.
   - Hardware ratio evidence: nemu64-test "RSP Timing: Clock CPU vs RDP" (`nemu64-test/src/tests/rsp_timing/mod.rs:48-49`) expects DPC_CLOCK delta = COUNT delta x 4/3 (+-20 per 133333). That confirms RCP = 2/3 PClock = 4/3 COUNT but is crystal-independent, so it does not by itself pin the absolute value.
   - For 60.85: osDpGetCounters man page ("For NTSC systems, this counter increments at 60.85 Mhz ... approximately 16.43 nanoseconds"; 1/60.85 MHz = 16.43 ns, internally consistent); ROM-header word 0x04 = 0x03A07F5F in Star Fox 64, Doom 64, Shadows of the Empire, Quake 64, New Tetris, Episode I Racer (libultra 2.0D-2.0I; masked value 0x03A07F50 = 60,850,000), vs 0x03B9ACAF (62,500,000) in Cruis'n USA / NBA Hangtime (n64brew ROM_Header).
   - Where 60.85 comes from (inference, labelled): 14.318182 MHz x 17 / 4 = **60.8523 MHz** exactly - the RCP rate you get if RCLK is synthesized from the NTSC colorburst crystal (X1) with the same x17 PLL. The retail board instead has a dedicated X2 (250/17 MHz) to hit exactly 250 MHz. Likely an earlier clock plan / dev-hardware figure that stuck in docs and in makerom's default. Note the patent family (US6166748 etc.) describes the bus "on the order of 240 MHz", consistent with a pre-final RCLK in the 243 MHz range. No retail-board source shows 60.85.
   - Effect of the header value: only old libultra (<=2.0I) reads it into osClockRate (x3/4); real clocks never change (MM decomp `include/rom_header.h:39`). MM writes 0xF (`src/makerom/rom_header.s:5`) and its libultra initializes osClockRate = 62.5M constant (`src/libultra/os/initialize.c:15,60`) -> 46.875 MHz.
2. **VCLK constant: 48,681,818 (hardware/ares/MiSTer) vs 48,681,812 (libultra `VI_NTSC_CLOCK`, `include/PR/rcp.h:540`).** Judged: hardware nominal is 48,681,818.18 Hz. libultra's 48,681,812 = 14.31818 MHz (crystal rounded to 7 digits) x 17/5; likewise VI_MPAL_CLOCK 48,628,316 = 14.302446 x 17/5 (true 48,628,321.7). Libultra's value only affects DACRATE rounding in `osAiSetFrequency` (`src/libultra/io/aisetfreq.c:5`); -0.12 ppm, never changes the chosen integer DACRATE for normal rates. ares should keep 48,681,818 for VCLK but must not "correct" game-computed DACRATEs.
3. **VR4300 DivMode encoding.** n64brew Clock_Timing gives DivMode 0b01 = 1:1.5; the NEC VR4300 UM gives the Config.EC readback for mPD30200-100 as 0b111 = 1:1.5 and lists 1:1.5 as the 100 MHz-model ratio. Both agree on 1:1.5 for the N64; only the pin encoding text differs. Not timing-relevant. ares EC = 7 (`cpu/cpu.hpp:665`) matches the UM.
4. **Board revisions.** Clock generator part changes across NUS-CPU revisions (MX8330MC at U7 and U15 on NUS-CPU-01/-03/-04 per Console5 IC list and the NUS-CPU-03/04 schematic; MX9911MC substituted at U7 on later boards - it lacks the RSL FSO output so it can only serve the AV synthesizer; late "Funtastic"-era boards merge both into one MX8350 at U17). Frequencies are identical across all revisions: same x17 multiplier, same X1/X2 nominal values; the MX8350 hard-wires x17 for RCLK regardless of NTSC/PAL pin. No source found reporting a revision with different clock ratios. Exact revision -> part mapping for NUS-CPU-05..09 is not documented in the sources consulted (n64brew phrases it only as "early" vs "later"/"Funtastic-era").
5. **Clock-domain model.** ares and most emulators treat VI as an exact rational of the CPU clock; on hardware VCLK is from a separate crystal and drifts independently (+-30 ppm each). Nominal is the right deterministic choice; just note no VI/CPU phase relationship is fixed at power-on (inference from separate crystals; not measured here).

## ares implementation notes (master tick = 187.5 MHz)

- `ares/n64/system/system.hpp:37` `frequency = 93'750'000 * 2` (187.5 MHz master tick). `system.hpp:38` / `system.cpp:101,109` videoFrequency 48'681'818 NTSC, `system.cpp:113` 49'656'530 PAL. No MPAL (48,628,322) path.
- CPU: 1 PClock = 2 ticks (`cpu/cpu.cpp:140,148,153`, `cpu/dcache.cpp`, `cpu/memory.cpp:158`). COUNT: half-count accumulates tick>>1 (`cpu/cpu.cpp:72,120`, `cpu/cpu.hpp:42-43`), read >>1 (`cpu/interpreter-scc.cpp:39`), write <<1 (`:173`) - matches hardware half-cycle behaviour tested by nemu64-test "Timing: Half cycle calibration" (`nemu64-test/src/tests/timing/mod.rs:164-168`).
- RCP: 1 cycle = 3 ticks (`rsp/rsp.hpp:214,221`, `rsp/dma.cpp:20,67`, `si/io.cpp:67,87,104`, `rdp/rdp.cpp:30-34`).
- VI: `vi/vi.cpp:10-14` converts VCLK -> ticks with exact remainder (no drift).
- AI: `ai/io.cpp:61-62` `dac.frequency = videoFrequency/(dacRate+1)` (integer) then `period = 187.5M / frequency` (integer) - double truncation, ~+33 ppm sample-rate error at 32 kHz; should be a rational VCLK accumulator like VI. Power-on default 44100 (`ai/ai.cpp:76-78`).
- Hardcoded 187.5 MHz constants: `cpu/cpu.cpp:45,52` (GDB poll), `cartridge/rtc.cpp:46` (1 s RTC tick).

## Sources

- n64brew wiki: Clock_Timing (X1/X2, MX8330MC/MX9911MC/MX8350, RCLK/MClock/CPU/SI/PIF table, DivMode), Video_Interface (H_TOTAL derivation), Audio_Interface (DACRATE/BITRATE), Reality_Display_Processor_Interface (DPC_CLOCK 62.5 MHz), SysAD_Interface, VR4300, RDRAM, ROM_Header (clock-rate field table). Local copies: scratchpad `n64brew/`, `webresearch3/ROM_Header.txt`. https://n64brew.dev/wiki/Clock_Timing
- Datasheets via n64brew: Macronix MX8330MC, MX9911MC, MX8350 (Console5 / datasheetarchive mirrors); KDS AT-49 crystal (+-30 ppm).
- NEC VR4300 User's Manual U10504EJ7V0UM00: Table 1-1 (1:1.5), Config.EC, 6.3.3 Count register "half the PClock speed".
- Nintendo 64 SDK: Programming Manual ch. 3 (pro-man 03-07: CPU 93.75, RDRAM 250, RCP 62.5); N64 Introductory Manual step 1-2-2 (93.75 MHz); osDpGetCounters man page (60.85 MHz). https://ultra64.ca/files/documentation/online-manuals/man/n64man/os/osDpGetCounters.html
- Toshiba RDRAM datasheet (tCYCLE 4 ns min); MPR "Rambus Channel Provides 500 Mbyte/s Memory Interface".
- Console5 tech wiki Nintendo 64 IC list (NUS-CPU-01 / NUS-CPU(P)-01: U7 and U15 MX8330); NUS-CPU-03/04 schematic (Console5); bitbuilt region-switch guide (NUS-CPU-03 MX8330 at U7, FSEL pin 7).
- MM decomp (~/repos/mm-decomp-60fps): `include/PR/os_convert.h:6-7`, `include/PR/rcp.h:540-542`, `src/libultra/os/initialize.c:15-16,60-71`, `src/libultra/io/aisetfreq.c:5-19`, `include/rom_header.h:39`, `src/makerom/rom_header.s:5`.
- libdragon `include/n64sys.h:47,52,233`; n64-systembench `src/main.c:8-15` (xcycle = RCP x9 = CPU x6 = COP0 x12).
- N64_MiSTer: `rtl/pll.v:75,84` (62.5 / 93.75 MHz), `rtl/pll2.v:72` + `N64.sv:252-253` (VCLK 48.6818181818 / 49.65653 MHz), `rtl/cpu_cop0.vhd:390,622`.
- nemu64-test (thelemmy, 9a8b9f7): `src/tests/rsp_timing/mod.rs:48-49` (DPC_CLOCK/COUNT = 4/3), `src/tests/timing/mod.rs:164` (half-cycle calibration).
- US patent 6,166,748 family (Nintendo/SGI) - "on the order of 240 MHz" bus, single "clock generator 136 ... controlled by a crystal 148".
- ares (wScottSh/ares master @ 59158c28a): files cited inline above.
