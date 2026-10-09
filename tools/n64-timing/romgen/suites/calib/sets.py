"""The calibration kit ROMs (docs/calibration/hardware-run.md, tools/n64-timing/calibration/).

Each kit ROM combines bench ROMs (suites/bench/benches.py) with the kit's own points, so one
flashcart load measures many questions. build.py always builds this suite with --hw (hwout.py).
Every line is "#bench <rom> <point> key=value ...", the bench format, so suites/bench/report.py
derive() reads kit and bench output alike. `N64_CALIB_DELAYS=K,K,...` sets the boot delays of the
fork's builds (calibration/run.sh walks phase as the bench does); the console build is boot-1.
"""
import os
from dataclasses import dataclass, field

from ... import rcp, runtime
from ...suite import Step, Test, Value
from ..bench import asm as bench_asm, benches
from ..bench.benches import KSEG0, KSEG1, LIST_BUF, COLOR_IMAGE, Rom, rdp_point
from ..noise.sets import combiner
from ..rdpstat import routines
from ..rdpstat.routines import fill32
from ..snapper import asm as snapper_asm
from ..snapper.cases import UNCACHED, Lists, emit, run_sync
from . import asm

DELAYS = [int(k) for k in os.environ.get("N64_CALIB_DELAYS", "1,165,329,493,657,821,985,1149").split(",")]
CAL_BUF = 0x005D0000       # bank 5, clear of the bench buffers (SB_BUF 0x5C0000, HPOS 0x5A0000)


def dcb(suite):
    rom = Rom(suite, "dcb")
    for name in asm.DCB:
        rom.point(name[6:].replace("_", "-"), name, [KSEG0 | CAL_BUF], [("pairs", asm.UNROLL)], reps=8)


def wb_stores(suite):
    rom = Rom(suite, "wb-stores")
    for n in asm.WB_COUNTS:
        for tail in ("", "_lw"):
            rom.point(f"sw-{n}{tail.replace('_', '-')}", f"k_sw{n}{tail}", [KSEG1 | (CAL_BUF + 0x1000), 0],
                      [("stores", n), ("target", "rdram")], reps=8)


#Registers whose write has no effect the kit can see: V_INTR past the last line with interrupts
#off, a zero MI mask or DPC status write (set/clear pairs, none set), and the SP semaphore.
REG_TARGETS = [("vi-v-intr", 0xA440000C, 0x3FF), ("mi-intr-mask", 0xA430000C, 0),
               ("dpc-status", 0xA410000C, 0), ("sp-semaphore", 0xA404001C, 0)]


def reg_write(suite):
    rom = Rom(suite, "reg-write")
    for dev, addr, value in REG_TARGETS:
        for n in asm.REG_COUNTS:
            for tail in ("", "_lw"):
                rom.point(f"{dev}-{n}{tail.replace('_', '-')}", f"k_sw{n}{tail}", [addr, value],
                          [("stores", n), ("target", dev)], reps=8)


def ifill(suite):
    rom = Rom(suite, "ifill")
    for name, cold in (("warm", 0), ("cold", 1)):
        rom.point(name, "k_ifill", [cold], [("cold", cold)], reps=8)


VI_DELAYS = [1, 10, 100, 300, 1000, 1314, 2000, 3000, 10000, 100000]


def vi_enable(suite):
    rom = Rom(suite, "vi-enable")
    for d in VI_DELAYS:
        rom.point(f"delay-{d}", "k_vi_enable", [d], [("delay", d)], reps=4,
                  extra=["v_at_enable", "first_ticks", "v_after", "line_ticks"])


def count_fields(suite):
    rom = Rom(suite, "count-fields")
    rom.point("fields-60", "k_count_fields", [60], [("fields", 60)], reps=3, extra=["field_min", "field_max"])


def fifo_depth(suite):
    rom = Rom(suite, "fifo-depth")
    for n in (64, 512):
        body = [rcp.nop()] * n + [rcp.full_sync()]
        words = rcp.words(body)
        build = Step("bench_list_step", [suite.blob(words), len(words), 0, 0, 0, 0, 0, KSEG1 | LIST_BUF], 0)
        rom.point(f"nops-{n}", "k_fifo_depth", [LIST_BUF, 4 * len(words), 20000], [("nops", n)], reps=4,
                  extra=["current_minus_start", "status"], pre=[build])


