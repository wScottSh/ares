#!/usr/bin/env bash
# Build rasky/n64-systembench as it was when its hardware values were measured:
# a commit with the vendored libdragon, compiled by the GCC that libdragon's
# build-toolchain.sh pinned on that commit's date. build-systembench.sh builds
# the 2025 commit 845635c with a 2026 compiler instead.
#
# usage: build-systembench-era.sh [2023|2022]
#   2023 (default): 50f5066, 2023-01-25, the commit that added the SI and JOY rows and their
#     values (blame of main.c:596-613), and the last one before 4b538eb rewrote TIMEIT_MULTI.
#     Toolchain: libdragon a54ccd736 (2022-09-13), GCC 12.2.0 / binutils 2.39 / newlib
#     4.2.0.20211231, the last toolchain change before 2023-01-25.
#   2022: d12e8ea, 2022-08-10, the last commit of the 2022-08 series. Its RDRAM, RCP and PI values
#     date from de9d9dd and 3c6a0ee (2022-08-08/09); the timed functions are the same source from
#     de9d9dd to 50f5066, and only the code around them grows. Toolchain: libdragon eed8ef3b7
#     (2022-07-13), GCC 12.1.0 / binutils 2.38 / newlib 4.1.0, the versions the vendored
#     libdragon 49e6a7d pins.
# SYSBENCH_COMMIT and TOOLCHAIN_COMMIT override the era's pair, to build a neighbouring commit.
#
# The toolchain image is built once from that libdragon commit's own Dockerfile, with its base
# image pinned by digest, and reused. Output: $OUT/n64-systembench.{z64,elf}, one
# $OUT/boot-K/n64-systembench.{z64,elf} per BOOT_DELAYS entry (the scheme of build-systembench.sh,
# padded after the vendored entrypoint's deadloop), and $OUT/provenance.txt. Nothing is written
# inside the repo. Licenses and permission: see build-systembench.sh.
set -euo pipefail

era=${1:-2023}
case $era in
  2023) commit=50f5066e07174b0e4af9a6f87960a679e183060a toolchain=a54ccd736efc6bbce0a447a51f3b539ef0b9b0a2 ;;
  2022) commit=d12e8ea3c65be62b90f943bacf732ccd5dcc7ff0 toolchain=eed8ef3b708ce87e3ae23087a5bab59716a2deb7 ;;
  *) echo "usage: $0 [2023|2022]" >&2; exit 2 ;;
esac
SYSBENCH_COMMIT=${SYSBENCH_COMMIT:-$commit}
TOOLCHAIN_COMMIT=${TOOLCHAIN_COMMIT:-$toolchain}
BASE_IMAGE=ubuntu@sha256:152dc042452c496007f07ca9127571cb9c29697f42acbfad72324b2bb2e43c98
IMAGE=n64-timing/libdragon-toolchain:${TOOLCHAIN_COMMIT:0:9}

N64_TIMING_HOME=${N64_TIMING_HOME:-$HOME/n64-timing}
SYSBENCH_SRC=${SYSBENCH_SRC:-$N64_TIMING_HOME/scratch/r29/clones/n64-systembench}
LIBDRAGON_SRC=${LIBDRAGON_SRC:-$N64_TIMING_HOME/scratch/r29/clones/libdragon}
OUT=${OUT:-$N64_TIMING_HOME/systembench-era/$era}
BOOT_DELAYS=${BOOT_DELAYS-$(seq -s ' ' 1 63 1954)}

fetch() {
  local url=$1 dir=$2 commit=$3
  [ -d "$dir/.git" ] || git clone -q "$url" "$dir"
  git -C "$dir" cat-file -e "$commit^{commit}" 2>/dev/null || git -C "$dir" fetch -q origin
}
fetch https://github.com/rasky/n64-systembench "$SYSBENCH_SRC" "$SYSBENCH_COMMIT"
fetch https://github.com/DragonMinded/libdragon "$LIBDRAGON_SRC" "$TOOLCHAIN_COMMIT"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  ctx=$(mktemp -d)
  trap 'rm -rf "$ctx"' EXIT
  git -C "$LIBDRAGON_SRC" archive "$TOOLCHAIN_COMMIT" Dockerfile tools/build-toolchain.sh | tar -x -C "$ctx"
  # The syntax line would pull an unpinned frontend image; the base image is pinned by digest.
  sed -i -e '/^# syntax=/d' -e "s|^FROM ubuntu:18.04\$|FROM $BASE_IMAGE|" "$ctx/Dockerfile"
  docker build -q -t "$IMAGE" "$ctx" >/dev/null
