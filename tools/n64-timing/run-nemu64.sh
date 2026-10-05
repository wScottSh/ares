#!/usr/bin/env bash
# Runs the nemu64-test ROMs through n64-run and writes per-set results.
#
# usage: run-nemu64.sh [SET...]
# SET defaults to "timing cycle cop0hazard". ROMs come from romgen/build.py (or build-nemu64.sh).
# Output: $N64_TIMING_HOME/results/nemu64/<set>/{stdout.txt,stderr.txt,frames.tsv,tests.tsv,failures.txt,summary.txt}
#         plus values.tsv (and categories.tsv for timing) for romgen-built ROMs
#         $N64_TIMING_HOME/results/nemu64/summary.txt
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
runner="${N64_RUN:-$N64_TIMING_HOME/build/$(basename "$repo")/n64-run/rundir/n64-run.exe}"
[ -x "$runner" ] || runner="${runner%.exe}"

sets="${*:-timing cycle cop0hazard}"

results="$N64_TIMING_HOME/results/nemu64"
mkdir -p "$results"
: > "$results/summary.txt"

for set in $sets; do
  rom="$N64_TIMING_HOME/roms/nemu64-$set.z64"
  [ -f "$rom" ] || { echo "missing $rom; run romgen/build.py first" >&2; exit 1; }
  out="$results/$set"
  mkdir -p "$out"
  start=$(date +%s.%N)
  status=0
  "$runner" "$rom" --emulated-seconds 900 --wall-seconds 1800 --stats "$out/frames.tsv" \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  wall=$(awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN { printf "%.1f", e - s }')
  {
    echo "== $set exit=$status wall_s=$wall"
    grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
    python "$here/nemu64-results.py" "$out/stdout.txt" "$out"
    if [ -f "${rom%.z64}.tests.tsv" ]; then
      PYTHONPATH="$here" python -m romgen.report "${rom%.z64}.tests.tsv" "$out/stdout.txt" "$out"
    fi
  } | tee "$out/summary.txt" >> "$results/summary.txt"
done
cat "$results/summary.txt"
