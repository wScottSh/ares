"""The bench ROMs: one function per ROM that adds its measurement points to a Suite.

Each point is one Value: a measurement step that leaves COUNT ticks (and any extra counters)
in RES[], then a bench_emit step that prints
"#bench <rom> <point> <constant fields> min=<ticks> max=<ticks> <extra fields>".
COUNT ticks at half the VR4300 PClock (93.75 MHz / 2). The host side (derive.py) turns ticks
into pclk, rclk and rates; expected.tsv holds the cited hardware values.
"""
import struct

from ...suite import Step, Test, Value
from ... import rcp

KSEG0, KSEG1 = 0x80000000, 0xA0000000

# Physical layout. Banks are the 1 MiB RDRAM banks; the runtime owns banks 0-4 (payload,
# framebuffers FB0 at 2 MiB and FB1 at 3 MiB, data and stack).
MEMSET_BUF = 0x00500000      # bank 5, 1 MiB
ROW_BANK = 0x00580000        # bank 5
DMISS_A = 0x00540100         # bank 5
HPOS_ADDR = 0x005A0000       # bank 5 (no VI traffic)
HPOS_VI_ADDR = 0x00280000    # bank 2, the VI front buffer's bank
LIST_BUF = 0x00600000        # bank 6
SP_DMA_BUF = 0x00620000      # bank 6, 2 KiB-row aligned
PI_DMA_BUF = 0x00640000      # bank 6
DRAIN_ADDR = 0x00660000      # bank 6
HPOS_SAMPLES_BUF = 0x00680000
COLOR_IMAGE = 0x00700000     # bank 7, 320x240 RGBA5551

MIB = 1 << 20
VI_OFF = 1
TICK_FIELDS = [("min", 0), ("max", 1)]


def cstr(suite, text):
    data = text.encode("ascii") + b"\0"
    data += b"\0" * (-len(data) % 4)
    return suite.blob(list(struct.unpack(f">{len(data) // 4}I", data)))


def emit_step(suite, rom, point, consts, fields):
    prefix = " ".join([f"#bench {rom} {point}"] + [f"{k}={v}" for k, v in consts])
    params = [cstr(suite, prefix), len(fields)]
    for key, index in fields:
        params += [cstr(suite, key + "="), index]
    return Step("bench_emit", params, 0)


class Rom:
    def __init__(self, suite, name):
        self.suite = suite
        self.name = name
        self.test = Test(name, [])
        suite.tests.append(self.test)

    def point(self, point, kernel, args, consts=(), reps=4, flags=0, extra=(), pre=()):
        steps = list(pre) + [
            Step("bench_run", [kernel, reps, flags, *args], 0),
            emit_step(self.suite, self.name, point, list(consts) + [("reps", reps)],
                      TICK_FIELDS + [(k, 2 + i) for i, k in enumerate(extra)]),
        ]
        self.test.values.append(Value(point, steps, []))


def vi_variants():
    return [("vi-on", 0), ("vi-off", VI_OFF)]


def mi_memset_uncached(suite):
    rom = Rom(suite, "mi-memset-uncached")
    for vi, flags in vi_variants():
        rom.point(vi, "k_memset_sd", [KSEG1 | MEMSET_BUF, MIB],
                  [("bytes", MIB), ("vi", vi[3:])], reps=2, flags=flags)


def mi_memset_cached(suite):
    rom = Rom(suite, "mi-memset-cached")
    for vi, flags in vi_variants():
        rom.point(vi, "k_memset_sd", [KSEG0 | MEMSET_BUF, MIB],
                  [("bytes", MIB), ("vi", vi[3:])], reps=3, flags=flags)


def mi_memset_rspdma(suite):
    rom = Rom(suite, "mi-memset-rspdma")
    for vi, flags in vi_variants():
        rom.point(vi, "k_memset_spdma", [MEMSET_BUF, MIB],
                  [("bytes", MIB), ("vi", vi[3:])], reps=2, flags=flags)


def mi_memset_repeat(suite):
    rom = Rom(suite, "mi-memset-repeat")
    for vi, flags in vi_variants():
        rom.point(vi, "k_memset_repeat", [KSEG1 | MEMSET_BUF, MIB],
                  [("bytes", MIB), ("vi", vi[3:])], reps=2, flags=flags)


