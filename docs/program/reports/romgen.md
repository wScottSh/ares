# Unit romgen report

**Status:** done. All acceptance items were met and measured on 2026-10-05.

- **Branch:** `feat/romgen` (worktree `C:\Users\Scott\repos\ares-wt\romgen`), based on `origin/feat/harness` @ `c8592d16a`.
- **Head:** `16884f97c`.
- **PR:** https://github.com/wScottSh/ares/pull/34, base `feat/harness`.

## Pickup

The previous agent left uncommitted work: the timing port (26 tests, 1604 values), the assembler, the runtime, the importer, the classifier, and the run-script hook. I checked it before keeping it. Its timing ROM already reproduced 924 / 1109 with the baseline's category split. Its build takes about 7 s, so the slow average-bound scan in the last note is no longer a problem (measured). I committed the work as-is first (`05cd32060`) and then added the following:

- The `cycle` set (12 tests, 13 values) and the `cop0hazard` set (5 tests, 5 values). Before this they did not exist.
- The runtime now records FCSR at the first exception, which the CTC1 tests check. `mips.py` gained the `dla` pseudo-instruction.
- `checkpoint()`, a step that runs checks between steps (`6eda4423f`). It fixes a port bug, described under Divergences.
- `selftest.py` runs as a plain script. It has two multi-word hand checks (`li`, `dla` with a %hi carry). A mutated `dla` makes it fail (70/71, exit 1).
- A README with the MIT text and the source commit, plus updates to the harness README.

## Commands

```sh
python tools/n64-timing/romgen/build.py --suite nemu64 --out C:/Users/Scott/n64-timing/roms
N64_RUN=/c/Users/Scott/n64-timing/build/harness/n64-run/rundir/n64-run.exe bash tools/n64-timing/run-nemu64.sh --cpu interpreter    # and --cpu recompiler
python tools/n64-timing/romgen/selftest.py
```

- **Determinism.** Two builds into separate directories gave byte-identical ROMs and `.tests.tsv` listings, checked with `cmp` (measured). sha256: timing `e27b6645…`, cycle `ddd6f6e5…`, cop0hazard `977c88d4…`. The ROMs in `C:\Users\Scott\n64-timing\roms` are the current build (`cmp` clean).
- **Per-test TSV.** The output is `results/nemu64-<cpu>/<set>/values.tsv`. The timing set also gets `categories.tsv`.
- **Self-test.** `assembler self-test: 71/71 passed`.
- **Importer.** Rerunning `import_nemu64.py` against the clone at `9a8b9f7` reproduces the committed `tables.py` (no diff).

## Raw counts (measured, n64-run from the harness build, stack-base core)

```
=== interpreter
Timing: Failed 924 of 1604 tests (42% success rate)
category  failures  C1  C2  C3  C4  C5  C6  C7  C8  C9  C10  C11  other
count     924       439 204 172 50  14  11  10  10  9   3    2    0
Cycle: Failed 9 of 13 tests (30% success rate)
CP0-hazards: Failed 5 of 5 tests (0% success rate)
=== recompiler
Timing: Failed 1109 of 1604 tests (30% success rate)
count     1109      439 216 324 59  18  11  2   10  9   3    2    16
Cycle: Failed 10 of 13 tests (23% success rate)
CP0-hazards: Failed 5 of 5 tests (0% success rate)
```

The test counts match nemu64-test exactly: 1604, 13 and 5.

## Comparison with the baseline

