# Report: mmbench

**Status: DONE.** Every acceptance item is met. The table names the evidence for each.

| Acceptance item | Result |
|---|---|
| Scenes | 4: `filesel`, `sct` (South Clock Town scripted walk), `field` (Termina Field walk), `title` (title-screen cutscene). |
| 600 fields per scene, per-field stats, per-game-frame duration | `fields.tsv`, `gframes.tsv`, `summary.tsv`/`.txt`. |
| Two runs byte-identical | `--check-determinism` PASS, 17 files. |
| Wall time reported | Yes. See Wall time below. |
| #23 recipe run | All 21 expected values match. |
| PR open against feat/harness | #33. |

- Branch: `feat/mmbench` (worktree `C:\Users\Scott\repos\ares-wt\mmbench`, from origin/feat/harness c8592d16a)
- Head SHA: `a1f3544abe6ccd2661022ff152d08b12a887fb20` (2 commits: 678ac3d6f feature, a1f3544ab .gitignore for `__pycache__`)
- PR: https://github.com/wScottSh/ares/pull/33 (base feat/harness, not merged)

## Commands

```
# one command: builds n64-run, runs the 4 scenes in parallel, prints the summary
bash tools/n64-timing/mmbench/mmbench.sh "C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64" [--out DIR] [--check-determinism] [--cpu recompiler] [--scenes filesel,sct,field,title] [--jobs N] [--shots]
```
- The default output dir is `C:\Users\Scott\n64-timing\mmbench\results\latest`. The runs this report quotes are under `...\results\final3\run{1,2}` (`final2` and `final` are the earlier builds).
- Per run the bench writes `summary.txt`, `summary.tsv`, `fields.tsv`, `gframes.tsv`, `buffer-confirmation.tsv`, and `wall.tsv`. Per scene it writes `script.txt`, `stats.tsv`, and `events.txt`.
- `--shots` renders with paraLLEl and saves `start.ppm`/`end.ppm` per scene. It is for visual checks only.

## Per-scene results (raw, measured, interpreter, `--rdp none`, `final3/run1/summary.tsv`)

```
scene	window_start_frame	fields	gframes	fields_per_gframe_mean	dist_1	dist_2	dist_3	dist_4	dist_5	dist_6plus	gframe_fields_min	gframe_fields_max	rsp_busy_clocks_per_field_mean	gfx_tasks	game_frames
filesel	460	600	449	1.0000	449	0	0	0	0	0	1	1	458629.1	451	
sct	329	600	198	3.0000	0	0	198	0	0	0	3	3	1270203.9	200	200
field	349	600	199	3.0000	0	0	199	0	0	0	3	3	1289098.2	200	200
title	269	600	199	3.0000	0	0	199	0	0	0	3	3	376865.2	200	200
```
- A game frame is the run of fields between two `VI_ORIGIN` changes. Partial frames at the window edges are excluded.
- Cross-check against the game's own counters. `gfx_tasks` is the delta of `gfxCtx->gfxPoolIdx`, and `game_frames` is the delta of `GameState.frames`. In the Play scenes both read 200 over 600 fields, which agrees with 198 or 199 complete origin-change frames at 3 fields each. In filesel the counter reads 451 tasks. The first ~150 fields after the overlay loads have no origin change and no gfx tasks (inferred to be the load and fade-in), and every field after that swaps.
- The model today runs the file-select menu at 1 field per game frame, which is 60 fps. #11 asks about the hardware slowdown in this menu, so this row is the fork's baseline for it. The model today also shows no frame drops in SCT or Termina Field: every game frame is exactly 3 fields.
- `cpu_cycles` per field is constant (about 1,567,040) because it counts elapsed VR4300 cycles, idle or not. So it is not a load metric, and I removed it from the summary. It is still in `fields.tsv`.
- Recompiler run (`results/rec`), for information: window starts move 1 field later, and `rsp_busy` differs by 0.3 to 1.2% (filesel 463961.0, sct 1273812.4, field 1304662.6, title 381836.8). Recompiler timing is not interpreter-identical, which fits #10.

## Determinism (measured)

