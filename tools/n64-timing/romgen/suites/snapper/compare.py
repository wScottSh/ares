"""Compares a snapper ROM's output with the snapper64 console dumps.

usage: python -m romgen.suites.snapper.compare SET STDOUT_TXT OUT_DIR [--corpus DIR]

SET is a set name from sets.py (span-tri, test-mode-rw, fill-tri-sweep, rect-nosync).
STDOUT_TXT is the ROM's guest output: one "@snap <id> <bytes> <fnv>" line per record, each
optionally followed by the emux XHEXDUMP of its bytes. The console dumps are the decoded
snapper64 assets (fetch.sh), named <id>.test, read from --corpus (default
$N64_TIMING_HOME/corpora/snapper64-decoded). Before comparing, the script checks the dumps a
set uses against the digest pinned in REFERENCE_DIGEST. The R/W group has no dumps; its
expected words come from the source's assertion (cases.expected_rw).

A record matches when its FNV-1a 32 equals the reference's. When the ROM also dumped the
bytes (always for the small records, for every record with --define DUMP=1), the script
compares them byte for byte and counts differing pixels.

Writes OUT_DIR/records.tsv (id, group, test, result, differing pixels) and
OUT_DIR/compare.txt (one "snapper:<set> <group>: X/Y match" line per group), and prints the
latter.
"""
import argparse
import hashlib
import os
import re
import struct
import sys

from . import cases, sets

# sha256 over "<id> <sha256 of <id>.test>\n" for every dump the set reads, sorted by id.
REFERENCE_DIGEST = {
    "span-tri": "ec78fa6d5192790cc525b7d3db4d5338853a04f2b08bb305ec0248b9341205dd",
    "fill-tri-sweep": "fc5aa265a4c2bb1477bc62926dfc4211f76de51f8e5a99767dc85c51fe090a4f",
    "rect-nosync": "b5e06e457336222c4946f23c58a3ad9c23e5b8ded94fc62bf9e58e7d183ce4de",
}

SNAP = re.compile(r"^@snap (\S+) (\d+) 0x([0-9a-f]+)$")
HEXDUMP = re.compile(r"^[0-9a-f]{16} [0-9a-f]{4}: ([0-9a-f ]+)\|", re.I)
RW_GROUP = "RDP Test-Mode - Span R/W"


def fnv1a_words(data):
    h = 0x811C9DC5
    for (w,) in struct.iter_unpack(">I", data):
        h = ((h ^ w) * 0x01000193) & 0xFFFFFFFF
    return h


def default_corpus():
    home = os.environ.get("N64_TIMING_HOME", os.path.expanduser("~/n64-timing"))
    return os.path.join(home, "corpora", "snapper64-decoded")


def parse(stdout_txt):
    """{id: (bytes, fnv, dumped bytes or None)}"""
    out, current = {}, None
    with open(stdout_txt, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = SNAP.match(line)
            if m:
                current = m.group(1)
                out[current] = [int(m.group(2)), int(m.group(3), 16), bytearray()]
                continue
            m = HEXDUMP.match(line)
            if m and current is not None:
                out[current][2] += bytes.fromhex(m.group(1).replace(" ", ""))
    return {k: (n, h, bytes(d) if d else None) for k, (n, h, d) in out.items()}


def reference_digest(ids, corpus):
    lines = []
    for rid in sorted(ids):
        with open(os.path.join(corpus, f"{rid}.test"), "rb") as f:
            lines.append(f"{rid} {hashlib.sha256(f.read()).hexdigest()}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def expected_bytes(case, rec, corpus):
    if case.group == RW_GROUP:
        return cases.expected_rw(case.name)
    with open(os.path.join(corpus, f"{rec.id}.test"), "rb") as f:
        return f.read()


def compare(set_def, stdout_txt, corpus):
    got = parse(stdout_txt)
    rows = []
    for case in set_def.cases:
        for rec in case.records:
            want = expected_bytes(case, rec, corpus)
            seen = got.get(rec.id)
            if seen is None:
                rows.append((rec.id, case.group, case.name, "not-run", ""))
                continue
            size, fnv, dumped = seen
            if dumped is not None and len(dumped) == size:
                differ = sum(dumped[i:i + 4] != want[i:i + 4] for i in range(0, size, 4))
                result = "match" if differ == 0 and size == len(want) else "differ"
                rows.append((rec.id, case.group, case.name, result, str(differ)))
            else:
                result = "match" if size == len(want) and fnv == fnv1a_words(want) else "differ"
                rows.append((rec.id, case.group, case.name, result, ""))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("stdout_txt")
    ap.add_argument("out_dir")
    ap.add_argument("--corpus", default=default_corpus())
    ap.add_argument("--print-digest", action="store_true",
                    help="print the reference digest of the set's dumps and exit")
    args = ap.parse_args()
    set_def = next((s for s in sets.SETS if s.set_name == args.set), None)
    if set_def is None:
        raise SystemExit(f"unknown set {args.set}")
    ids = [r.id for c in set_def.cases for r in c.records if c.group != RW_GROUP]
    if ids:
        missing = [i for i in ids if not os.path.exists(os.path.join(args.corpus, f"{i}.test"))]
        if missing:
            raise SystemExit(f"pending:snapper-lfs: {len(missing)} of {len(ids)} dumps missing "
                             f"from {args.corpus} (run fetch.sh)")
        digest = reference_digest(ids, args.corpus)
        if args.print_digest:
            print(f"{args.set}\t{digest}")
            return
        if digest != REFERENCE_DIGEST[args.set]:
            raise SystemExit(f"{args.corpus}: the {args.set} dumps do not match the pinned digest")
    rows = compare(set_def, args.stdout_txt, args.corpus)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "records.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("id\tgroup\ttest\tresult\tdiffering_pixels\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    lines = []
    for group in dict.fromkeys(r[1] for r in rows):
        mine = [r for r in rows if r[1] == group]
        n = sum(r[3] == "match" for r in mine)
        not_run = sum(r[3] == "not-run" for r in mine)
        extra = f" ({not_run} not run)" if not_run else ""
        lines.append(f"snapper:{args.set} {group}: {n}/{len(mine)} match{extra}")
    with open(os.path.join(args.out_dir, "compare.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
