#!/usr/bin/env bash
# Runs the noise ROM through n64-run and checks its rectangle against the LFSRs (README.md).
#
# usage: run.sh
# The ROM comes from romgen/build.py --suite noise --out $NOISE_ROMS (default
# $N64_TIMING_HOME/roms); the checker is n64-timing-noise from the same build as n64-run.
# Output: $N64_TIMING_HOME/results/noise/{stdout.txt,stderr.txt,bits.txt,summary.txt}
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
romgen="$(cd "$here/../.." && pwd)"
. "$romgen/../host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"
checker="${N64_NOISE:-$(dirname "$runner")/n64-timing-noise}"
rom="${NOISE_ROMS:-$N64_TIMING_HOME/roms}/noise-rect-1016.z64"
out="${NOISE_RESULTS:-$N64_TIMING_HOME/results/noise}"
[ -f "$rom" ] || { echo "missing $rom; run romgen/build.py --suite noise first" >&2; exit 1; }
mkdir -p "$out"
status=0
"$runner" "$rom" --emulated-seconds 20 --wall-seconds 600 > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
{
  echo "== rect-1016 exit=$status"
  grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
  if PYTHONPATH="$(dirname "$romgen")" "$PYTHON" -m romgen.suites.noise.decode "$out/stdout.txt" "$out/bits.txt" &&
     "$checker" rect "$out/bits.txt"; then
    echo "noise:rect-1016 pass"
  else
    echo "noise:rect-1016 FAIL"
  fi
} 2>&1 | tee "$out/summary.txt"
