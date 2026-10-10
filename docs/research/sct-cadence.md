# South Clock Town cadence on hardware: none found for the bench's state

Unit U-SCT of `docs/design/green-plan.md` (P1). The question: can an existing hardware capture give `mm:south-clock-town` a coarse fields-per-frame band, as the #11 captures gave the file-select rows?

## Answer

None found. No published capture or measurement shows Majora's Mask in the state the bench runs. The bench uses human Link on day 1 at 12:00, loaded through map select with the debug save, and runs scripted circles in the plaza. The captures that exist show other states. They also show that the cadence in South Clock Town depends on the view. In capture W, the same scene, day and form give 2.99 fields per game frame in one 4-second window and 3.27 in a 15-second plaza window (measured). A band taken from one view therefore says nothing about another view. `mm:south-clock-town` stays report-only. Its hardware value comes from the #16 console run, item `16.mm-bench-scenes`.

## What the captures show

All numbers come from `sct-cadence/run.sh`. It reuses `framediff.py` and `bursts.py` from `mm-filesel-slowdown/`. `sct-cadence/summary.py` keeps only high-motion bursts (median diff at least 2, at least 15 new frames), because `mm-filesel-slowdown.md` found low-motion bursts unreliable. Fields per game frame = mean interval × 59.826 / capture fps. The measurements were rerun on 2026-10-10 and match this doc.

| Capture | Window | State | Frames | At 3 fields | Fields per game frame |
|---|---|---|---|---|---|
| W | 765.0-940.0 s, 15 bursts | Deku Link, day 1 morning, from the Clock Tower exit (title card at 770 s) until the East Clock Town title card at 940 s | 1370 | 92.6% | 3.078 pooled. Per burst 2.84 to 3.27 |
| W | 877.3-891.8 s | the same, Deku Link walking in the plaza toward the carpenters and the tower base, NPCs on screen | 264 | 73.1% | **3.267**. There are runs of `3434...` and `4444...` |
| W | 922.6-939.97 s, 3 bursts | the same, other views | 193 | 100% | 2.994 |
| U | 9034.1-9042.9 s | Deku Link, day 1 (clock reads "1st"), entering from the west (title card at 9034 s) | 166 | 51.8% | 3.045 |
| U | 9060.5-9074.0 s | the same, second entry (title card at 9060 s), stairs and plaza edge | 264 | 42.4% | 3.044 |
| U | 10654.9-10661.2 s | human Link, day 2, west stairs only, then the fade to West Clock Town | 129 | 79.1% | 2.860 |

Capture tags follow `mm-filesel-slowdown.md`:

- **W** is YouTube `UpYHyLo3-aQ`, WatchmeplayNintendo, Part 1, 2015-11-15, 59.94 fps. Per its description it was recorded from a real N64 with the official S-video cable, a US Collector's Edition gold cartridge, and a DVD recorder that upconverts to 480i before a Hauppauge HD PVR. The description notes that the game uses the Expansion Pak. NTSC is inferred because a US cartridge plays only on an NTSC console. Its chain is clean (`mm-filesel-slowdown.md`: 408 of 428 gameplay intervals at exactly 3). The 59.94 Hz capture of a 59.826 Hz source adds one capture frame about every 8.8 s, which is 0.2% (inferred).
- **U** is YouTube `57fdDCbAs28`, UltraNova5000, "Real Hardware Let's Play pt.1", 2019-10-24, RGB, 60.000 fps. NTSC is inferred from the cadence. A 50 Hz PAL console would give about 3.6 capture frames per 20 fps game frame, not 3.0. Per frame, U jitters by ±1 capture frame (the 2s and 4s pair up), so only its window means are usable (`mm-filesel-slowdown.md`). The sections were cut with `--force-keyframes-at-cuts`, which re-encodes them. Duplicates still read as duplicates (most intervals are 3 or a 2/4 pair).

Window means include the occasional non-gameplay stall: a textbox opening, the 9 and 10+ intervals in W 837-844 s, and fades. That is why W's 2.84 and 2.95 windows sit under 3. They hold low-motion tails and 1s or 2s from fades, not frames faster than the game's divisor.

## Why none of it becomes a check

A usable source has to name the console (NTSC, Expansion Pak) and the scene state, and give a number a band can come from. W and U pass on the console. They fail on the state.

1. **Player form.** The bench is human Link (`MapSelect_Init` sets `PLAYER_FORM_HUMAN`, `z_select.c:1092`). W and U are Deku Link in every South Clock Town window with more than 10 s of gameplay. The only human window, U at 10654 s, is 6 s on the west stairs on day 2.
2. **Time and NPCs.** The bench starts at 12:00 on day 1 (map select's default cutscene setting 0 sets `CLOCK_TIME(12, 0)`, `z_select.c:868-873`). W runs a little after 06:00 on day 1 (inferred: the first exit from the Clock Tower), and U's hour is not shown. The NPC schedule, and so the draw load, differs.
3. **View.** The bench circles the plaza under scripted stick input (`tools/n64-timing/mmbench/README.md`, scene `sct`). No capture follows that path. W shows that the view alone moves the cadence from 2.99 to 3.27 inside one scene state. A band carried from a different view would be a guess.
4. **A one-sided band has no power.** MM gameplay asks for divisor 3, so "at least 3.00" holds for any model that is not too fast. The model already reads 3.0000 (198 of 198 frames at 3, standing run `calib-kit-merge`). An upper bound would have to come from the bench's own state, which no source shows.

Other places searched:

| Candidate | Why it fails |
|---|---|
| `mm-filesel-slowdown.md` captures U and W, as first used | Their gameplay checks (U 525-560 s, W 270-300 s) are the opening in the Lost Woods and Clock Tower, not South Clock Town |
| `mm-rdp-stream.md` (South Clock Town, 3.00 VI per frame) | ares traces, not hardware |
| `scheduler-granularity.md`, `recompiler-parity.md`, `determinism.md` | the fork or ares running the `sct` window, not hardware |
| TASVideos and speedrun timing for MM | made on emulators. No console cadence for a named South Clock Town state turned up (web search, 2026-10-10) |
| Dolphin forum, "majoras mask runs like crap", Admentus, 2018-01-20 | "lag is present on the actual hardware itself too and is mostly noticeable within Clock Town" refers to the GameCube Collector's Edition, not an N64, and gives no number |
| Other `origin/research/*` docs | none measures MM on a console |

## What would close it

- **#16, item `16.mm-bench-scenes`.** Run the bench's `sct` scene on the console with the BENCH ROM (U-MMR in `green-plan/pending.md`). That gives the bench's own state and view, so its spread can set the band.
- **A bench scene matched to W 877-892 s, without hardware.** Load map select with the morning setting (cutscene 0x8000, 06:00) and the Deku form, then drive Link from the Deku flower toward the carpenters along W's path. The fork's 3.00 could then be compared with W's 3.27 window. The risk is the camera. Matching W's camera closely enough to inherit its view is unproven. It is a follow-up, not part of this unit.

The table also says something about the model, though it asserts nothing (inferred). Hardware drops to 3.27 fields per game frame in the plaza with NPCs on screen. The fork holds 3.00 on every frame of its own plaza window. That fits the RDP time the fork lacks (`mm-filesel-slowdown.md`). A check on it needs the matched state above.
