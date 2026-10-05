"""repeater64 demos "RDP 1-Cycle No-Sync" and "RDP Fill-Mode Syncs", ported.

Sources: src/demos/RDPNoSync1C.cpp, src/demos/RDPSync.cpp, src/rdpDumpTest.cpp and the command
encoders in src/rdp/rdp.h. The No-Sync references are the 20 console framebuffer dumps
assets/1000000{0..13 hex}.test. They are read from a local repeater64 checkout at build time
and pinned by SHA-256 below; they are not committed here.
"""
import hashlib
import os
import struct

from ...suite import Test, Value
from . import rdp
from .routines import eq_dec, rle_diff, wait_eq, write32

FB = 0x00500000              # repeater64 main.cpp: RGBA16 320x240 surfaces with stride 0x800
FB_CPU = 0xA0000000 | FB
FB_STRIDE = 0x800
FB_STRIDE_PX = FB_STRIDE // 2
REGION = (16, 48, 320 - 16, 240 - 48)   # RDPNoSync1C.cpp testRegion
REGION_W = REGION[2] - REGION[0] + 1     # rdpDumpTest.cpp compares x <= testRegion[2]
REGION_H = REGION[3] - REGION[1]         # and y < testRegion[3]
CASES = 20                               # rdpDumpTest.h TEST_CASE_COUNT
WAIT = 1 << 26

DEFAULT_ASSETS = os.path.join(os.environ.get("N64_TIMING_HOME", os.path.expanduser("~/n64-timing")),
                              "scratch", "r29", "clones", "repeater64", "assets")
REFERENCE_SHA256 = {
    0x00: "0b329c0490b13e8bd49edda2262c11cf4d4ec5009d58a505f26c4a3bdbf5c732",
    0x01: "75861cd05813d030d1f54c9f8439413399b54adee5748a34a90f42b5541ba2af",
    0x02: "4dd314c91e0ed256bcb7225497ebda2b272574c43740694baf1cbdb44685fdba",
    0x03: "9ba5800b01dfd0da470b0342142c71c0f013a7fd75e122df7d7383a4915ef164",
    0x04: "01f67866113920b0a510b84bf134ea52a057eccb5da1f792617b2f7f889ca7f1",
    0x05: "b6ec5d00738990d01093a59f3360dcfcb6ca76c040b3ac1cb16d76cf638cd1fe",
    0x06: "ac21ba416ad9c165ceb940bf7e235714aed30fac2c11093e4010a4c67d60cd8d",
    0x07: "4260aa5bd46960d8dc9653c8c3816ec0ff5eb43bc270a2459a45060ca88c9d2c",
    0x08: "4113b993c2e35d08996397bc94b206daf79b85417ca033ad302c9e067e62be10",
    0x09: "f744323e4095b18cbece2f505c12dbce517c2283b79eef1a2898bd5e146691a4",
    0x0a: "5f2a5396f8cf8449dabecb4ffeeb83cc038c550abf85539da40e046ada7f987d",
    0x0b: "3fdcc6d44f16f8bb74ce6d0a17d03c6d7d0e23a65074696e59ed4df7b1efebe9",
    0x0c: "679f7a7276ce4fa77bbaf57389acfd14a9dca1e2dca443d2c70323da59e1455d",
    0x0d: "55f2a078577a41a4391a4d97bd0d337014d59d443d4cd429d34569e4fff976f1",
    0x0e: "eb5904fa0ced6dad8b774c2324e3b83a56ecb7873de307bf1d8f3d6fb46cbf47",
    0x0f: "c2a2577afb9f37a46609e28aea8b264e5782f1f0c9c753164ae4d56fcbd7a496",
    0x10: "783f5a283489ab227c4cef0a70d3031c7760c6e8a8e7aed7cbfd191c16193ef7",
    0x11: "788b449c0f5cfac24240462e5b87df0ffcf5ceb33091deb5a930c9417b7aff32",
    0x12: "a5c5e4c6b10852e3c66fbd525fcbde1033e05e730d35a9018947f61d4ce3de24",
    0x13: "fac2558958fccbd0334d92b62f457fba10ef459baaa120c7c71d399d233f51bc",
}


