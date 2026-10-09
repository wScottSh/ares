# verify-65: PR #65 (T7d fetch window and I-fills through SysAD)

Head 84e195217 (merges master 1a6a9de57), base master 1a6a9de57. Verifier: independent builds at ~/n64-timing/build/verify-65-{base,head,mut}; results ~/n64-timing/results/verify-65/. ROMs rebuilt by romgen from each worktree (cop0hazard/cycle ROM byte-identical to the worker's).

## Verdict: PASS-WITH-NOTES. Recommend landing; fix the notes in labels/docs (no code change required).

## Check items (measured)
- nemu64:cycle 7/13 failed -> 0/13 failed (all 7 SMC pass). Reproduced.
- nemu64 timing 11/1604 on both, same failing set (sorted, values stripped: identical). values.tsv: byte-identical base vs head (pass/fail only; no measured columns for passes). Only the failing sums move: VI-on false 41851->41865, true 41829->41851 (rows 4/5), VI-off 80400000 41001->41000. Other 10 sums unchanged. The I-fill 48->45 does not reach the timed loops (code is already cached), so little moves, as expected.
- cop0hazard 0/5 on both with the #64 ROM.
- MM boots both scenes: 7 mmbench scenes reach windows, det + stepcap PASS 27 files, 8146 fields (master 8158). Window starts move 1-2 fields earlier (title 250->249, filesel 441->440, sct 306->304, field 324->322 ...): cheaper I-fills make boot shorter, so 8158->8146 is explained by timing shift (12 fields over 7 scenes).

## Standing (base vs head, measured)
ctest 5/5 both; behaviors --check ok, --self-test ok, lint-literals ok; snapper all match, rdpstat 0/7 0/2 0/21 fail both, thar0 table identical; nemu64 det and stepcap PASS (timing 24, cycle 2, cop0hazard 1 fields); state round trip PASS (600 fields, saves 150/300/457), TMEM poke PASS (first diff field 31).
Bench: pass/fail statuses identical (10 fail / 11 pass / 19 report). NOT literally "identical": values move slightly (pi-dma cart-to-ram-8 197.33->196.0 still fail; uncached-vs-hpos bank2-vi median 34->36; dirty-miss-isolated dirty-single 46->48; setter-sweep 1.324->1.32; memset rows +-0.001). The worker's report says same rows; true for status, not for values.

## MM wall (interleaved base/head x4, 600 fields, load 8.1 -> 2.3)
base 19.745 19.528 19.698 19.809 (median 19.72); head 20.252 20.102 20.136 20.348 (median 20.19). +2.4%. cpu_instructions 730,765,610 -> 748,005,376 (+2.36%), ns/instr 26.7-27.2 both. So wall difference = extra emulated instructions (same 600 fields of emulated time; shorter fills leave more run time), not slower per-instruction. Worker's explanation confirmed. The "idle loops" part was not traced by me (inferred); instruction count and ns/instr are measured.

## Cause attributions for the 11
- C7 VI off x8: all eight sum exactly 41000 on head (41000/1000 = exactly 41 per miss, no tail). Expected 42.0-43.0 mean (a410..a7f8). cpu.dfill-total=41 is the hardware median (cpu-memory-costs.md), mean 42.5, so about 1.5 pclk mean tail per miss is absent. Row ri.refresh-trigger confirms refresh is modeled only while the VI is active, with a recorded source conflict (rdram-bus-arbitration B11 vs nemu64 VI-off data). Accurate and consistent with data. Caveat: that the missing tail IS refresh is a hypothesis (inferred); T6 evidence (35.5 vs 32.54 uncached overshoot) is the worker's/T6's, I did not rerun it. The "missing reference" statement (D-fill latency distribution or pre-VI-init refresh rate) is honest, though the mean 42.5 +-0.5 of the nemu64 test itself is the available reference and what is missing is the mechanism.
- C7 VI on x2 (41851/41865 vs 42250..44250) and C6 x1 (33 vs 35..37): VI-fetch contention, T11's. Consistent with the model lacking VI fetch contention (both are VI-on only); inferred, not provable until T11 lands.

## ifill 45 / provenance
- Derivation chain: Table 11-2 1+1+(1-2)+2+M+8+1 with M from Table 11-1 D-fill (cpu-memory-costs.md row 63, vr4300-wb.md row 66). I could not read the NEC manual (not on disk); I checked the arithmetic from the quoted formulas. D-fill stall = 41 - 1 issue = 40 = 7 + x + M (x in 1..2) gives x+M = 33. I-fill = 13 + x + M = **46**, independent of x. The research says "45-47" by taking x and M ranges independently; 45 is the low corner, which is not jointly consistent with the 40 D-fill (needs x+M=32). So "derived" is generous: the formula derivation gives 46 (if my reading of both tables as quoted is right); 45 is a pick at the bottom of the research range. nemu64-test's "~43 extra cycles" comment is a source comment, not an assertion. Without an asserting check (bench:ifill-isolated has no ROM) nothing separates 43/45/46/47. Recommend relabeling inferred (or correcting to 46 once someone verifies the tables in the PDF), with the 43-47 range stated in the note. Not a blocker: no check anywhere in the suite moves between 45 and 46 (unverified by me beyond the SMC/timing sets; I did not run a 46 build).
- Removing the 48-pclk I-cache Hit Write Back charge: no hardware reference. It follows the existing policy (cpu.cache-index-load-tag note: other CACHE ops without a measurement cost their issue slot); the writeback now goes through the write buffer like the D side. Label it as policy, not reference-supported.
- cpu.fetch-ahead-slots 2 (fit, fit-from smc-multiple-writes, verify smc-single-write). Reasoned from the ROM source (cycle.py/icache.rs): single-write tests (6,8) and (7,8): store 2 and 1 ahead of the line boundary at index 8, both expect old value. With 3 slots the fill would be even earlier relative to the store, so both still expect old: single-write cannot tell 2 from 3, only rules out <=1 (and under the store-first ordering). The mutation confirms it fails there. Multiple-writes (0x3f: first six SW seen) is the only 2-vs-3 discriminator and is the fit data. So the "verify" check is not independent for the value 2. The note says this honestly in prose; but per preference 21 the row should carry a `verify-is-fit:` note (and the spec label "fit only"). Flag as a note.
- Stores read first / CACHE: store ordering is tested (mutation below). Load-after-fetch ordering rests on the RSP "Clock CPU vs RDP" mutation (worker's, not rerun by me), CACHE read-first is untested; both labeled inferred in the row. Acceptable.

## Mutation (rerun by me)
Set readFirst=false (every store lands before the word two ahead is fetched), built at verify-65-mut: cycle fails 2 of 13: single-write a=0x2222 b=0x1111, multiple-writes a=0x7f b=0x3f. Matches worker. (Timing stays 11.)

## Diff hygiene
- pc/nextpc writes grep (ares/n64, excluding rsp/rdp): setPc callers: cpu.cpp:170 (power), exceptions.cpp:44 and 78 (exception, NMI/reset), interpreter-scc.cpp:309/312 (ERET), system.cpp:319 (pcOverride). All go through setPc, which flushes. Other writers: Pipeline::branch (nextpc, target), skip() (pc+=4), begin() (pc=nextpc), end() (ipu.pc=pc), all consistent with the vaddr-matched ring (fetchAhead re-reads pc if it moved; branches change nextpc before the slot is read). No bypass found. Load-state: window and head are serialized; Pipeline::power flushes.
- Stale-by-design cases: a TLB change or a debugger code write inside the two-instruction window leaves a stale word (hardware-like; no TLB-change check in take() for a translated slot). Not tested; low risk.
- Behavior change to note (not in plan, not covered by a check): instruction() now steps CpuIssue before the fetch fault is raised (master faulted without the issue step). One pclk extra before a fetch-fault exception. No suite value moved. Fix or document.
- Faulting fetch held in slot: slot.translated=false, re-devirtualized with exceptions at issue; correct for TLB-refill and address error (misaligned vaddr&3 too).
- SerializerVersion unchanged ("v153.8-dma"); layout gains window[2]+head. Precedent T7a/T7c. T11's PR bumps it, so old states break at that point regardless.
- CTC1 CE peek uses pipeline.next(), falls back to readDebug. Fine.
- Dead code: both legacy rows and allowlist lines removed; no leftovers. Comments explain whys.
- Overlap with T11: origin/feat/t11 changes behaviors.tsv only (different rows) among {sysad.hpp/.cpp, cpu.cpp, behaviors.tsv}; no textual sysad conflict today. A T11 refit of sysad periods touches different constants than IfillPath/ifill-stall, but IfillPath depends on wire(Read,4,CleanMiss) and MeanEdgeWait, so a refit there moves the I-fill path. Worktree ares-wt/t11 and t11-fix-base were clean when I looked.

## Not reproduced / not done
- Worker's perf stat bisect (cycles +1.3%/+2.3%, host IPC) not rerun; wall and instruction count reproduced.
- "Load waits behind I-fill" mutation (RSP Timing 133293) not rerun.
- NEC manual not available locally; the 46-vs-45 arithmetic uses the research docs' quoted formulas.

## Housekeeping
No background processes of mine remain (a stray find / was stopped via TaskStop). Worktrees ares-wt/verify-65, verify-65-base, verify-65-mut; builds under ~/n64-timing/build/verify-65-*.
