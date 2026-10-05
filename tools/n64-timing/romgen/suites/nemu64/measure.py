"""Port of nemu64-test's cycle measurement harness (src/tests/timing/mod.rs).

emit_measurement_loop is a line-for-line port. step_measure (below) copies one of the
two loop templates into the program buffer, appends the body and the preconditions exactly as
MeasurementProgram::new lays them out, then runs it the way run_measurement does.
"""
from ...nemu import Assembler, GPR, RegisterIndex, ExceptionTimingMode, FCSR, Status
from ... import runtime
from ...suite import Step, Check
from ... import runtime as rt

MEASURE_RA_SLOT = 8
MEASURE_PRECONDITIONS_SLOT = 9


def emit_measurement_loop(call_preconditions):
    code = []
    count = RegisterIndex.Count
    ra_offset = MEASURE_RA_SLOT * 8

    def branch_offset(frm, to):
        return to - frm - 1

    code.append(Assembler.make_sw(GPR.RA, ra_offset, GPR.V1))
    label_1 = len(code)
    code.append(Assembler.make_move(GPR.K0, GPR.S2))
    code.append(Assembler.make_move(GPR.A2, GPR.V0))
    code.append(Assembler.make_move(GPR.A3, GPR.V1))
    code.append(Assembler.make_move(GPR.T0, GPR.A0))
    code.append(Assembler.make_move(GPR.T1, GPR.A1))
    if call_preconditions:
        code.append(Assembler.make_ld(GPR.S3, MEASURE_PRECONDITIONS_SLOT * 8, GPR.V1))
        code.append(Assembler.make_jalr(GPR.RA, GPR.S3))
        code.append(Assembler.make_nop())
        code.append(Assembler.make_nop())
    code.append(Assembler.make_mfc0(GPR.S3, count))
    code.append(Assembler.make_nop())
    code.append(Assembler.make_nop())
    code.append(Assembler.make_mtc0(GPR.S3, count))
    code.append(Assembler.make_nop())
    code.append(Assembler.make_ori(GPR.S3, GPR.R0, 2))
    branch_2f = len(code)
    code.append(Assembler.make_beq(GPR.S6, GPR.S3, 0))
    code.append(Assembler.make_nop())
    code.append(Assembler.make_nop())
    code[branch_2f] = Assembler.make_beq(GPR.S6, GPR.S3, branch_offset(branch_2f, len(code)))
    code.append(Assembler.make_mfc0(GPR.S3, count))
    code.append(Assembler.make_jalr(GPR.RA, GPR.T9))
    code.append(Assembler.make_nop())
    code.append(Assembler.make_mfc0(GPR.S5, count))
    code.append(Assembler.make_ori(GPR.S1, GPR.R0, 1))
    branch_3f = len(code)
    code.append(Assembler.make_bne(GPR.S1, GPR.S2, 0))
    code.append(Assembler.make_nop())
    code.append(Assembler.make_move(GPR.S5, GPR.K1))
    code[branch_3f] = Assembler.make_bne(GPR.S1, GPR.S2, branch_offset(branch_3f, len(code)))
    code.append(Assembler.make_move(GPR.S7, GPR.T8))
    code.append(Assembler.make_sub(GPR.T8, GPR.S5, GPR.S3))
    code.append(Assembler.make_addiu(GPR.S6, GPR.S6, -1))
    code.append(Assembler.make_ori(GPR.S3, GPR.R0, 70))
    label_4 = len(code)
    code.append(Assembler.make_bne(GPR.S3, GPR.R0, branch_offset(label_4, label_4)))
    code.append(Assembler.make_addiu(GPR.S3, GPR.S3, -1))
    code.append(Assembler.make_bne(GPR.S6, GPR.R0, branch_offset(len(code), label_1)))
    code.append(Assembler.make_nop())
    code.append(Assembler.make_lw(GPR.RA, ra_offset, GPR.V1))
    code.append(Assembler.make_jr(GPR.RA))
    code.append(Assembler.make_nop())
    return code


LOOP_PLAIN = emit_measurement_loop(False)
LOOP_PRE = emit_measurement_loop(True)


