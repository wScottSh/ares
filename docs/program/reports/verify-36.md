## Verification of PR #36 (T2): PASS-WITH-NOTES

Own builds (RelWithDebInfo, clang, n64 core): head f73be58f7 (`verify-36-head`), base feat/t1 7a92d98c0 (`verify-36-base`). Private N64_TIMING_HOME.

**det** `N64_RUN=<head> determinism.sh <MM rom>` -> `determinism: PASS, 17 files byte-identical, 3807 fields with trace_hash`. Field 0 cpu_cycles 48056114 (matches the report).

**trace_hash covers hidden state.** MM, same waits, control script vs the same plus `poke 0x807FFF00 w 0xdeadbeef` after field 10 (`--frames 40`). 41 rows each; only column `trace_hash` differs, first at row 12, 29 differing rows (every field from the next onward). All other columns identical.

**nemu64 (romgen suite, built by me, run on both binaries)**
- base: timing 924/1604, cycle 9/13, cop0hazard 5/5
- head: timing 922/1604, cycle 9/13, cop0hazard 5/5
- failures.txt diff: only `Random (decrement)` and `Random (masking)` removed; nothing added. `Random (read early)` still fails but now on a later check (a=0x1f b=0x1d, was a=0x1f b=0x15), same failure count.

**nall serializer byte-equivalence**
1. Standalone test (old vs new serializer.hpp, 1.8 MB mixed u8 spans, zero-length span, growth, read-back): size 1805009, FNV hash 39e2f2df99a09d3a for both, round trip OK.
2. Real state: head rebuilt with the t1 serializer.hpp (`verify-36-oldnall`) vs head; MM 600 fields `--stats` files `cmp` IDENTICAL, including trace_hash (hash of full serialized state each field).

**PRNG consumers vs report table** (read at diff): seed 0 in System::power (system.cpp:420), CcLow/CcHigh 9/15 constants (rdram.hpp), degrade still draws random() (rdram.cpp:205), CP0 Random = (31 - elapsed % period) & 63 with period 32-W or 96-W, epoch = instructionIndex+2 at Wired write (interpreter-scc.cpp), SP_PC = ipu.pc, RTC fixed 2000-01-01 (cart + 64DD), bio sensor on cpu.pclock()*4/375 (= /93.75, correct), gamepad.cpp:456-458 still random() (now pinned). Grep of ares/n64 finds no remaining host time/rand sources besides these. All match the table.

**desktop-ui** compiles to object level: `desktop-ui.cpp.obj`, `emulator/emulator.cpp.obj` (includes nintendo-64, nintendo-64dd, arcade), `settings/settings.cpp.obj` built clean.

**Notes (non-blocking)**
- `settings.developer.deterministicEntropy` and its UI checkbox remain (still used by super-famicom); its hint text now does nothing for N64 (desktop-ui/settings/developer.cpp:54-58).
- CPU Random is a placeholder inside the 2-instruction post-Wired window (stated in the code comment, owned by T7c).
- trace_hash serializes full state (~9 MiB) per field; wall cost not re-measured by me.
- determinism.sh ignores wall.tsv by design.

Commands: cmake/ninja builds above; `determinism.sh`; `run-nemu64.sh` with `N64_RUN` per binary and `N64_TIMING_HOME=...\verify36-{head,base}`; `n64-run --script`; `cmp`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
