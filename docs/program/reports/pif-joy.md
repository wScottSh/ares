# pif-joy report

Status: done. Branch feat/pif-joy, head 33ad9d4fa, base master c7824c6da. PR: https://github.com/wScottSh/ares/pull/80.
Worktree: /home/wscottsh/repos/ares-wt/pif-joy. Builds: ~/n64-timing/build/pif-joy (head) and pif-joy-base (master). Homes: ~/n64-timing/pif-joy-home-{base,head,quick}. Raw: ~/n64-timing/results/pif-joy/{before,after,wall}. The base worktree has been removed. No processes of mine are running.

Commits:
- fb6fd61c3 adds benches.py SB_JOY_FRAMES and tools/n64-timing/joybus-fit.py. The bench ROMs are byte-identical.
- c4614ed03 rebuilds estimateTiming, adds the 6 rows and deletes the 4 legacy.si.dma-read-* rows and their allowlist entries.
- 33ad9d4fa regenerates the results, the spec, the closure draft and mm-bench.md, and adds a README line.

## What changed

`pif.estimateTiming` (the RD64B joybus phase) is rebuilt from the published n64-systembench totals, after the frame walk that n64brew PIF-NUS ("Joybus frame") describes:

- At most 5 channels are walked. 0xFE ends the frame. 0x00 and 0xFD skip a channel. 0xFF is a nop.
- Each handshake costs a fixed part plus 2000 rclk per wire byte. The 2000 comes from n64brew Joybus Protocol: 4 us per bit, 8 bits, 62.5 MHz. A present device pays tx + rx bytes. An empty port pays tx bytes and then times out.
- The old walk counted a 0xFE it never read after channel 5. That is why Empty 8B..63B all read the same as 4B (20728).

`tools/n64-timing/joybus-fit.py` solves the costs exactly from five totals and prints every other point:

| row | value (rclk) | basis | fit-from | independent checks |
|---|---|---|---|---|
| si.read64-base | 14109.5 (14145.5 less 36 that ares charges after the phase) | fit | Empty 0B, 4B, 8B | Empty 1B, 32B, 56B, 63B; Accessory |
| pif.joybus-skip | 1403.5 | fit | Empty 0B, 4B, 8B | Empty 1B, 32B, 56B, 63B |
| pif.joybus-escape | 884.5 (0xFE; 0xFF charged the same, inferred) | fit | Empty 0B, 4B, 8B | Empty 1B..63B; Accessory (one more 0xFF than 1J) |
| pif.joybus-byte | 2000 | derived (n64brew) | - | Accessory |
| pif.joybus-handshake | 12072.5 | fit | 1J | Accessory |
| pif.joybus-no-device | 17100.5 | fit, verify-is-fit | 2J, assuming one pad on port 1 | none (2J-4J are reports) |

The rig's controller presence is not published. Under a one-pad rig, 3J and 4J land at +0.04% and +0.05% (reports). Under a four-pad rig, 2J-1J (19985) would have to equal the present handshake that 1J-0B gives (22957). So the totals favor one pad. That is inferred, not proven, which is why 2J-4J stay report-only.

The four `legacy.si.dma-read-*` rows and their allowlist entries are deleted.

## Verification

Base is master c7824c6da (build `pif-joy-base`) and head is c4614ed03 (build `pif-joy`). Each ran `standing.sh` with a private `N64_TIMING_HOME`. Every suite ROM was rebuilt from its own tree, and the two ROM lists are identical: 655 ROMs, list sha256 71ab0f2838e4. Load was 13-17 for base and 17-21 for head. The raw runs are in `~/n64-timing/results/pif-joy/{before,after}`.

JOY points (bench, 32 boot delays, model range 0 at every delay):

