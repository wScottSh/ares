# t13-fix report: T13 follow-up (perf, dead code, rows, ADR) + T15 notes

Status: done. Branch feat/t13-fix, head 865ed0755, base master b7a876909. PR https://github.com/wScottSh/ares/pull/70 (open, base master).
Worktrees: /home/wscottsh/repos/ares-wt/t13-fix (head), ares-wt/t13-fix-base (master, detached). The throwaway worktrees t13-fix-chk (cross-check) and t13-fix-mut (sensitivity) are removed; their builds stay in ~/n64-timing/build/t13-fix-{chk,mut}. Builds: ~/n64-timing/build/t13-fix and build/t13-fix-base. Private homes: ~/n64-timing/t13-fix-home-{before,after,chk,mut}. Raw data: ~/n64-timing/results/t13-fix/{before,after,chk,wall,perf,mut,s2}. Drivers in the same directory: standing2.sh (standing.sh is the same script with the broken mmbench argument), extra.sh, compare.sh, wall.sh, mut.sh, perf/symdiff.py. No process of mine is still running (ps checked).

## Commits (each pushed)
1. 7517e7c69 rdp: cache readiness. `readiness()` returns `cachedReadiness`. `changed()` clears it at step start and end, kick, Port::granted, DPC writeWord, crash, power and the end of serialize. `nextStep()` is the old body, unchanged.
2. 26f897b72 engine: delete the async mode. `m_async_on` was always 0. Deleted: fences, m_async_* fields, the watermark fold, the image hazard, the async branches of Sync Full and pipeline_drain, and the COW half of the TMEM load gate (the gate now takes only rdp). -385 lines.
3. 5b4dc0812 behaviors: new rows rdp.span-slots (4) and rdp.port-lookahead (8), model-choice, with measured sensitivity. The code reads both from behaviors.hpp. The fit text is honest. filesel is split into mm:filesel-empty, mm:filesel-options (fit-from of mem-overhead-read/-write) and mm:filesel-named (independent). The TMEM-load assumption is added to mem-overhead-read. T15 notes: attribute-stage per-primitive fields, rdp.setter dispatch entry rule, and a sentence in the unsynced check's source (2-cycle cannot tell 22 from 24). The rdp_core.c derivation comment is fixed. Generated files are regenerated.
4. 865ed0755 ADR 0001: Implementation reconciliation records the 3 Decision 3 deviations with evidence. Decision 3 points at it.

## Acceptance (measured, base = master b7a876909)
- compare.sh before after: nemu64/bench/thar0/noise 42/42 files identical, including values.tsv x3. rdpstat.txt (systemtest 0/7, dpc 0/2, repeater64 0/21, 1prim 2/4, unsynced 0/2 failed), snapper.txt, ctest (9/9), rom-sha256 (all identical) and MM 600 --stats (md5 56e118e27192798c0710bcddd61a0b59, trace_hash included) are all identical. mmbench, all 7 scenes including the 4 filesel ones: 27/27 files identical. filesel_check: empty PASS, Options PASS, named FAIL (1.6884), rotation FAIL, as on master. noise:rect-1016 pass. thar0: 4/100 in band, mean 5.16%. bench: fail 7 / pass 14.
- det + stepcap: nemu64 x3 and MM (27 files, 8219 fields) PASS. Every file is byte-identical to master's except host-time files (rdp.txt, wall.tsv, mmbench.log). State round trip 150/300/457 PASS both sides.
- behaviors --check, --self-test and lint-literals ok on head. mem_misses=0, gclk_off_share 0.5927 (unchanged).
- Cache correctness: a throwaway build (master + commit 1, recomputing nextStep on every readiness call and aborting on a mismatch) ran the full standing set ("chk"). Its outputs are byte-identical to master, so it never aborted.
- Commit 2 alone: MM 600 --stats is identical (results/t13-fix/s2). The after standing covers all four commits together.

