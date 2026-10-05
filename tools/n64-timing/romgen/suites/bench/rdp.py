"""RDP command encoders (n64brew Reality_Display_Processor/Commands field layouts).

Each function returns one 64-bit command word. Coordinates are in pixels and are encoded as
10.2 fixed point.
"""
NOP, SYNC_LOAD, SYNC_PIPE, SYNC_TILE, SYNC_FULL = 0x00, 0x26, 0x27, 0x28, 0x29

CYCLE_1, CYCLE_FILL = 0, 3


def _op(code):
    return code << 56


def bare(code):
    return _op(code)


def set_color_image(addr, width, fmt=0, size=2):
    return _op(0x3F) | (fmt << 53) | (size << 51) | ((width - 1) << 32) | (addr & 0x3FFFFFF)


def set_scissor(x0, y0, x1, y1):
    return _op(0x2D) | ((x0 * 4) << 44) | ((y0 * 4) << 32) | ((x1 * 4) << 12) | (y1 * 4)


def set_other_modes(cycle, atomic=False):
    """Blender, Z, image read and alpha compare all off: the combiner output is written."""
    return _op(0x2F) | (int(atomic) << 55) | (cycle << 52)


def set_combine_prim():
    """(0 - 0) * 0 + PRIMITIVE for color and alpha in both cycles."""
    zero_a, zero_b, zero_mul, prim_add = 15, 15, 31, 3
    za, zb, zm, pa = 7, 7, 7, 3
    return (_op(0x3C) | (zero_a << 52) | (zero_mul << 47) | (za << 44) | (zm << 41)
            | (zero_a << 37) | (zero_mul << 32) | (zero_b << 28) | (zero_b << 24)
            | (za << 21) | (zm << 18) | (prim_add << 15) | (zb << 12) | (pa << 9)
            | (prim_add << 6) | (zb << 3) | pa)


def set_prim_color(rgba):
    return _op(0x3A) | rgba


def set_env_color(rgba):
    return _op(0x3B) | rgba


def rect(x0, y0, x1, y1):
    """Fill Rectangle; in 1-cycle mode (x1, y1) is exclusive."""
    return _op(0x36) | ((x1 * 4) << 44) | ((y1 * 4) << 32) | ((x0 * 4) << 12) | (y0 * 4)


def words(commands):
    out = []
    for c in commands:
        out += [(c >> 32) & 0xFFFFFFFF, c & 0xFFFFFFFF]
    return out
