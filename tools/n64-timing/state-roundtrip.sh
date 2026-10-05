#!/usr/bin/env bash
# Checks that save states carry the whole machine, pixel engine included.
#   1. Round trip: a run that saves and reloads its state at fields 150, 300 and 457 must
#      write a stats file byte-identical to a plain run (every column, trace_hash included).
#   2. Coverage: overwriting one TMEM byte at field 30, before the game first draws, must
#      change trace_hash from that field on while every other column of that row stays
#      identical. A poke mid-game can be overwritten by the game's next TMEM load first.
# usage: state-roundtrip.sh ROM [FRAMES]   (FRAMES default 600)
# env:   N64_RUN=<n64-run binary> skips the build; OUT=<dir> sets the output directory.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rom="${1:?usage: state-roundtrip.sh ROM [FRAMES]}"
frames="${2:-600}"
N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
out="${OUT:-$N64_TIMING_HOME/state-roundtrip}"
exe="${N64_RUN:-$(bash "$here/build.sh" | tail -n 1)}"
mkdir -p "$out"

state="$out/state.bin"
printf 'wait 150\nsave-state %s\nload-state %s\nwait 150\nsave-state %s\nload-state %s\nwait 157\nsave-state %s\nload-state %s\n' \
  "$state" "$state" "$state" "$state" "$state" "$state" > "$out/roundtrip.txt"
printf 'wait 30\npoke-tmem 0x123 0x5a\n' > "$out/poke.txt"

"$exe" "$rom" --frames "$frames" --stats "$out/plain.tsv" 2> "$out/plain.log" > /dev/null
"$exe" "$rom" --frames "$frames" --stats "$out/roundtrip.tsv" --script "$out/roundtrip.txt" 2> "$out/roundtrip.log" > /dev/null
"$exe" "$rom" --frames "$frames" --stats "$out/poke.tsv" --script "$out/poke.txt" 2> "$out/poke.log" > /dev/null

exec python - "$out" <<'EOF'
import sys
from pathlib import Path

out = Path(sys.argv[1])
def rows(name):
    lines = (out / name).read_text().splitlines()
    return lines[0].split("\t"), [l.split("\t") for l in lines[1:]]

header, plain = rows("plain.tsv")
_, roundtrip = rows("roundtrip.tsv")
_, poke = rows("poke.tsv")
th = header.index("trace_hash")
failed = False

for log in ("roundtrip.log", "poke.log"):
    if "failed" in (out / log).read_text():
        print(f"state-roundtrip: FAIL, {log} reports a failed step")
        failed = True

if roundtrip == plain:
    print(f"round trip: PASS, {len(plain)} fields byte-identical with saves and loads at fields 150, 300, 457")
else:
    first = next(i for i, (a, b) in enumerate(zip(plain, roundtrip)) if a != b) if len(plain) == len(roundtrip) else min(len(plain), len(roundtrip))
    cols = [header[c] for c in range(len(header)) if first < min(len(plain), len(roundtrip)) and plain[first][c] != roundtrip[first][c]]
    print(f"round trip: FAIL, first differing field {first}, columns {cols}")
    failed = True

first = next((i for i, (a, b) in enumerate(zip(plain, poke)) if a != b), None)
if first is None:
    print("tmem poke: FAIL, no row changed")
    failed = True
else:
    cols = [header[c] for c in range(len(header)) if plain[first][c] != poke[first][c]]
    later = all(plain[i][th] != poke[i][th] for i in range(first, len(plain)))
    verdict = "PASS" if cols == ["trace_hash"] and later else "FAIL"
    failed |= verdict == "FAIL"
    print(f"tmem poke: {verdict}, first differing field {first} (columns {cols}), trace_hash differs on every later field: {later}")

sys.exit(1 if failed else 0)
EOF