- **Totals.** All six totals match: 924/9/5 on the interpreter and 1109/10/5 on the recompiler.
- **Interpreter categories.** C1-C11 match one for one (439, 204, 172, 50, 14, 11, 10, 10, 9, 3, 2).
- **Interpreter test groups.** All match the baseline's group table: COP1 64-bit 244, COP1 32-bit 223, CPU register dependency 199, Exceptions 135, COP1 register dependency 59, Cached 19, Individual 10, Uncached VI off/on 9/2, Load Miss VI off/on 8/2, Compare 7, Likely 4, and Data cache Size, Random (decrement) and Random (masking) 1 each.
- **Recompiler.** The baseline publishes only totals and notes. The run agrees with the notes: 16 write-buffer failures (the `other` column), and none of the 8 `Load Miss (VI disabled)` cases fail.
- **Classifier caveat.** `categories.py` assigns categories with rules over the test group and value description, written by the previous agent from the baseline doc. The category match therefore shows that the rules reproduce the doc's split. It is not independent evidence that each value has that root cause.
- **Cycle failures.** The interpreter fails the 7 self-modifying-code values (`a=0x2222 b=0x1111`, and `0xff` vs `0x3f` for multiple writes) and both CTC1 tests (`Cause` `0x3c` vs `0x1000003c` / `0x2000003c`). These are the baseline's tests and values. The recompiler adds `BGEZAL: Within delay slot of BEQ` (`0x3ff` vs `0x301`), the recompiler-only bug the baseline names.
- **cop0hazard failures.** `COUNT hazards` fails on the second readback, +1 vs +0. Both SoftwareInterrupt hazard tests fail on ExceptPC, 4 bytes early. `enable but disable right away` takes an Int. All of these match the baseline.

## Divergences

1. **Fixed port bug.** The first cycle/cop0hazard port ran every step before any check. In nemu64-test, `CountHazards` returns at its first failed assertion, which happens at COUNT value 0 on ares. The port went on to write 0xFFFFFFFC and 0xFFFFFFFF, which carried COUNT past Compare (0) and latched IP7. The later interrupt tests then failed on `Cause` (`0x8100` vs `0x100`) instead of on ExceptPC. I confirmed this by building a ROM without `CountHazards`, which showed the baseline's ExceptPC failures. `checkpoint()` now ends a value at its first failure. It is applied to `CountHazards`, `HalfCycleExactCalibration` and every `preset_cause_to_copindex2`. After the fix, all failure reasons match the baseline, and the timing totals are unchanged.
2. **`Random (read early)` value (settings difference).** The port reads `0x1f` where the baseline read `0x16`. Expected is `0x15`, so the test fails either way. ares's `getControlRandom` returns `random()`, and n64-run seeds entropy deterministically, whereas the baseline used the desktop build with unknown entropy (harness report). That the seed explains the value is inferred and not traced.
3. **Port approximations, none observed to change a result.**
   - `dla` uses LLVM's six-instruction expansion. The length is inferred from LLVM's MIPS assembler and was not checked against a rustc build.
   - Registers that rustc would allocate are fixed in the port.
   - Exception-context fields are compared on their low 32 bits.
   - Heap buffers are at a fixed `SCRATCH_BASE` (0x80500000) with the Rust alignment.
   - Timing in the Rust glue code around the inline asm is not reproduced.

## Not done or left as is

- `build-nemu64.sh`, the Docker/cargo path, is still in the harness. It cannot run here. romgen replaces it in the README's main path.
- `run-nemu64.sh` looks for the runner at `build/<worktree>/…` by default. This worktree has no runner build, so I set `N64_RUN` to the harness build. The core is identical: this branch changes only `tools/`.

## Follow-ups (difficulty estimates are inferred from the r29 corpus doc; I did not read those repos' source)

1. **Thar0 RDP-Timing-Tests (MIT), first.** It is the only console RDP counter data: 100 fill-rectangle configs, and exact values for the alpha all-fail cases. romgen would need an RDP command-list builder (color image, other modes, combiner, rectangle), DPC_BUFBUSY/PIPEBUSY readout, VI on/off, and buffer bank placement. Expectations come from `compare.py` `hw_data`. Estimate: medium, about 1 day. Open question: what DPC counters return under `--rdp none` with today's core.
2. **n64-systembench (no license).** The source cannot be imported. Port only the expected-cycle table, which is facts, and re-implement each benchmark: cached and uncached loads, RCP register read, PI DMA sizes, SI DMA, PI word read/write. The ROM grades within tolerance bands. Estimate: small to medium. It needs PI/SI DMA routines in the runtime.
3. **Mr-Wiseguy N64-Cache-Emulation-Tests.** These are functional tests, not timing, per r29. The runtime already has the cache-op scaffolding (`invalidate_range`, `step_smc`). Estimate: small. Lower priority for the timing program.
