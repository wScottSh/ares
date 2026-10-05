#!/usr/bin/env bash
# Builds n64-run and runs the Majora's Mask bench.
# usage: mmbench.sh ROM [mmbench.py options], or set MM_ROM and omit ROM.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then rom="$1"; shift; else rom="${MM_ROM:?pass the ROM path or set MM_ROM}"; fi
exe="$(bash "$here/../build.sh" | tail -n 1)"
exec python "$here/mmbench.py" "$rom" --exe "$exe" "$@"