def rgba(r, g, b, a):
    return r << 24 | g << 16 | b << 8 | a


def fill_color16(r, g, b, a):
    c = rdp.rgba5551(r, g, b, a)
    return c << 16 | c


def to_10p2(v):
    return int(v * 4)


# RDPQ_COMBINER1((0,0,0,ENV), (0,0,0,1)) from libdragon include/rdpq_macros.h
CC_ENV = ((8 << 52) | (8 << 28) | (16 << 47) | (5 << 15) | (8 << 37) | (8 << 24) | (16 << 32) | (5 << 6)
          | (7 << 44) | (7 << 12) | (7 << 41) | (6 << 9) | (7 << 21) | (7 << 3) | (7 << 18) | 6)


def clear_list():
    """RDPNoSync1C.cpp draw(): the first DPL, closed by runSync's SYNC_FULL."""
    return rdp.DisplayList("r64_clear").add(
        rdp.sync_pipe(),
        rdp.color_image(FB, FB_STRIDE_PX),
        rdp.scissor(0, 0, to_10p2(319), to_10p2(239)),
        rdp.other_modes(rdp.CYCLE_FILL),
        rdp.fill_color(fill_color16(0, 0, 0, 0)),
        rdp.rect(0, 0, to_10p2(319), to_10p2(239)),
        rdp.sync_full(),
    )


def nosync_list(case):
    """RDPNoSync1C.cpp draw(): the second DPL (dplTri) for test case 0x10000000 | case."""
    x0, y0, x1, y1 = REGION
    lst = rdp.DisplayList(f"r64_nosync_{case:02x}").add(
        rdp.sync_pipe(),
        rdp.fill_color(fill_color16(0x22, 0x22, 0x22, 0)),
        rdp.scissor(*(to_10p2(v) for v in REGION)),
        rdp.rect(to_10p2(x0), to_10p2(y0), to_10p2(x1), to_10p2(y1)),
        rdp.sync_pipe(),
        rdp.other_modes(rdp.CYCLE_1, dither_rgb=3, dither_alpha=3),
        rdp.combine(CC_ENV),
    )
    size_y, size_x = case * 6 + 1, 1
    if case >= 10:
        size_x, size_y = (case - 10) * 10 + 1, 8
    pos_y = y0 + 2
    for y in range(32):
        pos_x = x0 + 2
        for x in range(64):
            lst.add(rdp.sync_pipe(),
                    rdp.env_color(rgba(0xFF, 0xFF, 0xFF, 0xFF)),
                    rdp.rect(to_10p2(pos_x), to_10p2(pos_y),
                             to_10p2(pos_x + x + size_x), to_10p2(pos_y + y + size_y)),
                    rdp.env_color(rgba(0xFF, 0, 0, 0xFF)),
                    rdp.env_color(rgba(0, 0xFF, 0, 0xFF)),
                    rdp.env_color(rgba(0, 0, 0xFF, 0xFF)))
            pos_x += x + size_x + 1
            if pos_x + x + size_x + 1 > x1:
                break
        pos_y += y + size_y + 1
        if pos_y + y + size_y + 1 > y1:
            break
    assert len(lst.cmds) + 1 <= 2000, "RDPNoSync1C.cpp allocates dplTri{2000}"
    return lst.add(rdp.sync_full())


FILL_ROW = 100
FILL_A = fill_color16(0xFF, 0, 0, 0xFF)
FILL_B = fill_color16(0, 0xFF, 0, 0xFF)


