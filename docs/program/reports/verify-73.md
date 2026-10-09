# verify-73: PR #73 (t17-fix)

PR comment: https://github.com/wScottSh/ares/pull/73#issuecomment-6066786007. Raw: ~/n64-timing/results/verify-73/{head,base}, worktrees ~/repos/ares-wt/verify-73{,-base}, builds ~/n64-timing/build/verify-73-{base,head}.

## verify-73: PASS-WITH-NOTES (head 9c9b6e115579fb787ceb85ff8cd2144f5a589f7a, base master 9a4e98c42)

Recommendation: land. Fix the notes below before the closure draft is posted on #1. Independent run: own worktrees, builds (gcc, RelWithDebInfo), private N64_TIMING_HOME, all suite ROMs rebuilt from each tree. `standing.sh` ran on head and on base (head's script, pidma included), back to back, load 1.6-4.8 at start.

### 1. No timing change (measured, base vs head)
- MM 600 `--stats` md5 56e118e27192798c0710bcddd61a0b59 on both.
- nemu64 values.tsv timing, cycle, cop0hazard: `cmp` identical. All 7 mmbench stats.tsv identical. bench/rdpstat/snapper/thar0/noise values identical. ROM sha256 lists identical except head's added rdpstat-emux-bus (7bd9d203..., matches the report). Remaining diffs across the results trees: wall-time strings and the --behaviors table columns.
- det x3 + MM PASS (29 files, 8219 fields); stepcap x3 + MM PASS; state round trip PASS (150/300/457); TMEM poke PASS; ctest 9/9 on both.
- Parallel mmbench wall (7 scenes at once): head 104.7 s total, filesel-rotate 104.2; base 103.5 for rotate.

### 2. Regeneration
`behaviors.py --results <my head run>`, `behaviors.py`, `--check`: ok. `git diff` = exactly one line in each of n64-timing-results.tsv, n64-timing.md, map-1-closure-draft.md (the provenance line). Every result and detail string, the counts (31 fail / 10 fit only / 3 model-choice / 60 pass / 12 cal-16 / 16 no-corpus / 7 no-rom / 10 report-only; 86 checks) reproduce. `--self-test`: 33 ok lines, 0 failing (report says 34; not reconciled, 33 lines printed). Mutation: removing the "every check is a guard" rule fails exactly `only guards on a row that is not a model choice`; making a guard able to pass fails the three row_status cases.

### 3. pidma
Prebuilt `pi_dma_test.z64` (sha256 1d2c999c... checked by `sha256sum -c` in standing.sh) is run; nothing is built. It is a committed binary in rasky/n64_pi_dma_test (`git ls-files` lists it, tree clean, no LICENSE file in that repo), kept outside ares and not committed; the spec says so. Reproduced: `FAIL 23770..23808/24000`, worst offset (167,15), bands 0-31 +14.97%, 32-63 +6.78%, ROM self-check 8 failures (the ROM stops counting timing failures at 8, pi_dma_test.c:217; they are sizes 3-4, outside the replay range).
Rule "all calibrated offsets within 3% and self-check SUCCESS": conservative and deterministic (scores the worst of 384 best-fit offsets; the offsets are fit to the ROM's own printed values, not to hardware). One bug: `calibrate()` takes `max()` over the ROM's printed failures; when the ROM reports SUCCESS nothing is printed and it raises `ValueError: max() iterable argument is empty` (reproduced on `calibrate({}, {})`). So the PASS the rule describes cannot be reached. It surfaces as a loud not-run, not a false pass, and matters only once the model passes. Tick quantization (16 units) against a 3% band at 8-31 B is a second risk of failing a perfect model (inferred, not tested).

### 4. Gates
- `legacy.pi.write-busy` is live: `ares/n64/pi/bus.hpp:77` `scheduleAfter(EventKind::PI_BUS_Write, pclk(200))`. verify-72 was wrong; the worker's correction stands. `pi.io-busy` (134 rclk) has no reader (grep of `PiIoBusy`: nothing).
- Re-gated rows match their reasons: cpu.dcb, rdp.color-half-pixels-16bpp (snapper attach is BPP_32, cases.py:30,110), rdp.cmd-fetch-burst, rdp.cmd-fifo-dwords (TODO-comment reference), the 5 legacy.si.dma-read-*, 3 model-choice rows, legacy.pif.step-quantum, build-corpora -> fail. Gate text nits: `report-only` text promises the source names the published value or says none exists, but `mm:south-clock-town` (behind clock.vclk, ai.fetch-bytes, vi.register-sample, vi.unfetched-sample, vi.display-window) says neither; `calibration-16` text says "no public hardware value" for the legacy.si.dma-read-* rows that have published 1..4-command totals (guards).
- Rows whose value no code reads (behaviors.hpp constants vs uses under ares/ and tools/, 9 of 102):
  - pass: `clock.unit` (core uses its own literal `UnitsPerSecond = 750'000'000`, clock.hpp:30), `ri.refresh-waits-for-burst` (flag; the no-preemption behavior is structural, nothing reads the flag), `rdp.span-ram-segment` (16 B; passes via snapper:span-tri).
  - fail: `sp.dma-rate-check` (6.5 B/rclk is the check's expected value, not a charge).
  - pending:no-rom: `cpu.uncached-read-dword-total` 37, `cpu.pif-ram-read` 1974, `pi.io-busy` 134 (core charges legacy 200 pclk), `si.read64-base` 13600 (hle.cpp:203 hardcodes it).
  - pending:calibration-16: `rdp.color-half-pixels-16bpp` (derived from RdpSpanRamHalf in code).
  Under pref 2 these are specs not built from their table; the three pass rows overstate. I did not scan the 47 rows with no constant (rules, orders, maps, legacy) and did not trace what core charges for a PIF RAM or dword read.

### 5. Closure draft
Counts, the 19 failing checks (incl. the 3 thar0 fit-from configs +8.07/+2.55/+2.43%), residuals, Destination table all match my run. Pending closing conditions are right except the gate-text nits above. Destination "<= 2 min" cites the committed T16 median table (filesel-rotate 102.897 s), not this run; my parallel run is consistent. tools/bench claim verified read-only in mm-decomp-60fps: tools/bench untracked at 56fa21dd0, bench.py runs `ares` from PATH via tools/ares/ares-headless.sh and records ~/src/ares (origin ares-emulator/ares), `func_80173B48` pin under `#if BENCH` in uncommitted game.c. "not done" is true. Not posted: #1 has 0 comments.

### 6. harness:emux-bus
Head 4/4. Mutant runner with `cpu.XPROFREAD(slot, metric)` removed from `RSP::XPROFREAD` (rsp/emux.cpp:215): 3/4, only "RSP XPROFREAD global CPU bursts grow" fails (a=0x420 b=0x420). Head rebuilt and 4/4 again.

### 7. Hygiene
`grep /home docs/spec tools/n64-timing/mmbench/README.md`: none. No binaries in the diff. No background process of mine remains.

Not reproduced: copied-runner interleaved MM wall timing (no emulator code change; parallel totals used).

### Follow-ups for a fix-up PR
1. pidma-replay.py calibrate(): handle an empty printed set (self-check SUCCESS) so PASS is reachable.
2. Pass/pending rows with unread values (item 4): wire the constants (clock.unit, ri.refresh-waits-for-burst, rdp.span-ram-segment, pi.io-busy) or mark them not built; sp.dma-rate-check is a check value.
3. Gate texts: report-only and calibration-16 wording vs the rows they hold; give mm:south-clock-town a source naming its reported value or none.
4. Reconcile self-test count (33 vs 34 claimed).
