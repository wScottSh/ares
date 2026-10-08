#!/usr/bin/env bash
# Runs the rdpstat ROMs through n64-run and writes per-set results.
#
# usage: run.sh [SET...]
# SET defaults to "systemtest dpc repeater64 1prim unsynced". ROMs come from
# romgen/build.py --suite rdpstat --out $N64_TIMING_HOME/roms.
# Output: $N64_TIMING_HOME/results/rdpstat/<set>/{stdout.txt,stderr.txt,values.tsv,summary.txt}
#         $N64_TIMING_HOME/results/rdpstat/summary.txt
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
. "$romgen/../host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
roms="${RDPSTAT_ROMS:-$N64_TIMING_HOME/roms}"

sets="${*:-systemtest dpc repeater64 1prim unsynced}"

results="$N64_TIMING_HOME/results/rdpstat"
mkdir -p "$results"
: > "$results/summary.txt"

for set in $sets; do
  rom="$roms/rdpstat-$set.z64"
  [ -f "$rom" ] || { echo "missing $rom; run romgen/build.py --suite rdpstat first" >&2; exit 1; }
  out="$results/$set"
  mkdir -p "$out"
  status=0
  "$runner" "$rom" --emulated-seconds 120 --wall-seconds 600 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  {
    echo "== $set exit=$status"
    grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
    grep "^Test '" "$out/stdout.txt" || true
    grep -o '[A-Za-z-]*: Failed [0-9]* of [0-9]* tests.*' "$out/stdout.txt" || echo "no summary line"
    PYTHONPATH="$(dirname "$romgen")" "$PYTHON" -m romgen.report "${rom%.z64}.tests.tsv" "$out/stdout.txt" "$out"
  } | tee "$out/summary.txt" >> "$results/summary.txt"
done
cat "$results/summary.txt"
