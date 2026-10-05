# MM file-select frame rate on NTSC hardware

Ticket: wScottSh/ares#11 (map #1). Research date: 2026-10-05.
Target: NTSC retail NUS-001 with Expansion Pak, MM US 1.0 (the bench ROM).

Builds on (not repeated here): `research/1prim-cost` (the full-screen 1-cycle fill), `research/rdp-command-timing` (span rates), `research/rdp-memory-traffic` (RMW traffic, GCLK stalls), `research/rsp-rdp-fifo` and `research/mm-rdp-stream` (ring back-pressure, scheduler order), and the MM bench report (`feat/mmbench`, scene `filesel`).

Tags: **[measured]** I measured it from a capture or a bench run in this ticket. **[cited]** a source states it. **[inferred]** my reasoning; basis given.

## TL;DR

- **The threads hold no MM hardware capture.** The four YouTube links in ares-emulator/ares#2320 are ares captures. Their titles say "ares nightly ... 2x speed menu", and the ares status bar ("60 VPS") is in frame [measured]. MiSTer N64_MiSTer#27 has no capture and no measurement. The only hardware capture in either thread is OoT USA Rev 2, attached to #2320 on 2026-07-28 [measured].
- **So I measured MM on two public hardware recordings.** Both are 60 fps recordings of a real N64 playing MM US. They disagree by menu content, and the disagreement is the finding:

  | Menu state | Saves on the cart | Hardware, fields per game frame | Hardware fps | Method |
  |---|---|---|---|---|
  | Main screen, idle, cursor on File 1 | both files empty | **1.00** (0.99 to 1.02) | 60 | cursor pulse period, 2 windows |
  | Options screen, idle | both files empty | **1.00** | 60 | cursor pulse period, 16 s |
  | Title to file-select fade-in | both files empty | 1.00 (4 of 4 intervals) | 60 | per-frame diff |
  | Window rotation (Main to Options or back, 7 game frames) | both files empty | 1.00 to 1.57 per rotation, 1.20 overall | 50 | per-frame diff, 10 rotations |
  | Main screen, idle, cursor on File 1 | two named files | **2.00** (1.96 to 2.04) | 30 | cursor pulse fit |
  | Title to file-select fade-in, sub-window slides, fade to black | two named files | 2.00 (24 of 26 intervals; the other 2 are 1) | 30 | per-frame diff |
  | Window rotation | two named files | 1.50 to 1.57 | 38 to 40 | per-frame diff, 2 rotations |

  For comparison, OoT's file select runs at exactly 2.00 fields per frame on hardware in every file-select state, in two captures from two different rigs [measured].
- **The fork.** The bench `filesel` scene (empty files, idle main screen) runs at 1.0000 fields per game frame, 449 of 449 frames [cited, mmbench report]. That matches the empty-file hardware value. The match is a coincidence, because the fork's RDP takes zero time. With named files the fork would still run at 1 field [inferred: nothing in the fork's frame cost depends on RDP work], where hardware runs at 2.
- **The limiting unit is the RDP [inferred, strong].** On hardware the MM file-select frame finishes almost exactly at the 16.7 ms field boundary. Small content changes push it across. Three observations point at the RDP:
  1. MM asks for 60 fps here (`GameState_SetFramerateDivisor(&this->state, 1)`, `z_file_choose_NES.c:2512`). A 2-field frame is therefore a missed retrace, not a game choice.
  2. The fork's RSP is busy 4.95 ms per field (median) and 5.69 ms at most, gfx plus audio [measured]. That is a third of a field.
  3. An RDP estimate from the display lists gives about 333 k clocks (5.3 ms) of pixel compute and about 0.85 MB of RDRAM traffic per frame. The full-screen RMW fill from `1prim-cost` is about a quarter of that compute. With the measured share of RDP time lost to memory stalls ("half to two thirds", F3DEX3, cited in `rdp-memory-traffic`), this comes to 11 to 16 ms [inferred]. That range reaches the 16.7 ms boundary, and no other unit comes near it.

  The frame time also depends on screen area. Rotation frames with the window turned edge-on fit in 1 field even where the flat window takes 2 [measured]. I did not measure CPU time.
