#!/usr/bin/env bash
# Runs every suite, the MM bench, the determinism and step-cap checks, the state round trip and
# the gen check into one directory, the layout behaviors.py --results reads.
#
# usage: standing.sh OUT MM_ROM
# env: N64_TIMING_HOME (ROMs go to $N64_TIMING_HOME/roms, rebuilt from this tree), N64_BUILD_DIR,
#      REPEATER64_ASSETS (rdpstat repeater64 references), PIDMA_DIR (a rasky/n64_pi_dma_test
#      checkout: its prebuilt pi_dma_test.z64, pinned below, and the golden logs in data/)
#      build-systembench-era.sh and build-systembench.sh need docker; without it the systembench checks are pending:no-rom
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/host.sh"
out="$(mkdir -p "$1" && cd "$1" && pwd)"
mm="$2"
commit="$(git -C "$n64_repo" rev-parse --short HEAD)"
[ -n "$(git -C "$n64_repo" status --porcelain --untracked-files=no)" ] && commit="$commit dirty"
echo "$commit" > "$out/run-commit.txt"
export N64_TIMING_HOME N64_BUILD_DIR="$n64_build" N64_RUN="${N64_RUN:-$(n64_target n64-run)}"
roms="$N64_TIMING_HOME/roms"
results="$N64_TIMING_HOME/results"
mkdir -p "$roms"
exits=

for s in nemu64 rdpstat snapper thar0 noise cpu; do
  (cd "$n64_repo" && "$PYTHON" tools/n64-timing/romgen/build.py --suite "$s" --out "$roms") > "$out/romgen-$s.txt" 2>&1
done
rm -rf "$roms/bench" "$results/bench"
(cd "$n64_repo" && "$PYTHON" tools/n64-timing/romgen/build.py --suite bench --out "$roms/bench") > "$out/romgen-bench.txt" 2>&1
rm -rf "$roms/systembench" "$roms/systembench-845635c"
OUT="$roms/systembench" SYSBENCH_STAGE="$N64_TIMING_HOME/systembench-stage" "$here/build-systembench-era.sh" 2023 \
  > "$out/build-systembench.txt" 2>&1 || rm -rf "$roms/systembench"
OUT="$roms/systembench-845635c" SYSBENCH_STAGE="$N64_TIMING_HOME/systembench-845635c-stage" "$here/build-systembench.sh" \
  > "$out/build-systembench-845635c.txt" 2>&1 || rm -rf "$roms/systembench-845635c"
(cd "$roms" && find . -name '*.z64' | sort | xargs sha256sum) > "$out/rom-sha256.txt"

uptime > "$out/load-start.txt"
( "$N64_RUN" "$mm" --frames 600 --stats "$out/mm600.tsv" > /dev/null 2> "$out/mm600.err" ) &
( "$PYTHON" "$here/mmbench/mmbench.py" --exe "$N64_RUN" "$mm" --out "$out/mmbench" > "$out/mmbench.txt" 2>&1 ) &
"$here/run-nemu64.sh" > "$out/nemu64.txt" 2>&1 || exits="$exits nemu64"
"$here/romgen/suites/bench/run.sh" > "$out/bench.txt" 2>&1 || exits="$exits bench"
"$here/romgen/suites/rdpstat/run.sh" > "$out/rdpstat.txt" 2>&1 || exits="$exits rdpstat"
"$here/romgen/suites/snapper/run.sh" > "$out/snapper.txt" 2>&1 || exits="$exits snapper"
"$here/romgen/suites/noise/run.sh" > "$out/noise.txt" 2>&1 || exits="$exits noise"
"$here/run-thar0.sh" > "$out/thar0.txt" 2>&1 || exits="$exits thar0"
"$here/romgen/suites/cpu/run.sh" > "$out/cpu.txt" 2>&1 || exits="$exits cpu"
if [ -d "$roms/systembench" ]; then
  SYSBENCH_ROMS="$roms/systembench" "$here/systembench/run.sh" > "$out/systembench.txt" 2>&1 || exits="$exits systembench"
