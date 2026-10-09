#!/usr/bin/env bash
# Builds the calibration kit and runs every kit ROM on the fork at each boot delay (the model side
# of each hardware comparison, docs/calibration/hardware-run.md).
# usage: tools/n64-timing/calibration/run.sh [OUT_DIR]
# OUT_DIR defaults to $N64_TIMING_HOME/results/calib. Writes OUT_DIR/roms (the builds, boot-1 is the
# console build), OUT_DIR/boot-<K>/<rom>.txt (stdout, the kit log) and .err, and rom-sha256.txt.
# env: N64_RUN (default: this worktree's runner), CALIB_JOBS (default 4), N64_CALIB_DELAYS.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
out="${1:-$N64_TIMING_HOME/results/calib}"
run="${N64_RUN:-$(n64_target n64-run)}"
here="$n64_repo/tools/n64-timing"
mkdir -p "$out"
"$PYTHON" "$here/romgen/build.py" --suite calib --out "$out/roms" >/dev/null
(cd "$out/roms" && find . -name '*.z64' | sort | xargs sha256sum) > "$out/rom-sha256.txt"
printf 'until 0x804200E8 w == 0x600DF00D\nstop\n' > "$out/stop.script"
find "$out/roms" -name '*.z64' | sort | while read -r rom; do
  rel="${rom#$out/roms/}"
  echo "$rom $out/${rel%.z64}"
done | xargs -P "${CALIB_JOBS:-4}" -n 2 sh -c '
  mkdir -p "$(dirname "$2")"
  "'"$run"'" "$1" --script "'"$out"'/stop.script" --wall-seconds 600 > "$2.txt" 2> "$2.err" || echo "run failed: $1 (see $2.err)" >&2
' sh
grep -L '^#kit-end' $(find "$out" -name '*.txt' -path '*boot-*') 2>/dev/null | sed 's/^/no #kit-end line: /' >&2 || true
echo "$out"
