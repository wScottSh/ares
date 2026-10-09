#!/usr/bin/env bash
# Build the original rasky/n64-systembench ROM with libdragon in docker.
# Nothing is written inside the repo. Output: $OUT/n64-systembench.{z64,elf}
# and $OUT/provenance.txt.
#
# n64-systembench has no license file, so neither its source nor the ROM is
# committed (preferences line 9). libdragon is public domain (Unlicense,
# LICENSE.md). Building it is allowed by preferences line 28b, for this repo only.
set -euo pipefail

SYSBENCH_COMMIT=845635c68c759c92595edaf5369e76332ebb321d
# 845635c dropped the vendored libdragon ("any trunk version should work"),
# but main.c needs PI_STATUS_DMA_BUSY from dma.h, which only the preview
# branch exports. This is the last preview commit before 845635c.
LIBDRAGON_COMMIT=cc490afe0132f099858882347aa944b97b61b631
# The preview toolchain image (GCC 16.2, 2026-09-14). ghcr keeps no image from
# December 2025, so the compiler is newer than the one 845635c was built with.
IMAGE=ghcr.io/dragonminded/libdragon@sha256:bbc663285582d0d64a6f53416cdc9735be7ca63d58228e2d75e673de7a35b21f

N64_TIMING_HOME=${N64_TIMING_HOME:-$HOME/n64-timing}
SYSBENCH_SRC=${SYSBENCH_SRC:-$N64_TIMING_HOME/scratch/r29/clones/n64-systembench}
LIBDRAGON_SRC=${LIBDRAGON_SRC:-$N64_TIMING_HOME/scratch/r29/clones/libdragon}
OUT=${OUT:-$N64_TIMING_HOME/systembench}

fetch() {
  local url=$1 dir=$2 commit=$3
  [ -d "$dir/.git" ] || git clone -q "$url" "$dir"
  git -C "$dir" cat-file -e "$commit^{commit}" 2>/dev/null || git -C "$dir" fetch -q origin
}
fetch https://github.com/rasky/n64-systembench "$SYSBENCH_SRC" "$SYSBENCH_COMMIT"
fetch https://github.com/DragonMinded/libdragon "$LIBDRAGON_SRC" "$LIBDRAGON_COMMIT"

stage=$OUT/stage
rm -rf "$stage"
mkdir -p "$stage/libdragon"
git -C "$SYSBENCH_SRC" archive "$SYSBENCH_COMMIT" | tar -x -C "$stage"
# main.c includes ../libdragon/include/regsinternal.h, the old vendored path.
git -C "$LIBDRAGON_SRC" archive "$LIBDRAGON_COMMIT" | tar -x -C "$stage/libdragon"

docker run --rm -v "$stage:/work" -w /work "$IMAGE" bash -euc "
  trap 'chown -R $(id -u):$(id -g) /work' EXIT
  make -C libdragon -j\$(nproc) install-mk libdragon tools install tools-install >/work/libdragon-build.log 2>&1
  make -j\$(nproc) >/work/systembench-build.log 2>&1
  mips64-elf-gcc --version | head -n 1 >/work/gcc-version.txt
"

cp "$stage/n64-systembench.z64" "$stage/build/n64-systembench.elf" "$OUT/"
{
  echo "n64-systembench $SYSBENCH_COMMIT"
  echo "libdragon $LIBDRAGON_COMMIT"
  echo "image $IMAGE"
  echo "gcc $(cat "$stage/gcc-version.txt")"
  (cd "$OUT" && sha256sum n64-systembench.z64 n64-systembench.elf)
} >"$OUT/provenance.txt"
cat "$OUT/provenance.txt"
