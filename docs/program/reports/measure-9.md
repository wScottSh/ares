# measure-9 report (#9 scheduler granularity)

Status: done. Doc pushed, no PR.
Branch: research/scheduler-granularity. Head: 1b33a85e52bc91e2c5f54b3e1cdb591fadb2676c.
Doc: https://github.com/wScottSh/ares/blob/research/scheduler-granularity/docs/research/scheduler-granularity.md
Artifacts: docs/research/scheduler-granularity/ (instrumentation.patch, n64-run-on-mmbench.patch, bench/matrix scripts, configs, analyze.py, arb2.cpp, logs, analyze-output.tsv). Raw stderr/stats: C:\Users\Scott\n64-timing\m9.

Map gist: the ADR shape costs about 11.8 s per 600 MM sct fields with today's devices. CPU-RSP alternation is about 8.3 ns per RSP-running CPU instruction (2.1 s). The horizon check is not measurable. Arbitration is 20 to 55 ns per burst (0.3 to 1.8 s). That leaves about 92 to 98 s of the 120 s budget.

Key numbers (min of 6 to 10 interleaved runs, noisy shared host):
- The sct window (mmbench South Clock Town, fields 329-929) is the realistic load. The RSP runs during 53% of CPU instructions there, against 7% during boot. Today's interpreter takes 14.05 s instrumented (about 12.9 s without counters, inferred), against the 8.5 s boot figure the ADR cites as fact 3.
- Full sync per instruction while the RSP is halted: 2.9 ns (sct) and 3.8 ns (boot) per sync skipped by the horizon.
- Full sync per instruction while the RSP runs: 14.7 ns. RSP-only alternation (the ADR shape, mode 3): 8.3 to 8.6 ns. The ADR assumed 3 ns.
- Floor with all-device batching at 512 clocks: 9.68 s (sct). Batching coarser than that gains almost nothing.
- arb2 (ADR Decision 2 shape: per-requester FIFOs, argmin rank/arrival, 8-bank row/dirty, memcpy, callback, 6-actor min scan): 19.7 to 27.7 ns per grant at the minimum, up to 53 ns. The ADR assumed 50 to 100 ns.
- Bursts per 600 sct fields: 12.3 M non-RDP, measured or inferred. RDP is 5 to 20 M, inferred because --rdp none counts nothing.
- Horizon skip is not exact today. cpu_cycles and rsp_busy_clocks at field 928 differ by mode, because CPU reads of RCP registers do not catch devices up. This is consistent with the ADR's requirement of catchUp before cross-device access.
- Recompiler appendix (prior agent's data, boot): 1.48 s at JitInterleaving 4096, 1.62 s at 0, 2.21 s with the RSP interpreter.

Suggested ADR budget edits: anchor "interpreters today" on sct (13 to 14 s). Set the alternation row to 249 M x 8.3 to 8.6 ns = 2.1 s. Set the RI row to 20 to 55 ns per burst. catchUp must not walk idle actors: stepping the 4 other devices and the queue each RSP-running instruction costs another 7 ns.

Reused from the prior agent: its core instrumentation (counters, chunk/bussync/jit knobs), bench.sh, matrix2 recompiler data, and arb.cpp (superseded by arb2.cpp). Not reused: its rdtsc per-device profile (dominated by rdtsc overhead) and its RIP sampler symbolization (the exe is stripped, so attributions were wrong).

Added: M9_MODE 1/2/3 (horizon skip, batch floor, RSP-only alternation), the window snapshot at the script's `mark`, and an n64-run built from the mmbench runner so the sct script plays.

Open questions:
- The CPU pipeline scoreboard cost (the ADR's "+5 ns") is unmeasured until that code exists.
- RDP burst counts need the RDP actor.
- The host was shared with other agents' builds and runs. Medians are 5 to 10% above the minimums, and single runs swung up to 2x. An idle-host rerun would tighten the numbers.
- A dedicated RSP single-step entry point might cut part of the 8.3 ns alternation. Not tried.

Notes: no permission denials. The worktree keeps uncommitted instrumentation and the mmbench runner files, which are never delivered. Only docs/research was committed.