fi
if [ -d "$roms/systembench-845635c" ]; then
  SYSBENCH_ROMS="$roms/systembench-845635c" SYSBENCH_RESULTS="$results/systembench-845635c" \
    "$here/systembench/run.sh" > "$out/systembench-845635c.txt" 2>&1 || exits="$exits systembench-845635c"
fi
pidma="${PIDMA_DIR:-$N64_TIMING_HOME/scratch/r29/clones/n64_pi_dma_test}"
mkdir -p "$out/pidma"
if echo "1d2c999c42baa57b9c16a21c0bd75b984901ee615ab30482fdec6ed7fcf156cb  $pidma/pi_dma_test.z64" \
    | sha256sum -c - > "$out/pidma/sha256.txt" 2>&1; then
  ARES_PILOG="$out/pidma/pi.log" "$N64_RUN" "$pidma/pi_dma_test.z64" --frames 3000 \
    > "$out/pidma/stdout.txt" 2> "$out/pidma/stderr.txt"
  "$PYTHON" "$here/pidma-replay.py" "$out/pidma/pi.log" "$pidma/data" --stdout "$out/pidma/stdout.txt" \
    --table "$out/pidma/points.tsv" > "$out/pidma/summary.txt" 2>&1
  rm -f "$out/pidma/pi.log"
fi
for suite in nemu64 bench systembench systembench-845635c rdpstat snapper noise thar0 cpu; do
  rm -rf "$out/$suite"
  cp -r "$results/$suite" "$out/$suite"
done
(cd "$n64_build" && ctest > "$out/ctest.txt" 2>&1)
(cd "$n64_repo" && "$PYTHON" tools/n64-timing/behaviors.py --check && "$PYTHON" tools/n64-timing/behaviors.py --self-test \
  && "$PYTHON" tools/n64-timing/lint-literals.py && "$PYTHON" tools/n64-timing/pidma-replay.py --self-test && "$PYTHON" tools/n64-timing/mmbench/filesel_check.py --self-test \
  && "$PYTHON" tools/n64-timing/systembench/report.py --self-test \
  && "$PYTHON" tools/n64-timing/calibration/kit.py --self-test \
  && (cd tools/n64-timing && "$PYTHON" -m romgen.suites.nemu64.phase --self-test)) > "$out/behaviors.txt" 2>&1
"$here/calibration/run.sh" "$out/calib" > "$out/calib.txt" 2>&1 || echo "calibration/run.sh failed (see $out/calib.txt)" >&2
for set in timing cycle cop0hazard; do
  DET_OUT="$out/det-nemu64-$set" "$here/determinism.sh" "$roms/nemu64-$set.z64" > "$out/det-nemu64-$set.txt" 2>&1
  DET_OUT="$out/stepcap-nemu64-$set" "$here/determinism.sh" --step-cap "$roms/nemu64-$set.z64" > "$out/stepcap-nemu64-$set.txt" 2>&1
done
DET_OUT="$out/det-mm" "$here/determinism.sh" "$mm" > "$out/det-mm.txt" 2>&1
DET_OUT="$out/stepcap-mm" "$here/determinism.sh" --step-cap "$mm" > "$out/stepcap-mm.txt" 2>&1
OUT="$out/state-roundtrip" "$here/state-roundtrip.sh" "$mm" > "$out/state-roundtrip.txt" 2>&1 || exits="$exits state-roundtrip"
wait
"$PYTHON" "$here/mmbench/filesel_check.py" "$out/mmbench" > "$out/filesel.txt" 2>&1
uptime > "$out/load-end.txt"
{
  echo "standing: scripts that exited nonzero:${exits:- none}"
  "$PYTHON" "$here/behaviors.py" --failing "$out"
} | tee "$out/failing.txt"
echo "standing: $out"