def fill_sync_list():
    """RDPSync.cpp draw(): one row of 160 two-pixel fill rectangles, each followed by a new
    SetFillColor with no sync in between. SYNC_FULL is appended so the CPU can wait."""
    lst = rdp.DisplayList("r64_fillsync").add(
        rdp.sync_pipe(),
        rdp.color_image(FB, FB_STRIDE_PX),
        rdp.scissor(0, 0, to_10p2(319), to_10p2(239)),
        rdp.other_modes(rdp.CYCLE_FILL),
    )
    for x in range(0, 320, 2):
        lst.add(rdp.fill_color(FILL_A),
                rdp.rect(x * 4, FILL_ROW * 4, x * 4 + 4, FILL_ROW * 4),
                rdp.fill_color(FILL_B),
                rdp.sync_pipe())
    return lst.add(rdp.sync_full())


CLEAR = clear_list()
NOSYNC = [nosync_list(c) for c in range(CASES)]
FILL_SYNC = fill_sync_list()
LISTS = [CLEAR, *NOSYNC, FILL_SYNC]


def rle(pixels):
    words = []
    run, value = 0, None
    for p in pixels:
        if p == value and run < 0x10000:
            run += 1
            continue
        if value is not None:
            words.append((run - 1) << 16 | value)
        run, value = 1, p
    words.append((run - 1) << 16 | value)
    return words


def load_reference(case, assets):
    path = os.path.join(assets, f"{0x10000000 | case:08X}.test")
    data = open(path, "rb").read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != REFERENCE_SHA256[case]:
        raise SystemExit(f"{path}: sha256 {digest} does not match the pinned reference")
    assert len(data) == 2 * REGION_W * REGION_H
    return struct.unpack(f">{REGION_W * REGION_H}H", data)


def reference_asm(assets):
    out = [".align 4"]
    for case in range(CASES):
        words = rle(load_reference(case, assets))
        out.append(f"r64_ref_{case:02x}:")
        for i in range(0, len(words), 16):
            out.append("    .word " + ", ".join(str(w) for w in words[i:i + 16]))
    return "\n".join(out)


def run_list(symbols, lst):
    """DPL::runSync: wait for DMA_BUSY clear, START, END, then wait for PIPE_BUSY clear."""
    start = symbols[lst.label] & 0x1FFFFFFF
    return [wait_eq(rdp.DPC_STATUS, rdp.DMA_BUSY, 0, WAIT, 0),
            write32(rdp.DPC_START, start), write32(rdp.DPC_END, start + lst.size()),
            wait_eq(rdp.DPC_STATUS, rdp.PIPE_BUSY, 0, WAIT, 0)]


def nosync(symbols):
    values = []
    region = FB_CPU + REGION[1] * FB_STRIDE + REGION[0] * 2
    for case in range(CASES):
        steps = run_list(symbols, CLEAR) + run_list(symbols, NOSYNC[case]) + [
            rle_diff(region, FB_STRIDE, REGION_W, REGION_H, symbols[f"r64_ref_{case:02x}"], 1)]
        values.append(Value(f" [Value: {0x10000000 | case:08X}]", steps, [
            eq_dec(1, 0, "pixels differ from the console reference"),
        ]))
    return values


def fill_sync(symbols):
    row = FB_CPU + FILL_ROW * FB_STRIDE
    steps = run_list(symbols, FILL_SYNC) + [
        rle_diff(row, FB_STRIDE, 320, 1, symbols["r64_fill_expected"], 1)]
    return [Value("", steps, [
        eq_dec(1, 0, "pixels not drawn in the SetFillColor that follows their rectangle"),
    ])]


FILL_EXPECTED_ASM = f".align 4\nr64_fill_expected:\n    .word {(319 << 16) | (FILL_B & 0xFFFF)}"


def build(suite):
    s = suite.symbols
    suite.tests += [
        Test("RDP 1-Cycle No-Sync", nosync(s)),
        Test("RDP Fill-Mode Syncs", fill_sync(s)),
    ]
