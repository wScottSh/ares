# Unit: design-synth (arena cross-judge + synthesis for the timing core)

GOAL
Judge three independent timing-core design candidates against the rubric, pick a base, graft the best parts of the others, and write the one synthesized design package the build track will execute.

INPUT
- Candidates: C:\Users\Scott\n64-timing\design\core\candidate-{opus,fable,sonnet}\ (rationale.md, plan.md, sketch/). Read every one end to end.
- Their brief: C:\Users\Scott\.claude\orchestrate\ares-n64-timing\briefs\design-core.md.
- Grounding: `git -C C:\Users\Scott\repos\ares show origin/research/ares-timing-architecture:docs/research/ares-timing-architecture.md`; research docs on origin/research/* (list in the brief, plus hardware-corpora).
- Arena and architect procedure: C:\Users\Scott\.claude\plugins\cache\pstack-claude\pstack\0.9.67\skills\arena\SKILL.md (Phases C-F) and ..\architect\references\{rationale-template.md,design-red-flags.md}.

FACTS ESTABLISHED BY THE COORDINATOR (checked first-hand; treat as binding)
1. License: ata4/angrylion-rdp-plus ships "MAME License.txt", the old MAME non-commercial license ("Redistributions may not be sold, nor may they be used in a commercial product"). Incompatible with ares ISC. Fable's angrylion choice is out.
2. cen64 jgemu fork (gitlab.com/jgemu/cen64 @ 2f8d7bc) is BSD-3 (LICENSE: Tyler J. Stachecki 2015, Rupert Carmichael 2025-2026; LICENSES adds Ryan Holtz 2011-2023 for the MAME-lineage RDP). A full clone is at C:\Users\Scott\AppData\Local\Temp\claude\C--Users-Scott-repos-ares\9b50e916-d60e-4b8b-8c45-7ac981964d4b\scratchpad\jgcen64 (src/rdp/). ares's own MAME RDP removed in 5f9804fb6 was BSD-3 (MAMEdev) and "too slow to be usable".
3. Harness measurement (coordinator rerun): MM 600 VI fields, interpreter, --rdp none, today's core: 8.5 s wall, byte-identical across runs (deterministic entropy on). Recompiler 1.44 s. Budget is 120 s.
4. Delivery: nobody can merge; build work is a linear stack of PRs Scott lands (standing orders line 12). External test ROM builds (cargo, libdragon) are blocked for agents; verification corpora come from our own in-repo Python ROM generator (unit romgen, porting nemu64-test now), MM bench (unit mmbench), prebuilt ROMs (rasky pi_dma_test, hydra-emu rdp tests, bigbass timing) and ports of MIT corpora (Thar0 RDP-Timing-Tests next). Plans must use only these.

RUBRIC (score each candidate 1-5 per row, with one-line reasons)
1. Exactness: bus/contention order is a pure function of timestamps, independent of sync frequency, bit-deterministic.
2. Coverage: every map decision (#2-#29 research docs) has a concrete home in the shape.
3. Interface depth and ownership: single owner of RDRAM bytes and RDRAM time; small public surface; no red flags.
4. Plan quality: verifiable units, each ending on a check that the available verification (fact 4) can actually run, ordered on a green base, subtraction first.
5. License and provenance compliance (fact 1-2).
6. Budget realism against fact 3.

OUTPUT
Write C:\Users\Scott\n64-timing\design\core\synthesis\:
- judge.md: rubric scores per candidate, recommended base, rationale.
- rationale.md: the synthesized package per rationale-template.md, Synthesis decision filled (base, grafts with source candidate, rejections with reason).
- plan.md: the build sequence as units for the program. For each unit: id, goal, files/areas touched, depends-on, check (exact verification using fact 4 sources with expected results or the reference value), and difficulty (hard/normal). Units must be sized for one agent in roughly 3-6 hours. Include the spec work: constants TSV + generator + generated spec docs, and the final spec assembly for the map.
- sketch/: the merged header sketch.
Resolve divergences explicitly: time unit (750 MHz LCM vs 187.5 MHz), CPU model (scoreboard vs stage-time recurrence), RDP source (now cen64-jgemu port vs restoring ares's MAME RDP), arbitration default, recompiler fate, where paraLLEl goes (deleted vs kept as presentation/oracle).

TIMEBOX
About 2 hours. Write nothing outside the synthesis directory.

REPORT
Return: base pick and scores table, the divergence resolutions (one line each), unit list (id + one line + check), the top 3 risks.

STANDING
Read C:\Users\Scott\.claude\orchestrate\ares-n64-timing\preferences.md.