| point | hw | base | head | head verdict |
|---|---|---|---|---|
| empty-0b | 15030 | 15060 | 15025 | pass (fit) |
| empty-1b | 16424 | 16481 fail | 16429 | pass |
| empty-4b | 20644 | 20728 fail | 20641 | pass (fit) |
| empty-8b | 21163 | 20728 fail | 21161 | pass (fit) |
| empty-32b | 21163 | 20728 fail | 21161 | pass |
| empty-56b | 21170 | 20728 fail | 21161 | pass |
| empty-63b | 21178 | 20728 fail | 21161 | pass |
| read64-1 (1J) | 37987 | 38477 fail | 37992 | pass (fit) |
| accessory | 36834 | 39898 fail | 36865 | pass (+0.08%) |
| read64-2 | 57972 | 57890 | 57977 | report (fit) |
| read64-3 | 77924 | 77321 | 77962 | report |
| read64-4 | 97890 | 96734 | 97948 | report |

The JOY end-poll is not walked. Every head pass clears its band edge by at least 25 rclk. That is more than one full 16.7 rclk poll period, so poll phase cannot flip these verdicts (inferred from the margins).

Standing values that moved. Each one moves because MM's controller poll is the 4J frame (one pad, three empty ports), and its RD64B now takes 1214 rclk longer (read64-4 96734 -> 97948).

- MM 600 `--stats`: md5 210d0d46 -> 96291850. Divergence starts at frame 46. fb_hash differs on 372 of 600 frames, rsp_busy_clocks on 548 and cpu_cycles on 187. cpu_cycles at frames 0 and 599 is identical.
- mmbench:
  - filesel-named 1.6798 -> 1.6941 fields per game frame (356 -> 353 gframes). Still fails the 1.90-2.10 target.
  - filesel-rotate 1.0896 -> 1.0908 (window 1157 -> 1155 fields).
  - RSP busy clocks per field: sct 1711067.9 -> 1708022.4, title 411477.0 -> 411383.2, filesel 499510.3 -> 499005.6, filesel-options 713483.8 -> 713289.5, field 1513777.0 -> 1513644.5.
  - filesel acceptance: FAIL on both, with the same PASS/FAIL rows.
- Unchanged:
  - nemu64 timing, cycle and cop0hazard `values.tsv` are byte-identical.
  - thar0 `compare.tsv` is byte-identical.
  - pidma: FAIL on both, 23776..23833/24000.
  - Every bench row outside the JOY points is identical.
  - rdpstat, snapper and noise: only host-time lines differ.
- det and stepcap PASS on both: MM (29 files, 8219 fields) and nemu64 x3. The round trip PASSes at 150/300/457, and the TMEM poke PASSes. ctest is 9/9.
- `--check` is ok. `--self-test` runs 49 cases with 0 failed. Lint is ok.
- Row status 36 fail / 67 pass -> 31 fail / 72 pass. Check results 27 fail / 63 pass -> 19 fail / 71 pass.
- MM wall: copied runners, 3 rounds interleaved, load 16.9-17.3. Base 26.46/26.47/26.51 s and head 26.37/26.54/26.47 s, so both medians are 26.47 s.

## Deviations

- `benches.py` now names the JOY frames (`SB_JOY_FRAMES`) so that `joybus-fit.py` reads the same blocks. The bench ROMs are byte-identical.
- `docs/spec/mm-bench.md` is regenerated from this run. `mmbench/report.py` only runs with `PYTHONPATH=tools/n64-timing`, because `behaviors.py` imports `romgen` (a pre-existing break, see follow-ups).
- The ares-side 36 rclk after the phase (RDRAM write and poll) is measured on master as the mean over the 8 JOY points (28..50).

## Follow-ups

- 0xFD and the TX skip/reset flags are charged as one skip. n64brew says the reset holds the line low for about 1 ms, and no total measures that.
- The cartridge channel (EEPROM/RTC) is charged like a controller handshake. No total measures it.
- The rig's controller presence for 2J-4J is unknown. If it is ever learned, pif.joybus-no-device gets a real check.
- `mmbench/report.py` fails with `ModuleNotFoundError: romgen` unless PYTHONPATH includes tools/n64-timing.

## For the next unit
- The MM baseline is now md5 96291850. Every poll RD64B is 1214 rclk longer.
- Fit provenance follows pref 21. Five totals are fit-from (Empty 0B/4B/8B, 1J, 2J). The independent checks are Empty 1B/32B/56B/63B and Accessory. pif.joybus-no-device is verify-is-fit because the rig's presence is assumed.
- No published total was left unexplained, and no per-case constant was needed. The only premise is the one-pad rig, which is inferred.
