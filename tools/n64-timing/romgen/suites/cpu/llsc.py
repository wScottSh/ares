"""SC and SCD against the VR4300 User's Manual (U10504EJ7V0UM00).

Expected values come from the manual, not from an emulator run:
- 16 "SC"/"SCD" (pp. 487-490): rt reads 1 after a store that succeeds and 0 after one that fails
  (the LLbit is clear). AddressTranslation runs whether or not the LLbit is set, and "if this
  instruction both fails and causes an exception, the exception takes precedence".
- 16 "ERET": ERET clears the LLbit, so an SC after an exception return fails.
- 6.2 "Precision of Exceptions": the excepting instruction is aborted and can be re-executed, so
  an SC that raises an exception leaves rt and memory as they were.

What the manual leaves open is run and reported, not checked: whether an SC that fails (LLbit
clear) to an address WatchLo matches raises Watch. The fork does not (it raises Watch only when the
store happens; verify-121). The "Watch on a failing SC" test checks only what holds either way, the
memory word unchanged, and prints `#bench cpu-llsc watch-fail-<op> exc=<n> exccode=<code> rt_lo=<rt>`,
which the calibration kit records from a console capture without comparing it.

Each value records RES[0..1] = rt (hi, lo) after the sequence, RES[2..3] = the memory word or
doubleword (hi, lo), RES[4..5] = rt as an exception handler sees it, RES[8] = exceptions taken
and RES[9] = Cause.ExcCode << 2.
"""
from ... import runtime as rt
from ...suite import Check, Step, Test, Value

BUF = rt.SCRATCH_BASE + 0x100                 # KSEG0, cached
BUF_PHYS = BUF & 0x1FFFFFFF
MAP_PAGE = (rt.SCRATCH_BASE & 0x1FFFFFFF) + 0x2000   # only ever reached uncached
MAP_UNC = 0xA0000000 | MAP_PAGE | 0x100
MAP_VA = 0x00010000
MAP_ADDR = MAP_VA + 0x100

EXC_TLBS = 3 << 2
EXC_WATCH = 23 << 2
STATUS_EXL = 2
WATCH_W = 1

OPS = {
    # name: (ll, sc, load, store, memory before, rt before)
    "SC": ("ll", "sc", "lw", "sw", 0x11112222, 0x5A5A0001),
    "SCD": ("lld", "scd", "ld", "sd", 0x1111222233334444, 0x5A5A00015A5A0002),
}


def li64(reg, value):
    hi, lo = value >> 32, value & 0xFFFFFFFF
    if not hi:
        return f"    li {reg}, {lo:#x}"
    return (f"    li {reg}, {hi:#x}\n    dsll32 {reg}, {reg}, 0\n    li $t5, {lo:#x}\n"
            f"    dsll32 $t5, $t5, 0\n    dsrl32 $t5, $t5, 0\n    or {reg}, {reg}, $t5")


def save_rt(offset):
    return f"    dsrl32 $t5, $t6, 0\n    sw $t5, {offset}($a1)\n    sw $t6, {offset + 4}($a1)"


ERET_CLEARS_LLBIT = """    mfc0 $t0, $status
    ori $t0, $t0, {exl}
    mtc0 $t0, $status
    la $t0, {name}_eret
    dmtc0 $t0, $epc
    nop
    nop
    eret
{name}_eret:"""

WATCH_ON = f"""    li $t0, {BUF_PHYS | WATCH_W:#x}
    mtc0 $t0, $watchlo
    mtc0 $zero, $watchhi
    nop
    nop
    nop
    nop"""

WATCH_OFF = "    mtc0 $zero, $watchlo\n    nop\n    nop\n    nop\n    nop"

