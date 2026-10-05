# tools-fix: DONE
Branch feat/tools-fix, head 1531da34e, PR https://github.com/wScottSh/ares/pull/47 (base master; supersedes #42). Merged origin/feat/r3 (clean).
Raw: C:\Users\Scott\n64-timing\results\tools-fix\after\ (fresh build in build/tools-fix; no MM wall-time check run beyond determinism).

Checks (measured, fresh build, master engine)
- snapper: span-tri 432/432, test-mode-rw 32/32, fill-tri-sweep 2048/2048, rect-nosync 20+40+20=80/80
- determinism.sh MM: PASS, 17 files byte-identical, 3807 fields
- nemu64: timing 922 fail, cycle 9, cop0hazard 5 (922/9/5)
- behaviors.py --check ok; clock-rebase.py --check: 0 rewrite, 0 by hand
- state-roundtrip: normal run with /c/ OUT -> PASS both, exit 0. Unwritable save (OUT/state.bin is a dir) -> new: FAIL both lines, exit 1; old script: FAIL line then "round trip: PASS", exit 1.

Changes: snapper run.sh/README lose --rdp and -<rdp> dir suffix (no --cpu anywhere in tools/); state-roundtrip.sh cygpath -m + any failed step forces round-trip FAIL; clock-rebase.py vulkan SKIP entry removed.

DEVIATIONS: none. Unwritable path simulated via directory at state.bin (OUT drives all paths; stats must stay writable).
FOLLOW-UPS: docs/design/timing-core/plan.md still mentions --cpu/--rdp removal (historical, left). fill-tri-sweep full-byte compare still not run (verify-42 note 2).
