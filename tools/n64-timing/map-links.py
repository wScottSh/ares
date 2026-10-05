#!/usr/bin/env python3
"""Rewrite research-branch doc links in the wayfinder map body to master.

usage: gh issue view 1 --json body --jq .body | map-links.py [--check] > new-body.md

--check exits 1 if any rewritten target file is missing from the working tree.
"""
import re
import sys
from pathlib import Path

REPO = "https://github.com/wScottSh/ares"
LINK = re.compile(re.escape(REPO) + r"/blob/research/[^/\s)]+/(docs/research/[^\s)>\"']+)")
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    body = sys.stdin.read()
    targets = []

    def rewrite(m):
        targets.append(m.group(1))
        return f"{REPO}/blob/master/{m.group(1)}"

    out = LINK.sub(rewrite, body)
    missing = sorted({t for t in targets if not (ROOT / t).is_file()})
    for t in missing:
        print(f"missing: {t}", file=sys.stderr)
    if "--check" in sys.argv[1:]:
        print(f"{len(targets)} links, {len(missing)} missing", file=sys.stderr)
        return 1 if missing else 0
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
