#!/usr/bin/env bash
# Reproduces every capture measurement in ../mm-filesel-slowdown.md.
# Needs yt-dlp, ffmpeg (for yt-dlp section cuts), Python 3 with opencv-python and numpy.
# usage: run.sh WORKDIR
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="${1:?usage: run.sh WORKDIR}"
mkdir -p "$work"; cd "$work"

get() { # id format section
  [ -f "$1.mp4" ] || yt-dlp -q -f "$2" ${3:+--download-sections "$3"} -o "$1.mp4" "https://www.youtube.com/watch?v=$1"
}
# MM hardware: UltraNova5000 pt.1 (empty files), WatchmeplayNintendo Part 1 (two named files)
get 57fdDCbAs28 298 "*0-600"
get UpYHyLo3-aQ 298 "*0-600"
# OoT hardware on the UltraNova5000 rig (chain check)
get aTxWmxP1HZg 298 "*0-420"
# ares nightly captures from ares-emulator/ares#2320 (method control)
get e6dUTwfkxxU 299 ""
# OoT hardware capture attached to ares-emulator/ares#2320 (comment 2026-07-28)
[ -f oot_hw.mp4 ] || curl -sSL -o oot_hw.mp4 "https://github.com/user-attachments/assets/9a15322f-ba3d-4cff-bb74-7e31a2198a58"

U="57fdDCbAs28.mp4"; W="UpYHyLo3-aQ.mp4"; UCROP="48 0 972 712"; WCROP="168 0 1112 720"
py() { python "$here/$1" "${@:2}"; }

echo "== per-frame cadence, OoT hardware (#2320 attachment)"
py framediff.py oot_hw.mp4 oot_hw.diff.tsv
py cadence.py oot_hw.diff.tsv
echo "== per-frame cadence in high-motion bursts"
py framediff.py "$U" u.diff.tsv $UCROP 150 270
py bursts.py u.diff.tsv "$U" u_burst $UCROP
py framediff.py "$W" w.diff.tsv $WCROP 15 60
py bursts.py w.diff.tsv "$W" w_burst $WCROP
py framediff.py aTxWmxP1HZg.mp4 uo.diff.tsv 0 0 830 720 14 48
py bursts.py uo.diff.tsv aTxWmxP1HZg.mp4 uo_burst 0 0 830 720
echo "== capture-chain check on 20 fps gameplay"
py framediff.py "$U" u_play.diff.tsv $UCROP 525 560
py bursts.py u_play.diff.tsv "$U" uplay_burst $UCROP
py framediff.py "$W" w_play.diff.tsv $WCROP 270 300
py bursts.py w_play.diff.tsv "$W" wplay_burst $WCROP
echo "== idle states: cursor pulse period (40 game frames)"
py pulse.py e6dUTwfkxxU.mp4 7.8 11.6 495 333 788 408
py trifit.py e6dUTwfkxxU.mp4 7.8 9.5 495 333 788 408
py pulse.py "$U" 161 168.6 205 222 400 272
py trifit.py "$U" 164.0 167.4 205 222 400 272
py pulse.py "$U" 171 187 215 405 345 445
py trifit.py "$U" 176 183 215 405 345 445
py trifit.py "$W" 19.95 21.5 330 222 525 270
