## Verification: PASS-WITH-NOTES

Independent run on head 964ef15749c0a837d2251b2ca7dfb41c94f0b641 vs base 8889b93b1. Own worktrees (`ares-wt/verify-61`, `verify-61-base`), own builds (`build/verify-61-{base,head}`, gcc RelWithDebInfo via `tools/n64-timing/build.sh`), ROMs rebuilt by `romgen/build.py` (nemu64 ROM byte-identical to the worker's). Raw outputs: `~/n64-timing/results/verify-61/{base,head,wall}`.

### Unit check (measured)
- nemu64 timing failures: base 453 of 1604, head 11 of 1604.
- Per-value diff over all 1604 values (same keys both sides): 1151 pass->pass, **442 fail->pass, 0 pass->fail**, 11 fail->fail, nothing else. The 11 value lines (rows 18.0-18.1 Load Miss VI on, 19.0-19.7 Load Miss VI off, 20.0 Load from uncached VI on) are byte-identical base vs head. That is C7 x10 and C6 x1, as claimed.
- Failure categories on head: C6 1, C7 10, all others 0. Exceptions Roundtrip 15/15 (base 10).
- nemu64 cycle (9 of 13 fail) and cop0hazard (5 of 5 fail): `values.tsv` byte-identical base vs head.

### Standing checks, base = head (measured)
- snapper 432+32+2048+20+40+20 = 2592/2592 match. rdpstat: RDP-status 0 of 7, DPC-sequencing 0 of 2, RDP-pixels 0 of 21 failed. thar0 rows 84/85/92/93: 77772 / 155052 / 77772 / 155052 on both.
- bench: `fail 10, pass 11, report 19`, `results.tsv` identical (cmp).
- ctest 5/5 (both). `behaviors.py --check`, `--self-test`, `lint-literals.py`: ok.
- `determinism.sh` and `--step-cap`: PASS on MM (27 files, 8158 fields) and the three nemu64 ROMs, both sides. State round trip + TMEM poke: PASS.

### MM 600-field wall (measured, interleaved base/head, 5 pairs, load average 2.0 falling to 1.2)
base: 19.61 19.47 19.56 19.61 19.57 (median 19.57 s). head: 19.95 19.78 19.79 19.78 19.83 (median 19.79 s). Head is +1.1%, every head run above every base run. Matches the worker's ~1%. Budget is 120 s.

### Mutation (measured)
ERET 3 -> 2 (tsv + regenerated hpp/spec, rebuilt head): both Roundtrip values fail with 14 vs 15, failures 13 (C1 +2). Reverted, rebuilt, back to 11. Worktree is clean at the PR head.

### Provenance notes (non-blocking)
1. `cpu.eret` is Basis `fit`, fit-from and check both `exception-roundtrip`, note `verify-is-fit`, spec renders "fit only, no independent check". Correct per preference 21. The 3 pclk comes from one measurement (both Roundtrip rows are 15), so the Roundtrip pass is not verification of ERET.
2. `cpu.exc-fpu-detect` is Basis `measured`, but its note says the rule is read off the same tables that check it. By preference 21 that is a fit read off its own check. Same precedent as `cpu.fpu-trivial`, so not new, but the basis column overstates. Consider `fit` or a note in the spec that the COP1 tables are both source and check. Boundary grounding against `romgen/suites/nemu64/tables.py`:
   - W conversion at 2^32: bracketed (S: 4294967040 takes 10, 4294967296 takes 7; D: 4294967295.9999995 takes 10, 4294967296 takes 7). 
   - From L at 2^55: bracketed (36028797018963965 takes 10, ...968 takes 7).
   - To L at 2^53: **not bracketed.** The data has 0.5 (late) and 2^53 (early) and nothing between, so any threshold in (0.5, 2^53] fits. 2^53 is the smallest tested early value and the double-mantissa limit, a reasonable choice, but it is an upper bound from data, not a measured boundary. The row should say so.
3. Store address error, TLBS and Mod: the `cpu.exc-ex` note says "AdES, TLBS and Mod have no test; inferred to share the load's stage", and `exceptions.cpp` carries the same comment. Labeled inferred, good. The row's basis is still `measured`, and the comment's "(one address check serves both)" asserts a mechanism with no reference. Minor.
4. The CTC1-raised FPE, interrupts, bus errors, NMI, fetch-time exceptions charge nothing and are listed as unreferenced in the notes (consistent with the report).

### Diff scope (read in full, 11 files)
- Files beyond the plan list are justified: `pipeline.hpp`/`cpu.cpp` carry `inFlight`, `decoder.cpp` adds ERET, CACHE D Index Load Tag and the W/L-with-S-form cost to the existing one cost table, `memory.cpp` drops the legacy `step(pclk(1))` (both sites) with its tsv row, spec row and allowlist line removed together. `checks.tsv` gains `exception-roundtrip`, needed so the fit row names a check.
- No remaining references to `legacy.cpu.address-error`, `CpuExcFpuUnimpl`, `CpuExcFpuArithExtra`, `CpuCacheIndexOp`, `cpu.exc-fpu-unimpl`, `cpu.exc-fpu-arith-extra`, `cpu.cache-index-op`, or the `faulted` flag in the n64 core, tools or docs.
- Comments explain why and cite the table; none narrate phases. One drift: `pipeline.hpp` says the member cost "10%" and the report says 11%. Trivial.
- Failure mode checked by reading: an exception with `inFlight` null (interrupt, fetch) returns before charging, and `retire` skips; same effective behavior as the old `faulted` path.

Nothing from the worker's report failed to reproduce.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
