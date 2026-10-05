#!/usr/bin/env bash
# usage: run.sh LABEL CPU(interpreter|recompiler) [ENV=VAL ...]
set -u
out=C:/Users/Scott/n64-timing/results/measure-28
bin=C:/Users/Scott/n64-timing/build/measure-28/n64-run/rundir/n64-run.exe
rom="C:/Users/Scott/PARA/3-Resources/Emulation/ROMs/N64/Legend of Zelda - Majora's Mask.v64"
label=$1; cpu=$2; shift 2
env "$@" M28_TASKLOG=$out/$label.tasks.tsv "$bin" "$rom" --frames ${FRAMES:-600} --cpu $cpu --stats $out/$label.stats.tsv >/dev/null 2>$out/$label.stderr
echo "$label $(tail -1 $out/$label.stats.tsv | cut -f6,7) $(tail -1 $out/$label.stderr)"
