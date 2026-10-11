#!/usr/bin/env bash
# Checks that save states carry the whole machine, pixel engine included.
#   1. Round trip: a run that saves and reloads its state at fields 150, 300 and 457 must
#      write a stats file byte-identical to a plain run (every column, trace_hash included).
#   2. Coverage: overwriting one TMEM byte at field 30, before the game first draws, must
#      change trace_hash from that field on while every other column of that row stays
#      identical. A poke mid-game can be overwritten by the game's next TMEM load first.
#   3. Repeat write: romgen's state suite (MI repeat writes behind an RSP DMA) is saved after
#      each field of its plain run but the last, and a fresh run loads each state after field 0,
#      before its first repeat write. That run must print the plain run's #bench line, whose sum
#      covers every repeat write's bytes, and its later rows must match the plain run's (frame,
#      cpu_cycles and trace_hash belong to the run). A state without a posted repeat write's flag
#      replays it wrong and changes the sum, so each ROM fails unless the runner reports
#      posted-repeats > 0 at one of its saves; otherwise the comparison could not see the flag.
# usage: state-roundtrip.sh ROM [FRAMES]   (FRAMES default 600)
# env:   N64_RUN=<n64-run binary> skips the build; OUT=<dir> sets the output directory.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/host.sh"
rom="${1:?usage: state-roundtrip.sh ROM [FRAMES]}"
frames="${2:-600}"
out="${OUT:-$N64_TIMING_HOME/state-roundtrip}"
exe="${N64_RUN:-$(bash "$here/build.sh" | tail -n 1)}"
mkdir -p "$out"
if command -v cygpath >/dev/null; then
  out="$(cygpath -m "$out")"
  rom="$(cygpath -m "$rom")"
fi

state="$out/state.bin"
printf 'wait 150\nsave-state %s\nload-state %s\nwait 150\nsave-state %s\nload-state %s\nwait 157\nsave-state %s\nload-state %s\n' \
  "$state" "$state" "$state" "$state" "$state" "$state" > "$out/roundtrip.txt"
printf 'wait 30\npoke-tmem 0x123 0x5a\n' > "$out/poke.txt"
(cd "$here" && "$PYTHON" romgen/build.py --suite state --out "$out/state-roms") > "$out/state-roms.txt" 2>&1

"$exe" "$rom" --frames "$frames" --stats "$out/plain.tsv" 2> "$out/plain.log" > /dev/null
"$exe" "$rom" --frames "$frames" --stats "$out/roundtrip.tsv" --script "$out/roundtrip.txt" 2> "$out/roundtrip.log" > /dev/null
"$exe" "$rom" --frames "$frames" --stats "$out/poke.tsv" --script "$out/poke.txt" 2> "$out/poke.log" > /dev/null

for rom in "$out"/state-roms/*.z64; do
  name="$(basename "$rom" .z64)"
  "$exe" "$rom" --frames 30 --stats "$out/$name-plain.tsv" > "$out/$name-plain.out" 2> "$out/$name-plain.log"
  for field in $(seq 1 $(($(wc -l < "$out/$name-plain.tsv") - 3))); do
    printf 'wait %d\nsave-state %s\n' "$field" "$out/$name-$field.bin" > "$out/$name-save-$field.txt"
    printf 'load-state %s\n' "$out/$name-$field.bin" > "$out/$name-load-$field.txt"
    "$exe" "$rom" --frames $((field + 1)) --script "$out/$name-save-$field.txt" > /dev/null 2> "$out/$name-save-$field.log"
    "$exe" "$rom" --frames 30 --stats "$out/$name-load-$field.tsv" --script "$out/$name-load-$field.txt" \
      > "$out/$name-load-$field.out" 2> "$out/$name-load-$field.log"
  done
done

exec "$PYTHON" - "$out" <<'EOF'
import re
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

step_failed = {log: "failed" in (out / log).read_text() for log in ("roundtrip.log", "poke.log")}
for log, bad in step_failed.items():
    if bad:
        print(f"state-roundtrip: FAIL, {log} reports a failed step")
        failed = True

if step_failed["roundtrip.log"]:
    print("round trip: FAIL, a save or load step failed")
elif roundtrip == plain:
    print(f"round trip: PASS, {len(plain)} fields byte-identical with saves and loads at fields 150, 300, 457")
else:
    first = next(i for i, (a, b) in enumerate(zip(plain, roundtrip)) if a != b) if len(plain) == len(roundtrip) else min(len(plain), len(roundtrip))
    cols = [header[c] for c in range(len(header)) if first < min(len(plain), len(roundtrip)) and plain[first][c] != roundtrip[first][c]]
    print(f"round trip: FAIL, first differing field {first}, columns {cols}")
failed |= step_failed["roundtrip.log"] or roundtrip != plain

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

machine = [c for c in range(len(header)) if header[c] not in ("frame", "cpu_cycles", "trace_hash")]
def bench(name):
    return [l for l in (out / name).read_text().splitlines() if l.startswith("#bench")]
plains = sorted(out.glob("state-repeat-*-plain.tsv"))
if not plains:
    print("repeat write: FAIL, no state-repeat ROM (see state-roms.txt)")
    failed = True
for plain_tsv in plains:
    name = plain_tsv.name[:-len("-plain.tsv")]
    _, base = rows(plain_tsv.name)
    line = bench(f"{name}-plain.out")
    bad = []
    posted = []
    for field in range(1, len(base) - 1):
        _, loaded = rows(f"{name}-load-{field}.tsv")
        save_log = (out / f"{name}-save-{field}.log").read_text()
        count = re.search(r"^n64-run: save-state .* posted-repeats=(\d+)$", save_log, re.M)
        posted.append(int(count[1]) if count else None)
        logs = save_log + (out / f"{name}-load-{field}.log").read_text()
        later = [[r[c] for c in machine] for r in loaded[1:]]
        want = [[r[c] for c in machine] for r in base[field + 1:field + 1 + len(later)]]
        if "failed" in logs or not line or bench(f"{name}-load-{field}.out") != line or later != want:
            bad.append(field)
    counts = " ".join("-" if n is None else str(n) for n in posted)
    if bad:
        why = f"fields {bad} differ from the plain run"
    elif None in posted:
        why = "the runner reported no posted-repeats count at a save"
    elif not any(posted):
        why = ("no save held a posted repeat write, so the comparison cannot see a lost repeat flag;"
               " move the delays (romgen/suites/state)")
    else:
        why = None
    failed |= why is not None
    print(f"repeat write {name}: {'FAIL' if why else 'PASS'}, loaded after field 0 from saves after fields"
          f" 1-{len(posted)}, posted-repeats {counts}, " + (why or f"every run prints {line[0].split()[-1]}"))

sys.exit(1 if failed else 0)
EOF
