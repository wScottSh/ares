#!/usr/bin/env bash
# Runs the snapper ROMs through n64-run and compares them with the snapper64 console dumps.
#
# usage: run.sh [SET...]
# SET defaults to "span-tri test-mode-rw fill-tri-sweep rect-nosync". ROMs come from
# romgen/build.py --suite snapper --out $SNAPPER_ROMS (default $N64_TIMING_HOME/roms); the dumps
# from fetch.sh. Without the dumps, the comparison prints pending:snapper-lfs.
# Output: $N64_TIMING_HOME/results/snapper/<set>/{stdout.txt,stderr.txt,records.tsv,compare.txt}
#         $N64_TIMING_HOME/results/snapper/summary.txt
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
repo="$(cd "$romgen/../../.." && pwd)"
runner="${N64_RUN:-$N64_TIMING_HOME/build/$(basename "$repo")/n64-run/rundir/n64-run.exe}"
[ -x "$runner" ] || runner="${runner%.exe}"
roms="${SNAPPER_ROMS:-$N64_TIMING_HOME/roms}"

sets="${*:-span-tri test-mode-rw fill-tri-sweep rect-nosync}"

results="${SNAPPER_RESULTS:-$N64_TIMING_HOME/results/snapper}"
mkdir -p "$results"
: > "$results/summary.txt"

for set in $sets; do
  rom="$roms/snapper-$set.z64"
  [ -f "$rom" ] || { echo "missing $rom; run romgen/build.py --suite snapper first" >&2; exit 1; }
  out="$results/$set"
  mkdir -p "$out"
  status=0
  "$runner" "$rom" --emulated-seconds 120 --wall-seconds 1800 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  {
    echo "== $set exit=$status"
    grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
    PYTHONPATH="$(dirname "$romgen")" python -m romgen.suites.snapper.compare \
      "$set" "$out/stdout.txt" "$out" 2>&1 || true
  } | tee -a "$results/summary.txt"
done
