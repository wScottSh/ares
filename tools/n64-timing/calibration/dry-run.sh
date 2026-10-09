#!/usr/bin/env bash
# Feeds the fork's own kit logs to ingest.py as a fake console capture, in a scratch tree, so the
# whole path (parse, FNV check, store, compare, spec regeneration) runs without hardware. The
# console builds' logs (boot-1 and single) become ISViewer logs; kit-span also goes in as a
# byte-swapped SRAM save and kit-cpu as a cut log, which ingestion must store and not compare.
# usage: tools/n64-timing/calibration/dry-run.sh MODEL_DIR   (a calibration/run.sh output)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../host.sh"
model="$1"
capture="$(mktemp -d)"
trap 'rm -rf "$capture"' EXIT
for f in "$model"/boot-1/*.txt "$model"/single/*.txt; do
  cp "$f" "$capture/$(basename "$f" .txt).isviewer.log"
done
"$PYTHON" - "$model" "$capture" <<'PY'
import sys
model, capture = sys.argv[1:]
data = open(f"{model}/boot-1/kit-span.txt", "rb").read()
data += b"\0" * (-len(data) % 4)
swapped = b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
open(f"{capture}/kit-span.srm", "wb").write(swapped + b"\0" * (0x8000 - len(swapped)))
cpu = open(f"{model}/boot-1/kit-cpu.txt", "rb").read()
open(f"{capture}/kit-cpu.cut.log", "wb").write(cpu[:len(cpu) // 2])
PY
"$PYTHON" "$n64_repo/tools/n64-timing/calibration/ingest.py" "$capture" --id dry-run --model "$model" --dry-run
