"""The ported snapper64 test groups, as cases of on-target steps plus the records they emit.

Each group follows one file of snapper64 src/tests/ at commit e1cd8a61fc43:
- RDPTestModeSpan.cpp  "RDP Test-Mode - Span Tri"   216 tests, 2 surfaces each
- RDPTestModeRW.cpp    "RDP Test-Mode - Span R/W"   32 tests, 128 span reads each
- RDPFillTriSweep.cpp  "RDP Fill Mode Tri (Sweep)"  2048 tests, 1 surface each
- RDPRectNoSync1C.cpp, RDPRectNoSync2C.cpp, RDPRectNoSyncFill.cpp  20 + 40 + 20 tests

A record is what one snapper64 Assert::surface call compares: the RGBA32 bytes of a surface.
Its id is the dump's file stem, "%08X_%08X_%02X" of crc32(group name), crc32(test name) and the
1-based assert index (src/framework/assert.cpp), so it names the console dump directly. The R/W
group asserts values instead of surfaces; its record is the 128 words the ROM reads back, and the
expected bytes are computed from the source's assertion (expected_rw).
"""
import struct
import zlib
from dataclasses import dataclass, field

from ... import rcp
from ...suite import Step
from ..rdpstat.routines import fill32, wait_eq, write32
from .tri import Vertex, f32, triangle

SURF = 0x00500000              # test surface (snapper64 allocates it per test with surface_alloc)
SPAN_SURF = 0x00540000         # the 4x32 span-buffer surface of the Span Tri group
RW_OUT = 0x00541000            # the R/W group's 128 read-back words
UNCACHED = 0xA0000000
WAIT = 1 << 26

RGBA, BPP_32 = 0, 3            # rdp.h Format::RGBA, BBP::_32
SPAN_WORDS = 128               # rdp.h TestMode::SPAN_WORDS

# rdp.h OtherMode().cycleType(c).ditherRGBA(DISABLED).ditherAlpha(DISABLED), the rest 0
DITHER_OFF = rcp.CD_DISABLE | rcp.AD_DISABLE


@dataclass
class Record:
    id: str
    addr: int                  # physical
    size: int
    width: int                 # RGBA32 pixels per row
    dump: bool = False         # always hex-dumped (small records)


@dataclass
class Case:
    group: str
    name: str
    steps: list = field(default_factory=list)
    records: list = field(default_factory=list)


def crc(text):
    return zlib.crc32(text.encode())


def record_id(group, test, n):
    return f"{crc(group):08X}_{crc(test):08X}_{n:02X}"


# libdragon include/rdpq_macros.h at e356bf3: slot codes of RDPQ_COMBINER1/2 for (0,0,0,X)
ZERO_RGB = (8, 8, 16)          # SUBA, SUBB, MUL = ZERO
ZERO_ALPHA = (7, 7, 7)
ALPHA_ONE = 6
SHADE, ENV, COMBINED, RGB_ZERO = 4, 5, 0, 7
COMBINER_2PASS = 1 << 63


def _cc_cycle(add_rgb, shifts_rgb, shifts_alpha):
    a, b, m = ZERO_RGB
    aa, ab, am = ZERO_ALPHA
    sa, sb, sm, sd = shifts_rgb
    ta, tb, tm, td = shifts_alpha
    return (a << sa | b << sb | m << sm | add_rgb << sd
            | aa << ta | ab << tb | am << tm | ALPHA_ONE << td)


CYCLE0 = ((52, 28, 47, 15), (44, 12, 41, 9))
CYCLE1 = ((37, 24, 32, 6), (21, 3, 18, 0))


def combiner1(add_rgb):
    """RDPQ_COMBINER1((0,0,0,add_rgb), (0,0,0,1))"""
    return _cc_cycle(add_rgb, *CYCLE0) | _cc_cycle(add_rgb, *CYCLE1)


