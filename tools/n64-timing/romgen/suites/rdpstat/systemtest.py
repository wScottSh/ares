"""n64-systemtest `src/tests/rdp/mod.rs` (Level::RDPBasic), ported.

Test order and values follow src/tests/testlist.rs:689-694. A Rust `?` ends a test at its
first failed assertion; each one becomes a checkpoint() where later steps have side effects.
"""
from ... import runtime as rt
from ...suite import Check, Test, Value, checkpoint
from ... import rcp
from .routines import eq, read16, read32, res_mask, wait_eq, write32, fill32

FB = 0x00580000          # 8x8 RGBA5551 auxiliary framebuffer (UncachedHeapMemory, 16-aligned)
FB_CPU = 0xA0000000 | FB
BLACK = rcp.rgba5551(0, 0, 0, 0)
BLUE = rcp.rgba5551(0, 0, 255, 0)
GREEN = rcp.rgba5551(0, 255, 0, 0)
WAIT_ITERATIONS = 10_000  # mod.rs wait_for_status


def fill_rect_list(label, color):
    """The 8x8 fill-mode program StatusFlagsDuringRun and run_from_dmem_test assemble."""
    r = (0, 0, 7 << 2, 7 << 2)
    return rcp.DisplayList(label).add(
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, 8, FB),
        rcp.set_scissor_frac(*r),
        rcp.set_other_mode(rcp.CYC_FILL, 0),
        rcp.set_fill_color(color | color << 16),
        rcp.fill_rectangle_frac(*r),
        rcp.pipe_sync(),
    )


RUN_LIST = fill_rect_list("st_run_list", BLUE).add(rcp.full_sync(), rcp.full_sync())
DMEM_LIST = fill_rect_list("st_dmem_list", GREEN).add(rcp.full_sync())
LISTS = [RUN_LIST, DMEM_LIST]


def wait_status(goal, res):
    return [wait_eq(rcp.DPC_STATUS, 0xFFFFFFFF, goal, WAIT_ITERATIONS, res),
            checkpoint([eq(res, goal, f"Time out waiting for RDP status {goal:#x}")])]


def freeze_steps(res):
    return [write32(rcp.DPC_STATUS, rcp.SET_FREEZE),
            read32(rcp.DPC_STATUS, res, rcp.FREEZE),
            checkpoint([eq(res, rcp.FREEZE, "RDP was told to freeze, but it didn't")])]


def unfreeze_steps(res):
    return [write32(rcp.DPC_STATUS, rcp.CLEAR_FREEZE),
            read32(rcp.DPC_STATUS, res, rcp.FREEZE),
            checkpoint([eq(res, 0, "RDP was told to stop being frozen but it's still frozen")])]


def start_and_end_masking():
    steps = freeze_steps(0)
    for v in [0xFFF, 0xFF_FFFF, 0x12FF_FFFF, 0x1280_0000, 0xFFFF_FFFF, 0]:
        m = v & 0xFF_FFF8
        steps += [write32(rcp.DPC_START, v), write32(rcp.DPC_END, v),
                  read32(rcp.DPC_START, 1), read32(rcp.DPC_CURRENT, 2), read32(rcp.DPC_END, 3),
                  checkpoint([
                      eq(1, m, f"RDP START isn't masked properly on write ({v:#x} was written)"),
                      eq(2, m, f"RDP START isn't masked properly on write ({v:#x} was written)"),
                      eq(3, m, f"RDP END isn't masked properly on write ({v:#x} was written)"),
                  ])]
    return [Value("", steps + unfreeze_steps(4), [])]


def start_is_valid_flag(start):
    steps = [read32(rcp.DPC_CURRENT, 0)] + freeze_steps(1) + [
        read32(rcp.DPC_STATUS, 2, rcp.START_VALID),
        read32(rcp.DPC_STATUS, 3, rcp.END_VALID),
        checkpoint([eq(2, 0, "start-valid should be false when entering the test"),
                    eq(3, 0, "end-valid should be false when entering the test")]),
        write32(rcp.DPC_START, start),
        read32(rcp.DPC_STATUS, 4), read32(rcp.DPC_START, 5),
        write32(rcp.DPC_START, 0x12_3450),
        read32(rcp.DPC_STATUS, 6), read32(rcp.DPC_START, 7), read32(rcp.DPC_CURRENT, 8),
        write32(rcp.DPC_END, start),
        read32(rcp.DPC_STATUS, 9), read32(rcp.DPC_START, 10), read32(rcp.DPC_CURRENT, 11),
    ] + unfreeze_steps(12) + [
        res_mask(4, rcp.START_VALID, 13), res_mask(4, rcp.END_VALID, 14),
        res_mask(6, rcp.START_VALID, 15), res_mask(6, rcp.END_VALID, 16),
        res_mask(9, rcp.START_VALID, 17), res_mask(9, rcp.END_VALID, 18),
    ]
    checks = [
        eq(13, rcp.START_VALID, "start-valid should be set after writing start-address"),
        eq(14, 0, "end-valid should be false after writing start-address"),
        eq(5, start, "RDP start address after writing"),
        eq(15, rcp.START_VALID, "Writing start after start should keep start-valid true"),
        eq(16, 0, "Writing start while start-valid should not set end-valid"),
        eq(7, start, "Writes to start address should be ignored while start-valid is set"),
        Check(rt.CHK_EQ_REL, 8, 0, 0, msg="Writes to start should not affect current"),
        eq(17, 0, "After writing end, start-valid should be cleared"),
        eq(18, 0, "After writing end, end-valid should not be set (at least not while frozen)"),
        eq(10, start, "Reading back end address after write to it (3)"),
        eq(11, start, "Current should be equal to start (which is also equal to end) (3)"),
    ]
    return Value(f" [Value: {start:#x}]", steps, checks)


