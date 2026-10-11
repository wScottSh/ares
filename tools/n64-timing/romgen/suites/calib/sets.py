"""The calibration kit ROMs (docs/calibration/hardware-run.md, tools/n64-timing/calibration/).

Each kit ROM combines bench ROMs (suites/bench/benches.py) with the kit's own points, so one
flashcart load measures many questions. build.py always builds this suite with --hw (hwout.py).
Every line is "#bench <rom> <point> key=value ...", the bench format, so suites/bench/report.py
derive() reads kit and bench output alike. `N64_CALIB_DELAYS=K,K,...` sets the boot delays of the
fork's builds (calibration/run.sh walks phase as the bench does); the console build is boot-1.
`N64_CALIB_PADS=P,P,...` sets the layout pads run.sh builds every kit ROM at (build.py --layout-pad).
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
from . import asm, blockslope, bus, cpu2, opslope, repeat, rspdma, tex, vilb, zmem

DELAYS = [int(k) for k in os.environ.get("N64_CALIB_DELAYS", "1,165,329,493,657,821,985,1149").split(",")]
#One 32 B I-cache line of pads, as the bench walks (suites/bench/phases.py PADS).
PADS = [int(p) for p in os.environ.get("N64_CALIB_PADS", "0,1,2,3,4,5,6,7").split(",")]
CAL_BUF = 0x005D0000       # bank 5, clear of the bench buffers (SB_BUF 0x5C0000, HPOS 0x5A0000)


def dcb(suite):
    rom = Rom(suite, "dcb")
    for name in asm.DCB:
        rom.point(name[6:].replace("_", "-"), name, [KSEG0 | CAL_BUF], [("pairs", asm.UNROLL)], reps=8)


def wb_stores(suite, name="wb-stores"):
    rom = Rom(suite, name)
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


def ifill(suite, name="ifill"):
    rom = Rom(suite, name)
    for name, cold in (("warm", 0), ("cold", 1)):
        rom.point(name, "k_ifill", [cold], [("cold", cold)], reps=8)


VI_DELAYS = [1, 10, 100, 300, 1000, 1314, 2000, 3000, 10000, 100000]


def vi_enable(suite):
    rom = Rom(suite, "vi-enable")
    for d in VI_DELAYS:
        rom.point(f"delay-{d}", "k_vi_enable", [d], [("delay", d)], reps=4,
                  extra=["v_at_enable", "first_ticks", "v_after", "line_ticks"])


VI_MID_LINE = 0x100  # V_CURRENT half-line 256: output line 128, inside vi_init's V_VIDEO 0x25..0x1FF


def vi_mid_field(suite):
    rom = Rom(suite, "vi-mid-field")
    for d in VI_DELAYS:
        rom.point(f"delay-{d}", "k_vi_enable_mid", [d, VI_MID_LINE], [("delay", d), ("line", VI_MID_LINE)], reps=4,
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
    cmd_fetch_frozen(suite, rom)


FETCH_SPINS = range(16)


def cmd_fetch_frozen(suite, rom):
    """The command FIFO filling behind a frozen RDP: DPC_CURRENT can only stop at a burst boundary
    there, so the offsets a poll sees are multiples of the burst whatever the poll's cadence
    (calibration/kit.py derive: burst_gcd). The spins move the first poll by about 3 pclk each, over
    more than one 35 pclk poll period."""
    words = rcp.words([rcp.nop()] * 512 + [rcp.full_sync()])
    build = Step("bench_list_step", [suite.blob(words), len(words), 0, 0, 0, 0, 0, KSEG1 | LIST_BUF], 0)
    for spin in FETCH_SPINS:
        rom.point(f"frozen-s{spin}", "k_fetch_frozen", [LIST_BUF, 4 * len(words), spin], [("spin", spin)], reps=4,
                  flags=benches.VI_OFF, extra=["seen", "first", "last"], pre=[build] if spin == 0 else [])


def sp_dma_chain(suite):
    """sp-dma-sweep's DMAs queued back to back through SP_DMA_FULL, max(16, 4096 / size) of them, timed
    to SP_DMA_BUSY clear: the 26 pclk quantum of the busy poll that ends sp-dma-sweep's single DMA
    (verify-63c) falls on the whole chain, so per DMA it is 26 / n pclk."""
    rom = Rom(suite, "sp-dma-chain")
    for direction, len_reg in (("rd", 0x8), ("wr", 0xC)):
        for off in benches.SP_OFFSETS:
            for size in benches.SP_SIZES:
                n = max(16, 4096 // size)
                rom.point(f"{direction}-{size}-off{off:x}", "k_sp_chain",
                          [benches.SP_BASE + len_reg, size - 1, benches.SP_DMA_BUF + off, n],
                          [("bytes", size), ("dir", direction), ("off", off), ("dmas", n)])


def bus_reads(suite):
    """A cartridge domain-2 read: the SRAM the kit logs to, under hw_init's DOM2 timing (legacy.pi.cart-read
    charges 250 pclk)."""
    rom = Rom(suite, "bus-reads")
    benches.sb_cached(rom, 32, "k_sb_lw")
    benches.sb_point(rom, "dom2-sram-word", "k_sb_lw", [KSEG1 | 0x08000000, 0], 50, "rclk")


PI_ROW_ENDS = [0x7F8, 0x7FC, 0x7C0]
PI_ROW_CROSSES = [(16, 0x7F2), (19, 0x7F2), (26, 0x7F4), (12, 0x7FA), (39, 0x7F8), (24, 0x7EE)]


def pi_dma_rowend(suite):
    """pi-dma-sizes' DMAs into RDRAM 8 B, 4 B and 64 B before a 2 KiB row end, so the first block ends at
    the row (followups: PI first block ending at a row end). At 4 B the first block holds no more bytes
    than its misalignment, so the rule posts an empty-mask write (pi.first-block-empty-write).
    PI_ROW_CROSSES are the worst n64_pi_dma_test points (pidma:logs): small DMAs whose non-empty first
    block is clipped at the row and whose rest crosses it (prehw-plan U-PIROW-CROSS)."""
    rom = Rom(suite, "pi-dma-rowend")
    pi = benches.PI_BASE
    points = [(size, off) for off in PI_ROW_ENDS for size in (8, 128, 1024)] + PI_ROW_CROSSES
    for size, off in points:
        benches.sb_while(rom, f"cart-to-ram-{size}-off{off:x}",
                         [(pi + 0x0, benches.PI_DMA_BUF + off), (pi + 0x4, 0x10000000)], (pi + 0xC, size - 1),
                         pi + 0x10, 10, [("bytes", size), ("off", off)])


STATUS_FRAME = [0xFF010300FFFFFFFF] * 4 + [0xFE00000000000000] + [0] * 2 + [1]


def joybus_setup(suite):
    """Which controller ports answer a status command and which report an accessory: ingestion
    compares an SI capture with the fork run that had the same pads (calibration/run.sh pads-4)."""
    rom = Rom(suite, "joybus-setup")
    rom.point("status-4", "k_sb_joybus", [suite.blob(benches.joybus_block(STATUS_FRAME)), KSEG1 | benches.SB_BUF,
                                          benches.SB_BUF + 64], [("commands", 4)], reps=1, flags=benches.VI_OFF)
    rom.point("pads", "k_pads", [KSEG1 | (benches.SB_BUF + 64)], reps=1, extra=["mask", "paks"])


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


#kit-span2 (calibration/derived.py span2). Each line of the color image is one 2 KiB RDRAM row
#(ri.row-of), so every line of a rectangle meets memory alike and no span crosses a row.
SPAN2_ROW_PX = {32: 512, 16: 1024}
SPAN2_LINES = 256
SPAN2_WRITE_WIDTHS = list(range(1, 81)) + [160, 320]
SPAN2_IMRD_WIDTHS = [1, 8, 16, 32, 64, 128, 160, 192, 256, 320]


def span2_prologue(bpp, mode1):
    siz = IM_SIZ_32b if bpp == 32 else rcp.IM_SIZ_16b
    return [rcp.set_color_image(rcp.IM_FMT_RGBA, siz, SPAN2_ROW_PX[bpp], COLOR_IMAGE),
            rcp.set_scissor(0, 0, 320, SPAN2_LINES), rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4),
            rcp.set_prim_color(0xFF0000FF), rcp.set_other_mode(rcp.CYC_1CYCLE, mode1)]


def span_write(suite):
    """Write-only 1-cycle rectangles (no IM_RD, no Z) at every width 1-80 px, 160 and 320: the width
    spacing of DPC_CLOCK's steps shows when a span RAM half is released for reuse
    (item:16.span-write-release)."""
    rom = Rom(suite, "span-write")
    for bpp in (32, 16):
        for w in SPAN2_WRITE_WIDTHS:
            rdp_point(rom, f"b{bpp}-w{w}", [rcp.fill_rectangle(0, 0, w, SPAN2_LINES)], 1,
                      [("bpp", bpp), ("w", w), ("h", SPAN2_LINES)], prologue=span2_prologue(bpp, 0))


def span_imrd(suite):
    """span_write's 32 bpp rectangles with IM_RD, out to 320 px: the steady cost per 64 B half against
    the RI wire time (item:16.mem-overhead-pipelined)."""
    rom = Rom(suite, "span-imrd")
    for w in SPAN2_IMRD_WIDTHS:
        rdp_point(rom, f"b32-w{w}", [rcp.fill_rectangle(0, 0, w, SPAN2_LINES)], 1,
                  [("bpp", 32), ("w", w), ("h", SPAN2_LINES)], prologue=span2_prologue(32, rcp.IM_RD))


SPAN_COST_REPLAYS = (16, 64)


def span_cost(suite):
    """span_write's 1 px rectangle at 16 bpp, MM's color depth, with every pixel failing alpha compare
    (PRIMITIVE alpha 0 under a blend alpha threshold of 0xFF), replayed N = 16 and 64 times: 256 one-pixel
    1-cycle spans per rectangle that write nothing, the compute-only shape Thar0's alpha all-fail
    rectangles have. DPC_CLOCK per added rectangle moves 256 times any per-span cost; a written 1 px
    span would hide it behind its write (rdp.span-line-gap, prehw-plan.md U-SCT-SPAN, mm:south-clock-town)."""
    rom = Rom(suite, "span-cost")
    prologue = [*span2_prologue(16, rcp.AC_THRESHOLD)[:3], rcp.set_prim_color(0xFF000000),
                rcp.set_blend_color(rcp.rgba8(0, 0, 0, 0xFF)), rcp.set_other_mode(rcp.CYC_1CYCLE, rcp.AC_THRESHOLD)]
    for n in SPAN_COST_REPLAYS:
        rdp_point(rom, f"acfail-n{n}", [rcp.fill_rectangle(0, 0, 1, SPAN2_LINES)], n,
                  [("bpp", 16), ("w", 1), ("h", SPAN2_LINES), ("ac", "fail")], prologue=prologue)


@dataclass
class BenchKit:
    """A kit ROM built from bench builders and the kit's own; one per boot delay."""
    set_name: str
    rom_name: str
    builders: list
    extra_asm: list = field(default_factory=list)
    category: str = "Calib"
    consts: dict = field(default_factory=dict)

    @property
    def banner_flags(self):
        return f"(calib={self.set_name})"

    @property
    def asm(self):
        return [bench_asm.ASM, asm.ASM] + self.extra_asm

    def build(self, suite):
        for b in self.builders:
            b(suite)


