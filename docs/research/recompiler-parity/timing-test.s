# CPU recompiler-vs-interpreter timing microbenchmarks for ares (see ../recompiler-parity.md).
# Each test prints "Tn <COP0 Count delta, hex>" over IS-Viewer; build with build-rom.py.
#   T1 ALU loop (control)            T2 ADD.S loop           T3 C.EQ.S loop
#   T4 two loads that always D-cache miss (slow path) after pending deferred cycles
#   T5 JAL to a callee 16 KiB away (same I-cache index); return lands mid-line
#   T6 control for T5: callee on a different I-cache index
.set noreorder
.set noat
.text
.globl _start
_start:
    lui   $sp, 0x8030
    li    $t0, 0x20000000      # CU1, FR=0, IE=0, kernel
    mtc0  $t0, $12
    nop
    nop
    li    $s7, 0               # test id
    # ---- T1: pure ALU loop ----
    jal   t1
    nop
    li    $a0, 1
    jal   print
    move  $a1, $v0
    # ---- T2: ADD.S loop ----
    jal   t2
    nop
    li    $a0, 2
    jal   print
    move  $a1, $v0
    # ---- T3: C.EQ.S loop ----
    jal   t3
    nop
    li    $a0, 3
    jal   print
    move  $a1, $v0
    # ---- T4: dcache-miss slow path with pending cycles ----
    jal   t4
    nop
    li    $a0, 4
    jal   print
    move  $a1, $v0
    # ---- T5: callee evicts caller's return line (mid-line alias entry) ----
    jal   t5
    nop
    li    $a0, 5
    jal   print
    move  $a1, $v0
    # ---- T6: control for T5: callee does not alias ----
    jal   t6
    nop
    li    $a0, 6
    jal   print
    move  $a1, $v0
    .word 0x4200006C           # emux XIOCTL exit
    nop
hang: b hang
    nop

.align 5
t1: li $t9, 10000
    mfc0 $t8, $9
1:  addiu $t0, $t0, 1
    addiu $t1, $t1, 1
    addiu $t2, $t2, 1
    addiu $t9, $t9, -1
    bnez $t9, 1b
    nop
    mfc0 $v0, $9
    jr $ra
    subu $v0, $v0, $t8

.align 5
t2: li $t9, 10000
    mtc1 $zero, $f0
    mtc1 $zero, $f2
    mfc0 $t8, $9
1:  add.s $f4, $f0, $f2
    addiu $t1, $t1, 1
    addiu $t2, $t2, 1
    addiu $t9, $t9, -1
    bnez $t9, 1b
    nop
    mfc0 $v0, $9
    jr $ra
    subu $v0, $v0, $t8

.align 5
t3: li $t9, 10000
    mtc1 $zero, $f0
    mtc1 $zero, $f2
    mfc0 $t8, $9
1:  c.eq.s $f0, $f2
    addiu $t1, $t1, 1
    addiu $t2, $t2, 1
    addiu $t9, $t9, -1
    bnez $t9, 1b
    nop
    mfc0 $v0, $9
    jr $ra
    subu $v0, $v0, $t8

# two addresses 8 KiB apart share a D-cache line index -> every load misses
.align 5
t4: li $t9, 10000
    lui $a2, 0x8020
    lui $a3, 0x8020
    ori $a3, $a3, 0x2000
    mfc0 $t8, $9
1:  addiu $t0, $t0, 1
    addiu $t1, $t1, 1
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    addiu $t4, $t4, 1
    addiu $t5, $t5, 1
    lw    $t6, 0($a2)
    lw    $t7, 0($a3)
    addiu $t9, $t9, -1
    bnez $t9, 1b
    nop
    mfc0 $v0, $9
    jr $ra
    subu $v0, $v0, $t8

# caller loop; return address of jal is mid-line; callee lives 16 KiB away (same I-cache index)
.align 5
t5: move $s6, $ra
    li $s5, 1000
    mfc0 $s4, $9
    nop
    nop
    jal  far5            # at line offset 0x14 -> return address offset 0x1c (mid-line)
    nop
    addiu $s5, $s5, -1   # <- mid-line return point
    bnez $s5, t5+0x14
    nop
    mfc0 $v0, $9
    move $ra, $s6
    jr $ra
    subu $v0, $v0, $s4

.align 5
t6: move $s6, $ra
    li $s5, 1000
    mfc0 $s4, $9
    nop
    nop
    jal  far6
    nop
    addiu $s5, $s5, -1
    bnez $s5, t6+0x14
    nop
    mfc0 $v0, $9
    move $ra, $s6
    jr $ra
    subu $v0, $v0, $s4

# print: a0 = test id, a1 = value -> "T<id> <8 hex>\n" via IS-Viewer
.align 5
print:
    move $s0, $ra
    lui  $t0, 0xB3FF
    # build "T" id ' '
    li   $t1, 0x54
    sll  $t1, $t1, 24
    addiu $t2, $a0, 0x30
    sll  $t2, $t2, 16
    or   $t1, $t1, $t2
    ori  $t1, $t1, 0x2000      # ' ' then first hex digit later
    # hex digits
    move $t3, $a1
    li   $t4, 8
    li   $t5, 0                # word1
    li   $t6, 0                # word2
    li   $t7, 0
2:  srl  $t2, $t3, 28
    sll  $t3, $t3, 4
    sltiu $at, $t2, 10
    bnez $at, 3f
    addiu $t2, $t2, 0x30
    addiu $t2, $t2, 7
3:  # shift into 64-bit accumulator (t5:t6) as 8 chars
    sll  $t5, $t5, 8
    srl  $at, $t6, 24
    or   $t5, $t5, $at
    sll  $t6, $t6, 8
    or   $t6, $t6, $t2
    addiu $t4, $t4, -1
    bnez $t4, 2b
    nop
    # line layout: 'T' id ' ' d0 | d1 d2 d3 d4 | d5 d6 d7 '\n'
    srl  $at, $t5, 24
    or   $t1, $t1, $at         # but ' ' at byte 2, d0 at byte3
    andi $t1, $t1, 0xFFFF
    lui  $at, 0
    # rebuild cleanly
    li   $t1, 0x54
    sll  $t1, $t1, 24
    addiu $t2, $a0, 0x30
    sll  $t2, $t2, 16
    or   $t1, $t1, $t2
    ori  $t1, $t1, 0x2000
    srl  $at, $t5, 24
    or   $t1, $t1, $at
    sll  $t2, $t5, 8
    srl  $at, $t6, 24
    or   $t2, $t2, $at         # d1..d4
    sll  $t3, $t6, 8
    ori  $t3, $t3, 0x0A        # d5 d6 d7 '\n'
    jal  piw
    nop
    sw   $t1, 0x20($t0)
    jal  piw
    nop
    sw   $t2, 0x24($t0)
    jal  piw
    nop
    sw   $t3, 0x28($t0)
    jal  piw
    nop
    li   $t1, 12
    sw   $t1, 0x14($t0)
    jal  piw
    nop
    jr   $s0
    nop

piw: lui $t9, 0xA460
4:  lw  $at, 0x10($t9)
    andi $at, $at, 3
    bnez $at, 4b
    nop
    jr  $ra
    nop

.org t5 - _start + 0x4000
far5: jr $ra
    nop
.org t6 - _start + 0x4200
far6: nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
far6b: jr $ra
    nop
