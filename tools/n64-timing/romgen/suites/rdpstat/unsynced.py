"""Unsynced attribute changes: a register written right after a rectangle, with no SYNC_PIPE.

n64brew Reality_Display_Processor/Pipeline, "Effect of unsynced attribute changes" (rdp-command-
timing.md s.3.7), gives for each attribute the cycles of the previous primitive the change
corrupts, 1-cycle / 2-cycle. These cases check the combiner row (24 / 22): a rectangle drawn with
the combiner selecting PRIMITIVE (red), followed directly by a Set Combine selecting ENVIRONMENT
(green). The rectangle's last 24 cycles, its last 24 pixels in 1-cycle and 11 in 2-cycle (two
cycles per pixel), should come out green and every other pixel red. The table is the reference;
there is no console capture of these cases.
"""
from ...suite import Test, Value
from ... import rcp
from .repeater64 import FB, FB_CPU, FB_STRIDE, FB_STRIDE_PX, rle
from .routines import eq_dec, rle_diff, wait_eq, write32

X0, Y0 = 16, 60
WIDTH, ROWS = 64, 4
WAIT = 1 << 26
OLD = rcp.rgba5551(0xFF, 0, 0, 0xFF)
NEW = rcp.rgba5551(0, 0xFF, 0, 0xFF)
COMBINER_CYCLES = {1: 24, 2: 22}


def combine(source):
    return rcp.set_combine_lerp(*["0", "0", "0", source] * 4)


def case_list(cyc):
    mode0 = (rcp.CYC_1CYCLE if cyc == 1 else rcp.CYC_2CYCLE) | rcp.CD_DISABLE | rcp.AD_DISABLE
    return rcp.DisplayList(f"unsynced_combine_c{cyc}").add(
        rcp.pipe_sync(),
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, FB_STRIDE_PX, FB),
        rcp.set_scissor(0, 0, 320, 240),
        rcp.set_other_mode(mode0, 0),
        rcp.set_prim_color(rcp.rgba8(0xFF, 0, 0, 0xFF)),
        rcp.set_env_color(rcp.rgba8(0, 0xFF, 0, 0xFF)),
        combine("PRIMITIVE"),
        rcp.fill_rectangle_frac(X0 * 4, Y0 * 4, (X0 + WIDTH) * 4, (Y0 + ROWS) * 4),
        combine("ENVIRONMENT"),
        rcp.pipe_sync(),
        rcp.full_sync(),
    )


def expected(cyc):
    pixels = COMBINER_CYCLES[cyc] // cyc
    return [OLD] * (WIDTH * ROWS - pixels) + [NEW] * pixels


LISTS = [case_list(cyc) for cyc in COMBINER_CYCLES]


def data():
    out = [".align 4"]
    for cyc in COMBINER_CYCLES:
        out.append(f"unsynced_ref_c{cyc}:")
        out.append("    .word " + ", ".join(str(w) for w in rle(expected(cyc))))
    return "\n".join(out)


def case(symbols, cyc, lst):
    start = symbols[lst.label] & 0x1FFFFFFF
    region = FB_CPU + Y0 * FB_STRIDE + X0 * 2
    steps = [
        wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, WAIT, 0),
        write32(rcp.DPC_START, start), write32(rcp.DPC_END, start + lst.size()),
        wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, WAIT, 0),
        rle_diff(region, FB_STRIDE, WIDTH, ROWS, symbols[f"unsynced_ref_c{cyc}"], 1),
    ]
    return Value("", steps, [eq_dec(1, 0, "pixels differ from the table's corrupted tail")])


def build(suite):
    s = suite.symbols
    suite.tests += [Test(f"Unsynced Set Combine: {cyc}-cycle, last {COMBINER_CYCLES[cyc]} cycles",
                         [case(s, cyc, lst)]) for cyc, lst in zip(COMBINER_CYCLES, LISTS)]