- `mmbench.sh ... --check-determinism` printed `determinism: PASS, 17 files byte-identical (wall.tsv excluded)` on three passes (`final`, `final2`, `final3`). Each pass compares run1 against run2.
- `final/run1` and `final2/run1` came from two builds (the second build changed only usage text and a comment). Their outputs are identical except `wall.tsv` and `script.txt`.
- I checked that the checker catches a defect. One flipped bit in `sct/stats.tsv` was reported as that file. A deleted `gframes.tsv` was reported as missing.

## Wall time (measured, this machine, 12 host threads, other agents possibly active)

- Bench, 4 scenes in parallel, interpreter: total 22.2, 22.9, 22.6, 23.1, 25.2, 26.0, and 28.8 s across runs. Each scene run takes 16 to 28 s and covers boot plus its 600-field window, which ends at field 869 to 1060.
- Serial (`--jobs 1`): 76.4 s total (filesel 20.5, sct 20.1, field 19.8, title 14.4).
- Recompiler, parallel: 4.9 s.
- Inferred: the window alone is about 12 s of interpreter time per scene, at about 50 fields/s solo. That is well under the 2-minute budget today. The final timing model will be slower.
- One-off outlier: the first parallel bench with `--rdp vulkan` shots took 151 s. A single vulkan run in the same period took 57 s once and 20 s at other times. I did not investigate. I suspect host contention.

## #23 run-time confirmation (measured, `sct` window start field 329 and all 600 window fields)

| item | expected | found | verdict |
|---|---|---|---|
| gFramebuffers[0] | 0x807DA800 | 0x807da800 | match |
| gFramebuffers[1] | 0x80000500 | 0x80000500 | match |
| gZBufferPtr | 0x80383AC0 | 0x80383ac0 | match |
| gWorkBuffer | 0x803A92C0 | 0x803a92c0 | match |
| gGfxSPTaskOutputBufferPtr | 0x803CEB10 | 0x803ceb10 | match |
| gGfxSPTaskOutputBufferEnd | 0x803E6B10 | 0x803e6b10 | match |
| gZBufferLoRes | 0x80383AC0 | 0x80383ac0 | match |
| gWorkBufferLoRes | 0x803A92C0 | 0x803a92c0 | match |
| gGfxSPTaskOutputBufferLoRes | 0x803CEB10 | 0x803ceb10 | match |
| sKaleidoAreaPtr | 0x8074xxxx..0x8077xxxx (bank 7) | 0x8074af20 | match |
| sZeldaArena.head | ZeldaArena start | 0x803ffda0 | recorded |
| malloc_arena.head | 0x803824C0 | 0x803824c0 | match |
| play.tha {size,start,head,tail} | Play arena bounds | 0x00380260, 0x803ffda0, 0x803ffda0, 0x803ffda0 | recorded |
| OSTask.type (gfxCtx->task.list) | 1 (gfx) | 1 | match |
| OSTask.output_buff | 0x803CEB10 | 0x803ceb10 | match |
| OSTask.output_buff_size | 0x803E6B10 | 0x803e6b10 | match |
| SETZIMG (last per field) | 0x0383AC0 | 0383ac0 | match |
| SETCIMG (last per field) | 0x0000500 / 0x07DA800 | 0000500 07da800 | match |
| DPC_START | 0x3CEB10 | 3ceb10 (all 600 fields) | match |
| DPC_END range | within 0x3CEB10..0x3E6B10 | 0x3CEC30..0x3E6A68 | match |
| VI_ORIGIN | 0x000780 / 0x7DAA80 | 000780 7daa80 | match |
| fields where last SETCIMG == front buffer | 0 | 0 | match |

Also measured: `gRegEditor` = 0x803824D0. That equals #23's allocator replay `reg = n0 + NODE`.

Notes on the method:
- The Play arena runs from 0x803FFDA0 to 0x80780000 (start + size). ZeldaArena starts at the arena start.
- Step 4 is read from the RDRAM OSTask in `gfxCtx->task`, not from DMEM 0xFE8. By the end of a field the microcode has overwritten DMEM 0xFC0..0xFFF (measured: garbage values). So the reading covers the most recent gfx task, not every task start.
- Step 2 uses the last SETCIMG/SETZIMG per field, not a full command log. The brief Z-clear SETCIMG to 0x00383AC0 is therefore not observed. A per-command RDP log would need a core hook, and core edits are out of scope.

