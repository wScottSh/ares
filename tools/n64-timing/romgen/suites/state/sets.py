"""The ROM state-roundtrip.sh saves and loads in: MI repeat writes made while an RSP DMA holds
the RDRAM channel, so a repeat write waits posted for its RI grant. The runner saves at a field
boundary, between two instructions; the CPU runs NOPs after each repeat write, so a save can land
while a repeat write is still posted. Each step's pattern is its address plus the rep's start COUNT, and the
ROM prints a sum over every rep of the first and last octbyte of each 128 B block, so a repeat write the loaded
state replays wrong changes the printed line."""
from ... import runtime
from ..bench import asm, benches
from ..bench.sets import SetDef
from ...suite import Step

STATE_BYTES = 64 << 10

ASM = r"""
# args = {delay}. Waits out two VI field starts, then `delay` loop iterations. state-roundtrip.sh
# loads its states after field 0, and a slot that had already made a repeat write would keep its
# own repeat flag through a load that lacks it. The delay walks the phase the field start fixed.
state_settle:
    lw $t3, 0($a0)
    li $t0, 0xA4400010
    li $t2, 2
ss_field:
    lw $t1, 0($t0)
    sltiu $t1, $t1, 10
    bnez $t1, ss_field
    nop
ss_start:
    lw $t1, 0($t0)
    sltiu $t1, $t1, 10
    beqz $t1, ss_start
    nop
    addiu $t2, $t2, -1
    bnez $t2, ss_field
    nop
ss_delay:
    beqz $t3, ss_done
    nop
    b ss_delay
    addiu $t3, $t3, -1
ss_done:
    jr $ra
    nop

# Kernel. args = {addr (KSEG1), bytes}. Per 128 B: queue a 4 KiB RSP DMA DMEM -> RDRAM if the
# DMA queue has room, set MI repeat mode, read MI_MODE back (all older writes done), SD the
# block's address plus the start COUNT, then NOPs while the repeat write waits behind the DMA for the channel.
# Then adds words 3 and 31 (low halves of the first and last octbyte) of every block to RES[2], which keeps its sum across the reps.
k_state_repeat:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    addu $t1, $t0, $t1
    li $t4, 0xA4300000
    li $t5, 0x17F
    li $t7, 0xA4040000
    li $t8, SP_DMA_BUF
    li $t9, 0xFFF
    mfc0 $t2, $count
ksr_loop:
    lw $t6, 0x14($t7)
    bnez $t6, ksr_mode
    nop
    sw $zero, 0($t7)
    sw $t8, 4($t7)
    sw $t9, 0xC($t7)
ksr_mode:
    sw $t5, 0($t4)
    lw $t6, 0($t4)
    addu $t6, $t0, $t2
    sd $t6, 0($t0)
""" + "    nop\n" * 64 + r"""
    addiu $t0, $t0, 128
    bne $t0, $t1, ksr_loop
    nop
ksr_wait:
    lw $t6, 0x18($t7)
    bnez $t6, ksr_wait
    nop
    mfc0 $t3, $count
    lw $t0, 0($a0)
    lw $t6, 0($a1)
ksr_sum:
    lw $t8, 12($t0)
    addu $t6, $t6, $t8
    lw $t8, 124($t0)
    addu $t6, $t6, $t8
    addiu $t0, $t0, 128
    bne $t0, $t1, ksr_sum
    nop
    sw $t6, 0($a1)
    jr $ra
    subu $v0, $t3, $t2
"""


def repeat(suite, delay):
    rom = benches.Rom(suite, "state-repeat")
    rom.point("vi-on", "k_state_repeat", [benches.KSEG1 | benches.MEMSET_BUF, STATE_BYTES],
              [("bytes", STATE_BYTES), ("vi", "on")], reps=128, extra=("sum",),
              pre=[Step("state_settle", [delay], 0)])


#state-roundtrip.sh fails a ROM none of whose saves holds a posted repeat write. These delays
#give 2-3 such saves each; a delay sweep of 0..1262 found none at 80, 100 and 300.
DELAYS = (150, 900, 1262)

SETS = [SetDef(f"state-repeat-{k}", f"state-repeat-{k}", "Bench", "(bench=state-repeat)",
               lambda suite, k=k: repeat(suite, k), [asm.ASM, ASM],
               {"SCRATCH_BASE": runtime.SCRATCH_BASE, "SP_DMA_BUF": benches.SP_DMA_BUF})
        for k in DELAYS]
