#!/usr/bin/env python3
"""Ingests a console calibration capture into the spec (docs/calibration/hardware-run.md).

usage: ingest.py CAPTURE_DIR [--id NAME] [--model DIR] [--dry-run]
       ingest.py --refresh [--model DIR]

CAPTURE_DIR holds what the console produced, in any mix: ISViewer logs (sc64deployer debug output),
SRAM saves from the flashcart SD card (.srm, .sra, .sav; either byte order) and transcribed screen
text. Every file whose bytes contain a `#kit rom=` header is a kit log. ingest.py

1. parses each log and checks its #kit-end byte count and FNV (an incomplete log is stored, never
   compared),
2. stores every log under docs/calibration/hardware/<NAME>/ as <rom>.<n>.log with a manifest.tsv
   (NAME defaults to console-<date>),
3. recomputes every hw:<question> row of docs/spec/n64-timing-results.tsv against the fork's run of
   the same kit ROMs (--model, a calibration/run.sh output; without it run.sh runs into
   $N64_TIMING_HOME/results/calib),
4. regenerates the spec (behaviors.py) and prints every behavior whose status changed.

--dry-run does all of it in a scratch copy of the tree and prints the changes; the repository is
not touched. --refresh skips steps 1-2.
"""
import argparse
import datetime
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RESULTS = "docs/spec/n64-timing-results.tsv"
sys.path.insert(0, str(REPO / "tools/n64-timing"))
COPY = ["ares/n64", "tools/n64-timing", "docs/spec", "docs/calibration"]


def load(root, rel, name):
    spec = importlib.util.spec_from_file_location(name, Path(root) / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statuses(root):
    b = load(root, "tools/n64-timing/behaviors.py", "behaviors_ingest")
    errors, rows, checks, _ = b.validate(str(root))
    found = b.load_results(str(root), rows, checks, errors)
    return {r["id"]: b.row_status(r, found) for r in rows}, {c: v[0] for c, v in found.items() if c.startswith("hw:")}


def store(root, capture, name):
    kit = load(root, "tools/n64-timing/calibration/kit.py", "kit_ingest")
    files = sorted(p for p in Path(capture).rglob("*") if p.is_file())
    logs = kit.read_logs(files)
    if not logs:
        raise SystemExit(f"{capture}: no file holds a `#kit rom=` header; see hardware-run.md, Capture")
    out = Path(root) / kit.HARDWARE / name
    out.mkdir(parents=True, exist_ok=True)
    manifest = ["log\tsource\tsha256\tcomplete\tbytes\tkit_sha\tri_refresh"]
    for rom, entries in sorted(logs.items()):
        known = rom in kit.KIT_ROMS
        for n, (path, log) in enumerate(entries, 1):
            text = log.text + (f"#kit-end rom={rom} bytes={log.footer.get('bytes')} fnv={log.footer.get('fnv')}\n"
                               if log.footer else "")
            dest = out / f"{rom}.{n}.log"
            dest.write_text(text, encoding="ascii", errors="replace", newline="\n")
            manifest.append("\t".join([dest.name, path.name, hashlib.sha256(path.read_bytes()).hexdigest(),
                                       "yes" if log.complete else "no", str(len(log.text)),
                                       log.header.get("sha", "-"), log.header.get("ri_refresh", "-")]))
            note = "" if log.complete else "  INCOMPLETE: footer missing or FNV mismatch; stored, not compared"
            print(f"ingest: {path.name}: {rom} ({'kit ROM' if known else 'not a kit ROM'}), {len(log.records)} "
                  f"records{note}")
    (out / "manifest.tsv").write_text("\n".join(manifest) + "\n", encoding="utf-8", newline="\n")
    return out


def refresh(root, model):
    kit = load(root, "tools/n64-timing/calibration/kit.py", "kit_refresh")
    path = Path(root) / RESULTS
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    kept = [l for l in lines if not l.startswith("hw:")]
    rows = []
    for q in kit.questions(root):
        res, detail = kit.result_from(root, model, q["id"])
        if res == "missing":
            raise SystemExit(f"hw:{q['id']}: {detail}")
        rows.append(f"hw:{q['id']}\t{res}\t{detail}")
    body = sorted(kept[2:] + rows, key=lambda l: l.split("\t")[0])
    path.write_text("\n".join(kept[:2] + body) + "\n", encoding="utf-8", newline="\n")


def model_dir(args):
    if args.model:
        return Path(args.model)
    out = Path(os.environ.get("N64_TIMING_HOME", Path.home() / "n64-timing")) / "results" / "calib"
    subprocess.run([str(HERE / "run.sh"), str(out)], check=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", nargs="?")
    ap.add_argument("--id", default=f"console-{datetime.date.today().isoformat()}")
    ap.add_argument("--model", help="a calibration/run.sh output directory")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if not args.capture and not args.refresh:
        ap.error("name a capture directory, or --refresh")
    model = model_dir(args)
    root = REPO
    scratch = None
    if args.dry_run:
        scratch = Path(tempfile.mkdtemp(prefix="ingest-dry-run-"))
        for rel in COPY:
            if (REPO / rel).exists():
                shutil.copytree(REPO / rel, scratch / rel, ignore=shutil.ignore_patterns("__pycache__"))
        root = scratch
    try:
        before, hw_before = statuses(root)
        if args.capture:
            print(f"ingest: stored in {store(root, args.capture, args.id).relative_to(root)}")
        refresh(root, model)
        subprocess.run([sys.executable, str(Path(root) / "tools/n64-timing/behaviors.py"), "--root", str(root)],
                       check=True, stdout=subprocess.DEVNULL)
        after, hw_after = statuses(root)
        flips = [(rid, before[rid], after[rid]) for rid in before if before[rid] != after[rid]]
        hw = [(c, hw_before.get(c, "-"), hw_after[c]) for c in sorted(hw_after) if hw_before.get(c) != hw_after[c]]
        for c, b, a in hw:
            print(f"ingest: {c}: {b} -> {a}")
        for rid, b, a in flips:
            print(f"ingest: behavior {rid}: {b} -> {a}")
        print(f"ingest: {len(hw)} hardware checks and {len(flips)} behaviors changed"
              + (" (dry run; the repository is unchanged)" if scratch else
                 "; commit docs/calibration/hardware, docs/spec and docs/calibration/inventory.md"))
    finally:
        if scratch:
            shutil.rmtree(scratch)


if __name__ == "__main__":
    main()
