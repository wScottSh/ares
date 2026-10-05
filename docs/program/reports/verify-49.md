## Verification of PR #49 (T5, timeline scheduler): PASS-WITH-NOTES

Own builds (RelWithDebInfo, clang64, build.sh): base = origin/master ee8be6512 (build/verify-49-base), head = e8fab0989 (build/verify-49-head). Scratch mutation tree build/verify-49-neg (worktree verify-49-neg, never committed). Raw outputs: C:\Users\Scott\n64-timing\results\verify-49\{stepcap-*,det-mm,nemu64-base,nemu64-head,roundtrip,pidma-*,wall}.

**1. unit:timeline.** Head: ctest "100% tests passed out of 1"; the exe prints "timeline: ok". Mutations I applied to timeline.hpp, each rebuilt and run:
- argmin tie `c < at` -> `c <= at`: FAIL, 8 failures.
- caller-rank test removed (`|| (at == floor && best >= caller)` deleted): FAIL, 3 failures.
- Parked/Blocked check removed in the advance scan: FAIL, 2 failures.
- `best >= caller` -> `best > caller`: PASSES. Equivalent mutant: the caller is on the stack (or the unattached CPU) and never a candidate, so best != caller. Not a test gap.

**2. stepcap** (`determinism.sh --step-cap`, N64_RUN=head exe)
- MM, 7 scenes: "stepcap: PASS, 27 files byte-identical, 8312 fields with trace_hash".
- nemu64 timing ROM: "stepcap: PASS, 3 files byte-identical, 26 fields with trace_hash".
- Negative control (schedule() no longer lowers the horizon): nemu64 timing "stepcap: FAIL, stats.tsv first differing row 1 (frame 0), columns cpu_cycles,trace_hash; stdout.txt bytes differ". MM with the same mutation also fails, but by hanging (filesel-rotate never reaches the end of its script, frame limit 3000), so it is a weaker control than the nemu64 one.

**3. nemu64** (run-nemu64.sh, base vs head, my builds)
- Timing 922/1604, Cycle 9/13, CP0 5/5 failed on both. tests.tsv and values.tsv byte-identical (cmp) for all 3 sets. Matches 922/9/5.

**4. det / state-roundtrip.** det MM: "determinism: PASS, 27 files byte-identical, 8312 fields with trace_hash". state-roundtrip: "round trip: PASS, 600 fields byte-identical with saves and loads at fields 150, 300, 457"; "tmem poke: PASS, first differing field 31 (columns ['trace_hash'])". gen: behaviors.py --check ok, --self-test ok, lint-literals ok.

**5. Wall time, interleaved base/head, 3 runs** (sct via mmbench.py --scenes sct --jobs 1; MM600 via n64-run --frames 600)
- MM 600 fields: base 10.296 / 10.354 / 10.341 s; head 8.685 / 8.638 / 8.741 s (-16%). Head ns/instr 12.61 / 12.54 / 12.69 (688,939,808 instr).
- sct (800 M instr): base total 21.2 / 21.2 / 21.2 s (sct 20.8 each); head 20.9 / 20.9 / 20.9 (sct 20.5 each), ns/instr 25.63 / 25.67 / 25.63 (-1.4%).
- Matches the worker's numbers within noise. Base binary has no instr-count line, so ns/instr is head-only. The MM600 gain is explained by the horizon skip (RSP mostly halted in boot); in sct the RSP runs about half the time, so little is skipped. Not separately profiled by me.

**6. Design read (timeline.hpp/.cpp, cpu.cpp, rsp.cpp, memory/io.hpp) against ADR Decision 1**
- Ordering: advance() steps argmin (time, rank) among attached, non-stack, Runnable actors and the event heap head; `listed` is rank-sorted so strict `<` keeps the lower rank on ties. Stops when at > floor, or at == floor and rank >= caller (CPU is last, so everything at t runs before a CPU access at t).
- No step past an on-stack actor: floor = min(t, every stackTime on the stack). Parked/Blocked skipped by kind. The CPU is never attached so never stepped. Depth bounded by actor count (unit test asserts 2).
- Every RCP register access catches up first: Memory::RCP read/write call thread.sync() after the access cost, for AI, MI, PI, RDP, RDRAM, RI, RSP (incl. DMEM/IMEM), SI, VI. RSP's MFC0/MTC0 to DPC regs sync explicitly. Scratch threads (actor == Count) never sync.
- Horizon: schedule() and wake() lower it; CPU top-level catchUp sets it from the last scan; refreshHorizon on load; stepCap pins 0. Stale-high cases checked: SP_STATUS unhalt and dmaQueue call wake. No other path makes an actor runnable earlier.
- Sync-frequency dependence found: none observed, and stepcap (every-instruction vs horizon-skipped) is byte-equal over 8312 MM fields plus nemu64. Latent note: fireEvents(limit) uses the `limit` computed before the first handler ran. If a handler ever woke the RSP earlier than the next queued event, later events could fire before it, and the result would depend on the catchUp target. No handler does today (dmaQueue/unhalt are reached only from register writes and RSP steps), so this is a T6/T8 trap, not a bug. Same for Actor::run's "return after posting earlier than limit" contract (Deviation 1): unenforced, no current violator.
- CPU memory accesses still happen at ex time while catch-up is to instruction start plus the RCP-access sync, same as base semantics; the bus-time ordering is T6.
- Deviation 10 scope: call-site migrations, determinism/mmbench step-cap modes, README, checks.tsv, lint all plausible and needed. No dead code found besides the worker-listed haltedCycles and Readiness::blocked/await (kept for T6). Timing constants touched (VI idle 0x800 vclk liveness, PIF poll 40960 pclk) are marked as non-hardware in behaviors.tsv.

**7. bench PI DMA 8 B (cart-to-ram-8)**
- Reproduced in COUNT units: base min=max=157, head min=max=145. 12 counts = 24 CPU cycles = 16 rclk = 209.33 -> 193.33 rclk, matching the report.
- Cause check: head with only the `thread.sync()` in Memory::RCP::read removed gives min=max=157 again. So the PI_STATUS read catching the timeline up (completion fires at its own time instead of after the instruction) is the cause; one fewer poll iteration (12 counts, about one lw + and + bnez + nop) results. Other PI sizes in head: 128 B 1189, 1024 B 9001, 65536 B 583465 counts.

**Not reproduced / caveats**
- I did not rerun rdpstat, thar0, filesel_check, the other bench ROMs or the MM field-by-field diff table; the moved-point causes in the worker report for sp-dma-sweep, uncached-vs-hpos, mi-memset-rspdma are unverified by me (worker labels them inferred).
- Base has no --step-cap, so stepcap is head-only by construction.
- Commit trailers use Opus 5.5 (worker declared).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
