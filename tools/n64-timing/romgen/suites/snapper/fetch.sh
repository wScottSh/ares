#!/usr/bin/env bash
# Fetches the snapper64 console dumps and decodes them for compare.py.
#
# usage: fetch.sh
# Clones https://github.com/HailToDodongo/snapper64 at e1cd8a61fc43 into
# $N64_TIMING_HOME/corpora/snapper64 without running anything from it, downloads the Git LFS
# objects (assets/*.test.7z, 7094 files), and extracts each archive's single .test file into
# $N64_TIMING_HOME/corpora/snapper64-decoded/. Rerunning skips the work already done.
# Without git-lfs it downloads the objects through the LFS batch API and checks each sha256.
# Extraction uses 7z or 7zz if present, else bsdtar (Windows tar.exe and libarchive read 7z).
set -euo pipefail

N64_TIMING_HOME="${N64_TIMING_HOME:-$HOME/n64-timing}"
COMMIT=e1cd8a61fc43
EXPECTED=7094
clone="$N64_TIMING_HOME/corpora/snapper64"
decoded="$N64_TIMING_HOME/corpora/snapper64-decoded"

if [ ! -d "$clone/.git" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone -q https://github.com/HailToDodongo/snapper64 "$clone"
fi
git -C "$clone" -c advice.detachedHead=false checkout -q "$COMMIT"
if git lfs version >/dev/null 2>&1; then
  git -C "$clone" lfs pull
else
  "$(command -v python || command -v python3)" - "$clone" <<'EOF'
import concurrent.futures, hashlib, json, sys, urllib.request
from pathlib import Path

pointers = {}
for path in sorted(Path(sys.argv[1], "assets").glob("*.test.7z")):
    head = path.read_bytes()[:200].decode("ascii", "replace")
    if head.startswith("version https://git-lfs"):
        fields = dict(line.split(" ", 1) for line in head.splitlines() if " " in line)
        pointers[path] = (fields["oid"].removeprefix("sha256:"), int(fields["size"]))

def batch(objects):
    body = json.dumps({"operation": "download", "transfers": ["basic"],
                       "objects": [{"oid": o, "size": n} for o, n in objects]}).encode()
    request = urllib.request.Request("https://github.com/HailToDodongo/snapper64.git/info/lfs/objects/batch",
                                     body, {"Accept": "application/vnd.git-lfs+json",
                                            "Content-Type": "application/vnd.git-lfs+json"})
    with urllib.request.urlopen(request) as reply:
        return {o["oid"]: o["actions"]["download"] for o in json.load(reply)["objects"]}

def download(path, oid, action):
    with urllib.request.urlopen(urllib.request.Request(action["href"], headers=action.get("header", {}))) as reply:
        data = reply.read()
    if hashlib.sha256(data).hexdigest() != oid:
        sys.exit(f"{path.name}: sha256 mismatch")
    path.write_bytes(data)

items = list(pointers.items())
with concurrent.futures.ThreadPoolExecutor(16) as pool:
    for i in range(0, len(items), 100):
        chunk = items[i:i + 100]
        actions = batch([v for _, v in chunk])
        list(pool.map(lambda kv: download(kv[0], kv[1][0], actions[kv[1][0]]), chunk))
print(f"lfs: downloaded {len(items)} objects")
EOF
fi

if command -v 7z >/dev/null; then
  extract() { 7z e "$1" -o"$decoded" -y -bso0 -bsp0; }
elif command -v 7zz >/dev/null; then
  extract() { 7zz e "$1" -o"$decoded" -y -bso0 -bsp0; }
elif [ -x /c/Windows/System32/tar.exe ]; then
  extract() { /c/Windows/System32/tar.exe -xf "$1" -C "$decoded" --strip-components=1; }
else
  extract() { bsdtar -xf "$1" -C "$decoded" --strip-components=1; }
fi

mkdir -p "$decoded"
for archive in "$clone"/assets/*.test.7z; do
  name="$(basename "$archive" .7z)"
  [ -f "$decoded/$name" ] || extract "$archive"
done

count=$(find "$decoded" -maxdepth 1 -name '*.test' | wc -l)
echo "$decoded: $count of $EXPECTED dumps"
[ "$count" -eq "$EXPECTED" ]
