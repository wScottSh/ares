# Run the calibration kit on a console

This guide takes you through one calibration session (#16) on an N64. You run each kit ROM from a flashcart, capture the log it prints, and run one command that stores the capture and puts the console's values into the spec. [inventory.md](inventory.md) lists every question the session answers and the spec rows and checks that each answer closes.

## Before you start

You need:

- An NTSC retail NUS-001 console with an Expansion Pak. The kit ROMs use RDRAM above 4 MiB, so they do not run without the Pak.
- One standard controller in port 1, and no other controllers. The fork's runs that the console is compared with have one controller, and the joybus points measure the ports.
- A flashcart. Use one of these:
  - SummerCart64 (SC64), with `sc64deployer` on a PC and a USB cable. This is the best path because the log arrives over USB as the ROM runs.
  - EverDrive-64 X7 (ED64). The log is in the cartridge SRAM, and the ED64 writes it to the SD card.
- A TV or capture device, and a phone camera for the fallback.
- On the PC, a checkout of this repository with the runner built (`tools/n64-timing/build.sh`) and libdragon's `ipl3_compat.z64` at the path that `tools/n64-timing/romgen/README.md` names.

Allow about 45 minutes. Each kit ROM runs for less than 5 seconds after it boots. Most of the time is loading ROMs from the menu and copying files.

## Build the kit

1. On the PC, run:

   ```sh
   tools/n64-timing/calibration/run.sh
   ```

   This builds every kit ROM and runs each one on the fork. That run is the model side of each comparison. It writes `$N64_TIMING_HOME/results/calib/`. It takes about one minute.

2. Copy these ROMs to the flashcart's SD card. They are the console builds:

   - `$N64_TIMING_HOME/results/calib/roms/boot-1/*.z64` (7 ROMs: `kit-cpu`, `kit-vi`, `kit-dma`, `kit-hpos`, `kit-rdp`, `kit-span`, `kit-noise`)
   - `$N64_TIMING_HOME/results/calib/roms/single/*.z64` (5 ROMs: `rdpstat-1prim`, `rdpstat-dpc`, `rdpstat-systemtest`, `rdpstat-unsynced`, `nemu64-timing`)

   Each ROM prints a first line `#kit rom=<id> sha=<commit>`. The commit must be the one you built from. The ingestion step records it.

## Set up the flashcart

### SummerCart64

1. Connect the SC64 to the PC with USB.
2. Before you start each ROM, start the debug listener and leave it running:

   ```sh
   sc64deployer debug --isv 0x03FF0000 | tee capture/<rom>.isviewer.log
   ```

   The kit ROMs write the log through the ISViewer protocol at cartridge address 0x13FF0000, which is SC64 ROM offset 0x03FF0000. Run `sc64deployer debug --help` to confirm the option name for your `sc64deployer` version.

3. Also enable SRAM saving for the ROM if your menu asks. The ROM header declares 32 KiB SRAM (bytes 0x3C-0x3F: `ED`, save type 3), so the SRAM copy is a second capture.

### EverDrive-64 X7

1. Copy the ROMs to the SD card.
2. In the ED64 menu, check that the save type for each kit ROM is SRAM 32K. The ROM header declares it through the ED64 homebrew header. If your OS version ignores the header, set the save type by hand.
3. The log is written to SRAM as the ROM runs. The ED64 copies SRAM to the SD card when you press Reset and return to the menu. On OS 3.x the save is in `ED64/gamedata/`. Confirm the folder on the first ROM before you run the others.

## Run the kit

Run the ROMs in this order. Press Reset after each one and return to the menu. Do not power off between ROMs, because the ED64 saves SRAM to the SD card on Reset.

| # | ROM | Runs for (console) | Log size | Measures |
|---|---|---|---|---|
| 1 | `kit-cpu` | 0.2 s | 8.6 KB | uncached and cached reads, register writes, the write buffer, D- and I-cache misses, RDRAM rows |
| 2 | `kit-vi` | 3.6 s | 1.7 KB | VI start after enable (#77), COUNT ticks per field |
| 3 | `kit-dma` | 1.1 s | 8.6 KB | memsets with VI on and off, SP DMA, PI DMA, SI DMA and joybus |
| 4 | `kit-hpos` | 0.2 s | 6.5 KB | uncached load latency against the VI line position |
| 5 | `kit-rdp` | 0.2 s | 6.5 KB | RDP syncs, setters, atomic primitives, rectangles, the command FIFO and fetch |
| 6 | `kit-span` | 0.2 s | 9.0 KB | span cost against width at 16 and 32 bpp |
| 7 | `kit-noise` | 0.2 s | 26.6 KB | RDP noise and dither patterns |
| 8 | `rdpstat-1prim` | 0.2 s | 0.9 KB | the 1PRIMITIVE stale read |
| 9 | `rdpstat-dpc` | 0.2 s | 0.5 KB | DPC DMA_BUSY and END_PENDING sequencing |
| 10 | `rdpstat-systemtest` | 0.2 s | 0.7 KB | n64-systemtest RDP status cases |
| 11 | `rdpstat-unsynced` | 0.2 s | 0.5 KB | unsynced combiner changes |
| 12 | `nemu64-timing` | 0.8 s | 25.5 KB | the nemu64-test timing cases |

The run times are the fork's emulated time from boot to the last line. The console's time is the same to within the boot time. Each log is under the 32 KiB SRAM size.

For each ROM:

1. Start the listener (SC64 only).
2. Start the ROM from the menu.
3. Wait until the screen shows text. The ROM then has finished. The first page starts with `#kit rom=<id>`, and the status line at the bottom reads `<id> page 1`.
4. Check that the log ends with a line `#kit-end rom=<id> bytes=<n> fnv=<hash>`. On the SC64 it is the last line of the listener output. On the screen it is on the last page.
5. Press Reset and return to the menu.

Then run these external ROMs. They are not in the repository. Each one has its own output, and you compare it by hand:

- **n64-systembench.** Build it with `tools/n64-timing/build-systembench.sh` from PR #83 (`feat/systembench`). Run it twice: once with one controller in port 1, and once with four controllers. Capture its ISViewer output. `tools/n64-timing/systembench/report.py` on that branch reads the output. These runs answer the `systembench` question, and they show where each TIMEIT_WHILE poll lands.
- **Thar0/RDP-Timing-Tests.** The romgen port's `--hw` build hangs in its first config on the fork, so run the original ROM as its README describes. It answers `thar0-console`.
- **snapper64** and **n64_pi_dma_test.** These are optional. They repeat published console data.

## Capture

Put every capture file for the session in one directory, for example `capture/`. ingest.py reads all of these formats, in any mix:

- SC64 listener output: `<rom>.isviewer.log`.
- SRAM saves from the SD card: `.srm`, `.sra` or `.sav`, in either byte order.
- Transcribed screen text: `<rom>.photo.txt`. Use this only when no other path works.

### Photo fallback

If neither USB nor SRAM works, film the screen. Each page shows for 8 seconds, and the pages loop. Film one full loop for each ROM. Make sure each frame shows the bottom status line (`<id> page <n>`), so the pages can be ordered. Then type the pages into `<rom>.photo.txt`, one screen line per text line. Join the lines that the 38-column screen wrapped. ingest.py checks the `#kit-end` byte count and FNV hash. A transcription with one wrong character is stored, but it is not compared.

## Ingest

Run:

```sh
tools/n64-timing/calibration/ingest.py capture/ --id console-<date>
```

The command does these things:

1. It parses every file and prints one line for each log, with the ROM, the record count, and `INCOMPLETE` when the footer is missing or does not match.
2. It stores every log under `docs/calibration/hardware/console-<date>/`, with a `manifest.tsv` that records each source file's SHA-256, the kit commit and `RI_REFRESH`.
3. It compares each question's points with the fork's run of the same ROM, under the question's rule. It then writes each result as the `hw:<question>` row of `docs/spec/n64-timing-results.tsv`.
4. It regenerates the spec and the inventory, and prints each behavior whose status changed.

To see what an ingestion would change without writing to the repository, add `--dry-run`. `tools/n64-timing/calibration/dry-run.sh <run.sh output>` runs the whole path on the fork's own logs as a fake capture.

## What to send back

- The `capture/` directory, as it is: the listener logs, the SD card saves and any videos or photos. The data comes from your console, so it can be committed.
- The output of `ingest.py`.
- Your console's details: the board revision (on the label under the console), the flashcart and its firmware or OS version, and the Expansion Pak.

## What each result will tell us

Each question in [inventory.md](inventory.md) has a `hw:<id>` result. A pass means the model's value agrees with your console under the question's rule. A fail gives the console's value and the model's range. The rows that the question closes then show what to change. These are the main questions:

- **The seven rows that wait only for calibration #16.**
  - `dcb` tells whether a cached access right after a cached store pays the +1 pclk (`cpu.dcb`).
  - `register-write` gives the posted RCP-register write cost per device (`sysad.register-write`).
  - `cmd-fifo-depth` gives how far DPC_CURRENT runs ahead of a frozen RDP. The model reads 240 B, and MiSTer uses 64 dwords (`rdp.cmd-fifo-dwords`).
  - `cmd-fetch-burst` gives the RDP command fetch size (`rdp.cmd-fetch-burst`).
  - `color-half-16bpp` tells whether a 16 bpp span half is 32 px or 16 px (`rdp.color-half-pixels-16bpp`).
  - `noise-alpha-dither` and `noise-dither-bits` tell which noise bits feed alpha dither, alpha compare and color dither.
- **#77.** `vi-first-line` tells when the VI starts its first line after an enable, and whether V_CURRENT holds while the VI is blanked. On the fork, V_CURRENT at the enable reads 524 (0x20C, the field's last line) for delays up to 1314 iterations, and 0 from 2000 iterations on. The answer decides whether the `mi-memset-rspdma` pass is real or depends on a model choice.
- **Fit-only rows.** `rdp-rect-base` checks the rectangle base, line gap and dead pixels against data that the Thar0 fit did not use. `sp-dma-direction` checks the read-direction SP DMA rate that `ri.overhead-read` was fitted to.
- **Open residuals.**
  - `vi-cpu-contention` gives the VI's delay on an isolated uncached load, by bank and line position (the model is about 2x the nemu64 means).
  - `memset-vi` tells whether n64brew's memset table was measured with the VI on.
  - `pi-dma-small` tells where the small PI DMAs lose 12 rclk.
  - `dirty-miss` and `nemu64-console` give the D-fill tail with the VI off (Load Miss mean 42.5 against the model's 41).
  - `stale-read` tells whether the 32 px 1PRIMITIVE case reads stale data on hardware.
  - `span-width` gives the span cost against width that the Thar0 IM_RD (+8 %) and Z (-5 %) residuals depend on.
- **Clock.** `count-per-field` gives COUNT ticks per NTSC field, which pins the X1 to X2 ratio and your console's crystal error (`clock.vclk`).

The inventory also lists the questions that have no kit ROM yet. Their `kit` column reads `none:`. These include write granularity, RI priority under DMA load, TMEM load rate, fill and copy rate, VI fetch per AA mode, exception entry costs and CACHE op costs. A follow-up unit adds their points to a kit ROM.
