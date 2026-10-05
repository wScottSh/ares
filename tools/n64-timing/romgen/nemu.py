"""nemu64-test compatible encoder API and constants.

A Python port of thelemmy/nemu64-test @ 9a8b9f7 src/assembler.rs (Assembler::make_*), plus the
COP0/COP1 register types the test tables reference (src/cop0.rs, src/cop1.rs). Names and
argument orders mirror the Rust, so translated test tables read the same as the original.
Note the Rust quirk kept here: make_beq(a, b, off) puts `a` in the rt field and `b` in rs.

nemu64-test is MIT licensed; see suites/nemu64/LICENSE.nemu64-test.
"""
import enum
import struct
from fractions import Fraction

from . import mips


class GPR(enum.IntEnum):
    R0 = 0; AT = 1; V0 = 2; V1 = 3; A0 = 4; A1 = 5; A2 = 6; A3 = 7
    T0 = 8; T1 = 9; T2 = 10; T3 = 11; T4 = 12; T5 = 13; T6 = 14; T7 = 15
    S0 = 16; S1 = 17; S2 = 18; S3 = 19; S4 = 20; S5 = 21; S6 = 22; S7 = 23
    T8 = 24; T9 = 25; K0 = 26; K1 = 27; GP = 28; SP = 29; S8 = 30; RA = 31

    def raw_value(self):
        return int(self)


FR = enum.IntEnum("FR", {f"F{i}": i for i in range(32)})


class RegisterIndex(enum.IntEnum):
    Index = 0x00; Random = 0x01; EntryLo0 = 0x02; EntryLo1 = 0x03; Context = 0x04
    PageMask = 0x05; Wired = 0x06; _Unused7 = 0x07; BadVAddr = 0x08; Count = 0x09
    EntryHi = 0x0A; Compare = 0x0B; Status = 0x0C; Cause = 0x0D; ExceptPC = 0x0E
    PRevID = 0x0F; Config = 0x10; LLAddr = 0x11; WatchLo = 0x12; WatchHi = 0x13
    XContext = 0x14; PErr = 0x1A; CacheErr = 0x1B; TagLo = 0x1C; TagHi = 0x1D; ErrorEPC = 0x1E


class CacheOp(enum.IntEnum):
    InstructionIndexInvalidate = 0b000_00
    DataIndexWriteBackInvalidate = 0b000_01
    InstructionIndexLoadTag = 0b001_00
    DataIndexLoadTag = 0b001_01
    InstructionIndexStoreTag = 0b010_00
    DataIndexStoreTag = 0b010_01
    DataCreateDirtyExclusive = 0b011_01
    InstructionHitInvalidate = 0b100_00
    DataHitInvalidate = 0b100_01
    InstructionFill = 0b101_00
    DataHitWriteBackInvalidate = 0b101_01
    InstructionHitWriteBack = 0b110_00
    DataHitWriteBack = 0b110_01


Opcode = enum.IntEnum("Opcode", {k.upper(): v for k, v in mips.OP.items()} | {"_I28": 28})
RegimmOpcode = enum.IntEnum("RegimmOpcode", {k.upper(): v for k, v in mips.REGIMM.items()})
SpecialOpcode = enum.IntEnum("SpecialOpcode", {k.upper(): v for k, v in mips.FUNCT.items()})

_COP1_FLOAT = {
    "ADD": 0, "SUB": 1, "MUL": 2, "DIV": 3, "SQRT": 4, "ABS": 5, "MOV": 6, "NEG": 7,
    "ROUND_L": 8, "TRUNC_L": 9, "CEIL_L": 10, "FLOOR_L": 11, "ROUND_W": 12, "TRUNC_W": 13,
    "CEIL_W": 14, "FLOOR_W": 15, "CVT_S": 32, "CVT_D": 33, "CVT_W": 36, "CVT_L": 37,
    "C_F": 48, "C_UN": 49, "C_EQ": 50, "C_UEQ": 51, "C_OLT": 52, "C_ULT": 53, "C_OLE": 54,
    "C_ULE": 55, "C_SF": 56, "C_NGLE": 57, "C_SEQ": 58, "C_NGL": 59, "C_LT": 60, "C_NGE": 61,
    "C_LE": 62, "C_NGT": 63,
}
for _i in list(range(16, 32)) + [34, 35] + list(range(38, 48)):
    _COP1_FLOAT[f"_F{_i}"] = _i
