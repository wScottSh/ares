"""Write-buffer points that resolve the full-buffer rule and the block entry count (kit-cpu, questions wb-spaced
and wb-evict; prehw-plan.md U-WB-POINTS).

wb-spaced: N = 5 and 6 uncached RDRAM stores with g = 0, 1, 2, 4 or 8 nops between consecutive stores, timed from
the first store to after the last (wb-stores' sw-N with spacing). With spacing the buffer drains partly between
stores, so a store that waits for an empty buffer (the R4300i datasheet's "emptied") waits less past the fork's
one free entry (NEC's "has a space") than at g = 0.

wb-evict: cached SWs that each miss on a dirty line, so each queues a block writeback.
  victims-<v>  v = 1-4 such stores back to back, then one uncached LW, timed to the load's data
  victim-sw<s> one such store, then s = 1-4 uncached RDRAM stores, timed to after the last store: the store that
               finds no free entry behind the writeback's block entries stalls (cpu.wb-block-entries)
Each rep first dirties the v victim lines at A (one D-cache line each, consecutive indexes), then drains the buffer
with an uncached LW; the timed stores go to B = A + 8 KiB, the same indexes.
"""
from ..bench.benches import KSEG0, KSEG1, Rom

WB_BUF = 0x005D1000            # sets.py CAL_BUF + 0x1000, wb-stores' store target
EVICT_A = 0x005D4400           # bank 5, D-cache indexes clear of dcb's CAL_BUF lines
DCACHE = 0x2000
LINE = 16
DRAIN = 0x005D3000
SPACED_N = (5, 6)
SPACED_G = (0, 1, 2, 4, 8)
VICTIMS = (1, 2, 3, 4)
STORES = (1, 2, 3, 4)


def spaced_kernel(n, g):
    return f"k_wbs_{n}_g{g}"


def evict_kernel(kind, k):
    return f"k_wbe_{kind}{k}"


def spaced(n, g):
    stores = ["    sw $t5, 0($t0)"] * n
    body = ("\n" + "    nop\n" * g).join(stores)
    return f"""
# args = {{target, value}}: {n} uncached stores of value to target, {g} nops between consecutive stores.
{spaced_kernel(n, g)}:
    lw $t0, 0($a0)
    lw $t5, 4($a0)
    lw $t6, 0($t0)
    nop
    mfc0 $t8, $count
{body}
    mfc0 $t9, $count
    jr $ra
    subu $v0, $t9, $t8
"""


def evict(kind, k):
    victims = k if kind == "v" else 1
    dirty = "\n".join(f"    lw $t5, {LINE * i}($t0)\n    sw $t5, {LINE * i}($t0)" for i in range(victims))
    misses = "\n".join(f"    sw $t5, {LINE * i}($t1)" for i in range(victims))
    if kind == "v":
        tail = "    lw $t9, 0($t2)\n    addu $t9, $t9, $zero"
    else:
        tail = "\n".join(["    sw $t5, 0($t3)"] * k)
    return f"""
# args = {{A, B, drain, target}}: dirties {victims} line(s) at A, drains, then times {victims} cached store(s) to B
# that evict them, then {"one uncached load" if kind == "v" else f"{k} uncached store(s) to target"}.
{evict_kernel(kind, k)}:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    lw $t3, 12($a0)
{dirty}
    lw $t7, 0($t2)
    addiu $t6, $zero, 64
kwbe_{kind}{k}_spin:
    bnez $t6, kwbe_{kind}{k}_spin
    addiu $t6, $t6, -1
    mfc0 $t8, $count
{misses}
{tail}
    mfc0 $t6, $count
    jr $ra
    subu $v0, $t6, $t8
"""


ASM = "\n".join([spaced(n, g) for n in SPACED_N for g in SPACED_G]
                + [evict("v", v) for v in VICTIMS] + [evict("s", s) for s in STORES])


def wb_spaced(suite):
    rom = Rom(suite, "wb-spaced")
    for n in SPACED_N:
        for g in SPACED_G:
            rom.point(f"sw-{n}-g{g}", spaced_kernel(n, g), [KSEG1 | WB_BUF, 0],
                      [("stores", n), ("gap", g), ("target", "rdram")], reps=8)


def wb_evict(suite):
    rom = Rom(suite, "wb-evict")
    args = [KSEG0 | EVICT_A, KSEG0 | (EVICT_A + DCACHE), KSEG1 | DRAIN, KSEG1 | WB_BUF]
    for v in VICTIMS:
        rom.point(f"victims-{v}", evict_kernel("v", v), args, [("victims", v), ("tail", "load")], reps=8)
    for s in STORES:
        rom.point(f"victim-sw{s}", evict_kernel("s", s), args, [("victims", 1), ("stores", s)], reps=8)


BUILDERS = [wb_spaced, wb_evict]
