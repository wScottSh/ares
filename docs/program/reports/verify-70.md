# verify-70: PR #70 (t13-fix), head 865ed0755cac83c6b1569129c804661049019ddc, base master b7a876909

**Verdict: PASS-WITH-NOTES. Recommendation: land.** Notes are label/text items, none blocks. Nothing in the worker's report failed to reproduce.

Setup: worktrees ares-wt/verify-70 (head), verify-70-base (master), verify-70-pre13 (c8b8a31a7, source only; runner = verify-67-base build of the same commit), verify-70-chk and -chk2 (mutation builds). Builds ~/n64-timing/build/verify-70-{head,base,chk,chk2}. Private N64_TIMING_HOME ~/n64-timing/verify-70-home-{before,after,chk}; all 27 suite ROMs rebuilt from each tree with romgen/build.py (pref 25); sha256 lists identical before vs after (results/verify-70/{before,after}/rom-sha256.txt). Results ~/n64-timing/results/verify-70/. Drivers: the worker's standing2.sh / compare.sh / wall.sh with path edits only. Host load 0.96-1.8 during wall; standing runs share the box with their own parallel MM jobs (not timed). No background process of mine remains (ps checked).

## 1. Byte-identity vs master (measured, before = master, after = head)
- compare.sh before after: nemu64 + bench + thar0 + noise 42/42 files identical (values.tsv x3 included). rdpstat.txt, snapper.txt, ctest.txt, rom-sha256.txt identical. rdpstat: 0/7, 0/2, 0/21, unsynced 0/2, 1prim 2 of 4 failed (as on master). snapper span-tri 432/432. ctest 9/9 both sides. bench: fail 7, pass 14. noise:rect-1016 pass.
- MM 600 --stats md5 56e118e27192798c0710bcddd61a0b59 on both (trace_hash included). mem_misses=0 (stderr both runs). gclk_off_share 0.5927.
- mmbench, all 7 scenes: 27/27 files identical (excl. host-time wall.tsv, rdp.txt). filesel_check on head: empty PASS (1.0113, 98.9%), Options PASS (1.0000), named FAIL (1.6884, 68.8% at 2), rotation FAIL (rotation 5 has a 0-field frame). Same as the worker and as verify-67.
- det x3 nemu64 + MM PASS, stepcap x3 + MM PASS; det-mm and stepcap-mm dirs diff -r clean (71 files each, host-time files excluded). compare.sh prints "det-mm outputs DIFF" because its `cat $(ls)` hits subdirectories; that is a script bug, my recursive diff is the check.
- State round trip 150/300/457 PASS, TMEM poke PASS. behaviors --check/--self-test/lint-literals ok.
- thar0 mean |residual| of BUF avg 5.156% (own recompute from compare.tsv: 4.787% on 60 VI-off, 5.709% on 40 VI-on, matching the row text 4.79/5.71).

## 2. Readiness cache soundness
nextStep() reads: pipe.wake/current/count/chunk/chunkEnd, fetch.dwords/arrival, executor.busy/until, the three Ports (flights, posted, queue, freeAt via eligible()), dpc.freeze/crashed, the engine FIFO (need/next/drains/buffered), the span pool (span_peek), tmemLoad, Thread::clock.
Writers, by reading every mutation site: all pipe/fetch/executor/Port/engine/pool/tmemLoad writes are inside step(), startFetch/startLoad (called only from step and kick), or Port::granted. step() calls changed() at entry and exit, kick() after startFetch, granted() after its edits. dpc fields have one external writer, RDP::writeWord (RSP and CPU DPC register writes both arrive there); changed() follows dpc.write. Crash, power and serialize-end covered. Thread::clock for the RDP is written only in run() (before step) and power() (Thread::reset, followed by changed()). Nothing outside RDP calls rdp_render_* engine functions that feed readiness (engine.cpp wrappers are serialize/dps/image getters). I found no uncovered writer.
Residual note (not a bug): in power(), changed() precedes `dpc = {}` and engine reload; fine only because nothing calls readiness() inside power(). A changed() at the end would be sturdier. serialize() calls changed() at the end, so a load mid-span is covered.
Mutation check, rebuilt myself (verify-70-chk: head + readiness() recomputes nextStep() every call and abort()s if a cached value differs, returns the fresh value): full standing set (nemu64, bench, thar0, noise, rdpstat, snapper, MM 600, all mmbench scenes, det/stepcap, state round trip with loads at 150/300/457) ran without abort and every output is byte-identical to master (42/42, mm600 md5 equal, 27/27 mmbench). Detector is live: chk2 = chk with the changed() in Port::granted deleted aborts with "READINESS CACHE STALE" within 100 MM fields (exit 134). Not exercised by any suite: a DPC write from RSP code mid-span other than what MM does, reset after a crash. These are argued above, not run.

## 3. Dead code (-385 lines, rdp_core.c/h)
m_async_on: only stores in base are `atomic_store(&rdp->m_async_on, 0)` at rdp.c:170 and rdp_core.c:7436 (construct); no setter, no load that can be true. m_async_pending is set to 1 only on the branch gated by m_async_on (rdp_core.c:5399/5450 base). So every deleted fence/watermark/image-hazard/COW branch was unreachable. rdp_async_fence* had no caller outside the engine. No serializer line removed (diff has no deleted `s(`), serialize() added only changed(); ares/n64/system SerializerVersion untouched ("v153.11-noise") and round trip passes. Left behind, as the worker says: m_tmem_pool 64 x 4 KiB COW ring (only slot 0 is used) and rdp_wq_busy with no caller; deleting them touches the state format, separate unit.

