"""Kit points for the zmem kit ROM (sets.py KITS["kit-zmem"]): the RDP's memory side. Write-back
granularity under Z rejection (rdp-write-granularity.md), 1PRIMITIVE cost under memory traffic (#19),
color and Z prefetch slots (#20), the IM_RD clobber test (#17), X-bus command fetch, END appended to a
running list, per-type triangle setup and PIPEBUSY under memory stalls (#16).

Every point runs zmem_k: it clears a color region and writes a Z comb, runs one list, and reports
DPC_CLOCK, BUFBUSY and PIPEBUSY with an FNV-1a hash of the region's pixels and a count of pixels of
one color, so content compares exactly beside time.

Buffers: the color image at COLOR_IMAGE (bank 7, benches.py), the Z image at ZBUF (bank 5), the list
at LIST_BUF (bank 6) or at DMEM 0 for X-bus fetches.
"""
from dataclasses import dataclass

from ... import rcp
from ...suite import Step
from ..bench.benches import KSEG1, LIST_BUF, COLOR_IMAGE, VI_OFF, Rom

ZBUF = 0x00540000
DMEM = 0xA4000000
WIDTH = 320
PLAIN = rcp.CYC_1CYCLE | rcp.CD_DISABLE | rcp.AD_DISABLE
NEAR, FAR = rcp.zdz(0, 0), rcp.zdz(rcp.MAXFBZ, 0)
PRIM_Z = 0x4000
RED, GREEN = rcp.rgba8(255, 0, 0, 255), rcp.rgba8(0, 255, 0, 255)
RGB_MASK = 0xFFFE
FORCE_BL = 1 << 14
BLEND_MIX = (1 << 22) | (1 << 20)     # cycles 0 and 1: P*A + M*(1-A), m2a = memory (as rdpstat/stale.py)
TIMEOUT = 100 * rcp.COUNT_PER_MS
EXTRA = ["clock", "bufbusy", "pipebusy", "hash", "count"]


def c5551(rgba):
    return rcp.rgba5551(rgba >> 24, (rgba >> 16) & 0xFF, (rgba >> 8) & 0xFF, rgba & 0xFF) & RGB_MASK


@dataclass
class Region:
    """Rows [y, y + rows) of the 320 px color image: cleared before the list, hashed and counted after."""
    y: int
    rows: int
    color: int = RED

    def args(self):
        addr = KSEG1 | (COLOR_IMAGE + 2 * WIDTH * self.y)
        return [addr, WIDTH * self.rows // 2, 0], [addr, WIDTH * self.rows, RGB_MASK, c5551(self.color)]


@dataclass
class Comb:
    """Z rows [y, y + rows): `near` for n pixels, then `far` for n, from x = 0 on each row. n = 0 fills
    the rows with `near` alone."""
    y: int
    rows: int
    n: int
    near: int = NEAR
    far: int = FAR

    def args(self):
        return [KSEG1 | (ZBUF + 2 * WIDTH * self.y), self.rows, WIDTH, self.n, self.near, self.far]


NO_COMB = [0, 0, 0, 0, 0, 0]


def prologue(mode0=PLAIN, mode1=0, prim=RED, extra=()):
    return [rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, WIDTH, COLOR_IMAGE),
            rcp.set_depth_image(ZBUF), rcp.set_scissor(0, 0, WIDTH, 240),
            rcp.set_combine_lerp(*["0", "0", "0", "PRIMITIVE"] * 4), rcp.set_prim_color(prim),
            rcp.set_prim_depth(PRIM_Z, 0), rcp.set_other_mode(mode0, mode1), *extra]


def zpoint(rom, point, consts, pro, body, n, region, comb=None, epilogue=(rcp.full_sync(),), xbus=False,
           split=False, delay=0, flags=VI_OFF, reps=4):
    """One zmem_k point: pro + n x body + epilogue at LIST_BUF (DMEM 0 when xbus). split: END first
    stops before the epilogue and moves past it `delay` COUNT ticks later."""
    suite = rom.suite
    pro, body, epi = rcp.words(pro), rcp.words(body), rcp.words(list(epilogue))
    head = 4 * (len(pro) + n * len(body))
    nbytes = head + 4 * len(epi)
    assert not xbus or nbytes <= 0x1000
    build = Step("bench_list_step", [suite.blob(pro) if pro else 0, len(pro), suite.blob(body) if body else 0,
                                     len(body), n, suite.blob(epi), len(epi), DMEM if xbus else KSEG1 | LIST_BUF], 0)
    clear, count = region.args()
    args = [0 if xbus else LIST_BUF, nbytes, rcp.SET_XBUS if xbus else rcp.CLEAR_XBUS, head if split else 0, delay,
            *clear, *(comb.args() if comb else NO_COMB), *count]
    rom.point(point, "zmem_k", args, list(consts) + [("n", n), ("vi", "off" if flags & VI_OFF else "on")],
              reps=reps, flags=flags, extra=EXTRA, pre=[build])