fi
image_id=$(docker image inspect --format '{{.Id}}' "$IMAGE")

stage=${SYSBENCH_STAGE:-$OUT-stage}
rm -rf "$stage"
mkdir -p "$stage"
git -C "$SYSBENCH_SRC" archive "$SYSBENCH_COMMIT" | tar -x -C "$stage"
# timeit_average drops only one sample when every sample is equal (min and max are both index 0),
# then divides by n-2: the fork's identical samples read (n-1)/(n-2) high, 9/8 or 49/48. Hardware
# samples jitter, so its readings dropped two (inferred). ">=" picks the last maximum instead; the
# result is the same whenever the samples differ, and the ELF layout is unchanged (measured).
if [ "${ERA_TIE_FIX:-1}" = 1 ]; then
  grep -q 'samples\[i\] > samples\[max\]' "$stage/src/main.c" || { echo "no timeit_average tie to fix in $SYSBENCH_COMMIT" >&2; exit 1; }
  sed -i 's/samples\[i\] > samples\[max\]/samples[i] >= samples[max]/' "$stage/src/main.c"
fi

docker run --rm -v "$stage:/work" -w /work "$image_id" bash -euc "
  trap 'chown -R $(id -u):$(id -g) /work' EXIT
  for goals in install-mk libdragon install tools tools-install; do
    make -C libdragon -j\$(nproc) \$goals >>/work/libdragon-build.log 2>&1
  done
  make -j\$(nproc) >/work/systembench-build.log 2>&1
  mips64-elf-gcc --version | head -n 1 >/work/gcc-version.txt
  mips64-elf-ld --version | head -n 1 >/work/ld-version.txt
  mkdir -p pristine && cp n64-systembench.z64 build/n64-systembench.elf pristine/
  sed -i -e 's/^\tli a0, 0\$/\tlui t3, BOOT_DELAY_HI\n\tori t3, t3, BOOT_DELAY_LO\n1:\tbnez t3, 1b\n\taddiu t3, t3, -1\n&/' \
         -e '/^deadloop:\$/{n;n;s/\$/\n\t.space 2048 - 16/}' libdragon/src/entrypoint.S
  cp libdragon/src/entrypoint.S entrypoint.delay.S
  for k in $BOOT_DELAYS; do
    sed -e \"s/BOOT_DELAY_HI/\$((k >> 16))/;s/BOOT_DELAY_LO/\$((k & 0xffff))/\" entrypoint.delay.S >libdragon/src/entrypoint.S
    make -C libdragon -j\$(nproc) install >>/work/libdragon-build.log 2>&1
    rm -f n64-systembench.z64 build/n64-systembench.elf
    make >>/work/systembench-build.log 2>&1
    mkdir -p boot-\$k && cp n64-systembench.z64 build/n64-systembench.elf boot-\$k/
  done
"

mkdir -p "$OUT"
cp "$stage/pristine/n64-systembench.z64" "$stage/pristine/n64-systembench.elf" "$OUT/"
rm -rf "$OUT"/boot-*
for k in $BOOT_DELAYS; do
  mkdir -p "$OUT/boot-$k" && cp "$stage/boot-$k/n64-systembench.z64" "$stage/boot-$k/n64-systembench.elf" "$OUT/boot-$k/"
done
{
  echo "n64-systembench $SYSBENCH_COMMIT (era $era, vendored libdragon, timeit_average tie fix ${ERA_TIE_FIX:-1})"
  echo "toolchain libdragon $TOOLCHAIN_COMMIT Dockerfile, base $BASE_IMAGE"
  echo "image $IMAGE $image_id"
  echo "gcc $(cat "$stage/gcc-version.txt")"
  echo "ld $(cat "$stage/ld-version.txt")"
  echo "boot delays $BOOT_DELAYS"
  (cd "$OUT" && sha256sum n64-systembench.z64 n64-systembench.elf)
} >"$OUT/provenance.txt"
cat "$OUT/provenance.txt"
