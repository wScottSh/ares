"""Minimal RDP command encoders and the DPC/SP register map the rdpstat suite uses.

Field layouts follow the two sources' own encoders: n64-systemtest `src/rdp/rdp_assembler.rs`
and repeater64 `src/rdp/rdp.h`. Coordinates are 10.2 fixed point. These helpers are local to
this suite; R2's command-list builder is meant to replace them.
"""
from dataclasses import dataclass, field

DPC_START = 0xA4100000
DPC_END = 0xA4100004
DPC_CURRENT = 0xA4100008
DPC_STATUS = 0xA410000C
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

# DPC_STATUS write bits
CLEAR_XBUS = 0x1
SET_XBUS = 0x2
CLEAR_FREEZE = 0x4
SET_FREEZE = 0x8

CYCLE_1 = 0
CYCLE_FILL = 3


def _cmd(op, value=0):
    assert value >> 56 == 0
    return (op << 56) | value


def sync_pipe():
    return _cmd(0x27)


def sync_full():
    return _cmd(0x29)


def color_image(phys, width, fmt=0, size=2):
    """Set_Color_Image; `width` is the image width in pixels."""
    return _cmd(0x3F, (fmt << 53) | (size << 51) | ((width - 1) << 32) | (phys & 0x3FFFFFF))


def scissor(x0, y0, x1, y1):
    """Arguments in 10.2 units."""
    return _cmd(0x2D, (x0 << 44) | (y0 << 32) | (x1 << 12) | y1)


def rect(x0, y0, x1, y1):
    """Fill_Rectangle (0x36); arguments in 10.2 units."""
    return _cmd(0x36, (x1 << 44) | (y1 << 32) | (x0 << 12) | y0)


def fill_color(value):
    return _cmd(0x37, value & 0xFFFFFFFF)


def env_color(rgba):
    return _cmd(0x3B, rgba & 0xFFFFFFFF)


def other_modes(cycle, dither_rgb=0, dither_alpha=0):
    return _cmd(0x2F, (cycle << 52) | (dither_rgb << 38) | (dither_alpha << 36))


def combine(value):
    return _cmd(0x3C, value)


def rgba5551(r, g, b, a):
    """repeater64 rdp.h packColor and n64-systemtest RGBA5551::from_argb8888."""
    return ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | (a >> 7)


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
