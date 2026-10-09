#!/usr/bin/env bash
# Runs the original n64-systembench ROM (build-systembench.sh) through n64-run, unpadded and at every boot delay,
# and reports each benchmark against the hardware value compiled into it, under its own pass rule.
#
# usage: run.sh
# env: SYSBENCH_ROMS (default $N64_TIMING_HOME/systembench, build-systembench.sh OUT), SYSBENCH_JOBS (runners at once, default 4)
# Output: $N64_TIMING_HOME/results/systembench/{pristine,boot-<K>}/{stdout.txt,stderr.txt}
#         $N64_TIMING_HOME/results/systembench/{runs.txt,measurements.tsv,results.tsv,summary.txt}
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/../host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
roms="${SYSBENCH_ROMS:-$N64_TIMING_HOME/systembench}"
results="${SYSBENCH_RESULTS:-$N64_TIMING_HOME/results/systembench}"

[ -f "$roms/n64-systembench.z64" ] || { echo "missing $roms/n64-systembench.z64; run build-systembench.sh first" >&2; exit 1; }
rm -rf "$results"
mkdir -p "$results"
{
  echo "pristine $roms/n64-systembench.z64"
  for rom in "$roms"/boot-*/n64-systembench.z64; do
    if [ -f "$rom" ]; then echo "$(basename "$(dirname "$rom")") $rom"; fi
  done
} | xargs -P "${SYSBENCH_JOBS:-4}" -L 1 sh -c '
  out="$1/$2"
  mkdir -p "$out"
  status=0
  "$0" "$3" --frames 2 --wall-seconds 300 > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  echo "== $2 exit=$status $(grep "^n64-run: stop=" "$out/stderr.txt" || echo "no stop line")"
' "$runner" "$results" | sort > "$results/runs.txt"
grep -v ' exit=0 n64-run: stop=frame-limit' "$results/runs.txt" || true
"$PYTHON" "$here/report.py" "$results" | tee "$results/summary.txt"