def cmd_fetch(suite):
    rom = Rom(suite, "cmd-fetch")
    for name, body, n in (("rect-320x8", rcp.fill_rectangle(0, 0, 320, 8), 64), ("nop", rcp.nop(), 512)):
        words = rcp.words(benches.rdp_prologue() + [body] * n + [rcp.full_sync()])
        build = Step("bench_list_step", [suite.blob(words), len(words), 0, 0, 0, 0, 0, KSEG1 | LIST_BUF], 0)
        rom.point(f"{name}-{n}", "k_cmd_fetch", [LIST_BUF, 4 * len(words)], [("cmds", n)], reps=4,
                  flags=benches.VI_OFF, extra=["changes", "min_step", "max_step", "first_step"], pre=[build])


SPAN_WIDTHS = [1, 4, 8, 12, 14, 15, 16, 17, 18, 20, 24, 28, 30, 31, 32, 33, 34, 36, 40, 44, 46, 47, 48, 49, 50,
               56, 62, 63, 64, 65, 66, 72, 80]
IM_SIZ_32b = 3


def span_width(suite):
    """1-cycle rectangles 8 lines high with IM_RD, at 16 and 32 bpp: where DPC_CLOCK steps against the
    width shows the span's color half (span-ram.md question 1)."""
    rom = Rom(suite, "span-width")
    for bpp, siz in ((16, rcp.IM_SIZ_16b), (32, IM_SIZ_32b)):
        prologue = [rcp.set_color_image(rcp.IM_FMT_RGBA, siz, 320, COLOR_IMAGE), rcp.set_scissor(0, 0, 320, 240),
                    rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4), rcp.set_prim_color(0xFF0000FF),
                    rcp.set_other_mode(rcp.CYC_1CYCLE, rcp.IM_RD)]
        for w in SPAN_WIDTHS:
            rdp_point(rom, f"b{bpp}-w{w}", [rcp.fill_rectangle(0, 0, w, 8)], 1, [("bpp", bpp), ("w", w), ("h", 8)],
                      prologue=prologue)


@dataclass
class BenchKit:
    """A kit ROM built from bench builders and the kit's own; one per boot delay."""
    set_name: str
    rom_name: str
    builders: list
    category: str = "Calib"
    consts: dict = field(default_factory=dict)

    @property
    def banner_flags(self):
        return f"(calib={self.set_name})"

    @property
    def asm(self):
        return [bench_asm.ASM, asm.ASM]

    def build(self, suite):
        for b in self.builders:
            b(suite)


KITS = {
    "kit-cpu": [benches.uncached_sizes, benches.rcp_reg_read, benches.pif_ram_read, benches.pi_io_read,
                benches.pi_io_write, benches.si_io_write, benches.dirty_row_sweep, benches.dirty_miss_isolated,
                dcb, wb_stores, reg_write, ifill],
    "kit-vi": [vi_enable, count_fields],
    "kit-dma": [benches.mi_memset_uncached, benches.mi_memset_cached, benches.mi_memset_rspdma,
                benches.mi_memset_repeat, benches.sp_dma_sweep, benches.pi_dma_sizes, benches.si_dma],
    "kit-hpos": [benches.uncached_vs_hpos],
    "kit-rdp": [benches.rdp_sync_sweep, benches.rdp_setter_sweep, benches.rdp_atomic_sweep, benches.rdp_rectn,
                fifo_depth, cmd_fetch],
    "kit-span": [span_width],
}

# The noise kit: Thar0/RDP-Noise's rectangle (suites/noise) and variants for rdp-noise.md questions
# 1-4. Each record dumps its surface as #hex lines.
SURF = 0x00500000
CD_NOISE, AD_NOISE = 2 << 6, 2 << 4
AC_DITHER = 3


def prim_combiner():
    return rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4)


def noise_combiner():
    return rcp.set_combine_raw(combiner())


def noise_list(width, siz, x0, x1, mode0, mode1, cc, prim=0, frac=0xFF, blend=None):
    out = [rcp.pipe_sync(), rcp.set_color_image(0, siz, width, SURF), rcp.set_scissor(0, 0, width, 1),
           rcp.set_other_mode(mode0, mode1), cc, rcp.set_prim_color(prim, level_frac=frac)]
    if blend is not None:
        out.append(rcp.set_blend_color(blend))
    return out + [rcp.fill_rectangle(x0, 0, x1, 1), rcp.full_sync()]


