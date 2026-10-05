# Unit tools-integrate report

- **Branch:** feat/tools (worktree C:\Users\Scott\repos\ares-wt\tools), from origin/feat/romgen @16884f97c; merged feat/r1, feat/r2, feat/r4 (merge commits).
- **Head:** 52bc154baf593a57a78dfcb0a0a8c8280af9b537
- **PR:** https://github.com/wScottSh/ares/pull/41 (base feat/romgen)
- **Verdict comments:** #38 PASS, #39 PASS-WITH-NOTES, #37 PASS-WITH-NOTES.
- **Evidence:** C:\Users\Scott\n64-timing\results\tools\{merged,refactored} (step2, step3 are intermediates); scripts verify-all.sh, compare.sh, buildall.sh in that dir. Runner: build.sh into build\tools (interpreter).

## Merge
Conflicts: build.py (docstring, suite_sets; kept R4's variant which re-raises real import errors) and romgen README table (kept both rows). Nothing else.

## Verdicts (measured, runner from this tree, --cpu interpreter)
- **nemu64:** 924/1604, 9/13, 5/5 failed; categories C1-C11 unchanged (439 204 172 50 14 11 10 10 9 3 2, other 0).
- **bench (R1) PASS:** 13/13 ROMs exit emux-exit, 138/138 points, format ok, expected pass 2 / fail 19 / report 19, selftest 7/7, builds deterministic, two runs identical.
- **thar0 (R2) PASS-WITH-NOTES:** 100/100 specs reported, deltas -1, selftest 0 failures. expected.tsv equals compare.py hw_data x62500 for 100/100 rows and sample_results.txt 100/100 in order. Notes: RUNS=32 not 1000; runner "Failed 0 of 100" only counts specs.
- **rdpstat (R4) PASS-WITH-NOTES:** none 4/7, 2/2, 21/21 failed; vulkan 0/7, 2/2, 21/21. stdout byte-identical to R4's recorded runs. 5 SHA-256 pins recomputed independently (cases 08, 0a, 0f, 10, 13) match; builder checks all 20 each build.
- Spot checks bench: n64brew MIPS_Interface memset table (25.7, 49.8, 2.58, 3.80 ms), systembench main.c PI DMA 193/1591/12168/777807, nemu64-test cache.rs:304 (36); derived 18.38 and 71.24 recomputed.

## Refactor (before = merged, after = refactored)
1. **One RDP builder:** rcp.py now has all encoders, DPC/SP map, DisplayList; bench/rdp.py and rdpstat/rdp.py deleted. Commands are 64-bit ints. ROM bytes identical except the opcode byte gains the GBI 0xC0 prefix in bench rdp ROMs and rdpstat ROMs (thar0 already had it): verified over 13475 differing bytes in 7 ROMs, every diff is byte|0xC0. Results step2 vs step1: all 33 compared files identical (incl. bench).
2. **Runtime boot** calls pif_terminate_boot (routine moved from rcp.py into runtime.py; thar0 no longer calls it). nemu64 ROM bytes change; nemu64 values.tsv/categories/stdout identical to merged.
3. **Decoupled:** step_measure, run_measurement, measure_slot_constants and loop templates moved from runtime.py to suites/nemu64/measure.py (measure.asm()); stub labels removed from bench; thar0/rdpstat sets no longer link nemu64 templates.
- Result after all three: nemu64 (all 3 sets values.tsv + timing categories + stdout except cop0hazard absolute addresses), thar0 (stdout, compare.tsv), rdpstat (stdout, values.tsv) byte-identical. Bench verdicts all identical.
- Determinism: final tree builds twice cmp-identical for all 4 suites (47 files); the ROMs verified are those hashes. Run determinism: second full run of all suites identical (33 files).

## Deviations / findings
- **Layout sensitivity (found, fixed):** after step 3 alone, nemu64 value 22.0 "RSP Timing: Clock CPU vs RDP" flipped pass to fail (a=0x208b8, range 0x208c1..0x208e9). Cause: the polling loop's I-cache line alignment (loop moved from 0x80001c2c to 0x800017f4, mod 32: 12 to 20). Fix: .align 32 before step_dp_clock_vs_cpu (it sat on a line boundary by luck before). The alignment link is from symbol addresses plus the restored result, not from a cache trace.
- **Bench numbers drift with code layout:** 19 of 40 result rows changed value (e.g. cached memset 58.334 to 58.3345 ms/MiB; single-sample pclk 44 to 46); all verdicts unchanged. Step 3 is a pure move and already produces the drift, so layout (not the PIF write) is the cause (inferred from that, not traced).
- cop0hazard stdout differs only in absolute EPC/ExceptPC addresses (ROM layout).
- nop is now 0xC0000000 (gsDPNoOp) instead of 0; no result change.
- Windows CRLF warnings from git autocrlf on edited files; diffs are clean.
- Not done: no-comments pass; mutation checks not rerun on the unified builder (selftests pass).

## Follow-ups
- Make the nemu64 clock-loop test alignment-robust rather than pinned (or note in the spec that its 20-clock band is layout-sensitive).
- Bench expectations that need cache-phase control (single-sample pclk) could be made repeatable with an explicit .align in k_ routines.
- R4: fix render.cpp DMEM read for --rdp none; port repeater64 FillTri/UndefShade; rdpstat:1prim.
- Thar0 at RUNS=1000 (~18 min) not measured.
- Core units merge feat/tools (one merge) instead of r1/r2/r4 separately.
