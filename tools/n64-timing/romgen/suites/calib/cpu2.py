"""Kit points for the cpu2 kit ROM (sets.py KITS["kit-cpu2"]): builders follow the bench convention
(suites/bench/benches.py Rom.point), kernels the bench kernel convention (asm.py).

Two harnesses. `exact` times a CPU-local event in four shots, the last three entered at pclk
offsets p, p + T and p + 2T + 1 (T the constant shot length), so they see both parities of the
half-pclk COUNT and lo + hi ticks is the event in pclk (nemu64-test's two-measurement sum,
timing/mod.rs). `walk` times bus-bound events in eight shots entered 0..7 pclk apart, covering the
3:2 pclk:rclk phase, and keeps the min, max and sum of two intervals.
"""
import struct
from dataclasses import dataclass, replace

from ..bench.benches import KSEG0, KSEG1, VI_OFF, Rom

CPU2_BUF = 0x005E0000                 # bank 5: kit-cpu2's own buffer, 64 KiB
# D-cache index 0x1F00 (addr & 0x1FF0) holds only the line buffer and the stack top, idle while a kernel runs.
DLINE = KSEG0 | (CPU2_BUF + 0x1F00)
DRAIN = KSEG1 | (CPU2_BUF + 0x8000)
TLB_PFN = (CPU2_BUF + 0x4000) >> 12   # the 8 KiB page pair the TLB Mod point maps
TLB_VA = 0x00002000
TLB_MISS_VA = 0x00006000
FS = 0x01000000

