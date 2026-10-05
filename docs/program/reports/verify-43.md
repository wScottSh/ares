# verify-43 (T10, PR #43)

Worktrees: ares-wt/verify-43-head, verify-43-base, verify-43-neg (scratch negative controls, unpushed). Builds: build/verify-43, verify-43-base, verify-43-neg, verify-43-neg2. PR comment: https://github.com/wScottSh/ares/pull/43#issuecomment-5997429295

## Independent verification of #43 (T10): PASS-WITH-NOTES

Head 15abbcb28, base feat/t3 (9793b9b5f). Builds: `build/verify-43` (head, fresh configure), `build/verify-43-base`. Raw outputs: `C:\Users\Scott\n64-timing\verify\verify-43\`.

### Results (all measured by me)
| Check | Command | Result |
|---|---|---|
| Fresh configure + build, no Vulkan | `N64_BUILD_DIR=build/verify-43 tools/n64-timing/build.sh` | 87/87 steps link `n64-run.exe`; `CMakeCache.txt` and `build.ninja` have 0 "vulkan" matches |
| det with fb_hash, MM 600 fields | `determinism.sh MM 600` | `PASS, 17 files byte-identical, 3807 fields with trace_hash` |
| fb_hash > 4 distinct per scene | distinct `fb_hash` in `mm-*/<scene>/stats.tsv` | filesel 637 / sct 326 / field 326 / title 324 (T3: 3 each); intro 600 fields: 234 (T3: 3) |
| Intro fb_hash equals T9 `--rdp soft` | `n64-run-t9-after.exe --rdp soft` vs head, 600 fields | fb_hash identical on 600/600 fields |
| State round trip | `state-roundtrip.sh MM 600` | round trip PASS (600 fields byte-identical, saves/loads at 150/300/457); TMEM poke PASS (field 31, only `trace_hash`, differs on every later field) |
| Negative control | head with the `io(ctx, rdp->m_tmem, 0x1000)` line removed from `rdp_render_serialize` (scratch worktree, not pushed) | round trip FAIL at field 151 (`fb_hash`, `trace_hash`); poke FAIL "no row changed" |
| rdpstat (ROMs rebuilt from feat/r4, byte-identical to the worker's) | `n64-run ROM --emulated-seconds 120` | head: systemtest 0/7, dpc 2/2, repeater64 0/21 failed. T3: systemtest 4/7, dpc 2/2, repeater64 21/21 failed |
| nemu64 (ROMs rebuilt from this branch) | `run-nemu64.sh`, head vs T3 | timing 922/1604, cycle 9/13, cop0hazard 5/5 failed on both; `values.tsv` and `tests.tsv` byte-identical for all 3 sets |
| mmbench timing columns | `mmbench.py MM --exe ...`, head vs T3, 2401 rows | `gframes.tsv` and `summary.txt` byte-identical; `fields.tsv`: the only differing column is `rdp_pixels` (1865 rows; T3 has 0). scene..zimg identical. Intro stats: every column except `fb_hash` and `trace_hash` identical to T3 |
| Leftover Vulkan/paraLLEl | `git grep -i` outside docs/, thirdparty/, engine | `LICENSE` MoltenVK block and `cmake/macos/helpers.cmake:127,143` (worker disclosed). Engine files cite "ParaLLEl-RDP" as the source of noise/dither/blend formulas (attribution; MIT notice in `rdp_blendlut.h`). `ares/n64/vulkan/` gone; `--rdp` gone from `n64-run` and its README |

`trace_hash` differs from T3 because `fieldBoundary()` hashes the full serialized state, which now includes drawn RDRAM; this is the expected effect, and is why the TMEM negative control is meaningful.

### DMEM byteswap fix (rdp_core.c:1353-1358)
Reverted in a scratch build: rdpstat systemtest goes 0/7 to 3/7 failed, so the fix is load-bearing (XBUS DMEM is big-endian bytes in ares). repeater64 stays 0/21 (RDRAM-sourced lists).

### Hazard-publish change (rdp_core.c:5127-5131, 5181-5185)
Read the diff: `rdp_haz_publish` now runs before the drain on the end-of-list path, plus both held-primitive publishes on the partial-command path. Evidence it is pixel-neutral on MM: intro fb_hash equals the T9 binary (pre-change) on all 600 fields, and repeater64 is 0/21. I did not run the other three scenes against a T9 binary, so the "four scenes identical" claim is only partly reproduced by me. Serialization depends on this (no queued spans or held primitive across calls); the reasoning in the engine README holds.

### Notes
1. Not reproduced: the desktop-ui compile (9 objects) and the macOS build; I built `n64-run` only.
2. Round trip is in-process only (worker deviation 7, confirmed as stated). A first run of mine used a `/c/...` path inside the script file, the native exe could not write it, and `state-roundtrip.sh` printed `round trip: PASS` while its own `FAIL, roundtrip.log reports a failed step` line also printed. Rerun with `C:/...` paths gave both PASS. The script's PASS line can appear next to a failed-save, so read the whole output.
3. Stack hazard: `run.sh` in the rdpstat (feat/r4) and snapper (feat/r3) suites pass `--rdp`, which this PR removes (`n64-run ... --rdp none` prints usage). They need a one-line fix when T10 lands.
4. Engine perf: head intro 600 fields 10.9 s wall, render 1697 ms, 18.97 ns/px over 89,477,643 px (matches the worker's 18.8-27.4 range). mmbench 4 scenes in parallel: 37.4 s head vs 28.2 s T3.

Verdict: PASS-WITH-NOTES.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
