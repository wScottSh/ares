"""Hand-ported test bodies that are not plain cycle measurements.

Each routine is a step: a0 = params, a1 = result pointer (RES[]). Routines save the
callee-saved registers they use. The instruction sequences inside each test keep the shape
of nemu64-test's inline asm, since the timing between those instructions is what the test
observes; the surrounding Rust (loops, comparisons) becomes plain runtime code.
"""

COMMON = r"""
# Shared by tests that expect an exception (nemu64-test exception_handler::expect_exception).
# expect_begin: a0 = instructions to skip on the exception. expect_end: a0 = result pointer,
# writes {count, cause, status, epc, vector, badvaddr} (low 32 bits) and fcsr and clears the record.
expect_begin:
    la $t0, DATA_BASE
    sw $zero, D_SEEN($t0)
    sw $zero, D_STREAK($t0)
    jr $ra
    sw $a0, D_SKIP($t0)

expect_end:
    la $t0, DATA_BASE
    sw $zero, D_SKIP($t0)
    lw $t1, D_SEEN($t0)
    sw $t1, 0($a0)
    lw $t1, D_EXC_CAUSE($t0)
    sw $t1, 4($a0)
    lw $t1, D_EXC_STATUS($t0)
    sw $t1, 8($a0)
    lw $t1, D_EXC_EPC + 4($t0)
    sw $t1, 12($a0)
    lw $t1, D_EXC_VECTOR + 4($t0)
    sw $t1, 16($a0)
    lw $t1, D_EXC_BADVADDR + 4($t0)
    sw $t1, 20($a0)
    lw $t1, D_EXC_FCSR($t0)
    sw $t1, 24($a0)
    sw $zero, D_EXC_CAUSE($t0)
    sw $zero, D_SEEN($t0)
    jr $ra
    sw $zero, D_STREAK($t0)

# Copies expect_end's seven words at $t0 to res[0..6] at $a1.
copy_exception_record:
    addiu $t2, $zero, 7
cer_loop:
    lw $t1, 0($t0)
    sw $t1, 0($a1)
    addiu $t0, $t0, 4
    addiu $t2, $t2, -1
    bnez $t2, cer_loop
    addiu $a1, $a1, 4
    jr $ra
    addiu $a1, $a1, -28

# cop0::clear_tlb: every entry gets EntryHi.ASID = 1 so nothing matches.
step_clear_tlb:
    mtc0 $zero, $entrylo0
    mtc0 $zero, $entrylo1
    li $t0, 1
    dmtc0 $t0, $entryhi
    mtc0 $zero, $pagemask
    move $t1, $zero
ct_loop:
    mtc0 $t1, $index
    nop
    nop
    tlbwi
    addiu $t1, $t1, 1
    sltiu $t2, $t1, 32
    bnez $t2, ct_loop
    nop
    jr $ra
    dmtc0 $zero, $entryhi

# preset_cause_to_copindex2 (src/cop0.rs): MFC2 with COP2 unusable, skip it, and report
# whether Cause came back as CpU with CE = 2. res[0] = 1 on success.
step_preset_cop2:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    sd $a1, 8($sp)
    jal expect_begin
    addiu $a0, $zero, 1
    mfc2 $zero, 0
    la $a0, DATA_BASE + D_DECBUF
    jal expect_end
    nop
    ld $a1, 8($sp)
    la $t0, DATA_BASE + D_DECBUF
    lw $t1, 0($t0)
    lw $t2, 4($t0)
    li $t3, 0x3000007C
    and $t2, $t2, $t3
    li $t3, 0x2000002C
    xor $t2, $t2, $t3
    addiu $t1, $t1, -1
    or $t2, $t2, $t1
    sltiu $t2, $t2, 1
    sw $t2, 0($a1)
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16
"""

