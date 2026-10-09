# Handoff: timing-model program, 2026-10-09 (unicron)

All plan units are landed on master (wScottSh/ares 7664d395b). Nothing is running. One PR is open and waits on Scott: wScottSh/mm-decomp-60fps#1.

## Landed this session (PRs, each with an independent sonnet verdict in ledger.tsv)

- #60 L0 Linux harness port. #61 T7b exceptions. #62 T7c CP0 timing. #64 cop0hazard ROM order. #65 T7d fetch window and I-fills.
- #63 T11 VI fetch on the bus (first head failed verify-63 on accuracy; fixed, re-verified twice, merged with T7d).
- #66 CPU provenance labels. #67 T13 RDP memory interface. #68 T14 noise LFSR. #69 T15 unsynced attribute sampling. #70 t13-fix (RDP readiness cache, -9% MM wall).
- #71 T16 run budget (all scenes < 120 s; slowest filesel-rotate 102.9 s). #72 T17 spec assembly and closure draft.
- #73 t17-fix (honest gates, pidma wired). #74 not-built status. #75/#76 systembench ports and builds (PIF RAM read, dword read, PI I/O read and write busy, SI I/O, SI write64 ROM). #78 phase walk and per-check verdict rules. #79 consistent-only / pass-conditional labels. #80 joybus/PIF timing from systembench totals.

## Where the numbers stand (master ce3b475d7, measured by verifiers)

- Spec: 149 behaviors: 72 pass, 31 fail, 10 fit only, 3 model-choice, 7 pending:calibration-16, 15 pending:no-corpus, 11 pending:report-only. Every behavior is built (behaviors.py --check enforces a code read or pointer per row).
- nemu64 failures: timing 9 / 1604 (C7 Load Miss VI-off x8: D-fill has no tail; 20.0 same-bank VI-on mean), cycle 0 / 13, cop0hazard 0 / 5.
- snapper 2592 / 2592. rdpstat 0/7, 0/2, 0/21; 1prim 2/4 (its expectation is a cen64 extrapolation, not hardware). thar0 4/100 inside the strict console min..max, mean |residual| about 5%.
- Map #1 Destination: determinism pass; <= 2 min pass; file select #11 FAIL (named files 1.6941 vs 1.90-2.10; empty 1.0113 pass); tools/bench item not done (gate tools-bench).
- Closure draft: docs/spec/map-1-closure-draft.md (generated, not posted to #1).


## Landed 2026-10-09 (after Scott's rulings, preferences 28-29)

- #83 systembench: original n64-systembench built with libdragon in docker, run on the fork, pointwise checks.
- #88 sysbench-era: hardware-era build (50f5066, GCC 12.2, tie fix) is the binary the checks run. Five model-error candidates remain (PI I/O W -4, SI I/O W -8, SI DMA W ROM -4, PI DMA 8 -6, PI DMA 128 -11 fit data); only the #16 same-binary run gives them an independent check. Nothing refit.
- #85 calibration kit for #16: docs/calibration/hardware-run.md (procedure), docs/calibration/inventory.md (224 entries: 208 questions, 7 not hardware-decidable, 9 not decidable by this kit), tools/n64-timing/calibration/ingest.py. --check enforces coverage. Dry run: 76 of 80 hw checks pass on the emulator's own logs.
- wScottSh/mm-decomp-60fps#1: tools/bench on the fork, func_80173B48 pin removed. Verified (verify-mm1), NOT merged: gate mm-bench-merge (Scott merges; it puts his uncommitted bench harness on main).
- Issues filed: #82 RSP halted cycles always 0, #84 VI::compose segfault on mid-field blank, #86 RDP hazard tail, #87 Watch exception never fires.

## Open gates (Scott)

- mm-bench-merge: merge wScottSh/mm-decomp-60fps#1 when ready (tools-bench and systembench-build were resolved 2026-10-09).
- #16 hardware calibration run: deferred by Scott; the kit is ready (see above). It decides the filesel named-files gap, the VI-vs-CPU contention strength, the D-fill tail, thar0 residuals, the first VI line after enable (#77), noise questions, pidma offset.

## Next work if resumed

followups.md lists everything parked, newest at the bottom. The cheap, reference-backed ones: verify-80 wording fix on joybus independent checks; U32R banked cause; pidma COUNT logging to pin the offset; mmbench/report.py PYTHONPATH break; rdp.port-lookahead / span-slots sensitivity notes.

## How to resume

Store: ~/.claude/orchestrate/ares-n64-timing/ (preferences.md lines 1-27 are the standing orders). orch CLI needs bun (~/.npm-global/bin/bun). One command reruns every standing check: tools/n64-timing/standing.sh, then behaviors.py --results <dir>. Workers opus, verifiers sonnet, medium effort; verifiers never touch the coordinator checkout (verify-pr.md step 2).
