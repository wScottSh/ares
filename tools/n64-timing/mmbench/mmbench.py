#!/usr/bin/env python3
"""Deterministic Majora's Mask (NTSC-U 1.0) frame-timing bench on the headless n64-run.

Each scene is one cold-boot run driven by a generated input script. The script reaches the
scene, marks the first field of a fixed-length window, and stops the run when the window ends.
"""

import argparse
import hashlib
import math
import os
import re
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROM_MD5 = "2a0a8acb61538235bc1094d297fb6556"  # zeldaret/mm baseroms/n64-us/checksum-compressed.md5
WINDOW = 600

# NTSC-U 1.0 addresses from zeldaret/mm 56fa21dd tools/disasm/n64-us/variables.txt and the
# struct offsets in include/ (z64game.h, z64play.h, z64actor.h, regs.h).
GAMESTATE_TABLE = 0x801BD910  # gGameStateOverlayTable, 0x30-byte GameStateOverlay entries
OVERLAY_MAP_SELECT = GAMESTATE_TABLE + 1 * 0x30
OVERLAY_CONSOLE_LOGO = GAMESTATE_TABLE + 2 * 0x30
OVERLAY_TITLE_SETUP = GAMESTATE_TABLE + 4 * 0x30
OVERLAY_FILE_SELECT = GAMESTATE_TABLE + 5 * 0x30
REG_EDITOR = 0x801F3F60  # gRegEditor; dREG(80)/dREG(81) are data[26*96+80/81] at +0x14
SAVE_GAME_MODE = 0x801EF670 + 0x3CA8  # gSaveContext.gameMode; 2 = GAMEMODE_FILE_SELECT
PLAY = "[0x801E3FB0]"  # sEffectContext.play, set by Play_Init
SCENE_ID = PLAY + "+0xA4"
TRANSITION_MODE = PLAY + "+0x18B4A"
GAME_FRAMES = PLAY + "+0x9C"  # GameState.frames, one per Graph_Update
UPDATE_DIVISOR = PLAY + "+0xA2"  # GameState.framerateDivisor
# Graph_ThreadEntry's local GraphicsContext, inside sGraphStack (0x801F87B8, size 0x1800). Its
# address is fixed for the ROM. The route through GameState.gfxCtx is not used because that
# field read 0 for some fields of the title scene.
GFX_CTX = "0x801F9CB8"
GFX_TASKS = GFX_CTX + "+0x2C8"  # gfxCtx->gfxPoolIdx, +1 per gfx task submitted (graph.c)
GFX_TASK = GFX_CTX + "+0x88"  # gfxCtx->task.list, the OSTask of the latest gfx task

STICK = 32767


def overlay_loaded(entry):
    return f"until 0x{entry:08X} w != 0"


def scene_settled(scene_id):
    # Play_Init leaves transitionMode at 0 before the fade-in starts, so wait for the
    # fade-in to begin and then to finish.
    return [
        f"until {SCENE_ID} h == 0x{scene_id:X}",
        f"until {TRANSITION_MODE} b != 0",
        f"until {TRANSITION_MODE} b == 0",
    ]


def via_map_select(index):
    # Map select is in the retail ROM but unreachable. Copying its overlay entry over
    # TitleSetup's makes ConsoleLogo hand off to it; MapSelect_Init starts the cursor at
    # dREG(80) when it is in range.
    return [
        overlay_loaded(OVERLAY_CONSOLE_LOGO),
        f"copy 0x{OVERLAY_MAP_SELECT:08X} 0x{OVERLAY_TITLE_SETUP:08X} 0x30",
        f"poke [0x{REG_EDITOR:08X}]+0x1434 h {index}",
        f"poke [0x{REG_EDITOR:08X}]+0x1436 h {index}",
        overlay_loaded(OVERLAY_TITLE_SETUP),
        "wait 30",
        "input A",
        "wait 10",
        "input",
    ]


def counters(tag):
    return [f"peek {tag}.gfx_tasks {GFX_TASKS} w"]


