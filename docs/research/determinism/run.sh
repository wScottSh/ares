#!/usr/bin/env bash
# run.sh NAME [n64-run options...]: MM run with state hashes -> NAME.tsv, NAME.err
set -u
B=${N64_RUN:-C:/Users/Scott/n64-timing/build/measure-27/n64-run/rundir/n64-run.exe}
R=${MM_ROM:-"C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64"}
name=$1; shift
"$B" "$R" --state-hash --stats "$name.tsv" "$@" > "$name.out" 2> "$name.err"
echo "$name rc=$? $(grep -E '^n64-run:' "$name.err")"
grep '^probe:' "$name.err"