- **Acceptance check** (the last section). On the bench, empty files must give 1.00 fields per frame, and two named files must give 2.00. The model must hit both. Together they bound the modeled RDP frame cost to a narrow band around one field.

## Captures used

| Tag | Source | What it shows | Capture rate | Chain check |
|---|---|---|---|---|
| **U** | YouTube `57fdDCbAs28`, UltraNova5000, "Zelda: Majora's Mask N64 RGB 60fps Real Hardware Let's Play pt.1", 2019-10-24 (Twitch VOD) | MM new game: file select with **two empty files**, 157 to 265 s | 60.000 | On 20 fps gameplay the per-frame intervals jitter between 2 and 4 capture frames, but the mean is 3.02 to 3.03 over 117 to 130 frames. The wall clock is right and per-frame timing has ±1 frame of jitter. The same rig records OoT's file select at strict 2-field cadence (`aTxWmxP1HZg`, 4 bursts, 61 intervals of 2). That rules out a rig that cannot show 30 fps. |
| **W** | YouTube `UpYHyLo3-aQ`, WatchmeplayNintendo, "... Playthrough (Actual N64 Capture) - Part 1", 2015-11-15. The description says it was recorded from a real N64 with a US Collector's Edition gold cartridge. | MM file select with **two named files** ("Link", "Mike"), with erase and name entry, 15 to 55 s | 59.940 | 20 fps gameplay shows 408 of 428 intervals at exactly 3 capture frames [measured]. This is a clean chain. |
| **O** | GitHub attachment on ares-emulator/ares#2320 (meauxdal, 2026-07-28), OBS 32.1.2, 2560×1440 | OoT USA Rev 2 file select on hardware | 60.000 | Duplicate frames differ by analog noise (mean abs diff 0.01 to 0.03), so each one is a separate sample of the same picture. |
| **A** | YouTube `e6dUTwfkxxU`, meauxdal, MM USA on ares nightly 20251209 (linked from #2320) | ares, not hardware | 60.000 | This is the method control: ares runs file select at 1 field per frame. |

The other #2320 links (`uuH--vVHy4c` MM JP, `BedbUxyZIDQ` OoT US, `vEd-acS0BEU` OoT JP) are ares captures as well (titles, and the status bar in frame). They are not hardware references.

The rig details of U and W (capture card, mods) are not documented beyond the video titles and descriptions. Each MM state above rests on one capture.

## Method

Every number comes from the scripts in `docs/research/mm-filesel-slowdown/`. `run.sh WORKDIR` downloads the four videos and the attachment and reruns every measurement quoted here (rerun on 2026-10-05; the output matches this doc). The videos are not committed.

Two methods, because compression noise hides single duplicate frames in idle states:

1. **Per-frame differencing for motion** (`framediff.py`, `cadence.py`, `bursts.py`). Each capture frame is cropped to the game picture, converted to grayscale, and reduced to 320×240. The script then takes the mean absolute difference from the previous frame. In a moving burst (a window rotating or sliding, or a fade), a new game frame differs by 1 to 30 levels and a repeated frame by 0.0 to 0.2. A frame counts as new above 15 % of the burst median. The interval between new frames, in capture frames, is the number of VI fields that game frame was on screen. A capture chain can drop or repeat frames, but it cannot invent distinct ones. So a run of 1-intervals in U is real 60 fps output, even though U's single 2-intervals are uncertain by ±1.
2. **Cursor-pulse period for idle states** (`pulse.py`, `trifit.py`). `FileSelect_PulsateCursor` (`z_file_choose_NES.c:522-541`) runs every game frame. It ramps the highlight alpha toward a target and flips the target every 20 game frames (`highlightTimer = 20`). So one pulse period is exactly 40 game frames at any frame rate. The scripts track the mean color of the highlighted element and fit the period. `pulse.py` takes the spectral peak over many cycles. `trifit.py` does a least-squares triangle-wave fit when a window has only 1 to 3 cycles, and reports how much worse the fit gets at 1, 1.5, 2 and 3 fields per frame. Fields per game frame = period × 59.826 / 40, where 59.826 Hz is the NTSC VI field rate (48.681812 MHz / (3094 × 263), n64brew Video Interface). Wall-clock jitter in the chain averages out over the window.

Control on the ares capture A, where ares runs at 1 field per frame: `pulse.py` gives 1.031 and `trifit.py` gives 1.00 (fit residual 64× worse at 1.5 or 2) [measured]. Control on O: 153 of 154 intervals are 2. The one 4-interval holds two bit-identical frames (mean abs diff 0.00), which is OBS repeating a frame [measured].

## Results

### MM, hardware, two empty files (capture U)

| State | Time in U | Result [measured] |
|---|---|---|
| Fade-in from title | 160.42 to 160.62 s | intervals `1111` |
| Main idle, File 1 highlighted | 161.0 to 168.6 s | pulse period 0.6625 s, so **0.991** fields per frame (spectral, 7.6 s). Triangle fit on the clean 164.0 to 167.4 s part: best 1.02, range within 1.5× of best residual 0.92 to 1.10. |
| Options idle ("Switch" pulsing) | 171 to 187 s | period 0.6684 s, so **1.000** (spectral, 16 s window, about 13 visible cycles). Triangle fit at 176 to 183 s: 1.00, residual 23× worse at 1.5, 2 or 3. |
| Window rotations (Main to Options, Options to Main, Main to Name entry and back) | 168.8, 188.3, 192.5, 200.7, 204.1, 212.0, 214.0, 243.6, 246.9, 257.9 s | intervals `1111111`, `111121`, `111211`, `111111`, `111112`, `111112`, `1111124`, `1111121`, `2111111`, `1111123`. 78 fields over 65 game frames, so 1.20 fields per frame. Every rotation has at least 4 consecutive 1-field frames. The 2s and 3s fall at the start or end, where the window faces the camera. |
| "Open this file?" info slide-in | 260.30 to 260.42 s | `112111` (low-motion burst, median diff 1.0, less certain) |
| Fade into the game | 263.57 to 263.65 s | `11111` |

### MM, hardware, two named files (capture W)

| State | Time in W | Result [measured] |
|---|---|---|
| Fade-in from title | 19.42 to 19.62 s | `2222` |
| Main idle, File 1 ("Link") highlighted | 19.95 to 21.50 s | triangle fit **2.00**, range 1.96 to 2.04. Residual 193× worse at 1.0 and 79× worse at 1.5. |
| Erase sub-window slide | 23.22 s | `222` |
| "Are you sure?" slides | 25.93, 31.60, 33.27 s | `22211222`, `222`, `22` |
| Window rotations | 35.07, 47.56 s | `211221`, `2111222` |
| "Open this file?" and fade to black | 48.92, 51.18 s | `11224222` (low-motion burst, median 0.9), `222222` |

The same rotation, frame by frame (W, 47.53 to 47.71 s): the flat window, then 4 single-field frames while the window turns through edge-on, then 2-field frames as the second window faces the camera.

### OoT, hardware (captures O and U-rig)

| Capture | State | Result [measured] |
|---|---|---|
| O | main idle, window rotation to Options, Options idle, rotation back (5.2 s) | 153 of 154 intervals are 2. The one 4 is an OBS repeat. **2.00**. |
| U-rig (`aTxWmxP1HZg`) | fade, window rotations, name entry | 61 intervals of 2 across 4 bursts. **2.00**. A fifth burst at 47.55 s, the transition out of file select into the game, shows 1.30. |

### The fork (bench `filesel`, `origin/feat/mmbench`)

- **Cadence**: 1.0000 fields per game frame, 449 of 449 complete frames, interpreter, `--rdp none` [cited: `reports/mmbench.md`, run `final3/run1`]. The scene has two empty files with File 1 highlighted (bench `shots2/filesel/end.ppm`, viewed in this ticket). That is the same state as U's 161 to 168 s.
- **RSP busy** per field, steady part (fields 160 to 599): median 619,284, mean 603,162, max 711,528 scheduler clocks [measured, `final3/run1/fields.tsv`]. The units are "the core's scheduler clocks (2 per PClock)" (`tools/n64-timing/README.md` on `feat/mmbench`; I did not re-derive them). That is 309.6 k RCP clocks = **4.95 ms** median and 5.69 ms max, gfx plus audio.
- **RDP time**: zero. ares renders on each `DPC_END` write and sets `CURRENT = END` (`rsp-rdp-fifo` row 5), so the ucode's ring back-pressure never waits [cited].
- **Upstream ares** (capture A): 1.00 fields per frame in idle [measured]. This is the "2x speed" in #2320, measured against the OoT value of 2.

## Which unit causes the slowdown

**Frame mechanics [cited source, MM decomp `56fa21dd0`].**

- File select sets the frame-rate divisor to 1 (`z_file_choose_NES.c:2512`), so `cfb->updateRate = 1` (`graph.c:236`).
- `Sched_Schedule` dispatches a new gfx task only when the RSP and RDP are both idle and `Sched_TaskFramebuffersValid` holds. That check needs `pendingSwapBuf1 == NULL`, so the previous frame must already have been swapped in at a retrace (`sched.c:243-252, 282`).
- The CPU-side submit `Graph_TaskSet00` blocks until the previous task completes (`graph.c:155-156`).

So each gfx task starts at a retrace, and the frame stays on screen for ceil(T / 16.7 ms) fields. T is the time from that start to the RDP's `SYNC_FULL`, including audio RSP preemption, unless the CPU delivers the list later than that. A 2-field frame means T > 16.7 ms.

**Candidates.**

| Unit | Per-frame cost | Source |
|---|---|---|
| RSP (gfx + audio) | 4.95 ms median, 5.69 ms max | [measured] fork, RSP timing as ares models it. On hardware the gfx task can only take longer if the RDP back-pressures the ring (`rsp-rdp-fifo` rows 5 and 6). In that case the RDP is the limiter. |
| CPU | not measured | The bench's `cpu_cycles` counts elapsed cycles, not busy cycles (mmbench report). File select runs no actors. The CPU work is input, menu logic, skybox view and DL building (`FileSelect_Main`, `z_file_choose_NES.c:2299-2408`). I have no number, so CPU is **not excluded by measurement**. |
| RDP | 11 to 16 ms (estimate below) | [inferred] from display lists, `rdp-command-timing` rates and `rdp-memory-traffic` stall share |

**RDP estimate for the idle main screen [inferred].** Compute uses the `rdp-command-timing` rates: 1-cycle 1 px/clk, 2-cycle 0.5 px/clk, fill 4 px/clk at 16 bpp, and the cen64-measured law `14/prim + Σ spans (px·129/128 + 12)`. The draw order is from `FileSelect_Main` and the setup DLs in `z_rcp.c`.

| Draw | Mode (source) | Pixels | Compute (clk) | RDRAM bytes |
|---|---|---|---|---|
| Z clear (`func_8012CF0C(gfxCtx, 0, 1, …)`) | fill, 16 bpp | 76,800 | ≈ 19,200 | 153.6 k write |
| Skybox (`Skybox_Draw`, `SETUPDL_40`) | 2-cycle, `G_RM_OPA_SURF`, no image read | ≈ 76,800 | ≈ 160,000 | 153.6 k write + texture loads |
| Window frame, 3 DLs × 4×5 quads (`SETUPDL_42`) | 1-cycle, `G_RM_XLU_SURF` (RMW) | ≈ 41,000 (window ≈ 247 × 166 px, estimated from a W still) | ≈ 49,000 | ≈ 164 k |
| Window contents: buttons, name boxes at alpha 0 or 200, title, text | 1-cycle XLU (`SETUPDL_42`/`39`) | ≈ 15,000 to 25,000 | ≈ 25,000 incl. per-glyph TMEM loads and syncs | ≈ 60 to 100 k |
| Full-screen fill, `screenFillAlpha` (`1prim-cost`) | 1-cycle `G_RM_CLD_SURF` (RMW), atomic | 76,800 | 80,294 | 307 k |
| **Total** | | | **≈ 333,000 ≈ 5.3 ms** | **≈ 0.85 MB** |

`rdp-memory-traffic` cites F3DEX3's GCLK sampling: the RDP is stalled on framebuffer and Z I/O for "often half to two thirds of the total RDP time". With that share, wall time is 2× to 3× compute, so **10.7 to 16 ms**. The upper end reaches the 16.7 ms boundary. The band is wide, and the stall share is a figure from typical game scenes, not from this screen. Rows 3 and 4 are rough.

**Why the RDP and not the RSP or CPU [inferred from measurements].**

1. **The cost depends on screen area.** In 10 of 10 rotations on U, and in the frame-by-frame W rotation, the frames where the window turns toward edge-on fit in 1 field. The 2-field frames sit where the window faces the camera. RDP pixel work falls with the window's projected area. RSP vertex work and CPU work do not. RSP triangle setup drops only when back-face culling (`G_CULL_BACK` in `SETUPDL_42`) removes the window, but tilted, unculled frames are 1-field too.
2. **The cost depends on content near a boundary.** W's two named files add two names (8 glyphs × shadow + text each, `FileSelect_DrawFileInfo`, gated on `nameAlpha != 0`) and the file buttons' name boxes. That is a few thousand pixels plus about 32 small TMEM loads. On the RDP this is a few percent of the estimate above, which is enough to cross a boundary that U shows the empty-file frame already grazing (2- and 3-intervals at the ends of U's rotations). The CPU and RSP also do slightly more work for the names. So this point alone does not separate the units. Point 1 does.
3. **RSP headroom.** 4.95 ms median against 16.7 ms. The RSP alone would need about 3.4× its modeled cost to miss a field.
4. **Same pattern in OoT.** OoT draws the same kind of screen (sky, rotating translucent window, full-screen fill) and stays at 2 fields in every file-select state on two rigs. That fits a heavier RDP load in OoT that stays above the boundary. I did not estimate OoT's load.

**Conclusion.** The slowdown is the RDP's per-frame fill and RMW cost: skybox, translucent window, and the full-screen `G_RM_CLD_SURF` fill. With RDRAM stalls it lands within a few percent of one field. MM file select on hardware is therefore not "about 30 fps". It is 60 fps with empty files and 30 fps with two named files, and rotations fall in between. The fork's 1 field per frame is right for the bench's empty-file state, but only because the RDP costs zero there. The same zero cost makes the fork wrong for the named-file state.

## Open questions

1. **CPU time per file-select frame on hardware.** No measurement. Probe: on a calibration run (#16), sample `osGetCount` around `Graph_ExecuteAndDraw`, or log MM's own `gRSPGfxTimeTotal`/`gRDPTimeTotal` (sched.c) together with retrace timestamps.
2. **Hardware RDP time per frame.** Probe: `DPC_CLOCK` delta per gfx task, or MM's `gRDPTimeTotal`, on the empty-file and two-file screens. The acceptance check below predicts both land within a few percent of 16.7 ms.
3. **Second captures per state.** U and W are one recording each. A second rig recording an empty-file and a two-file MM file select would confirm the content dependence.
4. **One-file state.** No capture shows exactly one named file idle on the main screen. W at 34 to 35.5 s (after the erase) is too short to fit.

## Acceptance check for the finished timing model

Run the MM bench (`tools/n64-timing/mmbench/mmbench.sh`) with the interpreter on the US 1.0 ROM. Metric: mean **fields per game frame** over the complete game frames in the scene window (bench `gframes.tsv`), excluding the load and fade-in at the start.

| Bench scene state | Expected | Tolerance | Source | Bench support today |
|---|---|---|---|---|
| `filesel` as it is: two **empty** files, main screen idle, cursor on File 1 | **1.00** | mean ≤ 1.05, and at least 95 % of game frames at 1 field | Capture U, 161 to 168.6 s: 0.991 (pulse, 7.6 s) and 1.02 (fit, range 0.92 to 1.10) | yes (`filesel`) |
| Options screen idle, empty files | **1.00** | mean ≤ 1.05 | Capture U, 171 to 187 s: 1.000 (pulse, 16 s) | needs a scene: `filesel` plus a press to Options |
| Two **named** files, main screen idle, cursor on File 1 | **2.00** | mean 1.90 to 2.10, and at least 90 % of game frames at 2 fields | Capture W, 19.95 to 21.50 s: 2.00 (fit, 1.96 to 2.04; residual 193× worse at 1.0) | needs a scene: create two files through name entry in the script first. Cold boot with scripted input stays deterministic. |
| Window rotation Main to Options, empty files (7 game frames) | 1.0 to 1.6 fields per frame, at least 4 consecutive 1-field frames | per rotation | Capture U, 10 rotations, 1.20 overall | needs a scene |

**Pass rule.** The model passes when both the empty-file row (1.00) and the two-named-file row (2.00) pass. The empty-file row alone is met today by a model with zero RDP cost, so it cannot reject a model that is too fast. The two-file row alone is met by any model that is too slow. Passed together, they show that the modeled RDP frame cost sits inside the narrow band between the two loads, around 16.7 ms. The Options and rotation rows are secondary. Report a failure on them, but do not block on them, because each rests on one recording.

The fork today passes row 1 [cited: 1.0000 over 449 frames] and would fail row 3 [inferred: zero RDP time gives 1 field per frame]. Before the timing model lands, the bench needs the two-file scene, so that row 3 can be measured rather than inferred.

## Sources

- ares-emulator/ares#2320 and all 4 comments (fetched with `gh`, 2026-10-05). The hardware capture is the OoT attachment from meauxdal, 2026-07-28. flagrama comment (2026-07-28): "The menu runs at 60 draw updates per second, but it seems on hardware there is a ton of slowdown ... implies the menu should be running at exactly 30 ... That's false". This is a statement, not a measurement. For MM it agrees with the mixed cadence measured here.
- MiSTer-devel/N64_MiSTer#27 and both comments (thoseposers 2024-07-05, "Initial menu runs at double-speed (60 FPS rather than 30 FPS)"; meauxdal on PAL). No capture or measurement.
- YouTube `57fdDCbAs28`, `UpYHyLo3-aQ`, `aTxWmxP1HZg`, `e6dUTwfkxxU`, `uuH--vVHy4c`, `BedbUxyZIDQ`, `vEd-acS0BEU`. Downloaded with yt-dlp (1080p60 or 720p60 formats 299/298) on 2026-10-05. Titles, uploaders, dates and descriptions were read with `yt-dlp --print`.
- MM decomp (zeldaret/mm, `mm-decomp-60fps` @ `56fa21dd0`): `src/overlays/gamestates/ovl_file_choose/z_file_choose_NES.c` (lines 21-29, 425-458, 522-541, 1371-1450, 1657-1834, 2222-2280, 2299-2408, 2512), `src/code/sched.c` (243-326, 425-445), `src/code/graph.c` (145-240), `src/code/game.c` (33-44), `src/code/z_rcp.c` (`SETUPDL_39/40/42`), `src/code/z_vr_box_draw.c:26`.
- MM bench: `reports/mmbench.md`; `C:\Users\Scott\n64-timing\mmbench\results\final3\run1\{fields,gframes,summary}.tsv`; `results\shots2\filesel\end.ppm`; `tools/n64-timing/README.md` on `origin/feat/mmbench` (unit of `rsp_busy_clocks`).
- Research docs on `origin/research/*`: `1prim-cost`, `rdp-command-timing`, `rdp-memory-traffic`, `rsp-rdp-fifo`, `mm-rdp-stream`.
- n64brew, Video Interface (NTSC VI clock 48.681812 MHz, 3094 × 263 timing gives 59.826 Hz).