def play_counters(tag):
    return counters(tag) + [
        f"peek {tag}.game_frames {GAME_FRAMES} w",
        f"peek {tag}.update_divisor {UPDATE_DIVISOR} b",
    ]


def walk(moves):
    steps = []
    for stick, fields in moves:
        steps += [f"input {stick}", f"wait {fields}"]
    return steps


def circle(fields, period, step=5):
    # Turning the stick a full circle every `period` fields keeps Link running loops in the
    # open plaza instead of reaching an exit, a wall, or an NPC that opens a textbox.
    moves = []
    for t in range(0, fields, step):
        angle = 2 * math.pi * t / period
        x, y = round(STICK * math.sin(angle)), round(-STICK * math.cos(angle))
        moves.append((f"x={x} y={y}", min(step, fields - t)))
    return moves


# #23 run-time confirmation, step 1: pointers read at the start of the South Clock Town window.
BUFFER_POINTERS = [
    ("gFramebuffers[0]", "0x801FBB80", 0x807DA800),
    ("gFramebuffers[1]", "0x801FBB84", 0x80000500),
    ("gZBufferPtr", "0x801FBB8C", 0x80383AC0),
    ("gWorkBuffer", "0x801FBB90", 0x803A92C0),
    ("gGfxSPTaskOutputBufferPtr", "0x801FBB94", 0x803CEB10),
    ("gGfxSPTaskOutputBufferEnd", "0x801FBB98", 0x803E6B10),
    ("gZBufferLoRes", "0x801FBBA4", 0x80383AC0),
    ("gWorkBufferLoRes", "0x801FBBA8", 0x803A92C0),
    ("gGfxSPTaskOutputBufferLoRes", "0x801FBBAC", 0x803CEB10),
    ("sKaleidoAreaPtr", "0x801D0BA8", (0x80740000, 0x80780000)),
    ("sZeldaArena.head", "0x801F5100", None),
    ("malloc_arena.head", "0x8009CD20", 0x803824C0),
    ("play.tha.size", PLAY + "+0x74", None),
    ("play.tha.start", PLAY + "+0x78", None),
    ("play.tha.head", PLAY + "+0x7C", None),
    ("play.tha.tail", PLAY + "+0x80", None),
    ("OSTask.type", GFX_TASK, 0x00000001),
    ("OSTask.output_buff", GFX_TASK + "+0x28", 0x803CEB10),
    ("OSTask.output_buff_size", GFX_TASK + "+0x2C", 0x803E6B10),
]


def scene_scripts():
    title_route = scene_settled(0x08)
    return {
        "title": title_route + ["mark window"] + play_counters("start")
        + [f"wait {WINDOW}"] + play_counters("end") + ["stop"],
        # EnMag (z_en_mag.c): a first Start during the title fade-in skips to MAG_STATE_DISPLAY,
        # which ignores input for 20 game frames; a second Start after that opens file select.
        # Later in the title, a cutscene flag fades it out, so the presses come early.
        "filesel": title_route + [f"until {GAME_FRAMES} w >= 10", "input Start", "wait 10", "input",
                                  f"until {GAME_FRAMES} w >= 60", "input Start", "wait 10", "input",
                                  f"until 0x{SAVE_GAME_MODE:08X} w == 2",
                                  overlay_loaded(OVERLAY_FILE_SELECT), "mark window"] + counters("start")
        + [f"wait {WINDOW}"] + counters("end") + ["stop"],
        "sct": via_map_select(92) + scene_settled(0x6F) + ["mark window"]
        + [f"peek {name} {addr} w" for name, addr, _ in BUFFER_POINTERS]
        + play_counters("start")
        + walk([(f"y=-{STICK}", 60)] + circle(WINDOW - 60, period=180))
        + play_counters("end") + [f"peek end.scene {SCENE_ID} h", "stop"],
        "field": via_map_select(2) + scene_settled(0x2D) + ["mark window"] + play_counters("start")
        + walk([(f"y=-{STICK}", 400), (f"x={STICK} y=-{STICK}", 200)])
        + play_counters("end") + [f"peek end.scene {SCENE_ID} h", "stop"],
    }


