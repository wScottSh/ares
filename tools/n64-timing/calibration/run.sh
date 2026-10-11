#!/usr/bin/env bash
# Builds the calibration kit and runs every kit ROM on the fork: the model side of each hardware
# comparison (docs/calibration/hardware-run.md). Every kit ROM is built at each layout pad
# (romgen/suites/calib/sets.py PADS, build.py --layout-pad); the calib suite runs at each boot delay
# (sets.py DELAYS), the other kit ROMs (kit.py KIT_ROMS) once per pad. kit-pif runs until the PIF halts it.
# usage: tools/n64-timing/calibration/run.sh [OUT_DIR]
# OUT_DIR defaults to $N64_TIMING_HOME/results/calib. Writes OUT_DIR/roms/{boot-<K>,single}/*.z64
# (boot-1 and single are the console builds), OUT_DIR/{boot-<K>,single}/<rom>.txt (the kit log),
# the same under OUT_DIR/roms/p<P>/ and OUT_DIR/p<P>/ for each layout pad P > 0,
# OUT_DIR/pads-4/[p<P>/]boot-<K>/kit-dma.txt (kit-dma with four controllers, for a four-pad capture),
# OUT_DIR/ext/thar0.txt (the romgen Thar0 port, the fork side of ext:thar0),
# OUT_DIR/ext/systembench.txt (the unpadded hardware-era n64-systembench ROM from $SYSBENCH_ROMS, default
# $N64_TIMING_HOME/roms/systembench where standing.sh builds it; the fork side of ext:systembench),
# OUT_DIR/ext/mm-bench/<scene>.txt (each Majora's Mask BENCH scene ROM from $MM_BENCH_ROMS, default
# $N64_TIMING_HOME/roms/mm-bench where build-mm-bench.sh writes them; the fork side of ext:mm-bench)
# and .err, the cartridge SRAM the run left (.srm), and rom-sha256.txt. A standing run keeps it as <run dir>/calib for behaviors.py --results.
# env: N64_RUN (default: this worktree's runner), CALIB_JOBS (default 4), N64_CALIB_DELAYS, N64_CALIB_PADS,
# SYSBENCH_ROMS, MM_BENCH_ROMS.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
out="${1:-$N64_TIMING_HOME/results/calib}"
run="${N64_RUN:-$(n64_target n64-run)}"
here="$n64_repo/tools/n64-timing"
pads="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); from romgen.suites.calib import sets; print(*sets.PADS)' "$here")"
singles="$("$PYTHON" - "$here" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/calibration")
import kit
print(" ".join(f"{suite}:{set_name}" for suite, set_name, walks in kit.KIT_ROMS.values() if not walks))
PY
)"
for pad in $pads; do
  if [ "$pad" = 0 ]; then dir="$out/roms" flag=(); else dir="$out/roms/p$pad" flag=(--layout-pad "$pad"); fi
  mkdir -p "$dir/single"
  "$PYTHON" "$here/romgen/build.py" --suite calib "${flag[@]}" --out "$dir" >/dev/null
  for single in $singles; do
    "$PYTHON" "$here/romgen/build.py" --suite "${single%%:*}" --set "${single#*:}" --hw "${flag[@]}" --out "$dir/single" >/dev/null
  done
done
mkdir -p "$out/ext"
"$PYTHON" "$here/romgen/build.py" --suite thar0 --out "$out/ext" >/dev/null
(cd "$out/roms" && find . -name '*.z64' | sort | xargs sha256sum; cd "$out/ext" && sha256sum thar0-rdp.z64) > "$out/rom-sha256.txt"
sysbench="${SYSBENCH_ROMS:-$N64_TIMING_HOME/roms/systembench}/n64-systembench.z64"
if [ -f "$sysbench" ]; then
  sha256sum "$sysbench" >> "$out/rom-sha256.txt"
  "$run" "$sysbench" --frames 2 --wall-seconds 300 > "$out/ext/systembench.txt" 2> "$out/ext/systembench.err" \
    || echo "systembench run failed (see $out/ext/systembench.err)" >&2
else
  echo "no $sysbench (build-systembench-era.sh): hw:systembench stays missing" >&2
fi
"$run" "$out/ext/thar0-rdp.z64" --emulated-seconds 3600 --wall-seconds 3600 > "$out/ext/thar0.txt" 2> "$out/ext/thar0.err" &
thar0_pid=$!
mmroms="${MM_BENCH_ROMS:-$N64_TIMING_HOME/roms/mm-bench}"
mm_pids=()
if compgen -G "$mmroms/mm-bench-*.z64" >/dev/null; then
  mkdir -p "$out/ext/mm-bench"
  (cd "$mmroms" && sha256sum mm-bench-*.z64) >> "$out/rom-sha256.txt"
  for rom in "$mmroms"/mm-bench-*.z64; do
    scene="$(basename "$rom" .z64)"
    "$run" "$rom" --wall-seconds 1800 > "$out/ext/mm-bench/${scene#mm-bench-}.txt" 2> "$out/ext/mm-bench/${scene#mm-bench-}.err" &
    mm_pids+=($!)
  done
else
  echo "no $mmroms/mm-bench-*.z64 (calibration/build-mm-bench.sh): hw:mm-bench stays missing" >&2
fi
printf 'until 0x804200E8 w == 0x600DF00D\nstop\n' > "$out/stop.script"
#kit-pif never writes the done word: the PIF halts it. It stops at one second past its last sample, so a
#build that is not halted still ends its log, and kit.py --verify-run reports it.
pif_seconds="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); from romgen.suites.pif import sets; print(sets.SAMPLES * sets.STEP_TICKS // 46875000 + 1)' "$here")"
find "$out/roms" -name '*.z64' | sort | while read -r rom; do
  rel="${rom#$out/roms/}"
  case "$rel" in */kit-pif.z64) limit="$pif_seconds" ;; *) limit=0 ;; esac
  echo "$rom $out/${rel%.z64} 1 $limit"
  case "$rel" in boot-*/kit-dma.z64 | p*/boot-*/kit-dma.z64) echo "$rom $out/pads-4/${rel%.z64} 4 0" ;; esac
done | xargs -P "${CALIB_JOBS:-4}" -n 4 sh -c '
  mkdir -p "$(dirname "$2")"
  "'"$run"'" "$1" --controllers "$3" --script "'"$out"'/stop.script" --emulated-seconds "$4" --wall-seconds 1800 --dump-sram "$2.srm" > "$2.txt" 2> "$2.err"
  status=$?
  [ "$status" = 0 ] || { [ "$status" = 2 ] && [ "$4" != 0 ]; } || echo "run failed: $1 (see $2.err)" >&2
' sh
wait "$thar0_pid" || echo "thar0 port run failed (see $out/ext/thar0.err)" >&2
for pid in "${mm_pids[@]}"; do
  wait "$pid" || echo "an mm-bench run failed (see $out/ext/mm-bench/*.err)" >&2
done
"$PYTHON" "$here/calibration/kit.py" --verify-run "$out"
echo "$out"
