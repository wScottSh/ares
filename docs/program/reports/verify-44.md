## Verification of PR #44 (T4, clock rebase): PASS-WITH-NOTES

Independent builds (RelWithDebInfo, build/verify-44-{base,a,vi,diag,head}): base = origin/feat/t3 9793b9b5f, a = 276f75721 (rebase only), vi = b271f3fc9, diag = vi with `clock.vclk` set back to 750000000/48681818 (old period; edited only in my scratch worktree), head = 8cb75b222. Raw outputs: C:\Users\Scott\n64-timing\results\verify-44\{base,a,vi,diag,head,det-base,det-head}, compare script cmp.py there.

**1. Codemod**
- Fresh worktree at head: `clock-rebase.py --check` -> "0 line(s) to rewrite, 0 to convert by hand", rc 0. Plain run -> "rewrote 0 line(s); allowlist unchanged; table unchanged". Regenerated behaviors.hpp/.tsv/spec differ from committed only by CRLF/LF (`git diff --ignore-cr-at-eol` empty). `behaviors.py --check` ok, `--self-test` 15 ok, `lint-literals.py` ok.

**2. Rebase only (276f75721) vs base, MM 600 fields** (n64-run ROM --frames 600 --stats)
- Every column identical except trace_hash (600/600 differ; the hash serializes the clocks).

**3. VI change**
- clocks.md (origin/research/clocks, line 19): VCLK = 315/22 x 17/5 MHz = 1071/22 MHz = 48.681818182 MHz. Units per VCLK at 750 MHz = 750*22/1071 = 16500/1071 = 5500/357 (15.40616...). Matches `clock.vclk` 5500/357 in behaviors.tsv:3. Old constant 48'681'818 Hz is 3.7 ppb low (0.18/48.68e6).
- Diagnostic repeated: vi vs base: cpu_cycles 528/600 (first field 25), rsp_busy_clocks 466/600 (from 65), dpc_end 4/600 (from 112), trace_hash 600/600. diag vs base: only trace_hash differs. diag vs vi: the same 528/466/4 diffs. So the period alone explains the whole VI diff. All counts equal the worker's.

**4. AI**
- Each sample is (DACRATE+1) VCLKs via the same accumulator (ai/io.cpp, ai.cpp:31); per clocks.md:23 and n64brew AI. This removes the double truncation (+33 ppm at 32 kHz). Accumulator math: vclks < 357, numerator 5500 -> no overflow.
- Power-on: videoFrequency() = floor(750e6*357/5500) = 48,681,818; /44100 = 1103.9 -> integer 1103 VCLKs -> 48,681,818.18/1103 = 44,136.7 Hz. That is a whole VCLK divider as claimed.
- head vs vi: cpu_cycles 303/600 (from 146), rsp_busy 454/600, dpc_end 5/600 (from 157). head vs base: 526 / 495 / 7 of 600; fb_hash and every other column identical in all rows.

**5. nemu64 / det**
- Timing 922/1604, Cycle 9/13, CP0 5/5 failed on base and head (stdout "Failed" lines). tests.tsv and values.tsv byte-identical in all 3 sets (27/1605, 13/14, 6/6 lines). frames.tsv differs only in trace_hash, plus cpu_cycles in 5 of 26 timing rows (first row 1) from the VI change.
- determinism.sh on MM, head and base: "PASS, 17 files byte-identical, 3807 fields with trace_hash".

**6. Hand-written commit read (276f75721 + codemod output)**
- Clock is s64 units; 2^63/750e6 = 1.2e10 s, no overflow. Thread::clock, countClock, syncClock, rsp dma.clock, pipeline.clocksTotal (u64), pif bootTimeout (s32 -> s64), serialization via .units: all 64-bit. nall priority_queue u32 -> u64 throughout (clock, entries, step, insert, remove, ge). nall's only user is n64.hpp.
- synchronize: delta = Thread::clock - syncClock; queue steps by that delta; devices no longer rebased; stepCount truncation same as before.
- Spot-checked conversions against tick originals: PI_BUS_Write 400 ticks = pclk(200); writeForceFinish `remaining + remaining` = old ticks*2 ticks (double charge preserved); dmaDuration cycles*3 -> rclk; RSP halted 128 ticks = pclk(64); PIF 10240*8 ticks = pclk(40960); flash 3500*187500/1000 ticks = us(3500); RDP quantum 1 s -> 62.5M rclk. All exact.

**Notes (none block)**
- VI exact-VCLK change is outside the plan's expected diff (plan names only the AI +33 ppm change); documented by the worker and fully reproduced above. Plan check text should be read as "identical except AI and VCLK".
- AI power-on: truncation gives 1103 (44,136.7 Hz, +0.083%); nearest divider is 1104 (44,093.8 Hz, -0.014%). No reference cited; hardware power-on DACRATE is not modelled by any cited source, and games rewrite it. Cosmetic.
- GDB poll interval: UnitsPerSecond/60/240 = 52083 units vs old 13020 ticks = 52080 (+3 units, debug-only).
- nall/priority-queue.hpp:96 `timeToNextEvent() -> s32` truncates the now-64-bit difference; unused in tree (dead).
- PI::readWord double charge kept (worker follow-up for T8). Also thar0 checks.tsv change (aa0350a89) is outside T4 files but needed after the tools merge. Commit trailers say Opus 5.5 (worker declared).
- Not reproduced: worker's wall-time spread (host load); my 600-field runs took 8.9-9.5 s each.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
