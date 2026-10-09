"""Kernels for the calibration kit's own points (sets.py). They follow the bench kernel convention
(suites/bench/asm.py bench_run): a0 = &args, a1 = &RES[2] for extra values, v0 = COUNT ticks.
"""

UNROLL = 16


def repeat(body, n=UNROLL):
    return "\n".join([body] * n)


def timed(name, setup, body, n=UNROLL):
    return f"""
{name}:
{setup}
    mfc0 $t8, $count
{repeat(body, n)}
    mfc0 $t9, $count
    jr $ra
    subu $v0, $t9, $t8
"""


DCB = {
    "k_dcb_sw_lw": "    sw $t5, 0($t0)\n    lw $t6, 4($t0)",
    "k_dcb_sw_nop_lw": "    sw $t5, 0($t0)\n    nop\n    lw $t6, 4($t0)",
    "k_dcb_nop_lw": "    nop\n    lw $t6, 4($t0)",
    "k_dcb_sw_sw": "    sw $t5, 0($t0)\n    sw $t5, 4($t0)",
    "k_dcb_nop_nop": "    nop\n    nop",
}
DCB_SETUP = "    lw $t0, 0($a0)\n    lw $t5, 0($t0)\n    lw $t5, 16($t0)\n    move $t5, $zero"

WB_COUNTS = range(1, 9)
REG_COUNTS = (1, 2, 4, 8)


def store_kernels():
    """k_sw<N>: N back-to-back stores of args[1] to args[0]; k_sw<N>_lw: the same, then one load
    from args[0], so its wait behind the buffered stores is in the time."""
    out = []
    setup = "    lw $t0, 0($a0)\n    lw $t5, 4($a0)\n    lw $t6, 0($t0)\n    nop"
    for n in sorted(set(WB_COUNTS) | set(REG_COUNTS)):
        out.append(timed(f"k_sw{n}", setup, "    sw $t5, 0($t0)", n))
        out.append(timed(f"k_sw{n}_lw", setup, "    sw $t5, 0($t0)", n).replace(
            "    mfc0 $t9, $count", "    lw $t6, 0($t0)\n    mfc0 $t9, $count"))
    return "\n".join(out)


