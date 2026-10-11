"""Single MI repeat writes, VI off (kit-dma, question repeat-write; prehw-plan.md U-REPEAT-KIT).

Each iteration sets MI_MODE to repeat mode with one RepeatCount and stores one doubleword, which the MI
turns into one repeat write (n64brew MIPS_Interface: repeat mode "Automatically clears after a single
Rambus write"). N = 16 and 64 iterations at one RDRAM address, so the N = 64 less N = 16 COUNT is 48
writes and every constant term (the write buffer filling, the writes still buffered at the closing
mfc0) cancels. RepeatCount 7 and 8 straddle one octbyte, 119 and 127 the last octbyte of a 128 B write.
"""
from ..bench.benches import KSEG1, MEMSET_BUF, VI_OFF, Rom

COUNTS = [7, 8, 119, 127]
NS = [16, 64]
MI_MODE_SET_REPEAT = 0x100

ASM = r"""
# args = {RDRAM address (KSEG1), N, MI_MODE value}. N times: MI_MODE = value, then one SD to the address.
k_repeat_n:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t5, 8($a0)
    li $t4, 0xA4300000
    mfc0 $t2, $count
krn_loop:
    sw $t5, 0($t4)
    sd $zero, 0($t0)
    addiu $t1, $t1, -1
    bnez $t1, krn_loop
    nop
    mfc0 $t3, $count
    jr $ra
    subu $v0, $t3, $t2
"""


def repeat_write(suite):
    rom = Rom(suite, "mi-repeat-write")
    for rc in COUNTS:
        for n in NS:
            rom.point(f"rc{rc}-n{n}", "k_repeat_n", [KSEG1 | MEMSET_BUF, n, MI_MODE_SET_REPEAT | rc],
                      [("rc", rc), ("n", n), ("vi", "off")], flags=VI_OFF)


BUILDERS = [repeat_write]