STEP_MEASURE_ASM = r"""
# ---------------------------------------------------------------------------------------
# Measurement, ported from nemu64-test timing/mod.rs (MeasurementProgram + run_measurement).
# a0 = params:
#   0 body ptr, 4 body words, 8 preconditions ptr, 12 preconditions words (0 = none),
#   16 value2 hi, 20 value2 lo, 24 value4 hi, 28 value4 lo, 32 status, 36 exception mode,
#   40 fcsr, 44 allocation bytes (the Rust buffer size, for the invalidate range),
#   48 repeat count (0 = single run), 52 averaged-mode flags
# a1 = result pointer. Single run: res[0] = ticks1, res[1] = ticks2.
# Averaged run (repeat > 0): res[0] = min, res[1] = max, res[2] = median, res[3] = sum.
step_measure:
    la $t0, DATA_BASE + D_SAVE
    sd $s0, 0($t0)
    sd $s1, 8($t0)
    sd $s2, 16($t0)
    sd $s3, 24($t0)
    sd $s4, 32($t0)
    sd $s5, 40($t0)
    sd $s6, 48($t0)
    sd $s7, 56($t0)
    sd $gp, 64($t0)
    sd $sp, 72($t0)
    sd $fp, 80($t0)
    sd $ra, 88($t0)
    move $s0, $a0
    move $s1, $a1
    sd $s1, 96($t0)

    lw $t1, 52($s0)
    andi $t2, $t1, 2
    beqz $t2, sm_no_vioff
    nop
    jal vi_set_type
    move $a0, $zero
    la $t0, DATA_BASE + D_SAVE
    sw $v0, 104($t0)
sm_no_vioff:
    lw $t1, 52($s0)
    andi $t2, $t1, 1
    beqz $t2, sm_no_vsync
    nop
    jal vi_wait_vsync
    nop
sm_no_vsync:
    lw $t0, 40($s0)
    ctc1 $t0, 31

    li $a0, EXEC_BASE
    jal invalidate_range
    lw $a1, 44($s0)
    li $s2, EXEC_BASE | 0x20000000
    la $t0, measure_loop_plain
    la $t1, measure_loop_plain_end
    lw $t2, 12($s0)
    beqz $t2, sm_copy_loop
    nop
    la $t0, measure_loop_pre
    la $t1, measure_loop_pre_end
sm_copy_loop:
    lw $t3, 0($t0)
    sw $t3, 0($s2)
    addiu $t0, $t0, 4
    bne $t0, $t1, sm_copy_loop
    addiu $s2, $s2, 4
    li $t4, 0x20000000
    subu $s3, $s2, $t4
    lw $t0, 0($s0)
    lw $t2, 4($s0)
sm_copy_body:
    beqz $t2, sm_body_done
    nop
    lw $t3, 0($t0)
    sw $t3, 0($s2)
    addiu $t0, $t0, 4
    addiu $t2, $t2, -1
    b sm_copy_body
    addiu $s2, $s2, 4
sm_body_done:
    li $t3, 0x03E00008
    sw $t3, 0($s2)
    sw $zero, 4($s2)
    addiu $s2, $s2, 8
    li $t4, 0x20000000
    subu $s4, $s2, $t4
    lw $t0, 8($s0)
    lw $t2, 12($s0)
    beqz $t2, sm_pre_done
    nop
sm_copy_pre:
    lw $t3, 0($t0)
    sw $t3, 0($s2)
    addiu $t0, $t0, 4
    addiu $t2, $t2, -1
    bnez $t2, sm_copy_pre
    addiu $s2, $s2, 4
    li $t3, 0x03E00008
    sw $t3, 0($s2)
    sw $zero, 4($s2)
sm_pre_done:
    li $a0, MEM_BASE
    jal invalidate_range
    addiu $a1, $zero, 80
    li $t0, MEM_BASE | 0x20000000
    li $t1, MEM_BASE
    sd $t1, 0($t0)
    li $t1, (MEM_BASE + 8) | 0x20000000
    sd $t1, 8($t0)
    addiu $t1, $s3, 16
    sd $t1, 16($t0)
    la $t2, measure_slot_constants
    ld $t1, 0($t2)
    sd $t1, 24($t0)
    ld $t1, 8($t2)
    sd $t1, 32($t0)
    ld $t1, 16($t2)
    sd $t1, 40($t0)
    ld $t1, 24($t2)
    sd $t1, 48($t0)
    ld $t1, 32($t2)
    sd $t1, 56($t0)
    sd $s4, 72($t0)

    lw $t1, 16($s0)
    dsll32 $t1, $t1, 0
    lwu $t2, 20($s0)
    or $t1, $t1, $t2
    dmtc1 $t1, $f2
    lw $t1, 24($s0)
    dsll32 $t1, $t1, 0
    lwu $t2, 28($s0)
    or $t1, $t1, $t2
    dmtc1 $t1, $f4

    lw $t0, 48($s0)
    beqz $t0, sm_single
    nop
    la $t0, DATA_BASE + D_HIST
    li $t1, HIST_BUCKETS
sm_hist_clear:
    sw $zero, 0($t0)
    addiu $t1, $t1, -1
    bnez $t1, sm_hist_clear
    addiu $t0, $t0, 4
    li $t0, -1
    sw $t0, 0($s1)
    sw $zero, 4($s1)
    sw $zero, 12($s1)
    lw $s6, 48($s0)
sm_avg_loop:
    jal run_measurement
    nop
    addu $t0, $v0, $v1
    addiu $t0, $t0, -5
    lw $t1, 0($s1)
    sltu $t2, $t0, $t1
    beqz $t2, sm_avg_nomin
    nop
    sw $t0, 0($s1)
sm_avg_nomin:
    lw $t1, 4($s1)
    sltu $t2, $t1, $t0
    beqz $t2, sm_avg_nomax
    nop
    sw $t0, 4($s1)
sm_avg_nomax:
    lw $t1, 12($s1)
    addu $t1, $t1, $t0
    sw $t1, 12($s1)
    sltiu $t2, $t0, HIST_BUCKETS
    bnez $t2, sm_avg_bucket
    move $t1, $t0
    li $t1, HIST_BUCKETS - 1
sm_avg_bucket:
    sll $t1, $t1, 2
    la $t2, DATA_BASE + D_HIST
    addu $t1, $t1, $t2
    lw $t2, 0($t1)
    addiu $t2, $t2, 1
    sw $t2, 0($t1)
    addiu $s6, $s6, -1
    bnez $s6, sm_avg_loop
    nop
    lw $t0, 48($s0)
    srl $t0, $t0, 1
    la $t1, DATA_BASE + D_HIST
    move $t2, $zero
    move $t3, $zero
sm_median:
    lw $t4, 0($t1)
    addu $t3, $t3, $t4
    sltu $t5, $t0, $t3
    bnez $t5, sm_median_found
    nop
    addiu $t1, $t1, 4
    b sm_median
    addiu $t2, $t2, 1
sm_median_found:
    b sm_finish
    sw $t2, 8($s1)
sm_single:
    jal run_measurement
    nop
    sw $v0, 0($s1)
    sw $v1, 4($s1)
sm_finish:
    lw $t1, 52($s0)
    andi $t2, $t1, 2
    beqz $t2, sm_no_vion
    nop
    la $t0, DATA_BASE + D_SAVE
    jal vi_set_type
    lw $a0, 104($t0)
sm_no_vion:
    la $t0, DATA_BASE + D_SAVE
    ld $s0, 0($t0)
    ld $s1, 8($t0)
    ld $s2, 16($t0)
    ld $s3, 24($t0)
    ld $s4, 32($t0)
    ld $s5, 40($t0)
    ld $s6, 48($t0)
    ld $s7, 56($t0)
    ld $gp, 64($t0)
    ld $sp, 72($t0)
    ld $fp, 80($t0)
    ld $ra, 88($t0)
    jr $ra
    nop

# Runs the built program once. In: s0 = params, s3 = body address. Out: v0 = ticks1,
# v1 = ticks2. Clobbers every register except s0, s1, s3, s4, s6, sp.
run_measurement:
    la $t0, DATA_BASE + D_SAVE
    sd $ra, 112($t0)
    sd $s0, 120($t0)
    sd $s1, 128($t0)
    sd $s3, 136($t0)
    sd $s4, 144($t0)
    sd $s6, 152($t0)
    sd $sp, 160($t0)
    li $3, MEM_BASE
    li $5, MEM_BASE | 0x20000000
    lw $18, 36($s0)
    li $22, 3
    move $25, $s3
    li $10, EXEC_BASE
    lw $16, 32($s0)
    ori $20, $31, 0
    dmfc1 $2, $f2
    dmfc1 $4, $f4
    nop
    nop
    mtc0 $16, $status
    jalr $10
    nop
    ori $31, $20, 0
    ori $26, $0, 0
    li $t0, STATUS_DEFAULT
    mtc0 $t0, $status
    move $v0, $24
    move $v1, $23
    la $t0, DATA_BASE + D_SAVE
    ld $ra, 112($t0)
    ld $s0, 120($t0)
    ld $s1, 128($t0)
    ld $s3, 136($t0)
    ld $s4, 144($t0)
    ld $s6, 152($t0)
    ld $sp, 160($t0)
    jr $ra
    nop

.align 8
measure_slot_constants:
    .dword 0x89ABCDEF01234567, 0x456789ABCDEF1234, 0x56789ABCDEF12345, 0x6789ABCDEF123456, 0x789ABCDEF1234567
"""


