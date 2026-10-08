"""Decodes the noise ROM's rectangle into the a, b and c bits of each pixel.

usage: python -m romgen.suites.noise.decode STDOUT_TXT BITS_TXT

Thar0/RDP-Noise fb2data.py's inverse of the combiner clamp: the pre-clamp value is abc100000;
a = 1, b = 0 saturates to 0xFF and a = 1, b = 1 wraps to 0x00, hiding c (written x); otherwise
the byte is bc100000, or one less from the multiply's rounding. Writes three lines to BITS_TXT:
the a, b and c bits of the 1016 pixels left to right, which is the order the RDP walks a
fill rectangle.
"""
import sys

from ..snapper.compare import parse
from .sets import RECORD, WIDTH


def decode(data):
    a, b, c = [], [], []
    for i in range(0, len(data), 4):
        r, g, bl = data[i:i + 3]
        if not r == g == bl:
            raise SystemExit(f"pixel {i // 4}: not gray ({r:02x} {g:02x} {bl:02x})")
        if r == 0xFF:
            a.append("1"), b.append("0"), c.append("x")
        elif r == 0x00:
            a.append("1"), b.append("1"), c.append("x")
        else:
            if r & 0x3F != 0x20:
                r += 1
            if r & 0x3F != 0x20:
                raise SystemExit(f"pixel {i // 4}: {r - 1:02x} is not bc100000")
            a.append("0"), b.append(str(r >> 7 & 1)), c.append(str(r >> 6 & 1))
    return "".join(a), "".join(b), "".join(c)


def main():
    size, _, data = parse(sys.argv[1]).get(RECORD, (0, 0, None))
    if data is None or size != WIDTH * 4 or len(data) != size:
        raise SystemExit(f"{RECORD}: no {WIDTH * 4}-byte dump in {sys.argv[1]}")
    with open(sys.argv[2], "w") as f:
        f.write("\n".join(decode(data)) + "\n")


if __name__ == "__main__":
    main()
