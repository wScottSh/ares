"""Assembler self-test.

Each expected word was encoded by hand from the field layouts in the NEC VR4300 User's
Manual (U10504EJ): chapter 16 (CPU instructions: I-type op|rs|rt|imm, R-type
SPECIAL|rs|rt|rd|sa|funct, J-type op|target, REGIMM rt-selected, COP0 MF/MT/CO) and
chapter 17 (FPU: COP1|fmt|ft|fs|fd|funct, COP1 MF/MT/CF/CT rs-selected). The emux words
come from nemu64-test src/emux.rs. The second half cross-checks the nemu64-compatible
encoder API against the text assembler, so a suite table can never drift from it.

usage: python tools/n64-timing/romgen/selftest.py
"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "romgen"

from romgen import mips  # noqa: E402
from romgen.nemu import GPR, FR, RegisterIndex, CacheOp, RegimmOpcode, Assembler, u5, u26

HAND_CHECKED = [
    # (statement, address, expected word, manual reference)
    ("nop", 0, 0x00000000, "16 SLL r0,r0,0"),
    ("addiu $t0, $zero, 1", 0, 0x24080001, "16 ADDIU op=0x09"),
    ("lw $t1, 4($sp)", 0, 0x8FA90004, "16 LW op=0x23"),
    ("sw $ra, 20($sp)", 0, 0xAFBF0014, "16 SW op=0x2B"),
    ("ld $t4, 16($v1)", 0, 0xDC6C0010, "16 LD op=0x37"),
    ("jr $ra", 0, 0x03E00008, "16 JR funct=0x08"),
    ("jalr $t9", 0, 0x0320F809, "16 JALR rd=31 funct=0x09"),
    ("addu $v0, $a0, $a1", 0, 0x00851021, "16 ADDU funct=0x21"),
    ("lui $at, 0x8000", 0, 0x3C018000, "16 LUI op=0x0F"),
    ("ori $t0, $t0, 0x1234", 0, 0x35081234, "16 ORI op=0x0D"),
    ("div $a0, $a1", 0, 0x0085001A, "16 DIV funct=0x1A"),
    ("dsll32 $t0, $t1, 0", 0, 0x0009403C, "16 DSLL32 funct=0x3C"),
    ("syscall", 0, 0x0000000C, "16 SYSCALL funct=0x0C"),
    ("break", 0, 0x0000000D, "16 BREAK funct=0x0D"),
    ("teq $v0, $a0", 0, 0x00440034, "16 TEQ funct=0x34"),
    ("teqi $v0, 1", 0, 0x044C0001, "16 TEQI REGIMM rt=0x0C"),
    ("bgezal $zero, 8", 0, 0x04110001, "16 BGEZAL REGIMM rt=0x11"),
    ("beq $zero, $zero, 8", 0, 0x10000001, "16 BEQ op=0x04, offset=(target-(pc+4))>>2"),
    ("bne $a0, $zero, 0", 0, 0x1480FFFF, "16 BNE op=0x05, offset=-1"),
    ("jal 0x80000400", 0x80000000, 0x0C000100, "16 JAL op=0x03, target>>2"),
    ("mfc0 $t0, $status", 0, 0x40086000, "16 MFC0 COP0 rs=0, rd=12"),
    ("mtc0 $t0, $count", 0, 0x40884800, "16 MTC0 COP0 rs=4, rd=9"),
    ("dmtc0 $v0, $epc", 0, 0x40A27000, "16 DMTC0 COP0 rs=5, rd=14"),
    ("eret", 0, 0x42000018, "16 ERET CO funct=0x18"),
    ("tlbwi", 0, 0x42000002, "16 TLBWI CO funct=0x02"),
    ("cache 0x19, 0($t0)", 0, 0xBD190000, "16 CACHE op=0x2F, op field in rt"),
    ("add.s $f0, $f2, $f4", 0, 0x46041000, "17 ADD.fmt fmt=S(16)"),
    ("cvt.d.s $f0, $f2", 0, 0x46001021, "17 CVT.D.fmt funct=0x21"),
    ("dmtc1 $a0, $f0", 0, 0x44A40000, "17 DMTC1 rs=5"),
    ("ctc1 $t0, 31", 0, 0x44C8F800, "17 CTC1 rs=6, fs=31"),
    ("mfc2 $zero, 0", 0, 0x48000000, "16 MFCz z=2"),
    ("xlog $t0, $zero, 0", 0, 0x42800025, "emux XLOG (src/emux.rs encode_xlog)"),
    ("xioctl 1", 0, 0x4200006C, "emux XIOCTL exit (src/emux.rs encode_xioctl)"),
    ("xhexdump $t0, $t1", 0, 0x42848027,
     "emux XHEXDUMP (ares cpu/interpreter.cpp XRDn = OP>>20, XRTn = OP>>15, funct 0x27)"),
]

# Pseudo-instructions that expand to several words.
HAND_CHECKED_MULTI = [
    ("li $t0, 0x80001234", [0x3C088000, 0x35081234], "16 LUI op=0x0F + ORI op=0x0D"),
    # LLVM's no-$at `dla` sequence; %hi carries into 0x8001 because %lo is negative.
    ("dla $t4, 0x8000F234", [0x3C0C0000, 0x658C0000, 0x000C6438, 0x658C8001, 0x000C6438,
                             0x658CF234], "16 LUI, DADDIU op=0x19, DSLL funct=0x38 sa=16"),
]

CROSS_CHECK = [
    (Assembler.make_nop(), "nop"),
    (Assembler.make_lb(GPR.A2, 0, GPR.V1), "lb $a2, 0($v1)"),
    (Assembler.make_sdr(GPR.R0, 0, GPR.V1), "sdr $zero, 0($v1)"),
    (Assembler.make_beq(GPR.V1, GPR.R0, 1), "beq $zero, $v1, pc+8"),
    (Assembler.make_beql(GPR.R0, GPR.R0, 4), "beql $zero, $zero, pc+20"),
    (Assembler.make_bnel(GPR.R0, GPR.R0, 1), "bnel $zero, $zero, pc+8"),
    (Assembler.make_blezl(GPR.A0, 1), "blezl $a0, pc+8"),
    (Assembler.make_bgezal(GPR.R0, 3), "bgezal $zero, pc+16"),
    (Assembler.make_jr(GPR.T4), "jr $t4"),
    (Assembler.make_jalr(GPR.RA, GPR.T9), "jalr $ra, $t9"),
    (Assembler.make_move(GPR.K0, GPR.S2), "move $k0, $s2"),
    (Assembler.make_sub(GPR.T8, GPR.S5, GPR.S3), "sub $t8, $s5, $s3"),
    (Assembler.make_add(GPR.R0, GPR.V0, GPR.A0), "add $zero, $v0, $a0"),
    (Assembler.make_daddi(GPR.R0, GPR.V0, 1), "daddi $zero, $v0, 1"),
    (Assembler.make_div(GPR.A0, GPR.V0), "div $v0, $a0"),
    (Assembler.make_dmultu(GPR.A0, GPR.V0), "dmultu $v0, $a0"),
    (Assembler.make_mflo(GPR.A2), "mflo $a2"),
    (Assembler.make_mthi(GPR.V0), "mthi $v0"),
    (Assembler.make_tne(GPR.V0, GPR.A0), "tne $v0, $a0"),
    (Assembler.make_regimm_trap(RegimmOpcode.TNEI, GPR.V0.raw_value(), 0), "tnei $v0, 0"),
    (Assembler.make_sll(GPR.A0, GPR.A1, u5.new(5)), "sll $a0, $a1, 5"),
    (Assembler.make_srlv(GPR.T0, GPR.T1, GPR.T2), "srlv $t0, $t1, $t2"),
    (Assembler.make_mfc0(GPR.S3, RegisterIndex.Count), "mfc0 $s3, $count"),
    (Assembler.make_mtc0(GPR.R0, RegisterIndex.EntryHi), "mtc0 $zero, $entryhi"),
    (Assembler.make_dmfc0(GPR.V0, RegisterIndex.Random), "dmfc0 $v0, $random"),
    (Assembler.make_cop0_tlbwr(), "tlbwr"),
    (Assembler.make_cache(CacheOp.DataIndexLoadTag, 0, GPR.T4), "cache 5, 0($t4)"),
    (Assembler.make_cop1_add(FR.F0, FR.F2, FR.F4).s(), "add.s $f0, $f2, $f4"),
    (Assembler.make_cop1_div(FR.F6, FR.F2, FR.F0).d(), "div.d $f6, $f2, $f0"),
    (Assembler.make_cop1_cvt_w(FR.F0, FR.F2).l(), "cvt.w.l $f0, $f2"),
    (Assembler.make_cop1_round_w(FR.F0, FR.F2).s(), "round.w.s $f0, $f2"),
    (Assembler.make_dmtc1(GPR.A0, FR.F0), "dmtc1 $a0, $f0"),
    (Assembler.make_mfc1(GPR.A2, FR.F0), "mfc1 $a2, $f0"),
    (Assembler.make_cfc1(GPR.A2, u5.new(31)), "cfc1 $a2, 31"),
    (Assembler.make_ldc1(FR.F2, 0, GPR.V1), "ldc1 $f2, 0($v1)"),
    (Assembler.make_jal(u26.extract_u32(0x80000400, 2)), "jal 0x80000400"),
]


def main():
    failures = 0
    for text, addr, expected, ref in HAND_CHECKED:
        (got,) = mips.assemble_one(text, addr)
        if got != expected:
            failures += 1
            print(f"FAIL {text!r}: {got:#010x} != {expected:#010x} ({ref})")
    for text, expected, ref in HAND_CHECKED_MULTI:
        got = mips.assemble_one(text)
        if got != expected:
            failures += 1
            print(f"FAIL {text!r}: {[hex(w) for w in got]} != {[hex(w) for w in expected]} ({ref})")
    for word, text in CROSS_CHECK:
        (got,) = mips.assemble_one(text, 0x80000000, {"pc": 0x80000000})
        if got != word:
            failures += 1
            print(f"FAIL nemu API vs {text!r}: {word:#010x} != {got:#010x}")
    total = len(HAND_CHECKED) + len(HAND_CHECKED_MULTI) + len(CROSS_CHECK)
    print(f"assembler self-test: {total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
