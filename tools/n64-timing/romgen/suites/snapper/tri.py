"""snapper64's triangle encoder (src/renderer/rdp.cpp triangleGen/triangleWrite), in float32.

snapper64 computes edge and shade coefficients in single precision on the VR4300
(-fsingle-precision-constant, no FMA on that CPU), so every operation here rounds to float32
the way the ROM does. A float32 +, -, * or / computed in double and rounded once to float32
equals the float32 result, because double carries more than 2 * 24 + 2 bits.
"""
import math
import struct

FLT_MIN = 1.1754943508222875e-38   # std::numeric_limits<float>::min()


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def floorf(x):
    """libdragon fm_floorf: floor.w.s then cvt.s.w."""
    return float(math.floor(x))


def s16_16(f):
    """rdp.cpp float_to_s16_16."""
    if f >= 32768.0:
        return 0x7FFFFFFF
    if f < -32768.0:
        return 0x80000000
    return int(floorf(f32(f * 65536.0))) & 0xFFFFFFFF


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class Vertex:
    def __init__(self, x, y, color=(0.0, 0.0, 0.0, 0.0)):
        self.x, self.y = f32(x), f32(y)
        self.color = tuple(f32(c) for c in color)

    def moved(self, dx, dy):
        return Vertex(f32(self.x + dx), f32(self.y + dy), self.color)


def triangle(v0, v1, v2, shade=False):
    """RDP::triangle(attrs, v0, v1, v2): the command words of a fill (0x08) or shade (0x0C)
    triangle."""
    a, b, c = v0, v1, v2
    if a.y > b.y:
        a, b = b, a
    if b.y > c.y:
        b, c = c, b
    if a.y > b.y:
        a, b = b, a

    x1, x2, x3 = a.x, b.x, c.x
    y1, y2, y3 = (f32(floorf(f32(v.y * 4.0)) / 4.0) for v in (a, b, c))
    y1f, y2f, y3f = (clamp(int(floorf(f32(v.y * 4.0))), -4096 * 4, 4095 * 4) for v in (a, b, c))

    hx, hy = f32(x3 - x1), f32(y3 - y1)
    mx, my = f32(x2 - x1), f32(y2 - y1)
    lx, ly = f32(x3 - x2), f32(y3 - y2)

    nz = f32(f32(hx * my) - f32(hy * mx))
    attr_factor = f32(-1.0 / nz) if abs(nz) > FLT_MIN else 0.0
    lft = 1 if nz < 0 else 0

    ish = f32(hx / hy) if abs(hy) > FLT_MIN else 0.0
    ism = f32(mx / my) if abs(my) > FLT_MIN else 0.0
    isl = f32(lx / ly) if abs(ly) > FLT_MIN else 0.0
    fy = f32(floorf(y1) - y1)

    xh = f32(x1 + f32(fy * ish))
    xm = f32(x1 + f32(fy * ism))
    xl = x2

    cmd = 0x0C if shade else 0x08
    hi = (cmd << 24) | (lft << 23) | (y3f & 0x3FFF)
    lo = ((y2f & 0x3FFF) << 16) | (y1f & 0x3FFF)
    out = [hi << 32 | lo,
           s16_16(xl) << 32 | s16_16(isl),
           s16_16(xh) << 32 | s16_16(ish),
           s16_16(xm) << 32 | s16_16(ism)]
    if shade:
        out += _shade_coeffs(v0, v1, v2, hx, hy, mx, my, ish, fy, attr_factor)
    return out


def _shade_coeffs(v0, v1, v2, hx, hy, mx, my, ish, fy, attr_factor):
    # rdp.cpp takes the color deltas from the vertices in argument order, not the Y-sorted
    # order the edges use. The port keeps that.
    final, dx, de, dy = [], [], [], []
    for i in range(4):
        m = f32(f32(v1.color[i] - v0.color[i]) * 255.0)
        h = f32(f32(v2.color[i] - v0.color[i]) * 255.0)
        nx = f32(f32(hy * m) - f32(my * h))
        ny = f32(f32(mx * h) - f32(hx * m))
        ddx = f32(nx * attr_factor)
        ddy = f32(ny * attr_factor)
        dde = f32(ddy + f32(ddx * ish))
        dx.append(s16_16(ddx))
        dy.append(s16_16(ddy))
        de.append(s16_16(dde))
        final.append(s16_16(f32(f32(v0.color[i] * 255.0) + f32(fy * dde))))

    def hi16(v):
        return v & 0xFFFF0000

    def lo16(v):
        return v & 0xFFFF

    def word(h, l):
        return (h & 0xFFFFFFFF) << 32 | (l & 0xFFFFFFFF)

    def ints(v):
        return word(hi16(v[0]) | lo16(v[1] >> 16), hi16(v[2]) | lo16(v[3] >> 16))

    def fracs(v):
        return word((v[0] << 16) | lo16(v[1]), (v[2] << 16) | lo16(v[3]))

    return [ints(final), ints(dx), fracs(final), fracs(dx),
            ints(de), ints(dy), fracs(de), fracs(dy)]
