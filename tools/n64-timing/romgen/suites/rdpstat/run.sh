#!/usr/bin/env bash
# Runs the rdpstat ROMs through n64-run and writes per-set results.
#
# usage: run.sh [--rdp none|vulkan] [SET...]
# SET defaults to "systemtest dpc repeater64". ROMs come from
# romgen/build.py --suite rdpstat --out $N64_TIMING_HOME/roms.
# Output: $N64_TIMING_HOME/results/rdpstat-<rdp>/<set>/{stdout.txt,stderr.txt,values.tsv,summary.txt}
#         $N64_TIMING_HOME/results/rdpstat-<rdp>/summary.txt
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
repo="$(cd "$romgen/../../.." && pwd)"
runner="${N64_RUN:-$N64_TIMING_HOME/build/$(basename "$repo")/n64-run/rundir/n64-run.exe}"
[ -x "$runner" ] || runner="${runner%.exe}"
roms="${RDPSTAT_ROMS:-$N64_TIMING_HOME/roms}"

rdp=none
if [ "${1:-}" = "--rdp" ]; then rdp="$2"; shift 2; fi
sets="${*:-systemtest dpc repeater64}"

results="$N64_TIMING_HOME/results/rdpstat-$rdp"
mkdir -p "$results"
: > "$results/summary.txt"

for set in $sets; do
  rom="$roms/rdpstat-$set.z64"
  [ -f "$rom" ] || { echo "missing $rom; run romgen/build.py --suite rdpstat first" >&2; exit 1; }
  out="$results/$set"
  mkdir -p "$out"
  status=0
  "$runner" "$rom" --rdp "$rdp" --emulated-seconds 120 --wall-seconds 600 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  {
    echo "== $set (rdp=$rdp) exit=$status"
    grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
    grep "^Test '" "$out/stdout.txt" || true
    grep -o '[A-Za-z-]*: Failed [0-9]* of [0-9]* tests.*' "$out/stdout.txt" || echo "no summary line"
    PYTHONPATH="$(dirname "$romgen")" python -m romgen.report "${rom%.z64}.tests.tsv" "$out/stdout.txt" "$out"
  } | tee "$out/summary.txt" >> "$results/summary.txt"
done
cat "$results/summary.txt"
