"""kit-pif: the PIF boot timeout, logged as a report (docs/calibration/hardware-run.md, The PIF boot timeout).

The ROM never sends the PIF terminate-boot command (build.py drops the runtime's pif_terminate_boot call
for a set with NO_TERMINATE_BOOT). n64brew PIF-NUS: the PIF expects the command "before 5 seconds from
boot", and "if it doesn't within about 5 seconds from boot, the PIF halts the VR4300 via the NMI line".
Every 10 ms of COUNT the ROM prints `#bench kit-pif count n=<sample> count=<COUNT>`, so the log's last
line is the last COUNT before the halt. A launch that already terminated boot (a flashcart menu) is
never halted: after SAMPLES lines the ROM ends its log with the #kit-end footer, so a complete log
means no halt was seen.
"""
from ... import runtime
from ...suite import Step, Test, Value
from ..nemu64.sets import SetDef

STEP_TICKS = 468750   # 10 ms of COUNT at 46.875 MHz (bench report.py units)
#2 x 6 s, the larger of the cited timeouts (n64brew PIF-NUS "about 5 seconds"; ares pif/hle.cpp 6 s):
#a bound to tell "never halted" from a halt, not a timing the model uses.
SAMPLES = 1200

ASM = r"""
k_pif_log:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    move $s0, $zero
    mfc0 $s1, $count
kpl_wait:
    mfc0 $t0, $count
    subu $t0, $t0, $s1
    bltz $t0, kpl_wait
    nop
    mfc0 $s2, $count
    la $a0, kpl_str_n
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s0
    la $a0, kpl_str_count
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s2
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    li $t0, PIF_STEP_TICKS
    addu $s1, $s1, $t0
    addiu $s0, $s0, 1
    sltiu $t0, $s0, PIF_SAMPLES
    bnez $t0, kpl_wait
    nop
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    jr $ra
    addiu $sp, $sp, 32
kpl_str_n: .asciiz "#bench kit-pif count n="
kpl_str_count: .asciiz " count="
.align 4
"""


def build(suite):
    suite.tests.append(Test("pif-timeout", [Value("count", [Step("k_pif_log", [], 0)], [])]))


SETS = [
    SetDef("kit-pif", "kit-pif", "PIF", "(pif: boot timeout, no terminate-boot)", build, [ASM],
           {"SCRATCH_BASE": runtime.SCRATCH_BASE, "NO_TERMINATE_BOOT": 1, "PIF_STEP_TICKS": STEP_TICKS,
            "PIF_SAMPLES": SAMPLES}),
]
