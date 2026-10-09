#!/usr/bin/env bash
# Builds the calibration kit and runs every kit ROM on the fork: the model side of each hardware
# comparison (docs/calibration/hardware-run.md). The calib suite runs at each boot delay
# (romgen/suites/calib/sets.py DELAYS), the other kit ROMs (kit.py KIT_ROMS) once.
# usage: tools/n64-timing/calibration/run.sh [OUT_DIR]
# OUT_DIR defaults to $N64_TIMING_HOME/results/calib. Writes OUT_DIR/roms/{boot-<K>,single}/*.z64
# (boot-1 and single are the console builds), OUT_DIR/{boot-<K>,single}/<rom>.txt (the kit log)
# and .err, the cartridge SRAM the run left (.srm), and rom-sha256.txt. A standing run keeps it as <run dir>/calib for behaviors.py --results.
# env: N64_RUN (default: this worktree's runner), CALIB_JOBS (default 4), N64_CALIB_DELAYS.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
out="${1:-$N64_TIMING_HOME/results/calib}"
run="${N64_RUN:-$(n64_target n64-run)}"
here="$n64_repo/tools/n64-timing"
mkdir -p "$out/roms/single"
"$PYTHON" "$here/romgen/build.py" --suite calib --out "$out/roms" >/dev/null
"$PYTHON" - "$here" <<'PY' | while read -r suite set; do
import sys
sys.path.insert(0, sys.argv[1] + "/calibration")
import kit
for rom, (suite, set_name, walks) in kit.KIT_ROMS.items():
    if not walks:
        print(suite, set_name)
PY
  "$PYTHON" "$here/romgen/build.py" --suite "$suite" --set "$set" --hw --out "$out/roms/single" >/dev/null
done
(cd "$out/roms" && find . -name '*.z64' | sort | xargs sha256sum) > "$out/rom-sha256.txt"
printf 'until 0x804200E8 w == 0x600DF00D\nstop\n' > "$out/stop.script"
find "$out/roms" -name '*.z64' | sort | while read -r rom; do
  rel="${rom#$out/roms/}"
  echo "$rom $out/${rel%.z64}"
done | xargs -P "${CALIB_JOBS:-4}" -n 2 sh -c '
  mkdir -p "$(dirname "$2")"
  "'"$run"'" "$1" --script "'"$out"'/stop.script" --wall-seconds 1800 --dump-sram "$2.srm" > "$2.txt" 2> "$2.err" || echo "run failed: $1 (see $2.err)" >&2
' sh
"$PYTHON" "$here/calibration/kit.py" --verify-run "$out"
echo "$out"