Cop1FloatInstruction = enum.IntEnum("Cop1FloatInstruction", _COP1_FLOAT)
Cop1Condition = enum.IntEnum(
    "Cop1Condition", {k[2:]: v for k, v in _COP1_FLOAT.items() if k.startswith("C_")})


class _UInt:
    """arbitrary-int's uN::new / uN::extract_u32."""

    def __init__(self, bits):
        self.bits = bits

    def new(self, value):
        if not 0 <= value < (1 << self.bits):
            raise ValueError(value)
        return value

    def extract_u32(self, value, start):
        return (value >> start) & ((1 << self.bits) - 1)

    extract_u64 = extract_u32


u2, u5, u24, u26, u27 = _UInt(2), _UInt(5), _UInt(24), _UInt(26), _UInt(27)


class ExceptionTimingMode(enum.IntEnum):
    Off = 0
    JustFire = 1
    Roundtrip = 2


class _Bits:
    """A bitbybit-style u32 register with with_<field>(value) builders."""

    FIELDS = {}

    def __init__(self, raw=0):
        self.raw = raw

    def raw_value(self):
        return self.raw

    def __getattr__(self, name):
        if name.startswith("with_") and name[5:] in self.FIELDS:
            lo, width = self.FIELDS[name[5:]]
            mask = ((1 << width) - 1) << lo

            def setter(value):
                value = int(getattr(value, "raw", value))
                return type(self)((self.raw & ~mask) | ((value << lo) & mask))
            return setter
        raise AttributeError(name)

    def __eq__(self, other):
        return type(self) is type(other) and self.raw == other.raw

    def __hash__(self):
        return hash((type(self).__name__, self.raw))

    def __repr__(self):
        return f"{type(self).__name__}({self.raw:#010x})"


class Status(_Bits):
    FIELDS = {
        "cop3usable": (31, 1), "cop2usable": (30, 1), "cop1usable": (29, 1), "cop0usable": (28, 1),
        "reduced_power": (27, 1), "fpu64": (26, 1), "reverse_endian": (25, 1),
        "tlb_miss_vectors": (22, 1), "tlb_shutdown": (21, 1), "soft_reset": (20, 1),
        "cop0_condition": (18, 1), "interrupt_mask_sw2": (9, 1), "interrupt_mask_sw1": (8, 1),
        "kx": (7, 1), "sx": (6, 1), "ux": (5, 1), "ksu": (3, 2), "erl": (2, 1), "exl": (1, 1),
        "ie": (0, 1),
    }


Status.ZERO = Status(0)
Status.DEFAULT = Status.ZERO.with_cop1usable(True).with_fpu64(True)
Status.ADDRESSING_MODE_64_BIT = Status.DEFAULT.with_kx(True).with_sx(True).with_ux(True)


class Cause(_Bits):
    FIELDS = {
        "branch_delay": (31, 1), "coprocessor_error": (28, 2), "interrupt_compare": (15, 1),
        "interrupt_sw2": (9, 1), "interrupt_sw1": (8, 1), "exception": (2, 5),
    }


Cause.DEFAULT = Cause(0)


class FCSRFlags(_Bits):
    FIELDS = {"invalid_operation": (4, 1), "division_by_zero": (3, 1), "overflow": (2, 1),
              "underflow": (1, 1), "inexact_operation": (0, 1)}


FCSRFlags.DEFAULT = FCSRFlags(0)
FCSRFlags.NONE = FCSRFlags(0)
FCSRFlags.ALL = FCSRFlags(0x1F)


class FCSR(_Bits):
    FIELDS = {
        "flush_denorm_to_zero": (24, 1), "condition": (23, 1),
        "enable_invalid_operation": (11, 1), "enable_division_by_zero": (10, 1),
        "enable_overflow": (9, 1), "enable_underflow": (8, 1), "enable_inexact_operation": (7, 1),
        "rounding_mode": (0, 2),
    }

    def with_enables(self, flags):
        return FCSR((self.raw & ~(0x1F << 7)) | (flags.raw << 7))


FCSR.ZERO = FCSR(0)
FCSR.DEFAULT = FCSR.ZERO.with_enable_invalid_operation(True).with_flush_denorm_to_zero(True)