## MM wall (wall/summary.txt; copied runners, perf stat, interleaved x4, load 0.90-1.20)
- pre-T13 c8b8a31a7: 21.106 21.247 21.043 21.172, median 21.14 s, 397.1 G instructions, ~78.3 G cycles.
- master: 29.369 28.792 28.742 29.073, median 28.93 s, 480.2 G instructions, ~101.9 G cycles.
- head: 26.047 26.145 26.047 25.994, median 26.05 s, 441.8 G instructions, ~91.7 G cycles.
- Head is -2.9 s (-10%) against master. It recovers 37% of master's +7.8 s over pre-T13, and 46% of the +83 G instructions.
- perf (-F 999, quiet host, perf/{pq,bq,hq}.data). From master to head, readiness, span_peek, poly_manager_peek, Port::eligible and dispatchable fall from 2,940 to 591 samples (nextStep included): -2,040 of -2,523 total.
- The remaining +3,465 samples, head against pre-T13: Timeline::advance +642 and RI::run +485 (more steps; the step count is in trace_hash, so it is fixed). RDP actor bookkeeping about +1,300 (step 270, nextStep 142, prefetch 136, writeBack 136, pipeline 105, Port::post 107, dispatchable 87, eligible 63, span_peek+poly_peek 248). RDRAM window traffic about +250 (Writable::write 121, Debugger::write/readWord 131). State hash about +160 (rdp_render_serialize 116, XXH3 45). T14 NoiseLfsr::jump +76. Pixel shading is net flat.
- verify-67 predicted the cache would recover "most" of the +7.4 s. It recovered 37%: the scheduler peeks were about 2,000 samples, not 2,300, and the rest is modeling cost that follows the step count.

## Sensitivity runs (mut/, throwaway builds, thar0 + MM 600)
- span-slots: 2 gives 4.96%, 4 gives 5.16%, 8 gives 5.16%. In-band 4/100 at each. MM changes at 2 and at 8.
- port-lookahead: 1 gives 8.61% (in-band 6), 8 gives 5.16% (4), 16 gives 6.24% (5). MM at 16 is byte-identical to 8.

## Deviations
1. ri/bus.hpp:129-130 dp branch NOT collapsed. ri.overhead-rdp is 0 but ri.overhead-read is 4.5 rclk, so the read half is live. Only the write half is value-coincident, and collapsing it would couple RDP writes to the CPU/DMA write row. The brief's "redundant" premise is half wrong.
2. thar0:vi-on-separate-bank is renamed thar0:separate-bank, because its config is VI-off (verify-67 note). ri.arbitration also cites it.
3. The ri.overhead-rdp reference changes 0.5-1.5% to 0.5-1.6%, as hardware data shows: visame 1-cycle +1.60%, 2-cycle +0.98%; visep +0.59% and +0.54%.
4. The fit rows' verify/fit-from text describes VI-on as "not a clean independent check" but keeps those configs in verify (the parameters never saw them). It does not switch to verify-is-fit. The coordinator may want that stricter label.
5. Step 3 also includes the unsynced-check sentence (verify-69 follow-up, 22 vs 24). It was not in the brief's list.
6. Commit trailers use the session attribution (Claude Opus 5.5).

## Follow-ups
- rdp.port-lookahead is Thar0-sensitive and is the best of 1/8/16 on the fit data. T13 did not record how 8 was chosen, so it may be an unrecorded fit. rdp.span-slots at 2 beats 4 on Thar0. Neither is refit (out of scope).
- The TMEM COW ring (m_tmem_pool 64 x 4 KiB, m_tmem_cows) now only ever uses slot 0, and rdp_wq_busy has no caller. Deleting them touches poly_manager_serialize (the state format). That is a separate unit.
- Further perf headroom, unmeasured guesses: a bool-only span-pending query for busy(), dispatchable() and startLoad() (span_peek is about 170 samples), and the per-access RDRAM Debugger calls on window traffic (about 130).
- Residuals as listed in followups.md (2-cycle Z -11.8%, VI-same-bank Z, 32 px stale read, filesel named 1.69 and rotation, fb_hash diffs) are unchanged.

## For the next unit
- Any new code path that mutates state RDP::nextStep() reads (pipe, executor, fetch, ports, dpc.freeze/crashed, engine FIFO, span pool, Thread::clock) from outside RDP::step must call rdp.changed(), or the timeline sees a stale readiness. The mismatch-abort build (see chk in this report) is the way to prove a change.
