#!/usr/bin/env bash
# Builds the Majora's Mask BENCH ROM (ext:mm-bench, kit.py EXT_ROMS) from the commit of
# wScottSh/mm-decomp-60fps that mm_bench.py pins, and writes one ROM per bench scene with its
# BenchConfig patched (mm_bench.py SCENES). The console runs these files; calibration/run.sh runs
# them on the fork as the model side.
# usage: tools/n64-timing/calibration/build-mm-bench.sh [OUT_DIR]
# OUT_DIR defaults to $N64_TIMING_HOME/roms/mm-bench. Writes OUT_DIR/mm-bench-<scene>.z64 and
# OUT_DIR/rom-sha256.txt, and fails unless every ROM's sha256 is the one mm_bench.py pins.
# env: MM_DECOMP (default ~/repos/mm-decomp-60fps, a clone with the pinned commit),
#      MM_BASEROM (default $MM_DECOMP/baseroms/n64-us/baserom.z64, the retail NTSC-U 1.0 ROM),
#      MM_BENCH_SRC (default $N64_TIMING_HOME/mm-bench/decomp-<commit>, the build worktree), MM_JOBS (default 16).
# The build runs in a detached git worktree of MM_DECOMP; the checkout's own working tree is never
# touched. The ROMs hold Nintendo data, so they stay outside this repository.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
here="$n64_repo/tools/n64-timing/calibration"
out="${1:-$N64_TIMING_HOME/roms/mm-bench}"
decomp="${MM_DECOMP:-$HOME/repos/mm-decomp-60fps}"
baserom="${MM_BASEROM:-$decomp/baseroms/n64-us/baserom.z64}"
commit="$("$PYTHON" "$here/mm_bench.py" --commit)"
src="${MM_BENCH_SRC:-$N64_TIMING_HOME/mm-bench/decomp-${commit:0:9}}"
if [ ! -e "$src/.git" ]; then
  mkdir -p "$(dirname "$src")"
  git -C "$decomp" worktree add --detach "$src" "$commit"
fi
[ "$(git -C "$src" rev-parse HEAD)" = "$commit" ] || { echo "$src is not at $commit" >&2; exit 1; }
[ -z "$(git -C "$src" status --porcelain --untracked-files=no)" ] || { echo "$src has tracked changes" >&2; exit 1; }
cmp -s "$baserom" "$src/baseroms/n64-us/baserom.z64" || cp "$baserom" "$src/baseroms/n64-us/baserom.z64"
jobs="${MM_JOBS:-16}"
make -C "$src" venv >/dev/null
[ -d "$src/extracted/n64-us/baserom" ] || make -C "$src" setup -j"$jobs"
[ -d "$src/extracted/n64-us/assets" ] || make -C "$src" assets -j"$jobs"
[ -d "$src/extracted/n64-us/asm" ] || make -C "$src" disasm -j"$jobs"
make -C "$src" -j"$jobs" BENCH=1
mkdir -p "$out"
"$PYTHON" "$here/mm_bench.py" --patch "$src/build/n64-us-bench/mm-n64-us.z64" "$out"
echo "$out"
