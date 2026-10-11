"""The ROM state-roundtrip.sh saves and loads in: MI repeat writes made while an RSP DMA holds
the RDRAM channel, so a repeat write waits posted for its RI grant. The runner saves at a field
boundary, between two instructions; the CPU runs NOPs after each repeat write, so a save can land
while a repeat write is still posted. Each step's pattern is its address plus the rep's start COUNT, and the
ROM prints a sum over every rep of the first and last octbyte of each 128 B block, so a repeat write the loaded
state replays wrong changes the printed line."""
from ... import runtime
from ..bench import asm, benches
from ..bench.sets import SetDef

STATE_BYTES = 64 << 10

ASM = r"""
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


def repeat(suite):
    rom = benches.Rom(suite, "state-repeat")
    rom.point("vi-on", "k_state_repeat", [benches.KSEG1 | benches.MEMSET_BUF, STATE_BYTES],
              [("bytes", STATE_BYTES), ("vi", "on")], reps=128, extra=("sum",))


#The runner reports the posted repeat writes at each save and state-roundtrip.sh fails unless a
#save of each ROM holds one. With 64 NOPs (32 left some boot delays without one, 850 and 900
#among them), every delay of 600..1300 tried has such a save among fields 1-9.
DELAYS = (680, 1262)

SETS = [SetDef(f"state-repeat-{k}", f"state-repeat-{k}", "Bench", "(bench=state-repeat)", repeat, [asm.ASM, ASM],
               {"SCRATCH_BASE": runtime.SCRATCH_BASE, "BOOT_DELAY": k, "LAYOUT_PAD": 0,
                "SP_DMA_BUF": benches.SP_DMA_BUF})
        for k in DELAYS]
