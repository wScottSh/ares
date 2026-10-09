# not-built report

Status: done. Branch: feat/not-built. Head: b5c00fbff. Base: master a087b5d96. PR: https://github.com/wScottSh/ares/pull/74.
Worktree: /home/wscottsh/repos/ares-wt/not-built. Builds: ~/n64-timing/build/not-built and ~/n64-timing/build/not-built-base.
Homes: ~/n64-timing/not-built-home-{base,head}. Raw output: ~/n64-timing/results/not-built/{before,after}.
The base worktree I made for the BEFORE run is removed.

## Items

### 1. Rows whose constant no code read (9 rows)

| Row | Action |
|---|---|
| clock.unit | `static_assert(Behavior::ClockUnit == UnitsPerSecond)` in timing/timeline.cpp |
| ri.refresh-waits-for-burst | static_assert of the flag in RiBus::Channel (decide() runs only when the channel is free) |
| si.read64-base | pif/hle.cpp estimateTiming base now reads `SiRead64Base`. The duplicate legacy.si.dma-read-base row and its allowlist entry are deleted. |
| rdp.span-ram-segment | span phase mask `& (RdpSpanRamSegment/4 - 1)`. The comment says the 4 positions are measured at 32 bpp only. |
| rdp.color-half-pixels-16bpp | `halfPixels(image, bpp)` returns the row's value for a 16 bpp color image (32 = 64/2, as before) |
| pi.io-busy | not-built: the code charges legacy.pi.write-busy 200 pclk at pi/bus.hpp PI::writeWord |
| cpu.pif-ram-read | not-built: charged as an RCP register read (memory/io.hpp, 22 pclk). Inferred from reading the code; no ROM measures it. |
| cpu.uncached-read-dword-total | not-built: SysAD::read uses ReadPath for every size up to Dual, one octbyte either way, so it costs the same 32 pclk as a word read. Inferred from reading the code; no ROM. |
| sp.dma-rate-check | deleted. It was a check value: bench expected.tsv sp-dma-sweep wr-4096-off0 already asserts 6.5 with the n64brew source. |

I scanned the 47 rows without a constant.
- The 23 legacy rows (22 now) are pinned to their code sites by the literal lint.
- All 24 rule, order and map rows have code. 16 already cited their row id in code. I found the code for the other 8: cpu.random-rule (getControlRandom), vi.register-sample and vi.fetch-overrun (VI::startFetch), vi.unfetched-sample (VI::compose), vi.aa-mode-lines (Fetch::start never reads io.antialias), vi.display-window (VI::window), rdp.attribute-stage (rdp_haz_stage_offset), rdp.write-run (RDP::writeBack).
- No row without a constant lacks code.

### 2. not-built status in behaviors.py