COMB_N = [1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32]
COMB_ROWS = 8


def write_granularity(suite):
    """A 320 x 8 Z-compared rectangle over a Z comb of period 2N (rdp-write-granularity.md test 1).
    Written runs per row are 320 / 2N: per-run write-back costs grow as 1/N, one masked burst per span
    is flat in N, one write per written octbyte (4 px at 16 bpp) is flat below N = 4 and halves above.
    all-fail (every pixel rejected) against all-pass and against no-rect says whether a fully
    rejected span writes."""
    rom = Rom(suite, "zmem-write-gran")
    region = Region(0, COMB_ROWS)
    rect = [rcp.fill_rectangle(0, 0, WIDTH, COMB_ROWS)]
    for upd in (0, 1):
        pro = prologue(mode1=rcp.ZS_PRIM | rcp.Z_CMP | (rcp.Z_UPD if upd else 0))
        tag = "zcmp-zupd" if upd else "zcmp"
        for n in COMB_N:
            zpoint(rom, f"{tag}-comb{n}", [("z", tag), ("comb", n)], pro, rect, 1, region, Comb(0, COMB_ROWS, n))
        zpoint(rom, f"{tag}-all-pass", [("z", tag), ("comb", "pass")], pro, rect, 1, region,
               Comb(0, COMB_ROWS, 0, near=FAR))
        zpoint(rom, f"{tag}-all-fail", [("z", tag), ("comb", "fail")], pro, rect, 1, region,
               Comb(0, COMB_ROWS, 0, near=NEAR))
    zpoint(rom, "no-rect", [("z", "none"), ("comb", "none")], prologue(mode1=rcp.ZS_PRIM | rcp.Z_CMP), [], 0,
           region, Comb(0, COMB_ROWS, 0, near=FAR))


ATOMIC_RECT = rcp.fill_rectangle(16, 16, 32, 20)
ATOMIC_MODES = [("plain", 0), ("zcmp-zupd", rcp.ZS_PRIM | rcp.Z_CMP | rcp.Z_UPD), ("imrd", rcp.IM_RD)]


def atomic_traffic(suite):
    """N overlapping 16x4 rectangles, 1PRIMITIVE off and on, with no memory reads, with Z read and
    write, and with IM_RD (#19). Per added rectangle, on minus off is the 1PRIMITIVE cost under each
    traffic; a fixed rdp.atomic-dead keeps it flat across modes, a wait for the last write-back grows
    it with the bytes in flight."""
    rom = Rom(suite, "zmem-atomic")
    region = Region(16, 4)
    for name, mode1 in ATOMIC_MODES:
        for atomic in (0, 1):
            pro = prologue(mode0=PLAIN | (rcp.ATOMIC_PRIM if atomic else 0), mode1=mode1)
            for n in (16, 64):
                zpoint(rom, f"{name}-atomic{atomic}-{n}", [("mode", name), ("atomic", atomic)], pro,
                       [ATOMIC_RECT], n, region, Comb(16, 4, 0, near=FAR))


SLOT_WIDTHS = [8, 16, 24, 32, 48, 64, 96, 128, 192, 320]
SLOT_MODES = [("plain", 0), ("imrd", rcp.IM_RD), ("zcmp", rcp.ZS_PRIM | rcp.Z_CMP),
              ("imrd-zcmp", rcp.IM_RD | rcp.ZS_PRIM | rcp.Z_CMP)]


