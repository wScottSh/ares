"""nemu64-test's `cop0hazard` feature set (Level::COP0Hazard), ported.

Test order follows src/tests/testlist.rs. The instruction sequences between the CP0 writes
and reads are the Rust inline asm's; `dla` keeps LLVM's six-instruction expansion.
"""
from ...suite import Check, Step, Test, Value, checkpoint
from ... import runtime as rt
from .timing import eq, preset_cop2_steps

SW1 = 0x100   # Cause.interrupt_sw1 / Status.interrupt_mask_sw1 (bit 8)
IE = 0x1


def random_read_early():
    return [Value("", [Step("step_random_read_early", [], 0)], [
        eq(0, 21, "Wired set to 20, Random decremented 10 times"),
        eq(1, 29, "Random expected to wrap at previously set Wired bound"),
        eq(2, 21, "Wired set to 20, Random decremented 10 times"),
        eq(3, 31, "Random expected to reset"),
    ])]


def count_hazards():
    """Checks run after each COUNT value, as in the Rust loop: a failure at 0 stops the test
    before the 0xFFFFFFFx writes carry COUNT past Compare and raise IP7 for later tests."""
    steps = []
    for count_value in [0, 100, 0x1234, 0x8000000, 0xFFFFFFFC, 0xFFFFFFFF]:
        steps += [Step("step_count_hazards", [count_value], 0), checkpoint([
            eq(0, count_value, "First readback"),
            eq(1, count_value, "Second readback"),
            eq(2, count_value, "Third readback"),
            eq(3, (count_value + 1) & 0xFFFFFFFF, "Fourth readback"),
        ])]
    return [Value("", steps, [])]


# res layout of the interrupt routines: expect_end's {count, cause, status, epc, vector,
# badvaddr, fcsr}, then [7] = the address the test expects in EPC.
def interrupt_checks(cause, status):
    return [
        Check(rt.CHK_EQ_HEX, 0, 1, msg="Expected exception Int: exceptions seen"),
        eq(4, 0x80000180, "Exception Vector"),
        eq(1, cause, "Cause"),
        eq(2, status, "Status"),
        Check(rt.CHK_EQ_REL, 3, 7, 0, msg="ExceptPC"),
    ]


def sw1_enabled_hazard():
    """exception_instructions test_sw_interrupt(DEFAULT|IM1|IE, SW1, DEFAULT, 0, hazard=true)."""
    status_before = rt.STATUS_DEFAULT | SW1 | IE
    step = Step("step_sw_interrupt", [status_before, SW1, rt.STATUS_DEFAULT], 0)
    return [Value("", preset_cop2_steps(20) + [step],
                  interrupt_checks(SW1, 0x24000003 | (SW1 & 0x300)))]


def sw1_enable_disable_instantly():
    step = Step("step_sw_enable_disable_instantly", [rt.STATUS_DEFAULT | SW1 | IE, SW1, 0], 0)
    return [Value("", preset_cop2_steps(20) + [step], [])]


def sw1_enable_disable_after_nop():
    step = Step("step_sw_enable_disable_after_nop", [rt.STATUS_DEFAULT | SW1 | IE, SW1, 0], 0)
    checks = interrupt_checks(SW1, 0x24000103)
    checks[-1] = Check(rt.CHK_EQ_REL, 3, 7, 0, msg="ExceptPC points to wrong instruction")
    return [Value("", preset_cop2_steps(20) + [step], checks)]


def build(suite):
    suite.tests += [
        Test("Random (read early)", random_read_early()),
        Test("MTC0/MFC0 COUNT hazards", count_hazards()),
        Test("SoftwareInterrupt1 (enabled, hazard)", sw1_enabled_hazard()),
        Test("SoftwareInterrupt1 (enable but disable right away)", sw1_enable_disable_instantly()),
        Test("SoftwareInterrupt12 (enable and disable after one nop)",
             sw1_enable_disable_after_nop()),
    ]


def _interrupt_routine(name, body):
    """a0 = {status, fire cause, third value}; $t4/$t5/$t6 hold them for `body`, which leaves
    the expected EPC in $t7."""
    return f"""
{name}:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    sd $a1, 8($sp)
    lw $t4, 0($a0)
    lw $t5, 4($a0)
    lw $t6, 8($a0)
    move $t7, $zero
    jal expect_begin
    addiu $a0, $zero, 1
{body}
    la $a0, DATA_BASE + D_DECBUF
    jal expect_end
    nop
    li $t0, STATUS_DEFAULT
    mtc0 $t0, $status
    ld $a1, 8($sp)
    la $t0, DATA_BASE + D_DECBUF
    jal copy_exception_record
    nop
    sw $t7, 28($a1)
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16
"""


ASM = "\n".join([
    r"""
# cop0/mod.rs RandomReadEarly. res = {start, readback, start (delayed), readback (delayed)}.
step_random_read_early:
    li $t0, 20
    li $t2, 5
    nop
    mtc0 $t0, $wired
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    mfc0 $t1, $random
    nop
    nop
    mtc0 $t2, $wired
    mfc0 $t3, $random
    nop
    nop
    sw $t1, 0($a1)
    sw $t3, 4($a1)
    li $t0, 20
    li $t2, 5
    nop
    mtc0 $t0, $wired
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    mfc0 $t1, $random
    nop
    nop
    mtc0 $t2, $wired
    nop
    mfc0 $t3, $random
    nop
    nop
    sw $t1, 8($a1)
    jr $ra
    sw $t3, 12($a1)

# cop0/mod.rs CountHazards for one COUNT value (a0 = {count_value}).
# res = {out0, out1, out2, out3} from the loop's second pass.
step_count_hazards:
    lw $t9, 0($a0)
    mfc0 $t8, $count
    li $v0, 2
ch_loop:
    nop
    mtc0 $t9, $count
    mfc0 $t0, $count
    mfc0 $t1, $count
    mfc0 $t2, $count
    mfc0 $t3, $count
    addi $v0, $v0, -1
    bne $v0, $zero, ch_loop
    nop
    mtc0 $t8, $count
    sw $t0, 0($a1)
    sw $t1, 4($a1)
    sw $t2, 8($a1)
    jr $ra
    sw $t3, 12($a1)
""",
    "# exception_instructions/mod.rs test_sw_interrupt (fire_position 0).",
    _interrupt_routine("step_sw_interrupt", """
    mtc0 $t4, $status
    dla $t7, swi_0
    dla $t8, swi_1
    mtc0 $t5, $cause
    nop
swi_0:
    mtc0 $t6, $status
    nop
swi_1:
    nop"""),
    r"""
# exception_instructions/mod.rs SoftwareInterrupt1EnableAndDisableInstantly. No exception is
# expected, so any interrupt taken here fails the value through the runner's
# unexpected-exception report.
step_sw_enable_disable_instantly:
    lw $t4, 0($a0)
    lw $t5, 4($a0)
    lw $t6, 8($a0)
    mtc0 $t4, $status
    mtc0 $t5, $cause
    mtc0 $t6, $cause
    nop
    jr $ra
    nop
""",
    "# exception_instructions/mod.rs SoftwareInterrupt1EnableAndDisableAfterOneNop.",
    _interrupt_routine("step_sw_enable_disable_after_nop", """
    mtc0 $t4, $status
    dla $t7, swd_0
    mtc0 $t5, $cause
    nop
swd_0:
    mtc0 $t6, $cause
    nop"""),
])
