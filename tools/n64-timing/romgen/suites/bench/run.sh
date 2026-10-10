#!/usr/bin/env bash
# Runs the bench ROMs through n64-run at every phase point (layout pad and boot delay) and joins their
# measurements with expected.tsv.
#
# usage: run.sh [ROM...]
# ROM defaults to every bench ROM (benches.py ROMS). Build them first (every point of phases.py):
#   python tools/n64-timing/romgen/build.py --suite bench --out $N64_TIMING_HOME/roms/bench
# env: BENCH_JOBS (runners at once, default 4), N64_BENCH_DELAYS, N64_BENCH_PADS (phases.py)
# Output: $N64_TIMING_HOME/results/bench/pad-<P>/boot-<K>/<rom>/{stdout.txt,stderr.txt}
#         $N64_TIMING_HOME/results/bench/{runs.txt,measurements.tsv,phases.tsv,results.tsv,summary.txt}
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
. "$romgen/../host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
roms_dir="${BENCH_ROMS:-$N64_TIMING_HOME/roms/bench}"

roms="${*:-$(cd "$romgen/.." && "$PYTHON" -c 'from romgen.suites.bench.benches import ROMS; print(" ".join(ROMS))')}"
points="$(cd "$romgen/.." && "$PYTHON" -m romgen.suites.bench.phases)"

results="${BENCH_RESULTS:-$N64_TIMING_HOME/results/bench}"
mkdir -p "$results"
for at in $points; do
  for rom in $roms; do
    [ -f "$roms_dir/$at/bench-$rom.z64" ] \
      || { echo "missing $roms_dir/$at/bench-$rom.z64; run romgen/build.py --suite bench first" >&2; exit 1; }
  done
done
for at in $points; do
  for rom in $roms; do echo "$at $rom"; done
done | xargs -P "${BENCH_JOBS:-4}" -L 1 sh -c '
  out="$1/$3/$4"
  mkdir -p "$out"
  status=0
  "$0" "$2/$3/bench-$4.z64" --emulated-seconds 120 --wall-seconds 600 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  echo "== $3 $4 exit=$status $(grep "^n64-run: stop=" "$out/stderr.txt" || echo "no stop line")"
' "$runner" "$results" "$roms_dir" | sort > "$results/runs.txt"
grep -v ' exit=0 n64-run: stop=emux-exit' "$results/runs.txt" || true
(cd "$romgen/.." && "$PYTHON" -m romgen.suites.bench.report "$roms_dir" "$results" $roms) | tee "$results/summary.txt"