def span_slots(suite):
    """8-line rectangles against width with color reads only, Z reads only, and both (#20). Z passes
    everywhere and is not updated, so every mode writes the same color pixels. If the two prefetch
    streams share the span slots, both costs add (imrd-zcmp - plain = (imrd - plain) + (zcmp - plain));
    if they overlap, both is near the larger of the two."""
    rom = Rom(suite, "zmem-slots")
    region = Region(0, 8)
    for name, mode1 in SLOT_MODES:
        pro = prologue(mode1=mode1)
        for w in SLOT_WIDTHS:
            zpoint(rom, f"{name}-w{w}", [("mode", name), ("w", w), ("h", 8)], pro,
                   [rcp.fill_rectangle(0, 0, w, 8)], 1, region, Comb(0, 8, 0, near=FAR))


#Triangle words (n64brew Reality Display Processor/Commands, Triangle; the layout snapper/tri.py
#emits): word 0 = command, lft (bit 55), YL, YM, YH in s11.2; then XL/DxLDy, XH/DxHDy, XM/DxMDy in
#s15.16. Shade adds 8 dwords and Z 2 dwords after the edges (shade before Z); a flat triangle has
#zero slopes, so its shade dwords carry only the RGBA integer parts in dword 0.
TRI_FILL, TRI_Z, TRI_SHADE, TRI_SHADE_Z = 0x08, 0x09, 0x0C, 0x0D


def triangle(cmd, x0, y0, x1, y1, shade_rgba=0):
    """A flat triangle covering [x0, x1) x [y0, y1) as one left-major trapezoid: H is the left edge,
    M the right, YM = YL."""
    hi = cmd << 24 | 1 << 23 | (4 * y1 & 0x3FFF)
    lo = (4 * y1 & 0x3FFF) << 16 | (4 * y0 & 0x3FFF)
    out = [hi << 32 | lo, (x1 << 16) << 32, (x0 << 16) << 32, (x1 << 16) << 32]
    if cmd & 0x4:
        r, g, b, a = shade_rgba >> 24, (shade_rgba >> 16) & 0xFF, (shade_rgba >> 8) & 0xFF, shade_rgba & 0xFF
        out += [r << 48 | g << 32 | b << 16 | a] + [0] * 7
    if cmd & 0x1:
        out += [0, 0]
    return out


def triangle_setup(suite):
    """N 1-pixel triangles of each type (#16 sub-item): DPC_CLOCK per added triangle is the setup
    cost of that type. The fork costs every primitive rdp.primitive-base; a console that charges the
    shade or Z coefficients separates the types."""
    rom = Rom(suite, "zmem-tri")
    region = Region(9, 3)
    pro = prologue()
    for name, cmd in (("fill", TRI_FILL), ("z", TRI_Z), ("shade", TRI_SHADE), ("shade-z", TRI_SHADE_Z)):
        for n in (16, 64):
            zpoint(rom, f"{name}-{n}", [("tri", name), ("cmd", f"{cmd:#04x}")], pro, triangle(cmd, 10, 10, 11, 11),
                   n, region)


def comb_shade():
    """1-cycle combiner: color = PRIMITIVE, alpha = SHADE (rdp.h G_CCMUX_PRIMITIVE 3, G_ACMUX_SHADE 4;
    zero is 15 / 15 / 31 / 7 for the color A, B, C, D inputs and 7 for the alpha inputs)."""
    hi = 15 << 20 | 31 << 15 | 7 << 12 | 7 << 9 | 15 << 5 | 31
    lo = 15 << 28 | 15 << 24 | 7 << 21 | 7 << 18 | 3 << 15 | 7 << 12 | 4 << 9 | 3 << 6 | 7 << 3 | 4
    return rcp.set_combine_raw(hi << 32 | lo)


CLOBBER_ROW = 100