TIMING = r"""
# timing::RepeatedMFC0Count. res[0..81] = the differences array (10 rows x 8, plus the
# overflow word the 9th SW of the last row writes), res[90] = first mismatch + 1 or 0.
step_repeated_mfc0:
    move $t8, $a1
    li $t9, 10
rm_loop:
    mfc0 $t0, $count
    mfc0 $t1, $count
    mfc0 $t2, $count
    mfc0 $t3, $count
    mfc0 $t4, $count
    mfc0 $t5, $count
    mfc0 $t6, $count
    mfc0 $t7, $count
    mfc0 $a2, $count
    mfc0 $a3, $count
    sub $v0, $t1, $t0
    sw $v0, 0($t8)
    sub $v0, $t2, $t1
    sw $v0, 4($t8)
    sub $v0, $t3, $t2
    sw $v0, 8($t8)
    sub $v0, $t4, $t3
    sw $v0, 12($t8)
    sub $v0, $t5, $t4
    sw $v0, 16($t8)
    sub $v0, $t6, $t5
    sw $v0, 20($t8)
    sub $v0, $t7, $t6
    sw $v0, 24($t8)
    sub $v0, $a2, $t7
    sw $v0, 28($t8)
    sub $v0, $a3, $a2
    sw $v0, 32($t8)
    addi $t8, $t8, 32
    addi $t9, $t9, -1
    bne $t9, $zero, rm_loop
    nop
    move $v0, $zero
    li $t0, 1
rm_row:
    sll $t1, $t0, 5
    addu $t1, $t1, $a1
    lw $t2, 0($t1)
    sltu $t2, $zero, $t2
    move $t3, $zero
rm_col:
    sll $t4, $t3, 2
    addu $t4, $t4, $t1
    lw $t4, 0($t4)
    andi $t5, $t3, 1
    xor $t5, $t5, $t2
    beq $t4, $t5, rm_ok
    nop
    sll $v0, $t0, 4
    or $v0, $v0, $t3
    b rm_done
    addiu $v0, $v0, 1
rm_ok:
    addiu $t3, $t3, 1
    sltiu $t4, $t3, 8
    bnez $t4, rm_col
    nop
    addiu $t0, $t0, 1
    sltiu $t4, $t0, 10
    bnez $t4, rm_row
    nop
rm_done:
    jr $ra
    sw $v0, 360($a1)

# timing::HalfCycleExactCalibration for one COUNT value (a0 = params: {count_value}).
# res = {out0, out1, out2, out3}
step_half_cycle:
    lw $t9, 0($a0)
    mfc0 $t8, $count
    li $v0, 2
hc_loop:
    nop
    mtc0 $t9, $count
    nop
    nop
    mfc0 $t0, $count
    mfc0 $t1, $count
    mfc0 $t2, $count
    mfc0 $t3, $count
    addi $v0, $v0, -1
    bne $v0, $zero, hc_loop
    nop
    mtc0 $t8, $count
    sw $t0, 0($a1)
    sw $t1, 4($a1)
    sw $t2, 8($a1)
    jr $ra
    sw $t3, 12($a1)

# timing::cache::CacheSizeTest::fits_within_cache(size, 16) for a0 = {size}. res[0] = 1 if
# every 16-byte step took exactly 3 COUNT ticks on the second pass.
step_cache_size:
    lw $t0, 0($a0)
    li $t1, SCRATCH_BASE
    li $t2, 16
    li $t3, 2
cs_outer:
    ori $t4, $t0, 0
    ori $t5, $t1, 0
cs_inner:
    mfc0 $t6, $count
    subu $t4, $t4, $t2
    sw $t6, 0($t5)
    addu $t5, $t5, $t2
    bne $t4, $zero, cs_inner
    nop
    addiu $t3, $t3, -1
    bne $t3, $zero, cs_outer
    nop
    lw $t6, 0($t1)
    li $t7, 16
    li $v0, 1
cs_check:
    sltu $t8, $t7, $t0
    beqz $t8, cs_done
    nop
    addu $t8, $t1, $t7
    lw $t8, 0($t8)
    subu $t9, $t8, $t6
    move $t6, $t8
    addiu $t9, $t9, -3
    bnez $t9, cs_fail
    nop
    b cs_check
    addiu $t7, $t7, 16
cs_fail:
    move $v0, $zero
cs_done:
    jr $ra
    sw $v0, 0($a1)

# cop0::RandomDecrement: res[4*wired + k] = Random after 1, 16, 31, 100 instructions.
step_random_decrement:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    move $t9, $zero
    move $t8, $a1
rd_loop:
    jal random_decrement_perform
    move $a0, $t9
    sw $v0, 0($t8)
    sw $v1, 4($t8)
    sw $a2, 8($t8)
    sw $a3, 12($t8)
    addiu $t8, $t8, 16
    addiu $t9, $t9, 1
    sltiu $t0, $t9, 64
    bnez $t0, rd_loop
    nop
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16

random_decrement_perform:
    nop
    mtc0 $a0, $wired
    nop
    nop
    mfc0 $v0, $random
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop
    mfc0 $v1, $random
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop
    mfc0 $a2, $random
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    nop; nop; nop; nop; nop
    nop; nop; nop
    mfc0 $a3, $random
    jr $ra
    nop

# cop0::RandomMasking: res[0] = Random read back after writing it.
step_random_masking:
    move $t0, $zero
    li $t1, 0xFFFFFFFF
    nop
    mtc0 $t0, $wired
    nop
    nop
    mtc0 $t1, $random
    nop
    nop
    mfc0 $t2, $random
    jr $ra
    sw $t2, 0($a1)

# cop0::CountOverflow: res = {count32 hi, count32 lo, count64 hi, count64 lo}
step_count_overflow:
    mfc0 $t9, $count
    li $t0, 0xF0FF0012
    dsll32 $t0, $t0, 0
    li $t1, 0xFFFFFFFD
    dsll32 $t1, $t1, 0
    dsrl32 $t1, $t1, 0
    or $t0, $t0, $t1
    dmtc0 $t0, $count
    nop; nop; nop; nop; nop; nop; nop; nop; nop; nop; nop; nop
    mfc0 $t2, $count
    dmfc0 $t3, $count
    mtc0 $t9, $count
    dsrl32 $t4, $t2, 0
    sw $t4, 0($a1)
    sw $t2, 4($a1)
    dsrl32 $t4, $t3, 0
    sw $t4, 8($a1)
    jr $ra
    sw $t3, 12($a1)

# cop0::compare::CompareInterruptSignalling2. a0 = {offset, op1, op2, op3}.
# res = {iterations, target, count_out}. The three ops are patched into a copy of the
# sequence in the scratch buffer, like the Rust's const-generic instantiations.
step_compare_signalling:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    move $s0, $a0
    move $s1, $a1
    la $t0, compare_template
    la $t1, compare_template_end
    li $t2, SCRATCH_BASE | 0x20000000
cmp_copy:
    lw $t3, 0($t0)
    sw $t3, 0($t2)
    addiu $t0, $t0, 4
    bne $t0, $t1, cmp_copy
    addiu $t2, $t2, 4
    li $t2, SCRATCH_BASE | 0x20000000
    lw $t3, 4($s0)
    sw $t3, compare_ops - compare_template($t2)
    lw $t3, 8($s0)
    sw $t3, compare_ops - compare_template + 4($t2)
    lw $t3, 12($s0)
    sw $t3, compare_ops - compare_template + 8($t2)
    li $a0, SCRATCH_BASE
    jal invalidate_range
    addiu $a1, $zero, compare_template_end - compare_template
    lw $5, 0($s0)
    li $t9, SCRATCH_BASE
    jalr $t9
    nop
    sw $3, 0($s1)
    sw $6, 4($s1)
    sw $4, 8($s1)
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    jr $ra
    addiu $sp, $sp, 32

compare_template:
    ori $7, $0, 500
cmp_0:
    mfc0 $6, $count
    mfc0 $8, $count
    beq $6, $8, cmp_1
    nop
    nop
cmp_1:
    mfc0 $6, $count
    addu $6, $6, $5
    addu $6, $6, $7
compare_ops:
    nop
    nop
    nop
    lui $3, 0
cmp_2:
    mfc0 $4, $cause
    srl $4, $4, 15
    andi $4, $4, 1
    beqzl $4, cmp_2
    addiu $3, $3, 1
    bne $7, $0, cmp_0
    addiu $7, $7, -500
    mfc0 $4, $count
    jr $ra
    nop
compare_template_end:

# The polling loop's cost depends on its I-cache line alignment, and the Value's range is 20 clocks
# wide, so the routine starts on a line.
.align 32
# rsp_timing::ClockCPUvsRSP: res[0] = DP clock delta (24 bit) over 100000 COUNT ticks
step_dp_clock_vs_cpu:
    li $t0, 0xA4100000
    li $t1, 8
    sw $t1, 0x0C($t0)
    mfc0 $t2, $count
    lw $t3, 0x10($t0)
    li $t4, 100000
    addu $t4, $t2, $t4
    sltu $t5, $t4, $t2
dc_loop:
    mfc0 $t6, $count
    lw $t7, 0x10($t0)
    beqz $t5, dc_noovf
    sltu $t8, $t6, $t2
    beqz $t8, dc_loop
    nop
dc_noovf:
    sltu $t8, $t6, $t4
    bnez $t8, dc_loop
    nop
    li $t1, 4
    sw $t1, 0x0C($t0)
    subu $t7, $t7, $t3
    li $t1, 0xFFFFFF
    and $t7, $t7, $t1
    jr $ra
    sw $t7, 0($a1)

# rsp_timing::ClockFoolishlyAttemptToWrite: res[0] = (clock_after - clock_before) & 0xFFFFFF
step_dp_clock_write:
    li $t0, 0xA4100010
    li $t9, 0xFFFFFF
    lw $t1, 0($t0)
    and $t1, $t1, $t9
    li $t2, 0x0FFFFF
    subu $t2, $t1, $t2
    and $t2, $t2, $t9
    sw $t2, 0($t0)
    lw $t3, 0($t0)
    and $t3, $t3, $t9
    subu $t3, $t3, $t1
    and $t3, $t3, $t9
    jr $ra
    sw $t3, 0($a1)

# rsp_timing::ClockIsMasked: res = {a, b, first clock, clock after the 24-bit wrap}.
# If the clock does not advance (a == b) the wrap wait is skipped, as in the Rust early return.
step_dp_clock_masked:
    li $t0, 0xA4100010
    lw $t1, 0($t0)
    lw $t2, 0($t0)
    sw $t1, 0($a1)
    sw $t2, 4($a1)
    sw $zero, 8($a1)
    beq $t1, $t2, dm_done
    sw $zero, 12($a1)
    li $t9, 0xFFFFFF
    lw $t3, 0($t0)
    sw $t3, 8($a1)
dm_loop:
    lw $t4, 0($t0)
    and $t5, $t4, $t9
    and $t6, $t3, $t9
    sltu $t7, $t5, $t6
    bnez $t7, dm_wrapped
    nop
    b dm_loop
    move $t3, $t4
dm_wrapped:
    sw $t4, 12($a1)
dm_done:
    jr $ra
    nop

# rsp_timing::CyclesSLL: runs the RSP program, res[0] = DP clock delta - 9
step_rsp_sll:
    la $t0, rsp_sll_program
    la $t1, rsp_sll_program_end
    li $t2, 0xA4001000
rs_copy:
    lw $t3, 0($t0)
    sw $t3, 0($t2)
    addiu $t0, $t0, 4
    bne $t0, $t1, rs_copy
    addiu $t2, $t2, 4
    li $t0, 0xA4080000
    sw $zero, 0($t0)
    li $t0, 0xA4040010
    li $t1, 0x89
    sw $t1, 0($t0)
rs_wait:
    lw $t1, 0($t0)
    andi $t1, $t1, 1
    beqz $t1, rs_wait
    nop
    li $t0, 0xA4000FF8
    lw $t1, 0($t0)
    lw $t2, 4($t0)
    subu $t2, $t2, $t1
    li $t3, 0xFFFFFF
    and $t2, $t2, $t3
    addiu $t2, $t2, -9
    jr $ra
    sw $t2, 0($a1)

rsp_sll_program:
    mfc0 $k0, 12
    nop
    nop
    nop
    nop
    sll $a0, $a1, 5
    nop
    nop
    nop
    nop
    mfc0 $k1, 12
    sw $k0, 0xFF8($zero)
    sw $k1, 0xFFC($zero)
    break
rsp_sll_program_end:
"""
