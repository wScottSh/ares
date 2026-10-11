# Run the calibration kit on a console

This guide takes you through one calibration session (#16) on an N64. You run each kit ROM from a flashcart, capture the log it prints, and run one command that stores the capture and puts the console's values into the spec. [inventory.md](inventory.md) lists every question the session answers, the spec rows and checks each answer closes, and the items that no console run can decide, with the reason for each.

## Before you start

You need:

- An NTSC retail NUS-001 console with an Expansion Pak. The kit ROMs use RDRAM above 4 MiB, so they do not run without the Pak.
- One standard controller in port 1, with nothing in its accessory slot. Remove every Controller Pak, Rumble Pak and Transfer Pak. The `kit-dma` ROM reads which ports answer and which report an accessory, and ingestion refuses a capture with an accessory, because the fork's runs have none.
- Three more controllers, only for the second `kit-dma` run (see [kit-dma with four controllers](#kit-dma-with-four-controllers)). Every other ROM runs with one. If you have only one controller, skip that run: `joybus-pads` is then decided for one controller only, and the 2J-4J joybus fit stays open.
- A flashcart. Use one of these:
  - SummerCart64 (SC64), with `sc64deployer` on a PC and a USB cable. This is the best path: the log arrives over USB as the ROM runs, and the PC can read the SRAM copy back.
  - EverDrive-64 X7 (ED64). The log is in the cartridge SRAM, and the ED64 writes it to the SD card.
- A TV or capture device. A phone camera is the last fallback, for short logs only (see [Photo fallback](#photo-fallback)).
- On the PC, a checkout of this repository with the runner built (`tools/n64-timing/build.sh`), and the boot stub below.

### The boot stub

Every kit ROM boots through libdragon's public-domain `ipl3_compat.z64`, signed for CIC 6102. The kit was verified with one exact file, and `romgen/build.py` refuses any other for a console build:

- libdragon commit `e356bf3f56f7afbf7e5246329562f145965cfdfc`, file `boot/bin/ipl3_compat.z64`
- sha256 `f522db2e31a701f82597f399e76d55c9487760d015aff9d90176b463ae39a068`

To get it:

```sh
git clone https://github.com/DragonMinded/libdragon "$N64_TIMING_HOME/scratch/r29/clones/libdragon"
git -C "$N64_TIMING_HOME/scratch/r29/clones/libdragon" checkout e356bf3f56f7afbf7e5246329562f145965cfdfc
sha256sum "$N64_TIMING_HOME/scratch/r29/clones/libdragon/boot/bin/ipl3_compat.z64"
```

That path is the default `romgen/build.py --ipl3` reads. The file is not committed to this repository.

Allow about six hours and 35 minutes for the required runs and seven hours and 35 minutes for the recommended ones (inferred from the per-run times below, at about three minutes for each power cycle, load and copy; `kit-zread` adds one run to the six and a half hours estimated before it; no console session has been timed). About four and a half of those hours are the layout-pad builds (see [Layout pads](#layout-pads)), and you can run them in a later session. Each kit ROM runs for a few seconds after it boots (the table in [Run the kit](#run-the-kit) has the times). Most of the time is power cycles, loading ROMs and copying files.

## Build the kit

1. On the PC, run:

   ```sh
   tools/n64-timing/calibration/run.sh
   ```

   This builds every kit ROM at 8 layout pads and runs each one on the fork: the walked kit ROMs at 8 boot delays per pad, `kit-dma` also with four controllers, the romgen Thar0 port, n64-systembench when its ROM is built (see n64-systembench under [External ROMs](#external-roms); without it `hw:systembench` reads `missing`), and the Majora's Mask BENCH ROMs, which it requires (see Majora's Mask bench under [External ROMs](#external-roms)). That run is the model side of each comparison. It writes `$N64_TIMING_HOME/results/calib/` and takes about five minutes on a loaded 32-core host (inferred; the run was not re-timed for this page). It fails if any ROM's cartridge SRAM copy differs from its ISViewer copy, if a ROM left the PI domain-1 timing changed, or if any wait gave up (see [A hang](#a-hang)).

2. Copy the console builds to the flashcart's SD card:

   - `$N64_TIMING_HOME/results/calib/roms/boot-1/*.z64`: the walked kit ROMs, one build each (`kit-cpu`, `kit-cpu2`, `kit-vi`, `kit-dma`, `kit-bus`, `kit-hpos`, `kit-rdp`, `kit-span`, `kit-span2`, `kit-tex`, `kit-zmem`, `kit-zread`, `kit-noise`, `kit-noise2`).
   - `$N64_TIMING_HOME/results/calib/roms/single/*.z64`: `rdpstat-1prim`, `rdpstat-dpc`, `rdpstat-systemtest`, `rdpstat-unsynced`, `nemu64-timing`, `nemu64-cycle`, `nemu64-cop0hazard`, `cpu-llsc`, `kit-pif`. Run `kit-pif` only through the SC64 `upload` path (see [The PIF boot timeout](#the-pif-boot-timeout)).
   - For the layout-pad runs, `$N64_TIMING_HOME/results/calib/roms/p<P>/boot-1/<rom>.z64` for P = 1 to 7, for each ROM whose Layout pads column in the [Order](#order) table reads `0-7`. Rename each to `<rom>-p<P>.z64` (for example `kit-cpu-p3.z64`), because the menu shows file names only. The log's first line names the pad (`build=p3/boot-1`), so the capture's file name does not matter to ingestion.
   - For the recommended phase runs, also `roms/boot-<K>/kit-cpu.z64`, `kit-dma.z64` and `kit-vi.z64` for the other seven delays K (165, 329, 493, 657, 821, 985, 1149). Rename each to `kit-cpu-<K>.z64` and so on, because the menu shows file names only.

   Each ROM prints a first line `#kit rom=<id> sha=<commit> rom_sha256=<hash> fmt=1 build=<boot-K or single>`, with `p<P>/` before the build for layout pad P. `sha` is the commit you built from. `rom_sha256` identifies the ROM's bytes: it is the SHA-256 of the `.z64` file with the `sha` and `rom_sha256` values set to zeros (`romgen/hwout.py`), so a later commit that does not change the kit gives the same value. The zeroed fields keep their length, so a `sha` of another length moves the code after it and changes the value. A build from a tree with uncommitted changes under `tools/n64-timing` (`sha` ends in `-dirty`) or from outside a git checkout (`sha=unknown`) does not match a clean build of the same commit. Build the console ROMs and the fork's model run from clean checkouts of the same commit. Ingestion compares each log's `rom_sha256` with the fork's run of the same build and refuses the capture if they differ. Copy the ROMs from the same `run.sh` output that ingestion uses. If you run `run.sh` again after a change to the kit, copy the ROMs again.

## Set up the flashcart

### SummerCart64

1. Connect the SC64 to the PC with USB. Check that `sc64deployer list` shows it.
2. Load each ROM from the PC with SRAM as its save type, then start the debug listener. Do this before you turn the console on:

   ```sh
   sc64deployer upload --save-type sram roms/boot-1/kit-cpu.z64
   sc64deployer debug --isv 0x03FF0000 | tee capture/kit-cpu.isviewer.log
   ```

   The kit ROMs write their log through the ISViewer protocol at cartridge address 0x13FF0000, which is SC64 ROM offset 0x03FF0000. The CIC is detected from the ROM's IPL3 (6102). If your `sc64deployer` version names the options differently, run `sc64deployer upload --help` and `sc64deployer debug --help`. You need the save type SRAM 256 Kbit, CIC 6102 and IS-Viewer at 0x03FF0000.
3. After a ROM finishes, read its SRAM copy back as a second capture:

   ```sh
   sc64deployer download save capture/kit-cpu.srm
   ```

   If you use the SC64 menu (N64FlashcartMenu) from the SD card instead of `upload`, set the save type to SRAM 32 KiB in the ROM's settings. The menu path does not enable the IS-Viewer, so only the SRAM copy and the screen are captured. `kit-pif` needs `upload`: it measures the PIF's boot timeout, which a menu launch has already ended.

### EverDrive-64 X7

1. Copy the ROMs to the SD card.
2. In the ED64 menu, check that the save type for each kit ROM is SRAM 32K. The ROM header declares it through the ED64 homebrew header (bytes 0x3C-0x3F: `ED`, save type 3). If your OS version ignores the header, set the save type by hand.
3. The log is written to SRAM as the ROM runs. Each kit ROM first clears all 32 KiB of SRAM, so no older save's bytes follow the log. The ED64 copies SRAM to the SD card when you press Reset and return to the menu. On OS 3.x the save is in `ED64/gamedata/`. Confirm the folder on the first ROM before you run the others.
4. The ED64 path has no USB log. A capture is complete when its SRAM save holds the `#kit-end` line.

## Run the kit

### Power cycles

Each kit ROM is compared with the fork's run from power-on. A Reset is a warm boot: COUNT, the RDRAM refresh, the RI, the VI and the RDP noise state are not at their power-on values. So:

- Turn the console off and on before every ROM. Wait 5 seconds while it is off.
- On the ED64, press Reset first (it writes SRAM to the SD card only then), return to the menu, and then turn the console off. On the SC64 with `upload`, turn the console off, upload the next ROM, start the listener and turn it on.
- The one exception is the reset run in step 3 of [Repeat runs](#repeat-runs), once for each layout pad. Those are the only captures taken after Reset.

### Order

Run the ROMs in this order. The times are the fork's emulated time from boot to the `#kit-end` line. The console's time is the same to within its boot time. Every log fits the 32 KiB SRAM.

<!-- From a run.sh output: tools/n64-timing/calibration/kit.py --table RUN_DIR -->
| # | ROM | Runs for | Log | Film it? | Layout pads | Answers |
|---|---|---|---|---|---|---|
| 1 | `kit-cpu` | 0.2 s | 9.0 KB | no | 0-7 | `dcb`, `register-write`, `ifill`, `wb-release`, `dirty-miss`, `dirty-row`, `cpu-reads`, `poll-phase`, `dom2-read` |
| 2 | `kit-vi` | 4.2 s | 3.4 KB | no | 0-7 | `vi-first-line`, `count-per-field`, `vi-mid-field-blank` |
| 3 | `kit-dma` | 1.2 s | 18.7 KB | no | 0-7 | `memset-vi`, `sp-dma-direction`, `pi-dma-small`, `joybus-pads`, `si-write64-poll`, `pi-row-end`, `sp-dma-rsp`, `repeat-write` |
| 4 | `kit-hpos` | 0.2 s | 6.7 KB | no | 0-7 | `vi-cpu-contention` |
| 5 | `kit-rdp` | 0.2 s | 8.3 KB | no | 0-7 | `cmd-fifo-depth`, `cmd-fetch-burst`, `rdp-sync-setter`, `rdp-atomic`, `rdp-rect-base` |
| 6 | `kit-span` | 0.2 s | 9.2 KB | no | 0-7 | `color-half-16bpp`, `span-width` |
| 7 | `kit-span2` | 0.5 s | 25.0 KB | no | 0 | `span-write-release`, `mem-overhead-pipelined` |
| 8 | `kit-noise` | 0.2 s | 32.4 KB | no | 0-7 | `noise-alpha-dither`, `noise-pixel-offset`, `noise-idle`, `noise-2cycle`, `noise-stall`, `noise-reset` |
| 9 | `kit-noise2` | 0.2 s | 17.1 KB | no | 0 | `noise-dither-bits` |
| 10 | `rdpstat-1prim` | 0.2 s | 1.1 KB | yes | 0 | `stale-read` |
| 11 | `rdpstat-dpc` | 0.2 s | 0.6 KB | yes | 0 | `dpc-sequencing` |
| 12 | `rdpstat-systemtest` | 0.2 s | 0.9 KB | yes | 0 | `systemtest-rdp` |
| 13 | `rdpstat-unsynced` | 0.2 s | 0.7 KB | yes | 0 | `unsynced-attrs` |
| 14 | `nemu64-timing` | 0.8 s | 26.8 KB | no | 0 | `nemu64-console` |
| 15 | `nemu64-cycle` | 0.2 s | 1.5 KB | yes | 0 | `nemu64-cycle-console` |
| 16 | `nemu64-cop0hazard` | 0.2 s | 0.8 KB | yes | 0 | `nemu64-cop0hazard-console` |
| 17 | `kit-tex` | 0.3 s | 16.3 KB | no | 0-7 | `tmem-load-rate`, `fill-copy-rate`, `tmem-load-setup`, `loadtile-rows`, `copy-passfail`, `copy-passfail-pixels`, `attribute-stage`, `attribute-sync-cost` |
| 18 | `kit-zmem` | 1.9 s | 30.1 KB | no | 0-7 | `write-granularity`, `write-granularity-pixels`, `atomic-contention`, `imrd-zcmp-slots`, `imrd-zcmp-slots-2cyc`, `zread-2cyc`, `clobber`, `xbus-fetch-rate`, `rdp-hold`, `triangle-setup`, `filesel-glyph`, `pipebusy-stall` |
| 19 | `kit-zread` | 1.1 s | 13.9 KB | no | 0 | `zread-1cyc`, `zread-1cyc-both-zsep`, `zread-1cyc-both-zsame` |
| 20 | `kit-cpu2` | 0.2 s | 19.7 KB | no | 0-7 | `cpu-exceptions`, `cpu-watch`, `cpu-watch-edge`, `irq-clear`, `cache-ops`, `count-write-hold`, `count-write-phase`, `fetch-ahead`, `ctc1-fpe-ce`, `load-interlock-cop`, `fpu-classes`, `cache-ops-sum`, `wb-drain-target` |
| 21 | `kit-bus` | 1.6 s | 12.0 KB | no | 0-7 | `ri-priority`, `ri-reorder`, `vi-fetch-modes`, `vi-frame-latch`, `ri-priority-overlap`, `ai-rate`, `ai-fetch`, `vi-fetch-position`, `vi-blank-counting`, `refresh-all-banks`, `vi-intr-latency`, `vi-rcp-phase`, `refresh-latch`, `vi-fetch-overrun`, `ri-write-gap` |
| 22 | `cpu-llsc` | 0.2 s | 0.8 KB | yes | 0 | `cpu-llsc-console` |
| 23 | `kit-pif` | 6.0 s | 25.5 KB | no | 0 | a report, no question |

For each ROM:

1. Turn the console off. Start the listener (SC64).
2. Turn the console on and start the ROM from the menu (or it starts at once after `upload`).
3. Wait until the screen shows text. The ROM has then finished. The first page starts with `#kit rom=<id>`, and the status line at the bottom reads `<id> page 1`.
4. Check that the log ends with `#kit-end rom=<id> bytes=<n> fnv=<hash>`. On the SC64 it is the last line of the listener output. On the screen it is on the last page.
5. On the ED64, press Reset and return to the menu, so the SRAM reaches the SD card. On the SC64, download the save.

### Layout pads

A kit ROM's timing can depend on where its code sits against the CPU's 32-byte instruction cache lines. Moving the code by 76 bytes changed 8 of 72 kit verdicts on the fork (issue #100). So `run.sh` builds every kit ROM at 8 layout pads. Pad P inserts P instructions at boot, which moves every later instruction by 4P bytes. Pads 0 to 7 cover one cache line. Pad 0 is the build in `roms/boot-1/`.

A question is layout-sensitive when the fork's values for it differ between pads. `tools/n64-timing/calibration/kit.py --layout RUN_DIR` lists each question, how many of its values differ by pad, and the value whose range moves most. In the table above, a ROM with a layout-sensitive question has `0-7` in its Layout pads column.

The pads move code. The 76-byte shift of issue #100 moved data. It lengthened the `#kit` header string, which comes after the measurement kernels, so the kernels stayed in place and the point tables and output code after the header moved. One fork-only experiment repeated that shift on `kit-dma` (measured, U-LAYOUT-RESIDUE). It lengthened the header by 76 bytes, built every pad 0-7 at every boot delay, and read each shifted log as a capture against the unshifted fork run at the same pad. `sp-dma-direction` passes at all 8 pads. The shift moves 197 of its 240 per-pad value ranges, by at most 26 COUNT ticks, and 58 of them leave the range that pads 0-7 span. Each moved range still meets the same pad's model range with the full `range:rel:1` slack to spare. So `sp-dma-direction` does not need a data axis at this shift. The other five `kit-dma` questions also pass at every pad. The raw data is on unicron in `~/n64-timing/results/u-layout-residue/x76/`: `run-x76.sh` builds and runs the shifted ROMs, `compare.py` scores them, and `compare.txt` is its output. A dirty tree no longer shifts data: `build.py` stamps its `sha=` in the same 12 columns as a clean tree's.

For each of those ROMs, run the build for each pad 1 to 7 once from a power cycle, in addition to the pad 0 runs. Do the same for the `kit-dma` four-controller run and the `kit-noise` reset run (see [Repeat runs](#repeat-runs)) at each pad. That is 91 more runs: 77 for the 11 ROMs, 7 for `kit-dma` with four controllers, and 7 Reset runs of `kit-noise`. At about three minutes for each power cycle, load and copy (inferred, not timed on a console), they add about four and a half hours. The logs are the same size as pad 0's, and each fits the 32 KiB SRAM. Together they add about 1.5 MB to the capture.

Ingestion reads each log's pad from its first line. It compares each pad's captures with the fork's run at the same pad, under the question's rule. A question's verdict holds only if it is the same at every pad; otherwise the result is `consistent-only`, and the detail names each pad's verdict. This is the bench layout rule (docs/design/green-plan.md section 3, Bench layout pads). A layout-sensitive question whose capture lacks a pad fails, as a capture that lacks a point does. A question that is not layout-sensitive is judged from the pads its captures hold.

### kit-dma with four controllers

Run `kit-dma` twice: once with one controller in port 1 and nothing else, and once with four controllers in ports 1-4. Name the second capture `kit-dma.pads4.isviewer.log` (or `.pads4.srm`), and `kit-dma.pads4.p<P>.isviewer.log` for layout pad P. Ingestion reads which ports answered from the log itself and compares each capture with the fork's run with the same controllers. The two setups answer `joybus-pads`, which decides the 2J-4J joybus fit.

### A hang

Every wait in a kit ROM gives up after a bound and the ROM goes on: a PI wait after 2^20 polls (about 0.3 s), an RDP wait for the DP interrupt after 2^22 polls (about 1 s). The fork's longest wait is 2.7 ms. Each wait that gave up counts in the `#kit-timeout pi=<n> rdp=<n>` line before the footer. The fork reads `pi=0x0 rdp=0x0` for every ROM, and ingestion fails every question of a ROM whose log counts any timeout, because the points after the wait are not measurements.

A ROM can still stop for good, for example in a CPU exception the kit does not expect. Then:

- On the ED64, the save on the SD card is empty (all zero bytes) or ends before the `#kit-end` line. An empty save means the ROM stopped before its first line; a truncated one means it stopped after the last record in the save.
- On the SC64, the listener output stops and the screen never shows text.

If a ROM hangs or logs a nonzero `#kit-timeout`, turn the console off and run it once more from a power cycle. Keep both captures, even the empty or truncated one: ingestion stores a log without a valid footer as INCOMPLETE and does not compare it. Then go on with the next ROM. In [What to send back](#what-to-send-back), name the ROM and the last record its log holds. A hang loses only that ROM's questions; nothing on the console or the flashcart needs a repair.

### The PIF boot timeout

`kit-pif` (`roms/single/kit-pif.z64`) is the one ROM that never finishes. Every other kit ROM sends the PIF terminate-boot command itself (`romgen/runtime.py` `pif_terminate_boot`). `kit-pif` does not, so the PIF halts the CPU through NMI after its boot timeout. n64brew [PIF-NUS](https://n64brew.dev/wiki/PIF-NUS) says the PIF expects the command "before 5 seconds from boot" and halts the CPU if it does not come "within about 5 seconds from boot". The fork's PIF (`ares/n64/pif/hle.cpp`) waits 6 s. The ROM prints `#bench kit-pif count n=<sample> count=<COUNT>` every 10 ms of COUNT, so its last line is the last COUNT before the halt.

Run it only from a cold boot through `sc64deployer upload`:

```sh
sc64deployer upload --save-type sram roms/single/kit-pif.z64
sc64deployer debug --isv 0x03FF0000 | tee capture/kit-pif.isviewer.log
```

Then turn the console on, wait 15 seconds, and turn it off. The screen stays black, and the log has no `#kit-end` line. A flashcart menu (the ED64 menu or the SC64 menu from the SD card) has already sent terminate-boot before it starts a ROM, so the PIF never halts the ROM, and the menu path has no ISViewer. A log that ends with `#kit-end` after about 12 s of samples shows that boot was already terminated: run it again through `upload`.

ingest.py stores the log (it reports it INCOMPLETE, as expected) and prints the last COUNT next to the fork's. This is a report, not a check. COUNT counts from the IPL3's write of 0, and no source bounds the offset between that and the start of the PIF's timer, so the last COUNT cannot decide between 5 s and 6 s (`tools/n64-timing/calibration/undecidable.tsv`, `legacy.pif.boot-timeout`). On the fork the last COUNT is 280890637 to 280890686 ticks over the 8 layout pads, 5.992 s, in sample 593. The fork's PIF halts the CPU 6.000 s after it starts its timer, and the pinned IPL3 writes COUNT 0 1.8 ms before that (measured with a scratch probe in `pif/hle.cpp`), so the next sample, 10 ms later, never runs.

### Repeat runs

A single run is one point on the console's boot phase. The fork's side spans 8 boot delays, and a pass needs the console's values to overlap the fork's range (preference 27).

1. Required: run every ROM in the table twice, each from a power cycle. These are the pad 0 builds. The layout-pad builds (see [Layout pads](#layout-pads)) run once each. Name the second capture `<rom>.run2.isviewer.log` and so on; ingestion keeps every log and takes the range over them.
2. Recommended: run the seven other boot-delay builds of `kit-cpu`, `kit-dma` and `kit-vi` once each, from a power cycle. These ROMs hold the poll-phase and VI-start points, where one boot phase can miss a narrow dip (issue #77 shows one at K = 1300-1316).
3. Required, once for each layout pad: after `kit-noise` finishes from a power cycle, press Reset and run the same `kit-noise` build again without turning the console off. Name that capture `kit-noise.reset.isviewer.log` (or `.reset.srm`), and `kit-noise.reset.p<P>.isviewer.log` for pad P. It answers `noise-reset`: does a reset reload the noise LFSR's power-on state.

### External ROMs

These ROMs are not built by the kit. Each capture goes in the capture directory under a name that starts with `ext-<rom>`, and ingestion stores it there.

- **Thar0/RDP-Timing-Tests** (`ext-thar0`). Build it from [Thar0/RDP-Timing-Tests](https://github.com/Thar0/RDP-Timing-Tests) at commit `a81ced93b28d` as its README describes, or use a build you trust. It logs over libdragon's USB log, which the SC64 and the ED64 X7 both carry; its `client.py` prints it. Save that text as `capture/ext-thar0.log`. Its text names no ROM, so ingestion checks the build by its configuration table: each file must print the romgen port's configurations (`romgen/suites/thar0/configs.py`), in order, or ingestion stores nothing. Ingestion then compares each configuration's pruned average BUFBUSY and PIPEBUSY with the fork's run of the romgen port, within 1%, and counts the configurations within 1% of Thar0's own console. It answers `thar0-console`. The romgen port's console build is not used: its `--hw` build hangs in its first configuration on the fork.
- **snapper64** (`ext-snapper64`). Run snapper64 `e1cd8a61fc43` as published and copy the `.test` dumps it writes into `capture/ext-snapper64/`. A dump's name is a hash of its group, test and assert, so ingestion stores nothing when a file is not named after a published dump (another snapper64 version, or a stray file); it needs the published dumps (`romgen/suites/snapper/fetch.sh`) for that check. Ingestion then compares each dump byte for byte with the published console dumps. It answers `snapper64`.
- **n64-systembench** (`ext-systembench`). Build the hardware-era build before `run.sh`, so the fork runs the same file:

  ```sh
  OUT="$N64_TIMING_HOME/roms/systembench" tools/n64-timing/build-systembench-era.sh 2023
  ```

  The script needs docker. It builds rasky/n64-systembench `50f5066` with its vendored libdragon and GCC 12.2.0 (libdragon `a54ccd736`'s Dockerfile), with the `timeit_average` tie fix; this is the build the `systembench:*` checks run. Its `provenance.txt` must show `fd5ec6c06acb686608c53554950c8b6b12b011dca5b30bf22bd7277a8d986823  n64-systembench.z64`, and `rambuf` sits at 0x800278c0. Run that unpadded `n64-systembench.z64` with one controller in port 1, not a boot-delay build, and save its ISViewer log as `capture/ext-systembench/run1.isviewer.log` (and `run2.isviewer.log` for the second run). The log names no build, so copy the `provenance.txt` line for the file you flashed into `capture/ext-systembench/rom-sha256.txt` (`<sha256>  n64-systembench.z64`). Ingestion stores nothing unless that sha256, the fork's (`run.sh` records it in `rom-sha256.txt`) and the pin above are the same. Ingestion then compares each of the 34 rows with the fork's run of the same file (`run.sh` writes it to `ext/systembench.txt`) under the ROM's own rule (within 1 CPU or 2 RCP cycles, or 0.2 %), and counts the rows that also match the published hardware value. It answers `systembench`. The comparison holds only for this binary: a change of one to three instructions in a poll loop moves the poll rows by up to 10 RCP cycles (verify-83), and `rambuf`'s address decides U32R rand and PI DMA 1 KiB, so a log from any other build decides nothing.
- **Majora's Mask bench** (`ext-mm-bench`). Build the BENCH ROMs before `run.sh`, so the fork runs the same files (`run.sh` exits 1 without them; `standing.sh` builds them):

  ```sh
  tools/n64-timing/calibration/build-mm-bench.sh
  ```

  The script builds wScottSh/mm-decomp-60fps at the commit `mm_bench.py` pins (the head of its `bench/sct-match` branch while that PR is open) with `make BENCH=1`, in a detached worktree of `$MM_DECOMP` (default `~/repos/mm-decomp-60fps`), from the retail NTSC-U 1.0 ROM in `$MM_BASEROM`. It writes `mm-bench-<scene>.z64` for the six scenes (the Play scenes `south_clock_town`, `termina_field`, `mountain_village_winter` and `great_bay_coast`, and the file-select scenes `file_select_empty` and `file_select_named`) and `rom-sha256.txt` to `$N64_TIMING_HOME/roms/mm-bench`, and fails unless each sha256 is the pinned one. The ROMs hold Nintendo data: keep them out of git. Run each scene ROM once from a power-on with no controller input. Each Play ROM boots into its scene with the debug save as map select loads it (human Link, day 1; South Clock Town at 12:00, the state of the fork's mmbench `sct` scene, so that run also decides `mm:south-clock-town`), plays 720 game frames (about 40 s at 20 fps), then prints its 600 measured frames over IS-Viewer at `0x13FF0000` and keeps running. The SC64 forwards IS-Viewer over USB; that path is untested on this ROM. Save each log as `capture/ext-mm-bench/<scene>.isviewer.log`, and copy the `rom-sha256.txt` of the files you flashed into `capture/ext-mm-bench/`: the log names no ROM identity, so ingestion compares those sha256 with the fork's and the pin and refuses the capture if they differ. Ingestion then compares each run's median fields per game frame (`vi`) and median `rdp_ticks` (gRDPTimeTotal, the OSTime ticks from the gfx task's start to the DP full sync) with the fork's per-frame range over its run of the same ROM. A file-select ROM first writes files 1 and 2 (and empties both owl saves) in the cartridge's flash save, so it overwrites whatever save the SC64 holds for it. It then waits on the idle main screen for 120 game frames and records 600 (about 12 to 24 s at 1 to 2 fields per frame). Every ROM also records the DPC counters (`dpc_clock`, `dpc_pipebusy`, ...) per frame, which ingestion reports but does not judge. The Play scenes answer `mm-bench`, the file-select scenes `mm-filesel`.

## Capture

Put every capture file for the session in one directory, for example `capture/`. ingest.py reads all of these, in any mix:

- SC64 listener output: `<rom>.isviewer.log`.
- SRAM saves: `.srm`, `.sra` or `.sav`, in either byte order (the SC64 download and the ED64 SD card differ).
- Transcribed screen text: `<rom>.photo.txt`.
- The external ROMs' files, named `ext-<rom>...`.

ingest.py undoes what capture tools add to a log: CRLF or CR line ends (a Windows `tee`, a text-mode copy, a serial terminal), UTF-16 (a PowerShell `>` redirect), a UTF-8 byte order mark, terminal color codes and a listener banner line before the log. It then checks the footer's byte count and FNV hash, so any other change to a byte marks the log INCOMPLETE: it is stored and not compared.

### Photo fallback

Use the screen only when neither USB nor SRAM works, and only for the short logs. Each page shows 26 lines for 8 seconds, and the pages loop. A log over about 2 KB is many pages, and one wrong character in the transcription voids it, so for those ROMs fix the USB or SRAM path instead. The table above marks the ROMs short enough to film.

Film one full loop for each ROM. Make sure each frame shows the bottom status line (`<id> page <n>`), so the pages can be ordered. Type the pages into `<rom>.photo.txt`, one screen line per text line, and join the lines that the 38-column screen wrapped. Type the 64 characters of `rom_sha256` in the first line exactly: ingestion uses them to identify the ROM.

## Ingest

Run:

```sh
tools/n64-timing/calibration/ingest.py capture/ --id console-<date>
```

The command does these things:

1. It parses every file and prints one line for each log, with the ROM, the record count, and `INCOMPLETE` when the footer is missing or does not match. It prints one line for each external ROM's files. Before it stores anything, it compares each kit log's `rom_sha256` with the fork's log of the same ROM and build. If one differs, the console ran a different ROM from the fork's. The command then stops, stores nothing, and prints both values and the commit that built the console's ROM. To continue, run `run.sh` at that commit and give its output to `--model`, or run the kit again on the console with the current ROMs. It also stops when an external ROM's capture is not the ROM its question names: a Majora's Mask BENCH or n64-systembench capture whose `rom-sha256.txt` differs from the fork's and the pin, a Thar0 capture whose configurations are not the port's, or a snapper64 file that is not a published dump.
2. It stores every log under `docs/calibration/hardware/console-<date>/` (reset captures as `<rom>.reset.<n>.log`, external files under `ext-<rom>/`), with a `manifest.tsv` that records each source file's SHA-256, the kit commit, the ROM's `rom_sha256`, `RI_REFRESH`, the boot (power-on or reset), the controller ports that answered and the build (boot delay and layout pad).
3. It compares each question's points with the fork's run of the same ROM, under the question's rule: the console's values over all its captures at a layout pad against the fork's range over its boot delays at that pad (see [Layout pads](#layout-pads)). A capture that lacks any point the question names fails. It writes each result as the `hw:<question>` row of `docs/spec/n64-timing-results.tsv`.
4. It regenerates the spec and the inventory, and prints each behavior whose status changed.

### Latency histograms

Two logs record distributions as well as the values the questions compare. No question compares a histogram; they are the console's data behind the means, for the bus investigation (docs/design/green-plan/bus.md, Q2 and section 3):

- `nemu64-timing` prints a `#hist <test>.<value> <cycles>:<count>,...` line before the result of each of its 21 averaged values (Load Miss and uncached loads, VI on and off, 1000 runs each). These are the counts behind `nemu64-console`'s min, max, median and mean. A refresh tail shows as a flat spread over 41..80 at about 1-2 %; a second latency state shows as a second peak at 42-44.
- `nemu64-console` compares those 21 averaged values against the fork's verdict at every VI phase of the nemu64 phase walk (`run-nemu64.sh timing-phase`), not against the fork's one run of the kit ROM, because the console boots into any phase. kit.py reads the walk from `nemu64/timing-phase` beside the model's `calib/` directory, as a standing run lays them out, and reports `missing` without it.
- `kit-hpos` already logs every load. kit.py derives `hist_pclk`, each latency in pclk with its count, for each `vi-cpu-contention` point.

To print them from stored logs or from the fork's run:

```sh
tools/n64-timing/calibration/kit.py --hist docs/calibration/hardware/console-<date>/nemu64-timing.*.log docs/calibration/hardware/console-<date>/kit-hpos.*.log
```

Each line is `<file> <rom>/<point> <metric> <latency>:<count>,...`. The `#hist` lines make `nemu64-timing`'s log about 0.8 KB longer, so it still fits the 32 KiB SRAM. Like every log over 2 KB, it needs the USB or SRAM path (see [Photo fallback](#photo-fallback)).

### Watch on a failing SC

`cpu-llsc` checks SC and SCD against the VR4300 User's Manual and prints its own verdict per case, like the nemu64 ROMs. `cpu-llsc-console` compares the verdicts of tests 0 and 1 (12 cases) exactly. Test 2 asks what the manual leaves open: does an SC or SCD that fails (the LLbit is clear) raise Watch when WatchLo matches its address? The fork does not. The ROM prints the console's answer as one line per instruction, and no question compares it:

```
#bench cpu-llsc watch-fail-sc exc=<0 or 1> exccode=<23 when Watch fired> rt_lo=<rt after>
```

`exc=0` with `rt_lo=0x0` means no Watch: the SC failed and wrote 0 to rt, as on the fork. `exc=1 exccode=23` with `rt_lo=0x5a5a0001` (SCD `0x5a5a0002`) means Watch fired and the exception aborted the SC. Test 2's own check, the memory word unchanged, holds in both cases. To read the line from a stored capture, run `grep watch-fail docs/calibration/hardware/console-<date>/cpu-llsc.*.log`. Report a Watch that fires; `item:cpu.sc-watch-on-fail` in [inventory.md](inventory.md) tracks it, and the fork's SC would then need to raise Watch before it tests the LLbit.

To see what an ingestion would change without writing to the repository, add `--dry-run`. `tools/n64-timing/calibration/dry-run.sh <run.sh output>` runs the whole path on the fork's own logs as a fake capture: ISViewer logs, real SRAM dumps in both byte orders, a CRLF log, the four-controller run, a cut log, the Thar0 port's output, the fork's n64-systembench log and the published snapper64 dumps.

## What to send back

- The `capture/` directory as it is: the listener logs, the saves, the external ROMs' files, and any videos or photos. The data comes from your console, so it can be committed.
- The output of `ingest.py`.
- Your console's details: the board revision (on the label under the console), the flashcart and its firmware or OS version, the Expansion Pak, and the controllers.

## What each result will tell us

Each question in [inventory.md](inventory.md) has a `hw:<id>` result. A pass means the model agrees with your console under the question's rule. A fail gives the console's values and the model's range. The rows that the question closes then show what to change. The inventory groups them: rows that wait only for this run, fit-only and model-choice rows, inferred rows, failing and weakly passing checks, and the items from issue #16 and the follow-ups. Its Coverage table names a question for every behavior row, or one of two reasons: `not-hardware-decidable` when no console run can decide it, and `not decidable by this kit` when a console could but this kit and a flashcart cannot, with what would (a retail cartridge's save chip, a modified IPL3).

`cpu-watch` compares the fork's Watch entry (fired 4 of 4, 6 pclk, the same entry as AdEL) with the console. No published value gives the entry cost. No behavior row names it, so its result moves no row.