HARNESS = f"""
# Points the 0x000 and 0x180 vectors at cpu2_vec_stub (COUNT into $k1, then cpu2_vec), saving
# the six words it replaces. Clobbers t0-t3.
cpu2_vec_on:
    li $t0, 0xA0000000
    la $t1, cpu2_vec_save
    lw $t3, 0($t0)
    sw $t3, 0($t1)
    lw $t3, 4($t0)
    sw $t3, 4($t1)
    lw $t3, 8($t0)
    sw $t3, 8($t1)
    lw $t3, 0x180($t0)
    sw $t3, 12($t1)
    lw $t3, 0x184($t0)
    sw $t3, 16($t1)
    lw $t3, 0x188($t0)
    sw $t3, 20($t1)
    la $t1, cpu2_vec_stub
    lw $t3, 0($t1)
    sw $t3, 0($t0)
    sw $t3, 0x180($t0)
    lw $t3, 4($t1)
    sw $t3, 4($t0)
    sw $t3, 0x184($t0)
    lw $t3, 8($t1)
    sw $t3, 8($t0)
    b cpu2_vec_flush
    sw $t3, 0x188($t0)
cpu2_vec_off:
    li $t0, 0xA0000000
    la $t1, cpu2_vec_save
    lw $t3, 0($t1)
    sw $t3, 0($t0)
    lw $t3, 4($t1)
    sw $t3, 4($t0)
    lw $t3, 8($t1)
    sw $t3, 8($t0)
    lw $t3, 12($t1)
    sw $t3, 0x180($t0)
    lw $t3, 16($t1)
    sw $t3, 0x184($t0)
    lw $t3, 20($t1)
    sw $t3, 0x188($t0)
cpu2_vec_flush:
    lw $t3, 0x188($t0)
    li $t0, 0x80000000
    cache 0x10, 0($t0)
    cache 0x10, 0x180($t0)
    jr $ra
    nop

cpu2_vec_stub:
    mfc0 $k1, $count
    j cpu2_vec
    nop

# Exception handler of the cpu2 kernels: returns to $k0 with Status.IE cleared, so a pending
# interrupt cannot re-enter. Clobbers t6.
cpu2_vec:
    mfc0 $t6, $status
    ori $t6, $t6, 1
    xori $t6, $t6, 1
    mtc0 $t6, $status
    dmtc0 $k0, $epc
    nop
    nop
    eret

# Every TLB entry invalid, with a distinct kseg0 VPN2 and ASID 1 so none can match; ASID 0 after.
cpu2_tlb_clear:
    mtc0 $zero, $entrylo0
    mtc0 $zero, $entrylo1
    mtc0 $zero, $pagemask
    li $t0, 0x80000001
    move $t1, $zero
cpu2_tc_loop:
    mtc0 $t1, $index
    mtc0 $t0, $entryhi
    nop
    nop
    tlbwi
    addiu $t1, $t1, 1
    ori $t2, $zero, 0x2000
    addu $t0, $t0, $t2
    sltiu $t2, $t1, 32
    bnez $t2, cpu2_tc_loop
    nop
    jr $ra
    mtc0 $zero, $entryhi

# Entry 0: TLB_VA's 8 KiB page pair, global, valid, not dirty, uncached.
cpu2_tlb_map:
    mtc0 $zero, $index
    mtc0 $zero, $pagemask
    li $t0, {TLB_VA:#x}
    mtc0 $t0, $entryhi
    li $t0, {(TLB_PFN << 6) | (2 << 3) | 3:#x}
    mtc0 $t0, $entrylo0
    li $t0, {((TLB_PFN + 1) << 6) | (2 << 3) | 3:#x}
    mtc0 $t0, $entrylo1
    nop
    nop
    tlbwi
    nop
    jr $ra
    mtc0 $zero, $entryhi

# Waits, at most 2^17 polls, for PI_STATUS DMA and IO busy to clear. Clobbers v0, t6.
cpu2_pi_wait:
    lui $v0, 2
cpu2_pw_loop:
    lui $t6, 0xA460
    lw $t6, 0x10($t6)
    andi $t6, $t6, 3
    beqz $t6, cpu2_pw_done
    addiu $v0, $v0, -1
    bnez $v0, cpu2_pw_loop
    nop
cpu2_pw_done:
    jr $ra
    nop

cpu2_spin:
    li $t6, 64
cpu2_spin_loop:
    addiu $t6, $t6, -1
    bnez $t6, cpu2_spin_loop
    nop
    jr $ra
    nop

# v1 = three packed 16-bit shot tick counts (low 48 bits). RES[2] = lo, RES[3] = hi, v0 = lo + hi.
cpu2_minmax3:
    andi $t0, $v1, 0xFFFF
    dsrl $t1, $v1, 16
    andi $t1, $t1, 0xFFFF
    dsrl32 $t2, $v1, 0
    andi $t2, $t2, 0xFFFF
    move $t3, $t0
    move $t4, $t0
    sltu $t5, $t1, $t3
    beqz $t5, cpu2_mm_a
    nop
    move $t3, $t1
cpu2_mm_a:
    sltu $t5, $t2, $t3
    beqz $t5, cpu2_mm_b
    nop
    move $t3, $t2
cpu2_mm_b:
    sltu $t5, $t4, $t1
    beqz $t5, cpu2_mm_c
    nop
    move $t4, $t1
cpu2_mm_c:
    sltu $t5, $t4, $t2
    beqz $t5, cpu2_mm_d
    nop
    move $t4, $t2
cpu2_mm_d:
    sw $t3, 0($a1)
    sw $t4, 4($a1)
    jr $ra
    addu $v0, $t3, $t4

.align 8
cpu2_vec_save: .word 0, 0, 0, 0, 0, 0
cpu2_save: .word 0, 0
.align 16
cpu2_ldi_data: .word 0x3F800000, 0, 0x3FF00000, 0
.align 32
cpu2_iline:
    jr $ra
    nop
.align 32
"""


def exact(name, body, setup="", cleanup="", pre="", post=""):
    """v0 = lo + hi = the event in pclk; RES[2] = lo, RES[3] = hi ticks; RES[4] = shots (of 4) whose
    end was an exception entry ($k1 stamped by cpu2_vec_stub). The body runs from the mfc0 that
    starts the time to {name}_cont, where an exception returns. It may use t0-t5, t9, v0, at and the
    FPRs; t6 dies at an exception."""
    return f"""
{name}:
    move $t7, $ra
    move $v1, $zero
    move $a3, $zero
{pre}
    li $a2, 4
{name}_shot:
{setup}
    la $k0, {name}_cont
    move $k1, $zero
    sltiu $t6, $a2, 2
    xori $t6, $t6, 1
    sll $t6, $t6, 2
    la $t9, {name}_sled
    addu $t9, $t9, $t6
    jr $t9
    nop
{name}_sled:
    nop
    mfc0 $t8, $count
{body}
{name}_cont:
    mfc0 $t9, $count
    beqz $k1, {name}_nofire
    nop
    move $t9, $k1
    addiu $a3, $a3, 1
{name}_nofire:
    subu $t9, $t9, $t8
    andi $t9, $t9, 0xFFFF
    dsll $v1, $v1, 16
    or $v1, $v1, $t9
{cleanup}
    addiu $a2, $a2, -1
    bnez $a2, {name}_shot
    nop
{post}
    move $k0, $zero
    move $k1, $zero
    jal cpu2_minmax3
    sw $a3, 8($a1)
    move $ra, $t7
    jr $ra
    nop
"""


