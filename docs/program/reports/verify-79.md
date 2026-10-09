## verify-79: PASS-WITH-NOTES

Head 120398a0f vs base e48d62a1b. Own builds (verify-79-{base,head}), private N64_TIMING_HOME per side, all 655 suite ROMs rebuilt from each tree (head rom-sha256.txt sha256 71ab0f2838e4, same as the worker's). Own standing.sh run per side, in parallel, 769 s base / 770 s head at load ~15 (no wall comparison; core unchanged). Raw: `~/n64-timing/results/verify-79/{base,head}`.

**1. No core timing change: reproduced.**
- MM 600 `mm600.tsv` md5 210d0d4625788e5e8d0e1d74be65a07f on both.
- nemu64 timing/cycle/cop0hazard values.tsv md5 identical base vs head (c263ddfa..., 3f2afbbd..., f4177fb2...). thar0 compare.tsv and mmbench summary.tsv cmp-identical.
- det and stepcap PASS on both: MM 29 files / 8219 fields, nemu64 x3 (1, 2, 25 fields). state round trip, tmem poke PASS, ctest 9/9, behaviors --check / --self-test / lint-literals / pidma-replay 5/5 ok.
- behaviors.hpp diff: one line, `pi.block-writeback` Basis::Derived -> Basis::Fit plus note string and verify string. Data only.

**2. consistent-only / pass-conditional:#77: confirmed.**
- `bench_label` recomputes via report.label. Mutation (in scratch worktree verify-79-mut, bench_label returns `r["verdict"]`): self-test goes 49 cases 0 failed -> 49 cases 1 failed, the stale-pass case, which returns `pass` instead of `consistent-only`. So the self-test catches it.
- Spec and closure count them apart: closure "Check results: 2 consistent-only, 27 fail, 63 pass, 1 pass-conditional:#77, 12 pending" and a "pass only weakly" table (rspdma, pi-dma-sizes, pi-dma-sizes-8). Row statuses unchanged (36 fail, 10 fit only, 3 model-choice, 67 pass).
- Bench summary head: consistent-only 1, fail 15, pass 26, pass-conditional:#77 2, report 26 (base: fail 15, pass 29, report 26).

**3. pi.block-writeback: confirmed.** Basis fit, fit-from = pi-dma-sizes-{128,1024,65536} (all three pass, labeled as fit arithmetic). Independent checks: `pidma:logs` fail (up to +14.97% worst band, 8 ROM self-check failures) and `pi-dma-sizes-8` consistent-only (180..194.67, mean 190.0, band 191.07..194.93, mean rule fail, window +-4.8%). Row reads **fail**.

**4. hpos / layout side effect: reproduced, no verdict moved except the relabels.**
- line_ticks: base 2926 and 2988 across the two ROMs, head 2979 and 2980 (HSYNC spacing 2984 per worker). Closer, still off by 4-5.
- Base vs head bench results.tsv: 20 of 68 rows moved a value, all inside phase spread; verdicts differ only for rspdma (pass -> pass-conditional:#77) and pi-dma-sizes-8 (pass -> consistent-only). Worker's examples reproduce (rspdma min 6.422 -> 6.492, pi-dma-8 mean 189 -> 190, write64 max 4069.33 -> 4073.33, u32-rand 132 -> 131, sp-dma-sweep max 6.693 -> 6.678). Also moved, not in the worker's list, report-only: dirty-row-sweep dirty_minus_clean min 0 -> -2, dirty-miss-isolated 20 -> 18.
- Code-layout walk (scratch worktree adds PAD nops after the boot delay loop; rspdma + pi-dma-sizes, 32 delays each, head runner, PAD 0-8 words):
  - rspdma b_per_rclk range / mean: PAD0 6.492..6.501 / 6.498; 1: 6.492..6.501 / 6.497; 2: 6.479..6.502 / 6.498; 3: 6.479..6.502 / 6.498; 4: 6.272..6.502 / 6.491; 5: 6.272..6.502 / 6.491; 6: 6.271..6.501 / 6.491; 7: 6.424..6.503 / 6.497; PAD8 == PAD0 exactly (period is 8 words = one icache line). PAD0 reproduces the standing run.
  - pi-dma-sizes cart-to-ram-8: 180..194.67 at every pad, mean 189-190, consistent-only at every pad.
  - Verdicts identical at all 9 pads. No verdict needs a code-layout walk today.
  - Note: rspdma `mean` rule band is 6.49..6.515. Mean at PAD 4-6 is 6.491, 0.001 inside the band; the pass-conditional rests on that margin plus #77. A further change could flip it. Phase spread (min 6.27) is real at some layouts; the boot delay set does not show it at PAD 0.

**5. Regeneration: reproduces.** `behaviors.py --results <my head run>` then `behaviors.py`: git diff touches only the three provenance lines (`standing run labels-phase/after on b66e6e897` -> `verify-79/head on 120398a0f`). n64-timing-results.tsv content (105 checks) identical. `--check` ok.

**Diff notes (non-blocking).**
- Worker's "holdoff_rclk_max 42.67 -> 74.67" confirmed (report-only, unexplained; worker lists as follow-up).
- Worker's report omitted the dirty-row min changes above (report-only).
- phases.py comment cites a measured dip list, not a hardware reference; it is measurement, fine.
- No dead code or scope creep seen; comments explain why.

Recommendation: land. Follow-ups: explain the holdoff 74.67 / window-edge sample; consider widening mean-rule margin awareness for rspdma (6.491 vs 6.49).

Nothing of mine is running.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
