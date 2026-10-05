"""nemu64-test's `cycle` feature set (Level::Cycle), ported.

Test order follows src/tests/testlist.rs. Each port keeps the instruction sequence of the
Rust inline asm (or of the code the Rust test generates), since what these tests observe is
which instruction the pipeline sees, not a cycle count.
"""
from ...nemu import Assembler, CacheOp, GPR
from ...suite import Check, Step, Test, Value
from ... import runtime as rt
from .describe import describe
from .timing import eq, preset_cop2_steps

SMC_SIG = "(bool, usize, usize)"

NEW_INSTRUCTION = Assembler.make_ori(GPR.T1, GPR.R0, 0x2222)


def modify_within_basic_block_code(at_beginning, further_down, generator_index, generated_index):
    """icache.rs test_modify_within_basic_block: the code it writes into its heap buffer."""
    code = [Assembler.make_lui(GPR.A1, NEW_INSTRUCTION >> 16),
            Assembler.make_ori(GPR.A1, GPR.A1, NEW_INSTRUCTION & 0xFFFF),
            at_beginning]
    assert len(code) <= generator_index
    code += [Assembler.make_nop()] * (generator_index - len(code))
    code.append(further_down)
    assert len(code) <= generated_index
    code += [Assembler.make_nop()] * (generated_index - len(code))
    code += [Assembler.make_ori(GPR.T1, GPR.R0, 0x1111),
             Assembler.make_jr(GPR.RA),
             Assembler.make_nop()]
    return code


def smc_step(suite, code, generated_index, t1=0, s_regs=(0,) * 8):
    return Step("step_smc", [suite.blob(code), len(code), generated_index, t1, *s_regs], 0)


def modify_within_basic_block(suite, at_beginning, further_down, values):
    out = []
    for expected_new, generator_index, generated_index in values:
        code = modify_within_basic_block_code(at_beginning, further_down, generator_index,
                                              generated_index)
        v = (expected_new, generator_index, generated_index)
        out.append(Value(describe(v, SMC_SIG), [smc_step(suite, code, generated_index)],
                         [eq(0, 0x2222 if expected_new else 0x1111, "Result value")],
                         describe(v, SMC_SIG, full=True)))
    return out


def single_value(suite, at_beginning, further_down, generator_index, generated_index, expected_new):
    code = modify_within_basic_block_code(at_beginning, further_down, generator_index,
                                          generated_index)
    return [Value("", [smc_step(suite, code, generated_index)],
                  [eq(0, 0x2222 if expected_new else 0x1111, "Result value")])]


def multiple_sw(suite):
    """icache.rs ModifyWithinBasicBlockMultipleSW."""
    code = [Assembler.make_sw(GPR(GPR.S0 + i), i << 2, GPR.V1) for i in range(8)]
    code += [Assembler.make_nop()] * 8
    code += [Assembler.make_jr(GPR.RA), Assembler.make_nop()]
    s_regs = [Assembler.make_ori(GPR.T1, GPR.T1, 1 << i) for i in range(8)]
    return [Value("", [smc_step(suite, code, 8, 0, s_regs)], [eq(0, 0x3F, "Result value")])]


# res layout of step_ctc1_*: expect_end's {count, cause, status, epc, vector, badvaddr, fcsr},
# then [7] = the word at EPC and [8] = EPC & 0xFF000000.
FPE = 15
STATUS_DEFAULT = rt.STATUS_DEFAULT
FCSR_OVERFLOW_ENABLED_AND_CAUSED = (1 << 9) | (1 << 14)


def ctc1_fire(routine, copindex, status):
    checks = [
        Check(rt.CHK_EQ_HEX, 0, 1, msg="Expected exception FPE: exceptions seen"),
        eq(4, 0x80000180, "Exception Vector"),
        eq(8, 0x80000000, "ExceptPC"),
        eq(7, Assembler.make_ctc1(GPR.V0, 31), "ExceptPC points to wrong instruction"),
        eq(1, (copindex << 28) | (FPE << 2), "Cause"),
        eq(2, status | 0x2, "Status"),
        eq(6, FCSR_OVERFLOW_ENABLED_AND_CAUSED, "FCSR"),
    ]
    step = Step(routine, [status, FCSR_OVERFLOW_ENABLED_AND_CAUSED], 0)
    return [Value("", preset_cop2_steps(20) + [step], checks)]