B32, B16 = 3, rcp.IM_SIZ_16b
PLAIN = rcp.CD_DISABLE | rcp.AD_DISABLE
NOISE_CASES = [
    # name, surface width, bytes per pixel, lists (each drawn after an idle spin of the given iterations)
    ("rect-1016", 1016, 4, [(0, noise_list(1016, B32, 0, 1016, rcp.CYC_1CYCLE | PLAIN, 0, noise_combiner()))]),
    ("idle-gap", 512, 4, [(0, noise_list(512, B32, 0, 256, rcp.CYC_1CYCLE | PLAIN, 0, noise_combiner())),
                          (100000, noise_list(512, B32, 256, 512, rcp.CYC_1CYCLE | PLAIN, 0, noise_combiner()))]),
    ("two-cycle", 256, 4, [(0, noise_list(256, B32, 0, 256, rcp.CYC_2CYCLE | PLAIN, 0, noise_combiner()))]),
    ("cd-noise-16", 256, 2, [(0, noise_list(256, B16, 0, 256, rcp.CYC_1CYCLE | CD_NOISE | rcp.AD_DISABLE, 0,
                                            prim_combiner(), prim=0x808080FF))]),
    ("ac-dither", 256, 4, [(0, noise_list(256, B32, 0, 256, rcp.CYC_1CYCLE | rcp.CD_DISABLE | AD_NOISE, AC_DITHER,
                                          prim_combiner(), prim=0xFFFFFF80))]),
    ("ad-noise-threshold", 256, 4, [(0, noise_list(256, B32, 0, 256, rcp.CYC_1CYCLE | rcp.CD_DISABLE | AD_NOISE,
                                                   rcp.AC_THRESHOLD, prim_combiner(), prim=0xFFFFFF78,
                                                   blend=0x00000080))]),
]
SPIN_ASM = """
# a0 = {iterations}: an idle CPU spin between two RDP lists.
cal_spin:
    lw $t0, 0($a0)
csp_loop:
    addiu $t0, $t0, -1
    bgtz $t0, csp_loop
    nop
    jr $ra
    nop
"""


@dataclass
class NoiseKit:
    set_name: str = "kit-noise"
    rom_name: str = "kit-noise"
    category: str = "Calib"
    banner_flags: str = "(calib=kit-noise)"
    consts: dict = field(default_factory=lambda: {"DUMP": 0})

    def _lists(self):
        lists = Lists("calnoise")
        cases = [(name, width, bpp, [(spin, lists.get(dl)) for spin, dl in draws])
                 for name, width, bpp, draws in NOISE_CASES]
        return lists, cases

    @property
    def asm(self):
        lists, cases = self._lists()
        names = [f"calnoise_name_{i}: .asciiz {runtime.asm_string(name)}" for i, (name, *_) in enumerate(cases)]
        return [routines.ASM, snapper_asm.ASM, SPIN_ASM, "\n".join([
            f"str_snap: .asciiz {runtime.asm_string('@snap ')}",
            f"str_snap_sep: .asciiz {runtime.asm_string(' ')}",
            f"str_snap_nl: .asciiz {runtime.asm_string(chr(10))}"] + names)] + [lst.asm() for lst in lists.all()]

    def build(self, suite):
        _, cases = self._lists()
        values = []
        for i, (name, width, bpp, draws) in enumerate(cases):
            steps = [fill32(UNCACHED | SURF, width * bpp // 4, 0)]
            for spin, lst in draws:
                if spin:
                    steps.append(Step("cal_spin", [spin]))
                steps += run_sync(lst)
            steps.append(emit(_Record(name, SURF, width * bpp), f"calnoise_name_{i}"))
            values.append(Value(f" [{name}]", steps, []))
        suite.tests.append(Test("RDP noise kit", values))


@dataclass
class _Record:
    id: str
    addr: int
    size: int
    dump: bool = True


def kit_sets(delays):
    sets = []
    for k in delays:
        for name, builders in KITS.items():
            sets.append(BenchKit(name, f"boot-{k}/{name}", builders,
                                 consts={"SCRATCH_BASE": runtime.SCRATCH_BASE, "BOOT_DELAY": k}))
        sets.append(NoiseKit(rom_name=f"boot-{k}/kit-noise", consts={"DUMP": 0, "BOOT_DELAY": k}))
    return sets


SETS = kit_sets(DELAYS)