SLED7 = "\n".join(["    nop"] * 7)


def walk(name, prep, op, access="", post=""):
    """Nine shots, the last eight entered 0..7 pclk apart. v0 = min op ticks; RES[2] = max op,
    RES[3] = sum op, RES[4] = min access, RES[5] = max access, RES[6] = sum access (eight shots).
    op is timed from one mfc0 to the next, access from there to a third."""
    return f"""
{name}:
    move $t7, $ra
    li $a3, -1
    sw $zero, 0($a1)
    sw $zero, 4($a1)
    sw $a3, 8($a1)
    sw $zero, 12($a1)
    sw $zero, 16($a1)
    li $a2, 9
{name}_shot:
{prep}
    andi $t6, $a2, 7
    sll $t6, $t6, 2
    la $t9, {name}_sled
    addu $t9, $t9, $t6
    jr $t9
    nop
{name}_sled:
{SLED7}
    mfc0 $t8, $count
{op}
    mfc0 $t9, $count
{access}
    mfc0 $v1, $count
    subu $v1, $v1, $t9
    subu $t9, $t9, $t8
    addiu $t6, $a2, -9
    beqz $t6, {name}_next
    sltu $t6, $t9, $a3
    beqz $t6, {name}_a
    nop
    move $a3, $t9
{name}_a:
    lw $t6, 0($a1)
    sltu $t6, $t6, $t9
    beqz $t6, {name}_b
    nop
    sw $t9, 0($a1)
{name}_b:
    lw $t6, 8($a1)
    sltu $t6, $v1, $t6
    beqz $t6, {name}_c
    nop
    sw $v1, 8($a1)
{name}_c:
    lw $t6, 12($a1)
    sltu $t6, $t6, $v1
    beqz $t6, {name}_d
    nop
    sw $v1, 12($a1)
{name}_d:
    lw $t6, 4($a1)
    addu $t6, $t6, $t9
    sw $t6, 4($a1)
    lw $t6, 16($a1)
    addu $t6, $t6, $v1
    sw $t6, 16($a1)
{name}_next:
    addiu $a2, $a2, -1
    bnez $a2, {name}_shot
    nop
{post}
    move $ra, $t7
    jr $ra
    move $v0, $a3
"""


EXACT_EXTRA = ("lo", "hi", "fired")
WALK_EXTRA = ("op_max", "op_sum", "next_min", "next_max", "next_sum")


@dataclass(frozen=True)
class Point:
    rom: str
    point: str
    kernel: str
    text: str
    consts: tuple
    args: tuple = ()
    reps: int = 2
    flags: int = 0
    extra: tuple = EXACT_EXTRA


def nops(n):
    return "\n".join(["    nop"] * n)


def ident(rom, point):
    return "cpu2_" + "_".join([rom, point]).replace("-", "_").replace(".", "_").replace("^", "e")


VEC_ON = "    jal cpu2_vec_on\n    nop"
VEC_OFF = "    jal cpu2_vec_off\n    nop"
STATUS_CLEAR = """    mfc0 $t1, $status
    li $t2, {mask:#x}
    and $t1, $t1, $t2
    mtc0 $t1, $status"""
STATUS_SET = """    mfc0 $t1, $status
    li $t2, {bits:#x}
    or $t1, $t1, $t2
    mtc0 $t1, $status
    nop
    nop"""


def exact_point(rom, point, body, consts, setup="", cleanup="", pre="", post=""):
    name = ident(rom, point)
    sub = lambda s: s.replace("{cont}", name + "_cont")
    return Point(rom, point, name, exact(name, sub(body), sub(setup), cleanup, pre, post), tuple(consts))


