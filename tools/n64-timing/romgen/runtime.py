"""On-target runtime for romgen test ROMs.

The runtime is table driven. A suite supplies a list of tests; each test has values, each
value runs a list of steps (routines that leave raw results in RES[]) and then a list of
checks over RES[]. The ROM decides pass/fail itself and prints nemu64-test's output format
through emux XLOG: "Running <name>...", "Test '<name>'<desc> failed: ...", and the final
"<Category>: Failed X of Y tests (Z% success rate)" line.

Memory map (KSEG0 virtual):
  0x80000000-0x800002FF  exception vectors, installed at boot
  0x80000400-            payload: this runtime, helpers, suite tables and code blobs
  FB0 / FB1              320x240 RGBA5551 framebuffers (VI on, like nemu64-test)
  EXEC_BASE              measurement program buffer (one at a time, rebuilt per measurement)
  MEM_BASE               measurement data slots ($3 cached / $5 uncached)
  DATA_BASE              runtime variables, RES[], line buffer, save areas
  STACK_TOP              stack (grows down)
  SCRATCH_BASE           scratch memory for tests that need a heap buffer
"""
from . import mips

PAYLOAD_BASE = 0x80000400
FB0 = 0x80200000
FB1 = 0x80300000
EXEC_BASE = 0x80400800
MEM_BASE = 0x80410000
DATA_BASE = 0x80420000
STACK_TOP = 0x80480000
SCRATCH_BASE = 0x80500000

STATUS_DEFAULT = 0x24000000
FCSR_DEFAULT = 0x01000800

# Data area layout (offsets from DATA_BASE)
D_LINEPOS = 0x000
D_SEEN = 0x004
D_STREAK = 0x008
D_SKIP = 0x00C          # instructions to skip on an expected exception; 0 = not expecting
D_OVR_VALID = 0x010
D_OVR_STATUS = 0x014
D_OVR_RET = 0x018       # 64-bit
D_EXC_VECTOR = 0x020    # 64-bit
D_EXC_EPC = 0x028       # 64-bit
D_EXC_BADVADDR = 0x030  # 64-bit
D_EXC_CAUSE = 0x038
D_EXC_STATUS = 0x03C
D_SUCC = 0x040
D_FAIL = 0x044
D_TEST_NAME = 0x048
D_VALUE = 0x04C
D_TI = 0x050
D_VI = 0x054
D_EXC_FCSR = 0x058
D_ABORT = 0x05C        # set by step_checks when a mid-value check fails
D_DECBUF = 0x060        # 32 bytes
D_SAVE = 0x1600         # callee-saved registers during a measurement
D_EXC_SAVE = 0x100      # registers the exception handler uses, 16 x 8
D_RES = 0x200           # RES[], 256 words
D_HIST = 0x600          # histogram for averaged measurements, 1024 words
D_LINEBUF = 0x1800      # 4 KiB

RES_WORDS = 256
HIST_BUCKETS = 1024

# Check opcodes
CHK_EQ_HEX = 1       # RES[a] == b
CHK_EQ_DEC = 2       # RES[a] == b
CHK_RANGE = 3        # b <= RES[a] <= c
CHK_RANGE_REL = 4    # RES[b] <= RES[a] <= RES[b] + c
CHK_SUM_DEC = 5      # RES[a] + RES[b] - c == d
CHK_GE_REL = 6       # RES[a] >= RES[b]
CHK_NE_REL = 7       # RES[a] != RES[b]
CHK_LE = 8           # RES[a] <= b
CHK_EQ_REL = 9       # RES[a] == RES[b] + c

CONSTS = dict(
    STATUS_DEFAULT=STATUS_DEFAULT, FCSR_DEFAULT=FCSR_DEFAULT, EXEC_BASE=EXEC_BASE,
    MEM_BASE=MEM_BASE, DATA_BASE=DATA_BASE, STACK_TOP=STACK_TOP, FB0=FB0, FB1=FB1,
    RES_WORDS=RES_WORDS, HIST_BUCKETS=HIST_BUCKETS,
    **{k: v for k, v in globals().items() if k.startswith(("D_", "CHK_"))},
)

