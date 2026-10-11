#!/usr/bin/env bash
# Builds kit-noise and kit-noise2 at every layout pad (sets.PADS) and every boot delay 1..LAST at step 1, runs
# each on the fork with ARES_DPLOG, laid out as calibration/run.sh does (OUT/[p<P>/]boot-<K>/<kit>.{txt,dplog,srm}),
# then prints kit.py --noise-sweep OUT: the boot-phase period and the offset set D +- K each noise question's
# source carries (prehw-plan.md U-NOISE-ORDER). LAST defaults to noise.py SWEEP_LAST.
# usage: tools/n64-timing/calibration/noise-sweep.sh OUT [LAST]
# env: N64_RUN (default: this worktree's runner), CALIB_JOBS (default 12).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
out="$1"
run="${N64_RUN:-$(n64_target n64-run)}"
here="$n64_repo/tools/n64-timing"
last="${2:-$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import noise; print(noise.SWEEP_LAST)' "$here/calibration")}"
pads="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); from romgen.suites.calib import sets; print(*sets.PADS)' "$here")"
export N64_CALIB_DELAYS="$(seq -s, 1 "$last")"
for pad in $pads; do
  if [ "$pad" = 0 ]; then dir="$out/roms" flag=(); else dir="$out/roms/p$pad" flag=(--layout-pad "$pad"); fi
  mkdir -p "$dir"
  [ "$(find "$dir" -maxdepth 2 -path '*/boot-*/kit-noise*.z64' | wc -l)" = "$((2 * last))" ] && continue
  "$PYTHON" "$here/romgen/build.py" --suite calib --set kit-noise --set kit-noise2 "${flag[@]}" \
    --jobs "${CALIB_JOBS:-12}" --out "$dir" >/dev/null
done
printf 'until 0x804200E8 w == 0x600DF00D\nstop\n' > "$out/stop.script"
find "$out/roms" -name 'kit-noise*.z64' | sort | while read -r rom; do
  rel="${rom#$out/roms/}"
  [ -s "$out/${rel%.z64}.dplog" ] || echo "$rom $out/${rel%.z64}"
done | xargs -r -P "${CALIB_JOBS:-12}" -n 2 sh -c '
  mkdir -p "$(dirname "$2")"
  ARES_DPLOG="$2.dplog" "'"$run"'" "$1" --controllers 1 --script "'"$out"'/stop.script" --emulated-seconds 0 \
    --wall-seconds 1800 --dump-sram "$2.srm" > "$2.txt" 2> "$2.err" || { rm -f "$2.dplog"; echo "run failed: $1 (see $2.err)" >&2; }
' sh
"$PYTHON" "$here/calibration/kit.py" --noise-sweep "$out"
