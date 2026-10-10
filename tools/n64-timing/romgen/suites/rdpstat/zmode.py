"""Unsynced z_mode changes: Set Other Modes changing only z_mode right after a rectangle, with no SYNC_PIPE.

n64brew Reality_Display_Processor/Pipeline, "Effect of unsynced attribute changes" (rdp-command-
timing.md s.3.7), z_mode row: the change corrupts the last 27 cycles of the previous primitive in
1-cycle mode and 26 in 2-cycle, so the last 27 pixels in 1-cycle and 13 in 2-cycle (two cycles per
pixel) take the new mode. The cases follow the kit-tex attribute points (calib/tex.py
attribute_case "zmode" and "zmode-rev"): a 64x4 PRIMITIVE-red rectangle at primitive Z 0 over a
far-plane Z buffer, Z compare on and Z update off. Opaque passes and draws red; decal fails and
leaves the background. Pass-to-fail turns the tail to background, fail-to-pass turns it red, so a
model that draws the old mode under the tail fails the first and one that skips the tail fails
both. The table is the reference; there is no console capture of these cases.
"""
from ...suite import Test, Value
from ... import rcp
from .repeater64 import FB, FB_CPU, FB_STRIDE, FB_STRIDE_PX, rle
from .routines import eq_dec, fill32, rle_diff, wait_eq, write32

X0, Y0 = 16, 60
WIDTH, ROWS = 64, 4
WAIT = 1 << 26
ZB = 0x00600000                  # past the 240 rows of FB; same stride as FB
ZB_CPU = 0xA0000000 | ZB
FAR = 0xFFFCFFFC                 # two Z words at MAXFBZ, dz 0
BG = rcp.rgba5551(0, 0, 0xFF, 0xFF)
RED = rcp.rgba5551(0xFF, 0, 0, 0xFF)
ZMODE_DEC = 3 << 10
ZMODE_CYCLES = {1: 27, 2: 26}
DIRECTIONS = {"pass-to-fail": (0, ZMODE_DEC), "fail-to-pass": (ZMODE_DEC, 0)}


def mode1(zmode):
    return rcp.ZS_PRIM | rcp.Z_CMP | zmode


def case_list(cyc, direction):
    before, after = DIRECTIONS[direction]
    mode0 = (rcp.CYC_1CYCLE if cyc == 1 else rcp.CYC_2CYCLE) | rcp.CD_DISABLE | rcp.AD_DISABLE
    return rcp.DisplayList(f"unsynced_zmode_c{cyc}_{direction.replace('-', '_')}").add(
        rcp.pipe_sync(),
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, FB_STRIDE_PX, FB),
        rcp.set_depth_image(ZB),
        rcp.set_scissor(0, 0, 320, 240),
        rcp.set_other_mode(mode0, mode1(before)),
        rcp.set_prim_color(rcp.rgba8(0xFF, 0, 0, 0xFF)),
        rcp.set_prim_depth(0, 0),
        rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4),
        rcp.fill_rectangle_frac(X0 * 4, Y0 * 4, (X0 + WIDTH) * 4, (Y0 + ROWS) * 4),
        rcp.set_other_mode(mode0, mode1(after)),
        rcp.pipe_sync(),
        rcp.full_sync(),
    )


def tail_pixels(cyc):
    return ZMODE_CYCLES[cyc] // cyc


def expected(cyc, direction):
    head, tail = (RED, BG) if direction == "pass-to-fail" else (BG, RED)
    return [head] * (WIDTH * ROWS - tail_pixels(cyc)) + [tail] * tail_pixels(cyc)


CASES = [(cyc, d) for cyc in ZMODE_CYCLES for d in DIRECTIONS]
LISTS = [case_list(cyc, d) for cyc, d in CASES]


def ref_label(cyc, direction):
    return f"zmode_ref_c{cyc}_{direction.replace('-', '_')}"


def data():
    out = [".align 4"]
    for cyc, d in CASES:
        out.append(f"{ref_label(cyc, d)}:")
        out.append("    .word " + ", ".join(str(w) for w in rle(expected(cyc, d))))
    return "\n".join(out)


def case(symbols, cyc, direction, lst):
    start = symbols[lst.label] & 0x1FFFFFFF
    rows = Y0 * FB_STRIDE
    steps = [
        wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, WAIT, 0),
        fill32(FB_CPU + rows, ROWS * FB_STRIDE // 4, BG << 16 | BG),
        fill32(ZB_CPU + rows, ROWS * FB_STRIDE // 4, FAR),
        write32(rcp.DPC_START, start), write32(rcp.DPC_END, start + lst.size()),
        wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, WAIT, 0),
        rle_diff(FB_CPU + rows + X0 * 2, FB_STRIDE, WIDTH, ROWS, symbols[ref_label(cyc, direction)], 1),
    ]
    return Value("", steps, [eq_dec(1, 0, "pixels differ from the table's z_mode tail")])


def test_name(cyc, direction):
    return f"Unsynced z_mode {direction}: {cyc}-cycle, last {ZMODE_CYCLES[cyc]} cycles"


def build(suite):
    s = suite.symbols
    suite.tests += [Test(test_name(cyc, d), [case(s, cyc, d, lst)]) for (cyc, d), lst in zip(CASES, LISTS)]
