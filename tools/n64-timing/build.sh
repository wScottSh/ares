#!/usr/bin/env bash
# Builds tools/n64-run (headless N64 runner) natively: MSYS2 clang64 on Windows, the host
# compiler on Linux (clang if installed, else gcc). Prints the runner path (host.sh n64_target).
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/host.sh"
config="${N64_BUILD_TYPE:-RelWithDebInfo}"

if [ -n "$n64_windows" ]; then
  msys="${MSYS2_ROOT:-/c/msys64}"
  export PATH="$msys/clang64/bin:$PATH"
  cc=clang cxx=clang++
  install="$msys/usr/bin/pacman -S --needed mingw-w64-clang-x86_64-{toolchain,cmake,ninja}"
else
  if command -v clang++ >/dev/null; then cc=clang cxx=clang++; else cc=gcc cxx=g++; fi
  install="the system package manager (apt install g++ cmake ninja-build)"
fi
for tool in "$cxx" cmake ninja; do
  command -v "$tool" >/dev/null || { echo "missing $tool; install with: $install" >&2; exit 1; }
done

if [ ! -f "$n64_build/CMakeCache.txt" ]; then
  cmake -S "$n64_repo" -B "$n64_build" -G Ninja \
    -DCMAKE_BUILD_TYPE="$config" \
    -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
    -DARES_CORES=n64 \
    -DARES_SKIP_DEPS=ON \
    -DENABLE_CCACHE=OFF
fi
cmake --build "$n64_build" --target n64-run n64-timing-tests n64-timing-dpc-regs n64-timing-noise
n64_target n64-run
