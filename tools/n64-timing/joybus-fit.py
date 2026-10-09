#!/usr/bin/env python3
"""Solves the PIF joybus-phase costs (pif.estimateTiming) from the n64-systembench RD64B totals.

The cost model is the one ares/n64/pif/hle.cpp charges: a fixed base, one cost per channel-skip
byte (0x00, 0xFD), one per non-advancing escape byte (0xFE end, 0xFF nop), and per handshake a
fixed cost plus the wire bytes. n64brew PIF-NUS ("Joybus frame") gives the frame walk: at most 5
channels, 0xFE ends it, the rest is ignored. n64brew Joybus Protocol gives the wire: 4 us per bit,
so 8 bits = 32 us = 2000 rclk at 62.5 MHz. A device answers its rx bytes; an empty port only takes
the tx bytes, then times out.

Five totals are solved exactly (FIT); every other point is predicted (CHECK, REPORT). The
systembench rig's controller presence is not published: the fit assumes one pad on port 1, as
n64-run connects, so read64-2 is fit-from and read64-3/4 are reports under that assumption.

usage: joybus-fit.py [expected.tsv]
"""
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from romgen.suites.bench.benches import SB_JOY_FRAMES  # noqa: E402

BYTE = 2000  # rclk per joybus byte: n64brew Joybus Protocol, 4 us per bit x 8 at 62.5 MHz
# ares charges this much of a RD64B total after the joybus phase (the 64 B RDRAM write, the poll
# and the harness): measured on master c7824c6da as the mean of measured minus estimateTiming over
# the 8 JOY points, 28..50 rclk (poll quantization), mean 36.1.
ARES_AFTER = 36
PRESENT = {0}  # ports with a device on the fit's rig (assumed; n64-run connects port 1 only)

FRAMES = {point: block for point, (block, _) in SB_JOY_FRAMES.items()}
FIT = ["empty-0b", "empty-4b", "empty-8b", "read64-1", "read64-2"]
REPORT = ["read64-3", "read64-4"]
PARAMS = ["base", "skip", "escape", "handshake", "no-device"]


def counts(dwords):
    """The parameter coefficients and the constant wire time of one frame (mirrors estimateTiming)."""
    ram = [d >> (56 - 8 * i) & 0xFF for d in dwords for i in range(8)]
    c = dict.fromkeys(PARAMS, 0)
    c["base"], wire, offset, channel = 1, 0, 0, 0
    while offset < 64 and channel < 5:
        send = ram[offset]
        offset += 1
        if send == 0xFE:
            c["escape"] += 1
            break
        if send == 0xFF:
            c["escape"] += 1
            continue
        if send in (0x00, 0xFD):
            c["skip"] += 1
            channel += 1
            continue
        tx, rx = send & 0x3F, ram[offset] & 0x3F
        offset += 1 + tx + rx
        if send & 0xC0:
            c["skip"] += 1
        elif channel in PRESENT:
            c["handshake"] += 1
            wire += BYTE * (tx + rx)
        else:
            c["no-device"] += 1
            wire += BYTE * tx
        channel += 1
    return c, wire


def solve(rows):
    """Exact Gauss-Jordan over Fractions; rows are (coefficients, rhs)."""
    m = [[Fraction(x) for x in r] + [Fraction(b)] for r, b in rows]
    n = len(m)
    for col in range(n):
        piv = next(r for r in range(col, n) if m[r][col])
        m[col], m[piv] = m[piv], m[col]
        m[col] = [x / m[col][col] for x in m[col]]
        for r in range(n):
            if r != col and m[r][col]:
                m[r] = [a - m[r][col] * b for a, b in zip(m[r], m[col])]
    return [r[-1] for r in m]


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "romgen/suites/bench/expected.tsv"
    hw = {}
    for line in path.read_text().splitlines()[1:]:
        f = line.split("\t")
        if f[0] == "si-dma" and f[1] in FRAMES:
            hw[f[1]] = Fraction(f[3])
    eqs = []
    for point in FIT:
        c, wire = counts(FRAMES[point])
        eqs.append(([c[p] for p in PARAMS], hw[point] - wire))
    value = dict(zip(PARAMS, solve(eqs)))
    for p in PARAMS:
        print(f"{p}\t{float(value[p]):g} rclk")
    print(f"si.read64-base (less the {ARES_AFTER} rclk ares charges after the phase)\t{float(value['base'] - ARES_AFTER):g} rclk")
    print("point\thw\tmodel\tdiff_pct\trole")
    for point in FRAMES:
        c, wire = counts(FRAMES[point])
        model = sum(value[p] * c[p] for p in PARAMS) + wire
        role = "fit" if point in FIT else "report" if point in REPORT else "check"
        print(f"{point}\t{hw[point]}\t{float(model):g}\t{float((model - hw[point]) / hw[point] * 100):+.3f}\t{role}")


if __name__ == "__main__":
    main()
