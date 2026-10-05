#!/usr/bin/env bash
# usage: bench.sh LABEL "ENV=.." EXE ARGS... ; appends one row to results.tsv
set -u
label=$1; envs=$2; exe=$3; shift 3
ROM="C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64"
out=${M9_DIR:-$HOME/n64-timing/m9}
env $envs "$exe" "$ROM" --frames 600 --stats "${M9_DIR_WIN:-C:/Users/Scott/n64-timing/m9}/stats-$label.tsv" "$@" >/dev/null 2>"$out/err-$label.txt"
line=$(grep '^n64-run: stop' "$out/err-$label.txt")
wall=$(echo "$line" | sed -n 's/.*wall_s=\([0-9.]*\).*/\1/p')
emu=$(echo "$line" | sed -n 's/.*emulated_s=\([0-9.]*\).*/\1/p')
cpu=$(grep '^m9.cpu' "$out/err-$label.txt" | sed -n 's/.*thread_cpu_s=\([0-9.]*\).*thread_gcycles=\([0-9.]*\).*/\1\t\2/p')
syncs=$(grep -P '^m9.txn\tsyncs\t' "$out/err-$label.txt" | cut -f3)
h=$(tail -n 1 "$out/stats-$label.tsv" | cut -f5-7)
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$label" "$envs $*" "$wall" "${cpu:-NA	NA}" "$syncs" "$emu" "$h" | tee -a "$out/results.tsv"
