# labels-phase: done

- Branch: feat/labels-phase, head 120398a0f76c3af8c1692a3183a8426179ddc64f, base master e48d62a1b.
- PR: https://github.com/wScottSh/ares/pull/79
- Worktree: /home/wscottsh/repos/ares-wt/labels-phase. Build: ~/n64-timing/build/labels-phase. Private home: ~/n64-timing/labels-phase-home, with corpora and scratch symlinked.
- Run: ~/n64-timing/results/labels-phase/after. Before: verify-78's head run ~/n64-timing/results/verify-78/head (master code, same ROM generator except my edits).
- Nothing of mine is still running.

## Items
1. **Weak passes (done).** report.py has `holds`, `label` and `acceptance`. results.tsv gains the columns `condition`, `mean_verdict` and `window_pct`. A consistent pass whose mean misses the band is `consistent-only`.
   - behaviors.py:
     - adds RESULT/WEAK `consistent-only|pass-conditional:#N`;
     - `bench_label` recomputes every verdict with report.label, which enforces it even on a stale results.tsv;
     - `bench_tally` orders the results fail > weak > pass;
     - row_status: a weak non-fit, non-guard check makes the row that weak status;
     - adds the STATUS_MEANING entries and the spec intro text;
     - adds a closure section "Checks that pass only weakly", with a count per result.
   - Self-test: 49 cases, 0 failed. Six are new, including a stale results.tsv "pass" that becomes consistent-only. A mutation that removes the recompute makes that case FAIL. bench selftest.py: 27 ok, with consistent-only, window, conditional and fail-with-condition cases.
   - pi-dma-8 is consistent-only: 180..194.67, mean 190.0, band 191.07..194.93, window ±4.8%. pi-io-write shows its window, ±8.0%.
2. **pi.block-writeback (done).** The basis goes derived -> fit, which is required: behaviors.py allows fit-from only on fit rows.
   - New checks bench:pi-dma-sizes-{8,128,1024,65536} are added. fit-from is 128, 1024 and 65536. verify is pidma:logs plus the 4 points.
   - The note says pidma:logs is independent and fails, and the 8 B point (not fit) is the other independent check.
   - Row status stays fail.
3. **mi-memset-rspdma (done).** The new expected.tsv `condition` column is `#77` on both of its check rows. The check result is `pass-conditional:#77`, and notes are in expected.tsv, checks.tsv and the README.
   - The only row that names this check, ri.overhead-write, already fails (sp-dma-sweep), so no row status moves.
4. **phases.py and hpos (done).**
   - phases.py and the README: 1314.7 iterations. The dip starts at 1292, 2606, 3921, 5236, 6550 and 7865, 1314 or 1315 apart. The brief's "spacing 1314.4" does not match those starts: (7865-1292)/5 = 1314.6, so I wrote the measured gaps instead.
   - hpos: the ROM averages 4 VI_CURRENT intervals. line_ticks went from 2926 to 2979 (HSYNC spacing 2984). outliers_per_line still passes at 1.0.

## Displayed result changes (n64-timing-results.tsv vs master)
- bench:pi-dma-sizes: pass -> consistent-only.
- bench:mi-memset-rspdma: pass -> pass-conditional:#77.
- New: bench:pi-dma-sizes-8 is consistent-only. bench:pi-dma-sizes-128, -1024 and -65536 pass, and they are fit data.
- Detail only: every consistent check gains "window ±x%, mean rule v". u32-banked, the JOY rows, read64-1 and accessory still fail under both rules.
- Row statuses: none change (36 fail, 10 fit only, 3 model-choice, 67 pass, 32 pending). Closure check counts: 63 pass, 2 consistent-only, 1 pass-conditional:#77, 27 fail, 12 pending.
- Spec Basis counts: derived 11 -> 10, fit 19 -> 20.

## Standing (measured)
- MM 600 md5 210d0d4625788e5e8d0e1d74be65a07f matches base.
- byte-identical to verify-78 head:
  - nemu64 timing, cycle and cop0hazard values.tsv (cmp);
  - thar0 compare.tsv;
  - mmbench summary.tsv.
- det and stepcap PASS: nemu64 x3 (25/2/1 fields) and MM (29 files, 8219 fields).
- State round trip PASS, tmem poke PASS.
- ctest 9/9 passed.
- In the run's behaviors.txt: --check ok, self-test ok, lint-literals ok, pidma-replay self-test 5/5.
- Bench rows: consistent-only 1, fail 15, pass 26, pass-conditional:#77 2, report 26.
- Wall time: standing 12m32s at load 18.65 -> 9.95. I did no separate wall comparison, because the core is unchanged.
- ROMs: 655 rebuilt from my tree. The sha256 of rom-sha256.txt is 71ab0f2838e4...

## Deviations
- behaviors.hpp changes, because pi.block-writeback now has Basis::Fit plus new verify and note strings. That is data only (MM md5 identical).
- The build's `behaviors.py --check` step needs results for the new check ids, so I first ran `--results` on the phase worker's run (results/phase/after), then built, then did the real standing run and regenerated from it. The committed results come from my run.
- I added an expected.tsv column, `condition`, and behaviors.py validates it.

## Side effect to know (measured)
bench_hpos is in the shared bench runtime, so 4 more instructions move every bench ROM's code. Values moved within their phase spread. No verdict moved apart from the relabels. Examples:
- rspdma min 6.422 -> 6.492 (the 32 delays no longer hit the dip; mean 6.495 -> 6.498);
- pi-dma-8 mean 189 -> 190;
- si-dma write64 max 4069.33 -> 4073.33;
- u32-rand 131..132 -> 131;
- sp-dma-sweep max 6.693 -> 6.678.

So the 32 boot delays do not cover code-layout phase. The hpos report row holdoff_rclk_max went 42.67 -> 74.67. The window now starts on a line's refresh: sample 0 at offset 3 reads 73 ticks, and the interior outliers read 44-51 ticks. It is report-only, and I did not root-cause it.

## Follow-ups
- holdoff_rclk_max: exclude the window-edge sample, or explain the 73-tick sample.
- Phase coverage of code layout: walk a code pad as well as the boot delay.
- #77 stays open.
