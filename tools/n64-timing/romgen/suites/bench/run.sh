#!/usr/bin/env bash
# Runs the bench ROMs through n64-run and joins their measurements with expected.tsv.
#
# usage: run.sh [--cpu interpreter|recompiler] [ROM...]
# ROM defaults to every bench ROM (benches.py ROMS). Build them first:
#   python tools/n64-timing/romgen/build.py --suite bench --out $N64_TIMING_HOME/roms/bench
# Output: $N64_TIMING_HOME/results/bench-<cpu>/<rom>/{stdout.txt,stderr.txt}
#         $N64_TIMING_HOME/results/bench-<cpu>/{measurements.tsv,results.tsv,summary.txt}
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
repo="$(cd "$romgen/../../.." && pwd)"
runner="${N64_RUN:-$N64_TIMING_HOME/build/$(basename "$repo")/n64-run/rundir/n64-run.exe}"
[ -x "$runner" ] || runner="${runner%.exe}"
roms_dir="${BENCH_ROMS:-$N64_TIMING_HOME/roms/bench}"

cpu=interpreter
if [ "${1:-}" = "--cpu" ]; then cpu="$2"; shift 2; fi
roms="${*:-$(cd "$romgen/.." && python -c 'from romgen.suites.bench.benches import ROMS; print(" ".join(ROMS))')}"

results="${BENCH_RESULTS:-$N64_TIMING_HOME/results/bench-$cpu}"
mkdir -p "$results"
for rom in $roms; do
  z64="$roms_dir/bench-$rom.z64"
  [ -f "$z64" ] || { echo "missing $z64; run romgen/build.py --suite bench first" >&2; exit 1; }
  out="$results/$rom"
  mkdir -p "$out"
  status=0
  "$runner" "$z64" --cpu "$cpu" --emulated-seconds 120 --wall-seconds 600 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  echo "== $rom exit=$status $(grep '^n64-run: stop=' "$out/stderr.txt" || echo 'no stop line')"
done
(cd "$romgen/.." && python -m romgen.suites.bench.report "$roms_dir" "$results" $roms) | tee "$results/summary.txt"