# The vector stubs, copied to 0x80000000, 0x80000080 and 0x80000180. Ported from nemu64-test
# src/exception_handler.rs: with $k0 != 0 (an exception-timing measurement) the stub latches
# COUNT into $k1 as its first instruction and returns past the faulting instruction.
VECTOR_STUB = """
    mfc0 $k1, $count
    beq $k0, $zero, {name}_generic
    mfc0 $k0, $epc
    addi $k0, $k0, 4
    mtc0 $k0, $epc
    nop
    nop
    eret
{name}_generic:
{load_vector}
    j exc_generic
    nop
"""


def vector_image(exc_generic):
    """The 0x300 bytes copied to 0x80000000 at boot (stubs at +0x000, +0x080, +0x180)."""
    data = bytearray(0x300)
    for name, offset in (("v000", 0x000), ("v080", 0x080), ("v180", 0x180)):
        load = ("    lui $k0, 0x8000" if offset == 0 else
                f"    lui $k0, 0x8000\n    ori $k0, $k0, {offset:#x}")
        img = mips.Image(0x80000000 + offset)
        img.symbol("exc_generic", exc_generic)
        img.asm(VECTOR_STUB.format(name=name, load_vector=load)).link()
        data[offset:offset + len(img.data)] = img.data
    return bytes(data)


