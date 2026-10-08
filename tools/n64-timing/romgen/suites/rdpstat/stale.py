"""Span-buffer coherency: four stacked image-read rectangles, with and without G_PM_1PRIMITIVE.

SDK pro-man 12.2.3 (Span Buffer Coherency): without 1PRIMITIVE the RDP prefetches the next
primitive's span before the previous primitive's pixels are written, so a read-modify-write of
the same pixels reads stale data; 1PRIMITIVE serializes them (docs/research/1prim-cost.md).
cen64 jgemu rdp_core.c:4551-4567 states the hardware-adjudicated outcome (PRDP 12:15 and 12:16
48-bit checksums, 1- and 2-cycle stacks of four identical one-row rectangles): non-atomic stacks
of narrow rectangles retire the two-blend value ("repeated blends of one pixel advance only every
other primitive"), atomic stacks and wide ones (cen64's D <= L, 25 or more 1-cycle pixels) the
four-blend value. The capture set itself is not public (1prim-cost.md open question 4).

Each case clears one row to black, draws K identical rectangles blending 50% white over memory
(P = pixel, A = CC alpha 0x80, M = memory, B = 1 - A, FORCE_BL, IM_RD), Sync Full, and reads the
first pixel. The two-blend and four-blend values are the same stack drawn with 1PRIMITIVE and
K = 2 or 4, which no stale read can affect, so every check compares two outcomes of one ROM.
"""
from ...suite import Test, Value
from ... import rcp
from .repeater64 import FB, FB_CPU, FB_STRIDE_PX
from .routines import eq_dec, fill32, read16, res_eq, wait_eq, write32

ROW = 100
X0 = 16
FORCE_BL = 1 << 14
BLEND_MIX = (1 << 22) | (1 << 20)   # cycle 0 and 1: P*A + M*(1-A) (m2a = memory)
WAIT = 1 << 26
CASES = [(cyc, width) for cyc in (1, 2) for width in (8, 32)]


def case_list(cyc, width, atomic, count):
    mode0 = (rcp.CYC_1CYCLE if cyc == 1 else rcp.CYC_2CYCLE) | (rcp.ATOMIC_PRIM if atomic else 0)
    mode1 = BLEND_MIX | FORCE_BL | rcp.IM_RD
    label = f"stale_c{cyc}_w{width}_a{atomic}_n{count}"
    return rcp.DisplayList(label).add(
        rcp.pipe_sync(),
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, FB_STRIDE_PX, FB),
        rcp.set_scissor(0, 0, 320, 240),
        rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4),
        rcp.set_prim_color(rcp.rgba8(255, 255, 255, 0x80)),
        rcp.set_other_mode(mode0, mode1),
        *[rcp.fill_rectangle(X0, ROW, X0 + width, ROW + 1)] * count,
        rcp.full_sync(),
    )


LISTS = []
KEYS = {}
for cyc, width in CASES:
    for atomic, count in ((0, 4), (1, 4), (1, 2)):
        lst = case_list(cyc, width, atomic, count)
        KEYS[(cyc, width, atomic, count)] = lst
        LISTS.append(lst)


def run_list(symbols, lst, res):
    start = symbols[lst.label] & 0x1FFFFFFF
    row = FB_CPU + 2 * (ROW * FB_STRIDE_PX + X0)
    return [
        wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, WAIT, res),
        fill32(row, 32, 0x00010001),
        write32(rcp.DPC_START, start), write32(rcp.DPC_END, start + lst.size()),
        wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, WAIT, res),
        read16(row, res),
    ]


def case(symbols, cyc, width):
    stale = width < 25
    steps = (run_list(symbols, KEYS[(cyc, width, 1, 2)], 0)
             + run_list(symbols, KEYS[(cyc, width, 1, 4)], 1)
             + run_list(symbols, KEYS[(cyc, width, 0, 4)], 2)
             + [res_eq(0, 1, 3), res_eq(2, 0 if stale else 1, 4)])
    outcome = "the two-blend value (stale reads)" if stale else "the four-blend value"
    return Value("", steps, [
        eq_dec(3, 0, "two and four atomic blends should differ"),
        eq_dec(4, 1, f"four non-atomic rectangles should retire {outcome}"),
    ])


def build(suite):
    s = suite.symbols
    suite.tests += [Test(f"1PRIMITIVE stale read: {cyc}-cycle, {width} px", [case(s, cyc, width)])
                    for cyc, width in CASES]
