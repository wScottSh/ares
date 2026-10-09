"""On-target routines for the bench suite.

Steps follow the runtime's step convention: a0 = params, a1 = &RES[step.res]. Kernels are
leaf routines that bench_run calls once per repetition; they may clobber t*, a*, v* and must
leave s* alone. Every bench line goes out through emux XLOG as
"#bench <rom> <point> key=value ...".
"""

ASM = r"""
# a0 = {kernel, reps, flags, kernel args...}. flags bit 0: VI blanked during the reps.
# RES[0] = min ticks, RES[1] = max ticks over the reps. The kernel gets a0 = &args and
# a1 = &RES[2] (extra values; the last rep's survive) and returns v0 = COUNT ticks.
bench_run:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    move $s0, $a0
    move $s3, $a1
    addiu $t0, $zero, -1
    sw $t0, 0($s3)
    sw $zero, 4($s3)
    lw $s1, 4($s0)
    lw $t0, 8($s0)
    andi $t0, $t0, 1
    beqz $t0, br_loop
    nop
    jal vi_set_type
    move $a0, $zero
    move $s2, $v0
br_loop:
    lw $t9, 0($s0)
    addiu $a0, $s0, 12
    jalr $t9
    addiu $a1, $s3, 8
    lw $t0, 0($s3)
    sltu $t1, $v0, $t0
    beqz $t1, br_nomin
    nop
    sw $v0, 0($s3)
br_nomin:
    lw $t0, 4($s3)
    sltu $t1, $t0, $v0
    beqz $t1, br_nomax
    nop
    sw $v0, 4($s3)
br_nomax:
    addiu $s1, $s1, -1
    bnez $s1, br_loop
    nop
    lw $t0, 8($s0)
    andi $t0, $t0, 1
    beqz $t0, br_out
    nop
    jal vi_set_type
    move $a0, $s2
br_out:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    jr $ra
    addiu $sp, $sp, 48

# a0 = {prefix string, nfields, (key string, RES index)...}. Prints the prefix, then
# " key=value" per field, as one XLOG line.
bench_emit:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    move $s0, $a0
    jal pr_str
    lw $a0, 0($s0)
    lw $s1, 4($s0)
    addiu $s0, $s0, 8
be_loop:
    beqz $s1, be_done
    nop
    la $a0, str_space
    jal pr_str
    nop
    jal pr_str
    lw $a0, 0($s0)
    lw $t0, 4($s0)
    sll $t0, $t0, 2
    la $t1, DATA_BASE + D_RES
    addu $t0, $t0, $t1
    jal pr_dec
    lw $a0, 0($t0)
    addiu $s0, $s0, 8
    b be_loop
    addiu $s1, $s1, -1
be_done:
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    jr $ra
    addiu $sp, $sp, 32

# Step. a0 = {prologue, prologue words, body, body words, n, epilogue, epilogue words, dst}.
# Writes prologue + n x body + epilogue to dst (an uncached address).
bench_list_step:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    lw $t9, 28($a0)
    lw $t0, 0($a0)
    jal bl_copy
    lw $t1, 4($a0)
    lw $t2, 16($a0)
bl_rep:
    beqz $t2, bl_epi
    nop
    lw $t0, 8($a0)
    jal bl_copy
    lw $t1, 12($a0)
    b bl_rep
    addiu $t2, $t2, -1
bl_epi:
    lw $t0, 20($a0)
    jal bl_copy
    lw $t1, 24($a0)
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16
bl_copy:
    beqz $t1, bl_ret
    nop
    lw $t3, 0($t0)
    sw $t3, 0($t9)
    addiu $t0, $t0, 4
    addiu $t9, $t9, 4
    b bl_copy
    addiu $t1, $t1, -1
bl_ret:
    jr $ra
    nop

# Kernel. args = {addr, bytes}. SD $zero over [addr, addr+bytes), 64 B per iteration.
k_memset_sd:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    addu $t1, $t0, $t1
    mfc0 $t2, $count
kms_loop:
    sd $zero, 0($t0)
    sd $zero, 8($t0)
    sd $zero, 16($t0)
    sd $zero, 24($t0)
    sd $zero, 32($t0)
    sd $zero, 40($t0)
    sd $zero, 48($t0)
    sd $zero, 56($t0)
    addiu $t0, $t0, 64
    bne $t0, $t1, kms_loop
    nop
    mfc0 $t3, $count
    jr $ra
    subu $v0, $t3, $t2

# Kernel. args = {addr (KSEG1), bytes}. MI repeat mode: one SD per 128 B with
# MI_MODE = repeat length 127 | set repeat mode (n64brew MIPS_Interface MI_MODE).
k_memset_repeat:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    addu $t1, $t0, $t1
    li $t4, 0xA4300000
    li $t5, 0x17F
    mfc0 $t2, $count
kmr_loop:
    sw $t5, 0($t4)
    sd $zero, 0($t0)
    addiu $t0, $t0, 128
    bne $t0, $t1, kmr_loop
    nop
    mfc0 $t3, $count
    jr $ra
    subu $v0, $t3, $t2

# Kernel. args = {dram phys addr, bytes}. RSP DMA DMEM 0 -> RDRAM in 4 KiB transfers,
# queued as soon as SP_DMA_FULL clears; ends when SP_DMA_BUSY clears.
k_memset_spdma:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    addu $t1, $t0, $t1
    li $t4, 0xA4040000
    li $t5, 0xFFF
    lw $t6, 0x18($t4)
    mfc0 $t2, $count
kmd_loop:
    lw $t6, 0x14($t4)
    bnez $t6, kmd_loop
    nop
    sw $zero, 0($t4)
    sw $t0, 4($t4)
    sw $t5, 0xC($t4)
    li $t6, 0x1000
    addu $t0, $t0, $t6
    bne $t0, $t1, kmd_loop
    nop
kmd_wait:
    lw $t6, 0x18($t4)
    bnez $t6, kmd_wait
    nop
    mfc0 $t3, $count
    jr $ra
    subu $v0, $t3, $t2

# Kernel. args = {base, s1 off, s1 val, s2 off, s2 val, trigger off, trigger val, poll off,
# poll mask, after off, after val}. Two setup writes, a read of the poll register to drain the
# write buffer, then COUNT, the trigger write, a poll until (reg & mask) == 0, COUNT, and a
# final write (interrupt acknowledge).
k_mmio_dma:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    addu $t1, $t1, $t0
    lw $t2, 8($a0)
    sw $t2, 0($t1)
    lw $t1, 12($a0)
    addu $t1, $t1, $t0
    lw $t2, 16($a0)
    sw $t2, 0($t1)
    lw $t1, 20($a0)
    addu $t1, $t1, $t0
    lw $t2, 24($a0)
    lw $t3, 28($a0)
    addu $t3, $t3, $t0
    lw $t4, 32($a0)
    lw $t5, 0($t3)
    mfc0 $t6, $count
    sw $t2, 0($t1)
kmm_poll:
    lw $t5, 0($t3)
    and $t5, $t5, $t4
    bnez $t5, kmm_poll
    nop
    mfc0 $t7, $count
    lw $t1, 36($a0)
    addu $t1, $t1, $t0
    lw $t2, 40($a0)
    sw $t2, 0($t1)
    jr $ra
    subu $v0, $t7, $t6

# Kernel. args = {prime (KSEG1), prime is a write, target (KSEG1)}. Opens the prime row
# clean (LW) or dirty (SW then LW, which also drains the write buffer), then times one
# uncached LW of the target.
k_row:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    beqz $t1, kr_read
    nop
    sw $zero, 0($t0)
kr_read:
    lw $t3, 0($t0)
    mfc0 $t4, $count
    lw $t5, 0($t2)
    addu $t5, $t5, $zero
    mfc0 $t6, $count
    jr $ra
    subu $v0, $t6, $t4

# Kernel. args = {A, victim (0 invalid, 1 clean, 2 dirty), gap (-1 = no second miss),
# B = A + 8 KiB (same D-cache index), C (other index), drain (KSEG1)}. Times a LW miss on B
# that evicts A's line, optionally followed after `gap` loop iterations by a LW miss on C.
k_dmiss:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    lw $t3, 12($a0)
    lw $t4, 16($a0)
    lw $a2, 20($a0)
    cache 1, 0($t0)
    cache 1, 0($t4)
    beqz $t1, kd_settle
    nop
    lw $t5, 0($t0)
    addiu $t6, $t1, -2
    bnez $t6, kd_settle
    nop
    sw $t5, 0($t0)
kd_settle:
    lw $t7, 0($a2)
    addiu $t6, $zero, 64
kd_spin:
    bnez $t6, kd_spin
    addiu $t6, $t6, -1
    mfc0 $t8, $count
    lw $t9, 0($t3)
    addu $t9, $t9, $zero
    bltz $t2, kd_end
    nop
kd_gap:
    bnez $t2, kd_gap
    addiu $t2, $t2, -1
    lw $t9, 0($t4)
    addu $t9, $t9, $zero
kd_end:
    mfc0 $t6, $count
    jr $ra
    subu $v0, $t6, $t8

# Kernel. args = {list phys addr, list bytes}. Clears the DPC counters, runs the list from
# RDRAM, waits for the DP interrupt (SYNC_FULL), then stores DPC_CLOCK, DPC_BUFBUSY,
# DPC_PIPEBUSY and DPC_TMEM to a1[0..3] and acknowledges the interrupt.
k_rdp:
    li $t0, 0xA4100000
    li $t1, 0x3C1
    sw $t1, 0xC($t0)
    lw $t2, 0($a0)
    lw $t3, 4($a0)
    addu $t3, $t2, $t3
    sw $t2, 0($t0)
    lw $t4, 0xC($t0)
    li $t6, 0xA4300000
    mfc0 $t5, $count
    sw $t3, 4($t0)
krd_wait:
    lw $t7, 8($t6)
    andi $t7, $t7, 0x20
    beqz $t7, krd_wait
    nop
    mfc0 $t8, $count
    lw $t7, 0x10($t0)
    sw $t7, 0($a1)
    lw $t7, 0x14($t0)
    sw $t7, 4($a1)
    lw $t7, 0x18($t0)
    sw $t7, 8($a1)
    lw $t7, 0x1C($t0)
    sw $t7, 12($a1)
    li $t7, 0x800
    sw $t7, 0($t6)
    jr $ra
    subu $v0, $t8, $t5

# Step. a0 = {header prefix, chunk prefix, uncached address, max samples, buffer (cached),
# lines}. Measures the VI line period as the mean of 4 VI_CURRENT change intervals (a
# refresh holdoff on one poll skews a single interval by up to 2%, verify-78), then from the next line
# start takes back-to-back timed uncached LWs for `lines` line periods (or until the buffer is
# full). Prints "<header> line_ticks=N count=N", then the samples 64 per line as
# "<chunk prefix> samples=off:lat,...", where off is the load's COUNT offset from the line start
# and lat its COUNT ticks.
bench_hpos:
    addiu $sp, $sp, -64
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    sd $s4, 40($sp)
    move $s0, $a0
    lw $t4, 16($s0)
    lw $t5, 12($s0)
bh_touch:
    lw $t6, 0($t4)
    addiu $t5, $t5, -4
    bgtz $t5, bh_touch
    addiu $t4, $t4, 16
    li $t0, 0xA4400010
    lw $t1, 0($t0)
bh_sync0:
    lw $t2, 0($t0)
    beq $t2, $t1, bh_sync0
    nop
    mfc0 $s3, $count
    li $t8, 4
bh_sync1:
    lw $t1, 0($t0)
    beq $t1, $t2, bh_sync1
    nop
    addiu $t8, $t8, -1
    bnez $t8, bh_sync1
    move $t2, $t1
    mfc0 $t3, $count
    subu $s3, $t3, $s3
    srl $s3, $s3, 2
    lw $t9, 20($s0)
    multu $s3, $t9
    mflo $a3
bh_sync2:
    lw $t2, 0($t0)
    beq $t2, $t1, bh_sync2
    nop
    mfc0 $t3, $count
    lw $a2, 8($s0)
    lw $t4, 16($s0)
    lw $t5, 12($s0)
    move $s4, $zero
bh_loop:
    mfc0 $t6, $count
    lw $t7, 0($a2)
    addu $t7, $t7, $zero
    mfc0 $t8, $count
    subu $t9, $t8, $t6
    subu $t6, $t6, $t3
    sll $t1, $t6, 16
    or $t1, $t1, $t9
    sw $t1, 0($t4)
    addiu $s4, $s4, 1
    beq $s4, $t5, bh_print_head
    addiu $t4, $t4, 4
    sltu $t1, $t6, $a3
    bnez $t1, bh_loop
    nop
bh_print_head:
    jal pr_str
    lw $a0, 0($s0)
    la $a0, str_bench_line
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s3
    la $a0, str_bench_count
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s4
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    lw $s1, 16($s0)
bh_chunk:
    beqz $s4, bh_done
    nop
    jal pr_str
    lw $a0, 4($s0)
    la $a0, str_bench_samples
    jal pr_str
    nop
    addiu $s2, $zero, 64
bh_print:
    lw $a0, 0($s1)
    jal pr_dec
    srl $a0, $a0, 16
    la $a0, str_bench_colon
    jal pr_str
    nop
    lw $a0, 0($s1)
    jal pr_dec
    andi $a0, $a0, 0xFFFF
    addiu $s1, $s1, 4
    addiu $s4, $s4, -1
    beqz $s4, bh_chunk_end
    addiu $s2, $s2, -1
    beqz $s2, bh_chunk_end
    nop
    la $a0, str_bench_comma
    jal pr_str
    nop
    b bh_print
    nop
bh_chunk_end:
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    b bh_chunk
    nop
bh_done:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    ld $s4, 40($sp)
    jr $ra
    addiu $sp, $sp, 64

# a0 = {kernel, reps, flags, kernel args...}: n64-systembench's TIMEIT_MULTI (main.c:105-127),
# which averages all reps but its lowest and highest. RES[0] = min ticks, RES[1] = max ticks,
# RES[2] = sum of ticks over the reps; the host takes (sum - min - max) / (reps - 2).
# RES[3] = the second highest rep, the highest TIMEIT_MULTI keeps (the highest is usually the
# cold first rep). The kernel gets a0 = &args, a1 = &RES[4] and a2 = reps left less one (reps - 1 down to 0), and
# returns v0 = COUNT ticks. flags as bench_run.
bench_multi:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    move $s0, $a0
    move $s3, $a1
    addiu $t0, $zero, -1
    sw $t0, 0($s3)
    sw $zero, 4($s3)
    sw $zero, 8($s3)
    sw $zero, 12($s3)
    lw $s1, 4($s0)
    lw $t0, 8($s0)
    andi $t0, $t0, 1
    beqz $t0, bm_loop
    nop
    jal vi_set_type
    move $a0, $zero
    move $s2, $v0
bm_loop:
    lw $t9, 0($s0)
    addiu $a0, $s0, 12
    addiu $a2, $s1, -1
    jalr $t9
    addiu $a1, $s3, 16
    lw $t0, 8($s3)
    addu $t0, $t0, $v0
    sw $t0, 8($s3)
    lw $t0, 0($s3)
    sltu $t1, $v0, $t0
    beqz $t1, bm_nomin
    nop
    sw $v0, 0($s3)
bm_nomin:
    lw $t0, 4($s3)
    sltu $t1, $t0, $v0
    beqz $t1, bm_nomax
    nop
    sw $t0, 12($s3)
    b bm_next
    sw $v0, 4($s3)
bm_nomax:
    lw $t0, 12($s3)
    sltu $t1, $t0, $v0
    bnezl $t1, bm_next
    sw $v0, 12($s3)
bm_next:
    addiu $s1, $s1, -1
    bnez $s1, bm_loop
    nop
    lw $t0, 8($s0)
    andi $t0, $t0, 1
    beqz $t0, bm_out
    nop
    jal vi_set_type
    move $a0, $s2
bm_out:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    jr $ra
    addiu $sp, $sp, 48

# Kernels. args = {addr, warm}. n64-systembench bench_ram_{cached,uncached}_r{8,16,32,64}, bench_siior
# and bench_rcp_io_r (main.c:163-268): COUNT, one volatile load whose value is unused, COUNT.
# warm != 0 reads the address once first, outside the timing (the cached benches' setup).
k_sb_lbu:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    beqz $t1, ksb_lbu_time
    nop
    lbu $t2, 0($t0)
ksb_lbu_time:
    mfc0 $t3, $count
    lbu $t2, 0($t0)
    mfc0 $t4, $count
    jr $ra
    subu $v0, $t4, $t3

k_sb_lhu:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    beqz $t1, ksb_lhu_time
    nop
    lhu $t2, 0($t0)
ksb_lhu_time:
    mfc0 $t3, $count
    lhu $t2, 0($t0)
    mfc0 $t4, $count
    jr $ra
    subu $v0, $t4, $t3

k_sb_lw:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    beqz $t1, ksb_lw_time
    nop
    lw $t2, 0($t0)
ksb_lw_time:
    mfc0 $t3, $count
    lw $t2, 0($t0)
    mfc0 $t4, $count
    jr $ra
    subu $v0, $t4, $t3

k_sb_ld:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    beqz $t1, ksb_ld_time
    nop
    ld $t2, 0($t0)
ksb_ld_time:
    mfc0 $t3, $count
    ld $t2, 0($t0)
    mfc0 $t4, $count
    jr $ra
    subu $v0, $t4, $t3

# Kernel. args = {addr0, addr1, addr2, addr3}. n64-systembench bench_ram_uncached_r32_{seq,
# random,multibank} (main.c:270-292): COUNT, four volatile LWs whose values are unused, COUNT.
k_sb_lw4:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    lw $t3, 12($a0)
    mfc0 $t4, $count
    lw $t5, 0($t0)
    lw $t5, 0($t1)
    lw $t5, 0($t2)
    lw $t5, 0($t3)
    mfc0 $t6, $count
    jr $ra
    subu $v0, $t6, $t4

# Kernel. args = {setup reg (0 = none), setup value, second setup reg (0 = none), its value,
# stmt reg, stmt value, poll reg, jitter}.
# n64-systembench TIMEIT_WHILE (main.c:75-103), as bench_pidma, bench_piiow, bench_sidmaw_{ram,rom} and
# bench_siiow (main.c:172-227) with cond `reg & (DMA_BUSY | IO_BUSY)`: the setup writes, COUNT,
# the stmt write, then a loop of 8 x (COUNT, poll read) that runs until the 8th poll sees idle.
# The result ends at the COUNT before the first poll that saw idle.
# Between the stmt and the polls the kernel runs a2 x jitter nops. The result can only end on
# a poll, and polls are about 25 pclk apart, so at one fixed phase it is the busy time plus
# wherever that phase puts the poll grid: 0 to 42 fixed nops after a 134 rclk PI write read
# 125.3 to 141.3 rclk. The core repeats one phase every rep, so the nops walk the grid over
# 50 pclk, two poll periods, and the TIMEIT_MULTI mean becomes the mean over phase.
k_sb_while:
    addiu $sp, $sp, -64
    sd $s0, 0($sp)
    sd $s1, 8($sp)
    sd $s2, 16($sp)
    sd $s3, 24($sp)
    sd $s4, 32($sp)
    sd $s5, 40($sp)
    sd $s6, 48($sp)
    sd $s7, 56($sp)
    lw $a3, 4($a0)
    lw $v1, 16($a0)
    lw $v0, 20($a0)
    lw $t9, 24($a0)
    lw $t8, 28($a0)
    multu $a2, $t8
    mflo $t8
    sll $t8, $t8, 2
    la $t7, ksw_sled_end
    subu $t7, $t7, $t8
    lw $a2, 0($a0)
    beqz $a2, ksw_setup2
    nop
    sw $a3, 0($a2)
ksw_setup2:
    lw $a2, 8($a0)
    beqz $a2, ksw_go
    lw $a3, 12($a0)
    sw $a3, 0($a2)
ksw_go:
    mfc0 $t0, $count
    sw $v0, 0($v1)
    jr $t7
    nop
    .space 200
ksw_sled_end:
ksw_loop:
    mfc0 $s0, $count
    lw $t1, 0($t9)
    andi $t1, $t1, 3
    mfc0 $s1, $count
    lw $t2, 0($t9)
    andi $t2, $t2, 3
    mfc0 $s2, $count
    lw $t3, 0($t9)
    andi $t3, $t3, 3
    mfc0 $s3, $count
    lw $t4, 0($t9)
    andi $t4, $t4, 3
    mfc0 $s4, $count
    lw $t5, 0($t9)
    andi $t5, $t5, 3
    mfc0 $s5, $count
    lw $t6, 0($t9)
    andi $t6, $t6, 3
    mfc0 $s6, $count
    lw $t7, 0($t9)
    andi $t7, $t7, 3
    mfc0 $s7, $count
    lw $t8, 0($t9)
    andi $t8, $t8, 3
    bnez $t8, ksw_loop
    nop
    beqz $t1, ksw_end
    move $v0, $s0
    beqz $t2, ksw_end
    move $v0, $s1
    beqz $t3, ksw_end
    move $v0, $s2
    beqz $t4, ksw_end
    move $v0, $s3
    beqz $t5, ksw_end
    move $v0, $s4
    beqz $t6, ksw_end
    move $v0, $s5
    beqz $t7, ksw_end
    move $v0, $s6
    move $v0, $s7
ksw_end:
    subu $v0, $v0, $t0
    ld $s0, 0($sp)
    ld $s1, 8($sp)
    ld $s2, 16($sp)
    ld $s3, 24($sp)
    ld $s4, 32($sp)
    ld $s5, 40($sp)
    ld $s6, 48($sp)
    ld $s7, 56($sp)
    jr $ra
    addiu $sp, $sp, 64

# Kernel. args = {words (16, the 8 joybus dwords), buf (KSEG1), out phys}. n64-systembench
# bench_joybus_* and joybus_write/joybus_read (main.c:294-511): the setup stores the command block to buf and runs
# joybus_write (ack SI_STATUS, SI DMA buf -> PIF RAM, poll SI_STATUS idle, ack); the timed
# stmt is joybus_read: SI_DRAM_ADDR = out, SI_PIF_ADDR_RD64B = PIF RAM, poll SI_STATUS idle.
k_sb_joybus:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    lw $t2, 8($a0)
    addiu $t3, $zero, 16
ksj_copy:
    lw $t4, 0($t0)
    sw $t4, 0($t1)
    addiu $t0, $t0, 4
    addiu $t3, $t3, -1
    bnez $t3, ksj_copy
    addiu $t1, $t1, 4
    lw $t1, 4($a0)
    li $t5, 0xA4800000
    li $t6, 0x1FC007C0
    sw $zero, 0x18($t5)
    sw $t1, 0x0($t5)
    sw $t6, 0x10($t5)
ksj_wpoll:
    lw $t4, 0x18($t5)
    andi $t4, $t4, 3
    bnez $t4, ksj_wpoll
    nop
    sw $zero, 0x18($t5)
    mfc0 $t7, $count
    sw $t2, 0x0($t5)
    sw $t6, 0x4($t5)
ksj_rpoll:
    lw $t4, 0x18($t5)
    andi $t4, $t4, 3
    bnez $t4, ksj_rpoll
    nop
    mfc0 $t8, $count
    jr $ra
    subu $v0, $t8, $t7

str_bench_line: .asciiz " line_ticks="
str_bench_samples: .asciiz " samples="
str_bench_count: .asciiz " count="
str_bench_colon: .asciiz ":"
str_bench_comma: .asciiz ","
.align 4
"""
