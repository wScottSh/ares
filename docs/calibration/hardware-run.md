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

Allow about two hours for the required runs and three for the recommended ones. Each kit ROM runs for a few seconds after it boots (the table in [Run the kit](#run-the-kit) has the times). Most of the time is power cycles, loading ROMs and copying files.

## Build the kit

1. On the PC, run:

   ```sh
   tools/n64-timing/calibration/run.sh
   ```

   This builds every kit ROM and runs each one on the fork: the walked kit ROMs at 8 boot delays, `kit-dma` also with four controllers, the romgen Thar0 port, and n64-systembench when its ROM is built (see n64-systembench under [External ROMs](#external-roms); without it `hw:systembench` reads `missing`). That run is the model side of each comparison. It writes `$N64_TIMING_HOME/results/calib/` and takes about one minute. It fails if any ROM's cartridge SRAM copy differs from its ISViewer copy, if a ROM left the PI domain-1 timing changed, or if any wait gave up (see [A hang](#a-hang)).

2. Copy the console builds to the flashcart's SD card:

   - `$N64_TIMING_HOME/results/calib/roms/boot-1/*.z64`: the walked kit ROMs, one build each (`kit-cpu`, `kit-cpu2`, `kit-vi`, `kit-dma`, `kit-bus`, `kit-hpos`, `kit-rdp`, `kit-span`, `kit-tex`, `kit-zmem`, `kit-noise`).
   - `$N64_TIMING_HOME/results/calib/roms/single/*.z64`: `rdpstat-1prim`, `rdpstat-dpc`, `rdpstat-systemtest`, `rdpstat-unsynced`, `nemu64-timing`, `nemu64-cycle`, `nemu64-cop0hazard`.
   - For the recommended phase runs, also `roms/boot-<K>/kit-cpu.z64`, `kit-dma.z64` and `kit-vi.z64` for the other seven delays K (165, 329, 493, 657, 821, 985, 1149). Rename each to `kit-cpu-<K>.z64` and so on, because the menu shows file names only.

   Each ROM prints a first line `#kit rom=<id> sha=<commit> fmt=1 build=<boot-K or single>`. The commit must be the one you built from. Ingestion records it.

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

   If you use the SC64 menu (N64FlashcartMenu) from the SD card instead of `upload`, set the save type to SRAM 32 KiB in the ROM's settings. The menu path does not enable the IS-Viewer, so only the SRAM copy and the screen are captured.

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
- The one exception is the reset run in step 3 of [Repeat runs](#repeat-runs). It is the only capture taken after Reset.

### Order

Run the ROMs in this order. The times are the fork's emulated time from boot to the `#kit-end` line. The console's time is the same to within its boot time. Every log fits the 32 KiB SRAM.

<!-- From a run.sh output: tools/n64-timing/calibration/kit.py --table RUN_DIR -->
| # | ROM | Runs for | Log | Film it? | Answers |
|---|---|---|---|---|---|
| 1 | `kit-cpu` | 0.2 s | 8.9 KB | no | `dcb`, `register-write`, `ifill`, `wb-release`, `dirty-miss`, `dirty-row`, `cpu-reads`, `poll-phase`, `dom2-read` |
| 2 | `kit-vi` | 3.6 s | 1.8 KB | yes | `vi-first-line`, `count-per-field` |
| 3 | `kit-dma` | 1.2 s | 15.6 KB | no | `memset-vi`, `sp-dma-direction`, `pi-dma-small`, `joybus-pads`, `pi-row-end` |
| 4 | `kit-hpos` | 0.2 s | 6.6 KB | no | `vi-cpu-contention` |
| 5 | `kit-rdp` | 0.2 s | 8.2 KB | no | `cmd-fifo-depth`, `cmd-fetch-burst`, `rdp-sync-setter`, `rdp-atomic`, `rdp-rect-base` |
| 6 | `kit-span` | 0.2 s | 9.1 KB | no | `color-half-16bpp`, `span-width` |
| 7 | `kit-noise` | 0.2 s | 29.5 KB | no | `noise-alpha-dither`, `noise-dither-bits`, `noise-pixel-offset`, `noise-idle`, `noise-2cycle`, `noise-stall`, `noise-reset` |
| 8 | `rdpstat-1prim` | 0.2 s | 1.0 KB | yes | `stale-read` |
| 9 | `rdpstat-dpc` | 0.2 s | 0.6 KB | yes | `dpc-sequencing` |
| 10 | `rdpstat-systemtest` | 0.2 s | 0.8 KB | yes | `systemtest-rdp` |
| 11 | `rdpstat-unsynced` | 0.2 s | 0.6 KB | yes | `unsynced-attrs` |
| 12 | `nemu64-timing` | 0.8 s | 25.9 KB | no | `nemu64-console` |
| 13 | `nemu64-cycle` | 0.2 s | 1.4 KB | yes | `nemu64-cycle-console` |
| 14 | `nemu64-cop0hazard` | 0.2 s | 0.7 KB | yes | `nemu64-cop0hazard-console` |
| 15 | `kit-tex` | 0.3 s | 16.2 KB | no | `tmem-load-rate`, `fill-copy-rate`, `tmem-load-setup`, `loadtile-rows`, `copy-passfail`, `copy-passfail-pixels`, `attribute-stage`, `attribute-sync-cost` |
| 16 | `kit-zmem` | 1.3 s | 20.3 KB | no | `write-granularity`, `write-granularity-pixels`, `atomic-contention`, `imrd-zcmp-slots`, `clobber`, `xbus-fetch-rate`, `rdp-hold`, `triangle-setup`, `pipebusy-stall` |
| 17 | `kit-cpu2` | 0.2 s | 17.7 KB | no | `cpu-exceptions`, `cpu-watch`, `cache-ops`, `load-interlock-cop`, `fpu-classes`, `cache-ops-sum`, `wb-drain-target` |
| 18 | `kit-bus` | 1.5 s | 10.6 KB | no | `ri-priority`, `ri-reorder`, `vi-fetch-modes`, `ri-priority-overlap`, `ai-rate`, `ai-fetch`, `vi-fetch-position`, `vi-blank-counting`, `refresh-all-banks`, `vi-intr-latency`, `vi-rcp-phase` |

For each ROM:

1. Turn the console off. Start the listener (SC64).
2. Turn the console on and start the ROM from the menu (or it starts at once after `upload`).
3. Wait until the screen shows text. The ROM has then finished. The first page starts with `#kit rom=<id>`, and the status line at the bottom reads `<id> page 1`.
4. Check that the log ends with `#kit-end rom=<id> bytes=<n> fnv=<hash>`. On the SC64 it is the last line of the listener output. On the screen it is on the last page.
5. On the ED64, press Reset and return to the menu, so the SRAM reaches the SD card. On the SC64, download the save.

### kit-dma with four controllers

Run `kit-dma` twice: once with one controller in port 1 and nothing else, and once with four controllers in ports 1-4. Name the second capture `kit-dma.pads4.isviewer.log` (or `.pads4.srm`). Ingestion reads which ports answered from the log itself and compares each capture with the fork's run with the same controllers. The two setups answer `joybus-pads`, which decides the 2J-4J joybus fit.

### A hang

Every wait in a kit ROM gives up after a bound and the ROM goes on: a PI wait after 2^20 polls (about 0.3 s), an RDP wait for the DP interrupt after 2^22 polls (about 1 s). The fork's longest wait is 2.7 ms. Each wait that gave up counts in the `#kit-timeout pi=<n> rdp=<n>` line before the footer. The fork reads `pi=0x0 rdp=0x0` for every ROM, and ingestion fails every question of a ROM whose log counts any timeout, because the points after the wait are not measurements.

A ROM can still stop for good, for example in a CPU exception the kit does not expect. Then:

- On the ED64, the save on the SD card is empty (all zero bytes) or ends before the `#kit-end` line. An empty save means the ROM stopped before its first line; a truncated one means it stopped after the last record in the save.
- On the SC64, the listener output stops and the screen never shows text.

If a ROM hangs or logs a nonzero `#kit-timeout`, turn the console off and run it once more from a power cycle. Keep both captures, even the empty or truncated one: ingestion stores a log without a valid footer as INCOMPLETE and does not compare it. Then go on with the next ROM. In [What to send back](#what-to-send-back), name the ROM and the last record its log holds. A hang loses only that ROM's questions; nothing on the console or the flashcart needs a repair.

### Repeat runs

A single run is one point on the console's boot phase. The fork's side spans 8 boot delays, and a pass needs the console's values to overlap the fork's range (preference 27).

1. Required: run every ROM in the table twice, each from a power cycle. Name the second capture `<rom>.run2.isviewer.log` and so on; ingestion keeps every log and takes the range over them.
2. Recommended: run the seven other boot-delay builds of `kit-cpu`, `kit-dma` and `kit-vi` once each, from a power cycle. These ROMs hold the poll-phase and VI-start points, where one boot phase can miss a narrow dip (issue #77 shows one at K = 1300-1316).
3. Required, once: after `kit-noise` finishes from a power cycle, press Reset and run `kit-noise` again without turning the console off. Name that capture `kit-noise.reset.isviewer.log` (or `.reset.srm`). It answers `noise-reset`: does a reset reload the noise LFSR's power-on state.

### External ROMs

These ROMs are not built by the kit. Each capture goes in the capture directory under a name that starts with `ext-<rom>`, and ingestion stores it there.

- **Thar0/RDP-Timing-Tests** (`ext-thar0`). Build it from [Thar0/RDP-Timing-Tests](https://github.com/Thar0/RDP-Timing-Tests) at commit `a81ced93b28d` as its README describes, or use a build you trust. It logs over libdragon's USB log, which the SC64 and the ED64 X7 both carry; its `client.py` prints it. Save that text as `capture/ext-thar0.log`. Ingestion compares each configuration's pruned average BUFBUSY and PIPEBUSY with the fork's run of the romgen port, within 1%, and counts the configurations within 1% of Thar0's own console. It answers `thar0-console`. The romgen port's console build is not used: its `--hw` build hangs in its first configuration on the fork.
- **snapper64** (`ext-snapper64`). Run snapper64 `e1cd8a61fc43` as published and copy the `.test` dumps it writes into `capture/ext-snapper64/`. Ingestion compares each dump byte for byte with the published console dumps. It answers `snapper64`.
- **n64-systembench** (`ext-systembench`). Build the hardware-era build before `run.sh`, so the fork runs the same file:

  ```sh
  OUT="$N64_TIMING_HOME/roms/systembench" tools/n64-timing/build-systembench-era.sh 2023
  ```

  The script needs docker. It builds rasky/n64-systembench `50f5066` with its vendored libdragon and GCC 12.2.0 (libdragon `a54ccd736`'s Dockerfile), with the `timeit_average` tie fix; this is the build the `systembench:*` checks run. Its `provenance.txt` must show `fd5ec6c06acb686608c53554950c8b6b12b011dca5b30bf22bd7277a8d986823  n64-systembench.z64`, and `rambuf` sits at 0x800278c0. Run that unpadded `n64-systembench.z64` with one controller in port 1, not a boot-delay build, and save its ISViewer log as `capture/ext-systembench.log` (and `ext-systembench.run2.log` for the second run). Ingestion compares each of the 34 rows with the fork's run of the same file (`run.sh` writes it to `ext/systembench.txt`) under the ROM's own rule (within 1 CPU or 2 RCP cycles, or 0.2 %), and counts the rows that also match the published hardware value. It answers `systembench`. The comparison holds only for this binary: a change of one to three instructions in a poll loop moves the poll rows by up to 10 RCP cycles (verify-83), and `rambuf`'s address decides U32R rand and PI DMA 1 KiB, so a log from any other build decides nothing.
- **n64_pi_dma_test** (`ext-pi_dma_test`). Run rasky's prebuilt ROM (the sha256 is pinned in `standing.sh`) and save its log as `capture/ext-pi_dma_test.log`. The ROM does not print its COUNT reads, which `pidma-offset` needs, so this capture only re-checks the published logs, and `pidma-offset` has no reader. A build that logs COUNT needs the ROM's source, which has no license.
- **Majora's Mask bench** (`ext-mm-bench`). Scott's `mm-decomp-60fps` BENCH build prints `osGetCount` and DPC_CLOCK per frame. Run it on the file-select screen with named files and in the scenes behind `mm:south-clock-town`, and save the log as `capture/ext-mm-bench.<scene>.log`. Ingestion stores it, and `mm-filesel` has no reader: the fork side would need the same BENCH build run on `n64-run`, and no tool in this repository builds it. Compare it by hand against `tools/n64-timing/mmbench`.

## Capture

Put every capture file for the session in one directory, for example `capture/`. ingest.py reads all of these, in any mix:

- SC64 listener output: `<rom>.isviewer.log`.
- SRAM saves: `.srm`, `.sra` or `.sav`, in either byte order (the SC64 download and the ED64 SD card differ).
- Transcribed screen text: `<rom>.photo.txt`.
- The external ROMs' files, named `ext-<rom>...`.

ingest.py undoes what capture tools add to a log: CRLF or CR line ends (a Windows `tee`, a text-mode copy, a serial terminal), UTF-16 (a PowerShell `>` redirect), a UTF-8 byte order mark, terminal color codes and a listener banner line before the log. It then checks the footer's byte count and FNV hash, so any other change to a byte marks the log INCOMPLETE: it is stored and not compared.

### Photo fallback

Use the screen only when neither USB nor SRAM works, and only for the short logs. Each page shows 26 lines for 8 seconds, and the pages loop. A log over about 2 KB is many pages, and one wrong character in the transcription voids it, so for those ROMs fix the USB or SRAM path instead. The table above marks the ROMs short enough to film.

Film one full loop for each ROM. Make sure each frame shows the bottom status line (`<id> page <n>`), so the pages can be ordered. Type the pages into `<rom>.photo.txt`, one screen line per text line, and join the lines that the 38-column screen wrapped.

## Ingest

Run:

```sh
tools/n64-timing/calibration/ingest.py capture/ --id console-<date>
```

The command does these things:

1. It parses every file and prints one line for each log, with the ROM, the record count, and `INCOMPLETE` when the footer is missing or does not match. It prints one line for each external ROM's files.
2. It stores every log under `docs/calibration/hardware/console-<date>/` (reset captures as `<rom>.reset.<n>.log`, external files under `ext-<rom>/`), with a `manifest.tsv` that records each source file's SHA-256, the kit commit, `RI_REFRESH`, the boot (power-on or reset) and the controller ports that answered.
3. It compares each question's points with the fork's run of the same ROM, under the question's rule: the console's values over all its captures against the fork's range over its boot delays. A capture that lacks any point the question names fails. It writes each result as the `hw:<question>` row of `docs/spec/n64-timing-results.tsv`.
4. It regenerates the spec and the inventory, and prints each behavior whose status changed.

To see what an ingestion would change without writing to the repository, add `--dry-run`. `tools/n64-timing/calibration/dry-run.sh <run.sh output>` runs the whole path on the fork's own logs as a fake capture: ISViewer logs, real SRAM dumps in both byte orders, a CRLF log, the four-controller run, a cut log, the Thar0 port's output, the fork's n64-systembench log and the published snapper64 dumps.

## What to send back

- The `capture/` directory as it is: the listener logs, the saves, the external ROMs' files, and any videos or photos. The data comes from your console, so it can be committed.
- The output of `ingest.py`.
- Your console's details: the board revision (on the label under the console), the flashcart and its firmware or OS version, the Expansion Pak, and the controllers.

## What each result will tell us

Each question in [inventory.md](inventory.md) has a `hw:<id>` result. A pass means the model agrees with your console under the question's rule. A fail gives the console's values and the model's range. The rows that the question closes then show what to change. The inventory groups them: rows that wait only for this run, fit-only and model-choice rows, inferred rows, failing and weakly passing checks, and the items from issue #16 and the follow-ups. Its Coverage table names a question for every behavior row, or one of two reasons: `not-hardware-decidable` when no console run can decide it, and `not decidable by this kit` when a console could but this kit and a flashcart cannot, with what would (a retail cartridge's save chip, a modified IPL3).

`cpu-watch` is expected to fail until issue #87 is fixed: the fork never raises the Watch exception. No behavior row names it, so a console that raises Watch moves no row.