## 4. Rows
- rdp.span-slots 4 model-choice: honest. Sensitivity 2 -> 4.96%, 4 and 8 -> 5.16% (worker's mut data; not rerun by me): 0.2 pt, in-band unchanged. Row says Thar0 does not favor 4 and T13 did not record why. Fine.
- rdp.port-lookahead 8 labeled model-choice: not fully honest. 1 -> 8.61% (in-band 6), 8 -> 5.16% (4), 16 -> 6.24% (5) is a 3.5 pt swing tuned toward the fit data, and the row's own text says "may have been chosen on" the fit data. Its verify column is thar0:imrd-1cycle (a fit-from config of the mem-overhead rows) and snapper:span-tri. Under pref 21 this is a fit row with no independent check, or it needs a verify-is-fit note. Recommend: relabel fit, fit-from = Thar0 VI-off, verify-is-fit with reason, or at minimum drop the model-choice label. Note-level, since the numbers and the sensitivity are stated in the text; the label is the only inaccuracy. (Not rerun: sensitivity builds; lookahead 1/16 not reproduced by me.)
- Fit text: mean 4.79% VI-off, 5.71% VI-on reproduced. Fit-from residuals +8.1 (cfg 2: 176749 vs 163555.5), +2.6, +2.4 (cfg 98 +4039.9/166378 = +2.43%) match. Named residuals nozb-visame-noimrd-1cyc -4.91% reproduced (-4019/81791); the other three (+4.0, -5.3, -4.7) from verify-67, not re-derived. "VI-on not a clean independent check" is right.
- mm:filesel split: empty and options fit data (they chose byte scaling), named independent and failing (1.6884 reproduced). Correct and well labeled; checks.tsv has the three ids.
- thar0:vi-on-separate-bank -> thar0:separate-bank: config zbrw-pass-zbsep-vioff-noimrd-1cyc is VI-off (name has vioff); model 225,260 vs hw 225,678.6 (-0.19%). Rename justified; all three row references updated.
- ri.overhead-rdp 0.5-1.6%: hardware VI-on/VI-off from compare.tsv: visame 1-cyc 81791.4/80499.7 = +1.60%, 2-cyc 158943.7/157393.0 = +0.99%, visep +0.59% / +0.54%. Matches.

## 5. ri/bus.hpp dp branch: worker is right
ri.overhead-read = 4.5 rclk (fit), ri.overhead-rdp = 0, ri.overhead-write = 0. bus.hpp trailer(): the Read arm picks RiOverheadRdp for dp requesters (0) over RiOverheadRead (4.5), so the read branch is live; only the write arm is value-coincident (RiOverheadRdp == RiOverheadWrite == 0). Collapsing would either change RDP reads (breaks byte-identity) or couple RDP writes to the CPU/DMA write row. Keeping it is correct. Verify-67's "redundant" was half wrong.

## 6. ADR 0001 amendment
Three deviations (halves never stall; one memory interface; 1PRIMITIVE counted from last span) match the code and verify-67. Evidence figures check against thar0 compare.tsv: 161,978 and 163,436 minimum over 240 lines = 674.9 and 681.0 rclk per line; VI-on write-only slowdowns 0.54-1.60%; atomic sweep 34.4 vs SDK 30-40 (bench report, rdp-atomic-sweep). The "about 7%" channel-held counterfactual is T13's estimate (in the ri.overhead-rdp row); I did not re-run it. The amendment says the evidence is one data point (1) and that VI-on data informed (2): honest. Decision 3 now points at the reconciliation section. Also removes the "(Empty until ...)" placeholder.

## 7. MM wall (copied runners, perf not needed; interleaved x4, load at start 0.96-1.83)
pre-T13 c8b8a31a7: 21.129 21.156 21.046 21.222, median 21.14 s.
master b7a876909: 29.329 28.459 28.554 28.523, median 28.54 s.
head 865ed0755: 25.923 25.978 25.946 26.009, median 25.96 s.
Head is -2.6 s (-9.0%) vs master; it recovers 35% of master's +7.4 s over pre-T13. Worker: 21.14 / 28.93 / 26.05. Master differs by 0.4 s (first master run 29.3 skews it; same load band). Still 4x under the 120 s budget; +23% over pre-T13 is modeling cost that follows the step count (worker's profile, not rerun).

## Diff findings
- ares/n64/rdp/engine/rdp.c:166-170: the comment about in-handler drains now sits above an empty gap where the m_async_on store was removed; harmless, trim the stray blank line.
- rdp_core.h comment above m_wait_lock reads fine after the cut.
- No timing constant without a row: Slots and the lookahead are now read from behaviors.hpp (rdp.hpp:102, timed.cpp:83).
- Scope creep: the unsynced-check sentence, rdp.setter and attribute-stage text are T15/verify-69 follow-ups the worker disclosed; they are documentation only.
- Commit trailers name Opus 5.5 (worker disclosed); cosmetic.

## Not reproduced / not run
Worker's span-slots and lookahead sensitivity builds, the perf sample tables, the 7% estimate. Hardware-only items unavailable.