# The generic handler returns to {name}_reexec instead of skipping: that stub stands in for a
# handler that saves rt, clears WatchLo and returns to the SC.
REEXEC = f"""    la $t0, DATA_BASE
    la $t1, {{name}}_reexec
    sd $t1, D_OVR_RET($t0)
    li $t1, {rt.STATUS_DEFAULT | STATUS_EXL:#x}
    sw $t1, D_OVR_STATUS($t0)
    li $t1, 1
    sw $t1, D_OVR_VALID($t0)
{WATCH_ON}
{{name}}_sc:
    {{sc}} $t6, 0($t4)
    la $t0, DATA_BASE
    b {{name}}_after
    sw $zero, D_OVR_VALID($t0)
{{name}}_reexec:
{save_rt(16)}
{WATCH_OFF}
    j {{name}}_sc
    nop
{{name}}_after:"""

# case: (description, expected rt or None for "unchanged", memory written, exception code,
#        rt seen by the handler)
CASES = {
    "success": (" (LLbit set: stores, rt = 1)", 1, True, None, None),
    "eret": (" (ERET between LL and SC: fails, rt = 0)", 0, False, None, None),
    "watch-skip": (" (Watch exception, handler skips the SC: rt and memory unchanged)", None, False, EXC_WATCH, None),
    "watch-reexec": (" (Watch exception, handler returns to the SC: handler sees rt unchanged, "
                     "SC re-executes after ERET and fails)", 0, False, EXC_WATCH, True),
    "tlb-skip": (" (LLbit set, TLB refill, handler skips the SC: rt and memory unchanged)", None, False, EXC_TLBS, None),
    "tlb-fail": (" (LLbit clear, TLB refill: the exception takes precedence over the failure)",
                 None, False, EXC_TLBS, None),
}


# Runs like a CASES entry, but only the memory word is checked; the exception count, ExcCode and rt
# are printed (module docstring).
WATCH_FAIL = "watch-fail"
WATCH_FAIL_DESC = " (LLbit clear, Watch armed on the address: memory unchanged; whether Watch fires is reported, not checked)"


def report_line(op):
    label = f"llsc_str_{op}_watch_fail".lower()
    head = f"#bench cpu-llsc {WATCH_FAIL}-{op.lower()} exc="
    code = f"""    la $a0, {label}
    jal pr_str
    nop
    jal pr_dec
    lw $a0, 32($a1)
    la $a0, llsc_str_exccode
    jal pr_str
    nop
    lw $a0, 36($a1)
    jal pr_dec
    srl $a0, $a0, 2
    la $a0, llsc_str_rt
    jal pr_str
    nop
    jal pr_hex
    lw $a0, 4($a1)
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop"""
    return code, f"{label}: .asciiz {rt.asm_string(head)}"


def routine(op, case):
    ll, sc, load, store, mem0, rt0 = OPS[op]
    name = f"llsc_{op}_{case}".lower().replace("-", "_")
    mapped = case.startswith("tlb")
    body = [f"{name}:", "    addiu $sp, $sp, -16", "    sd $ra, 0($sp)"]
    if mapped:
        body += ["    jal llsc_tlb_map", "    nop", f"    li $t4, {MAP_UNC:#x}"]
    else:
        body += [f"    li $t4, {BUF:#x}"]
    body += [li64("$t6", mem0), f"    {store} $t6, 0($t4)"]
    if mapped:
        body += [f"    li $t4, {MAP_ADDR:#x}"]
    body += [li64("$t6", rt0), "    sw $zero, 16($a1)", "    sw $zero, 20($a1)", f"    {ll} $t7, 0($t4)"]
    if case in ("eret", "tlb-fail", WATCH_FAIL):
        body += [ERET_CLEARS_LLBIT.format(exl=STATUS_EXL, name=name)]
    if mapped:
        body += ["    jal step_clear_tlb", "    nop"]
    body += ["    li $a0, 1", "    jal expect_begin", "    nop"]
    if case == "watch-reexec":
        body += [REEXEC.format(name=name, sc=sc)]
    else:
        if case in ("watch-skip", WATCH_FAIL):
            body += [WATCH_ON]
        body += [f"    {sc} $t6, 0($t4)"]
        if case in ("watch-skip", WATCH_FAIL):
            body += [WATCH_OFF]
    body += [save_rt(0)]
    if mapped:
        body += [f"    li $t4, {MAP_UNC:#x}"]
    body += [f"    {load} $t5, 0($t4)", "    dsrl32 $t0, $t5, 0" if load == "ld" else "    move $t0, $zero",
             "    sw $t0, 8($a1)", "    sw $t5, 12($a1)",
             "    addiu $a0, $a1, 32", "    jal expect_end", "    nop",
             "    lw $t5, 36($a1)", "    andi $t5, $t5, 0x7C", "    sw $t5, 36($a1)"]
    if case == WATCH_FAIL:
        body += [report_line(op)[0]]
    body += ["    ld $ra, 0($sp)", "    jr $ra", "    addiu $sp, $sp, 16"]
    return name, "\n".join(body)