# Floating-point values. Rust parses each literal straight to f32/f64; FLit keeps the exact
# decimal value so it can be rounded once, correctly, to whichever width the test uses.

class FLit:
    def __init__(self, neg, mag):
        self.neg = neg
        self.mag = Fraction(mag)

    def __neg__(self):
        return FLit(not self.neg, self.mag)

    def _value(self):
        return -self.mag if self.neg else self.mag

    def __mul__(self, other):
        v = self._value() * other._value()
        return FLit(v < 0 or (v == 0 and self.neg != other.neg), abs(v))

    def __truediv__(self, other):
        v = self._value() / other._value()
        return FLit(v < 0 or (v == 0 and self.neg != other.neg), abs(v))

    def bits(self, width):
        return _round_to_ieee(self.neg, self.mag, width)

    def __repr__(self):
        return f"FLit({'-' if self.neg else ''}{float(self.mag)!r})"


class FBits:
    """A float given by its bit pattern (NaN, infinity, f32::MAX, FConst::*)."""

    def __init__(self, width, bits):
        self.width = width
        self.raw = bits

    def __neg__(self):
        return FBits(self.width, self.raw ^ (1 << (self.width - 1)))

    def __mul__(self, other):
        exp_mask = 0x7F800000 if self.width == 32 else 0x7FF0000000000000
        is_inf = self.raw & ~(1 << (self.width - 1)) == exp_mask
        if is_inf and isinstance(other, FLit) and other.mag > 0:
            return self if not other.neg else -self
        raise TypeError(f"unsupported constant product {self!r} * {other!r}")

    def bits(self, width):
        if width != self.width:
            raise TypeError(f"f{self.width} constant used as f{width}")
        return self.raw

    def __repr__(self):
        return f"FBits{self.width}({self.raw:#x})"


def _round_to_ieee(neg, mag, width):
    exp_bits, frac_bits = (8, 23) if width == 32 else (11, 52)
    bias = (1 << (exp_bits - 1)) - 1
    sign = (1 << (width - 1)) if neg else 0
    if mag == 0:
        return sign
    e = mag.numerator.bit_length() - mag.denominator.bit_length()
    if Fraction(2) ** e > mag:
        e -= 1
    e = max(e, 1 - bias)
    scaled = mag / Fraction(2) ** (e - frac_bits)
    q, r = divmod(scaled.numerator, scaled.denominator)
    twice = 2 * r
    if twice > scaled.denominator or (twice == scaled.denominator and q & 1):
        q += 1
    if q >> (frac_bits + 1):
        q >>= 1
        e += 1
    if e > bias:
        return sign | (((1 << exp_bits) - 1) << frac_bits)
    if q >> frac_bits:
        return sign | ((e + bias) << frac_bits) | (q & ((1 << frac_bits) - 1))
    return sign | q


class _FloatType:
    def __init__(self, width):
        self.width = width
        if width == 32:
            self.INFINITY = FBits(32, 0x7F800000)
            self.NEG_INFINITY = FBits(32, 0xFF800000)
            self.NAN = FBits(32, 0x7FC00000)
            self.MAX = FBits(32, 0x7F7FFFFF)
            self.MIN = FBits(32, 0xFF7FFFFF)
            self.MIN_POSITIVE = FBits(32, 0x00800000)
            self.EPSILON = FBits(32, 0x34000000)
        else:
            self.INFINITY = FBits(64, 0x7FF0000000000000)
            self.NEG_INFINITY = FBits(64, 0xFFF0000000000000)
            self.NAN = FBits(64, 0x7FF8000000000000)
            self.MAX = FBits(64, 0x7FEFFFFFFFFFFFFF)
            self.MIN = FBits(64, 0xFFEFFFFFFFFFFFFF)
            self.MIN_POSITIVE = FBits(64, 0x0010000000000000)
            self.EPSILON = FBits(64, 0x3CB0000000000000)

    def from_bits(self, bits):
        return FBits(self.width, bits)


f32, f64 = _FloatType(32), _FloatType(64)


class _IntType:
    def __init__(self, bits, signed):
        self.MIN = -(1 << (bits - 1)) if signed else 0
        self.MAX = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1


i32, i64, u32, u64 = _IntType(32, True), _IntType(64, True), _IntType(32, False), _IntType(64, False)


