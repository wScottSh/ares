#!/usr/bin/env bash
# Runs the Thar0 RDP timing ROM through n64-run and compares it with the hardware results.
#
# usage: run-thar0.sh
# ROM from: python tools/n64-timing/romgen/build.py --suite thar0 --out $N64_TIMING_HOME/roms
# Output: $N64_TIMING_HOME/results/thar0/{stdout.txt,stderr.txt,compare.tsv,summary.txt}
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/host.sh"
runner="${N64_RUN:-$(n64_target n64-run)}"

rom="$N64_TIMING_HOME/roms/thar0-rdp.z64"
[ -f "$rom" ] || { echo "missing $rom; run romgen/build.py --suite thar0 first" >&2; exit 1; }
out="$N64_TIMING_HOME/results/thar0"
mkdir -p "$out"
status=0
"$runner" "$rom" --emulated-seconds 3600 --wall-seconds 3600 \
  > "$out/stdout.txt" 2> "$out/stderr.txt" || status=$?
{
  echo "== thar0 exit=$status"
  grep '^n64-run: stop=' "$out/stderr.txt" || echo "n64-run: no stop line"
  PYTHONPATH="$here" "$PYTHON" -m romgen.suites.thar0.compare "$out/stdout.txt" --out "$out/compare.tsv"
} | tee "$out/summary.txt"
