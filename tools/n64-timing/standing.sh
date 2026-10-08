#!/usr/bin/env bash
# Runs every suite, the MM bench, the determinism and step-cap checks, the state round trip and
# the gen check into one directory, the layout behaviors.py --results reads.
#
# usage: standing.sh OUT MM_ROM
# env: N64_TIMING_HOME (ROMs go to $N64_TIMING_HOME/roms, rebuilt from this tree), N64_BUILD_DIR,
#      REPEATER64_ASSETS (rdpstat repeater64 references), PIDMA_DIR (a rasky/n64_pi_dma_test
#      checkout: its prebuilt pi_dma_test.z64, pinned below, and the golden logs in data/)
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/host.sh"
out="$(mkdir -p "$1" && cd "$1" && pwd)"
mm="$2"
export N64_TIMING_HOME N64_BUILD_DIR="$n64_build" N64_RUN="${N64_RUN:-$(n64_target n64-run)}"
roms="$N64_TIMING_HOME/roms"
results="$N64_TIMING_HOME/results"
mkdir -p "$roms"

for s in nemu64 rdpstat snapper thar0 noise; do
  (cd "$n64_repo" && "$PYTHON" tools/n64-timing/romgen/build.py --suite "$s" --out "$roms") > "$out/romgen-$s.txt" 2>&1
done
(cd "$n64_repo" && "$PYTHON" tools/n64-timing/romgen/build.py --suite bench --out "$roms/bench") > "$out/romgen-bench.txt" 2>&1
(cd "$roms" && find . -name '*.z64' | sort | xargs sha256sum) > "$out/rom-sha256.txt"

uptime > "$out/load-start.txt"
( "$N64_RUN" "$mm" --frames 600 --stats "$out/mm600.tsv" > /dev/null 2> "$out/mm600.err" ) &
( "$PYTHON" "$here/mmbench/mmbench.py" --exe "$N64_RUN" "$mm" --out "$out/mmbench" > "$out/mmbench.txt" 2>&1 ) &
"$here/run-nemu64.sh" > "$out/nemu64.txt" 2>&1
"$here/romgen/suites/bench/run.sh" > "$out/bench.txt" 2>&1
"$here/romgen/suites/rdpstat/run.sh" > "$out/rdpstat.txt" 2>&1
"$here/romgen/suites/snapper/run.sh" > "$out/snapper.txt" 2>&1
"$here/romgen/suites/noise/run.sh" > "$out/noise.txt" 2>&1
"$here/run-thar0.sh" > "$out/thar0.txt" 2>&1
pidma="${PIDMA_DIR:-$N64_TIMING_HOME/scratch/r29/clones/n64_pi_dma_test}"
mkdir -p "$out/pidma"
if echo "1d2c999c42baa57b9c16a21c0bd75b984901ee615ab30482fdec6ed7fcf156cb  $pidma/pi_dma_test.z64" \
    | sha256sum -c - > "$out/pidma/sha256.txt" 2>&1; then
  ARES_PILOG="$out/pidma/pi.log" "$N64_RUN" "$pidma/pi_dma_test.z64" --frames 3000 \
    > "$out/pidma/stdout.txt" 2> "$out/pidma/stderr.txt"
  "$PYTHON" "$here/pidma-replay.py" "$out/pidma/pi.log" "$pidma/data" --stdout "$out/pidma/stdout.txt" --calibrated \
    > "$out/pidma/summary.txt" 2>&1
  rm -f "$out/pidma/pi.log"
fi
for suite in nemu64 bench rdpstat snapper noise thar0; do
  rm -rf "$out/$suite"
  cp -r "$results/$suite" "$out/$suite"
done
(cd "$n64_build" && ctest > "$out/ctest.txt" 2>&1)
(cd "$n64_repo" && "$PYTHON" tools/n64-timing/behaviors.py --check && "$PYTHON" tools/n64-timing/behaviors.py --self-test \
  && "$PYTHON" tools/n64-timing/lint-literals.py) > "$out/behaviors.txt" 2>&1
for set in timing cycle cop0hazard; do
  DET_OUT="$out/det-nemu64-$set" "$here/determinism.sh" "$roms/nemu64-$set.z64" > "$out/det-nemu64-$set.txt" 2>&1
  DET_OUT="$out/stepcap-nemu64-$set" "$here/determinism.sh" --step-cap "$roms/nemu64-$set.z64" > "$out/stepcap-nemu64-$set.txt" 2>&1
done
DET_OUT="$out/det-mm" "$here/determinism.sh" "$mm" > "$out/det-mm.txt" 2>&1
DET_OUT="$out/stepcap-mm" "$here/determinism.sh" --step-cap "$mm" > "$out/stepcap-mm.txt" 2>&1
OUT="$out/state-roundtrip" "$here/state-roundtrip.sh" "$mm" > "$out/state-roundtrip.txt" 2>&1
wait
"$PYTHON" "$here/mmbench/filesel_check.py" "$out/mmbench" > "$out/filesel.txt" 2>&1
uptime > "$out/load-end.txt"
echo "standing: $out"
