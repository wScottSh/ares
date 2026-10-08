#!/usr/bin/env python3
"""Writes the MM bench report: per-scene field times, the RDRAM channel per requester, and the
provenance of every timing behavior with its check result.

usage: report.py MMBENCH_DIR [--wall WALL_TSV] [--note TEXT] [--out FILE]

MMBENCH_DIR is one mmbench.py --out directory. WALL_TSV defaults to its wall.tsv; pass the
wall.tsv of a run with --jobs 1 for field times that do not share the host between scenes.
The provenance comes from ares/n64/timing/behaviors.tsv and docs/spec/n64-timing-results.tsv.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def behaviors_module():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("behaviors", ROOT / "tools/n64-timing/behaviors.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_tsv(path):
    lines = [l for l in Path(path).read_text(encoding="utf-8").split("\n") if l]
    return [dict(zip(lines[0].split("\t"), l.split("\t"))) for l in lines[1:]]


def field_times(bench, wall):
    walls = {r["run"]: float(r["wall_s"]) for r in read_tsv(wall)}
    out = ["| Scene | Fields run | Window fields | Game frames | Fields per game frame | Wall s | Host ms per field |",
           "|---|---|---|---|---|---|---|"]
    for s in read_tsv(bench / "summary.tsv"):
        run = len(read_tsv(bench / s["scene"] / "stats.tsv"))
        w = walls.get(s["scene"])
        out.append(f"| {s['scene']} | {run} | {s['fields']} | {s['gframes']} | {s['fields_per_gframe_mean']} | "
                   f"{w:.3f} | {w * 1000 / run:.2f} |" if w is not None else
                   f"| {s['scene']} | {run} | {s['fields']} | {s['gframes']} | {s['fields_per_gframe_mean']} | - | - |")
    return out


def bus_tables(bench):
    rows = read_tsv(bench / "bus.tsv")
    scenes = list(dict.fromkeys(r["scene"] for r in rows))
    requesters = list(dict.fromkeys(r["requester"] for r in rows))
    cell = {(r["scene"], r["requester"]): r for r in rows}
    head = "| Requester | " + " | ".join(scenes) + " |"
    rule = "|---|" + "---|" * len(scenes)

    def table(value):
        return [head, rule] + [f"| {q} | " + " | ".join(value(cell[(s, q)]) for s in scenes) + " |" for q in requesters]

    def per_burst(r, key):
        n = int(r["bursts"])
        return f"{int(r[key]) / n:.2f}" if n else "-"

    return (table(lambda r: r["busy_share"]),
            table(lambda r: f"{(int(r['bytes_read']) + int(r['bytes_written'])) / 2**20:.2f}"),
            table(lambda r: per_burst(r, "wait_rclk")),
            table(lambda r: f"{int(r['row_misses']) / int(r['bursts']):.3f}" if int(r["bursts"]) else "-"))


def provenance(b):
    errors, rows, checks, _ = b.validate(ROOT)
    found = b.load_results(ROOT, rows, checks, errors)
    if errors:
        raise SystemExit("\n".join(errors))
    statuses = sorted(b.statuses(rows, found))
    out = ["| Basis | " + " | ".join(statuses) + " | Rows |", "|---|" + "---|" * (len(statuses) + 1)]
    for basis in b.BASES:
        members = [r for r in rows if r["basis"] == basis]
        if members:
            counts = [sum(1 for r in members if b.row_status(r, found) == s) for s in statuses]
            out.append(f"| {basis} | " + " | ".join(str(c) for c in counts) + f" | {len(members)} |")
    table = ["| Behavior | Value | Basis | Status | Checks |", "|---|---|---|---|---|"]
    for r in rows:
        table.append(f"| `{r['id']}` | {b.cell(r['value'] + ' ' + r['unit'])} | {r['basis']} | {b.row_status(r, found)} | "
                     + b.cell("; ".join(b.result_word(c, found) for c in r["verify"].split())) + " |")
    return out, table, b.results_source(found)


def binary_table(bench, b):
    path = bench / "behaviors.tsv"
    if not path.exists():
        return f"The run has no `behaviors.tsv` (n64-run --behaviors), so the binary's table was not compared with `{b.TABLE}`."
    errors, rows, _, _ = b.validate(ROOT)
    repo = {r["id"]: (r["basis"], r["value"], r["unit"]) for r in rows}
    built = {r["id"]: (r["basis"], r["value"], r["unit"]) for r in read_tsv(path)}
    differ = sorted(k for k in repo.keys() | built.keys() if repo.get(k) != built.get(k))
    if differ:
        return f"The binary that ran differs from `{b.TABLE}` on: " + ", ".join(f"`{k}`" for k in differ) + "."
    return f"The binary that ran was built with this table: its `behaviors.tsv` matches `{b.TABLE}` on id, basis, value and unit for all {len(rows)} rows."


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bench", type=Path)
    p.add_argument("--wall", type=Path)
    p.add_argument("--note", default="", help="where the wall times came from (host, load, build)")
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    b = behaviors_module()
    summary, table, source = provenance(b)
    busy, mib, wait, misses = bus_tables(args.bench)
    out = [
        "# MM bench report",
        "",
        f"Generated by `tools/n64-timing/mmbench/report.py` from the mmbench run `{b.run_label(args.bench)}`"
        f" and the results of `{b.RESULTS}` ({source}). {args.note}".rstrip(),
        "",
        "## Field times",
        "",
        "Each scene runs from power-on through its route to the end of its window. Fields run counts every field of "
        "that run; host ms per field is the scene's wall time over them. The window is the fields the bench measures.",
        "",
        *field_times(args.bench, args.wall or args.bench / "wall.tsv"),
        "",
        "## RDRAM channel per requester over each window",
        "",
        "Share of the window's RCP clocks each requester held the channel (`busy_share` in `bus.tsv`):",
        "",
        *busy,
        "",
        "MiB moved (read plus written):",
        "",
        *mib,
        "",
        "RCP clocks waited per burst, from arrival to grant:",
        "",
        *wait,
        "",
        "Row misses per burst:",
        "",
        *misses,
        "",
        "## Provenance",
        "",
        f"Rows of `{b.TABLE}` by basis and status. Status is the row's result in `{b.SPEC}`: pass, fail, fit only, "
        "model-choice (only guards checked it), not-built (the code does not use its value), or the gates of a row no check "
        "decided. " + binary_table(args.bench, b),
        "",
        *summary,
        "",
        *table,
    ]
    text = "\n".join(out) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
