# Majora's Mask bench

`mmbench` measures how many VI fields each Majora's Mask game frame takes in seven scenes. It runs on the fork's headless runner (`tools/n64-run`) and is deterministic: two runs produce byte-identical results.

The bench needs only the ROM. Each scene is a cold-boot run driven by an input script that the bench generates. No save file or save state is used, so a timing-model change cannot leave stale state behind.

## Run

```sh
tools/n64-timing/mmbench/mmbench.sh "C:/path/to/Majora's Mask.v64" [options]
```

The script builds `n64-run` with `../build.sh`, then runs `mmbench.py`. Pass the ROM in `C:/...` form: Git Bash does not convert a `/c/...` path that contains an apostrophe. You can also set `MM_ROM` and omit the ROM argument.

| Option | Meaning |
|---|---|
| `--out DIR` | Result directory. Default `$N64_TIMING_HOME/mmbench/results/latest`. |
| `--scenes LIST` | Comma-separated subset of `title,filesel,filesel-named,filesel-options,filesel-rotate,sct,field`. Default all. |
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
| `filesel-named` | As `filesel`, then name entry creates File 1 and File 2 (name "A" each), and the cursor returns to File 1. | The cursor is on File 1 of the main screen. | None. |
| `filesel-options` | As `filesel`, then stick up to Options and A. | The Options screen is up (`CM_OPTIONS_MENU`). | None. |
| `filesel-rotate` | As `filesel`, then stick up to Options. | The cursor is on Options. | Eight cycles: A rotates to Options, B saves and rotates back. The window ends after the eighth cycle, so it is not 600 fields long. |
| `sct` | Map select, entry 92 ("53: Clock Town -South-"). | South Clock Town (scene 0x6F) finishes its fade-in. | Stick up for 60 fields, then three loops: the stick turns a full circle every 180 fields. |
| `field` | Map select, entry 2 ("1: Termina Field"). | Termina Field (scene 0x2D) finishes its fade-in. | Stick up for 400 fields, then up-right for 200. |

Map select is in the retail ROM but no input reaches it. The script copies its `gGameStateOverlayTable` entry over the TitleSetup entry while the console logo runs, so the logo hands off to map select. It also sets `dREG(80)` and `dREG(81)`, which `MapSelect_Init` uses as the starting cursor. A single A press then loads the scene with `Sram_InitDebugSave`'s save data.

The file-select routes read `FileSelectState` at its fixed address, `0x803E6B20`, the fourth `malloc_arena` node. The address was found by walking the arena list at run time. Before relying on it, a route checks the arena node size (`0x24560`) and `state.gfxCtx`. Each press is held until the game state shows the game reacted, then released until the game's own controller copy reads released. Every step waits on game state, not on a field count, so the routes still work when a game frame takes more fields. The files exist only in the run's emulated flash. No save file is read or written on the host.

The `sct` loops keep Link in the plaza. A straight walk reaches an NPC that opens a textbox and stops Link.

All addresses are for NTSC-U 1.0 and come from zeldaret/mm `56fa21dd` (`tools/disasm/n64-us/variables.txt` and the struct layouts in `include/`). `mmbench.py` lists them with their sources.

## Rendering

`n64-run` always draws with the pixel engine. Each scene writes `rdp.txt`, the runner's `rdp_engine` line (render calls, render time, pixels, ns per pixel). Before the engine was the only rasterizer, runs that drew no pixels produced the same window start fields and the same `origin`, `cpu_cycles`, `rsp_busy_clocks`, `dpc_start`, and `dpc_end` for all 2400 window fields as runs that drew them, so the four scenes do not read rendered pixels back into game logic. The three file-select menu scenes passed the same comparison (paraLLEl-RDP against no drawing, 2316 window fields and `rotations.tsv`) on the runner before the engine.

## Output

Every file except `wall.tsv` and `rdp.txt` (host time) is deterministic.

