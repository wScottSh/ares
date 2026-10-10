#!/usr/bin/env bash
# Reproduces every capture measurement in ../sct-cadence.md.
# Needs yt-dlp, ffmpeg, Python 3 with opencv-python and numpy.
# usage: run.sh WORKDIR
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
fs="$here/../mm-filesel-slowdown"
work="${1:?usage: run.sh WORKDIR}"
mkdir -p "$work"; cd "$work"
py() { python -I "$@"; }

[ -f W.mp4 ] || yt-dlp -q -f 298 -o W.mp4 "https://www.youtube.com/watch?v=UpYHyLo3-aQ"
[ -f U_a.mp4 ] || yt-dlp -q -f 298 --download-sections "*9010-9110" --force-keyframes-at-cuts -o U_a.mp4 "https://www.youtube.com/watch?v=57fdDCbAs28"
[ -f U_b.mp4 ] || yt-dlp -q -f 298 --download-sections "*10630-10740" --force-keyframes-at-cuts -o U_b.mp4 "https://www.youtube.com/watch?v=57fdDCbAs28"

WCROP="168 0 1112 720"; UCROP="48 60 740 712"
mkdir -p thumbs
echo "== W, 765-940 s: South Clock Town, Deku Link, day 1 morning"
py "$fs/framediff.py" W.mp4 w.tsv $WCROP 765 940
py "$fs/bursts.py" w.tsv W.mp4 thumbs/w $WCROP > w.bursts
py "$here/summary.py" w.bursts 59.94006
echo "== U, 9033-9042 s and 9060-9074 s: South Clock Town, Deku Link, day 1"
for r in "1 23.5 33" "2 50 64"; do
  set -- $r
  py "$fs/framediff.py" U_a.mp4 ua$1.tsv $UCROP $2 $3
  py "$fs/bursts.py" ua$1.tsv U_a.mp4 thumbs/ua$1 $UCROP > ua$1.bursts
  py "$here/summary.py" ua$1.bursts 60
done
echo "== U, 10654-10661 s: South Clock Town, human Link, day 2"
py "$fs/framediff.py" U_b.mp4 ub.tsv $UCROP 22 32
py "$fs/bursts.py" ub.tsv U_b.mp4 thumbs/ub $UCROP > ub.bursts
py "$here/summary.py" ub.bursts 60