def rom_md5(path):
    data = Path(path).read_bytes()
    magic = data[:4]
    if magic == b"\x37\x80\x40\x12":  # .v64, byte-swapped halfwords
        swapped = bytearray(len(data))
        swapped[0::2], swapped[1::2] = data[1::2], data[0::2]
        data = bytes(swapped)
    elif magic == b"\x40\x12\x37\x80":  # .n64, little-endian words
        data = b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
    return hashlib.md5(data).hexdigest()


def with_shots(steps, scene_dir):
    # The runner writes a shot during the field after the step, so the end shot needs one
    # extra field before the stop.
    out = []
    for step in steps:
        if step == "stop":
            out += [f"shot {(scene_dir / 'end.ppm').as_posix()}", "wait 1"]
        out.append(step)
        if step == "mark window":
            out.append(f"shot {(scene_dir / 'start.ppm').as_posix()}")
    return out


def run_scene(exe, rom, name, steps, outdir, cpu, shots):
    scene_dir = outdir / name
    scene_dir.mkdir(parents=True, exist_ok=True)
    if shots:
        steps = with_shots(steps, scene_dir)
    script = scene_dir / "script.txt"
    script.write_text("\n".join(steps) + "\n", newline="\n")
    stats = scene_dir / "stats.tsv"
    proc = subprocess.run(
        [exe, rom, "--script", str(script), "--stats", str(stats), "--cpu", cpu,
         "--frames", "3000", "--wall-seconds", "600", "--rdp", "vulkan" if shots else "none"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    lines = [l for l in proc.stderr.splitlines() if l.startswith("n64-run: ")]
    stop = lines[-1] if lines else ""
    wall = float(re.search(r"wall_s=([\d.]+)", stop).group(1)) if "wall_s=" in stop else float("nan")
    events = [l[len("n64-run: "):] for l in lines if not l.startswith("n64-run: stop=")]
    (scene_dir / "events.txt").write_text("\n".join(events) + "\n", newline="\n")
    if "stop=script-stop" not in stop:
        raise SystemExit(f"{name}: run did not reach the end of its script: {stop or proc.stderr[-500:]}")
    return events, wall


def parse_events(events):
    marks, peeks = {}, {}
    for e in events:
        verb, name, frame, *rest = e.split(" ")
        frame = int(frame.split("=")[1])
        if verb == "mark":
            marks[name] = frame
        elif verb == "peek":
            peeks[name] = (frame, rest[0])
        else:
            raise SystemExit(f"script failure: {e}")
    return marks, peeks


def read_stats(path):
    lines = Path(path).read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, l.split("\t"))) for l in lines[1:]]


def analyze(name, rows, start):
    # rows[i] is field i; a field's cost is the counter delta from the previous field.
    window = range(start, start + WINDOW)
    fields = []
    for f in window:
        cur, prev = rows[f], rows[f - 1]
        fields.append({
            "scene": name, "field": f - start, "frame": f, "origin": cur["origin"],
            "cpu_cycles": int(cur["cpu_cycles"]) - int(prev["cpu_cycles"]),
            "rsp_busy_clocks": int(cur["rsp_busy_clocks"]) - int(prev["rsp_busy_clocks"]),
            "dpc_start": cur["dpc_start"], "dpc_end": cur["dpc_end"],
            "cimg": cur["cimg"], "zimg": cur["zimg"],
        })
    # A game frame spans the fields from one VI origin change to the next. Fields before the
    # first change and after the last one belong to frames that straddle the window edges.
    changes = [i for i in range(1, len(fields)) if fields[i]["origin"] != fields[i - 1]["origin"]]
    gframes = []
    for n, (a, b) in enumerate(zip(changes, changes[1:])):
        span = fields[a:b]
        gframes.append({
            "scene": name, "gframe": n, "start_field": a, "fields": b - a,
            "cpu_cycles": sum(x["cpu_cycles"] for x in span),
            "rsp_busy_clocks": sum(x["rsp_busy_clocks"] for x in span),
        })
    return fields, gframes


