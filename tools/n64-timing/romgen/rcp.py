"""The RDP command builder, DPC/SP register map and on-target RCP helpers shared by the romgen suites.

A command is one 64-bit integer. The encodings follow the GBI layout in Thar0/RDP-Timing-Tests
src/rdp.h (itself lifted from f3d), which matches the RDP command reference on n64brew
(Reality Display Processor/Commands). Coordinates are in pixels unless the name ends in _frac,
which takes 10.2 fixed point.
"""
from dataclasses import dataclass, field

DPC_BASE = 0xA4100000
MI_BASE = 0xA4300000
VI_BASE = 0xA4400000

DPC_START = DPC_BASE + 0x00
DPC_END = DPC_BASE + 0x04
DPC_CURRENT = DPC_BASE + 0x08
DPC_STATUS = DPC_BASE + 0x0C
SP_MEM_ADDR = 0xA4040000
SP_DRAM_ADDR = 0xA4040004
SP_RD_LEN = 0xA4040008
SP_STATUS = 0xA4040010
SP_STATUS_DMA_BUSY = 0x4

# DPC_STATUS read bits (n64-systemtest src/rdp/rdp.rs)
XBUS = 0x1
FREEZE = 0x2
START_GCLK = 0x8
PIPE_BUSY = 0x20
CBUF_READY = 0x80
DMA_BUSY = 0x100
END_VALID = 0x200
START_VALID = 0x400

# DPC_STATUS write bits (n64brew Reality Display Processor/Interface)
CLEAR_XBUS = 0x1
SET_XBUS = 0x2
CLEAR_FREEZE = 0x4
SET_FREEZE = 0x8
DPC_CLR_TMEM_CTR = 1 << 6
DPC_CLR_PIPE_CTR = 1 << 7
DPC_CLR_CMD_CTR = 1 << 8
DPC_CLR_CLOCK_CTR = 1 << 9

# COUNT runs at half the 93.75 MHz PClock (libdragon TICKS_PER_SECOND).
COUNT_PER_MS = 46875

# Other modes, word 0 (bits 32-55 of the command)
CYC_1CYCLE, CYC_2CYCLE, CYC_COPY, CYC_FILL = (c << 20 for c in range(4))
ATOMIC_PRIM = 1 << 23
PM_NPRIMITIVE = 0
TP_NONE = 0
TD_CLAMP = 0
TL_TILE = 0
TT_NONE = 0
TF_POINT = 0
TC_FILT = 6 << 9
CK_NONE = 0
CD_DISABLE = 3 << 6
AD_DISABLE = 3 << 4

# Other modes, word 1
AC_NONE = 0
AC_THRESHOLD = 1
ZS_PRIM = 1 << 2
Z_CMP = 0x0010
Z_UPD = 0x0020
IM_RD = 0x0040
CVG_DST_FULL = 0x0200
ZMODE_OPA = 0
RM_NOOP = 0

# Combiner inputs (rdp.h G_CCMUX_* / G_ACMUX_*)
CC = {"0": 31, "PRIMITIVE": 3}
AC = {"0": 7, "PRIMITIVE": 3}

IM_FMT_RGBA = 0
IM_SIZ_16b = 2
SC_NON_INTERLACE = 0
MAXFBZ = 0x3FFF


def _f(value, bits, shift):
    return (value & ((1 << bits) - 1)) << shift


def _op(code, hi, lo):
    return (_f(code, 8, 24) | hi) << 32 | (lo & 0xFFFFFFFF)


def nop():
    return _op(0xC0, 0, 0)


def load_sync():
    return _op(0xE6, 0, 0)


def pipe_sync():
    return _op(0xE7, 0, 0)


def tile_sync():
    return _op(0xE8, 0, 0)


def full_sync():
    return _op(0xE9, 0, 0)


def set_color_image(fmt, siz, width, addr):
    return _op(0xFF, _f(fmt, 3, 21) | _f(siz, 2, 19) | _f(width - 1, 12, 0), addr)


def set_depth_image(addr):
    return _op(0xFE, 0, addr)


def _combine(hi, lo):
    return _op(0xFC, hi, lo)


def set_combine_lerp(a0, b0, c0, d0, aa0, ab0, ac0, ad0, a1, b1, c1, d1, aa1, ab1, ac1, ad1):
    hi = (_f(CC[a0], 4, 20) | _f(CC[c0], 5, 15) | _f(AC[aa0], 3, 12) | _f(AC[ac0], 3, 9)
          | _f(CC[a1], 4, 5) | _f(CC[c1], 5, 0))
    lo = (_f(CC[b0], 4, 28) | _f(CC[b1], 4, 24) | _f(AC[aa1], 3, 21) | _f(AC[ac1], 3, 18)
          | _f(CC[d0], 3, 15) | _f(AC[ab0], 3, 12) | _f(AC[ad0], 3, 9) | _f(CC[d1], 3, 6)
          | _f(AC[ab1], 3, 3) | _f(AC[ad1], 3, 0))
    return _combine(hi, lo)


def set_combine_raw(value):
    """A combiner word already packed as the low 56 bits of the command."""
    return _op(0xFC, value >> 32, value)


def rgba8(r, g, b, a):
    return _f(r, 8, 24) | _f(g, 8, 16) | _f(b, 8, 8) | _f(a, 8, 0)


