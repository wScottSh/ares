"""Host checks for the thar0 suite: RDP encodings, expected.tsv, and the comparator's reduction.

usage: python -m romgen.suites.thar0.selftest   (from tools/n64-timing)
"""
import os
import sys
import tempfile

from ... import rcp
from . import compare
from .configs import SPECS
from .thar0 import setup_dl

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")


def hexcmd(cmd):
    return f"{cmd[0]:08X} {cmd[1]:08X}"


# libultra gbi.h gsDPSetCombineMode(G_CC_PRIMITIVE, G_CC_PRIMITIVE) is FCFFFFFF FFFDF6FB.
check("combine prim", hexcmd(rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4)), "FCFFFFFF FFFDF6FB")
check("full sync", hexcmd(rcp.full_sync()), "E9000000 00000000")
check("pipe sync", hexcmd(rcp.pipe_sync()), "E7000000 00000000")
check("fill rect 320x240", hexcmd(rcp.fill_rectangle(0, 0, 320, 240)), "F65003C0 00000000")
check("scissor 320x240", hexcmd(rcp.set_scissor_frac(0, 0, 0, 1280, 960)), "ED000000 005003C0")
check("color image rgba16 320", hexcmd(rcp.set_color_image(0, 2, 320, 0x80100000)), "FF10013F 80100000")
check("fill mode", hexcmd(rcp.set_other_mode(rcp.CYC_FILL, 0)), "EF300000 00000000")

# Spec 37 (ZB read/write, Z fail, 2-cycle) exercises the fail prepass and every om1 flag but IM_RD.
dl = [hexcmd(c) for c in setup_dl(SPECS[37])]
check("spec 37 othermode", dl[13], "EF100CF0 00000234")
check("spec 37 length", len(dl), 23)
check("spec 20 (Z pass) has no prepass", len(setup_dl(SPECS[20])), 18)

# The plan's exact hardware anchors (T12): alpha-fail 1-cycle 77772, 2-cycle 155052 BUFBUSY.
exp = compare.load_expected()
check("expected 92", (exp[92][0], exp[92][1]), ("ac-zbsep-vioff-noimrd-1cyc", (77772.0, 77772.0, 77772.0)))
check("expected 93 min", exp[93][1][0], 155052.0)

# analyze.py prunes values outside the 1%/99% quantiles before min/avg/max.
check("reduce prunes extremes", compare.reduce([5] + [10] * 98 + [50]), (10, 10.0, 10))
check("signed delta", compare.signed32(0xFFFFFFFF), -1)

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "out.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Running x...\n{SPECS[92].desc}\nBUF = [\n    77772, 77773, \n]\nPIPE = [\n    4294967295, \n]\n")
    blocks = compare.parse(path)
    check("parse", blocks, {92: {"BUF": [77772, 77773], "PIPE": [-1]}})

for line in failures:
    print(line)
print(f"thar0 self-test: {len(failures)} failures")
sys.exit(1 if failures else 0)
