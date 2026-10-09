#!/usr/bin/env bash
# Feeds the fork's own kit logs to ingest.py as a fake console capture, in a scratch tree, so the
# whole path (normalize, parse, FNV check, store, compare per controller setup, spec regeneration)
# runs without hardware. The console builds' logs (boot-1 and single) become ISViewer logs, with
# these swapped in for the ways a real capture arrives: kit-span as the cartridge SRAM the fork's run
# left (console byte order) and kit-rdp as that SRAM byte-swapped, both in place of their ISViewer
# logs; kit-vi with CRLF line ends; kit-dma also as its four-controller run; and kit-cpu as an extra
# cut log, which ingestion must store and not compare.
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
cpu = open(f"{model}/boot-1/kit-cpu.txt", "rb").read()
open(f"{capture}/kit-cpu.cut.log", "wb").write(cpu[:len(cpu) // 2])
PY
"$PYTHON" "$n64_repo/tools/n64-timing/calibration/ingest.py" "$capture" --id dry-run --model "$model" --dry-run