ASM = "\n".join([timed(name, DCB_SETUP, body) for name, body in DCB.items()] + [store_kernels()]) + r"""

# args = {cold}: one call to a function alone in its 32-byte I-cache line; cold = 1 index-invalidates
# the line first, so the call pays one instruction-cache fill.
k_ifill:
    move $t7, $ra
    lw $t1, 0($a0)
    la $t0, cal_ifill_fn
    jalr $t0
    nop
    beqz $t1, kif_time
    nop
    cache 0, 0($t0)
kif_time:
    mfc0 $t8, $count
    jalr $t0
    nop
    mfc0 $t9, $count
    move $ra, $t7
    jr $ra
    subu $v0, $t9, $t8
.align 32
cal_ifill_fn:
    jr $ra
    nop
.align 32

# args = {delay}: waits for vertical blank (V_CURRENT >= 0x200, past vi_init's V_VIDEO end 0x1FF),
# blanks the VI, spins `delay` iterations, selects the 16 bpp type again and times
# the first two VI_V_CURRENT changes. RES[2] = V_CURRENT at the enable, RES[3] = ticks to its first
# change, RES[4] = V_CURRENT after it, RES[5] = ticks to the second change. v0 = RES[3].
k_vi_enable:
    lw $t1, 0($a0)
    li $t0, 0xA4400000
kve_vblank:
    lw $t2, 0x10($t0)
    sltiu $t2, $t2, 0x200
    bnez $t2, kve_vblank
    nop
    sw $zero, 0($t0)
kve_delay:
    addiu $t1, $t1, -1
    bgtz $t1, kve_delay
    nop
    li $t2, 0x324E
    mfc0 $t8, $count
    sw $t2, 0($t0)
    lw $t3, 0x10($t0)
kve_first:
    lw $t4, 0x10($t0)
    beq $t4, $t3, kve_first
    nop
    mfc0 $t9, $count
kve_second:
    lw $t5, 0x10($t0)
    beq $t5, $t4, kve_second
    nop
    mfc0 $t6, $count
    sw $t3, 0($a1)
    subu $v0, $t9, $t8
    sw $v0, 4($a1)
    sw $t4, 8($a1)
    subu $t6, $t6, $t9
    jr $ra
    sw $t6, 12($a1)

# args = {fields}: COUNT ticks over `fields` VI fields, from one V_CURRENT wrap to another.
# RES[2] = the shortest field, RES[3] = the longest.
k_count_fields:
    lw $t1, 0($a0)
    li $t0, 0xA4400010
    li $t6, -1
    move $t7, $zero
    lw $t2, 0($t0)
kcf_sync:
    lw $t3, 0($t0)
    sltu $t4, $t3, $t2
    beqz $t4, kcf_sync
    move $t2, $t3
    mfc0 $t8, $count
    move $t5, $t8
kcf_field:
    lw $t3, 0($t0)
    sltu $t4, $t3, $t2
    beqz $t4, kcf_field
    move $t2, $t3
    mfc0 $t9, $count
    subu $t4, $t9, $t5
    move $t5, $t9
    sltu $t3, $t4, $t6
    beqz $t3, kcf_notmin
    nop
    move $t6, $t4
kcf_notmin:
    sltu $t3, $t7, $t4
    beqz $t3, kcf_notmax
    nop
    move $t7, $t4
kcf_notmax:
    addiu $t1, $t1, -1
    bnez $t1, kcf_field
    nop
    sw $t6, 0($a1)
    sw $t7, 4($a1)
    jr $ra
    subu $v0, $t9, $t8

# args = {list phys, bytes, wait ticks}: freezes the RDP, points START/END at the list, waits, and
# reads how far DPC_CURRENT ran ahead. RES[2] = CURRENT - START frozen, RES[3] = DPC_STATUS frozen.
# Then unfreezes and waits for the DP interrupt of the list's SYNC_FULL. v0 = RES[2].
k_fifo_depth:
    li $t0, 0xA4100000
    li $t1, 0x3C1
    sw $t1, 0xC($t0)
    li $t1, 0x8
    sw $t1, 0xC($t0)
    lw $t2, 0($a0)
    lw $t3, 4($a0)
    addu $t3, $t2, $t3
    sw $t2, 0($t0)
    sw $t3, 4($t0)
    lw $t4, 8($a0)
    mfc0 $t5, $count
kfd_wait:
    mfc0 $t6, $count
    subu $t6, $t6, $t5
    sltu $t6, $t6, $t4
    bnez $t6, kfd_wait
    nop
    lw $t6, 8($t0)
    lw $t7, 0xC($t0)
    subu $v0, $t6, $t2
    sw $v0, 0($a1)
    sw $t7, 4($a1)
    li $t1, 0x4
    sw $t1, 0xC($t0)
    li $t6, 0xA4300000
kfd_done:
    lw $t7, 8($t6)
    andi $t7, $t7, 0x20
    beqz $t7, kfd_done
    nop
    li $t7, 0x800
    jr $ra
    sw $t7, 0($t6)

# args = {list phys, bytes}: starts the list and polls DPC_CURRENT until the DP interrupt, keeping
# every change. RES[2] = changes seen, RES[3] = smallest step, RES[4] = largest step, RES[5] = first
# step (bytes). v0 = ticks to the interrupt.
k_cmd_fetch:
    li $t0, 0xA4100000
    li $t1, 0x3C1
    sw $t1, 0xC($t0)
    lw $t2, 0($a0)
    lw $t3, 4($a0)
    addu $t3, $t2, $t3
    sw $t2, 0($t0)
    li $a2, 0xA4300000
    move $a3, $zero
    li $v1, -1
    move $t9, $zero
    move $t5, $zero
    move $t1, $t2
    mfc0 $t8, $count
    sw $t3, 4($t0)
kcm_poll:
    lw $t4, 8($t0)
    beq $t4, $t1, kcm_same
    subu $t6, $t4, $t1
    bnez $a3, kcm_notfirst
    nop
    move $t5, $t6
kcm_notfirst:
    addiu $a3, $a3, 1
    sltu $t7, $t6, $v1
    beqz $t7, kcm_notmin
    nop
    move $v1, $t6
kcm_notmin:
    sltu $t7, $t9, $t6
    beqz $t7, kcm_notmax
    nop
    move $t9, $t6
kcm_notmax:
    move $t1, $t4
kcm_same:
    lw $t7, 8($a2)
    andi $t7, $t7, 0x20
    beqz $t7, kcm_poll
    nop
    mfc0 $t7, $count
    sw $a3, 0($a1)
    sw $v1, 4($a1)
    sw $t9, 8($a1)
    sw $t5, 12($a1)
    li $t6, 0x800
    sw $t6, 0($a2)
    jr $ra
    subu $v0, $t7, $t8

# args = {list phys, bytes, spin}: freezes the RDP, spins `spin` iterations (so the reps and points
# walk the poll's phase against the fetches), points START/END at the list and polls DPC_CURRENT 64
# times while the frozen FIFO fills. RES[2] = mask of the offsets seen (bit i: CURRENT - START = 8 i,
# i < 32), RES[3] = the first offset other than 0, RES[4] = the offset after the polls. Then unfreezes
# and waits for the list's DP interrupt. v0 = ticks of the 64 polls.
k_fetch_frozen:
    li $t0, 0xA4100000
    li $t1, 0x3C1
    sw $t1, 0xC($t0)
    li $t1, 0x8
    sw $t1, 0xC($t0)
    lw $t2, 0($a0)
    lw $t3, 4($a0)
    lw $t4, 8($a0)
kff_spin:
    addiu $t4, $t4, -1
    bgez $t4, kff_spin
    nop
    addu $t3, $t2, $t3
    move $a2, $zero
    move $a3, $zero
    li $t5, 64
    sw $t2, 0($t0)
    mfc0 $t8, $count
    sw $t3, 4($t0)
kff_poll:
    lw $t6, 8($t0)
    subu $t6, $t6, $t2
    bnez $a3, kff_first_known
    nop
    move $a3, $t6
kff_first_known:
    srl $t7, $t6, 3
    sltiu $t1, $t7, 32
    beqz $t1, kff_next
    addiu $t1, $zero, 1
    sllv $t1, $t1, $t7
    or $a2, $a2, $t1
kff_next:
    addiu $t5, $t5, -1
    bnez $t5, kff_poll
    nop
    mfc0 $t9, $count
    sw $a2, 0($a1)
    sw $a3, 4($a1)
    sw $t6, 8($a1)
    li $t1, 0x4
    sw $t1, 0xC($t0)
    li $t6, 0xA4300000
kff_done:
    lw $t7, 8($t6)
    andi $t7, $t7, 0x20
    beqz $t7, kff_done
    nop
    li $t7, 0x800
    sw $t7, 0($t6)
    jr $ra
    subu $v0, $t9, $t8

# args = {response block, uncached}: reads the four channels of a joybus status frame's reply.
# RES[2] = channels that answered (bit i: channel i's rx byte has no error bit), RES[3] = channels
# whose status reports an accessory (Controller Pak, Rumble Pak). v0 = 0.
k_pads:
    lw $t0, 0($a0)
    move $t1, $zero
    move $t2, $zero
    addiu $t3, $zero, 1
    addiu $t4, $zero, 4
kpd_loop:
    lbu $t5, 2($t0)
    andi $t5, $t5, 0xC0
    bnez $t5, kpd_next
    nop
    or $t1, $t1, $t3
    lbu $t5, 6($t0)
    andi $t5, $t5, 1
    beqz $t5, kpd_next
    nop
    or $t2, $t2, $t3
kpd_next:
    sll $t3, $t3, 1
    addiu $t4, $t4, -1
    bnez $t4, kpd_loop
    addiu $t0, $t0, 8
    sw $t1, 0($a1)
    sw $t2, 4($a1)
    jr $ra
    move $v0, $zero

# args = {length register, length - 1, DRAM address, n}: n SP DMAs of one size between DMEM 0 and one
# DRAM address, each written as soon as SP_DMA_FULL clears, then SP_DMA_BUSY polled clear. v0 = ticks.
k_sp_chain:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    lw $t3, 12($a0)
    li $t4, 0xA4040000
    mfc0 $t8, $count
ksc_loop:
    lw $t5, 0x14($t4)
    andi $t5, $t5, 1
    bnez $t5, ksc_loop
    nop
    sw $zero, 0($t4)
    sw $t2, 4($t4)
    sw $t1, 0($t0)
    addiu $t3, $t3, -1
    bnez $t3, ksc_loop
    nop
ksc_wait:
    lw $t5, 0x18($t4)
    andi $t5, $t5, 1
    bnez $t5, ksc_wait
    nop
    mfc0 $t9, $count
    jr $ra
    subu $v0, $t9, $t8
"""