KITS = {
    "kit-cpu": [benches.uncached_sizes, benches.rcp_reg_read, benches.pif_ram_read, benches.pi_io_read,
                benches.pi_io_write, benches.si_io_write, benches.dirty_row_sweep, benches.dirty_miss_isolated,
                dcb, wb_stores, reg_write, ifill, bus_reads, *opslope.BUILDERS],
    "kit-vi": [vi_enable, count_fields, vi_mid_field],
    "kit-dma": [benches.mi_memset_uncached, benches.mi_memset_cached, benches.mi_memset_rspdma,
                benches.mi_memset_repeat, benches.sp_dma_sweep, benches.pi_dma_sizes, benches.si_dma, joybus_setup, sp_dma_chain, pi_dma_rowend,
                *rspdma.BUILDERS, *repeat.BUILDERS, *blockslope.BUILDERS],
    "kit-hpos": [benches.uncached_vs_hpos],
    "kit-rdp": [benches.rdp_sync_sweep, benches.rdp_setter_sweep, benches.rdp_atomic_sweep, benches.rdp_rectn,
                fifo_depth, cmd_fetch],
    "kit-span": [span_width],
    "kit-span2": [span_write, span_imrd, span_cost],
    "kit-tex": tex.BUILDERS,
    "kit-zmem": zmem.BUILDERS,
    "kit-zread": [zmem.reads_1cycle],
    "kit-cpu2": cpu2.BUILDERS,
    "kit-bus": bus.BUILDERS,
    "kit-vilb": vilb.BUILDERS,
}
KIT_ASM = {"kit-cpu": [opslope.ASM], "kit-tex": [tex.ASM], "kit-zmem": [zmem.ASM], "kit-zread": [zmem.ASM], "kit-cpu2": [cpu2.ASM],
           "kit-bus": [bus.ASM], "kit-vi": [asm.VI_MID_ASM], "kit-dma": [rspdma.ASM, repeat.ASM, blockslope.ASM],
           "kit-vilb": [vilb.ASM]}

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
    ("im-rd-stall", 256, 4, [(0, noise_list(256, B32, 0, 256, rcp.CYC_1CYCLE | PLAIN, rcp.IM_RD, noise_combiner()))]),
    ("ad-noise-threshold", 256, 4, [(0, noise_list(256, B32, 0, 256, rcp.CYC_1CYCLE | rcp.CD_DISABLE | AD_NOISE,
                                                   rcp.AC_THRESHOLD, prim_combiner(), prim=0xFFFFFF78,
                                                   blend=0x00000080))]),
    # alpha 0x7F + AD >= blend 0x80 iff AD != 0: Angrylion's 0-7 drops a pixel, MiSTer's odd 1-7 never does
    # (rdp-noise.md:39). 512 px at 16 bpp is the most pixels whose dump keeps the log inside the 32 KiB SRAM.
    ("ad-noise-7f", 512, 2, [(0, noise_list(512, B16, 0, 512, rcp.CYC_1CYCLE | rcp.CD_DISABLE | AD_NOISE,
                                            rcp.AC_THRESHOLD, prim_combiner(), prim=0xFFFFFF7F, blend=0x00000080))]),
]
#kit-noise2 (prehw-plan.md U-NOISE-KIT2), for the G_CD_NOISE and G_AC_DITHER bits. kit-noise keeps its own draws,
#since one moved or removed draw would move the offset set fixed for ad-noise-7f. Gray 0x84 has low bits 4,
#so a channel rounds up iff its dither value is below 4: one bit per channel per pixel. The anchor and
#ac-dither are kit-noise's draws, copied.
NOISE2_CASES = [
    NOISE_CASES[0],
    ("cd-noise-84", 512, 2, [(0, noise_list(512, B16, 0, 512, rcp.CYC_1CYCLE | CD_NOISE | rcp.AD_DISABLE, 0,
                                            prim_combiner(), prim=0x848484FF))]),
    next(case for case in NOISE_CASES if case[0] == "ac-dither"),
]
NOISE_KITS = {"kit-noise": NOISE_CASES, "kit-noise2": NOISE2_CASES}
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
                 for name, width, bpp, draws in NOISE_KITS[self.set_name]]
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
            if not builders:
                continue
            sets.append(BenchKit(name, f"boot-{k}/{name}", builders, KIT_ASM.get(name, []),
                                 consts={"SCRATCH_BASE": runtime.SCRATCH_BASE, "BOOT_DELAY": k}))
        sets += [NoiseKit(set_name=kit, rom_name=f"boot-{k}/{kit}", banner_flags=f"(calib={kit})",
                          consts={"DUMP": 0, "BOOT_DELAY": k}) for kit in NOISE_KITS]
    return sets


SETS = kit_sets(DELAYS)