def branch_result(routine, expected, msg, ra_offset=None):
    checks = [eq(0, expected, msg)]
    if ra_offset is not None:
        checks.append(eq(1, ra_offset, "BGEZAL return address is incorrect"))
    return [Value("", [Step(routine, [], 0)], checks)]


def build(suite):
    sw_v1 = Assembler.make_sw(GPR.A1, 0, GPR.V1)
    sw_a0 = Assembler.make_sw(GPR.A1, 0, GPR.A0)
    nop = Assembler.make_nop()
    delay_msg = "BGEZAL within a delay slot should add its offset to the branch target address"
    beq_msg = "BEQ within a delay slot should add its offset to the branch target address"
    suite.tests += [
        Test("icache: Self-modifying code within basic block (single write) (cycle accurate)",
             modify_within_basic_block(suite, nop, sw_v1, [(False, 6, 8), (False, 7, 8)])),
        Test("icache: Modify target of branch (from within delay slot) (cycle accurate)",
             single_value(suite, Assembler.make_beq(GPR.R0, GPR.R0, 5), sw_v1, 3, 8, False)),
        Test("icache: Self-modifying code within basic block (with explicit dcache HitWriteBack) (cycle accurate)",
             modify_within_basic_block(suite, sw_a0,
                                       Assembler.make_cache(CacheOp.DataHitWriteBack, 0, GPR.A0),
                                       [(False, 7, 8)])),
        Test("icache: Self-modifying code within basic block (with implicit dcache write back) (cycle accurate)",
             modify_within_basic_block(suite, sw_a0, Assembler.make_sw(GPR.A1, 8192, GPR.A0),
                                       [(False, 7, 8)])),
        Test("icache: Self-modifying code within basic block (with i-cache invalidation) (cycle accurate)",
             modify_within_basic_block(
                 suite, sw_v1, Assembler.make_cache(CacheOp.InstructionIndexInvalidate, 0, GPR.A0),
                 [(False, 6, 7)])),
        Test("icache: Self-modifying code within basic block (multiple writes)", multiple_sw(suite)),
        Test("Fire exception through CTC1 (followed by MFC1)",
             ctc1_fire("step_ctc1_mfc1", 1, STATUS_DEFAULT)),
        Test("Fire exception through CTC1 (followed by MFC2)",
             ctc1_fire("step_ctc1_mfc2", 2, STATUS_DEFAULT | (1 << 30))),
        Test("BEQ: Within delay slot of J", branch_result("step_beq_in_j", 769, beq_msg)),
        Test("BEQ: Within delay slot of JR", branch_result("step_beq_in_jr", 514, beq_msg)),
        Test("BGEZAL: Within delay slot of J",
             branch_result("step_bgezal_in_j", 769, delay_msg, 36)),
        Test("BGEZAL: Within delay slot of BEQ",
             branch_result("step_bgezal_in_beq", 769, delay_msg, 36)),
    ]


def _ctc1_routine(name, second):
    return f"""
{name}:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    sd $a1, 8($sp)
    lw $t1, 0($a0)
    lw $v0, 4($a0)
    mtc0 $t1, $status
    nop
    nop
    jal expect_begin
    addiu $a0, $zero, 1
    ctc1 $v0, 31
    {second}
    la $a0, DATA_BASE + D_DECBUF
    jal expect_end
    nop
    li $t0, STATUS_DEFAULT
    mtc0 $t0, $status
    ld $a1, 8($sp)
    la $t0, DATA_BASE + D_DECBUF
    jal copy_exception_record
    nop
    lw $t1, 0($a1)
    beqz $t1, {name}_none
    lw $t1, 12($a1)
    lw $t2, 0($t1)
    sw $t2, 28($a1)
    lui $t2, 0xFF00
    and $t1, $t1, $t2
    sw $t1, 32($a1)
{name}_none:
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16
"""