def status_flags_during_run(symbols):
    start = symbols[RUN_LIST.label] & 0x1FFFFFFF
    end = start + RUN_LIST.size()
    idle_busy = rcp.CBUF_READY | rcp.PIPE_BUSY | rcp.START_GCLK
    steps = [fill32(FB_CPU, 32, BLACK | BLACK << 16),
             write32(rcp.DPC_START, start), write32(rcp.DPC_END, start),
             read32(rcp.DPC_START, 0), read32(rcp.DPC_CURRENT, 1),
             checkpoint([eq(0, start, "RDP start should be equal to START after writing END"),
                         eq(1, start, "RDP current should be equal to START after writing END")])]
    steps += wait_status(idle_busy, 2)
    steps += [read32(rcp.DPC_START, 3), read32(rcp.DPC_CURRENT, 4),
              checkpoint([eq(3, start, "RDP start should be equal to START after writing END"),
                          eq(4, start, "RDP current should be equal to START after writing END")]),
              write32(rcp.DPC_END, start + 8)]
    steps += wait_status(idle_busy, 5)
    steps += [read32(rcp.DPC_START, 6),
              checkpoint([eq(6, start, "RDP start should be equal to START after writing END")]),
              write32(rcp.DPC_END, end - 16)]
    steps += wait_status(idle_busy, 7)
    steps += [write32(rcp.DPC_END, end - 8)]
    steps += wait_status(rcp.CBUF_READY, 8)
    steps += [read16(FB_CPU, 9),
              checkpoint([eq(9, BLUE, "Auxiliary framebuffer should be filled with BLUE")]),
              write32(rcp.DPC_END, end)]
    steps += wait_status(rcp.CBUF_READY, 10)
    steps += [read32(rcp.DPC_START, 11)]
    return [Value("", steps, [eq(11, start, "RDP start should be equal to START after reaching the end")])]


def run_from_dmem(symbols, dmem_range):
    src = symbols[DMEM_LIST.label] & 0x1FFFFFFF
    length = DMEM_LIST.size()
    dmem_start, dmem_end = dmem_range(length)
    assert (dmem_end - dmem_start) & 0xFFF == length
    steps = [fill32(FB_CPU, 32, BLACK | BLACK << 16),
             # RSP::start_dma_cpu_to_sp writes the byte length itself to SP_RD_LEN (not length - 1).
             write32(rcp.SP_MEM_ADDR, dmem_start), write32(rcp.SP_DRAM_ADDR, src),
             write32(rcp.SP_RD_LEN, length),
             wait_eq(rcp.SP_STATUS, rcp.SP_STATUS_DMA_BUSY, 0, 1 << 30, 0),
             write32(rcp.DPC_STATUS, rcp.SET_XBUS),
             write32(rcp.DPC_START, dmem_start), write32(rcp.DPC_END, dmem_end)]
    steps += wait_status(rcp.CBUF_READY | rcp.XBUS, 1)
    steps += [write32(rcp.DPC_STATUS, rcp.CLEAR_XBUS),
              read32(rcp.DPC_CURRENT, 2), read16(FB_CPU, 3)]
    return [Value("", steps, [
        eq(2, dmem_end, "RDP current should be equal to END after writing END (and waiting for the RDP to finish)"),
        eq(3, GREEN, "Auxiliary framebuffer should be filled with GREEN"),
    ])]


def build(suite):
    s = suite.symbols
    suite.tests += [
        Test("RDP START & END REG (masking)", start_and_end_masking()),
        Test("RSP STATUS: start-valid", [start_is_valid_flag(0x1238), start_is_valid_flag(0)]),
        Test("RDP STATUS: Flags during a run", status_flags_during_run(s)),
        Test("RDP STATUS: Run from DMEM (xbus)", run_from_dmem(s, lambda n: (0, n))),
        Test("RDP STATUS: Run from DMEM (xbus) (end of dmem)",
             run_from_dmem(s, lambda n: (0x1000 - n, 0x1000))),
        Test("RDP STATUS: Run from DMEM (xbus) (overflowing dmem)",
             run_from_dmem(s, lambda n: (0xFF0, 0xFF0 + n))),
    ]
