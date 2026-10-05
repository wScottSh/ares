# labels-t6: done
Branch feat/labels-t6, head 8449ce8609205193588057db45cb8a9a8afcd111, PR https://github.com/wScottSh/ares/pull/55 (base master).
Checks: behaviors.py --self-test --check ok; build.sh green; determinism.sh on MM PASS (27 files byte-identical, 8138 fields). Raw: C:\Users\Scott\n64-timing\results\labels-t6\after\.
Changes: ri.refresh-trigger note = explicit B11 vs nemu64 conflict (cites load-from-uncached-vi-off, load-miss-vi-off; model follows nemu64; reason). sysad.rdram-write-period / block-write-period: "inferred, not measured, to be VI fetch contention". cpu.dfill-total note: clean-row-miss assumption. vi.cpp:58-61 comment cites B11 conflict. hpp/spec regenerated.
DEVIATIONS: (a) sysad inference wording is in the reference column (that is where the text lived), not note. (b) ri.refresh-trigger basis left wiki; conflict in note. (c) "det unchanged" = determinism PASS on after only; no before run (comment/string-only diff, no code logic change). No MM wall time measured.
FOLLOW-UPS: none.
