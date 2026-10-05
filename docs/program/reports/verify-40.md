## Verification of PR #40 (T3): PASS-WITH-NOTES

Independent run at head 9793b9b5f vs base f73be58f7 (fresh builds, build/verify-40-{head,base}).

**Commands and results**
- `behaviors.py --self-test --check`: 17/17 cases ok, "check: ok". `lint-literals.py`: ok.
- Negative cases by hand (each reverted after): removed reference on `ri.read-hit` -> "has no reference. Cite the hardware reference ... or mark the basis model-choice"; unknown verify id `bench:bogus-x` -> "not defined in tools/n64-timing/checks.tsv. Add a row there ..."; new `step(13 * 2)`-style literal in ares/n64/cpu/memory.cpp -> "timing literal ... Add a row to ares/n64/timing/behaviors.tsv, run behaviors.py ..."; `step(Timing::Behavior::RiArbitration)` (value-less row) -> "has no numeric value ... Give the row a number, or implement the rule in code that cites the row." All exit 1 with a fix named.
- Hand-edit of docs/spec/n64-timing.md: `cmake --build --target n64-timing-gen` -> "never edit the generated file", "ninja: build stopped", rc=1.
- Audit of 15 random non-legacy rows (seed 40) against research docs on origin/research/*: all cited sections exist and values match (rdram-bus-arbitration B8 10/4/22/30 tc, dma-timing 14+LAT+1 and 128 B, span-ram 64 B, rdp-write-granularity 113, jgemu rdp_core.c:5346-5362, cpu-memory-costs 41, nemu64-timing-failures C1/C5/C9). All 61 legacy rows: file:line holds the claimed literal (flash rows via the `(3500 * FlashMs)/1000` forms on lines 4 and 10).
- det (MM, `determinism.sh`): head and base both "PASS, 17 files byte-identical, 3807 fields with trace_hash"; `diff -r` of head vs base run1 differs only in wall.tsv.
- nemu64 (timing/cycle/cop0hazard): Timing 922/1604, Cycle 9/13, CP0 5/5 failed on both; summaries identical modulo wall_s.
- The generator check runs inside the real build ("Checking N64 timing behaviors ... check: ok").

**Notes**
- Lint gap: lint-literals.py skips the line matching an `auto f(...)` declaration, so `auto CPU::f() -> void { step(13); }` on one line is not flagged (reproduced; multi-line bodies are caught). No such line exists in ares/n64 today (grep), so latent only.
- Lint alone passes a reference to a value-less row; `behaviors.py --check` catches it. The build runs --check, so fine.
- Not reproduced: the worker's MM wall-time numbers (shared host; not needed for this unit). Diff touches no runtime code.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
