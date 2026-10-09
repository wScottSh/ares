# calib-kit report

Status: done. Branch feat/calib-kit, head 6febf9e7d8ba95cef9daa4227c42a8b71d48a20e, PR https://github.com/wScottSh/ares/pull/85 (base master). Issue filed: https://github.com/wScottSh/ares/issues/84 (runner segfault in VI::compose on a mid-field VI blank and re-enable).

## Deliverables

1. Inventory. tools/n64-timing/calibration/questions.tsv has 45 questions (32 on an in-repo kit ROM, 5 ext:, 8 none:). behaviors.py writes docs/calibration/inventory.md from it, joined with every pending:calibration-16, fit-only, model-choice and report-only row and every failing or weak check. Each question is a hw:<id> check (checks.tsv suite row hw:*). The 7 bare pending:calibration-16 rows now name their hw check: cpu.dcb, sysad.register-write, rdp.cmd-fifo-dwords, rdp.cmd-fetch-burst, rdp.color-half-pixels-16bpp, rdp.noise-alpha-dither, rdp.noise-dither-bits. 24 other rows add one. --check rules: no bare pending:calibration-16, a row's hw check needs an in-repo kit ROM and must be in its question's closes column, and closes ids must exist. There are 4 new self-test cases, and the self-test passes 53/53.
2. Kit ROMs. romgen build.py --hw and hwout.py are the console output layer. Output goes to the ISViewer (fork stdout and SC64 USB), to 32 KiB SRAM through the ED64 header (flashcart SD), and to paged screen text. Each log has a #kit header (rom, sha, RI/MI registers) and a #kit-end bytes+FNV footer. suites/calib has 7 ROMs (kit-cpu, kit-vi, kit-dma, kit-hpos, kit-rdp, kit-span, kit-noise) that combine the bench ROMs with new points. Five --hw suite builds join them: rdpstat-1prim, rdpstat-dpc, rdpstat-systemtest, rdpstat-unsynced, nemu64-timing. calibration/run.sh builds them and runs each on the fork. The calib suite runs at 8 boot delays.
3. Ingestion. calibration/ingest.py CAPTURE_DIR [--id] [--model] [--dry-run] stores logs under docs/calibration/hardware/<id>/ with manifest.tsv, recomputes the hw: rows of n64-timing-results.tsv, regenerates the spec and prints the flips. calibration/dry-run.sh feeds the fork's own logs to it as a fake capture.
4. docs/calibration/hardware-run.md is the Diataxis how-to.

## Checks (measured, unicron, load 6-7)

- run.sh at head: 61 fork runs (7 ROMs x 8 delays + 5) in 16.9 s, every log has a valid #kit-end footer, the largest log is 26.6 KB (kit-noise), all under SRAM 32 KiB. Raw output is in ~/n64-timing/results/calib-kit/after/calib.
- dry-run.sh at head: 32 hw checks go from pending:calibration-16 to pass, and 15 behaviors flip. These are the 7 calibration-16 rows, the fit-only rows rdp.primitive-base, rdp.span-dead-pixels and rdp.span-line-gap, and the report-only rows clock.vclk, cpu.ifill-stall, cpu.dirty-miss-order, cpu.wb-release and pif.joybus-no-device. Failing rows stay fail. The cut log is stored and not compared, and the byte-swapped .srm parses. Raw output is in ~/n64-timing/results/calib-kit/after/dry-run.txt.
- Disagreement check: a capture with fifo-depth changed to 256 and a recomputed footer gives hw:cmd-fifo-depth fail "console [256] model [240]", and rdp.cmd-fifo-dwords goes to fail. The same edit without the footer recomputed is caught as INCOMPLETE.
- Determinism: kit-cpu, kit-vi and kit-noise logs are byte-identical over 2 runs. Two calib builds are byte-identical.
- Standing, base 253e1c8ea vs head, with nemu64 ROMs rebuilt in a private N64_TIMING_HOME: nemu64 values.tsv is identical for all 3 sets (ROM sha256 timing bd946fb1..., cycle ae9c83aa..., cop0hazard 9518d316...). MM --frames 600 --stats md5 is 9629185039701bddcdbd90c248a4f38b on both. MM wall time was not compared, because the only change is the verify strings in behaviors.hpp.
- behaviors.py --check: ok. romgen selftest: 72/72.

## Model readings the kit surfaced (fork, measured)

- fifo-depth: CURRENT - START = 240 while frozen.
- cmd-fetch: rect list max step 288 B, NOP list 376 B.
- span-width color half: 32 px at 16 bpp, 16 px at 32 bpp.
- vi-enable: V_CURRENT at enable is 524 for delays <= 1314 and 0 from 2000.
- count-fields: 783516..783530 ticks per field.

## DEVIATIONS

- The Thar0 port's --hw build hangs in its first config on the fork (emulated 3491 s, no progress). The cause is not found. thar0-console is ext:thar0, so the original ROM is run.
- k_vi_enable blanks only in vertical blank, to avoid the #84 segfault.
- ED64 X7 USB is not implemented. The SRAM-to-SD path covers it. These are unverified on a console: the ED64 save folder, write-back on Reset, the ED64 header honored by both menus, and the sc64deployer --isv option name. The doc says to confirm each one on the first ROM.
- systembench (PR #83) is still a draft and was not merged. It is referenced as ext:systembench.

## FOLLOW-UPS

- Write kit points for the none: questions: write granularity, RI priority under DMA, same-bank reorder, TMEM load rate, fill and copy rate, VI fetch per AA mode, exception entry, CACHE ops.
- joybus-pads needs a fork run with --controllers 4 before a 4-pad capture can be compared.
- Root-cause the thar0 --hw hang.
- Fix #84.
- A standing run should run calibration/run.sh into <run>/calib, so behaviors.py --results computes the hw rows after a capture lands. standing.sh is not changed.

No background processes left running (checked with ps).
