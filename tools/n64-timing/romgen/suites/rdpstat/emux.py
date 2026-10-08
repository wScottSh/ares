"""emux XPROFREAD 0x04RF: the RDRAM channel counters of RI requester R, field F, that mmbench's
bus.tsv reports (cpu/emux.cpp). This guards the measuring tool, not a timing behavior.

Four uncached loads from RDRAM must each post a CpuSysAD burst: the power-on counter grows across
them, and a profile slot opened around them counts 4 to 8 bursts and 16 to 64 bytes read. A
requester index past RiBus::Requester::Count reads 0. Only the CPU's XPROFREAD runs here; the
RSP's (rsp/emux.cpp) forwards to it and is not covered.
"""
from ... import mips, runtime
from ...suite import Check, Step, Test, Value


def xprofread(rd, rt):
    return f"    .word {mips.emux(0x29, rd, rt):#010x}"


def xprof(code):
    return f"    .word {mips.emux(0x28, 8, code=code):#010x}"


# 0x04RF with R = 2 (CpuSysAD); F 0 bursts, 1 bytes read.
CPU_BURSTS, CPU_BYTES_READ = 0x0420, 0x0421
PAST_LAST_REQUESTER = 0x04C0
PROF_START, PROF_STOP, PROF_CLEAR = 1, 2, 3

ASM = "\n".join([
    "emux_bus_global:", "    lw $t1, 0($a0)", "    addiu $t0, $zero, -1", xprofread(8, 9), "    jr $ra", "    sw $t1, 0($a1)",
    "emux_bus_slot:", "    lw $t1, 0($a0)", "    move $t0, $zero", xprofread(8, 9), "    jr $ra", "    sw $t1, 0($a1)",
    "emux_prof_clear:", "    move $t0, $zero", xprof(PROF_CLEAR), "    jr $ra", "    nop",
    "emux_prof_start:", "    move $t0, $zero", xprof(PROF_START), "    jr $ra", "    nop",
    "emux_prof_stop:", "    move $t0, $zero", xprof(PROF_STOP), "    jr $ra", "    nop",
    "emux_uncached4:", "    lui $t0, 0xA010", "    lw $t1, 0($t0)", "    lw $t1, 0x100($t0)", "    lw $t1, 0x200($t0)",
    "    lw $t1, 0x300($t0)", "    jr $ra", "    nop",
])


def data():
    return ASM


def build(suite):
    suite.tests += [
        Test("emux 0x04RF: global CPU bursts grow across 4 uncached loads", [Value("", [
            Step("emux_bus_global", [CPU_BURSTS], 0), Step("emux_uncached4", [], 2), Step("emux_bus_global", [CPU_BURSTS], 1)],
            [Check(runtime.CHK_GE_REL, 1, 0, msg="not monotonic"), Check(runtime.CHK_NE_REL, 1, 0, msg="no new bursts")])]),
        Test("emux 0x04RF: slot CPU bursts and bytes over 4 uncached loads", [Value("", [
            Step("emux_prof_clear", [], 3), Step("emux_prof_start", [], 3), Step("emux_uncached4", [], 3),
            Step("emux_prof_stop", [], 3), Step("emux_bus_slot", [CPU_BURSTS], 0), Step("emux_bus_slot", [CPU_BYTES_READ], 4)],
            [Check(runtime.CHK_RANGE, 0, 4, 8, msg="slot bursts"), Check(runtime.CHK_RANGE, 4, 16, 64, msg="slot bytes read")])]),
        Test("emux 0x04RF: a requester past the last reads 0", [Value("", [
            Step("emux_bus_global", [PAST_LAST_REQUESTER], 0)],
            [Check(runtime.CHK_EQ_DEC, 0, 0, msg="out-of-range requester")])]),
    ]
