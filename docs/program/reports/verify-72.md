# verify-72: PR #72 (T17, MM bench integration and spec assembly), head ff7409b1bd0ad7b6ebcc77eb1c8fec9ab7ec9db9, base master 6dfbf7166

**Verdict: PASS-WITH-NOTES. Recommendation: land, then a fix-up PR before the closure draft is posted.** No timing change, tooling reproduces byte for byte, counts reproduce. The notes are gate and label honesty (section 4) and closure-draft gaps (section 6). git merge-tree of head vs current master (246521057): clean, no README.md conflict.

Setup: worktrees ares-wt/verify-72 (head), verify-72-base (6dfbf7166); builds ~/n64-timing/build/verify-72-{base,head} (gcc, RelWithDebInfo); private N64_TIMING_HOME ~/n64-timing/verify-72-home-{base,head} (corpora and r29 symlinked read-only); all 27 suite ROMs rebuilt from each tree; results ~/n64-timing/results/verify-72/{head,base-full,base,pidma}. I ran head's standing.sh on head, and the same standing.sh (copied untracked into the base worktree, base has none) on base. Load at start of head run 10.6 (my own builds just finished), end 1.7. No background process of mine remains.

## 1. No timing change (measured)
- MM 600 --stats md5 56e118e27192798c0710bcddd61a0b59 on base (standalone run and standing) and head. 
- nemu64 values.tsv timing, cycle, cop0hazard: cmp identical base vs head. rom-sha256 lists identical base vs head and identical to the worker's t17/final (27 ROMs).
- All 7 mmbench scenes' stats.tsv identical base vs head. After stripping wall times and paths, the only differences across the whole results tree are additions (bus.tsv, behaviors.tsv, `bus start/end` event lines, 29 vs 27 files in det-mm/stepcap-mm). Nothing removed or changed besides wall times.
- det x3 nemu64 + MM PASS (29 files, 8219 fields); stepcap x3 + MM PASS; state round trip PASS (150/300/457); TMEM poke PASS; ctest 9/9 (head); behaviors --check, --self-test, lint-literals ok. rdpstat/snapper/bench/thar0/noise outputs equal base after normalizing wall time.
- mmbench parallel wall (7 scenes at once): head total 105.3 s (rotate 104.8), base 105.0 s (104.5). Under 120 s. I did not redo copied-runner interleaved MM wall timing; the parallel bench totals show no change.
- filesel_check on head: empty PASS 1.0113, Options PASS 1.0000, named FAIL 1.6884, rotation FAIL; "acceptance: FAIL".

## 2. Regeneration (measured)
standing.sh head into my dir, then `behaviors.py --results <dir>`, `behaviors.py`, `--check`: all ok. `git diff` against the PR: exactly one line in each of n64-timing-results.tsv, n64-timing.md, map-1-closure-draft.md, the "standing run <path> on <commit>" provenance line. Every check result and detail string (model numbers included) is byte-identical to what the PR commits. So no result differs from the worker's.

## 3. Counts (reproduced from my run)
81 checks: 48 pass / 18 fail / 8 pending:calibration-16 / 6 pending:no-rom / 1 pending:build-corpora (15 pending). 149 rows: 67 pass / 30 fail / 10 fit only / 12 calibration-16 / 15 no-corpus / 14 no-rom / 1 build-corpora. All as claimed. The binary's --behaviors table matches behaviors.tsv for 149/149 ids (basis, unit, verify). The mm-bench provenance table: 149 rows, bases match behaviors.tsv.

## 4. Gate honesty
Moves checked, then each of the 14 no-rom rows. Published-reference column: where a reference exists and where it is weak.

- cpu.dcb, sysad.register-write, rdp.noise-alpha-dither, rdp.noise-dither-bits to calibration-16: honest. No hardware measurement is published for the DCB +1 (vendor manual only), the register-write delay (MiSTer RTL only), or the noise-bit assignment (Angrylion vs MiSTer conflict, rdp-noise.md). Thar0 RDP-Noise datasets cover the LFSR, not these bits.
- removed pending:snapper-lfs: fine, the dumps exist and the check runs. Dangling mentions remain (snapper/compare.py:123, run.sh:7, README, plan.md:102); with the dumps missing, --results now errors with not-run, which is loud. Fine.
- new no-rom gate: right idea, derived mechanically (ROM missing from rom-sha256.txt). Per row:

