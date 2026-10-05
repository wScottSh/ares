## Verify T12 (PR #52, head 9c5824b51): PASS-WITH-NOTES

Own builds from fresh worktrees: head `build/verify-52-head`, base (merge-base 425265069) `build/verify-52-base`. Driver: a copy of the worker's standing.sh pointed at my worktree; results in `results/verify-52/{head,base,sct}`.

### Raw numbers (all reproduced)
| Check | Base | Head |
|---|---|---|
| unit:timeline / unit:dpc-regs | n/a | `timeline: ok`, `dpc-regs: ok` |
| timeline mutation 1 (`limit()` returns `limit`) | n/a | both new cases FAIL (265, 279), 2 failures |
| timeline mutation 2 (`fireEvents` loop compares `events[0].at < limit`) | n/a | event case FAIL (279), 1 failure |
| rdpstat status / dpc / pixels failed | 0/7, 2/2, 0/21 | 0/7, 0/2, 0/21 |
| nemu64 Timing/Cycle/CP0 failed | 922/9/5 | 922/9/5; tests.tsv and values.tsv `cmp` identical in timing, cycle, cop0hazard; `Clock CPU vs RDP` pass both |
| thar0 cfg 84 / 92 BUF (1-cycle) | -1 | 77772 / 77772 (min=avg=max) |
| thar0 cfg 85 / 93 BUF (2-cycle) | -1 | 155052 / 155052 |
| det / stepcap | n/a | PASS, 27 files, 8307 fields each |
| state-roundtrip | n/a | PASS 600 fields; TMEM poke PASS |
| gen (--check, --self-test, lint) | n/a | ok |

MM sct window (ARES_DPLOG, `dplog-check.py --from 4495000000`, window start derived from run end minus the summed window cpu_cycles*8): C/D loops 180, 57,746 extra reads, longest 1,282; 106,327 END writes, 72,128 with CURRENT trailing, 16,643 END_PENDING; DPC_START with START_VALID=1: 0; 200 DP irqs, RSP halted at all 200, 11,920-130,448 units after the last END write; stall B 199 loops. All match the worker's report exactly. Plan's "START written while START_VALID=1" is NOT exercised (0), as the worker says.

### Notes
1. Fit rows are circular as checks. `rdp.primitive-base` 12, `rdp.span-dead-pixels` 2, `rdp.span-line-gap` 2 are solved from two data points (Thar0 77,772 / 155,052), and their check column is `thar0:alpha-fail-1cycle` / `-2cycle`, the same data. The thar0 84/85/92/93 exact matches therefore verify the arithmetic, not the model. The only non-circular content: base 12 comes out equal from both the 1-cycle and 2-cycle data. Basis `fit` and the data are stated honestly; the table does not say the check is the fit data. Recommend a note. Triangles reuse the base with no reference (stated).
2. `rdp.span-dead-pixels` cites n64brew "a dead cycle at the end of every line" (1 slot) but the fitted value is 2 px (4 clk in 2-cycle). The cite supports the existence, not the magnitude; the row should say so. span-line-gap's MiSTer "LINEIDLE + PREPARELINE = 2" is corroboration read from research/rdp-command-timing.md, not checked against RTL by me.
3. `rdp.sync-full` and `rdp.xbus-fetch-rate` are model-choice and say so with reasons; no fit-to-check issue. xbus rate rests on cen64 only.
4. Host-dependence (timed.cpp read in full): `steady_clock` is used only for `engine.renderNanoseconds` (stats column in n64-run), never fed back into emulation. `ARES_DPLOG` getenv only writes a log. Dispatch results depend on FIFO contents at dispatch time, which are timeline-derived; stepcap PASS (byte-identical) supports sync-frequency independence on all mm scenes and nemu64 ROMs. No host-timing dependence found.
5. Scope beyond plan list (worker disclosed): rsp.cpp, timeline.hpp wake limit, mmbench filesel-rotate wait, build.sh. filesel_check named-files row still FAIL (mean 1.0000, pre-existing; not moved).
6. Worker disclosed `taskkill /IM n64-run.exe` killing PID 12688, possibly another unit's run, contrary to standing order 20. Not verifiable by me; coordinator should check T6.
7. det field count 8307 vs 8312 base: expected from the timing change.

Not reproduced independently: wall-time table, MM 600-field fb_hash equality against base (not run), PIPE +4/+5 delta (visible in my thar0 log as +4.0/+5.0, matches).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
