#!/usr/bin/env bash
# Runs the cpu suite's ROMs through n64-run. Each ROM checks itself and prints
# "CPU: Failed X of Y tests"; the exit status is 1 when any test fails.
#
# usage: run.sh [SET...]   (SET defaults to every cpu-*.z64 in $N64_TIMING_HOME/roms)
# ROMs come from romgen/build.py --suite cpu --out $N64_TIMING_HOME/roms.
# Output: $N64_TIMING_HOME/results/cpu/<set>/{stdout.txt,stderr.txt,tests.tsv,failures.txt,summary.txt}
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tools="$(cd "$here/../../.." && pwd)"
. "$tools/host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
roms="$N64_TIMING_HOME/roms"
results="$N64_TIMING_HOME/results/cpu"
sets="${*:-$(cd "$roms" && ls cpu-*.z64 2>/dev/null | sed 's/^cpu-//; s/\.z64$//')}"
[ -n "$sets" ] || { echo "no cpu-*.z64 in $roms; run romgen/build.py --suite cpu first" >&2; exit 1; }
mkdir -p "$results"
: > "$results/summary.txt"
failed=0
for set in $sets; do
  rom="$roms/cpu-$set.z64"
  out="$results/$set"
  mkdir -p "$out"
  status=0
  "$runner" "$rom" --emulated-seconds 20 --wall-seconds 600 > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
  {
    echo "== $set exit=$status"
    grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
    "$PYTHON" "$tools/nemu64-results.py" "$out/stdout.txt" "$out"
  } | tee "$out/summary.txt" >> "$results/summary.txt"
  grep -q "CPU: Failed 0 of " "$out/summary.txt" || failed=1
done
cat "$results/summary.txt"
exit $failed
