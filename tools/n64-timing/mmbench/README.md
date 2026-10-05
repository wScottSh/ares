# Majora's Mask bench

`mmbench` measures how many VI fields each Majora's Mask game frame takes in four scenes. It runs on the fork's headless runner (`tools/n64-run`) and is deterministic: two runs produce byte-identical results.

The bench needs only the ROM. Each scene is a cold-boot run driven by an input script that the bench generates. No save file or save state is used, so a timing-model change cannot leave stale state behind.

## Run

```sh
tools/n64-timing/mmbench/mmbench.sh "C:/path/to/Majora's Mask.v64" [options]
```

The script builds `n64-run` with `../build.sh`, then runs `mmbench.py`. Pass the ROM in `C:/...` form: Git Bash does not convert a `/c/...` path that contains an apostrophe. You can also set `MM_ROM` and omit the ROM argument.

| Option | Meaning |
|---|---|
| `--out DIR` | Result directory. Default `$N64_TIMING_HOME/mmbench/results/latest`. |
| `--scenes LIST` | Comma-separated subset of `filesel,sct,field,title`. |
| `--jobs N` | Parallel runs. Default one per scene. |
| `--check-determinism` | Runs the bench twice into `DIR/run1` and `DIR/run2` and fails unless every output except `wall.tsv` and `rdp.txt` is byte-identical. `--shots` makes `script.txt` differ too (the shot paths name the run directory), so do not combine the two. |
| `--shots` | Saves `start.ppm` and `end.ppm` per scene from the RDRAM image the VI samples. Use it only to check the scenes visually. |

The bench accepts only the NTSC-U 1.0 ROM (MD5 `2a0a8acb61538235bc1094d297fb6556` after conversion to big-endian `.z64`, as listed in zeldaret/mm `baseroms/n64-us/checksum-compressed.md5`). `.z64`, `.v64`, and `.n64` byte orders are accepted.

## Scenes

Each scene measures a window of 600 VI fields. The window starts at a game-state condition, not at a fixed field number, so it still lines up when the timing model changes how long boot takes.

| Scene | Route from cold boot | Window starts | Input during the window |
|---|---|---|---|
| `title` | None. | The title Play scene (scene 0x08) finishes its fade-in. | None. |
| `filesel` | Title, then Start twice (game frames 10 and 60 of the title scene). | The file-select overlay is loaded. | None. |
| `sct` | Map select, entry 92 ("53: Clock Town -South-"). | South Clock Town (scene 0x6F) finishes its fade-in. | Stick up for 60 fields, then three loops: the stick turns a full circle every 180 fields. |
| `field` | Map select, entry 2 ("1: Termina Field"). | Termina Field (scene 0x2D) finishes its fade-in. | Stick up for 400 fields, then up-right for 200. |

Map select is in the retail ROM but no input reaches it. The script copies its `gGameStateOverlayTable` entry over the TitleSetup entry while the console logo runs, so the logo hands off to map select. It also sets `dREG(80)` and `dREG(81)`, which `MapSelect_Init` uses as the starting cursor. A single A press then loads the scene with `Sram_InitDebugSave`'s save data.

The `sct` loops keep Link in the plaza. A straight walk reaches an NPC that opens a textbox and stops Link.

All addresses are for NTSC-U 1.0 and come from zeldaret/mm `56fa21dd` (`tools/disasm/n64-us/variables.txt` and the struct layouts in `include/`). `mmbench.py` lists them with their sources.

## Rendering

`n64-run` always draws with the pixel engine. Each scene writes `rdp.txt`, the runner's `rdp_engine` line (render calls, render time, pixels, ns per pixel). Before the engine was the only rasterizer, runs that drew no pixels produced the same window start fields and the same `origin`, `cpu_cycles`, `rsp_busy_clocks`, `dpc_start`, and `dpc_end` for all 2400 window fields as runs that drew them, so the four scenes do not read rendered pixels back into game logic.

## Output

Every file except `wall.tsv` and `rdp.txt` (host time) is deterministic.

| File | Contents |
|---|---|
| `summary.txt`, `summary.tsv` | One row per scene: complete game frames in the window, mean fields per game frame, the distribution of game-frame lengths (1 to 5 fields, and 6 or more), mean RSP busy clocks per field, the pixels the pixel engine rasterized in the window (`rdp_pixels_window`), and two counters read from the game (see below). |
| `fields.tsv` | One row per window field: `field` (0 to 599), absolute `frame`, `origin`, the per-field deltas of `cpu_cycles` and `rsp_busy_clocks`, `dpc_start`, `dpc_end`, `cimg`, `zimg`, and the per-field delta of `rdp_pixels`. |
| `gframes.tsv` | One row per complete game frame: first window field, length in fields, and CPU and RSP clocks over those fields. |
| `buffer-confirmation.tsv` | The run-time confirmation from `docs/research/mm-buffer-placement.md` (#23), read in the `sct` window: expected and found values with a verdict. |
| `wall.tsv` | Host wall time, total and per scene. |
| `<scene>/script.txt` | The generated input script. |
| `<scene>/stats.tsv` | The runner's per-field stats for the whole run. |
| `<scene>/events.txt` | The window mark and every peek the script made. |

A game frame is the run of fields between two changes of `VI_ORIGIN`. Fields before the first change in the window and after the last change belong to frames that cross the window edge, and the bench leaves them out.

Two counters read from the game cross-check the game-frame count:

- `gfx_tasks` is the change in `gfxCtx->gfxPoolIdx`, which `Graph_Update` increments once per submitted graphics task.
- `game_frames` is the change in `GameState.frames` for Play scenes.

`cpu_cycles` counts elapsed VR4300 cycles, idle or not. Its per-field delta is therefore the field length in CPU clocks, not the CPU load.

## Gotchas

- The bench reads `GraphicsContext` at its fixed address in `sGraphStack` (`0x801F9CB8`) instead of through `GameState.gfxCtx`. In the title scene, `GameState.gfxCtx` reads 0 for some fields.
- The window marks, the input, and the peeks run between VI fields. Input set at the end of field N is visible to the game from field N+1.
