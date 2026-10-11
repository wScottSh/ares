#!/usr/bin/env python3
"""Times the MM bench for the Run budget (tools/n64-timing/README.md) on a shared host.

Each side is a runner copied to a fresh file (a freshly linked runner can run 1.7x slower than a
copy of it) plus the mmbench result directory whose scene scripts and stats.tsv that runner is
held to. Scenes run one at a time; the sides alternate, and their order flips every repeat, so
both see the same host load. Every run records the 1-minute load average before and after it
and perf stat's wall, user and sys seconds and instructions:u. user and instructions:u do not
depend on host load; wall does.

  wall.py ROM --out DIR --side NAME=EXE=REFDIR [--side ...] [--reps 5] [--scenes LIST]
  wall.py ROM --out DIR --side NAME=EXE=REFDIR --sweep 1,5 [--reps 5]
  wall.py --summary DIR

--sweep times whole mmbench.py runs (default --jobs) at each listed --phases value instead,
alternating the values; perf stat counts every child runner.
"""

import argparse
import csv
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENES = ("poweron", "title", "filesel", "filesel-named", "filesel-options", "filesel-rotate", "sct", "field")
FIELDS = ("rep", "scene", "side", "load_before", "load_after", "wall_s", "user_s", "sys_s",
          "instructions_u", "cycles_u", "fields", "stop", "output")
PERF = {"wall_s": r"([\d.]+) seconds time elapsed", "user_s": r"([\d.]+) seconds user",
        "sys_s": r"([\d.]+) seconds sys", "instructions_u": r"([\d,]+)\s+instructions:u",
        "cycles_u": r"([\d,]+)\s+cycles:u"}


def load1():
    return Path("/proc/loadavg").read_text().split()[0]


def perf_run(cmd, perf_out, **kw):
    before = load1()
    proc = subprocess.run(["perf", "stat", "-o", str(perf_out), "-e", "task-clock,cycles:u,instructions:u", "--", *cmd], **kw)
    row = {"load_before": before, "load_after": load1()}
    text = perf_out.read_text()
    for key, pat in PERF.items():
        m = re.search(pat, text)
        row[key] = m.group(1).replace(",", "") if m else "?"
    return proc, row


def same(a, b):
    return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()


def run_scene(rom, side, exe, ref, scene, rep, out):
    d = out / "runs" / f"{scene}-{side}-{rep}"
    d.mkdir(parents=True, exist_ok=True)
    stats = d / "stats.tsv"
    args = ["--frames", "600"] if scene == "poweron" else \
        ["--script", str(ref / scene / "script.txt"), "--frames", "3000", "--wall-seconds", "600"]
    with open(d / "stderr.txt", "w") as err:
        _, row = perf_run([exe, rom, *args, "--stats", str(stats)], d / "perf.txt",
                          stdout=subprocess.DEVNULL, stderr=err)
    stop = re.search(r"stop=(\S+) frames=(\d+)", (d / "stderr.txt").read_text())
    expect = out / "runs" / f"poweron-{side}-1" / "stats.tsv" if scene == "poweron" else ref / scene / "stats.tsv"
    return {**row, "rep": rep, "scene": scene, "side": side, "stop": stop.group(1) if stop else "?",
            "fields": stop.group(2) if stop else "?", "output": "same" if same(stats, expect) else "DIFF"}


def run_sweep(rom, side, exe, ref, phases, rep, out):
    d = out / "sweep" / f"phases{phases}-{side}-{rep}"
    with open(out / "sweep" / f"phases{phases}-{side}-{rep}.log", "w") as log:
        proc, row = perf_run([sys.executable, str(HERE / "mmbench.py"), rom, "--exe", exe, "--out", str(d),
                              "--phases", str(phases)], out / "sweep" / f"phases{phases}-{side}-{rep}.perf",
                             stdout=log, stderr=subprocess.STDOUT)
    scenes = [p.name for p in ref.iterdir() if (p / "stats.tsv").exists()]
    ok = proc.returncode == 0 and all(same(d / s / "stats.tsv", ref / s / "stats.tsv") for s in scenes) \
        and len(list(d.glob("phase-*"))) == phases - 1
    return {**row, "rep": rep, "scene": f"mmbench --phases {phases}", "side": side, "stop": proc.returncode,
            "fields": "-", "output": "same" if ok else "DIFF"}


def jobs(sides, sweep, scenes, flip):
    """One repeat's runs as (side, exe, ref, scene or phases). The alternated items (the sides of a
    scene, or the --phases values of a sweep) run in reverse order on every other repeat."""
    if sweep:
        values = [int(x) for x in sweep.split(",")]
        return [(n, e, Path(r), v) for n, e, r in sides for v in (values[::-1] if flip else values)]
    return [(n, e, Path(r), sc) for sc in scenes.split(",") for n, e, r in (sides[::-1] if flip else sides)]


def median_range(vals):
    vals = sorted(float(v) for v in vals)
    return statistics.median(vals), vals[0], vals[-1]


def summary(out):
    rows = list(csv.DictReader(open(out / "runs.tsv"), delimiter="\t"))
    groups = {}
    for r in rows:
        groups.setdefault((r["scene"], r["side"]), []).append(r)
    lines = ["scene\tside\tn\twall_med\twall_min\twall_max\tload_min\tload_max\tuser_med\tuser_min\tuser_max\t"
             "sys_med\tinstr_u_med\tinstr_u_min\tinstr_u_max\toutputs"]
    for (scene, side), rs in groups.items():
        w, u, s, i = (median_range(r[k] for r in rs) for k in ("wall_s", "user_s", "sys_s", "instructions_u"))
        loads = [float(r[k]) for r in rs for k in ("load_before", "load_after")]
        outs = ",".join(sorted({r["output"] for r in rs}))
        lines.append(f"{scene}\t{side}\t{len(rs)}\t{w[0]:.2f}\t{w[1]:.2f}\t{w[2]:.2f}\t{min(loads):.2f}\t{max(loads):.2f}\t"
                     f"{u[0]:.2f}\t{u[1]:.2f}\t{u[2]:.2f}\t{s[0]:.2f}\t{i[0]:.4g}\t{i[1]:.4g}\t{i[2]:.4g}\t{outs}")
    (out / "summary.tsv").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("rom", nargs="?")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--side", action="append", default=[], help="NAME=EXE=REFDIR")
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--scenes", default=",".join(SCENES))
    p.add_argument("--sweep", help="comma-separated --phases values to time whole mmbench runs at")
    p.add_argument("--summary", action="store_true", help="only rewrite summary.tsv from runs.tsv")
    a = p.parse_args()
    if a.summary:
        return summary(a.out)
    if not a.rom or not a.side:
        p.error("ROM and at least one --side are required")
    sides = [s.split("=", 2) for s in a.side]
    for name, exe, ref in sides:
        if not os.access(exe, os.X_OK) or not Path(ref).is_dir():
            p.error(f"side {name}: {exe} is not executable or {ref} is not a directory")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "sweep").mkdir(exist_ok=True)
    runs = a.out / "runs.tsv"
    new = not runs.exists()
    with open(runs, "a", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="\t")
        if new:
            w.writeheader()
        for rep in range(1, a.reps + 1):
            for job in jobs(sides, a.sweep, a.scenes, flip=rep % 2 == 0):
                row = run_sweep(a.rom, *job, rep, a.out) if a.sweep else run_scene(a.rom, *job, rep, a.out)
                w.writerow(row)
                f.flush()
                print("\t".join(str(row[k]) for k in FIELDS), flush=True)
    summary(a.out)


if __name__ == "__main__":
    main()
