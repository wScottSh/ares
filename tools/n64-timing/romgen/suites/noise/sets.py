"""The noise ROM: Thar0/RDP-Noise rdp_noise.c's 1016x1 NOISE rectangle (README.md)."""
from dataclasses import dataclass, field

from ... import rcp, runtime
from ...suite import Test, Value
from ..rdpstat import routines
from ..snapper import asm
from ..snapper.cases import UNCACHED, Lists, emit, run_sync
from ..rdpstat.routines import fill32

SURF = 0x00500000
WIDTH = 1016
RECORD = "noise-rect-1016"
RGBA, BPP_32 = 0, 3

# libdragon include/rdpq_macros.h at e356bf3, RDPQ_COMBINER1((NOISE, 0, PRIM_LOD_FRAC, 0),
# (0, 0, 0, 0)): slot codes and their bit positions in both cycles.
NOISE, RGB_SUBB_ZERO, PRIM_LOD_FRAC, RGB_ADD_ZERO, ALPHA_ZERO = 7, 8, 14, 7, 7
RGB_SHIFTS = ((52, 28, 47, 15), (37, 24, 32, 6))
ALPHA_SHIFTS = ((44, 12, 41, 9), (21, 3, 18, 0))


def combiner():
    value = 0
    for rgb, alpha in zip(RGB_SHIFTS, ALPHA_SHIFTS):
        for code, shift in zip((NOISE, RGB_SUBB_ZERO, PRIM_LOD_FRAC, RGB_ADD_ZERO), rgb):
            value |= code << shift
        for shift in alpha:
            value |= ALPHA_ZERO << shift
    return value


def draw_list():
    """rdp_noise.c: rdpq_attach of a 1016x1 RGBA32 surface, 1-cycle with blending and
    dithering off, the NOISE x PRIM_LOD_FRAC combiner with PRIM_LOD_FRAC = 255, one fill
    rectangle over the whole surface."""
    return [
        rcp.pipe_sync(),
        rcp.set_color_image(RGBA, BPP_32, WIDTH, SURF),
        rcp.set_scissor(0, 0, WIDTH, 1),
        rcp.set_other_mode(rcp.CYC_1CYCLE | rcp.CD_DISABLE | rcp.AD_DISABLE, 0),
        rcp.set_combine_raw(combiner()),
        rcp.set_prim_color(0, level_frac=0xFF),
        rcp.fill_rectangle(0, 0, WIDTH, 1),
        rcp.full_sync(),
    ]


@dataclass
class Record:
    id: str
    addr: int
    size: int
    dump: bool = True


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    consts: dict = field(default_factory=lambda: {"DUMP": 0})

    def _lists(self):
        lists = Lists("noise")
        return lists, lists.get(draw_list())

    @property
    def asm(self):
        lists, _ = self._lists()
        return [routines.ASM, asm.ASM, "\n".join([
            f"str_snap: .asciiz {runtime.asm_string('@snap ')}",
            f"str_snap_sep: .asciiz {runtime.asm_string(' ')}",
            f"str_snap_nl: .asciiz {runtime.asm_string(chr(10))}",
            f"noise_name: .asciiz {runtime.asm_string(RECORD)}"])] + [lst.asm() for lst in lists.all()]

    def build(self, suite):
        _, draw = self._lists()
        steps = [fill32(UNCACHED | SURF, WIDTH, 0), *run_sync(draw),
                 emit(Record(RECORD, SURF, WIDTH * 4), "noise_name")]
        suite.tests.append(Test("RDP noise", [Value(" [rect 1016]", steps, [])]))


SETS = [SetDef("rect-1016", "noise-rect-1016", "Noise", "(noise: RDP NOISE rectangle, 1016x1)")]
