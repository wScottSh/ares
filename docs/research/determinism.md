# Run-to-run determinism in the fork's N64 core

Ticket: [#27 Run-to-run nondeterminism in ares](https://github.com/wScottSh/ares/issues/27). Map: [#1](https://github.com/wScottSh/ares/issues/1) ("Timing is bit-deterministic across runs (no host clock or GPU-thread dependence)").

Source state: `origin/feat/harness` at `c8592d16a`. All file:line references are at that commit unless marked otherwise.

## Answer

- **Entropy is the only host input that changed emulated state in this workload.** With the "Deterministic Entropy" setting off, the core seeds its PRNG from the C `clock()` value at power-on. RDRAM current-calibration then reads different bits during IPL3, and boot takes a different number of cycles. Two entropy-off runs reached the first VI field 157,759 PClock cycles apart, and every state hash differed from that field on. Every other source tested was byte-identical over 3,600 fields.
- **The original 1% South Clock Town noise was most likely this entropy path (inferred).** The desktop default for the setting is off. Majora's Mask seeds its game RNG from `osGetTime()` in `Play_Init`. A boot-time shift therefore gives each run a different game RNG seed, and a scene full of RNG-driven NPCs diverges the most.
- **paraLLEl-RDP is a host-timing dependency in RDRAM contents, but MM never observed it.** With the desktop-like screen thread on, RDRAM snapshots at VI field boundaries differed between two `--rdp vulkan` runs on 506 of 3,600 fields. CPU state, `cpu_cycles` and `rsp_busy_clocks` stayed identical. The probe counted zero CPU, RSP or PI reads of an RDP color or Z target between a draw command and the next SyncFull.
- **The harness's `--rdp vulkan` determinism is partly an artifact of the harness.** The runner hashes the scanout at every field, and `mapScanoutRead` waits on the GPU fence on the emulation thread. That serializes the GPU with the core once per field. The desktop does that wait on its screen thread instead.

## Workload and method

- Workload: Majora's Mask (`Legend of Zelda - Majora's Mask.v64`), boot with no controller input, 3,600 VI fields (60.67 s emulated). In this window MM runs the N64 logo, the title, and its 3D attract sequence. RSP busy time per 60 fields grows from about 0 to 94.8 M clocks after field 1,800 (measured, `long-vk.tsv`). This is not the gameplay scene set of the earlier bench. No input scripting exists yet, so South Clock Town gameplay itself was not reached.
- Runner: `tools/n64-run` from `feat/harness`, plus the measurement-only patch [`determinism/measure.patch`](determinism/measure.patch). The patch is never delivered. It adds:
  - `--entropy on|off`, `--no-runahead`, `--save-dir DIR`, `--state-hash`.
  - With `--state-hash`, three more stats columns per field: `rdram_hash` (hash of all 8 MiB of RDRAM), `cpu_hash` (hash of the 32 GPRs and PC), `pending_reads`.
  - Counters printed on stderr as one `probe:` line. They count each `random()` consumer, cartridge RTC host-time loads, flash reads, paraLLEl commands, SyncFull waits, and reads of the current RDP color or Z image (`target_read_any`). `target_read_pending` counts the subset that happen after a draw command and before the next SyncFull.
  - `N64RUN_FILL=<byte>` fills every `nall::memory::allocate` and `operator new` block with that byte.
- Scripts: [`run.sh`](determinism/run.sh) runs one config. [`cmp.py`](determinism/cmp.py) prints the first differing field per column. [`window.py`](determinism/window.py) prints the per-120-field `rsp_busy_clocks` difference. [`batch1.sh`](determinism/batch1.sh), [`batch2.sh`](determinism/batch2.sh) and [`batch3.sh`](determinism/batch3.sh) are the exact run sets. Batch 1 ran 7 instances at once, batch 2 ran 6, and batch 3 ran 4 next to 12 busy-loop processes on a 12-thread host.
- Reproduce: `git apply docs/research/determinism/measure.patch`, then `N64_BUILD_DIR=... tools/n64-timing/build.sh`. Then run each batch from an empty results directory, and run `python cmp.py A.tsv B.tsv` on each pair.

Every result row below is measured with the named runs, unless the row says cited or inferred.

## Results by source

| Source | Runs | Result (measured) |
|---|---|---|
| Baseline: interpreter, `--rdp none`, entropy on | A1, A2, A3 (A3 under 12 busy loops) | All columns identical on all 3,600 fields. Final `cpu_cycles` 5,687,907,099, `rsp_busy_clocks` 2,972,489,145 |
| Entropy off | B1, B2, plus A1 vs B1 | Differ from field 0. First-field `cpu_cycles`: 48,131,050 (A1), 48,119,218 (B1), 48,276,977 (B2). `rsp_busy_clocks` first differs at field 64 (B1 vs B2). `degrade()` calls: 800 (A), 840 (B1), 880 (B2). Final `rsp_busy_clocks` B1 vs B2 −0.0089%. Per-120-field RSP busy difference: max 0.084%, mean 0.012% (B1 vs B2). Max 0.112% (A1 vs B1) |
| `--rdp vulkan` vs `--rdp none` | long-vk, C2 vs A1 | `cpu_hash`, `cpu_cycles` and `rsp_busy_clocks` identical on all fields. `rdram_hash` differs from field 63, because paraLLEl draws into RDRAM and `none` does not. The CPU and RSP read RDP color or Z targets 1,088 times (`target_read_any`), always after SyncFull (`target_read_pending` = 0) |
| `--rdp vulkan`, two runs, harness mode | long-vk, C2, C3 (C3 under 12 busy loops) | Identical on every column, including `rdram_hash` |
| `--rdp vulkan` with the screen thread on (desktop-like) | G2, G3 | `cpu_hash`, `cpu_cycles` and `rsp_busy_clocks` identical. `rdram_hash` differs on 506 fields (G2 vs G3), first at field 65, and on 768 fields (C2 vs G3). The differing fields are scattered and later fields match again |
| Screen and audio paths on, `--rdp none` | G1 vs A1 | Identical |
| Recompiler, two runs | D1, D2, D3 (D3 under 12 busy loops) | Identical to each other. Not identical to the interpreter: `origin` differs from field 1, `rsp_busy_clocks` +1.33% at field 3,600, max per-120-field difference 4.07%. That is the known recompiler timing gap (#10, #28), not run-to-run noise |
| Host thread scheduling | A3, C3, D3 vs their unloaded twins | Identical. Wall time went from 117 s to 230 s (A) and from 140 s to 498 s (C) with no change in any emulated column |
| Uninitialised heap | F1 (`N64RUN_FILL=0xA5`), F2 (`0x5A`) vs A1 | Identical |
| Save file contents | H1, H2 (two random 128 KiB flash files) vs A1 | Identical. The file was loaded (`flash_word0` = random data vs `ffffffff`). MM made 16 flash reads in 600 fields, and the attract loop never reads save data |
| Cartridge RTC | all runs | `rtc_host_time` = 0. MM has no RTC. Not exercised |
| CP0 Random, SP_PC-while-running, controller-pak format | all runs | 0 calls each. Only the RDRAM `random()` consumers ran |

## Mechanisms and what removing each requires

### 1. Entropy seed (live; changes MM state)

- Setting parsed at `ares/n64/system/system.cpp:38`. Seeded at power-on at `:435-440`. If the setting is on, the seed is 0. Otherwise `Random::seed()` takes `(n64)clock()` (`ares/ares/random.hpp:20-21`), which depends on host time since process start.
- The desktop default is off (`desktop-ui/settings/settings.hpp:110`, cited). The harness forces it on (`tools/n64-run/n64-run.cpp:267`).
- Consumers of `random()` in the core:
  - RDRAM `ccLow`/`ccHigh` at power-on (`ares/n64/rdram/rdram.cpp:43-44`).
  - `RDRAM::Writable::degrade`, one draw per set bit for reads while the chip's current calibration is between the two thresholds (`ares/n64/rdram/rdram.cpp:195-207`).
  - CP0 Random (`ares/n64/cpu/interpreter-scc.cpp:269-272`).
  - SP_PC read while the RSP runs (`ares/n64/rsp/io.cpp:173-177`).
  - Controller pak format (`ares/n64/controller/gamepad/gamepad.cpp:456-458`).
- In MM only the RDRAM consumers ran. 4 calibration draws, then 800 to 880 `degrade` calls. The count differs per seed, because IPL3's calibration loop takes a different path. The first VI field then lands at a different cycle (see the table).
- To remove it, the timing model cannot keep a host-seeded PRNG. Each consumer needs a deterministic model:
  - RDRAM calibration: fixed reference thresholds and a deterministic decay. Real chips vary, so a fixed console is a modelling choice. The value needs a hardware reference. None is known for this note.
  - CP0 Random: a counter that decrements every instruction cycle and wraps from Wired to 31. This is the VR4300 behavior described in NEC's VR4300 manual, Random register section (cited from general knowledge of the manual; the page was not checked here).
  - SP_PC while running: the RSP's real PC at the time of the read.
  - Controller pak: a fixed serial.
- Until then, force the seed to 0 everywhere. That means removing the setting, or defaulting it on in the fork (map: "no toggle").

### 2. paraLLEl-RDP writes RDRAM on host time (live in RDRAM; not observed by MM)

- ares hands paraLLEl `rdram.ram.data` (`ares/n64/vulkan/vulkan.cpp:58`). paraLLEl imports it with `VK_EXT_external_memory_host` when the device supports that (`ares/n64/vulkan/parallel-rdp/parallel-rdp/rdp_device.cpp:81-87`). The GPU then reads and writes emulated RDRAM directly, whenever it executes.
- ares enqueues commands (`vulkan.cpp:142`) and waits for the GPU only at SyncFull (`:146`). A CPU, RSP or PI access to an RDP target between a draw and SyncFull sees whatever the GPU has finished at that host instant. The same applies to hidden RDRAM (`:70`).
- Measured: in desktop-like mode (G2 vs G3), RDRAM at the same emulated instant differed on 506 fields. MM's title sequence makes 1,088 target reads, all after SyncFull, so its state did not diverge. MM's sun and light-glow Z reads (`Environment_GraphCallback`, `src/code/z_kankyo.c:532-536` in zeldaret/mm at `56fa21dd`, cited) run in `Graph_TaskSet00` after the game waits for the previous graphics task to finish (`src/code/graph.c:156`, `:184-185`, cited). On ares that is after SyncFull, so this read is deterministic (inferred).
- Separate hazard: under `--rdp none` the RDP never writes the Z buffer. Those same MM Z reads then see different data than on hardware. That is an accuracy gap, not nondeterminism.
- To remove it: a CPU-side RDP that writes RDRAM in emulated time (the RDP-engine unit). Alternatively, a barrier that blocks on the GPU before any non-RDP access to an address the RDP may still write. The second still leaves rendered pixels dependent on the host GPU and driver.

### 3. Desktop screen thread (harmless to state)

- On the desktop, N64 run-ahead is forced off (`desktop-ui/program/utility.cpp:37`). `Screen::frame` therefore hands `VI::refresh` to the screen thread (`ares/ares/node/video/screen.cpp:15`, `:215-228`). That thread reads RDRAM through `rdram.ram.read` (`ares/n64/vi/vi.cpp:200`, `:218`). In homebrew mode this updates `rdram.profile.metrics` and the debugger's `lastReadCacheline` from the screen thread.
- Neither of those feeds emulated timing. G1 and G2 matched A1 and C2 on every timing and CPU column (measured). The profile counters that emux `XPROFREAD` reports are racy on the desktop (inferred from code). A bench that reports RDRAM metrics would see noise from this.
- To remove it: keep VI scanout on the emulation thread, as the harness does.

### 4. Recompiler (deterministic, but not equal to the interpreter)

- D1, D2 and D3 were identical even under load. The difference from the interpreter is a timing-model gap (+1.33% RSP busy over 3,600 fields), covered by #10 and #28. No host dependence was found.

### 5. Host thread scheduling and libco

- The N64 core uses no cothreads. Its devices are counters driven from `CPU::synchronize` (grounding doc, section 1). The only host threads are the screen thread, the audio stream, and paraLLEl's workers. Loaded runs matched unloaded runs (A3, C3, D3).

### 6. Audio and video drivers

- The runner attaches no host drivers. With run-ahead off, the core's screen and audio-stream code paths ran (G1) with no change in state. Desktop drivers (`OpenGL 3.2`, `WASAPI` with blocking audio in `C:/Users/Scott/Desktop/ares-v148/settings.bml`) only pace wall time. The core reads no wall time outside the RTC and bio-sensor sites below (inferred from the grep in the grounding doc, section 7, and from this ticket's code search).
- Host input is a host input. Any key or pad event that reaches the emulated controller during a bench changes state (inferred). Not tested.

### 7. Wall clock and RTC

- Cartridge RTC: on load, a fresh RTC is set from `time(0)`/`localtime`. A saved one advances by `now - saved` (`ares/n64/cartridge/rtc.cpp:11-28`). Save writes `time(0)` (`:33`). The 64DD RTC does the same (`ares/n64/dd/rtc.cpp:14-15`, `:32`, `:45`). The bio sensor uses `chrono::microsecond()` (`ares/n64/controller/gamepad/bio-sensor.cpp:3`, `:16`).
- mia enables the RTC only for Doubutsu no Mori (`NAF`) in its database. MM was not affected (`rtc_host_time` = 0). No RTC ROM was available, so this path was not measured.
- To remove it: in the timing model, start the RTC from a fixed epoch or a value given on the command line, and never advance it by host time between sessions. Drive the bio-sensor pulse from emulated time.

### 8. Uninitialised memory

- Core memories are filled on allocation (`ares/n64/memory/lsb/writable.hpp:25-32`). Save memories start at 0xff (`mia/pak/pak.cpp:139`). Device globals have static storage, so their members start at zero.
- Heap fill 0xA5 vs 0x5A changed nothing (F1, F2). Stack-uninitialised reads were not tested.

### 9. Save files

- `save.flash`, `save.eeprom` and similar files load from the host at power-on (`ares/n64/cartridge/cartridge.cpp:43-46`) and are written back on unload. The harness points saves at an unused directory. MM's attract loop does not depend on the contents (H1, H2).
- A gameplay bench that boots into a file depends on the save. If a run writes flash (owl save, Song of Time), the next run starts from a different file (inferred). To remove it, the bench must load a fixed save image and never write it back. The harness already never writes.

## The original 1% South Clock Town noise

Source: `docs/research/recompiler-parity.md` on `origin/research/recompiler-parity`, section 2 (cited). Two identical interpreter runs (B and B2) of the desktop `ares` binary differed by 1.0% `game_ticks` in South Clock Town and by 0.0008% in Mountain Village. `ic_miss` also differed (2,520,561 vs 2,513,496), so the game ran different code, not only different timing.

Most likely cause (inferred, not reproduced on that bench):

1. The bench ran the desktop binary. Its documented command sets no entropy option, and the desktop default is off (`settings.hpp:110`). The only local desktop settings file found, `C:/Users/Scott/Desktop/ares-v148/settings.bml`, has no `DeterministicEntropy` key. That is a stock v148 install, not necessarily the bench's build.
2. With entropy off, boot length varies by up to about 158 k PClock cycles between runs (measured, B1 vs B2).
3. MM seeds its game RNG with `Rand_Seed(osGetTime())` in `Play_Init` (`src/code/z_play.c:2260`, zeldaret/mm at `56fa21dd`, cited). `osGetTime` reads COUNT, so a boot shift changes the seed.
4. Scenes whose cost depends on RNG-driven actors diverge in proportion to how much RNG they consume. South Clock Town is full of wandering NPCs. Mountain Village has few. That matches 1.0% vs 0.0008%.

Ruled out on this workload (measured): host load, the screen thread, heap contents, save contents, RTC, and recompiler nondeterminism. paraLLEl's RDRAM race is real, but MM's Z reads happen after the graphics task ends, so it is the less likely cause (inferred).

To confirm: rerun the four-scene bench twice on the desktop binary with "Deterministic Entropy" on. If B and B2 then match exactly, the entropy path is confirmed. Or run the harness on the bench ROM with `--entropy off` twice and compare `game_ticks`. Input scripting or the bench ROM's scene warp is needed for that.

## Open questions

- Gameplay coverage. The workload never reached gameplay, so the RNG link from boot shift to game state is inferred from decomp source, not observed. The MM bench unit should run the pair above.
- Hardware references for RDRAM calibration thresholds and decay, CP0 Random stepping, and SP_PC reads while running. These are needed before the PRNG can be removed rather than pinned.
- Whether the paraLLEl race is observed by any other game. A game that reads a color or Z target before SyncFull would diverge run to run on the desktop. The `target_read_pending` probe can screen ROMs for this.