def set_prim_color(rgba, min_level=0, level_frac=0):
    return _op(0xFA, _f(min_level, 8, 8) | _f(level_frac, 8, 0), rgba)


def set_env_color(rgba):
    return _op(0xFB, 0, rgba)


def set_blend_color(rgba):
    return _op(0xF9, 0, rgba)


def set_fill_color(color):
    return _op(0xF7, 0, color)


def fill_rectangle_frac(ulx, uly, lrx, lry):
    return _op(0xF6, _f(lrx, 12, 12) | _f(lry, 12, 0), _f(ulx, 12, 12) | _f(uly, 12, 0))


def fill_rectangle(ulx, uly, lrx, lry):
    return fill_rectangle_frac(ulx * 4, uly * 4, lrx * 4, lry * 4)


def set_other_mode(mode0, mode1):
    return _op(0xEF, _f(mode0, 24, 0), mode1)


def set_prim_depth(z, dz):
    return _op(0xEE, 0, _f(z, 16, 16) | _f(dz, 16, 0))


def set_scissor_frac(ulx, uly, lrx, lry, mode=SC_NON_INTERLACE):
    return _op(0xED, _f(ulx, 12, 12) | _f(uly, 12, 0), _f(mode, 2, 24) | _f(lrx, 12, 12) | _f(lry, 12, 0))


def set_scissor(ulx, uly, lrx, lry):
    return set_scissor_frac(ulx * 4, uly * 4, lrx * 4, lry * 4)


def rgba5551(r, g, b, a):
    """Packs 8-bit components (repeater64 rdp.h packColor, n64-systemtest RGBA5551::from_argb8888)."""
    return ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | (a >> 7)


def zdz(z, dz):
    return _f(z, 14, 2) | _f(dz, 2, 0)


def words(dl):
    return [w for cmd in dl for w in (cmd >> 32, cmd & 0xFFFFFFFF)]


@dataclass
class DisplayList:
    """A command list placed in the ROM payload, 8-byte aligned so the RDP can fetch it."""
    label: str
    cmds: list = field(default_factory=list)

    def add(self, *cmds):
        self.cmds += cmds
        return self

    def asm(self):
        out = [".align 8", f"{self.label}:"]
        for i in range(0, len(self.cmds), 8):
            out.append("    .dword " + ", ".join(f"{c:#x}" for c in self.cmds[i:i + 8]))
        out.append(f"{self.label}_end:")
        return "\n".join(out)

    def size(self):
        return 8 * len(self.cmds)


# On-target helpers. Calling convention as for runtime routines: a0-a3 in, v0 out, t-registers
# clobbered, s-registers preserved.
ASM = r"""
# a0 = COUNT ticks to wait (libdragon wait_ticks).
wait_count:
    mfc0 $t0, $count
wc_loop:
    mfc0 $t1, $count
    subu $t1, $t1, $t0
    sltu $t1, $t1, $a0
    bnez $t1, wc_loop
    nop
    jr $ra
    nop

# a0 = {count, (address, value) x count}: uncached word stores in order.
io_writes:
    lw $t0, 0($a0)
    beqz $t0, iw_done
    addiu $a0, $a0, 4
iw_loop:
    lw $t1, 0($a0)
    lw $t2, 4($a0)
    sw $t2, 0($t1)
    addiu $t0, $t0, -1
    bnez $t0, iw_loop
    addiu $a0, $a0, 8
iw_done:
    jr $ra
    nop

# Runs one RDP command list and reads the DPC counters once they settle, following
# Thar0/RDP-Timing-Tests rdp_exec: wait for VI_CURRENT == 0, START, clear the four counters,
# END, wait for the DP interrupt, wait 2 ms. a0 = start, a1 = end (RDRAM addresses),
# a2 = 0 or out {BUFBUSY, PIPEBUSY, TMEM}. The DP interrupt is polled in MI_INTR and acked
# through MI_MODE instead of taken as an exception.
rdp_exec:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    move $s0, $a2
    li $t0, VI_BASE
re_vi:
    lw $t1, 0x10($t0)
    bnez $t1, re_vi
    nop
    li $t0, DPC_BASE
    sw $a0, 0x00($t0)
    li $t1, DPC_CLR_COUNTERS
    sw $t1, 0x0C($t0)
    sw $a1, 0x04($t0)
    li $t0, MI_BASE
re_dp:
    lw $t1, 0x08($t0)
    andi $t1, $t1, 0x20
    beqz $t1, re_dp
    nop
    li $t1, 0x800
    sw $t1, 0x00($t0)
    li $a0, 2 * COUNT_PER_MS
    jal wait_count
    nop
    beqz $s0, re_out
    nop
    li $t0, DPC_BASE
    lw $t1, 0x14($t0)
    sw $t1, 0($s0)
    lw $t1, 0x18($t0)
    sw $t1, 4($s0)
    lw $t1, 0x1C($t0)
    sw $t1, 8($s0)
re_out:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    jr $ra
    addiu $sp, $sp, 16
"""

CONSTS = dict(
    DPC_BASE=DPC_BASE, MI_BASE=MI_BASE, VI_BASE=VI_BASE, COUNT_PER_MS=COUNT_PER_MS,
    DPC_CLR_COUNTERS=DPC_CLR_TMEM_CTR | DPC_CLR_PIPE_CTR | DPC_CLR_CMD_CTR | DPC_CLR_CLOCK_CTR,
)
