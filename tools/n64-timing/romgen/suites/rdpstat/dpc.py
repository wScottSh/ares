"""DPC command-DMA sequencing: DMA_BUSY and the START/END double buffer (END_PENDING).

n64-systemtest asserts neither (its rdp/mod.rs:178-180 says DMA_BUSY is set "briefly" on
hardware and leaves it unchecked, and its TODO lists double buffering). These tests take their
expectations from the register descriptions instead:
- DPC_STATUS bits 8 (DMA_BUSY), 9 (END_VALID) and 10 (START_VALID): n64brew
  Reality_Display_Processor/Interface; MiSTer RDP.vhd:500-511.
- DPC_START latches only while START_VALID = 0. A DPC_END write while START_VALID = 1 and the
  command DMA is busy sets END_VALID and queues the new END; CURRENT moves to the queued START
  when it reaches the old END. n64brew; MiSTer RDP.vhd:545-566, 595-605.
Both are summarized with citations in docs/research/rsp-rdp-fifo.md rows 9, 10 and 12. No
console capture backs these tests; that the command DMA stays busy while the command FIFO is
full is inferred from "DMA waits for FIFO space" (docs/research/rdp-command-timing.md).

List A is 64 full-screen fill rectangles: at 4 px per clock in fill mode each takes about
19,200 RDP clocks, so the DMA is still fetching A for milliseconds after the CPU's writes
(inferred, not measured).
"""
from ...suite import Test, Value
from ... import rcp
from .repeater64 import FB, FB_CPU, FB_STRIDE_PX
from .routines import eq, in_range, read16, read32, res_mask, wait_eq, write32

RED = rcp.rgba5551(0xFF, 0, 0, 0xFF)
GREY = rcp.rgba5551(0x22, 0x22, 0x22, 0)
RECTS = 64
LONG_WAIT = 1 << 26

LIST_A = rcp.DisplayList("dpc_list_a").add(
    rcp.pipe_sync(),
    rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, FB_STRIDE_PX, FB),
    rcp.set_scissor_frac(0, 0, 320 << 2, 240 << 2),
    rcp.set_other_mode(rcp.CYC_FILL, 0),
    rcp.set_fill_color(GREY | GREY << 16),
    *[rcp.fill_rectangle_frac(0, 0, 319 << 2, 239 << 2)] * RECTS,
)
LIST_B = rcp.DisplayList("dpc_list_b").add(
    rcp.pipe_sync(),
    rcp.set_fill_color(RED | RED << 16),
    rcp.fill_rectangle_frac(0, 0, 7 << 2, 0),
    rcp.full_sync(),
)
LIST_SYNC = rcp.DisplayList("dpc_list_sync").add(rcp.full_sync())
LISTS = [LIST_A, LIST_B, LIST_SYNC]


def phys(symbols, lst):
    start = symbols[lst.label] & 0x1FFFFFFF
    return start, start + lst.size()


def idle_steps(res):
    return [wait_eq(rcp.DPC_STATUS, rcp.DMA_BUSY | rcp.PIPE_BUSY, 0, LONG_WAIT, res)]


def dma_busy(symbols):
    a, a_end = phys(symbols, LIST_A)
    s, s_end = phys(symbols, LIST_SYNC)
    steps = idle_steps(0) + [
        write32(rcp.DPC_START, a), write32(rcp.DPC_END, a_end),
        read32(rcp.DPC_STATUS, 1, rcp.DMA_BUSY),
        read32(rcp.DPC_CURRENT, 2),
        wait_eq(rcp.DPC_CURRENT, 0xFFFFFFFF, a_end, LONG_WAIT, 3),
        read32(rcp.DPC_STATUS, 4, rcp.DMA_BUSY),
        write32(rcp.DPC_START, s), write32(rcp.DPC_END, s_end),
    ] + idle_steps(5)
    return [Value("", steps, [
        eq(0, 0, "RDP should be idle before the test"),
        eq(1, rcp.DMA_BUSY, "DMA_BUSY should be set right after END while a 64-rectangle list is fetched"),
        in_range(2, a, a_end - 8, "CURRENT should trail END while the list is fetched"),
        eq(3, a_end, "CURRENT should reach END"),
        eq(4, 0, "DMA_BUSY should clear once CURRENT reaches END"),
    ])]


def end_pending(symbols):
    a, a_end = phys(symbols, LIST_A)
    b, b_end = phys(symbols, LIST_B)
    steps = idle_steps(0) + [
        write32(rcp.DPC_START, a), write32(rcp.DPC_END, a_end),
        write32(rcp.DPC_START, b),
        read32(rcp.DPC_STATUS, 1), read32(rcp.DPC_START, 2),
        write32(rcp.DPC_END, b_end),
        read32(rcp.DPC_STATUS, 3), read32(rcp.DPC_END, 4), read32(rcp.DPC_CURRENT, 5),
        wait_eq(rcp.DPC_CURRENT, 0xFFFFFFFF, b_end, LONG_WAIT, 9),
    ] + idle_steps(10) + [
        read32(rcp.DPC_STATUS, 11, rcp.START_VALID | rcp.END_VALID),
        read16(FB_CPU, 12),
        res_mask(1, rcp.START_VALID | rcp.END_VALID, 13),
        res_mask(3, rcp.START_VALID | rcp.END_VALID, 14),
    ]
    return [Value("", steps, [
        eq(0, 0, "RDP should be idle before the test"),
        eq(13, rcp.START_VALID, "START written after END should latch and set START_VALID only"),
        eq(2, b, "START should read back the queued address"),
        eq(14, rcp.START_VALID | rcp.END_VALID,
           "END written while START_VALID and the DMA is busy should set END_VALID (END_PENDING)"),
        eq(4, b_end, "END should read back the last written value"),
        in_range(5, a, a_end - 8, "CURRENT should still be in the first list"),
        eq(9, b_end, "CURRENT should reach the queued END"),
        eq(11, 0, "START_VALID and END_VALID should clear once the queued list starts"),
        eq(12, RED, "The queued list should draw"),
    ])]


def build(suite):
    s = suite.symbols
    suite.tests += [
        Test("DPC STATUS: DMA_BUSY while fetching a long list", dma_busy(s)),
        Test("DPC STATUS: END_PENDING double buffer", end_pending(s)),
    ]