def clobber(suite):
    """Two overlapping one-row triangles, IM_RD on, no sync between (#17; rdp-write-granularity.md
    test 3). reject: the second has shade alpha 0 under alpha compare (blend alpha 0x80), so every
    pixel of it is rejected; count is the first one's red pixels left. A stale span-buffer block
    written back clears them, a masked or per-run write-back keeps all w. blend: the second blends
    50% over memory; its hash equals blend-atomic (coherent read) or blend-only (read the cleared
    row), which says whether the second span read stale memory."""
    rom = Rom(suite, "zmem-clobber")
    region = Region(CLOBBER_ROW, 1)
    y0, y1 = CLOBBER_ROW, CLOBBER_ROW + 1
    for w in (8, 64):
        x0, x1 = 16, 16 + w
        first = triangle(TRI_SHADE, x0, y0, x1, y1, shade_rgba=0x000000FF)
        for atomic in (0, 1):
            mode0 = PLAIN | (rcp.ATOMIC_PRIM if atomic else 0)
            pro = prologue(mode0, rcp.IM_RD | rcp.AC_THRESHOLD, extra=[comb_shade(), rcp.set_blend_color(0x80)])
            zpoint(rom, f"reject-w{w}-atomic{atomic}", [("case", "reject"), ("w", w), ("atomic", atomic)], pro,
                   first + triangle(TRI_SHADE, x0, y0, x1, y1, shade_rgba=0), 1, region)
        second = triangle(TRI_SHADE, x0, y0, x1, y1, shade_rgba=0x00000080)
        for case, atomic, body in (("blend", 0, first + second), ("blend-atomic", 1, first + second),
                                   ("blend-only", 1, second)):
            mode0 = PLAIN | (rcp.ATOMIC_PRIM if atomic else 0)
            pro = prologue(mode0, rcp.IM_RD | FORCE_BL | BLEND_MIX, extra=[comb_shade()])
            zpoint(rom, f"{case}-w{w}", [("case", case), ("w", w), ("atomic", atomic)], pro, body, 1, region)


def xbus_fetch(suite):
    """One command list fetched over the X bus from DMEM and over RDRAM (rdp.xbus-fetch-rate,
    rdpstat:xbus): per added NOP the fetch rate dominates; small rectangles add their execution."""
    rom = Rom(suite, "zmem-xbus")
    region = Region(0, 1)
    for name, pro, body, counts in (("nop", [], [rcp.nop()], (64, 448)),
                                    ("rect", prologue(), [rcp.fill_rectangle(0, 0, 8, 1)], (16, 128))):
        for src, xbus in (("rdram", False), ("dmem", True)):
            for n in counts:
                zpoint(rom, f"{name}-{src}-{n}", [("list", name), ("src", src)], pro, body, n, region, xbus=xbus)


HOLD_DELAYS = [0, 50, 1000, 3000, 3800, 3900, 3950, 4000, 4050, 4100, 6000]


def hold(suite):
    """A 320x16 rectangle combining PRIMITIVE (red), then a Set Combine selecting ENVIRONMENT (green)
    with no sync, then Sync Full (followups: "Hold sees only commands already in the FIFO";
    rdpstat/unsynced.py: the combiner row recolors the last 24 1-cycle pixels). whole submits it in
    one END; append-d moves END past the setter d COUNT ticks after the first END. count is the green
    pixels: a setter that reaches the command processor while the rectangle runs recolors its tail
    as in whole; one the hold never sees leaves 0."""
    rom = Rom(suite, "zmem-hold")
    region = Region(0, 16, GREEN)
    pro = prologue(extra=[rcp.set_env_color(GREEN)]) + [rcp.fill_rectangle(0, 0, WIDTH, 16)]
    tail = (rcp.set_combine_lerp(*["0", "0", "0", "ENVIRONMENT"] * 4), rcp.full_sync())
    zpoint(rom, "whole", [("submit", "whole")], pro, [], 0, region, epilogue=tail)
    for d in HOLD_DELAYS:
        zpoint(rom, f"append-{d}", [("submit", "append"), ("delay", d)], pro, [], 0, region, epilogue=tail,
               split=True, delay=d)


PIPE_MODES = [("plain", 0), ("imrd", rcp.IM_RD), ("imrd-zcmp-zupd", rcp.IM_RD | rcp.ZS_PRIM | rcp.Z_CMP | rcp.Z_UPD)]


def pipebusy_stall(suite):
    """A 320x48 rectangle with VI scanout on and off (#16: does PIPEBUSY count memory stalls?). The VI
    lengthens DPC_CLOCK by its memory stalls; PIPEBUSY moves with it if it counts them and stays at
    the VI-off value if it counts only pipeline work."""
    rom = Rom(suite, "zmem-pipebusy")
    region = Region(0, 48)
    for name, mode1 in PIPE_MODES:
        for vi, flags in (("off", VI_OFF), ("on", 0)):
            zpoint(rom, f"{name}-vi{vi}", [("mode", name)], prologue(mode1=mode1),
                   [rcp.fill_rectangle(0, 0, WIDTH, 48)], 1, region, Comb(0, 48, 0, near=FAR), flags=flags)


