#!/usr/bin/env bash
# Feeds the fork's own kit logs to ingest.py as a fake console capture, in a scratch tree, so the
# whole path (normalize, parse, FNV check, store, compare per controller setup, spec regeneration)
# runs without hardware. The console builds' logs (boot-1 and single) become ISViewer logs, with
# these swapped in for the ways a real capture arrives: kit-span as the cartridge SRAM the fork's run
# left (console byte order) and kit-rdp as that SRAM byte-swapped, both in place of their ISViewer
# logs; kit-vi with CRLF line ends; kit-noise also as a capture after Reset; kit-dma also as its four-controller run; and kit-cpu as an extra
# cut log, which ingestion must store and not compare. The external ROMs go in as the fork's
# Thar0 port output (ext-thar0), the fork's n64-systembench output (ext-systembench) and the published
# snapper64 console dumps (ext-snapper64).
# usage: tools/n64-timing/calibration/dry-run.sh MODEL_DIR   (a calibration/run.sh output)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
model="$1"
capture="$(mktemp -d)"
trap 'rm -rf "$capture"' EXIT
for f in "$model"/boot-1/*.txt "$model"/single/*.txt; do
  cp "$f" "$capture/$(basename "$f" .txt).isviewer.log"
done
rm "$capture/kit-span.isviewer.log" "$capture/kit-rdp.isviewer.log"
cp "$model/boot-1/kit-span.srm" "$capture/kit-span.srm"
cp "$model/pads-4/boot-1/kit-dma.txt" "$capture/kit-dma.pads4.isviewer.log"
"$PYTHON" - "$model" "$capture" <<'PY'
import sys
model, capture = sys.argv[1:]
data = open(f"{model}/boot-1/kit-rdp.srm", "rb").read()
open(f"{capture}/kit-rdp.sav", "wb").write(b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4)))
vi = open(f"{model}/boot-1/kit-vi.txt", "rb").read()
open(f"{capture}/kit-vi.isviewer.log", "wb").write(vi.replace(b"\n", b"\r\n"))
open(f"{capture}/kit-noise.reset.isviewer.log", "wb").write(open(f"{model}/boot-1/kit-noise.txt", "rb").read())
cpu = open(f"{model}/boot-1/kit-cpu.txt", "rb").read()
open(f"{capture}/kit-cpu.cut.log", "wb").write(cpu[:len(cpu) // 2])
PY
cp "$model/ext/thar0.txt" "$capture/ext-thar0.usblog.txt"
[ -f "$model/ext/systembench.txt" ] && cp "$model/ext/systembench.txt" "$capture/ext-systembench.isviewer.log"
PYTHONPATH="$n64_repo/tools/n64-timing" "$PYTHON" - "$capture" <<'PY'
import shutil, sys
from pathlib import Path
from romgen.suites.snapper import compare as snap, sets as snap_sets
corpus = Path(snap.default_corpus())
ids = {r.id for st in snap_sets.SETS if st.set_name in snap.REFERENCE_DIGEST
       for c in st.cases for r in c.records if c.group != snap.RW_GROUP}
if corpus.is_dir():
    out = Path(sys.argv[1]) / "ext-snapper64"
    out.mkdir()
    for i in sorted(ids):
        shutil.copyfile(corpus / f"{i}.test", out / f"{i}.test")
PY
"$PYTHON" "$n64_repo/tools/n64-timing/calibration/ingest.py" "$capture" --id dry-run --model "$model" --dry-run