def combiner2(add0, add1):
    """RDPQ_COMBINER2((0,0,0,add0), (0,0,0,1), (0,0,0,add1), (0,0,0,1))"""
    return _cc_cycle(add0, *CYCLE0) | _cc_cycle(add1, *CYCLE1) | COMBINER_2PASS


def to_10p2(v):
    """rdp.h floatTo10p2: (uint32_t)(value * 4)"""
    return int(f32(v * 4.0))


def fill_rect(x0, y0, x1, y1):
    return rcp.fill_rectangle_frac(to_10p2(x0), to_10p2(y0), to_10p2(x1), to_10p2(y1))


def fill_rect_size(x0, y0, sx, sy):
    return fill_rect(x0, y0, f32(x0 + sx), f32(y0 + sy))


def attach(width, height):
    """TestSurface::attachAndClear's list: rdp.h attach(surf) followed by syncFull."""
    return [
        rcp.pipe_sync(),
        rcp.set_color_image(RGBA, BPP_32, width, SURF),
        rcp.set_scissor_frac(0, 0, to_10p2(width - 1), to_10p2(height - 1)),
        rcp.set_other_mode(rcp.CYC_FILL, 0),
        rcp.set_fill_color(0),
        rcp.full_sync(),
    ]


class Lists:
    """Interns the display lists the cases run, so identical lists share one copy in the ROM."""

    def __init__(self, prefix):
        self.prefix = prefix
        self.by_cmds = {}

    def get(self, cmds):
        key = tuple(cmds)
        lst = self.by_cmds.get(key)
        if lst is None:
            lst = rcp.DisplayList(f"{self.prefix}_dl{len(self.by_cmds)}", list(cmds))
            self.by_cmds[key] = lst
        return lst

    def all(self):
        return list(self.by_cmds.values())


def run_sync(lst):
    """DPL::runSync: wait for DMA_BUSY clear, START, END, then wait for PIPE_BUSY clear."""
    start = f"{lst.label} & 0x1FFFFFFF"
    end = f"{lst.label}_end & 0x1FFFFFFF"
    return [wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY, 0, WAIT, 0),
            write32(rcp.DPC_START, start), write32(rcp.DPC_END, end),
            wait_eq(rcp.DPC_STATUS, rcp.PIPE_BUSY, 0, WAIT, 0)]


def attach_and_clear(lists, width, height):
    return run_sync(lists.get(attach(width, height))) + [fill32(UNCACHED | SURF, width * height, 0)]


def emit(rec, name_label):
    return Step("snap_emit", [name_label, UNCACHED | rec.addr, rec.size, int(rec.dump)])


def span_tri(lists):
    """RDPTestModeSpan.cpp"""
    group = "RDP Test-Mode - Span Tri"
    other = rcp.set_other_mode(rcp.CYC_1CYCLE | DITHER_OFF, 0)
    cc = rcp.set_combine_raw(combiner1(SHADE))
    base = (Vertex(30, 0, (1.0, 0.0, 0.0, 1.0)),
            Vertex(60, 33, (0.0, 1.0, 0.0, 1.0)),
            Vertex(0, 50, (0.0, 0.0, 1.0, 1.0)))
    cases = []
    for kind in range(4):
        for i in range(54):
            name = f"Tri {kind} | {i}"
            d = -1.0 if kind >= 2 else 1.0
            shift = f32(4.0 + f32(float(i) * d))
            dx, dy = (8.0, shift) if kind % 2 == 0 else (shift, 8.0)
            vtx = [v.moved(dx, dy) for v in base]
            tri = Record(record_id(group, name, 1), SURF, 76 * 64 * 4, 76)
            span = Record(record_id(group, name, 2), SPAN_SURF, 4 * 32 * 4, 4, dump=True)
            draw = lists.get([other, cc, *triangle(*vtx, shade=True), rcp.full_sync()])
            steps = [Step("snap_span_fill", [0x55555555]),
                     fill32(UNCACHED | SPAN_SURF, 4 * 32, 0),
                     *attach_and_clear(lists, 76, 64),
                     *run_sync(draw),
                     Step("snap_span_dump", [UNCACHED | SPAN_SURF])]
            cases.append(Case(group, name, steps, [tri, span]))
    return cases


