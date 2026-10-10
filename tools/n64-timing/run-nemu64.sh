#!/usr/bin/env bash
# Runs the nemu64-test ROMs through n64-run and writes per-set results.
#
# usage: run-nemu64.sh [SET...]
# SET defaults to "timing cycle cop0hazard timing-phase". ROMs come from romgen/build.py (or build-nemu64.sh).
# timing-phase runs the averaged tests at every VI phase of romgen/suites/nemu64/phases.py.
# Output: $N64_TIMING_HOME/results/nemu64/<set>/{stdout.txt,stderr.txt,frames.tsv,tests.tsv,failures.txt,summary.txt}
#         plus values.tsv (and categories.tsv for timing) for romgen-built ROMs
#         $N64_TIMING_HOME/results/nemu64/timing-phase/{phase-<K>/{stdout.txt,stderr.txt,values.tsv},runs.txt,measurements.tsv,phase.tsv,summary.txt}
#         $N64_TIMING_HOME/results/nemu64/summary.txt
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"

sets="${*:-timing cycle cop0hazard timing-phase}"

results="$N64_TIMING_HOME/results/nemu64"
mkdir -p "$results"
: > "$results/summary.txt"

phase_walk() {
  local out="$results/timing-phase" k rom status
  rm -rf "$out"
  mkdir -p "$out"
  for k in $(cd "$here" && "$PYTHON" -m romgen.suites.nemu64.phases); do
    rom="$N64_TIMING_HOME/roms/phase-$k/nemu64-timing.z64"
    [ -f "$rom" ] || { echo "missing $rom; run romgen/build.py first" >&2; exit 1; }
    mkdir -p "$out/phase-$k"
    status=0
    "$runner" "$rom" --emulated-seconds 120 --wall-seconds 600 \
      > "$out/phase-$k/stdout.txt" 2> "$out/phase-$k/stderr.txt" || status=$?
    echo "phase-$k exit=$status $(grep '^n64-run: stop=' "$out/phase-$k/stderr.txt" || echo 'no stop line')" >> "$out/runs.txt"
    PYTHONPATH="$here" "$PYTHON" -m romgen.report "${rom%.z64}.tests.tsv" "$out/phase-$k/stdout.txt" "$out/phase-$k" > /dev/null
  done
  {
    echo "== timing-phase"
    grep -v ' exit=0 n64-run: stop=emux-exit' "$out/runs.txt" || true
    (cd "$here" && "$PYTHON" -m romgen.suites.nemu64.phase "$out")
  } > "$out/summary.txt"
  cat "$out/summary.txt" >> "$results/summary.txt"
}

for set in $sets; do
  if [ "$set" = timing-phase ]; then
    phase_walk
    continue
  fi
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
    "$PYTHON" "$here/nemu64-results.py" "$out/stdout.txt" "$out"
    if [ -f "${rom%.z64}.tests.tsv" ]; then
      PYTHONPATH="$here" "$PYTHON" -m romgen.report "${rom%.z64}.tests.tsv" "$out/stdout.txt" "$out"
    fi
  } | tee "$out/summary.txt" >> "$results/summary.txt"
done
cat "$results/summary.txt"
