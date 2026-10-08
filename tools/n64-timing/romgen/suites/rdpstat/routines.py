"""Step routines for the rdpstat suite. a0 = params, a1 = &RES[res] (romgen runtime convention).

Register accesses are single uncached loads and stores, the way the Rust and C++ sources do
them through volatile pointers.
"""
from ...suite import Check, Step
from ... import runtime as rt


def write32(addr, value):
    return Step("step_write32", [addr, value])


def read32(addr, res, mask=0xFFFFFFFF):
    return Step("step_read32", [addr, mask], res)


def read16(addr, res):
    return Step("step_read16", [addr], res)


def wait_eq(addr, mask, goal, iterations, res):
    """Polls (*addr & mask) == goal up to `iterations` reads; RES = the last masked value."""
    return Step("step_wait_eq", [addr, mask, goal, iterations], res)


def res_mask(src, mask, res):
    """RES[res] = RES[src] & mask, to assert single bits of one register read."""
    return Step("step_res_mask", [src, mask], res)


def res_eq(a, b, res):
    """RES[res] = 1 when RES[a] == RES[b], else 0, to compare two outcomes of one ROM."""
    return Step("step_res_eq", [a, b], res)


def fill32(addr, words, value):
    return Step("step_fill32", [addr, words, value])


def rle_diff(addr, stride, width, rows, rle_label, res):
    """Counts pixels of a width x rows RGBA16 region at `addr` (rows `stride` bytes apart) that
    differ from a run-length reference: words (run - 1) << 16 | pixel, in row-major order."""
    return Step("step_rle_diff", [addr, stride, width, rows, rle_label], res)


def eq(res, expected, msg):
    return Check(rt.CHK_EQ_HEX, res, expected, msg=msg)


def eq_dec(res, expected, msg):
    return Check(rt.CHK_EQ_DEC, res, expected, msg=msg)


def in_range(res, lo, hi, msg):
    return Check(rt.CHK_RANGE, res, lo, hi, msg=msg)


ASM = r"""
step_write32:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    jr $ra
    sw $t1, 0($t0)

step_read32:
    lw $t0, 0($a0)
    lw $t2, 4($a0)
    lw $t1, 0($t0)
    and $t1, $t1, $t2
    jr $ra
    sw $t1, 0($a1)

step_read16:
    lw $t0, 0($a0)
    lhu $t1, 0($t0)
    jr $ra
    sw $t1, 0($a1)

step_wait_eq:
    lw $t0, 0($a0)
    lw $t2, 4($a0)
    lw $t3, 8($a0)
    lw $t4, 12($a0)
swe_loop:
    lw $t1, 0($t0)
    and $t1, $t1, $t2
    beq $t1, $t3, swe_done
    addiu $t4, $t4, -1
    bnez $t4, swe_loop
    nop
swe_done:
    jr $ra
    sw $t1, 0($a1)

step_res_mask:
    lw $t0, 0($a0)
    lw $t2, 4($a0)
    sll $t0, $t0, 2
    la $t1, DATA_BASE + D_RES
    addu $t0, $t0, $t1
    lw $t1, 0($t0)
    and $t1, $t1, $t2
    jr $ra
    sw $t1, 0($a1)

step_res_eq:
    lw $t0, 0($a0)
    lw $t2, 4($a0)
    la $t1, DATA_BASE + D_RES
    sll $t0, $t0, 2
    addu $t0, $t0, $t1
    sll $t2, $t2, 2
    addu $t2, $t2, $t1
    lw $t0, 0($t0)
    lw $t2, 0($t2)
    xor $t0, $t0, $t2
    sltiu $t0, $t0, 1
    jr $ra
    sw $t0, 0($a1)

step_fill32:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
sf_loop:
    beqz $t1, sf_done
    addiu $t1, $t1, -1
    sw $t2, 0($t0)
    b sf_loop
    addiu $t0, $t0, 4
sf_done:
    jr $ra
    nop

step_rle_diff:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    lw $t3, 12($a0)
    lw $t4, 16($a0)
    move $v0, $zero
    move $t5, $zero
    move $t6, $zero
srd_row:
    beqz $t3, srd_done
    move $t7, $t0
    move $t8, $t2
srd_px:
    bnez $t5, srd_cmp
    nop
    lw $t9, 0($t4)
    addiu $t4, $t4, 4
    srl $t5, $t9, 16
    addiu $t5, $t5, 1
    andi $t6, $t9, 0xFFFF
srd_cmp:
    lhu $t9, 0($t7)
    beq $t9, $t6, srd_same
    addiu $t5, $t5, -1
    addiu $v0, $v0, 1
srd_same:
    addiu $t8, $t8, -1
    bnez $t8, srd_px
    addiu $t7, $t7, 2
    addiu $t3, $t3, -1
    b srd_row
    addu $t0, $t0, $t1
srd_done:
    jr $ra
    sw $v0, 0($a1)
"""