def rng_words(seed, count):
    """src/utils/rng.cpp RNG::randU32 (xorshift32)."""
    out = []
    for _ in range(count):
        seed ^= (seed << 13) & 0xFFFFFFFF
        seed ^= seed >> 17
        seed ^= (seed << 5) & 0xFFFFFFFF
        out.append(seed)
    return out


RW_STEP = 128
RW_PAGES = 8
RW_COUNT = RW_PAGES * RW_STEP


def rw_data(val_type):
    return [0xFFFFFFFF] * RW_COUNT if val_type == 0 else rng_words(val_type * 0x1234, RW_COUNT)


def rw_cases():
    """RDPTestModeRW.cpp. The data words go into the ROM as rw_data_<valType>."""
    group = "RDP Test-Mode - Span R/W"
    cases = []
    for val_type in range(4):
        for page in range(RW_PAGES):
            start = page * RW_STEP
            name = f"R/W Span {start}-{start + RW_STEP - 1}"
            name += " (FF)" if val_type == 0 else f" (Rand {val_type})"
            rec = Record(record_id(group, name, 1), RW_OUT, RW_STEP * 4, RW_STEP // 4, dump=True)
            steps = [Step("snap_span_rw", [f"rw_data_{val_type}", RW_COUNT, start, RW_STEP,
                                           UNCACHED | RW_OUT])]
            cases.append(Case(group, name, steps, [rec]))
    return cases


def expected_rw(test_name):
    """The words RDPTestModeRW.cpp asserts: the span buffer has 128 words, so register i holds
    the last word written to i mod 128; words 4k+2 keep only their low byte and words 4k+3 read
    0 (maskValue)."""
    val_type = 0 if test_name.endswith("(FF)") else int(test_name.rsplit(" ", 1)[1].rstrip(")"))
    start = int(test_name.split()[2].split("-")[0])
    data = rw_data(val_type)
    out = []
    for i in range(start, start + RW_STEP):
        v = data[RW_COUNT - SPAN_WORDS + i % SPAN_WORDS]
        out.append(v & 0xFF if i % 4 == 2 else 0 if i % 4 == 3 else v)
    return struct.pack(f">{RW_STEP}I", *out)


def fill_tri_sweep(lists):
    """RDPFillTriSweep.cpp"""
    group = "RDP Fill Mode Tri (Sweep)"
    count = 32
    size = 128.0 - 2.0
    cases = []
    for side in range(2):
        for sweep_y in range(count):
            for sweep_x in range(count):
                sx = f32(f32(float(sweep_x) / float(count)) * 2.0)
                sy = f32(f32(float(sweep_y) / float(count)) * 2.0)
                name = f"Sweep {side} | {sx:.2f} | {sy:.2f}"
                if side == 0:
                    p = [[f32(size - 0.25), 1.0] for _ in range(3)]
                    p[2][0] = f32(p[2][0] - f32(f32(size * sx) + 4.0))
                else:
                    p = [[1.0, -size], [1.0, size], [1.0, size]]
                    p[2][0] = f32(p[2][0] + f32(f32(size * sx) + 4.0))
                p[0][1] = f32(p[0][1] + f32(f32(size * sy) + 4.0))
                rec = Record(record_id(group, name, 1), SURF, 128 * 128 * 4, 128)
                draw = lists.get([rcp.set_fill_color(0xFFFFFFFF),
                                  *triangle(*(Vertex(x, y) for x, y in p)), rcp.full_sync()])
                steps = [*attach_and_clear(lists, 128, 128), *run_sync(draw)]
                cases.append(Case(group, name, steps, [rec]))
    return cases


def rgba(r, g, b, a):
    return r << 24 | g << 16 | b << 8 | a


WHITE, RED, GREEN, BLUE = (rgba(0xFF, 0xFF, 0xFF, 0xFF), rgba(0xFF, 0, 0, 0xFF),
                           rgba(0, 0xFF, 0, 0xFF), rgba(0, 0, 0xFF, 0xFF))


def nosync_list(head, i, rect_cmds, size_adjust):
    """The shared body of RDPRectNoSync{1C,2C,Fill}.cpp: a grid of rectangles, each followed by
    color changes with no sync in between. `rect_cmds(rect)` wraps one rectangle."""
    width, height = 320 - 32, 180
    cmds = list(head)
    base_y, base_x = float(i * 6 + 1), 1.0
    if i >= 10:
        base_x, base_y = float((i - 10) * 10 + 1), 8.0
    pos_y = 2.0
    for y in range(16):
        pos_x = 2.0
        for x in range(32):
            cmds += rect_cmds(fill_rect_size(pos_x, pos_y, f32(f32(x + base_x) + size_adjust),
                                             f32(f32(y + base_y) + size_adjust)))
            pos_x = f32(pos_x + f32(f32(x + base_x) + 1))
            if f32(f32(f32(pos_x + x) + base_x) + 1) > width:
                break
        pos_y = f32(pos_y + f32(f32(y + base_y) + 1))
        if f32(f32(f32(pos_y + y) + base_y) + 1) > height:
            break
    cmds.append(rcp.full_sync())
    assert len(cmds) <= 4000, "the tests allocate RDP::DPL dplTri{4000}"
    return cmds


def env_rect(rect):
    return [rcp.pipe_sync(), rcp.pipe_sync(), rcp.set_env_color(WHITE), rect,
            rcp.set_env_color(RED), rcp.set_env_color(GREEN), rcp.set_env_color(BLUE)]


def fill_rect_cmds(rect):
    return [rcp.pipe_sync(), rcp.pipe_sync(), rcp.pipe_sync(), rcp.set_fill_color(WHITE), rect,
            rcp.set_fill_color(RED), rcp.set_fill_color(GREEN), rcp.set_fill_color(BLUE)]


def nosync_case(lists, group, name, head, rect_cmds, size_adjust, i):
    rec = Record(record_id(group, name, 1), SURF, 288 * 180 * 4, 288)
    draw = lists.get(nosync_list(head, i, rect_cmds, size_adjust))
    return Case(group, name, [*attach_and_clear(lists, 288, 180), *run_sync(draw)], [rec])


def rect_nosync(lists):
    """RDPRectNoSync1C.cpp, RDPRectNoSync2C.cpp, RDPRectNoSyncFill.cpp"""
    cases = []
    head_1c = [rcp.pipe_sync(), rcp.set_other_mode(rcp.CYC_1CYCLE | DITHER_OFF, 0),
               rcp.set_combine_raw(combiner1(ENV))]
    for i in range(20):
        cases.append(nosync_case(lists, "RDP Rect No-Sync-Env 1C", f"Rect Env {i}",
                                 head_1c, env_rect, 0, i))
    cc_2c = (combiner2(ENV, COMBINED), combiner2(RGB_ZERO, ENV))
    for cycle in range(2):
        head = [rcp.pipe_sync(), rcp.set_other_mode(rcp.CYC_2CYCLE | DITHER_OFF, 0),
                rcp.set_combine_raw(cc_2c[cycle])]
        for i in range(20):
            cases.append(nosync_case(lists, "RDP Rect No-Sync-Env 2C",
                                     f"Rect Env {i} | In Cycle-{cycle + 1}", head, env_rect, 0, i))
    head_fill = [rcp.set_other_mode(rcp.CYC_FILL | DITHER_OFF, 0)]
    for i in range(20):
        cases.append(nosync_case(lists, "RDP Rect No-Sync-Fill", f"Rect Env {i}",
                                 head_fill, fill_rect_cmds, -1, i))
    return cases