RUNTIME = r"""
_start:
    j boot
    nop

# Helpers that measured bodies call by absolute address (nemu64-test timing/mod.rs
# instant_return_function / one_nop_then_return_function).
instant_return_function:
    jr $ra
    nop
one_nop_then_return_function:
    nop
    jr $ra
    nop

boot:
    la $sp, STACK_TOP
    move $k0, $zero
    move $k1, $zero
    li $t0, STATUS_DEFAULT
    mtc0 $t0, $status
    nop
    nop
    li $t0, FCSR_DEFAULT
    ctc1 $t0, 31
    li $t0, 0xA430000C
    li $t1, 0x555
    sw $t1, 0($t0)
    la $t0, DATA_BASE + D_LINEBUF
    la $t1, DATA_BASE + D_LINEPOS
    sw $t0, 0($t1)
    jal pif_terminate_boot
    nop
    jal install_vectors
    nop
    xioctl 2
    jal vi_init
    nop
    mfc0 $s7, $count
    jal run_tests
    nop
    mfc0 $t0, $count
    subu $a0, $t0, $s7
    jal print_summary
    nop
    xioctl 1
halt:
    b halt
    nop

# Sets the PIF boot-termination bit (PIF RAM byte 0x3F bit 3), as libdragon's boot code does.
# Without it the PIF halts the CPU 5 s after boot (ares pif/hle.cpp WaitTerminateBoot).
pif_terminate_boot:
    li $t0, 0xBFC007FC
    li $t1, 8
    jr $ra
    sw $t1, 0($t0)

# ---------------------------------------------------------------------------------------
install_vectors:
    la $t0, vector_image
    li $t1, 0x80000000
    li $t2, 0x300
iv_copy:
    lw $t3, 0($t0)
    sw $t3, 0($t1)
    addiu $t0, $t0, 4
    addiu $t2, $t2, -4
    bnez $t2, iv_copy
    addiu $t1, $t1, 4
    li $t0, 0x80000000
    li $t1, 0x80002000
iv_dcache:
    cache 1, 0($t0)
    addiu $t0, $t0, 16
    bne $t0, $t1, iv_dcache
    nop
    li $t0, 0x80000000
    li $t1, 0x80004000
iv_icache:
    cache 0, 0($t0)
    addiu $t0, $t0, 32
    bne $t0, $t1, iv_icache
    nop
    jr $ra
    nop

# Index-invalidates both caches over [a0, a0+a1) the way nemu64-test's
# UncachedHeapMemory::invalidate_caches does: per 32 bytes, I-cache index invalidate and two
# D-cache index writeback-invalidates.
invalidate_range:
    addu $a1, $a0, $a1
ir_loop:
    sltu $t0, $a0, $a1
    beqz $t0, ir_done
    nop
    cache 0, 0($a0)
    cache 1, 0($a0)
    cache 1, 16($a0)
    b ir_loop
    addiu $a0, $a0, 32
ir_done:
    jr $ra
    nop

# ---------------------------------------------------------------------------------------
# Generic exception handler (vector stubs jump here with $k0 = vector address when no
# exception-timing measurement is active). Mirrors exception_handler_compiled: records the
# first exception, acks software interrupts, skips the faulting instruction(s), clears the
# FCSR cause bits and zeroes $k0/$k1 on the way out.
exc_generic:
    la $k1, DATA_BASE + D_EXC_SAVE
    sd $at, 0($k1)
    sd $v0, 8($k1)
    sd $v1, 16($k1)
    sd $a0, 24($k1)
    sd $a1, 32($k1)
    sd $t0, 40($k1)
    sd $t1, 48($k1)
    sd $t2, 56($k1)
    sd $t3, 64($k1)
    la $at, DATA_BASE
    mfc0 $t0, $cause
    mfc0 $t1, $status
    dmfc0 $t2, $epc
    andi $t3, $t0, 0x300
    beqz $t3, eg_noack
    nop
    li $t3, 0xFFFFFCFF
    and $t3, $t0, $t3
    mtc0 $t3, $cause
eg_noack:
    lw $t3, D_SEEN($at)
    bnez $t3, eg_again
    nop
    sd $k0, D_EXC_VECTOR($at)
    sd $t2, D_EXC_EPC($at)
    dmfc0 $v0, $badvaddr
    sd $v0, D_EXC_BADVADDR($at)
    sw $t0, D_EXC_CAUSE($at)
    sw $t1, D_EXC_STATUS($at)
    b eg_counted
    sw $zero, D_STREAK($at)
eg_again:
    lw $v0, D_STREAK($at)
    addiu $v0, $v0, 1
    sw $v0, D_STREAK($at)
    sltiu $v0, $v0, 5
    bnez $v0, eg_counted
    nop
    la $v0, str_storm
    xlog $v0
    xioctl 1
eg_storm:
    b eg_storm
    nop
eg_counted:
    addiu $t3, $t3, 1
    sw $t3, D_SEEN($at)
    lw $v0, D_SKIP($at)
    beqz $v0, eg_unexpected
    nop
    sll $v0, $v0, 2
    b eg_ret
    daddu $t2, $t2, $v0
eg_unexpected:
    la $v0, str_unhandled
    xlog $v0
    bltz $t0, eg_ret
    daddiu $t2, $t2, 8
    daddiu $t2, $t2, -4
eg_ret:
    li $v0, -4
    and $t2, $t2, $v0
    lw $v0, D_OVR_VALID($at)
    beqz $v0, eg_noovr
    nop
    ld $t2, D_OVR_RET($at)
    lw $t1, D_OVR_STATUS($at)
    sw $zero, D_OVR_VALID($at)
eg_noovr:
    lui $v0, 0x2000
    or $v0, $v0, $t1
    mtc0 $v0, $status
    nop
    nop
    cfc1 $v0, 31
    addiu $v1, $t3, -1
    bnez $v1, eg_fcsr_seen
    nop
    sw $v0, D_EXC_FCSR($at)
eg_fcsr_seen:
    li $v1, 0xFFFC0FFF
    and $v0, $v0, $v1
    ctc1 $v0, 31
    dmtc0 $t2, $epc
    mtc0 $t1, $status
    ld $at, 0($k1)
    ld $v0, 8($k1)
    ld $v1, 16($k1)
    ld $a0, 24($k1)
    ld $a1, 32($k1)
    ld $t0, 40($k1)
    ld $t1, 48($k1)
    ld $t2, 56($k1)
    ld $t3, 64($k1)
    lui $k1, 0
    lui $k0, 0
    eret

# ---------------------------------------------------------------------------------------
# Output. pr_* append to the line buffer; pr_flush sends it through XLOG.
pr_str:
    la $t0, DATA_BASE + D_LINEPOS
    lw $t1, 0($t0)
ps_loop:
    lbu $t2, 0($a0)
    beqz $t2, ps_done
    addiu $a0, $a0, 1
    sb $t2, 0($t1)
    b ps_loop
    addiu $t1, $t1, 1
ps_done:
    jr $ra
    sw $t1, 0($t0)

pr_dec:
    la $t3, DATA_BASE + D_DECBUF + 31
    sb $zero, 0($t3)
    li $t4, 10
pd_loop:
    divu $a0, $t4
    mflo $a0
    mfhi $t5
    addiu $t5, $t5, 48
    addiu $t3, $t3, -1
    bnez $a0, pd_loop
    sb $t5, 0($t3)
    j pr_str
    move $a0, $t3

pr_hex:
    la $t3, DATA_BASE + D_DECBUF + 31
    sb $zero, 0($t3)
ph_loop:
    andi $t5, $a0, 15
    sltiu $t6, $t5, 10
    bnez $t6, ph_digit
    addiu $t5, $t5, 48
    addiu $t5, $t5, 39
ph_digit:
    addiu $t3, $t3, -1
    srl $a0, $a0, 4
    bnez $a0, ph_loop
    sb $t5, 0($t3)
    addiu $t3, $t3, -2
    li $t5, 0x30
    sb $t5, 0($t3)
    li $t5, 0x78
    sb $t5, 1($t3)
    j pr_str
    move $a0, $t3

pr_flush:
    la $t0, DATA_BASE + D_LINEPOS
    lw $t1, 0($t0)
    sb $zero, 0($t1)
    la $t2, DATA_BASE + D_LINEBUF
    xlog $t2
    jr $ra
    sw $t2, 0($t0)

# ---------------------------------------------------------------------------------------
# VI setup, ported from nemu64-test src/graphics/vi.rs (NTSC, 320x240, 16 bpp).
vi_init:
    li $t0, 0xA4400000
    li $t1, 0x324E
    sw $t1, 0x00($t0)
    li $t1, 2
    sw $t1, 0x0C($t0)
    li $t1, 0x03E52239
    sw $t1, 0x14($t0)
    li $t1, 0x20D
    sw $t1, 0x18($t0)
    li $t1, 0xC15
    sw $t1, 0x1C($t0)
    li $t1, 0x0C150C15
    sw $t1, 0x20($t0)
    li $t1, 0x006C02EC
    sw $t1, 0x24($t0)
    li $t1, 0x002501FF
    sw $t1, 0x28($t0)
    li $t1, 0x000E0204
    sw $t1, 0x2C($t0)
    li $t1, 0x200
    sw $t1, 0x30($t0)
    li $t1, 0x400
    sw $t1, 0x34($t0)
    li $t1, FB0 & 0x1FFFFFFF | 0xA0000000
    sw $t1, 0x04($t0)
    li $t1, 320
    jr $ra
    sw $t1, 0x08($t0)

vi_wait_vsync:
    li $t0, 0xA4400010
vw_loop:
    lw $t1, 0($t0)
    sltiu $t1, $t1, 10
    beqz $t1, vw_loop
    nop
    jr $ra
    nop

# a0 = framebuffer type to set (0 = off); returns the previous type in v0
vi_set_type:
    li $t0, 0xA4400000
    lw $t1, 0($t0)
    andi $v0, $t1, 3
    li $t2, -4
    and $t1, $t1, $t2
    or $t1, $t1, $a0
    jr $ra
    sw $t1, 0($t0)

# ---------------------------------------------------------------------------------------
# Test runner. Table: count, then per test {name, nvalues, values}. Value: {desc, nsteps,
# steps, nchecks, checks}. Step: {routine, params, res_index}. Check: {op, a, b, c, d, msg}.
run_tests:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    la $s0, suite_tests
    lw $s1, 0($s0)
    addiu $s0, $s0, 4
rt_test:
    beqz $s1, rt_done
    nop
    lw $s2, 0($s0)
    la $t0, DATA_BASE + D_TEST_NAME
    sw $s2, 0($t0)
    la $a0, str_running
    jal pr_str
    nop
    move $a0, $s2
    jal pr_str
    nop
    la $a0, str_running_end
    jal pr_str
    nop
    jal pr_flush
    nop
    la $t0, DATA_BASE
    sw $zero, D_VI($t0)
    lw $s2, 4($s0)
    lw $s3, 8($s0)
rt_value:
    beqz $s2, rt_next
    nop
    jal run_value
    move $a0, $s3
    addiu $s3, $s3, 20
    b rt_value
    addiu $s2, $s2, -1
rt_next:
    la $t0, DATA_BASE
    lw $t1, D_TI($t0)
    addiu $t1, $t1, 1
    sw $t1, D_TI($t0)
    addiu $s0, $s0, 12
    b rt_test
    addiu $s1, $s1, -1
rt_done:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    jr $ra
    addiu $sp, $sp, 48

set_default_state:
    li $t0, STATUS_DEFAULT
    mtc0 $t0, $status
    li $t0, FCSR_DEFAULT
    jr $ra
    ctc1 $t0, 31

run_value:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s4, 32($sp)
    sd $s3, 40($sp)
    move $s0, $a0
    la $t0, DATA_BASE + D_VALUE
    sw $s0, 0($t0)
    jal set_default_state
    nop
    la $t0, DATA_BASE
    sw $zero, D_ABORT($t0)
    lw $s1, 4($s0)
    lw $s2, 8($s0)
rv_step:
    beqz $s1, rv_steps_done
    nop
    lw $t9, 0($s2)
    lw $a0, 4($s2)
    lw $a1, 8($s2)
    sll $a1, $a1, 2
    la $t0, DATA_BASE + D_RES
    jalr $t9
    addu $a1, $a1, $t0
    la $t0, DATA_BASE
    lw $t0, D_ABORT($t0)
    bnez $t0, rv_aborted
    addiu $s2, $s2, 12
    b rv_step
    addiu $s1, $s1, -1
rv_aborted:
    jal set_default_state
    nop
    la $s4, DATA_BASE
    b rv_fail
    addiu $v0, $zero, 1
rv_steps_done:
    jal set_default_state
    nop
    la $s4, DATA_BASE
    lw $t0, D_SEEN($s4)
    beqz $t0, rv_checks
    nop
    sw $zero, D_SEEN($s4)
    sw $zero, D_STREAK($s4)
    jal pr_test_prefix
    nop
    la $a0, str_failed_exc
    jal pr_str
    nop
    lw $a0, D_EXC_CAUSE($s4)
    srl $a0, $a0, 2
    andi $a0, $a0, 31
    sll $a0, $a0, 2
    la $t0, exception_names
    addu $a0, $a0, $t0
    jal pr_str
    lw $a0, 0($a0)
    la $a0, str_epc
    jal pr_str
    nop
    jal pr_hex
    lw $a0, D_EXC_EPC + 4($s4)
    la $a0, str_badvaddr
    jal pr_str
    nop
    jal pr_hex
    lw $a0, D_EXC_BADVADDR + 4($s4)
    la $a0, str_close_nl2
    jal pr_str
    nop
    jal pr_flush
    nop
    b rv_fail
    addiu $v0, $zero, 2
rv_checks:
    lw $s1, 12($s0)
    lw $s2, 16($s0)
rv_check:
    beqz $s1, rv_pass
    nop
    jal run_check
    move $a0, $s2
    bnez $v0, rv_fail
    addiu $s2, $s2, 24
    b rv_check
    addiu $s1, $s1, -1
rv_pass:
    lw $t0, D_SUCC($s4)
    addiu $t0, $t0, 1
    sw $t0, D_SUCC($s4)
    b rv_record
    move $v0, $zero
rv_fail:
    lw $t0, D_FAIL($s4)
    addiu $t0, $t0, 1
    sw $t0, D_FAIL($s4)
# Machine-readable record: "@<test>.<value> <0 pass|1 fail|2 exception> <cycles>..." with the
# measured effective cycles of every cycle check, for host-side per-value reports.
rv_record:
    move $s1, $v0
    la $a0, str_at
    jal pr_str
    nop
    jal pr_dec
    lw $a0, D_TI($s4)
    la $a0, str_dot
    jal pr_str
    nop
    jal pr_dec
    lw $a0, D_VI($s4)
    la $a0, str_space
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s1
    lw $s1, 12($s0)
    lw $s2, 16($s0)
rv_rec_check:
    beqz $s1, rv_rec_done
    nop
    lw $t0, 0($s2)
    addiu $t1, $zero, CHK_SUM_DEC
    bne $t0, $t1, rv_rec_next
    nop
    la $t3, DATA_BASE + D_RES
    lw $t0, 4($s2)
    sll $t0, $t0, 2
    addu $t0, $t0, $t3
    lw $t0, 0($t0)
    lw $t1, 8($s2)
    sll $t1, $t1, 2
    addu $t1, $t1, $t3
    lw $t1, 0($t1)
    addu $t0, $t0, $t1
    lw $t1, 12($s2)
    subu $s3, $t0, $t1
    la $a0, str_space
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s3
rv_rec_next:
    addiu $s2, $s2, 24
    b rv_rec_check
    addiu $s1, $s1, -1
rv_rec_done:
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    lw $t0, D_VI($s4)
    addiu $t0, $t0, 1
    sw $t0, D_VI($s4)
rv_out:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s4, 32($sp)
    ld $s3, 40($sp)
    jr $ra
    addiu $sp, $sp, 48

# Prints "Test '<name>'<desc>" into the line buffer.
pr_test_prefix:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    la $a0, str_test_open
    jal pr_str
    nop
    la $t0, DATA_BASE + D_TEST_NAME
    jal pr_str
    lw $a0, 0($t0)
    la $a0, str_quote
    jal pr_str
    nop
    la $t0, DATA_BASE + D_VALUE
    lw $t0, 0($t0)
    jal pr_str
    lw $a0, 0($t0)
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16

# A step that runs checks in the middle of a value. a0 = {count, check records...}. The first
# failure prints its line and sets D_ABORT, which ends the value as failed.
step_checks:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    lw $s1, 0($a0)
    addiu $s0, $a0, 4
sc_loop:
    beqz $s1, sc_done
    nop
    jal run_check
    move $a0, $s0
    bnez $v0, sc_fail
    addiu $s0, $s0, 24
    b sc_loop
    addiu $s1, $s1, -1
sc_fail:
    la $t0, DATA_BASE
    sw $v0, D_ABORT($t0)
sc_done:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    jr $ra
    addiu $sp, $sp, 32

# a0 = check record. Returns v0 = 0 on pass; on failure prints the failure line, v0 = 1.
run_check:
    addiu $sp, $sp, -64
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    sd $s5, 40($sp)
    move $s0, $a0
    la $s5, DATA_BASE + D_RES
    lw $t0, 0($s0)
    lw $t1, 4($s0)
    sll $t1, $t1, 2
    addu $t1, $t1, $s5
    lw $s1, 0($t1)
    lw $s2, 8($s0)
    lw $s3, 12($s0)
    addiu $t2, $zero, CHK_EQ_HEX
    beq $t0, $t2, rc_eq
    addiu $t2, $zero, CHK_EQ_DEC
    beq $t0, $t2, rc_eq
    addiu $t2, $zero, CHK_RANGE
    beq $t0, $t2, rc_range
    addiu $t2, $zero, CHK_RANGE_REL
    beq $t0, $t2, rc_range_rel
    addiu $t2, $zero, CHK_SUM_DEC
    beq $t0, $t2, rc_sum
    addiu $t2, $zero, CHK_GE_REL
    beq $t0, $t2, rc_ge_rel
    addiu $t2, $zero, CHK_NE_REL
    beq $t0, $t2, rc_ne_rel
    addiu $t2, $zero, CHK_LE
    beq $t0, $t2, rc_le
    addiu $t2, $zero, CHK_EQ_REL
    beq $t0, $t2, rc_eq_rel
    nop
    b rc_fail
    nop
rc_eq:
    beq $s1, $s2, rc_pass
    nop
    b rc_fail
    nop
rc_range:
    sltu $t3, $s1, $s2
    bnez $t3, rc_fail
    sltu $t3, $s3, $s1
    bnez $t3, rc_fail
    nop
    b rc_pass
    nop
rc_range_rel:
    sll $t1, $s2, 2
    addu $t1, $t1, $s5
    lw $s2, 0($t1)
    addu $s3, $s2, $s3
    b rc_range
    nop
rc_sum:
    sll $t1, $s2, 2
    addu $t1, $t1, $s5
    lw $t1, 0($t1)
    addu $s1, $s1, $t1
    subu $s1, $s1, $s3
    lw $s2, 16($s0)
    beq $s1, $s2, rc_pass
    nop
    b rc_fail
    nop
rc_ge_rel:
    sll $t1, $s2, 2
    addu $t1, $t1, $s5
    lw $s2, 0($t1)
    sltu $t3, $s1, $s2
    bnez $t3, rc_fail
    nop
    b rc_pass
    nop
rc_ne_rel:
    sll $t1, $s2, 2
    addu $t1, $t1, $s5
    lw $s2, 0($t1)
    bne $s1, $s2, rc_pass
    nop
    b rc_fail
    nop
rc_le:
    sltu $t3, $s2, $s1
    bnez $t3, rc_fail
    nop
    b rc_pass
    nop
rc_eq_rel:
    sll $t1, $s2, 2
    addu $t1, $t1, $s5
    lw $s2, 0($t1)
    addu $s2, $s2, $s3
    beq $s1, $s2, rc_pass
    nop
rc_fail:
    jal pr_test_prefix
    nop
    la $a0, str_failed
    jal pr_str
    nop
    lw $t0, 0($s0)
    addiu $t2, $zero, CHK_EQ_DEC
    beq $t0, $t2, rc_msg_dec
    addiu $t2, $zero, CHK_SUM_DEC
    beq $t0, $t2, rc_msg_dec
    nop
    la $a0, str_actual_hex
    jal pr_str
    nop
    jal pr_hex
    move $a0, $s1
    la $a0, str_expected_hex
    jal pr_str
    nop
    jal pr_hex
    move $a0, $s2
    lw $t0, 0($s0)
    addiu $t2, $zero, CHK_RANGE
    beq $t0, $t2, rc_msg_hi
    addiu $t2, $zero, CHK_RANGE_REL
    bne $t0, $t2, rc_msg_end
    nop
rc_msg_hi:
    la $a0, str_range_to
    jal pr_str
    nop
    jal pr_hex
    move $a0, $s3
    b rc_msg_end
    nop
rc_msg_dec:
    la $a0, str_actual_dec
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s1
    la $a0, str_expected_dec
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s2
rc_msg_end:
    la $a0, str_dot_space
    jal pr_str
    nop
    jal pr_str
    lw $a0, 20($s0)
    la $a0, str_nl2
    jal pr_str
    nop
    jal pr_flush
    nop
    b rc_out
    addiu $v0, $zero, 1
rc_pass:
    move $v0, $zero
rc_out:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    ld $s5, 40($sp)
    jr $ra
    addiu $sp, $sp, 64

# a0 = elapsed COUNT ticks for the whole suite
print_summary:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    li $t0, 468750
    divu $a0, $t0
    mflo $s0
    la $a0, str_summary_head
    jal pr_str
    nop
    li $t0, 100
    divu $s0, $t0
    mflo $a0
    jal pr_dec
    nop
    la $a0, str_dot
    jal pr_str
    nop
    li $t0, 100
    divu $s0, $t0
    mfhi $a0
    sltiu $t0, $a0, 10
    beqz $t0, ps_cs
    nop
    la $a0, str_zero
    jal pr_str
    nop
    li $t0, 100
    divu $s0, $t0
    mfhi $a0
ps_cs:
    jal pr_dec
    nop
    la $a0, str_summary_mid
    jal pr_str
    nop
    la $s1, DATA_BASE
    jal pr_dec
    lw $a0, D_FAIL($s1)
    la $a0, str_of
    jal pr_str
    nop
    lw $a0, D_FAIL($s1)
    lw $t0, D_SUCC($s1)
    jal pr_dec
    addu $a0, $a0, $t0
    la $a0, str_tests_open
    jal pr_str
    nop
    lw $t0, D_SUCC($s1)
    lw $t1, D_FAIL($s1)
    addu $t1, $t1, $t0
    li $t2, 100
    multu $t0, $t2
    mflo $t0
    nop
    nop
    divu $t0, $t1
    mflo $a0
    jal pr_dec
    nop
    la $a0, str_rate
    jal pr_str
    nop
    jal pr_flush
    nop
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    jr $ra
    addiu $sp, $sp, 32
"""