| File | Contents |
|---|---|
| `summary.txt`, `summary.tsv` | One row per scene: complete game frames in the window, mean fields per game frame, the distribution of game-frame lengths (1 to 5 fields, and 6 or more), mean RSP busy clocks per field, the pixels the pixel engine rasterized in the window (`rdp_pixels_window`), and two counters read from the game (see below). |
| `fields.tsv` | One row per window field: `field` (0 to 599), absolute `frame`, `origin`, the per-field deltas of `cpu_cycles` and `rsp_busy_clocks`, `dpc_start`, `dpc_end`, `cimg`, `zimg`, and the per-field delta of `rdp_pixels`. |
| `gframes.tsv` | One row per complete game frame: first window field, length in fields, and CPU and RSP clocks over those fields. |
| `buffer-confirmation.tsv` | The run-time confirmation from `docs/research/mm-buffer-placement.md` (#23), read in the `sct` window: expected and found values with a verdict. |
| `rotations.tsv` | `filesel-rotate` only: one row per Main to Options rotation game frame (7 per rotation) with its length in fields. |
| `bus.tsv` | One row per scene and RI requester (`refresh`, `vi`, `cpu`, `sp`, `dp_cmd`, `dp_color`, `dp_depth`, `dp_texture`, `dp_fill`, `pi`, `si`, `ai`): the RDRAM channel's bursts, bytes read, bytes written, row misses, RCP clocks the requester held the channel and RCP clocks it waited over the window, from the runner's `bus` script step. `busy_share` is `busy_rclk` over the window's RCP clocks, taken as its `cpu_cycles` times 2/3 (one PClock is 1.5 RCP clocks). |
| `behaviors.tsv` | The timing behaviors the runner was built with (`n64-run --behaviors`): id, basis, value, unit, checks. |
| `wall.tsv` | Host wall time, total and per scene. |
| `<scene>/script.txt` | The generated input script. |
| `<scene>/stats.tsv` | The runner's per-field stats for the whole run. |
| `<scene>/events.txt` | The window mark, every peek the script made, and the `bus` counter lines at the window's start and end. |

A game frame is the run of fields between two changes of `VI_ORIGIN`. Fields before the first change in the window and after the last change belong to frames that cross the window edge, and the bench leaves them out.

Two counters read from the game cross-check the game-frame count:

- `gfx_tasks` is the change in `gfxCtx->gfxPoolIdx`, which `Graph_Update` increments once per submitted graphics task.
- `game_frames` is the change in `GameState.frames` for Play scenes.

`cpu_cycles` counts elapsed VR4300 cycles, idle or not. Its per-field delta is therefore the field length in CPU clocks, not the CPU load.

A rotation frame's length is measured on the update side. `FileSelect_RotateToOptions` adds 50 to `windowRot` once per game frame until 314. The script marks the first field in which each value (50, 100, ..., 300, 314) is visible, and the first field of the options box slide after it. The gap between consecutive marks is the length of one rotation game frame in fields. VI origin changes cannot be tied to rotation frames without knowing the display lag.

## File-select acceptance check (#11)

```sh
python tools/n64-timing/mmbench/filesel_check.py RESULTS_DIR
```

`filesel_check.py` evaluates the acceptance table at the end of `docs/research/mm-filesel-slowdown.md` (branch `research/mm-filesel-slowdown`) against one bench result directory (`DIR`, or `DIR/run1` after `--check-determinism`):

| Row | Scene | Pass | Rank |
|---|---|---|---|
| Empty files, main screen idle | `filesel` | mean at most 1.05 fields per game frame, at least 95 % of game frames at 1 field | primary |
| Options idle | `filesel-options` | mean at most 1.05 | secondary |
| Two named files, main screen idle | `filesel-named` | mean 1.90 to 2.10, at least 90 % of game frames at 2 fields | primary |
| Main to Options rotation | `filesel-rotate` | each rotation: mean 1.0 to 1.6, at least 4 consecutive 1-field frames | secondary |

The exit code is 0 only when both primary rows pass. Secondary rows are printed but do not change the exit code.

## Gotchas

- The bench reads `GraphicsContext` at its fixed address in `sGraphStack` (`0x801F9CB8`) instead of through `GameState.gfxCtx`. In the title scene, `GameState.gfxCtx` reads 0 for some fields.
- The window marks, the input, and the peeks run between VI fields. Input set at the end of field N is visible to the game from field N+1.

## Report

`report.py OUT [--wall WALL_TSV] [--note TEXT] [--out FILE]` writes the bench report as Markdown: per-scene field times (wall time over the fields each scene runs), the RDRAM channel per requester over each window from `bus.tsv`, and the provenance table (every row of `ares/n64/timing/behaviors.tsv` with its basis and its status in `docs/spec/n64-timing-results.tsv`). It also compares the run's `behaviors.tsv` with the repository table. The scenes of one mmbench run share the host; for field times, pass `--wall` the `wall.tsv` of a run with `--jobs 1`. `docs/spec/mm-bench.md` is one such report, with `--wall tools/n64-timing/mmbench/wall-budget.tsv` (the serial medians of the Run budget in `tools/n64-timing/README.md`).
