# t17-fix report

Status: done. Branch feat/t17-fix, head 9c9b6e115, base master 9a4e98c42. PR https://github.com/wScottSh/ares/pull/73. Worktree /home/wscottsh/repos/ares-wt/t17-fix, build ~/n64-timing/build/t17-fix, private home ~/n64-timing/t17-fix-home (scratch, corpora symlinked). Raw: ~/n64-timing/results/t17-fix/{after,pidma-probe}. BEFORE = verify-72/head (ff7409b1b; code identical to master, diff is README only).

## Items
1. pidma:logs wired (prebuilt ROM, nothing built). standing.sh runs pi_dma_test.z64 (sha256 1d2c999c42ba..., pinned) 3000 frames with ARES_PILOG (46 s); pidma-replay.py --calibrated scores all 384 best-fit offsets. Result FAIL: 23770..23808/24000 within +-3%; worst band 8-31 B +14.97%, 32-63 +6.78%; ROM self-check 8 failures (capped, sizes 3-4). pi.block-bytes now fail. build-corpora gate removed.
2. Re-gates: rdp.cmd-fetch-burst -> calibration-16; rdp.cmd-fifo-dwords -> ~rdpstat:current-prefetch + calibration-16 (check source now says TODO comment); 5 legacy.si.dma-read-* -> guards of read64 totals + calibration-16; new bench:si-dma-read64-1..4 (37987/57972/77924/97890 rclk, systembench main.c:597-613 via dma-timing.md) decide si.read64-base (no-rom). legacy.pi.write-busy NOT deleted: verify-72 wrong, pi/bus.hpp writeWord still schedules pclk(200); pi.io-busy has no code (note says "not built"). New gate pending:report-only for report checks; dirty-row-sweep/dirty-miss-isolated sources name their reported values.
3. Guards: `~id` = can fail, never pass. det/stepcap must be `~` (lint). Model-choice rows with only guards -> status model-choice (ri.request-latency, scheduler.tie-rank, vi.fetch-overrun). Non-model-choice row with only guards = error. cpu.dcb -> calibration-16. rdp.color-half-pixels-16bpp -> calibration-16 (span-tri attach uses BPP_32; code derives 16bpp half from span-ram-half, row constant unused). Also found legacy.pif.step-quantum passing on stepcap alone -> ~stepcap + no-corpus; vi.register-sample -> report-only. Self-test: 4 rule cases + 5 row_status cases; master's row_status gives "pass" on two of them (checked).
4. Closure draft regenerated: Destination table (det pass; <=2 min pass, slowest filesel-rotate 102.897 s from committed mmbench/wall-budget.tsv = T16 medians; #11 fail, named 1.6884, empty 1.0113 pass; tools/bench item NOT DONE: mm-decomp-60fps tools/bench untracked, runs stock `ares` from PATH, records ~/src/ares = upstream ares-emulator, BENCH pin of func_80173B48 still in uncommitted game.c; fork's mmbench uses retail ROM where the function is unpinned). Failing checks section lists all 19 incl. the 3 thar0 fit-from configs (+8.07, +2.55, +2.43%). "Every behavior is built" assertion removed. Not posted.
5. harness:emux-bus (romgen rdpstat set emux-bus): CPU and RSP XPROFREAD 0x04RF. Head 4/4, build/t16 1/4, mutant ROM (RSP skips XPROFREAD) fails RSP test only. ROM sha 7bd9d203...
6. Results header now "standing run t17-fix/after on <commit>"; report.py prints run label. grep /home in docs/spec: none.

## Before/after rows (master -> branch)
pass 67->60, fail 30->31, fit only 10->10, model-choice 0->3, calibration-16 12->12, no-corpus 15->16, no-rom 14->7, report-only 0->10, build-corpora 1->0.
Moves: pass->model-choice ri.request-latency scheduler.tie-rank vi.fetch-overrun; pass->calibration-16 cpu.dcb rdp.color-half-pixels-16bpp; pass->no-corpus legacy.pif.step-quantum; pass->report-only vi.register-sample; build-corpora->fail pi.block-bytes; calibration-16->report-only ai.fetch-bytes clock.vclk cpu.dirty-miss-order cpu.ifill-stall cpu.wb-release rdp.fill-copy-rate rdp.tmem-load-rate vi.display-window vi.unfetched-sample; no-rom->calibration-16 5 legacy.si.dma-read-* rdp.cmd-fetch-burst rdp.cmd-fifo-dwords.
Checks (86): 49 pass, 19 fail, 10 no-rom, 8 report-only.

## Standing (measured)
--check ok, --self-test 34 ok, lint ok, ctest 9/9. MM 600 --stats md5 56e118e2... = before. nemu64 values.tsv x3 cmp-identical. 7 mmbench stats.tsv identical. ROM sha list identical + rdpstat-emux-bus. det/stepcap PASS (MM 29 files 8219 fields; nemu64 x3). Round trip + TMEM poke PASS. rdpstat 1prim 2/4 failed (as master). Load 1.7-3.4. MM wall not retimed (no emulator code change; header strings only).

## DEVIATIONS
- Results header names commit b7e4d49e9: the run used the working tree whose changes landed as 9c9b6e115 (same pattern as T17).
- New runner `harness` (rdpstat output reader) so a tool check gets a result without a behavior naming it.
- pidma pass rule: every calibrated offset must pass and ROM self-check SUCCESS.

## FOLLOW-UPS
- pi.io-busy is not built (code charges legacy 200 pclk). Scan for constants no code reads also lists cpu.pif-ram-read, si.read64-base, cpu.uncached-read-dword-total, sp.dma-rate-check (some are aggregates/check values; not individually verified).
- Write the bench si-dma ROM (now covers 5 checks).
- mm-decomp-60fps tools/bench item: decide whether to retire it in favor of mmbench, or do it.
No background process of mine running.
