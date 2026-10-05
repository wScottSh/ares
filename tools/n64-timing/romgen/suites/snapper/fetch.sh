#!/usr/bin/env bash
# Fetches the snapper64 console dumps and decodes them for compare.py.
#
# usage: fetch.sh
# Clones https://github.com/HailToDodongo/snapper64 at e1cd8a61fc43 into
# $N64_TIMING_HOME/corpora/snapper64 without running anything from it, downloads the Git LFS
# objects (assets/*.test.7z, 7094 files), and extracts each archive's single .test file into
# $N64_TIMING_HOME/corpora/snapper64-decoded/. Rerunning skips the work already done.
# Extraction uses 7z if present, else bsdtar (Windows tar.exe and libarchive read 7z).
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
COMMIT=e1cd8a61fc43
EXPECTED=7094
clone="$N64_TIMING_HOME/corpora/snapper64"
decoded="$N64_TIMING_HOME/corpora/snapper64-decoded"

if [ ! -d "$clone/.git" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone -q https://github.com/HailToDodongo/snapper64 "$clone"
fi
git -C "$clone" -c advice.detachedHead=false checkout -q "$COMMIT"
git -C "$clone" lfs pull

if command -v 7z >/dev/null; then
  extract() { 7z e "$1" -o"$decoded" -y -bso0 -bsp0; }
elif [ -x /c/Windows/System32/tar.exe ]; then
  extract() { /c/Windows/System32/tar.exe -xf "$1" -C "$decoded" --strip-components=1; }
else
  extract() { bsdtar -xf "$1" -C "$decoded" --strip-components=1; }
fi

mkdir -p "$decoded"
for archive in "$clone"/assets/*.test.7z; do
  name="$(basename "$archive" .7z)"
  [ -f "$decoded/$name" ] || extract "$archive"
done

count=$(find "$decoded" -maxdepth 1 -name '*.test' | wc -l)
echo "$decoded: $count of $EXPECTED dumps"
[ "$count" -eq "$EXPECTED" ]
