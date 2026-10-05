"""Builds romgen test ROMs.

usage: python tools/n64-timing/romgen/build.py --suite nemu64|bench|thar0|rdpstat --out DIR
       [--ipl3 IPL3_COMPAT_Z64] [--define NAME=VALUE]

Writes one .z64 per set of the suite (romgen/suites/<suite>/sets.py), for example
nemu64-timing.z64 or bench-pi-dma-sizes.z64, and a .tests.tsv next to each listing every value
the ROM runs. Output is deterministic: the same
inputs give byte-identical ROMs.

The boot code is libdragon's public-domain ipl3_compat.z64 (the same stub
make-emux-smoke-rom.py uses). It loads the flat payload at ROM 0x1000 to the entry point in
header word 0x8, with the payload size in header word 0x10.
"""
import argparse
import importlib
import os
import struct
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "romgen"

from romgen import mips, runtime  # noqa: E402
from romgen.suite import Suite  # noqa: E402

DEFAULT_IPL3 = os.path.join(os.environ.get("N64_TIMING_HOME", os.path.expanduser("~/n64-timing")),
                            "scratch", "r29", "clones", "libdragon", "boot", "bin", "ipl3_compat.z64")


def suite_sets(name):
    try:
        sets = importlib.import_module(f"romgen.suites.{name}.sets")
    except ModuleNotFoundError:
        raise SystemExit(f"unknown suite {name}")
    return sets.SETS


def runtime_text(extra_asm):
    return "\n".join([runtime.RUNTIME] + extra_asm)


def build_payload(set_def):
    suite = Suite(set_def.rom_name, set_def.category, set_def.banner_flags)
    extra = list(set_def.asm)
    base_text = runtime_text(extra)
    probe = mips.Image(runtime.PAYLOAD_BASE).asm(base_text, **runtime.CONSTS, **set_def.consts)
    suite.symbols = probe.layout()
    set_def.build(suite)
    image = mips.Image(runtime.PAYLOAD_BASE)
    image.asm(base_text, **runtime.CONSTS, **set_def.consts)
    image.asm(suite.emit())
    image.asm(".align 16\nvector_image:\n    .space 0x300\npayload_end:")
    image.link()
    for name, addr in suite.symbols.items():
        assert image.symbols[name] == addr, f"runtime symbol {name} moved"
    end = image.symbols["payload_end"]
    limit = getattr(set_def, "payload_limit", runtime.FB0)
    if end > limit:
        raise SystemExit(f"payload ends at {end:#x}, past {limit:#x}")
    data = bytearray(image.data)
    offset = image.symbols["vector_image"] - runtime.PAYLOAD_BASE
    data[offset:offset + 0x300] = runtime.vector_image(image.symbols["exc_generic"])
    return suite, bytes(data)


def make_rom(ipl3, payload):
    payload = payload + b"\0" * (-len(payload) % 0x1000)
    header = bytearray(ipl3)
    struct.pack_into(">I", header, 0x8, runtime.PAYLOAD_BASE)
    struct.pack_into(">I", header, 0x10, len(payload))
    return bytes(header) + payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="nemu64")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ipl3", default=DEFAULT_IPL3)
    ap.add_argument("--set", action="append", help="build only these sets")
    ap.add_argument("--define", action="append", default=[], metavar="NAME=VALUE",
                    help="override an integer assembler constant of the suite, e.g. RUNS=1000")
    args = ap.parse_args()
    defines = {k: int(v, 0) for k, v in (d.split("=", 1) for d in args.define)}
    ipl3 = open(args.ipl3, "rb").read()
    if len(ipl3) != 0x1000 or ipl3[:4] != b"\x80\x37\x12\x40":
        raise SystemExit(f"{args.ipl3}: expected a 4 KiB big-endian ipl3_compat.z64")
    os.makedirs(args.out, exist_ok=True)
    for set_def in suite_sets(args.suite):
        if args.set and set_def.set_name not in args.set:
            continue
        unknown = set(defines) - set(set_def.consts)
        if unknown:
            raise SystemExit(f"{set_def.rom_name}: no constant {', '.join(sorted(unknown))}")
        set_def.consts = {**set_def.consts, **defines}
        suite, payload = build_payload(set_def)
        rom = make_rom(ipl3, payload)
        path = os.path.join(args.out, f"{set_def.rom_name}.z64")
        with open(path, "wb") as f:
            f.write(rom)
        with open(os.path.join(args.out, f"{set_def.rom_name}.tests.tsv"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("index\ttest\tvalue\texpected_cycles\n")
            for ti, t in enumerate(suite.tests):
                for vi, v in enumerate(t.values):
                    desc = v.full_desc if v.full_desc is not None else v.desc
                    expected = ",".join(str(c) for c in v.expected_cycles())
                    f.write(f"{ti}.{vi}\t{t.name}\t{desc}\t{expected}\n")
        print(f"{path}: {len(suite.tests)} tests, {suite.value_count()} values, "
              f"{len(rom)} bytes, payload {len(payload)} bytes")


if __name__ == "__main__":
    main()
