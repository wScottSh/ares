## verify-80: PASS-WITH-NOTES

Head 33ad9d4fa9e257fbb4233a855c7bb0f319f10432 vs base c7824c6da. Own worktrees and builds (`verify-80-{base,head}`), private N64_TIMING_HOME, every suite ROM rebuilt from its own tree (655 ROMs, list sha256 71ab0f2838e4, identical base/head). `standing.sh` on both, MM = baserom.z64. Raw: `~/n64-timing/results/verify-80/{base,head}`. Load 6.9-12 at the end of the runs.

**Reproduced as claimed (measured)**
- JOY table (bench, 32 boot delays, model range 0 at every delay): 12 of 63 bench rows changed, exactly the JOY points. head: empty-0b 15025, 1b 16429, 4b 20641, 8b/32b/56b/63b 21161, read64-1 37992, -2 57977, -3 77962, -4 97948, accessory 36865. Base values equal the report (e.g. accessory 39898). Min margin of a pass to its band edge: 25.1 (empty-0b), 25.4 (63b), 27.8 (1b), others 33-71. One poll period is 16.7 rclk, so an unwalked end-poll cannot flip these (inferred from the margins; the port's end-poll is not walked).
- MM 600 `--stats` md5 210d0d46 -> 96291850; first divergence frame 46; fb_hash differs on 372 frames, rsp_busy_clocks 548, cpu_cycles 187, trace_hash 554; cpu_cycles equal at frames 0 and 599. mmbench: filesel-named 1.6798 -> 1.6941 (356 -> 353 gframes, still fails 1.90-2.10), filesel-rotate 1.0896 -> 1.0908; RSP busy per field sct 1711067.9 -> 1708022.4, title 411477.0 -> 411383.2, filesel 499510.3 -> 499005.6, field 1513777.0 -> 1513644.5.
- Unchanged: nemu64 timing/cycle/cop0hazard `values.tsv` and thar0 `compare.tsv` byte-identical; pidma FAIL on both, 23776..23833/24000; all other bench rows identical.
- det, stepcap PASS on both (MM 29 files / 8219 fields; nemu64 x3); round trip PASS at 150/300/457; TMEM poke PASS; ctest 9/9 both; `behaviors.py --check`, `--self-test` (49 cases, 0 failed), lint-literals, pidma self-test ok. Regenerating `n64-timing-results.tsv` from my head run changes only its header line.
- `legacy.si.dma-read-{controller,empty-port,accessory,short-command}` rows and 4 allowlist entries are gone; no reference to them is left in ares/, tools/, docs/. Commit 1 touches no ares/ file; commits 2 and 3 share the head ares/ tree, which I built.

**Fit honesty (pref 21)**
- `joybus-fit.py` rerun: base 14145.5, skip 1403.5, escape 884.5, handshake 12072.5, no-device 17100.5 rclk (less 36 -> 14109.5). fit-from columns match the script: base/skip/escape from Empty 0B/4B/8B, handshake from 1J, no-device from 2J. There are 5 free parameters and 5 fit points, so the fit has zero residual degrees of freedom; pif.joybus-byte (2000) is fixed from n64brew, not fit.
- Genuinely independent numeric checks: 2. Empty 1B (+9.5 rclk) tests that skip cost is linear. Accessory (+37.5 rclk, +0.10%) tests escape minus byte cost only: handshake and base cancel in Accessory minus 1J (hw -1153, model -1115.5), so it cannot catch a handshake error and cannot separate the inferred 0xFF cost from the 2000 rclk byte.
- Not independent: Empty 32B/56B/63B have the same model coefficients as 8B (5 skips, no escape), so they predict 21163 by construction of the 5-channel cap. 32B (hw 21163) re-confirms the cap structure; 56B/63B pass only because the band is +-0.2% (hw is +7/+15 rclk over 8B, an unmodeled drift the spec does not mention). The spec and `behaviors.tsv` text "independent checks are Empty 1B, 32B, 56B and 63B and JOY Accessory" overstates this, and `pif.joybus-skip` / `-escape` list 32B/56B/63B as checks that cannot test them.
- 3J/4J (+0.04% / +0.05%) are two further predictions of the one-pad model; report-only is the conservative label and is correct.

**Structure vs reference** (n64brew is not quoted anywhere under docs/research; I fetched the pages live)
- PIF-NUS "Escape codes": 0x00 skip channel; 0xFD reset (line low 1 ms); 0xFE "finished, even before the fifth channel's handshake is parsed"; 0xFF nop, escape codes checked first. Joybus Protocol: "Zero, One, and the Controller Stop Bits are 4us long" (console stop bit 3 us). 8 x 4 us = 32 us = 2000 rclk is correct arithmetic; the stop bits fold into the handshake constant.
- Labeled inferred and consistent with that: 0xFF charged as 0xFE; cart channel charged as a controller handshake; skip/reset flag (0xC0) charged as one skip (n64brew gives ~520 us delay for bits 2/3 and a 1 ms reset; not charged, noted in the row). Unmodeled and not mentioned: n64brew says handshakes run channel 4 down to 0 (no effect on the totals).
- One-pad rig for 2J-4J: labeled inferred, 2J is verify-is-fit, 3J/4J reports. Evidence is real (3J/4J land within 0.05% after fitting 2J only).
- Unplanned behavior changes, both labeled in the rows: the cartridge channel is now charged by presence (old code always 20000), and a handshake with the 0xC0 flags is a skip. No plan.md unit covers PIF joybus.

**36 rclk ares-side offset**
It is the model's own post-phase charge (RDRAM write + poll), not a hardware quantity, so subtracting it avoids double counting; without it empty-0b would be 15066, above the band (15060.06). It is labeled in the row and the script. Recomputed on head from all 12 JOY points: measured minus estimateTiming = 29.5..42 (mean 35.5), so the constant 36 leaves up to about +-6 rclk in each fit point, and the fit is only as stable as ares' RDRAM-write and poll timing. Acceptable, not a blocker.

**Not done:** no wall-time comparison (the report's 26.47 s medians not reproduced); mmbench `wall_s total` under parallel base+head load was 112.7 base vs 112.1 head, which is not a timing measurement.

Recommendation: land. Ask for a wording fix in the next unit or a fixup: say the independent checks are Empty 1B and Accessory (escape minus byte only), and that 32B/56B/63B check the 5-channel cap, not the fit.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