def write_tsv(path, rows):
    keys = list(rows[0].keys())
    text = "\t".join(keys) + "\n" + "".join("\t".join(str(r[k]) for k in keys) + "\n" for r in rows)
    Path(path).write_text(text, newline="\n")


def summarize(fields, gframes, peeks):
    lengths = [g["fields"] for g in gframes]
    dist = Counter(min(l, 6) for l in lengths)
    mean = sum(lengths) / len(lengths) if lengths else float("nan")
    rsp = [f["rsp_busy_clocks"] for f in fields]
    def delta(key):
        start, end = peeks.get(f"start.{key}"), peeks.get(f"end.{key}")
        return str(int(end[1], 16) - int(start[1], 16)) if start and end else ""
    return {
        "fields": len(fields),
        "gframes": len(gframes),
        "fields_per_gframe_mean": f"{mean:.4f}",
        "dist_1": dist[1], "dist_2": dist[2], "dist_3": dist[3], "dist_4": dist[4],
        "dist_5": dist[5], "dist_6plus": dist[6],
        "gframe_fields_min": min(lengths) if lengths else "",
        "gframe_fields_max": max(lengths) if lengths else "",
        "rsp_busy_clocks_per_field_mean": f"{sum(rsp) / len(rsp):.1f}",
        "gfx_tasks": delta("gfx_tasks"),
        "game_frames": delta("game_frames"),
    }


def confirm_buffers(sct_fields, peeks):
    rows = []
    for name, _, expected in BUFFER_POINTERS:
        found = peeks.get(name, (None, "missing"))[1]
        if expected is None:
            verdict, shown = "recorded", "-"
        elif isinstance(expected, tuple):
            low, high = expected
            verdict = "match" if found.startswith("0x") and low <= int(found, 16) < high else "MISMATCH"
            shown = f"0x{low:08X}..0x{high - 1:08X}"
        else:
            verdict = "match" if found == f"0x{expected:08x}" else "MISMATCH"
            shown = f"0x{expected:08X}"
        rows.append({"item": name, "expected": shown, "found": found, "verdict": verdict})

    def distinct(key, cond=lambda f: True):
        return " ".join(sorted({f[key] for f in sct_fields if cond(f)}))

    rows.append({"item": "SETZIMG (last per field)", "expected": "0x0383AC0",
                 "found": distinct("zimg"), "verdict": "match" if distinct("zimg") == "0383ac0" else "MISMATCH"})
    cimg = distinct("cimg")
    rows.append({"item": "SETCIMG (last per field)", "expected": "0x0000500 0x07DA800",
                 "found": cimg, "verdict": "match" if cimg == "0000500 07da800" else "MISMATCH"})
    starts = distinct("dpc_start")
    rows.append({"item": "DPC_START", "expected": "0x3CEB10",
                 "found": starts, "verdict": "match" if starts == "3ceb10" else "MISMATCH"})
    ends = sorted({int(f["dpc_end"], 16) for f in sct_fields})
    inside = all(0x3CEB10 <= e <= 0x3E6B10 for e in ends)
    rows.append({"item": "DPC_END range", "expected": "0x3CEB10..0x3E6B10",
                 "found": f"0x{ends[0]:06X}..0x{ends[-1]:06X}", "verdict": "match" if inside else "MISMATCH"})
    origins = distinct("origin")
    rows.append({"item": "VI_ORIGIN", "expected": "0x000780 0x7DAA80",
                 "found": origins, "verdict": "match" if origins == "000780 7daa80" else "MISMATCH"})
    # Front buffer is never the RDP target: in each field the last SETCIMG and VI_ORIGIN
    # name different framebuffers (origin = buffer + 0x280, one 640-byte line in).
    clash = sum(1 for f in sct_fields if int(f["origin"], 16) - 0x280 == int(f["cimg"], 16))
    rows.append({"item": "fields with SETCIMG == front buffer", "expected": "0",
                 "found": str(clash), "verdict": "match" if clash == 0 else "MISMATCH"})
    return rows


