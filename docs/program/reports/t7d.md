# T7d report: fetch window and I-fills through SysAD

**Status:** done.
- Branch: feat/t7d.
- Head: 84e19521726f1478287aa02452920c525c7d4962. This is the merge of origin/master 1a6a9de57 (#64 cop0order, tools only).
- Base: master a1c92f1b9.
- PR: https://github.com/wScottSh/ares/pull/65

**Builds:**
- ~/n64-timing/build/t7d-base (master, worktree ares-wt/t7d-base)
- ~/n64-timing/build/t7d (head)

**Raw output:** ~/n64-timing/results/t7d/{before,after,after-v1,merged,mut,wall}. The after-v1 run is the pre-ring head. Drivers are standing.sh, compare.sh and wall.sh in the same directory.

## What changed
- **Fetch window.** `Pipeline` holds a two-slot ring with the words at pc and nextpc (pipeline.hpp/.cpp, cpu.cpp).
  - A store or CACHE op (opcodes 0x28-0x2f, 0x38-0x3f) reads the word two ahead before it executes. Every other instruction reads it after it executes.
  - Basis: NEC VR4300 UM ch.4 (IC of n runs in n-2's slot) and s.4.6.7 DCB (store data lands at WB).
  - setPc flushes the ring. Fetch faults are kept in the slot and raised at issue.
  - The issue step moves from fetch() to instruction(), on the same pclk.
  - interruptSampled stays at the top of instruction(), and the Issued record stays on the stack.
  - The CTC1 CE peek uses the window word.
- **I-fill.** The fill takes cpu.ifill-stall (45, derived) at the D-fill's clean row miss instead of the legacy 48. The I-cache Hit Write Back no longer steps 48. Both legacy rows are removed.
- **Rows.** cpu.fetch-ahead-slots changes from 3/derived to 2/fit.
  - fit-from nemu64:cycle/smc-multiple-writes; verify nemu64:cycle/smc-single-write (both new check rows).
  - The note says that only multiple-writes separates 2 from 3.

## Check
- **nemu64:cycle: PASS.** Failed 7 of 13 -> 0 of 13. All 7 SMC values go fail -> pass (measured).
- **nemu64 timing reaches 0: FAIL.** It stays at 11 of 1604, the same tests as master. Each one has a cause:
  - **C7 VI off x8.** The sum is 41000, so every miss costs exactly 41. Hardware's mean is 42.5 and its median 41: a tail is missing. With the VI off there is no VI fetch, and refresh is off by model choice (ri.refresh-trigger source conflict). So this is not T11's. It needs RI refresh or D-fill tail work. Missing reference: a hardware D-fill latency distribution, or a measured refresh rate before VI init. T6 showed that refresh on the blank VI overshoots the uncached load (35.5 against 32.54).
  - **C7 VI on x2.** Sums 41851 and 41865 against 42250..44250. VI fetch contention is not modeled yet, so rerun after T11 first (inferred).
  - **C6 x1.** Uncached load in the same bank as the VI framebuffer, VI on: median 33 against 35..37. This is VI fetch contention, T11's.
- **MM boots both scenes: PASS.**
  - det and stepcap on MM: 27 files and 8146 fields, all 7 mmbench scenes reaching their windows. Master had 8158 fields, because the timing shift moves the scene windows.
  - State round trip: PASS.

## Standing checks (master -> head, measured)
- cop0hazard with the #64 ROM: 0/5 on both binaries. With the old ROM: 2/5 on both.
- snapper 2592/2592; rdpstat 0/7 0/2 0/21; thar0 identical. bench fail 10 / pass 11 / report 19, the same rows.
- Notable bench report moves:
  - uncached-vs-hpos bank2-vi median 34 -> 36 (the hardware report value is 36);
  - dirty-miss-isolated 46 -> 48;
  - pi-dma cart-to-ram-8 197.33 -> 196.0 (still failing; T8's).
- ctest 5/5; behaviors --check, --self-test and lint: ok.
- det and stepcap: PASS on MM and on the 3 nemu64 ROMs, cop0hazard rerun on the #64 ROM. State round trip and TMEM poke: PASS.

## Mutations (results/t7d/mut)
- Store lands before the fetch: single-write (6,8) and multiple-writes fail (0x7f against 0x3f).
- A load waits behind the I-fill two ahead: RSP Timing "Clock CPU vs RDP" reads 133293 against 133313..133353. Only romgen's line boundary at that load + 2 exposes this, so the "load first" ordering is labeled inferred.

## MM wall
- 600 fields, 4 interleaved pairs, load 7.7 -> 2.7.
  - master: 20.57, 19.78, 19.74, 19.75 s (median 19.77).
  - head: 20.26, 20.24, 20.17, 20.20 s (median 20.22), +2.3%.
- ns per instruction is equal (27.0). Emulated instructions are +2.4% (730.8 M -> 748.0 M) from the 45-pclk I-fill.
- perf stat, 300 fields x3 interleaved, load 2.3 (median cycles):
  - master 28.25 G;
  - master + I-fill commit only 28.62 G (+1.3%);
  - head 28.89 G (+2.3%).
- Host instructions are +12.5% (136.2 G -> 153.3 G); IPC absorbs it.
- The first window (shift copies plus a decoder store flag) measured +31% cycles at load ~4 and was replaced by the ring (commit 4e318f72c).

## Deviations
1. FetchWindow is part of Pipeline and stores no ic Clock.
2. Files beyond the plan:
   - memory.cpp: fetch() drops the issue step;
   - interpreter-fpu.cpp: the CE peek;
   - sysad.hpp/.cpp: the I-fill path and writeback;
   - behaviors.tsv/hpp, the spec, checks.tsv and literal-allowlist.tsv.
3. The 45 is placed at a clean row miss. This is a derivation choice; the row's M came from the clean-miss D-fill.
4. CACHE in the read-first group is inferred, untested.
5. The save-state layout gains window[2] and head. SerializerVersion is unchanged (T7a/T7c precedent).

## Follow-ups
- bench:ifill-isolated has no ROM, so cpu.ifill-stall has no asserting check.
- C7 VI off needs the reference named above. C7 VI on and C6 need a rerun after T11.

## For the next unit
- Instruction words come from pipeline.take(). After an instruction executes, pipeline.next() is the following word as the I-cache served it.
- Any new pc redirect must go through setPc(), which flushes the ring, or move pc/nextpc the way a branch or skip() does. The ring compares vaddrs.
- Worktree ares-wt/t7d-base (detached master a1c92f1b9) and its build are mine and can be pruned.