class FConst:
    SIGNALLING_NAN_START_32 = FBits(32, 0x7F800001)
    SIGNALLING_NAN_END_32 = FBits(32, 0x7FBFFFFF)
    SIGNALLING_NAN_NEGATIVE_START_32 = FBits(32, 0xFF800001)
    SIGNALLING_NAN_NEGATIVE_END_32 = FBits(32, 0xFFBFFFFF)
    SIGNALLING_NAN_START_64 = FBits(64, 0x7FF0000000000001)
    SIGNALLING_NAN_END_64 = FBits(64, 0x7FF7FFFFFFFFFFFF)
    SIGNALLING_NAN_NEGATIVE_START_64 = FBits(64, 0xFFF0000000000001)
    SIGNALLING_NAN_NEGATIVE_END_64 = FBits(64, 0xFFF7FFFFFFFFFFFF)
    QUIET_NAN_START_32 = FBits(32, 0x7FC00000)
    QUIET_NAN_END_32 = FBits(32, 0x7FFFFFFF)
    QUIET_NAN_NEGATIVE_START_32 = FBits(32, 0xFFC00000)
    QUIET_NAN_NEGATIVE_END_32 = FBits(32, 0xFFFFFFFF)
    QUIET_NAN_START_64 = FBits(64, 0x7FF8000000000000)
    QUIET_NAN_END_64 = FBits(64, 0x7FFFFFFFFFFFFFFF)
    QUIET_NAN_NEGATIVE_START_64 = FBits(64, 0xFFF8000000000000)
    QUIET_NAN_NEGATIVE_END_64 = FBits(64, 0xFFFFFFFFFFFFFFFF)
    SUBNORMAL_MIN_POSITIVE_32 = FBits(32, 0x00000001)
    SUBNORMAL_MAX_POSITIVE_32 = FBits(32, 0x007FFFFF)
    SUBNORMAL_MIN_NEGATIVE_32 = FBits(32, 0x80000001)
    SUBNORMAL_MAX_NEGATIVE_32 = FBits(32, 0x807FFFFF)
    SUBNORMAL_MIN_POSITIVE_64 = FBits(64, 0x0000000000000001)
    SUBNORMAL_MAX_POSITIVE_64 = FBits(64, 0x000FFFFFFFFFFFFF)
    SUBNORMAL_MIN_NEGATIVE_64 = FBits(64, 0x8000000000000001)
    SUBNORMAL_MAX_NEGATIVE_64 = FBits(64, 0x800FFFFFFFFFFFFF)


def float_bits(value, width):
    return value.bits(width)


class FPUFloatInstruction:
    def __init__(self, value):
        assert (value >> 21) & 0x1F == 0
        self.value = value

    def s(self):
        return self.value | (16 << 21)

    def d(self):
        return self.value | (17 << 21)

    def w(self):
        return self.value | (20 << 21)

    def l(self):
        return self.value | (21 << 21)


def _special(op, sa, rd, rs, rt):
    return op | (sa << 6) | (rd << 11) | (rt << 16) | (rs << 21)


def _main(op, rt, rs, imm):
    return (imm & 0xFFFF) | (int(rt) << 16) | (int(rs) << 21) | (int(op) << 26)


def _cop(cop, instruction, rt, rd):
    return (int(rd) << 11) | (int(rt) << 16) | (instruction << 21) | ((16 + cop) << 26)