def _branch_routine(name, setup, branch_pair, tail):
    return f"""
{name}:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    sd $a1, 8($sp)
    daddiu $25, $31, 0
    lui $3, 0x0000
    jal {name}_0
    nop
{name}_0:
    {setup}
    {branch_pair[0]}
    {branch_pair[1]}
    nop
    nop
    nop
    nop
    nop
{name}_1:
    ori $3, $3, 1
    ori $3, $3, 2
    ori $3, $3, 4
{name}_2:
    ori $3, $3, 8
    ori $3, $3, 16
    ori $3, $3, 32
    ori $3, $3, 64
    ori $3, $3, 128
    ori $3, $3, 256
    ori $3, $3, 512
    {tail}
    ld $a1, 8($sp)
    sw $3, 0($a1)
    sw $4, 4($a1)
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16
"""


ASM = "\n".join([
    r"""
# icache.rs self-modifying-code tests. a0 = {code, words, generated index, $t1, $s0..$s7}.
# Like UncachedHeapMemory::new_with_align(8192 words, 4096): invalidate both caches over the
# 32 KiB buffer, write the code through KSEG1, then call it through KSEG0 with
# $2 = code (cached), $3 = generated slot (uncached), $4 = generated slot (cached).
# res[0] = $t1 after the call.
step_smc:
    addiu $sp, $sp, -96
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    sd $s4, 40($sp)
    sd $s5, 48($sp)
    sd $s6, 56($sp)
    sd $s7, 64($sp)
    sd $a1, 72($sp)
    sd $a0, 80($sp)
    li $a1, 32768
    li $a0, SCRATCH_BASE
    jal invalidate_range
    nop
    ld $t9, 80($sp)
    lw $t0, 0($t9)
    lw $t1, 4($t9)
    li $t2, SCRATCH_BASE + 0x20000000
smc_copy:
    lw $t3, 0($t0)
    sw $t3, 0($t2)
    addiu $t0, $t0, 4
    addiu $t1, $t1, -1
    bnez $t1, smc_copy
    addiu $t2, $t2, 4
    lw $t3, 8($t9)
    sll $t3, $t3, 2
    li $v0, SCRATCH_BASE
    addu $a0, $v0, $t3
    li $v1, SCRATCH_BASE + 0x20000000
    addu $v1, $v1, $t3
    lw $s0, 16($t9)
    lw $s1, 20($t9)
    lw $s2, 24($t9)
    lw $s3, 28($t9)
    lw $s4, 32($t9)
    lw $s5, 36($t9)
    lw $s6, 40($t9)
    lw $s7, 44($t9)
    lw $t1, 12($t9)
    or $6, $31, $0
    jalr $2
    nop
    or $31, $6, $0
    ld $a1, 72($sp)
    sw $t1, 0($a1)
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    ld $s4, 40($sp)
    ld $s5, 48($sp)
    ld $s6, 56($sp)
    ld $s7, 64($sp)
    jr $ra
    addiu $sp, $sp, 96

""",
    "# cop1/mod.rs FireExceptionViaCTC1FollowedByMFC1/MFC2. a0 = {status, fcsr}.",
    _ctc1_routine("step_ctc1_mfc1", "mfc1 $zero, $f0"),
    _ctc1_routine("step_ctc1_mfc2", "mfc2 $zero, 0"),
    "# jumps/conditionals.rs delay-slot branch tests. res = {$3, $4}.",
    _branch_routine("step_beq_in_j", "daddiu $25, $31, 0",
                    ("j step_beq_in_j_1", "beq $3, $0, step_beq_in_j_2"), "daddiu $31, $25, 0"),
    _branch_routine("step_beq_in_jr", "daddiu $4, $31, 36",
                    ("jr $4", "beq $3, $0, step_beq_in_jr_2"), "daddiu $31, $25, 0"),
    _branch_routine("step_bgezal_in_j", "daddiu $24, $31, 0",
                    ("j step_bgezal_in_j_1", "bgezal $3, step_bgezal_in_j_2"),
                    "dsub $4, $31, $24\n    daddiu $31, $25, 0"),
    _branch_routine("step_bgezal_in_beq", "daddiu $24, $31, 0",
                    ("beq $3, $0, step_bgezal_in_beq_1", "bgezal $3, step_bgezal_in_beq_2"),
                    "dsub $4, $31, $24\n    daddiu $31, $25, 0"),
])
