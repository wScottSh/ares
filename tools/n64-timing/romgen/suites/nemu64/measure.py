"""Port of nemu64-test's cycle measurement harness (src/tests/timing/mod.rs).

emit_measurement_loop is a line-for-line port. The runtime's step_measure copies one of the
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


def loop_templates_asm():
    out = [".align 4", "measure_loop_plain:"]
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
