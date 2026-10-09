# verify-69: PR #69 (T15 unsynced attribute sampling), head 57f995de7, base e096b194a

Verdict: PASS-WITH-NOTES. Recommend landing. Every worker claim I checked reproduced. Notes are labeling/coverage, none blocking.

Setup: worktrees ares-wt/verify-69 (head), verify-69-base, verify-69-mut (depth mutants, not the PR); builds ~/n64-timing/build/verify-69-{head,base}; private homes ~/n64-timing/verify-69-home-{before,after,x}; every suite ROM rebuilt from the matching tree (pref 25). ROM sha lists results/verify-69/rom-sha-*.txt: before/after identical except new rdpstat-unsynced.z64 ef3d8ecd...; rdpstat-repeater64 sha 96bc7eef... with REPEATER64_ASSETS set. Results ~/n64-timing/results/verify-69/. Host load 2-5 for timings, up to 21 during the parallel standing run (no timing taken then). Runners copied to fresh files (pref 26). My background jobs all exited; nothing running.

## 1. rdpstat:nosync-1cycle
- base and head: rdpstat repeater64 "Failed 0 of 21" (20 No-Sync + 1 fill-sync). 
- "65": repeater64 clone (HEAD 6ec3811b) assets/ holds 65 files = 60 .test + 5 .png. The 60 .test split 20 (10000000-10000013, RDPNoSync1C: demo sets testCases = 0x10000000|t, 20 cases) + 20 (RDPFillTri) + 20 (RDPUndefShade, both `std::array<uint32_t,20>`). So RDPNoSync1C = 20; the plan's 65 counted every asset. Worker is right; checks.tsv text now says 20 references (the "other 45 assets" wording is true: 40 .test + 5 png).

## 2. snapper (measured, both sides)
rect-nosync 1C 20/20, 2C 40/40, Fill 20/20; span-tri 432/432, test-mode-rw 32/32, fill-tri-sweep 2048/2048 = 2592/2592, identical base and head.

## 3. rdpstat:unsynced-combiner
- base 0/2 (24 px and 11 px differ), head 2/2.
- Table (docs/research/rdp-command-timing.md s.3.7): "24/22: combiner, convert". ROM expects 24 cycles = 24 px (1-cycle), 22 cycles = 11 px (2-cycle, 2 clk/px). Read correctly. Code offsets in rdp_haz_stage_offset match every table row (0/0, 7/4, 13/10, 13/12, 17/14, 18/16, 20/18, 21/18, 24/22, 25/24, 26/24, 27/26, 28/28, 29/28).
- Labeling: checks.tsv expect=self, source says "n64brew ...; no console capture"; unsynced.py docstring and rdpstat README say the same; behaviors row basis wiki, not measured. Honest.
- Mutation (depth +-1 via -DMUT in engine.cpp, my worktree): -1: unsynced 0/2, repeater64 fails 20/21 (567..90 px). +1: unsynced 1/2 (1-cycle fails; 2-cycle passes), repeater64 fails 20/21. Matches the worker.
- NOTE (coverage): the 2-cycle case cannot tell 22 from 24 cycles (+1 still passes; 2*w+1 span, 24 cycles minus the dead line cycle floors to 11 px). So the table's 22 vs the captures' 24 conflict is not decided by the ROM; only the 1-cycle case pins the depth at this row. Worth one sentence in the check source.