def base_points():
    """Harness offsets: N nops cost N pclk (cpu.issue), so pclk(base-nopN) - N is the harness's own."""
    out = [exact_point("base", f"nop{n}", nops(n), [("nops", n)]) for n in (0, 1, 2, 3)]
    out.append(exact_point("base", "jump", "    j {cont}\n    nop", [("nops", "j")]))
    return out


ADDR_BAD = KSEG0 | (CPU2_BUF + 0x102)
WATCH_PHYS = CPU2_BUF + 0x100
TLB_CLEAR = "    jal cpu2_tlb_clear\n    nop"
FPU_RESTORE = "    li $t1, FCSR_DEFAULT\n    ctc1 $t1, 31"
FS_CLEAR = f"    li $t1, {FS:#x}\n    ctc1 $t1, 31"


def watch_setup(bits):
    return (f"    li $t0, {KSEG0 | WATCH_PHYS:#x}\n    lw $t1, 0($t0)\n    li $t2, {WATCH_PHYS | bits:#x}\n"
            "    mtc0 $t2, $watchlo\n    mtc0 $zero, $watchhi\n    nop\n    nop")


def exception_points():
    """COUNT from the mfc0 before the faulting instruction to the vector's first instruction.
    Each runs with cpu2_vec patched in and returns to {cont}; eret needs no vector."""
    rows = [
        # point, exc, body, setup, cleanup, pre, post
        ("adel-lw", "AdEL", "    lw $t1, 0($t0)", f"    li $t0, {ADDR_BAD:#x}", "", "", ""),
        ("ades-sw", "AdES", "    sw $zero, 0($t0)", f"    li $t0, {ADDR_BAD:#x}", "", "", ""),
        ("ades-sd", "AdES", "    sd $zero, 0($t0)", f"    li $t0, {ADDR_BAD + 2:#x}", "", "", ""),
        ("tlbl-lw", "TLBL", "    lw $t1, 0($t0)", f"    li $t0, {TLB_MISS_VA:#x}", "", TLB_CLEAR, ""),
        ("tlbs-sw", "TLBS", "    sw $zero, 0($t0)", f"    li $t0, {TLB_MISS_VA:#x}", "", TLB_CLEAR, ""),
        ("mod-sw", "Mod", "    sw $zero, 0($t0)", f"    li $t0, {TLB_VA:#x}", "",
         TLB_CLEAR + "\n    jal cpu2_tlb_map\n    nop", TLB_CLEAR),
        ("jr-aligned", "none", "    jr $t0\n    nop", "    la $t0, {cont}", "", "", ""),
        ("fetch-ade", "AdEL-fetch", "    jr $t0\n    nop", "    la $t0, {cont}\n    addiu $t0, $t0, 2", "", "", ""),
        ("watch-lw", "Watch", "    lw $t1, 0($t0)", watch_setup(2), "    mtc0 $zero, $watchlo", "", ""),
        ("watch-sw", "Watch", "    sw $t1, 0($t0)", watch_setup(1), "    mtc0 $zero, $watchlo", "", ""),
        ("irq-sw", "Int-IP0", "    mtc0 $t2, $cause\n" + nops(16),
         "    mtc0 $zero, $cause\n" + STATUS_SET.format(bits=0x101) + "\n    li $t2, 0x100",
         "    mtc0 $zero, $cause\n" + STATUS_CLEAR.format(mask=0xFFFFFEFE), "", ""),
        # The timer point's start is the COMPARE value, so its lo/hi are ticks from the match.
        ("irq-timer", "Int-IP7", "    addiu $t8, $t8, 16\n    mtc0 $t8, $compare\n    li $t1, 64\n{cont}_spin:\n"
         + nops(5) + "\n    addiu $t1, $t1, -1\n    bgtz $t1, {cont}_spin\n    nop",
         "    mfc0 $t1, $count\n    addiu $t1, $t1, -1\n    mtc0 $t1, $compare\n" + STATUS_SET.format(bits=0x8001),
         "    mfc0 $t1, $count\n    addiu $t1, $t1, -1\n    mtc0 $t1, $compare\n"
         + STATUS_CLEAR.format(mask=0xFFFF7FFE),
         "    la $t0, cpu2_save\n    mfc0 $t1, $compare\n    sw $t1, 0($t0)",
         "    la $t0, cpu2_save\n    lw $t1, 0($t0)\n    mtc0 $t1, $compare"),
        ("fpe-ctc1-v", "FPE-V", "    ctc1 $t1, 31", f"    li $t1, {FS | 1 << 16 | 1 << 11:#x}", FS_CLEAR, "",
         FPU_RESTORE),
        ("fpe-ctc1-e", "FPE-E", "    ctc1 $t1, 31", f"    li $t1, {FS | 1 << 17:#x}", FS_CLEAR, "", FPU_RESTORE),
    ]
    out = [exact_point("exc", point, body, [("exc", exc)], setup, cleanup, VEC_ON + "\n" + pre, post + "\n" + VEC_OFF)
           for point, exc, body, setup, cleanup, pre, post in rows]
    # One fork rep of the timer point reads 25 where the rest read 2, so its metric is the min of four.
    out = [replace(p, reps=4) if p.point == "irq-timer" else p for p in out]
    out.append(exact_point("exc", "eret", "    eret", [("exc", "none")],
                           "    la $t0, {cont}\n    dmtc0 $t0, $epc\n" + STATUS_SET.format(bits=2)))
    return out


