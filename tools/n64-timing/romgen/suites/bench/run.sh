#!/usr/bin/env bash
# Runs the bench ROMs through n64-run at every boot delay and joins their measurements with expected.tsv.
#
# usage: run.sh [ROM...]
# ROM defaults to every bench ROM (benches.py ROMS). Build them first (every delay of phases.py):
#   python tools/n64-timing/romgen/build.py --suite bench --out $N64_TIMING_HOME/roms/bench
# env: BENCH_JOBS (runners at once, default 4), N64_BENCH_DELAYS (phases.py)
# Output: $N64_TIMING_HOME/results/bench/boot-<K>/<rom>/{stdout.txt,stderr.txt}
#         $N64_TIMING_HOME/results/bench/{runs.txt,measurements.tsv,phases.tsv,results.tsv,summary.txt}
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
. "$romgen/../host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
roms_dir="${BENCH_ROMS:-$N64_TIMING_HOME/roms/bench}"

roms="${*:-$(cd "$romgen/.." && "$PYTHON" -c 'from romgen.suites.bench.benches import ROMS; print(" ".join(ROMS))')}"
delays="$(cd "$romgen/.." && "$PYTHON" -m romgen.suites.bench.phases)"

results="${BENCH_RESULTS:-$N64_TIMING_HOME/results/bench}"
mkdir -p "$results"
for k in $delays; do
  for rom in $roms; do
    [ -f "$roms_dir/boot-$k/bench-$rom.z64" ] \
      || { echo "missing $roms_dir/boot-$k/bench-$rom.z64; run romgen/build.py --suite bench first" >&2; exit 1; }
  done
done
for k in $delays; do
  for rom in $roms; do echo "$k $rom"; done
done | xargs -P "${BENCH_JOBS:-4}" -L 1 sh -c '
  out="$1/boot-$3/$4"
  mkdir -p "$out"
  status=0
  "$0" "$2/boot-$3/bench-$4.z64" --emulated-seconds 120 --wall-seconds 600 \
    > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  echo "== boot-$3 $4 exit=$status $(grep "^n64-run: stop=" "$out/stderr.txt" || echo "no stop line")"
' "$runner" "$results" "$roms_dir" | sort > "$results/runs.txt"
grep -v ' exit=0 n64-run: stop=emux-exit' "$results/runs.txt" || true
(cd "$romgen/.." && "$PYTHON" -m romgen.suites.bench.report "$roms_dir" "$results" $roms) | tee "$results/summary.txt"
