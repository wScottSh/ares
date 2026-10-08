# Sourced by the harness scripts. Names the host-specific pieces in one place: the Python
# interpreter and where build.sh's CMake tree puts each target.
# MSYS2 (cmake/windows/helpers.cmake): <build>/<target>/rundir/<target>.exe
# Linux (cmake/linux/defaults.cmake):  <build>/rundir/bin/<target>
# env: N64_TIMING_HOME (default ~/n64-timing), N64_BUILD_DIR (default $N64_TIMING_HOME/build/<worktree>).

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
n64_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
n64_build="${N64_BUILD_DIR:-$N64_TIMING_HOME/build/$(basename "$n64_repo")}"
PYTHON="$(command -v python || command -v python3)"

if command -v cygpath >/dev/null; then
  n64_windows=1
  n64_target() { echo "$n64_build/$1/rundir/$1.exe"; }
else
  n64_windows=
  n64_target() { echo "$n64_build/rundir/bin/$1"; }
fi