LDI_SETUP = ("    la $t0, cpu2_ldi_data\n    lw $t1, 0($t0)\n    lwc1 $f6, 0($t0)\n    ldc1 $f8, 8($t0)\n"
             "    move $t2, $zero")


def ldi_points():
    """cpu.ldi's extensions: a load's consumer in the next slot, one slot later, or independent."""
    rows = [
        ("lwc1-add-s-next", "    lwc1 $f2, 0($t0)\n    add.s $f4, $f2, $f2", False),
        ("lwc1-add-s-gap", "    lwc1 $f2, 0($t0)\n    nop\n    add.s $f4, $f2, $f2", False),
        ("lwc1-add-s-indep", "    lwc1 $f2, 0($t0)\n    add.s $f4, $f6, $f6", False),
        ("ldc1-add-d-next", "    ldc1 $f2, 8($t0)\n    add.d $f4, $f2, $f2", False),
        ("ldc1-add-d-gap", "    ldc1 $f2, 8($t0)\n    nop\n    add.d $f4, $f2, $f2", False),
        ("ldc1-add-d-indep", "    ldc1 $f2, 8($t0)\n    add.d $f4, $f8, $f8", False),
        ("lw-mtc1-next", "    lw $t1, 0($t0)\n    mtc1 $t1, $f10", False),
        ("lw-mtc1-indep", "    lw $t1, 0($t0)\n    mtc1 $t2, $f10", False),
        ("lw-mtc2-next", "    lw $t1, 0($t0)\n    mtc2 $t1, 0", True),
        ("lw-mtc2-gap", "    lw $t1, 0($t0)\n    nop\n    mtc2 $t1, 0", True),
        ("lw-mtc2-indep", "    lw $t1, 0($t0)\n    mtc2 $t2, 0", True),
        ("lw-mfc2-next", "    lw $t1, 0($t0)\n    mfc2 $t1, 0", True),
        # BC1T (offset 1, so taken and not taken both land after the delay slot) has tf = 1 in
        # its rt field: a pending load to $at overlaps it.
        ("lw-at-bc1t", "    lw $at, 0($t0)\n    .word 0x45010001\n    nop", False),
        ("lw-t1-bc1t", "    lw $t1, 0($t0)\n    .word 0x45010001\n    nop", False),
    ]
    return [exact_point("ldi", point, body, [("cu2", int(cu2))], LDI_SETUP, "",
                        STATUS_SET.format(bits=0x40000000) if cu2 else "",
                        STATUS_CLEAR.format(mask=0xBFFFFFFF) if cu2 else "")
            for point, body, cu2 in rows]


def f32(x):
    return struct.unpack(">I", struct.pack(">f", x))[0]