class Assembler:
    """Port of nemu64-test src/assembler.rs Assembler::make_*."""

    make_main_immediate = staticmethod(_main)

    @staticmethod
    def make_special(op, sa, rd, rs, rt):
        return _special(int(op), sa, rd, rs, rt)

    @staticmethod
    def make_regimm_trap(op, rs, imm):
        return (imm & 0xFFFF) | (int(op) << 16) | (int(rs) << 21) | (1 << 26)

    @staticmethod
    def make_cop1_float_instruction(instruction, fd, fs, ft):
        return FPUFloatInstruction(int(instruction) | (int(fd) << 6) | (int(fs) << 11)
                                   | (int(ft) << 16) | (17 << 26))

    @staticmethod
    def make_cop1_c_cond(condition, fs, ft):
        return Assembler.make_cop1_float_instruction(int(condition), FR.F0, fs, ft)

    @staticmethod
    def make_jal(imm26):
        return imm26 | (3 << 26)

    @staticmethod
    def make_lui(rt, immediate):
        return _main(15, rt, 0, immediate)

    @staticmethod
    def make_lui_with_rs(rt, rs, immediate):
        return _main(15, rt, rs, immediate)

    @staticmethod
    def make_b(offset):
        return _main(4, 0, 0, offset)

    @staticmethod
    def make_nop():
        return 0

    @staticmethod
    def make_move(rd, rs):
        return _special(37, 0, rd, rs, 0)

    @staticmethod
    def make_jr(rs):
        return _special(8, 0, 0, rs, 0)

    @staticmethod
    def make_jr_with_extras(rs, rt):
        return _special(8, 0, 0, rs, rt)

    @staticmethod
    def make_jalr(return_reg, rs):
        return _special(9, 0, return_reg, rs, 0)

    @staticmethod
    def make_cache(op, offset, base):
        return _main(47, int(op), base, offset)

    @staticmethod
    def make_cop0_tlbr():
        return (16 << 26) | (16 << 21) | 1

    @staticmethod
    def make_cop0_tlbwi():
        return (16 << 26) | (16 << 21) | 2

    @staticmethod
    def make_cop0_tlbwr():
        return (16 << 26) | (16 << 21) | 6

    @staticmethod
    def make_cop0_tlbp():
        return (16 << 26) | (16 << 21) | 8


def _add(name, fn):
    setattr(Assembler, name, staticmethod(fn))


# I-type arithmetic: make_x(rt, rs, imm)
for _n, _op in [("addi", 8), ("addiu", 9), ("daddi", 24), ("daddiu", 25), ("slti", 10),
                ("sltiu", 11), ("andi", 12), ("ori", 13), ("xori", 14)]:
    _add(f"make_{_n}", lambda rt, rs, imm, _op=_op: _main(_op, rt, rs, imm))
# Two-register branches: make_x(rt, rs, offset)
for _n, _op in [("beq", 4), ("bne", 5), ("beql", 20), ("bnel", 21)]:
    _add(f"make_{_n}", lambda rt, rs, off, _op=_op: _main(_op, rt, rs, off))
# One-register branches: make_x(rs, offset) and make_x_with_extras(rs, rt, offset)
for _n, _op in [("blez", 6), ("bgtz", 7), ("blezl", 22), ("bgtzl", 23)]:
    _add(f"make_{_n}", lambda rs, off, _op=_op: _main(_op, 0, rs, off))
    _add(f"make_{_n}_with_extras", lambda rs, rt, off, _op=_op: _main(_op, rt, rs, off))
_add("make_bgezal", lambda rs, off: (off & 0xFFFF) | (17 << 16) | (int(rs) << 21) | (1 << 26))
# Loads and stores: make_x(rt, offset, base)
for _n in ["sd", "scd", "sdl", "sdr", "sw", "sc", "swl", "swr", "sh", "sb", "lb", "lbu", "lh",
           "lhu", "lw", "lwl", "lwr", "ldl", "ldr", "ll", "lld", "lwu", "ld"]:
    _add(f"make_{_n}", lambda rt, off, base, _op=mips.OP[_n]: _main(_op, rt, base, off))
for _n in ["lwc1", "ldc1", "swc1", "sdc1"]:
    _add(f"make_{_n}", lambda ft, off, base, _op=mips.OP[_n]: _main(_op, ft, base, off))
# Three-register R-type: make_x(rd, rs, rt)
for _n in ["add", "addu", "sub", "subu", "and", "or", "xor", "nor", "slt", "sltu", "dadd",
           "daddu", "dsub", "dsubu"]:
    _add(f"make_{_n}", lambda rd, rs, rt, _f=mips.FUNCT[_n]: _special(_f, 0, rd, rs, rt))
# Traps: make_x(rs, rt)
for _n in ["tne", "teq", "tge", "tlt", "tgeu", "tltu"]:
    _add(f"make_{_n}", lambda rs, rt, _f=mips.FUNCT[_n]: _special(_f, 0, 0, rs, rt))