| Row | Published reference? | Is no-rom the true reason? |
|---|---|---|
| cpu.uncached-read-dword-total 37 | yes, n64-systembench main.c:572-584 U64 read (cited value, ~/dma-timing, cpu-memory-costs) | yes |
| cpu.rcp-register-read 22 | yes, systembench VI_CONTROL read 24 minus about 2 harness | yes |
| cpu.pif-ram-read 1974 | yes, systembench PIF RAM read | yes |
| pi.io-busy 134 | yes, systembench PI I/O write busy | yes |
| si.write64 4065 | yes, systembench SI DMA 64 B to PIF (main.c:597-613) | yes |
| si.read64-base 13600 | yes for RD64B totals (systembench 37,987 / 57,972 / 77,924 / 97,890 RCP for 1..4 cmds; docs/research/dma-timing.md); but check bench:si-dma selects direction=write64 expecting 4065 only | partly: the ROM is missing AND the check would not test this row even with the ROM. Needs a read64 expectation |
| rdp.cmd-fifo-dwords 30 | weak. n64-systemtest src/tests/rdp/mod.rs:21-23 is a TODO comment ("CURRENT should advance up to START+240 ... even if the RDP is frozen"), an author's intent, not a recorded result (fetched with gh api) | yes in form, but the reference is a TODO note |
| rdp.cmd-fetch-burst 128 B | no. Row ref: "RI maximum; MiSTer fetches <= 22 words"; note says calibration #16. current-prefetch (START+240) measures FIFO depth, not burst size | no. Should be calibration-16 (or drop the check from this row) |
| legacy.pi.write-busy 200 | the check (pi-io-write 134) measures the replacement row; the legacy 200 is deleted by T8 | no-rom is formally true; moot |
| legacy.si.dma-read-base 13600 / controller 22000 / empty-port 18000 / accessory 20000 / short-command 1420 | no per-command hardware reference (the rows' own notes say so); only the 1..4-command totals are published, and the check does not encode them | no. no-corpus or calibration-16 fits; writing a write64 ROM does not decide them |

Net: 5 rows truly no-rom (published value, ROM missing), 1 partly (si.read64-base), 1 weak-reference (cmd-fifo-dwords), 7 mislabeled (cmd-fetch-burst, 5 legacy.si.*, legacy.pi.write-busy moot). The closure draft's "what closes it" for these (write a ROM) is wrong for 6-7 of 14.

- pidma:logs / pi.block-bytes "pending:build-corpora": not the true reason. The gate text says the corpus needs a libdragon or cargo build. pi_dma_test.z64 exists prebuilt (~/n64-timing/scratch/r29/clones/n64_pi_dma_test, golden logs in data/), and gates.md's resolution said to use prebuilt ROMs. I ran it on head: `ARES_PILOG=pi.log n64-run pi_dma_test.z64 --frames 300`, then pidma-replay.py pi.log <data> --sizes 8-382 --tolerance 0.03: 4214 points measured, 3404/24000 within +-3% (partial; 300 frames did not cover all points), worst deviation -9.43% in the 0-31 B band, consistent with bench:pi-dma-sizes failing at 8 B (196.0 vs 193). The reader `pidma_result` is a stub returning None (behaviors.py), so the check was never wired. Reason is unwired work, not a missing corpus. Likely fail, not pass, once wired (inferred; my run was partial). Affects pi.block-bytes plus pidma:logs pending inside pi.page-setup, pi.halfword-bias, pi.block-writeback (already fail).
- "report-only check => calibration-16": consistent with the plan (rdp-rectn "reported, not asserted", dirty-miss "report only"). The gate text "no public hardware value decides it" overstates for rows with a published value reported but not asserted: rdp-rectn (cen64 2021 / 80,287 vs model 2069 / 77,885, provenance doubted), dirty-row-sweep (datasheet 3 pclk vs model 2), dirty-miss-isolated clean (nemu64 41 vs 46 incl. harness). Text nit.
- Pass rows resting on a check that does not decide them (pref 21 / ruling 2). Fit-only labeling is correct for the 10 fit-only rows and fail takes precedence correctly. But:
  - cpu.dcb is "pass" while its own note says "nothing measures the +1 ... which only shows the stall does not fire elsewhere". Should be pending:calibration-16, not pass. The row_status rule ("pass if any non-fit check passes") cannot see this.
  - ri.request-latency, vi.fetch-overrun, scheduler.tie-rank, vi.register-sample: pass on det/stepcap only (determinism, not the value). For these model choices that is arguably their contract; vi.register-sample also carries a pending mm check. Label, not value.
  - rdp.color-half-pixels-16bpp (ref: "16 or 32 at 16 bpp, unmeasured", note "calibration #16") passes on snapper:span-tri; I did not test whether span-tri distinguishes 16 from 32 (the worker showed span-tri insensitive to lookahead depth), so that pass is unproven.
  - So 67 pass overstates by at least cpu.dcb, probably rdp.color-half-pixels-16bpp.
- thar0 strict min..max, no tolerance: correct per plan.md:127 ("each within the hardware min/max band ... residuals reported, not tuned away") and the exact-77,772 / 155,052 alpha-fail checks pass. Measured: 4 of 100 configs in band, 3 with min=max. The reader compares BUF only; plan R2 line 11 says BUFBUSY/PIPEBUSY, PIPE is ignored. Note, not blocker.

## 5. Bench report (mm-bench.md)
- Field times are T16's medians (39.270 / 55.948 / 81.334 / 67.071 / 102.897 / 63.097 / 60.669 s) and match the master README Run budget table exactly; host ms per field recomputes (39.27/852 = 46.09). Cites T16.
- Per-requester share, MiB, wait/burst, row misses: report.py rerun on my head mmbench dir reproduces everything from "## RDRAM channel" on byte for byte (deterministic counters). VI 7.3-7.4% and refresh 1.33-1.35% inside vi-fetch.md bands.
- Provenance table: 149 rows, bases equal behaviors.tsv.
- Hygiene: generated header carries the worker's local path (/home/wscottsh/n64-timing/results/t17/final).

## 6. Closure draft (map-1-closure-draft.md): not posted (gh issue 1 has 0 comments)
- Pending section: 42 rows with gate, matches (1 + 12 + 15 + 14).
- Failing section lists 30 rows, but only 15 of the 18 failing checks. Missing: thar0:nozb-vioff-imrd-1cyc (+8.07%), thar0:ac-zbsame-vioff-imrd-1cyc (+2.55%), thar0:ac-zcmp-zbsep-vioff-imrd-1cyc (+2.43%): the fit-from configs of rdp.mem-overhead-*/span-read-latency. The fit data itself is outside the console band; the draft hides that (only in the spec's Check results table).
- Absent vs map #1 Destination: determinism (PASS), 600-frame run <= 2 min (PASS), and the #11 acceptance "filesel empty <= 1.05 and named 1.90-2.10, both must pass" (named FAILS, 1.6884) appear nowhere as a headline; "MM bench integration: point tools/bench at the fork, remove the func_80173B48 pin" (Not yet specified list) is not addressed. Closing #1 on this draft would imply more than the results support.
- "What closes it" for the no-rom rows is wrong for the rows in section 4 above; pi.block-bytes reason wrong.
- "Every behavior is built from its reference" is an assertion, not a result; with 30 fail rows it needs the failure summary next to it (it follows).

## 7. Diff hygiene
- n64-run bus step / --behaviors, script.hpp: read-only, small, comment states what the columns are. emux 0x04RF: reads only; XPROF start/stop subtract/add per-requester counters like the existing rdram ones. MM md5 unchanged confirms no traced state moved.
- emux 0x04RF test: the worker's scratch ROM (results/t17/emux-bus.z64, sha 5e9d533b...) rerun by me: head 0 of 3 failed, base 2 of 3 failed (global CPU bursts do not grow, slot bursts 0). It is not committed to the repo, so nothing in the repo guards the new read (worker lists it as a follow-up). RSP path unexercised.
- behaviors.py: `--check` strengthening works. Self-test: 24 ok lines, 0 failing on head (worker said 26/26; I did not reconcile the 2). Mutation: in a scratch copy I disabled the "has no result" error; self-test then reports "a check with no result: FAILED". Dead code: `pidma_result` stub, ROM_FILES covers three runners only.
- checks.tsv: rdpstat:nosync-1cycle now target repeater64, selector "RDP 1-Cycle No-Sync", expect self: 20 of 20 pass against the pinned repeater64 console dumps (real console data, not fit). Not mutation-tested by me. rdpstat:current-prefetch expects 240 from the n64-systemtest TODO comment (section 4).
- Commit trailers name Opus 5.5 (disclosed).

## Not reproduced / not run
Copied-runner interleaved MM wall time (used parallel bench totals instead); worker's lookahead 1/16 throwaway builds; whether span-tri distinguishes half-pixel 16 vs 32; full pidma replay (my run partial, 300 frames); emux RSP path.

## Recommended follow-ups (fix-up PR before posting the closure draft)
1. Re-gate or wire pidma:logs (it is not build-corpora). 2. Move rdp.cmd-fetch-burst and the 5 legacy.si.dma-read-* to a truthful gate; add a read64 expectation to bench:si-dma. 3. cpu.dcb to pending; teach row_status that a check whose note says it does not measure the value cannot make pass (or add a per-row "decides" flag). 4. Closure draft: list all 18 failing checks, add Destination acceptance results (filesel named FAIL, det PASS, <= 2 min) and the tools/bench item. 5. Commit the emux XPROFREAD ROM test. 6. Drop absolute local paths from generated docs.