def f64(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


INF = float("inf")
FPU = [
    # point, op, fs bits, ft bits, operand class
    ("div-d-1e300-by-0", "div.d", f64(1e300), f64(0.0), "trivial"),
    ("div-d-1e300-by-1.5", "div.d", f64(1e300), f64(1.5), "control"),
    ("div-d-0-by-1e300", "div.d", f64(0.0), f64(1e300), "trivial"),
    ("mul-s-pow2", "mul.s", f32(3.3), f32(2.0 ** -100), "trivial"),
    ("mul-s-normal", "mul.s", f32(3.3), f32(1.7), "control"),
    ("mul-d-pow2", "mul.d", f64(3.3), f64(2.0 ** 700), "trivial"),
    ("mul-d-normal", "mul.d", f64(3.3), f64(1.7), "control"),
    ("mul-s-denorm", "mul.s", f32(1.5), 0x00000001, "operand-fpe"),
    ("mul-d-denorm", "mul.d", f64(1.5), 0x0000000000000001, "operand-fpe"),
    ("sub-s-nan", "sub.s", 0x7F800001, f32(1.0), "operand-fpe"),
    ("add-d-neginf", "add.d", f64(-INF), f64(1.0), "trivial"),
    ("sqrt-d-neg", "sqrt.d", f64(-4.0), 0, "trivial"),
    ("sqrt-d-4", "sqrt.d", f64(4.0), 0, "control"),
    ("ceil-w-s-below-2^31", "ceil.w.s", f32(2147483520.0), 0, "control"),
    ("ceil-w-s-3e9", "ceil.w.s", f32(3e9), 0, "result-fpe"),
    ("ceil-w-s-neg-2^31-256", "ceil.w.s", f32(-2147483904.0), 0, "result-fpe"),
    ("ceil-w-s-5e9", "ceil.w.s", f32(5e9), 0, "operand-fpe"),
    ("trunc-l-d-2^40", "trunc.l.d", f64(2.0 ** 40 + 0.5), 0, "threshold"),
    ("trunc-l-d-2^52", "trunc.l.d", f64(2.0 ** 52 + 0.5), 0, "threshold"),
    ("trunc-l-d-2^54", "trunc.l.d", f64(2.0 ** 54), 0, "operand-fpe"),
    ("cvt-d-l-0", "cvt.d.l", 0, 0, "trivial"),
    ("cvt-d-l-1", "cvt.d.l", 1, 0, "control"),
    ("cvt-s-l-0", "cvt.s.l", 0, 0, "trivial"),
]
UNARY = ("sqrt", "ceil", "trunc", "cvt")


def fpu_operands():
    return "\n".join([".align 8"] + [f"cpu2_fop_{i}: .dword {fs:#x}, {ft:#x}" for i, (_, _, fs, ft, _) in enumerate(FPU)])


def fpu_points():
    """cpu.fpu-trivial and cpu.exc-fpu-detect class members the nemu64 COP1 tables do not sample.
    FCSR has no enables, so only an unimplemented-operation cause (E) raises."""
    out = []
    for i, (point, op, _fs, _ft, cls) in enumerate(FPU):
        args = "$f6, $f2" if op.startswith(UNARY) else "$f6, $f2, $f4"
        setup = f"    la $t0, cpu2_fop_{i}\n    ldc1 $f2, 0($t0)\n    ldc1 $f4, 8($t0)\n" + FS_CLEAR
        out.append(exact_point("fpu", point, f"    {op} {args}", [("op", op), ("class", cls)], setup, FS_CLEAR,
                               VEC_ON, FPU_RESTORE + "\n" + VEC_OFF))
    return out


D_OPS = [("d-index-wb-inv", 0x01), ("d-index-load-tag", 0x05), ("d-index-store-tag", 0x09),
         ("d-create-dirty", 0x0D), ("d-hit-inv", 0x11), ("d-hit-wb-inv", 0x15), ("d-hit-wb", 0x19)]
I_OPS = [("i-index-inv", 0x00), ("i-index-load-tag", 0x04), ("i-index-store-tag", 0x08),
         ("i-hit-inv", 0x10), ("i-fill", 0x14), ("i-hit-wb", 0x18)]
# Each state first owns the index (the load or call evicts and writes back any other line there),
# so the index ops below never drop another address's dirty data.
D_STATE = {
    "absent": "    lw $t1, 0($t0)\n    cache 0x11, 0($t0)",
    "clean": "    lw $t1, 0($t0)\n    cache 0x11, 0($t0)\n    lw $t1, 0($t0)",
    "dirty": "    lw $t1, 0($t0)\n    cache 0x11, 0($t0)\n    lw $t1, 0($t0)\n    sw $t1, 0($t0)",
}
I_STATE = {
    "absent": "    jalr $t0\n    nop\n    cache 0x10, 0($t0)",
    "clean": "    jalr $t0\n    nop\n    cache 0x10, 0($t0)\n    jalr $t0\n    nop",
}
CACHE_PREP = """    mtc0 $zero, $taglo
    mtc0 $zero, $taghi
{line}
{state}
    li $t5, {drain:#x}
    lw $t1, 0($t5)
    jal cpu2_spin
    nop"""


def cache_points():
    """Each CACHE op on its line in each state (op = the CACHE alone), then the access that shows its
    effect (next = a load from the D line, a call into the I line)."""
    out = []
    for side, ops, states, line, access in (
            ("d", D_OPS, D_STATE, f"    li $t0, {DLINE:#x}", "    lw $t1, 0($t0)"),
            ("i", I_OPS, I_STATE, "    la $t0, cpu2_iline", "    jalr $t0\n    nop")):
        for op_name, code in ops:
            for state, prep in states.items():
                point = f"{op_name}-{state}"
                name = ident("cache", point)
                text = walk(name, CACHE_PREP.format(line=line, state=prep, drain=DRAIN),
                            f"    cache {code:#x}, 0($t0)", access)
                out.append(Point("cache", point, name, text, (("cache", side), ("op", f"{code:#x}"), ("state", state)),
                                 reps=1, flags=VI_OFF, extra=WALK_EXTRA))
    return out


STORE_TARGETS = [("rdram", KSEG1 | (CPU2_BUF + 0x9000)), ("sp-semaphore", 0xA404001C),
                 ("pi-cart", KSEG1 | 0x10000000)]
LOAD_TARGETS = [("rdram", KSEG1 | (CPU2_BUF + 0xA000)), ("mi-version", 0xA4300004),
                ("pi-cart", KSEG1 | 0x10000000), ("dcache-hit", KSEG0 | (CPU2_BUF + 0x1E00))]
WB_N = range(5)
WB_PREP = f"""    lw $t0, 0($a0)
    lw $t2, 4($a0)
    move $t1, $zero
    jal cpu2_pi_wait
    nop
    lw $t3, 0($t2)
    li $t5, {DRAIN:#x}
    lw $t3, 0($t5)
    jal cpu2_spin
    nop"""


def wb_points():
    """N = 0..4 stores of 0 to one target, then one load from another, timed as one op. The store
    value is 0 at every target: SP_SEMAPHORE takes any write as a release, and the cartridge word is
    what pi-io-write already writes."""
    out = []
    for n in WB_N:
        name = f"cpu2_wb{n}"
        text = walk(name, WB_PREP, "\n".join(["    sw $t1, 0($t0)"] * n + ["    lw $t3, 0($t2)"]),
                    post="    jal cpu2_pi_wait\n    nop")
        for sname, saddr in STORE_TARGETS:
            for lname, laddr in LOAD_TARGETS:
                out.append(Point("wb", f"{sname}-{n}-{lname}", name, text,
                                 (("stores", n), ("store", sname), ("load", lname)), (saddr, laddr), reps=1,
                                 flags=VI_OFF, extra=WALK_EXTRA[:2]))
    return out


POINTS = base_points() + exception_points() + ldi_points() + fpu_points() + cache_points() + wb_points()


def builder(rom_name):
    def build(suite):
        rom = Rom(suite, "cpu2-" + rom_name)
        for p in POINTS:
            if p.rom == rom_name:
                rom.point(p.point, p.kernel, list(p.args), list(p.consts), reps=p.reps, flags=p.flags,
                          extra=list(p.extra))
    build.__name__ = "cpu2_" + rom_name
    return build


BUILDERS = [builder(r) for r in dict.fromkeys(p.rom for p in POINTS)]
ASM = "\n".join([HARNESS, fpu_operands()] + list({p.kernel: p.text for p in POINTS}.values()))
