# Handoff: timing-model program, 2026-10-08 (unicron)

All plan units are landed on master (wScottSh/ares ce3b475d7). Nothing is running and no PR is open.

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

## Open gates (Scott)

- tools-bench: port mm-decomp-60fps tools/bench to the fork and drop the func_80173B48 pin, or retire it for mmbench. Default: retire.
- systembench-build: allow building rasky/n64-systembench with libdragon so bench numbers can be compared pointwise instead of consistent-with over poll phase. Default: skip.
- #16 hardware calibration run (unchanged). It decides the filesel named-files gap, the VI-vs-CPU contention strength, the D-fill tail, thar0 residuals, the first VI line after enable (#77), noise questions, pidma offset.

## Next work if resumed

followups.md lists everything parked, newest at the bottom. The cheap, reference-backed ones: verify-80 wording fix on joybus independent checks; U32R banked cause; pidma COUNT logging to pin the offset; mmbench/report.py PYTHONPATH break; rdp.port-lookahead / span-slots sensitivity notes.

## How to resume

Store: ~/.claude/orchestrate/ares-n64-timing/ (preferences.md lines 1-27 are the standing orders). orch CLI needs bun (~/.npm-global/bin/bun). One command reruns every standing check: tools/n64-timing/standing.sh, then behaviors.py --results <dir>. Workers opus, verifiers sonnet, medium effort; verifiers never touch the coordinator checkout (verify-pr.md step 2).