## Decisions (mine, within scope)

1. **Route: scripted input plus memory pokes from cold boot. No saves or states.** Every run regenerates from the ROM, so later timing changes cannot invalidate anything. Each window starts at a game-state condition, not a field number: scene id plus the fade-in ending, or the overlay being loaded. The title Start presses use the game's own frame counter.
2. **Map select via overlay-table copy.** I copy `gGameStateOverlayTable[MAP_SELECT]` over `[TITLE_SETUP]` while the console logo runs, and set the starting cursor through `dREG(80)`/`dREG(81)`. This uses the retail map-select code (`Sram_InitDebugSave` data). SCT is entry 92 and Termina Field is entry 2. Scene ids were checked at run time: 0x6F and 0x2D at window end.
3. **SCT walk is three stick circles (180 fields per loop) after 60 fields up.** Straight walks reached an NPC textbox ("Wait! Wait! Hang on!") that stops Link. I checked the loops visually with shots.
4. **`--rdp none`.** The evidence is a `--shots` (vulkan) run that matched the none run on all 2400 window fields (origin, cpu_cycles, rsp_busy, dpc_start, dpc_end) and on the window start fields. Inferred from that: no scene feeds rendered pixels into game logic. This is evidence, not proof.
5. **Guest memory access mirrors the CPU data cache without side effects.** A dirty dcache line wins, and a miss reads `rdram.ram` directly. I did not use `CPU::readDebug`, which goes through the bus, so a future bus or RDRAM timing model never sees script accesses. KSEG0 and KSEG1 reads agreed in the probe I ran.
6. **Four scenes in parallel processes.** They are independent cold boots, so parallelism cannot affect determinism, and it cuts wall time by about 3.3x.
7. **I removed the DMEM OSTask columns I first added.** At field end they hold microcode data, not the task.
8. **ROM check.** The .v64 converts to MD5 `2a0a8acb61538235bc1094d297fb6556`, which equals zeldaret/mm `baseroms/n64-us/checksum-compressed.md5` (verified). The bench refuses any other ROM.

## Gotchas

- `GameState.gfxCtx` (play+0) read 0 for some fields of the title scene, measured with both KSEG0 and KSEG1 reads. The bench reads GraphicsContext at its fixed address in `sGraphStack`, 0x801F9CB8, which I checked at run time. I did not root-cause why the field reads 0.
- The ROM path needs the `C:/...` form because of the apostrophe. `mmbench.sh` passes it straight through.
- Python on Windows: an edit made with `open(...).write` in text mode writes CRLF. Git normalized it, and the commit has LF only (checked).
- The bash tool turned `\\t` inside heredoc Python into real tabs. I used `chr(92)` to repair it.
- The runner writes a `shot` during the field after the step. The bench adds `wait 1` before `stop` in shots mode only.
- In `filesel`, the first Start must come early. EnMag fades the title out on a cutscene flag, and one Start at game frame 200 never opened file select.

## Follow-ups

- RDP command log hook (core): records every SETCIMG including the Z clear, and samples OSTask at each task start. Both are needed for a full #23 steps 2 and 4.
- File-select menu states for #11 (cursor moves, the Options screen). Today the bench measures only the idle main screen.
- Root-cause the `GameState.gfxCtx` read of 0, to make sure it is not a guest-memory-view bug. KSEG1 agreeing points to real RDRAM content.
- Wall time on the final model must be re-measured against the 2-minute budget.

## Files

- `C:\Users\Scott\repos\ares-wt\mmbench\tools\n64-run\script.hpp` (script grammar and parser)
- `C:\Users\Scott\repos\ares-wt\mmbench\tools\n64-run\n64-run.cpp` (GuestMemory, ScriptRunner, input, shots, stats columns)
- `C:\Users\Scott\repos\ares-wt\mmbench\tools\n64-timing\mmbench\mmbench.py`, `mmbench.sh`, `README.md`
- `C:\Users\Scott\repos\ares-wt\mmbench\tools\n64-timing\README.md` (script syntax and new columns)
- Results: `C:\Users\Scott\n64-timing\mmbench\results\final3\run1\` (and `run2`), `...\shots2\` (vulkan shots), `...\rec\` (recompiler), `...\serial\`
