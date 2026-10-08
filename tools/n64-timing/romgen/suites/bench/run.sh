#!/usr/bin/env bash
# Runs the bench ROMs through n64-run and joins their measurements with expected.tsv.
#
# usage: run.sh [ROM...]
# ROM defaults to every bench ROM (benches.py ROMS). Build them first:
#   python tools/n64-timing/romgen/build.py --suite bench --out $N64_TIMING_HOME/roms/bench
# Output: $N64_TIMING_HOME/results/bench/<rom>/{stdout.txt,stderr.txt}
#         $N64_TIMING_HOME/results/bench/{measurements.tsv,results.tsv,summary.txt}
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
. "$romgen/../host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
roms_dir="${BENCH_ROMS:-$N64_TIMING_HOME/roms/bench}"

roms="${*:-$(cd "$romgen/.." && "$PYTHON" -c 'from romgen.suites.bench.benches import ROMS; print(" ".join(ROMS))')}"

results="${BENCH_RESULTS:-$N64_TIMING_HOME/results/bench}"
mkdir -p "$results"
for rom in $roms; do
  z64="$roms_dir/bench-$rom.z64"
  [ -f "$z64" ] || { echo "missing $z64; run romgen/build.py --suite bench first" >&2; exit 1; }
  out="$results/$rom"
  mkdir -p "$out"
  status=0
  "$runner" "$z64" --emulated-seconds 120 --wall-seconds 600 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  echo "== $rom exit=$status $(grep '^n64-run: stop=' "$out/stderr.txt" || echo 'no stop line')"
done
(cd "$romgen/.." && "$PYTHON" -m romgen.suites.bench.report "$roms_dir" "$results" $roms) | tee "$results/summary.txt"