## 4. Labels
- rdp.pipeline-depth (derived): names the fit, 7332/7332 rects, table 24 = D-1 and records "2-cycle conflicts with the table (combiner 22 there, 24 here): the captures win". Honest. Worker report says "captures 25"; the row says 24 (affected cycles = D-1). Report loosely mixed D and affected cycles; row is right.
- rdp.attribute-stage (wiki): note says "inferred: only the combiner row and Set Env Color are checked; 3L-2 bound applies to every stage as cen64 fit it for the combiner; dither_alpha_en goes with alpha_compare_en; Set Convert not collected". Honest. Gap: the other stages (texture/blender/zmode/dither) are built from the wiki alone; row says only combiner+env are checked, which implies it. The extension of the combiner's 2-cycle depth 25 to the 2-cycle combine stage (table says 22) is the unstated inference; the pipeline-depth row covers it.
- NOTE: uncollected fields (cycle type, atomic, detail/sharpen, bi_lerp: not in the table, stay per primitive) are documented only in the worker report, not in any row/comment/spec. Set Convert and dither_alpha_en are documented.

## 5. Zero change elsewhere (base vs head, measured)
- MM 600 fields --stats: md5 8148a358bfd1bbf4ed1d7eadbbab051b for base x2 and head x2 (all 13 columns incl. trace_hash identical); mem_misses=0 all four. wall interleaved (copied runners, load 2.4-5.1): base 28.68, 28.60; head 28.38, 28.50 s.
- filesel (4 mmbench scenes, via filesel_check inputs): summary/fields/gframes/rotations.tsv and scene dirs byte-identical. filesel 1.0113, named 1.6884, options 1.0000, rotate 1.0938 (named and rotate still miss acceptance, as master).
- nemu64 Timing 9/1604, Cycle 0/13, CP0 0/5, per-test files identical (only wall_s/ns_per_instruction differ). bench: expected rows fail 7 / pass 14 / report 19, output identical modulo wall. thar0: output identical modulo wall (100 specs). rdpstat: 0/7, 0/2, 0/21, 1prim 2/4 both sides, plus unsynced 0/2 on head (new). snapper above. det (nemu64 x3, MM 27 files 8219 fields) PASS both; stepcap same; state round trip 150/300/457 + TMEM poke PASS both; ctest 5/5 both; behaviors --check, --self-test, lint-literals ok.

## 6. Diff
- 16 files, +380/-55. Engine edits are in rdp_core.c/h, rdp.c/h, engine.cpp (hazard hold and snapshot live in the engine; plan named timed.cpp). Justified. rdp_render_init gets pipeline_depth from Timing::Behavior::RdpPipelineDepth.units / UnitsPerRclk; the only remaining "25" in rdp_core.c is the derivation comment at :158 (stale-looking "min(3*L-2, 25)"; harmless, could say rdp.pipeline-depth). lint-literals ok.
- dispatch (timed.cpp): spans enter the pipeline at at+setup, setup = works[0] cost. Sound: a hold opens only on the primitive's own step, so works[0] is the primitive; count==1 gives the old value (hence MM/suites identical). It is a timing change for any held primitive with collected writes (master had it for Set Env Color too): each collected setter no longer delays the next primitive's entry. No behaviors row/cite for it beyond the table's "attribute setters execute in 1 pipeline cycle" (rdp-command-timing.md s.3.7/row "Attribute setter"). Note only.
- Re-render chain: publish stable-sorts writes by pixel and copies from the previous object, so later landings carry earlier ones; for env-only this equals master's per-seg copy of h->object (monotone px). HAZ_MAX_SEG 8->32.
- Double-draw tail: pre-existing. master rdp_haz_publish (rdp_core.c:213-262 at e096b194a) renders the whole primitive, then re-renders the tail from each landing pixel (partial row + remaining rows) with the same object, so IM_RD blend runs twice / Z self-fails for env already. T15 inherits the mechanism; its magnitude grows with the landing count (one Set Other Modes changing N stages is up to N+1 overdraws of the overlap) but only for the newly collected writes, none of which master handled. Nothing currently checked uses blend/Z with these stages. The worker disclosed it.

## Not reproduced / not run
Nothing failed to reproduce. I did not rerun the worker's MM wall x4 median (took x2 interleaved; 28.4-28.7 s, no difference). thar0 band count (4/100) not recomputed; thar0 output is byte-identical to master so it cannot differ.
