#!/usr/bin/env bash
# Runs a ROM twice on n64-run and fails unless both runs are byte-identical, including the
# per-field trace_hash. Majora's Mask NTSC-U 1.0 runs every mmbench scene; any other ROM runs
# FRAMES VI fields from power-on. On a difference, prints the first differing field and column
# of each differing TSV.
# With --step-cap the second run passes n64-run --step-cap (catch the timeline up before every
# CPU instruction), which proves the CPU's horizon skip changes nothing (checks.tsv: stepcap).
# usage: determinism.sh [--step-cap] ROM [FRAMES]   (FRAMES default 600; ignored for Majora's Mask)
# env:   N64_RUN=<n64-run binary> skips the build; DET_OUT=<dir> sets the output directory.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/host.sh"
mode=determinism
if [ "${1:-}" = "--step-cap" ]; then mode=stepcap; shift; fi
rom="${1:?usage: determinism.sh [--step-cap] ROM [FRAMES]}"
frames="${2:-600}"
out="${DET_OUT:-$N64_TIMING_HOME/$mode/$(basename "$rom" | tr -c 'A-Za-z0-9._\n-' _)}"
exe="${N64_RUN:-$(bash "$here/build.sh" | tail -n 1)}"

rm -rf "$out/run1" "$out/run2"
mkdir -p "$out"
is_mm=$(cd "$here/mmbench" && "$PYTHON" -c "import sys, mmbench; print(int(mmbench.rom_md5(sys.argv[1]) == mmbench.ROM_MD5))" "$rom")
if [ "$is_mm" = 1 ]; then
  check=--check-determinism; [ "$mode" = stepcap ] && check=--check-step-cap
  "$PYTHON" "$here/mmbench/mmbench.py" "$rom" --exe "$exe" --out "$out" $check > "$out/mmbench.log" 2>&1 || tail -n 3 "$out/mmbench.log" >&2
else
  for run in run1 run2; do
    mkdir -p "$out/$run"
    cap=; [ "$mode" = stepcap ] && [ "$run" = run2 ] && cap=--step-cap
    "$exe" "$rom" --frames "$frames" --stats "$out/$run/stats.tsv" $cap > "$out/$run/stdout.txt" 2> "$out/$run/stderr.txt" || true
    grep -v -e '^n64-run: stop=' -e '^n64-run: rdp_engine ' -e '^n64-run: cpu_instructions=' "$out/$run/stderr.txt" > "$out/$run/notices.txt" || true
    rm "$out/$run/stderr.txt"
  done
fi

exec "$PYTHON" - "$out/run1" "$out/run2" "$mode" <<'EOF'
import csv, sys
from pathlib import Path

a, b, label = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
# wall.tsv and rdp.txt hold host time; the stop and rdp_engine stderr lines are dropped above for the same reason.
skip = {"wall.tsv", "rdp.txt"}
files = sorted({p.relative_to(r) for r in (a, b) for p in r.rglob("*") if p.is_file() and p.name not in skip})
if not files:
    sys.exit(f"{label}: FAIL, no output under {a.parent}")

def first_difference(fa, fb):
    ra = list(csv.reader(fa.open(newline=""), delimiter="\t"))
    rb = list(csv.reader(fb.open(newline=""), delimiter="\t"))
    header = ra[0] if ra else []
    for i, (x, y) in enumerate(zip(ra, rb)):
        if x != y:
            cols = [header[j] if j < len(header) else str(j) for j in range(max(len(x), len(y)))
                    if j >= len(x) or j >= len(y) or x[j] != y[j]]
            field = x[0] if x else "?"
            return f"first differing row {i} (frame {field}), columns {','.join(cols)}"
    return f"row counts {len(ra)} vs {len(rb)}"

bad = []
for f in files:
    fa, fb = a / f, b / f
    if not fa.is_file() or not fb.is_file():
        bad.append(f"{f}: missing in one run")
    elif fa.read_bytes() != fb.read_bytes():
        bad.append(f"{f}: " + (first_difference(fa, fb) if f.suffix == ".tsv" else "bytes differ"))

hashed = 0
for f in files:
    if f.name == "stats.tsv":
        with (a / f).open(newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        if not rows or "trace_hash" not in rows[0]:
            bad.append(f"{f}: no trace_hash column")
        hashed += len(rows)

if bad:
    print(f"{label}: FAIL")
    for line in bad:
        print("  " + line)
    sys.exit(1)
print(f"{label}: PASS, {len(files)} files byte-identical, {hashed} fields with trace_hash")
EOF