# Shifts by constant: make_x(rd, rt, sa) and make_x_with_extras(rd, rt, rs, sa)
for _n in ["sll", "srl", "sra", "dsll", "dsrl", "dsra", "dsll32", "dsrl32", "dsra32"]:
    _add(f"make_{_n}", lambda rd, rt, sa, _f=mips.FUNCT[_n]: _special(_f, sa, rd, 0, rt))
    _add(f"make_{_n}_with_extras",
         lambda rd, rt, rs, sa, _f=mips.FUNCT[_n]: _special(_f, sa, rd, rs, rt))
# Variable shifts: make_x(rd, rt, rs)
for _n in ["sllv", "srlv", "srav", "dsllv", "dsrlv", "dsrav"]:
    _add(f"make_{_n}", lambda rd, rt, rs, _f=mips.FUNCT[_n]: _special(_f, 0, rd, rs, rt))
# Multiply/divide: make_x(rt, rs)
for _n in ["div", "divu", "ddiv", "ddivu", "mult", "multu", "dmult", "dmultu"]:
    _add(f"make_{_n}", lambda rt, rs, _f=mips.FUNCT[_n]: _special(_f, 0, 0, rs, rt))
for _n in ["mflo", "mfhi"]:
    _add(f"make_{_n}", lambda rd, _f=mips.FUNCT[_n]: _special(_f, 0, rd, 0, 0))
    _add(f"make_{_n}_with_extras", lambda rd, rs, rt, _f=mips.FUNCT[_n]: _special(_f, 0, rd, rs, rt))
for _n in ["mtlo", "mthi"]:
    _add(f"make_{_n}", lambda rs, _f=mips.FUNCT[_n]: _special(_f, 0, 0, rs, 0))
    _add(f"make_{_n}_with_extras", lambda rd, rs, rt, _f=mips.FUNCT[_n]: _special(_f, 0, rd, rs, rt))
for _n in ["sync", "break", "syscall"]:
    _add(f"make_{_n}", lambda _f=mips.FUNCT[_n]: _special(_f, 0, 0, 0, 0))
    _add(f"make_{_n}_with_extras", lambda rd, rs, rt, sa, _f=mips.FUNCT[_n]: _special(_f, sa, rd, rs, rt))
# Coprocessor moves: make_x(rt, rd)
for _n, _cn, _rs in [("mfc0", 0, 0), ("dmfc0", 0, 1), ("mtc0", 0, 4), ("dmtc0", 0, 5),
                      ("mfc1", 1, 0), ("dmfc1", 1, 1), ("cfc1", 1, 2), ("dcfc1", 1, 3),
                      ("mtc1", 1, 4), ("dmtc1", 1, 5), ("ctc1", 1, 6), ("dctc1", 1, 7),
                      ("mfc2", 2, 0), ("dmfc2", 2, 1), ("cfc2", 2, 2), ("dcfc2", 2, 3),
                      ("mtc2", 2, 4), ("dmtc2", 2, 5), ("ctc2", 2, 6), ("dctc2", 2, 7),
                      ("mfc3", 3, 0)]:
    _add(f"make_{_n}", lambda rt, rd, _c=_cn, _r=_rs: _cop(_c, _r, rt, rd))
# COP1 float ops
for _n, _i, _ft in [("abs", 5, True), ("cvt_d", 33, True), ("cvt_l", 37, True),
                    ("cvt_s", 32, True), ("cvt_w", 36, True), ("mov", 6, True), ("neg", 7, True),
                    ("sqrt", 4, True), ("round_w", 12, False), ("round_l", 8, False),
                    ("trunc_w", 13, False), ("trunc_l", 9, False), ("floor_w", 15, False),
                    ("floor_l", 11, False), ("ceil_w", 14, False), ("ceil_l", 10, False)]:
    _add(f"make_cop1_{_n}",
         lambda fd, fs, _i=_i: Assembler.make_cop1_float_instruction(_i, fd, fs, FR.F0))
    if _ft:
        _add(f"make_cop1_{_n}_with_ft",
             lambda fd, fs, ft, _i=_i: Assembler.make_cop1_float_instruction(_i, fd, fs, ft))
for _n, _i in [("add", 0), ("sub", 1), ("mul", 2), ("div", 3)]:
    _add(f"make_cop1_{_n}",
         lambda fd, fs, ft, _i=_i: Assembler.make_cop1_float_instruction(_i, fd, fs, ft))


def words_be(words):
    return b"".join(struct.pack(">I", w & 0xFFFFFFFF) for w in words)