def bench(args, out):
    scripts = scene_scripts()
    names = args.scenes.split(",")
    out.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.jobs or len(names)) as pool:
        futures = {n: pool.submit(run_scene, args.exe, args.rom, n, scripts[n], out, args.cpu, args.shots)
                   for n in names}
        results = {n: f.result() for n, f in futures.items()}
    total_wall = time.perf_counter() - began

    all_fields, all_gframes, summary, sct = [], [], [], None
    for n in names:
        marks, peeks = parse_events(results[n][0])
        fields, gframes = analyze(n, read_stats(out / n / "stats.tsv"), marks["window"])
        all_fields += fields
        all_gframes += gframes
        summary.append({"scene": n, "window_start_frame": marks["window"], **summarize(fields, gframes, peeks)})
        if n == "sct":
            sct = (fields, peeks)

    write_tsv(out / "fields.tsv", all_fields)
    write_tsv(out / "gframes.tsv", all_gframes)
    write_tsv(out / "summary.tsv", summary)
    if sct:
        write_tsv(out / "buffer-confirmation.tsv", confirm_buffers(*sct))

    walls = {"total": total_wall, **{n: results[n][1] for n in names}}
    (out / "wall.tsv").write_text("run\twall_s\n" + "".join(f"{k}\t{v:.3f}\n" for k, v in walls.items()),
                                  newline="\n")

    cols = ["scene", "window_start_frame", "gframes", "fields_per_gframe_mean", "dist_1", "dist_2",
            "dist_3", "dist_4", "dist_5", "dist_6plus", "rsp_busy_clocks_per_field_mean", "gfx_tasks",
            "game_frames"]
    widths = [max(len(c), *(len(str(s[c])) for s in summary)) for c in cols]
    table = "".join("  ".join(str(v).rjust(w) for v, w in zip(row, widths)).rstrip() + "\n"
                    for row in [cols] + [[s[c] for c in cols] for s in summary])
    (out / "summary.txt").write_text(table, newline="\n")
    print(table, end="")
    print("wall_s " + " ".join(f"{k}={v:.1f}" for k, v in walls.items()))
    print(f"results: {out}")


def identical_trees(a, b):
    def listing(root):
        return {p.relative_to(root) for p in root.rglob("*") if p.is_file() and p.name != "wall.tsv"}
    files = sorted(listing(a) | listing(b))
    differing = [f for f in files
                 if not (a / f).is_file() or not (b / f).is_file() or (a / f).read_bytes() != (b / f).read_bytes()]
    return files, differing


def main():
    home = Path(os.environ.get("N64_TIMING_HOME", Path.home() / "n64-timing"))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("rom")
    p.add_argument("--exe", required=True, help="n64-run binary")
    p.add_argument("--out", type=Path, default=home / "mmbench" / "results" / "latest")
    p.add_argument("--cpu", default="interpreter", choices=["interpreter", "recompiler"])
    p.add_argument("--scenes", default="filesel,sct,field,title")
    p.add_argument("--jobs", type=int, default=0, help="parallel runs (default: one per scene)")
    p.add_argument("--shots", action="store_true",
                   help="render with paraLLEl-RDP and save start.ppm/end.ppm per scene (visual check only)")
    p.add_argument("--check-determinism", action="store_true",
                   help="run the bench twice (OUT/run1, OUT/run2) and compare every output except wall.tsv")
    args = p.parse_args()

    md5 = rom_md5(args.rom)
    if md5 != ROM_MD5:
        raise SystemExit(f"ROM is not Majora's Mask NTSC-U 1.0 (md5 {md5}, want {ROM_MD5})")

    if not args.check_determinism:
        bench(args, args.out)
        return
    for run in ("run1", "run2"):
        bench(args, args.out / run)
    files, differing = identical_trees(args.out / "run1", args.out / "run2")
    if differing:
        raise SystemExit("determinism: FAIL, differing files: " + " ".join(map(str, differing)))
    print(f"determinism: PASS, {len(files)} files byte-identical (wall.tsv excluded)")


if __name__ == "__main__":
    main()
