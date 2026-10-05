#!/usr/bin/env bash
# usage: bench-sct.sh LABEL "ENV=.." EXE ARGS... ; runs the mmbench sct scene script (cold boot to
# South Clock Town, 600-field window) and appends one row with whole-run and window numbers
set -u
label=$1; envs=$2; exe=$3; shift 3
ROM="C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64"
out=${M9_DIR:-$HOME/n64-timing/m9}
env $envs "$exe" "$ROM" --script "${M9_DIR_WIN:-C:/Users/Scott/n64-timing/m9}/sct-script.txt" --frames 3000 --rdp none \
  --stats "${M9_DIR_WIN:-C:/Users/Scott/n64-timing/m9}/stats-$label.tsv" "$@" >/dev/null 2>"$out/err-$label.txt"
line=$(grep '^n64-run: stop' "$out/err-$label.txt")
wall=$(echo "$line" | sed -n 's/.*wall_s=\([0-9.]*\).*/\1/p')
win=$(grep '^m9.window' "$out/err-$label.txt" | sed -n 's/.*thread_cpu_s=\([0-9.]*\).*tsc_s=\([0-9.]*\).*/\2\t\1/p')
mark=$(grep -o 'mark window frame=[0-9]*' "$out/err-$label.txt" | head -1)
printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$envs $*" "$wall" "${win:-NA	NA}" "$mark"
