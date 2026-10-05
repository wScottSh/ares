"""On-target routines for the snapper suite. a0 = params, a1 = &RES[res] (romgen step convention).

The DPS test-mode registers (n64brew Reality_Display_Processor/Interface, snapper64
src/renderer/rdp.h): DP_TEST_MODE 0xA4200004, DP_BUFTEST_ADDR 0xA4200008,
DP_BUFTEST_DATA 0xA420000C.
"""

ASM = r"""
# a0 = {name, addr, bytes, always_dump}. Prints "@snap <name> <bytes> <fnv>", where <fnv> is
# FNV-1a 32 over the big-endian words, then hex-dumps the bytes if always_dump or DUMP != 0.
snap_emit:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    move $s0, $a0
    lw $t0, 4($s0)
    lw $t1, 8($s0)
    li $v0, 0x811C9DC5
    li $t3, 0x01000193
se_loop:
    lw $t2, 0($t0)
    xor $v0, $v0, $t2
    multu $v0, $t3
    mflo $v0
    addiu $t1, $t1, -4
    bnez $t1, se_loop
    addiu $t0, $t0, 4
    move $s1, $v0
    la $a0, str_snap
    jal pr_str
    nop
    lw $a0, 0($s0)
    jal pr_str
    nop
    la $a0, str_snap_sep
    jal pr_str
    nop
    jal pr_dec
    lw $a0, 8($s0)
    la $a0, str_snap_sep
    jal pr_str
    nop
    jal pr_hex
    move $a0, $s1
    jal pr_flush
    nop
    lw $t0, 12($s0)
    li $t1, DUMP
    or $t0, $t0, $t1
    beqz $t0, se_out
    nop
    lw $t0, 4($s0)
    lw $t1, 8($s0)
    xhexdump $t0, $t1
se_out:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    jr $ra
    addiu $sp, $sp, 32

# a0 = {value}. RDP::TestMode::enable, spanWrite(i, value) for i < 128, disable.
snap_span_fill:
    li $t0, 0xA4200000
    li $t1, 1
    sw $t1, 4($t0)
    lw $t2, 0($a0)
    move $t3, $zero
ssf_loop:
    sw $t3, 8($t0)
    sw $t2, 12($t0)
    addiu $t3, $t3, 1
    sltiu $t4, $t3, 128
    bnez $t4, ssf_loop
    nop
    jr $ra
    sw $zero, 4($t0)

# a0 = {dst}. RDPTestModeSpan.cpp's read-back: for row y < 8 read span words 4y, 4y+1, 4y+2,
# replicate the low byte of the third through the word, store them as pixels 0-2 of row y of
# the 4-pixel-wide surface at dst.
snap_span_dump:
    li $t0, 0xA4200000
    li $t1, 1
    sw $t1, 4($t0)
    lw $t5, 0($a0)
    move $t3, $zero
ssd_loop:
    sw $t3, 8($t0)
    lw $t1, 12($t0)
    sw $t1, 0($t5)
    addiu $t4, $t3, 1
    sw $t4, 8($t0)
    lw $t1, 12($t0)
    sw $t1, 4($t5)
    addiu $t4, $t3, 2
    sw $t4, 8($t0)
    lw $t1, 12($t0)
    sll $t2, $t1, 8
    or $t1, $t1, $t2
    sll $t2, $t1, 16
    or $t1, $t1, $t2
    sw $t1, 8($t5)
    addiu $t3, $t3, 4
    sltiu $t4, $t3, 32
    bnez $t4, ssd_loop
    addiu $t5, $t5, 16
    jr $ra
    sw $zero, 4($t0)

# a0 = {data, count, start, reads, dst}. RDPTestModeRW.cpp: enable, spanClear, spanWrite(i,
# data[i]) for i < count, then dst[k] = spanRead(start + k) for k < reads, disable.
snap_span_rw:
    li $t0, 0xA4200000
    li $t1, 1
    sw $t1, 4($t0)
    move $t3, $zero
ssr_clear:
    sw $t3, 8($t0)
    sw $zero, 12($t0)
    addiu $t3, $t3, 1
    sltiu $t4, $t3, 128
    bnez $t4, ssr_clear
    nop
    lw $t2, 0($a0)
    lw $t5, 4($a0)
    move $t3, $zero
ssr_write:
    lw $t1, 0($t2)
    sw $t3, 8($t0)
    sw $t1, 12($t0)
    addiu $t3, $t3, 1
    bne $t3, $t5, ssr_write
    addiu $t2, $t2, 4
    lw $t3, 8($a0)
    lw $t5, 12($a0)
    lw $t2, 16($a0)
ssr_read:
    sw $t3, 8($t0)
    lw $t1, 12($t0)
    sw $t1, 0($t2)
    addiu $t3, $t3, 1
    addiu $t5, $t5, -1
    bnez $t5, ssr_read
    addiu $t2, $t2, 4
    jr $ra
    sw $zero, 4($t0)
"""
