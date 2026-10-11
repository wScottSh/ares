"""Back-to-back runs of one CPU-side operation, VI off (kit-cpu, question op-slope; prehw-plan.md U-OP-SLOPE).

Each operation runs N = 16 and N = 64 times between two COUNT reads, so the N = 64 less N = 16 COUNT is 48
operations and every constant term (the setup, the stores still buffered at the closing mfc0) cancels, as in
repeat-write (repeat.py). The operations:
  reg-write       one SW to MI_INTR_MASK (a zero mask write has no effect the kit can see), as reg-write
  dmiss           one cached LW that misses at the next 8 KiB step: every line shares one D-cache index
                  (8 KiB direct-mapped), so each fill evicts the previous, clean line
  ifill           one 32 B I-cache line, index-invalidated before the timed call, run straight through
  u32r            one uncached LW of one RDRAM word, the same row every time
  row-miss-clean  one uncached LW 2 KiB on, so each opens a new row of bank 5 after a read (clean) row
  row-miss-dirty  one SW to the open row, then one uncached LW 2 KiB on: each load opens a new row after a
                  written (dirty) one
"""
from ..bench.benches import KSEG0, KSEG1, MEMSET_BUF, ROW_BANK, VI_OFF, Rom
from .asm import timed

NS = [16, 64]
SB_BUF = 0x005C0000
MI_INTR_MASK = 0xA430000C
ROW = 0x800
DCACHE = 0x2000
LINE_WORDS = 8

LOAD_FIRST = "    lw $t0, 0($a0)\n    lw $t5, 4($a0)\n    lw $t6, 0($t0)\n    nop"
BODIES = {
    "reg-write": (LOAD_FIRST, "    sw $t5, 0($t0)"),
    "dmiss": ("    lw $t0, 0($a0)", f"    lw $t5, 0($t0)\n    addiu $t0, $t0, {DCACHE:#x}"),
    "u32r": (LOAD_FIRST, "    lw $t5, 0($t0)"),
    "row-miss-clean": (LOAD_FIRST, f"    addiu $t0, $t0, {ROW:#x}\n    lw $t5, 0($t0)"),
    "row-miss-dirty": (LOAD_FIRST, f"    sw $zero, 0($t0)\n    addiu $t0, $t0, {ROW:#x}\n    lw $t5, 0($t0)"),
}
ARGS = {
    "reg-write": [MI_INTR_MASK, 0],
    "dmiss": [KSEG0 | MEMSET_BUF, 0],
    "u32r": [KSEG1 | SB_BUF, 0],
    "row-miss-clean": [KSEG1 | ROW_BANK, 0],
    "row-miss-dirty": [KSEG1 | ROW_BANK, 0],
}
OPS = list(BODIES) + ["ifill"]


def kernel(op, n):
    return f"k_os_{op.replace('-', '_')}_{n}"


def ifill_kernel(n):
    block = f"os_ifill_blk_{n}"
    lines = [["    nop"] * LINE_WORDS for _ in range(n)]
    lines[-1][-2] = "    jr $ra"
    return f"""
# args = {{}}: index-invalidates the {n} I-cache lines of {block}, then times one call through them.
{kernel("ifill", n)}:
    la $t0, {block}
    li $t1, {n}
kosi_inv_{n}:
    cache 0, 0($t0)
    addiu $t1, $t1, -1
    bnez $t1, kosi_inv_{n}
    addiu $t0, $t0, 32
    la $t0, {block}
    move $t7, $ra
    mfc0 $t8, $count
    jalr $t0
    nop
    mfc0 $t9, $count
    move $ra, $t7
    jr $ra
    subu $v0, $t9, $t8
.align 32
{block}:
""" + "\n".join("\n".join(line) for line in lines) + "\n.align 32\n"


ASM = "\n".join([timed(kernel(op, n), setup, body, n) for op, (setup, body) in BODIES.items() for n in NS]
                + [ifill_kernel(n) for n in NS])


def op_slope(suite):
    rom = Rom(suite, "op-slope")
    for op in OPS:
        for n in NS:
            rom.point(f"{op}-n{n}", kernel(op, n), ARGS.get(op, [0]), [("op", op), ("n", n), ("vi", "off")],
                      reps=8, flags=VI_OFF)


BUILDERS = [op_slope]