- New `code` column. A row with a number is built when the core reads it as `Timing::Behavior::X`, or as the bare name in a file with `using namespace Timing::Behavior` (verify-73's grep missed those bare reads).
- A rule row names its code as `ares/n64/<path>:<symbol>`; --check requires the symbol to be in that file.
- A row whose value is unused reads `not-built: <text with path:symbol>`.
- Errors: no read and no code; a pointer that does not resolve; code or not-built on a row the code reads; a code column on a legacy row; a not-built row with no pointer.
- `row_status` returns not-built first, whatever the checks say.
- The spec has a Code column and a "Not built" section. The closure draft's first paragraph says "3 behaviors are not built: ..." and a "Behaviors not built" table follows. Pending checks of not-built rows are left out of the "pass, fail or fit only" table.
- report.py's status sentence names not-built.
- 8 new self-test cases. Each failure case asserts its own error message, and the committed tree must pass, so a check that stopped firing would fail its case. I did not run separate mutations of behaviors.py.

### 3. pidma

- calibrate(meas, printed, gold) no longer raises on an empty printed set. With nothing printed, the error is the number of timed points outside the ROM's own band (float32 0.1f, pi_dma_test.c:211). A difference array over read shifts makes this exact.
- The output for the current FAIL run is unchanged.
- `pidma-replay.py --self-test` has 5 cases. Case 1 is `calibrate({}, {}, {})`; the old code raised ValueError on that input. standing.sh runs the self-test under gen, and gen_result now requires each tool's "N cases, 0 failed" line.
- Data (measured, synthetic run at the golden midpoint, nothing printed): 7168 offsets fit, read shift -208..239 units (28 ticks), 830 of 24000 points fail at the worst offset. So the every-offset PASS rule cannot be reached from a SUCCESS run until the offset is pinned.
- The tick is not the cause. One tick is 0.6% of the 158-tick minimum at 8 B. The pidma:logs check source now records this.
- I did not change the verdict rule.

### 4. Gate wording

- calibration-16 now reads: "no check the program can run decides it: no hardware value is published, or the published one (a vendor figure, a test author's note, or a total over several rows that only guards each of them) has no corpus that measures this row". It covers cpu.dcb (vendor value) and the legacy.si.dma-read-* rows (guarded totals).
- mm:south-clock-town now says it reports fields per game frame and RSP busy clocks per field, and that none of these is published.
- Two more report-only sources failed the same rule. thar0:fill-mode now names the SDK's 8 B/rclk. bench:rdp-loadsz-sweep now names 8 B/rclk and the jgemu law.
- The rdp.tmem-load-rate reference said "0.418 B/clk", but jgemu-dpc-probe.md says 0.418 cycles per byte. The reference now says clocks per byte.

### 5. Self-test count

master printed 33 case lines (27 cases + --fix-lines + 5 status), so the 34 in t17-fix was a miscount. Each self-test now prints its own total. The new totals are behaviors.py 41/0 and pidma-replay 5/0.

## Rows whose status changed (master -> branch)

| Row | Before | After |
|---|---|---|
| cpu.pif-ram-read | pending:no-rom | not-built |
| cpu.uncached-read-dword-total | pending:no-rom | not-built |
| pi.io-busy | pending:no-rom | not-built |
| sp.dma-rate-check | fail | (deleted) |
| legacy.si.dma-read-base | pending:calibration-16 | (deleted, duplicate of si.read64-base) |

Rows go from 149 to 147. Counts: fail 31->30, not-built 0->3, no-rom 7->4, calibration-16 12->11; the rest are unchanged.
clock.unit, ri.refresh-waits-for-burst and rdp.span-ram-segment stay pass. The code now reads their values.

## Standing (measured, base and head run back to back, overlapping)

Load: base 1.43 -> 6.94, head 4.35 -> 1.58.

- MM 600 --stats md5 is 56e118e27192798c0710bcddd61a0b59 on both.
- nemu64 values.tsv for timing, cycle and cop0hazard: cmp identical. 7/7 mmbench stats.tsv identical.
- ROM sha256 lists (28 ROMs, rebuilt per tree) are identical; sha256 of the list file is d82b030d...
- behaviors.results() over before and after: 86/86 (check, result, detail) identical.
- det and stepcap PASS on both (MM 29 files, 8219 fields; nemu64 x3). Round trip PASS (150/300/457). TMEM poke PASS. ctest 9/9 on both.
- --check ok, lint ok.
- pidma FAIL 23770..23808/24000 on both.
- The other differences between the trees are host timings in rdp.txt, stderr and summary files, plus run labels.
- MM wall time was not retimed. The emulator change is behavior-preserving; md5 and trace_hash are identical.

## Regeneration

- --results comes from after/ (header "standing run not-built/after on d6f0aefaf"). That run's tree is d6f0aefaf, and b5c00fbff changes only docs and report.py.
- mm-bench.md was regenerated with report.py and the T16 wall-budget note.

## DEVIATIONS

- I deleted two rows (sp.dma-rate-check, legacy.si.dma-read-base) rather than relabel them: one was a check value already asserted in expected.tsv, the other a duplicate literal.
- clock.unit and ri.refresh-waits-for-burst are "read" through static_asserts. The code's own UnitsPerSecond and the decide() structure are what implement them. The static_assert makes a change to either value fail the build.
- The not-built pointers name a symbol, not a line, so they do not drift when lines move. The brief asked for file:line.
- report.py's status sentence was edited (a file outside the brief's named list) so mm-bench.md stays accurate.
- docs/design sketch behaviors.tsv and codemods/clock-rebase.py still mention sp.dma-rate-check. Both are historical, so I left them.

## FOLLOW-UPS

- pidma: log the ROM's COUNT reads (ARES_PILOG) so the offset is known. Until then a SUCCESS run cannot PASS the every-offset rule.
- Build pi.io-busy, cpu.pif-ram-read and the dword read path. Each needs a bench ROM (pi-io-write, pif-ram-read, uncached-sizes are no-rom).
- The span phase is 4 positions at 16 bpp too (Z, and 16 bpp color). Nothing measures that.

No background process of mine is running.