def report_checks(op):
    mem0 = OPS[op][4]
    return [Check(rt.CHK_EQ_HEX, 2, mem0 >> 32, msg="memory after (high word)"),
            Check(rt.CHK_EQ_HEX, 3, mem0 & 0xFFFFFFFF, msg="memory after (low word)")]


def checks(op, case):
    _, _, _, _, mem0, rt0 = OPS[op]
    _, rt_after, stored, exc, handler = CASES[case]
    width = 0xFFFFFFFF if op == "SC" else (1 << 64) - 1
    rt_after = rt0 if rt_after is None else rt_after
    mem = (rt0 & width) if stored else mem0

    def pair(index, value, what):
        return [Check(rt.CHK_EQ_HEX, index, value >> 32, msg=f"{what} (high word)"),
                Check(rt.CHK_EQ_HEX, index + 1, value & 0xFFFFFFFF, msg=f"{what} (low word)")]

    out = [Check(rt.CHK_EQ_HEX, 8, 0 if exc is None else 1, msg="exceptions taken")]
    if exc is not None:
        out.append(Check(rt.CHK_EQ_HEX, 9, exc, msg="Cause.ExcCode << 2"))
    out += pair(0, rt_after, "rt after")
    out += pair(2, mem, "memory after")
    if handler:
        out += pair(4, rt0, "rt seen by the handler")
    return out


TLB_MAP = f"""
# One global entry: MAP_VA's even page -> MAP_PAGE, uncached (C = 2), dirty and valid.
llsc_tlb_map:
    mtc0 $zero, $index
    mtc0 $zero, $pagemask
    li $t0, {MAP_VA:#x}
    mtc0 $t0, $entryhi
    li $t0, {(MAP_PAGE >> 12) << 6 | 2 << 3 | 7:#x}
    mtc0 $t0, $entrylo0
    li $t0, 1
    mtc0 $t0, $entrylo1
    nop
    nop
    tlbwi
    nop
    jr $ra
    mtc0 $zero, $entryhi
"""


def asm():
    strings = [f"llsc_str_exccode: .asciiz {rt.asm_string(' exccode=')}",
               f"llsc_str_rt: .asciiz {rt.asm_string(' rt_lo=')}"] + [report_line(op)[1] for op in OPS]
    return "\n".join([TLB_MAP] + [routine(op, case)[1] for op in OPS for case in CASES] +
                     [routine(op, WATCH_FAIL)[1] for op in OPS] + strings + [".align 4"])


def build(suite):
    for op in OPS:
        suite.tests.append(Test(op, [Value(CASES[case][0], [Step(routine(op, case)[0], [], 0)], checks(op, case))
                                     for case in CASES]))
    suite.tests.append(Test("Watch on a failing SC", [
        Value(f" {op}{WATCH_FAIL_DESC}", [Step(routine(op, WATCH_FAIL)[0], [], 0)], report_checks(op)) for op in OPS]))