STRINGS = {
    "str_running": "Running ",
    "str_running_end": "...\n",
    "str_test_open": "Test '",
    "str_quote": "'",
    "str_failed": " failed: ",
    "str_failed_exc": " failed with exception: ",
    "str_actual_hex": "a == b expected, but a=",
    "str_expected_hex": " b=",
    "str_range_to": "..=",
    "str_actual_dec": "a == b expected, but: Actual: ",
    "str_expected_dec": ", expected ",
    "str_dot_space": ". ",
    "str_nl2": "\n\n",
    "str_epc": " (EPC=",
    "str_badvaddr": " BadVAddr=",
    "str_close_nl2": ")\n\n",
    "str_unhandled": "Got unhandled exception. Attempting to continue\n",
    "str_storm": "Exception storm detected. Aborting.\n",
    "str_dot": ".",
    "str_at": "@",
    "str_space": " ",
    "str_nl": "\n",
    "str_zero": "0",
    "str_of": " of ",
    "str_tests_open": " tests (",
    "str_rate": "% success rate)\n",
}

# nemu64-test src/cop0.rs CauseException Debug names
EXCEPTION_NAMES = {
    0: "Int", 1: "Mod", 2: "TLBL", 3: "TLBS", 4: "AdEL", 5: "AdES", 6: "IBE", 7: "DBE",
    8: "Sys", 9: "Bp", 10: "RI", 11: "CpU", 12: "Ov", 13: "Tr", 15: "FPE", 23: "WATCH",
}


def asm_string(s):
    return '"' + s.encode("unicode_escape").decode("ascii").replace('"', '\\"') + '"'
