# Report: mmbench2

**Status: DONE.**

- Branch: `feat/mmbench2`. Worktree: `C:\Users\Scott\repos\ares-wt\mmbench2`. It started from origin/master `bdcc9c805`, and origin/master `ad7fbdfea` (with #45 stack) was merged in mid-run.
- Head: `f6e50ac36` (feature commit `41ae0cad5`, then a merge of master). It merges into master cleanly.
- PR: https://github.com/wScottSh/ares/pull/46 (base master, not merged).
- Files: `tools/n64-timing/mmbench/{mmbench.py,README.md,filesel_check.py}`. No changes to n64-run, because no new script verb was needed.

## Check

| Item | Result |
|---|---|
| `filesel-named`: two named files, cursor File 1, idle 600 fields, cold boot | done. Name entry creates "A" in File 1 and File 2. Confirmed by peeks `end.name1/2 = 0x0a3e3e3e` and by a shot. |
| `filesel-options`: Options idle 600 fields | done (shot confirmed) |
| `filesel-rotate`: Main to Options rotations | done. 8 rotations, 7 frames each, in `rotations.tsv`. |
| Check script for the doc's acceptance rows | `filesel_check.py`. Exit 0 only when both primary rows pass. |
| Row 1, empty main idle (mean ≤ 1.05, ≥ 95 % at 1 field) | **PASS**. Mean 1.0000, 449/449 frames at 1 field. |
| Row 2, Options idle (≤ 1.05) | **PASS**. Mean 1.0000, 598 frames. |
| Row 3, named main idle (1.90 to 2.10, ≥ 90 % at 2 fields) | **FAIL as expected**. Mean 1.0000, 0 % at 2 fields (598 frames). |
| Row 4, rotation (1.0 to 1.6, ≥ 4 consecutive 1-field frames) | **PASS**. All 8 rotations are 1,1,1,1,1,1,1. |
| The checker catches a defect | Synthetic named row (1.99, 99 % at 2) gives PASS. Rotation 1,2,1,2,1,2,1 gives FAIL. |
| `--check-determinism` with the new scenes | PASS, 27 files (before: 17). |

## Standing checks (same binary; n64-run and the core equal master `ad7fbdfea`)

- Determinism before: PASS, 17 files. After: PASS, 27 files.
- The 4 existing scenes give byte-identical `script.txt`, `stats.tsv`, and `events.txt` before and after. Values: filesel 1.0000 (rsp 458658.2), sct 3.0000, field 3.0000, title 3.0000.
- New rows: named 704425.9, options 652535.9, rotate 692362.4 rsp_busy per field.
- Wall time before: 4 scenes parallel 27.1 s. After: 7 scenes parallel 54.2 s. The longest scene is `filesel-rotate` at 53.6 s, `filesel-named` takes 49.4 s, and the old scenes take 28 to 35 s under 7-way contention.
- nemu64, generator, and step-cap: not run. This change is tools-only, and the binary is master's.
- Raw output: `C:\Users\Scott\n64-timing\results\mmbench2\{before,after}\run{1,2}`. Shots: `...\shots-master` (pixel engine) and `...\shots` (paraLLEl, pre-merge).

## Deviations

- `filesel-rotate`'s window is set by its 8 cycles (1120 fields), not 600, because each cycle includes the options flash save. `analyze` now takes a window end from `mark end`. The default stays 600.
- Rotation frame lengths are measured on the update side: the marks are the fields where `windowRot` reaches 50 through 314, plus the first options-slide frame. VI origin changes cannot be tied to rotation frames without a known display lag. That display cadence equals update cadence in steady state is inferred.
- One-letter names. `FileSelect_DrawFileInfo` draws all 8 glyph quads regardless of the name, so the draw count is the same.
- Master moved mid-run: #45, with `--cpu` removed and the pixel engine added. I merged it (no rebase) and resolved two trivial conflicts: the `--scenes` default next to the removed `--cpu`, and the README Rendering paragraph.

## Next unit must know

- `FileSelectState` is at `0x803E6B20`, the 4th `malloc_arena` node, found at run time. The guards are node size `0x24560` and `state.gfxCtx`. If it ever moves, the run hits the frame limit and the bench fails loudly.
- `filesel_check.py DIR/run1` is the #11 gate. Row 3 is the one the RDP timing model must flip to 2.00.

## Follow-ups

- None blocking.
