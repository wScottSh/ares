#!/usr/bin/env bash
# Builds tools/n64-run (headless N64 runner) natively with MSYS2 clang64.
# Output: $N64_TIMING_HOME/build/<name>/n64-run/rundir/n64-run.exe
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
build="${N64_BUILD_DIR:-$N64_TIMING_HOME/build/$(basename "$repo")}"
config="${N64_BUILD_TYPE:-RelWithDebInfo}"
msys="${MSYS2_ROOT:-/c/msys64}"

export PATH="$msys/clang64/bin:$PATH"
for tool in clang++ cmake ninja; do
  command -v "$tool" >/dev/null || {
    echo "missing $tool; install with: $msys/usr/bin/pacman -S --needed mingw-w64-clang-x86_64-{toolchain,cmake,ninja}" >&2
    exit 1
  }
done

if [ ! -f "$build/CMakeCache.txt" ]; then
  cmake -S "$repo" -B "$build" -G Ninja \
    -DCMAKE_BUILD_TYPE="$config" \
    -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
    -DARES_CORES=n64 \
    -DARES_SKIP_DEPS=ON \
    -DENABLE_CCACHE=OFF
fi
cmake --build "$build" --target n64-run n64-timing-tests n64-timing-dpc-regs
echo "$build/n64-run/rundir/n64-run.exe"