BUILDERS = [write_granularity, atomic_traffic, span_slots, triangle_setup, clobber, xbus_fetch, hold,
            pipebusy_stall]

ASM = f"""
# args = {{list phys (DMEM offset for the X bus), list bytes, DPC_STATUS X-bus bit, split bytes (0 = whole),
# delay ticks, clear dst, clear words, clear value, Z dst (0 = none), Z rows, Z cols, comb N, near, far,
# region, region halfwords, count mask, count value}}. Clears the color region, writes the Z comb, clears
# the DPC counters, runs the list (END at split, then at the end `delay` ticks after the first END), waits
# up to {TIMEOUT} ticks for the DP interrupt, then hashes the region. RES[2..6] = DPC_CLOCK, BUFBUSY,
# PIPEBUSY, FNV-1a over the region's halfwords, halfwords whose (value & mask) = count value. v0 = ticks.
zmem_k:
    lw $t0, 20($a0)
    beqz $t0, zmem_noclear
    lw $t1, 24($a0)
    lw $t2, 28($a0)
zmem_clear:
    sw $t2, 0($t0)
    addiu $t1, $t1, -1
    bnez $t1, zmem_clear
    addiu $t0, $t0, 4
zmem_noclear:
    lw $t0, 32($a0)
    beqz $t0, zmem_noz
    lw $t1, 36($a0)
zmem_zrow:
    lw $t2, 40($a0)
    lw $t3, 44($a0)
    move $t4, $t3
    lw $t5, 48($a0)
    lw $t6, 52($a0)
zmem_zcol:
    sh $t5, 0($t0)
    beqz $t3, zmem_znext
    addiu $t0, $t0, 2
    addiu $t4, $t4, -1
    bnez $t4, zmem_znext
    move $t7, $t5
    move $t5, $t6
    move $t6, $t7
    move $t4, $t3
zmem_znext:
    addiu $t2, $t2, -1
    bnez $t2, zmem_zcol
    nop
    addiu $t1, $t1, -1
    bnez $t1, zmem_zrow
    nop
zmem_noz:
    li $t0, 0xA4100000
    lw $t1, 8($a0)
    ori $t1, $t1, 0x3C0
    sw $t1, 0xC($t0)
    lw $t2, 0($a0)
    lw $t3, 4($a0)
    addu $t3, $t2, $t3
    lw $t4, 12($a0)
    sw $t2, 0($t0)
    lw $t9, 0xC($t0)
    li $t6, 0xA4300000
    mfc0 $t5, $count
    beqz $t4, zmem_whole
    addu $t4, $t2, $t4
    sw $t4, 4($t0)
    lw $t7, 16($a0)
zmem_delay:
    mfc0 $t8, $count
    subu $t8, $t8, $t5
    sltu $t8, $t8, $t7
    bnez $t8, zmem_delay
    nop
zmem_whole:
    sw $t3, 4($t0)
    li $t7, {TIMEOUT}
zmem_wait:
    lw $t8, 8($t6)
    andi $t8, $t8, 0x20
    bnez $t8, zmem_done
    nop
    mfc0 $t8, $count
    subu $t8, $t8, $t5
    sltu $t8, $t8, $t7
    bnez $t8, zmem_wait
    nop
zmem_done:
    mfc0 $t8, $count
    subu $v0, $t8, $t5
    lw $t7, 0x10($t0)
    sw $t7, 0($a1)
    lw $t7, 0x14($t0)
    sw $t7, 4($a1)
    lw $t7, 0x18($t0)
    sw $t7, 8($a1)
    li $t7, 0x800
    sw $t7, 0($t6)
    lw $t0, 56($a0)
    lw $t3, 60($a0)
    lw $t4, 64($a0)
    lw $t5, 68($a0)
    li $t1, 0x811C9DC5
    li $t6, 16777619
    move $t2, $zero
zmem_hash:
    lhu $t7, 0($t0)
    xor $t1, $t1, $t7
    multu $t1, $t6
    mflo $t1
    and $t8, $t7, $t4
    bne $t8, $t5, zmem_hnext
    addiu $t0, $t0, 2
    addiu $t2, $t2, 1
zmem_hnext:
    addiu $t3, $t3, -1
    bnez $t3, zmem_hash
    nop
    sw $t1, 12($a1)
    jr $ra
    sw $t2, 16($a1)
"""