SP_BASE = 0xA4040000
SP_SIZES = [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
SP_OFFSETS = [0x000, 0x7C0, 0x7F8]   # row-aligned, 64 B and 8 B before a 2 KiB row end


def sp_dma_sweep(suite):
    rom = Rom(suite, "sp-dma-sweep")
    # Baseline: the same register traffic with a harmless trigger (SP_DRAM_ADDR rewrite).
    rom.point("poll", "k_mmio_dma", [SP_BASE, 0x0, 0, 0x4, SP_DMA_BUF, 0x4, SP_DMA_BUF,
                                     0x18, 1, 0x4, SP_DMA_BUF],
              [("bytes", 0), ("dir", "none"), ("off", 0)])
    for direction, len_reg in (("rd", 0x8), ("wr", 0xC)):
        for off in SP_OFFSETS:
            for size in SP_SIZES:
                rom.point(f"{direction}-{size}-off{off:x}", "k_mmio_dma",
                          [SP_BASE, 0x0, 0, 0x4, SP_DMA_BUF + off, len_reg, size - 1,
                           0x18, 1, 0x4, SP_DMA_BUF],
                          [("bytes", size), ("dir", direction), ("off", off)])


PI_BASE = 0xA4600000
PI_SIZES = [8, 128, 1024, 65536]


def pi_dma_sizes(suite):
    rom = Rom(suite, "pi-dma-sizes")
    # Pads the payload so every DMA reads cartridge bytes that exist (ROM 0x1000 onward).
    suite.blob([0x5A5A5A5A] * (max(PI_SIZES) // 4))
    rom.point("poll", "k_mmio_dma", [PI_BASE, 0x0, PI_DMA_BUF, 0x4, 0x10000000,
                                     0x0, PI_DMA_BUF, 0x10, 3, 0x10, 2],
              [("bytes", 0)])
    for size in PI_SIZES:
        rom.point(f"cart-to-ram-{size}", "k_mmio_dma",
                  [PI_BASE, 0x0, PI_DMA_BUF, 0x4, 0x10000000, 0xC, size - 1, 0x10, 3, 0x10, 2],
                  [("bytes", size)])


HPOS_MAX_SAMPLES = 1536
HPOS_LINES = 3


def uncached_vs_hpos(suite):
    name = "uncached-vs-hpos"
    rom = Rom(suite, name)
    for point, addr, bank in (("bank5", HPOS_ADDR, 5), ("bank2-vi", HPOS_VI_ADDR, 2)):
        header = f"#bench {name} {point} bank={bank} lines={HPOS_LINES}"
        rom.test.values.append(Value(point, [Step("bench_hpos", [
            cstr(suite, header), cstr(suite, f"#bench {name} {point}"), KSEG1 | addr,
            HPOS_MAX_SAMPLES, KSEG0 | HPOS_SAMPLES_BUF, HPOS_LINES], 0)], []))


ROW_TARGETS = [0x8, 0x800, 0x1000, 0x8000, 0x40000]


def dirty_row_sweep(suite):
    rom = Rom(suite, "dirty-row-sweep")
    for prime, is_write in (("clean", 0), ("dirty", 1)):
        for delta in ROW_TARGETS:
            rom.point(f"{prime}-{delta:x}", "k_row",
                      [KSEG1 | ROW_BANK, is_write, KSEG1 | (ROW_BANK + delta)],
                      [("prime", prime), ("delta", delta)], reps=8)


def dirty_miss_isolated(suite):
    rom = Rom(suite, "dirty-miss-isolated")
    a = KSEG0 | DMISS_A
    b, c = a + 0x2000, a + 0x4020
    for victim, kind in (("invalid", 0), ("clean", 1), ("dirty", 2)):
        for gap in (-1, 0, 20, 80):
            label = "single" if gap < 0 else f"gap{gap}"
            rom.point(f"{victim}-{label}", "k_dmiss",
                      [a, kind, gap, b, c, KSEG1 | DRAIN_ADDR],
                      [("victim", victim), ("gap", gap)], reps=8)


# RDP lists run from LIST_BUF; each is prologue + n x body + SYNC_FULL.
RDP_EXTRA = ["clock", "bufbusy", "pipebusy", "tmembusy"]


def rdp_prologue(atomic=False):
    return [rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, 320, COLOR_IMAGE), rcp.set_scissor(0, 0, 320, 240),
            rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4), rcp.set_prim_color(0xFF0000FF),
            rcp.set_other_mode(rcp.CYC_1CYCLE | (rcp.ATOMIC_PRIM if atomic else 0), 0)]


def rdp_point(rom, point, body, n, consts, prologue=None, flags=VI_OFF, reps=4):
    suite = rom.suite
    pro = rcp.words(rdp_prologue() if prologue is None else prologue)
    body_words = rcp.words(body)
    epi = rcp.words([rcp.full_sync()])
    nbytes = 4 * (len(pro) + n * len(body_words) + len(epi))
    build = Step("bench_list_step", [
        suite.blob(pro), len(pro), suite.blob(body_words) if body_words else 0, len(body_words),
        n, suite.blob(epi), len(epi), KSEG1 | LIST_BUF], 0)
    rom.point(point, "k_rdp", [LIST_BUF, nbytes],
              list(consts) + [("n", n), ("vi", "off" if flags & VI_OFF else "on")],
              reps=reps, flags=flags, extra=RDP_EXTRA, pre=[build])


SYNC_KINDS = [("pipe", rcp.pipe_sync()), ("tile", rcp.tile_sync()), ("load", rcp.load_sync())]
SMALL_RECT = rcp.fill_rectangle(0, 0, 8, 1)


def rdp_sync_sweep(suite):
    rom = Rom(suite, "rdp-sync-sweep")
    rdp_point(rom, "none-0", [], 0, [("kind", "none")])
    for kind, sync in SYNC_KINDS:
        for n in (16, 64, 256):
            rdp_point(rom, f"{kind}-{n}", [sync], n, [("kind", kind)])
    for n in (16, 64):
        rdp_point(rom, f"rect-{n}", [SMALL_RECT], n, [("kind", "rect")])
        for kind, sync in SYNC_KINDS:
            rdp_point(rom, f"rect-{kind}-{n}", [SMALL_RECT, sync], n,
                      [("kind", f"rect+{kind}")])


SETTERS = [("nop", rcp.nop()), ("prim-color", rcp.set_prim_color(0x00FF00FF)),
           ("env-color", rcp.set_env_color(0x0000FFFF)),
           ("other-modes", rcp.set_other_mode(rcp.CYC_1CYCLE, 0))]


def rdp_setter_sweep(suite):
    rom = Rom(suite, "rdp-setter-sweep")
    rdp_point(rom, "none-0", [], 0, [("kind", "none")])
    for kind, cmd in SETTERS:
        for n in (256, 1024, 4096):
            rdp_point(rom, f"{kind}-{n}", [cmd], n, [("kind", kind)])


ATOMIC_RECT = rcp.fill_rectangle(16, 16, 32, 20)


def rdp_atomic_sweep(suite):
    rom = Rom(suite, "rdp-atomic-sweep")
    for atomic in (0, 1):
        for n in (1, 16, 64):
            rdp_point(rom, f"atomic{atomic}-{n}", [ATOMIC_RECT], n,
                      [("atomic", atomic), ("rect", "16x4")], prologue=rdp_prologue(bool(atomic)))


def rdp_rectn(suite):
    rom = Rom(suite, "rdp-rectn")
    rdp_point(rom, "rect-320x6", [rcp.fill_rectangle(0, 0, 320, 6)], 1, [("w", 320), ("h", 6)])
    rdp_point(rom, "rect-320x6-x8", [rcp.fill_rectangle(0, 0, 320, 6)], 8, [("w", 320), ("h", 6)])
    rdp_point(rom, "duty-320x240", [rcp.fill_rectangle(0, 0, 320, 240)], 1, [("w", 320), ("h", 240)])


# Ports of n64-systembench @845635c (rasky, no license: its measurement designs are followed and
# its numbers cited, no code copied). Each point runs bench_multi, n64-systembench's TIMEIT_MULTI;
# report.py applies the same averaging and truncation (main.c:105-127, 640-646). The VI is blanked
# throughout, as the original sets VI_CONTROL = 0 before every bench (main.c:623-624).
SB_BUF = 0x005C0000          # bank 5, rambuf (64-byte aligned, main.c:47-48)
SB_LOADS = [(8, "k_sb_lbu"), (16, "k_sb_lhu"), (32, "k_sb_lw"), (64, "k_sb_ld")]
PIF_RAM = 0x1FC007C0
SI_BASE = 0xA4800000


def sb_point(rom, point, kernel, args, reps, unit, consts=(), pre=()):
    steps = list(pre) + [
        Step("bench_multi", [kernel, reps, VI_OFF, *args], 0),
        emit_step(rom.suite, rom.name, point, list(consts) + [("unit", unit), ("reps", reps)],
                  TICK_FIELDS + [("sum", 2)]),
    ]
    rom.test.values.append(Value(point, steps, []))


def sb_cached(rom, bits, kernel):
    """The cached-read baseline the port's harness overhead comes from (main.c:230-248)."""
    sb_point(rom, f"c{bits}", kernel, [KSEG0 | SB_BUF, 1], 50, "pclk", [("bits", bits)])


def uncached_sizes(suite):
    rom = Rom(suite, "uncached-sizes")
    for bits, kernel in SB_LOADS:
        sb_cached(rom, bits, kernel)
        sb_point(rom, f"u{bits}", kernel, [KSEG1 | SB_BUF, 0], 50, "pclk", [("bits", bits)])


def rcp_reg_read(suite):
    rom = Rom(suite, "rcp-reg-read")
    sb_cached(rom, 32, "k_sb_lw")
    sb_point(rom, "vi-control", "k_sb_lw", [0xA4400000, 0], 50, "pclk")


def pif_ram_read(suite):
    rom = Rom(suite, "pif-ram-read")
    sb_cached(rom, 32, "k_sb_lw")
    sb_point(rom, "pif-ram", "k_sb_lw", [KSEG1 | PIF_RAM, 0], 50, "rclk")


def pi_io_write(suite):
    rom = Rom(suite, "pi-io-write")
    sb_point(rom, "rom-word", "k_sb_while", [0, 0, KSEG1 | 0x10000000, 0, PI_BASE + 0x10], 50, "rclk")


def joybus_block(dwords):
    return [w for d in dwords for w in (d >> 32, d & 0xFFFFFFFF)]


def si_dma(suite):
    rom = Rom(suite, "si-dma")
    zero = Step("bench_list_step", [suite.blob([0] * 16), 16, 0, 0, 0, 0, 0, KSEG1 | SB_BUF], 0)
    sb_point(rom, "write64", "k_sb_while", [SI_BASE + 0x0, SB_BUF, SI_BASE + 0x10, PIF_RAM, SI_BASE + 0x18],
             10, "rclk", [("dir", "write64")], pre=[zero])
    for n in range(1, 5):
        block = [0xFF010401FFFFFFFF] * n + [0xFE00000000000000] + [0] * (6 - n) + [1]
        sb_point(rom, f"read64-{n}", "k_sb_joybus", [suite.blob(joybus_block(block)), KSEG1 | SB_BUF, SB_BUF + 64],
                 50, "rclk", [("dir", "read64"), ("commands", n)])


ROMS = {
    "mi-memset-uncached": mi_memset_uncached,
    "mi-memset-cached": mi_memset_cached,
    "mi-memset-rspdma": mi_memset_rspdma,
    "mi-memset-repeat": mi_memset_repeat,
    "sp-dma-sweep": sp_dma_sweep,
    "pi-dma-sizes": pi_dma_sizes,
    "uncached-vs-hpos": uncached_vs_hpos,
    "dirty-row-sweep": dirty_row_sweep,
    "dirty-miss-isolated": dirty_miss_isolated,
    "rdp-sync-sweep": rdp_sync_sweep,
    "rdp-setter-sweep": rdp_setter_sweep,
    "rdp-atomic-sweep": rdp_atomic_sweep,
    "rdp-rectn": rdp_rectn,
    "uncached-sizes": uncached_sizes,
    "rcp-reg-read": rcp_reg_read,
    "pif-ram-read": pif_ram_read,
    "pi-io-write": pi_io_write,
    "si-dma": si_dma,
}