def asm():
    """step_measure, run_measurement and the two loop templates; nemu64 sets link this in."""
    out = [STEP_MEASURE_ASM, ".align 4", "measure_loop_plain:"]
    out += [f"    .word {w}" for w in LOOP_PLAIN]
    out += ["measure_loop_plain_end:", "measure_loop_pre:"]
    out += [f"    .word {w}" for w in LOOP_PRE]
    out += ["measure_loop_pre_end:"]
    return "\n".join(out)


def allocation_bytes(body_len, pre_len):
    """MeasurementProgram::new's buffer size and placement, checked against the runtime's
    fixed EXEC_BASE (the program must land at EXEC_BASE with no shift)."""
    loop = LOOP_PRE if pre_len is not None else LOOP_PLAIN
    code_len = len(loop) + body_len + 2 + ((pre_len + 2) if pre_len is not None else 0)
    lines = code_len * 4 // 32 + 1
    count = code_len + (16 + lines) * 8
    base_line = (rt.EXEC_BASE >> 5) & 0x1FF
    assert 16 <= base_line and base_line + lines <= 512, "program would be shifted"
    return (count * 4 + 15) & ~15


VI_WAIT_VSYNC = 1
VI_DISABLE = 2


def measure_step(suite, body, value2, value4, status, exception_mode, fcsr, res,
                 preconditions=None, repeat=0, vi_flags=0):
    body = list(body)
    pre_label, pre_len = "0", 0
    if preconditions is not None:
        pre_label, pre_len = suite.blob(preconditions), len(preconditions)
    params = [
        suite.blob(body) if body else "0", len(body), pre_label, pre_len,
        (value2 >> 32) & 0xFFFFFFFF, value2 & 0xFFFFFFFF,
        (value4 >> 32) & 0xFFFFFFFF, value4 & 0xFFFFFFFF,
        status.raw_value() if isinstance(status, Status) else status,
        int(exception_mode), fcsr.raw_value() if isinstance(fcsr, FCSR) else fcsr,
        allocation_bytes(len(body), pre_len if preconditions is not None else None),
        repeat, vi_flags,
    ]
    return Step("step_measure", params, res)


def cycles_checks(res, expected, exception_mode):
    """assert_cycles_with_codegen's two soft asserts over (ticks1, ticks2) at RES[res]."""
    just_fire = exception_mode == ExceptionTimingMode.JustFire
    msg = ("Two measurements aren't close. Most likely, exception didn't fire" if just_fire else
           "Two measurements aren't close. Most likely, the MTC0 COUNT initialization didn't "
           "work or something else (e.g. cache effect) kicked in")
    return [
        Check(rt.CHK_RANGE_REL, res + 1, res, 1, msg=msg),
        Check(rt.CHK_SUM_DEC, res, res + 1, 2 if just_fire else 5, expected, msg="Measured cycles"),
    ]
