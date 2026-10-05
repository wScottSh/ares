"""VR4300 instruction encoder and a two-pass text assembler for the subset romgen needs.

Field layouts follow the NEC VR4300 User's Manual (U10504EJ), chapter 16 "CPU Instruction
Set Details" and chapter 17 "FPU Instruction Set Details": I-type op|rs|rt|imm16,
J-type op|target26, R-type SPECIAL|rs|rt|rd|sa|funct, COPz op|fmt|rt|rd|0|funct.
"""
import re
import struct

GPR_NAMES = [
    "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
    "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
    "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
    "t8", "t9", "k0", "k1", "gp", "sp", "s8", "ra",
]
GPR = {name: i for i, name in enumerate(GPR_NAMES)}
GPR["fp"] = 30
GPR["r0"] = 0

COP0_REGS = {
    "index": 0, "random": 1, "entrylo0": 2, "entrylo1": 3, "context": 4, "pagemask": 5,
    "wired": 6, "badvaddr": 8, "count": 9, "entryhi": 10, "compare": 11, "status": 12,
    "cause": 13, "epc": 14, "prid": 15, "config": 16, "lladdr": 17, "watchlo": 18,
    "watchhi": 19, "xcontext": 20, "taglo": 28, "taghi": 29, "errorepc": 30,
}

OP = {
    "special": 0, "regimm": 1, "j": 2, "jal": 3, "beq": 4, "bne": 5, "blez": 6, "bgtz": 7,
    "addi": 8, "addiu": 9, "slti": 10, "sltiu": 11, "andi": 12, "ori": 13, "xori": 14, "lui": 15,
    "cop0": 16, "cop1": 17, "cop2": 18, "beql": 20, "bnel": 21, "blezl": 22, "bgtzl": 23,
    "daddi": 24, "daddiu": 25, "ldl": 26, "ldr": 27,
    "lb": 32, "lh": 33, "lwl": 34, "lw": 35, "lbu": 36, "lhu": 37, "lwr": 38, "lwu": 39,
    "sb": 40, "sh": 41, "swl": 42, "sw": 43, "sdl": 44, "sdr": 45, "swr": 46, "cache": 47,
    "ll": 48, "lwc1": 49, "lld": 52, "ldc1": 53, "ld": 55,
    "sc": 56, "swc1": 57, "scd": 60, "sdc1": 61, "sd": 63,
}

FUNCT = {
    "sll": 0, "srl": 2, "sra": 3, "sllv": 4, "srlv": 6, "srav": 7, "jr": 8, "jalr": 9,
    "syscall": 12, "break": 13, "sync": 15, "mfhi": 16, "mthi": 17, "mflo": 18, "mtlo": 19,
    "dsllv": 20, "dsrlv": 22, "dsrav": 23, "mult": 24, "multu": 25, "div": 26, "divu": 27,
    "dmult": 28, "dmultu": 29, "ddiv": 30, "ddivu": 31, "add": 32, "addu": 33, "sub": 34,
    "subu": 35, "and": 36, "or": 37, "xor": 38, "nor": 39, "slt": 42, "sltu": 43,
    "dadd": 44, "daddu": 45, "dsub": 46, "dsubu": 47, "tge": 48, "tgeu": 49, "tlt": 50,
    "tltu": 51, "teq": 52, "tne": 54, "dsll": 56, "dsrl": 58, "dsra": 59, "dsll32": 60,
    "dsrl32": 62, "dsra32": 63,
}

REGIMM = {
    "bltz": 0, "bgez": 1, "bltzl": 2, "bgezl": 3, "tgei": 8, "tgeiu": 9, "tlti": 10,
    "tltiu": 11, "teqi": 12, "tnei": 14, "bltzal": 16, "bgezal": 17, "bltzall": 18, "bgezall": 19,
}

COP_RS = {"mf": 0, "dmf": 1, "cf": 2, "mt": 4, "dmt": 5, "ct": 6, "bc": 8, "co": 16}
COP1_FMT = {"s": 16, "d": 17, "w": 20, "l": 21}
COP1_FUNCT = {
    "add": 0, "sub": 1, "mul": 2, "div": 3, "sqrt": 4, "abs": 5, "mov": 6, "neg": 7,
    "round.l": 8, "trunc.l": 9, "ceil.l": 10, "floor.l": 11, "round.w": 12, "trunc.w": 13,
    "ceil.w": 14, "floor.w": 15, "cvt.s": 32, "cvt.d": 33, "cvt.w": 36, "cvt.l": 37,
}
TLB_FUNCT = {"tlbr": 1, "tlbwi": 2, "tlbwr": 6, "tlbp": 8, "eret": 24}

# emux extension encodings (COP0 CO space). Source: nemu64-test src/emux.rs and
# ares/n64/cpu/emux.cpp.
EMUX_FUNCT = {"xdetect": 0x20, "xlog": 0x25, "xhexdump": 0x27, "xioctl": 0x2C}


def _u(value, bits):
    mask = (1 << bits) - 1
    if not -(1 << (bits - 1)) <= value <= mask:
        raise ValueError(f"{value:#x} does not fit in {bits} bits")
    return value & mask


def i_type(op, rs, rt, imm):
    return (op << 26) | (rs << 21) | (rt << 16) | _u(imm, 16)


def r_type(rs, rt, rd, sa, funct):
    return (OP["special"] << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (_u(sa, 5) << 6) | funct


def j_type(op, target):
    return (op << 26) | ((target >> 2) & 0x3FFFFFF)


def cop_move(cop, rs, rt, rd):
    return ((OP["cop0"] + cop) << 26) | (rs << 21) | (rt << 16) | (rd << 11)


def emux(funct, rd=0, rt=0, code=0):
    return (OP["cop0"] << 26) | (COP_RS["co"] << 21) | (rd << 20) | (rt << 15) | ((code & 0x1FF) << 6) | funct


class AsmError(Exception):
    pass


class Image:
    """A flat memory image assembled from text at a fixed base address.

    Two passes: the first sizes every statement with symbols unresolved, the second encodes.
    Statement sizes never depend on symbol values, so the passes always agree.
    """

    def __init__(self, base):
        self.base = base
        self.symbols = {}
        self.externals = {}
        self._pending = []

    def asm(self, text, **consts):
        self._pending.append((text, consts))
        return self

    def symbol(self, name, value):
        self.externals[name] = value

    def layout(self):
        """Assigns addresses only (pass 1) and returns the symbol table."""
        self._layout()
        return dict(self.symbols)

    def link(self):
        layout = self._layout()
        out = bytearray()
        for addr, body, consts, raw in layout:
            out += b"\0" * (addr - self.base - len(out))
            try:
                out += self._encode(body, addr, consts)
            except Exception as e:
                raise AsmError(f"{raw.strip()!r}: {e}") from e
        out += b"\0" * (self.end - self.base - len(out))
        self.data = bytes(out)
        return self

    def _layout(self):
        self.symbols = dict(self.externals)
        statements = []
        for text, consts in self._pending:
            for lineno, raw in enumerate(text.splitlines(), 1):
                line = _outside_quotes(raw, "#")[0].strip()
                if not line:
                    continue
                while True:
                    m = re.match(r"^([A-Za-z_.$][\w.$]*):\s*(.*)$", line)
                    if not m:
                        break
                    statements.append(("label", m.group(1), consts, raw))
                    line = m.group(2)
                if line:
                    for part in _outside_quotes(line, ";"):
                        if part.strip():
                            statements.append(("stmt", part.strip(), consts, raw))

        addr = self.base
        layout = []
        previous = ""
        for kind, body, consts, raw in statements:
            if kind != "label":
                mnem = body.split(None, 1)[0].lower()
                if mnem in ("li", "la") and _is_control(previous):
                    raise AsmError(f"{raw.strip()!r}: two-instruction pseudo in a delay slot")
                previous = mnem
            if kind == "label":
                if body in self.symbols:
                    raise AsmError(f"duplicate label {body}")
                self.symbols[body] = addr
                continue
            size = self._size(body, addr, consts)
            layout.append((addr, body, consts, raw))
            addr += size
        self.end = addr
        return layout

    def _size(self, body, addr, consts):
        mnem, args = _split(body)
        if mnem == ".align":
            n = self._eval(args[0], consts, 0)
            return (-addr) % n
        if mnem == ".space":
            return self._eval(args[0], consts, 0)
        if mnem == ".word":
            return 4 * len(args)
        if mnem == ".dword":
            return 8 * len(args)
        if mnem == ".half":
            return 2 * len(args)
        if mnem == ".byte":
            return len(args)
        if mnem in (".ascii", ".asciiz"):
            return len(_string(body)) + (mnem == ".asciiz")
        if mnem == ".bytes":
            return len(consts[args[0]])
        if mnem in ("li", "la"):
            return 8
        return 4

    def _eval(self, expr, consts, default=None):
        env = dict(self.symbols)
        env.update(consts)
        try:
            return int(eval(expr, {"__builtins__": {}}, env))
        except NameError:
            if default is None:
                raise
            return default

    def _encode(self, body, addr, consts):
        mnem, args = _split(body)
        ev = lambda e: self._eval(e, consts)
        if mnem == ".align":
            return b"\0" * ((-addr) % ev(args[0]))
        if mnem == ".space":
            return b"\0" * ev(args[0])
        if mnem == ".word":
            return b"".join(struct.pack(">I", ev(a) & 0xFFFFFFFF) for a in args)
        if mnem == ".dword":
            return b"".join(struct.pack(">Q", ev(a) & 0xFFFFFFFFFFFFFFFF) for a in args)
        if mnem == ".half":
            return b"".join(struct.pack(">H", ev(a) & 0xFFFF) for a in args)
        if mnem == ".byte":
            return bytes(ev(a) & 0xFF for a in args)
        if mnem == ".ascii":
            return _string(body)
        if mnem == ".asciiz":
            return _string(body) + b"\0"
        if mnem == ".bytes":
            return bytes(consts[args[0]])
        words = encode(mnem, args, addr, ev)
        return b"".join(struct.pack(">I", w) for w in words)


def _outside_quotes(text, sep):
    """Splits on `sep` outside double-quoted strings."""
    parts, cur, quoted, escaped = [], "", False, False
    for ch in text:
        if quoted:
            cur += ch
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
            cur += ch
        elif ch == sep:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _is_control(mnem):
    return (mnem in ("j", "jal", "jr", "jalr", "b") or mnem in REGIMM and not mnem.startswith("t")
            or mnem.startswith(("beq", "bne", "blez", "bgtz", "bc1")))


def _split(body):
    parts = body.split(None, 1)
    mnem = parts[0].lower()
    if len(parts) == 1:
        return mnem, []
    if mnem in (".ascii", ".asciiz"):
        return mnem, [parts[1]]
    return mnem, [a.strip() for a in _commas(parts[1])]


def _commas(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _string(body):
    m = re.search(r'"((?:[^"\\]|\\.)*)"', body)
    return m.group(1).encode("latin-1").decode("unicode_escape").encode("latin-1")


def reg(name):
    raw = name.strip()
    n = raw.lstrip("$").lower()
    if n.isdigit() and raw.startswith("$"):
        r = int(n)
    elif n in GPR:
        r = GPR[n]
    else:
        raise AsmError(f"bad register {name}")
    if not 0 <= r < 32:
        raise AsmError(f"bad register {name}")
    return r


def freg(name):
    n = name.strip().lstrip("$").lower()
    if not n.startswith("f"):
        raise AsmError(f"bad FPU register {name}")
    return int(n[1:])


def cop0reg(name, ev):
    n = name.strip().lstrip("$").lower()
    if n in COP0_REGS:
        return COP0_REGS[n]
    return ev(n)


def mem(arg, ev):
    m = re.match(r"^(.*)\((.+)\)$", arg.strip())
    if not m:
        raise AsmError(f"bad memory operand {arg}")
    off = m.group(1).strip() or "0"
    return ev(off), reg(m.group(2))


def branch_offset(target, addr):
    delta = target - (addr + 4)
    if delta % 4:
        raise AsmError("unaligned branch target")
    return delta >> 2


def encode(mnem, args, addr, ev):
    """Returns the list of instruction words for one statement."""
    a = args
    if mnem == "nop":
        return [0]
    if mnem == "move":
        return [r_type(reg(a[1]), 0, reg(a[0]), 0, FUNCT["or"])]
    if mnem in ("li", "la"):
        v = ev(a[1]) & 0xFFFFFFFF
        rt = reg(a[0])
        return [i_type(OP["lui"], 0, rt, v >> 16), i_type(OP["ori"], rt, rt, v & 0xFFFF)]
    if mnem == "b":
        return [i_type(OP["beq"], 0, 0, branch_offset(ev(a[0]), addr))]
    if mnem in ("beqz", "bnez", "beqzl", "bnezl"):
        op = {"beqz": "beq", "bnez": "bne", "beqzl": "beql", "bnezl": "bnel"}[mnem]
        return [i_type(OP[op], reg(a[0]), 0, branch_offset(ev(a[1]), addr))]
    if mnem in ("beq", "bne", "beql", "bnel"):
        return [i_type(OP[mnem], reg(a[0]), reg(a[1]), branch_offset(ev(a[2]), addr))]
    if mnem in ("blez", "bgtz", "blezl", "bgtzl"):
        return [i_type(OP[mnem], reg(a[0]), 0, branch_offset(ev(a[1]), addr))]
    if mnem in REGIMM:
        if mnem.startswith("t"):
            return [i_type(OP["regimm"], reg(a[0]), REGIMM[mnem], ev(a[1]))]
        return [i_type(OP["regimm"], reg(a[0]), REGIMM[mnem], branch_offset(ev(a[1]), addr))]
    if mnem in ("j", "jal"):
        target = ev(a[0])
        if (target ^ (addr + 4)) & 0xF0000000:
            raise AsmError("jump target outside the 256 MB segment")
        return [j_type(OP[mnem], target)]
    if mnem == "lui":
        return [i_type(OP["lui"], 0, reg(a[0]), ev(a[1]))]
    if mnem in ("addi", "addiu", "slti", "sltiu", "daddi", "daddiu"):
        return [i_type(OP[mnem], reg(a[1]), reg(a[0]), ev(a[2]))]
    if mnem in ("andi", "ori", "xori"):
        imm = ev(a[2])
        if not 0 <= imm <= 0xFFFF:
            raise AsmError(f"{mnem} immediate {imm:#x} out of range")
        return [i_type(OP[mnem], reg(a[1]), reg(a[0]), imm)]
    if mnem in ("lwc1", "ldc1", "swc1", "sdc1"):
        off, base = mem(a[1], ev)
        return [i_type(OP[mnem], base, freg(a[0]), off)]
    if mnem == "cache":
        off, base = mem(a[1], ev)
        return [i_type(OP["cache"], base, ev(a[0]), off)]
    if mnem in OP and OP[mnem] >= 26:
        off, base = mem(a[1], ev)
        return [i_type(OP[mnem], base, reg(a[0]), off)]
    if mnem in ("sll", "srl", "sra", "dsll", "dsrl", "dsra", "dsll32", "dsrl32", "dsra32"):
        return [r_type(0, reg(a[1]), reg(a[0]), ev(a[2]), FUNCT[mnem])]
    if mnem in ("sllv", "srlv", "srav", "dsllv", "dsrlv", "dsrav"):
        return [r_type(reg(a[2]), reg(a[1]), reg(a[0]), 0, FUNCT[mnem])]
    if mnem in ("mult", "multu", "div", "divu", "dmult", "dmultu", "ddiv", "ddivu",
                "tge", "tgeu", "tlt", "tltu", "teq", "tne"):
        return [r_type(reg(a[0]), reg(a[1]), 0, 0, FUNCT[mnem])]
    if mnem in ("mfhi", "mflo"):
        return [r_type(0, 0, reg(a[0]), 0, FUNCT[mnem])]
    if mnem in ("mthi", "mtlo", "jr"):
        return [r_type(reg(a[0]), 0, 0, 0, FUNCT[mnem])]
    if mnem == "jalr":
        if len(a) == 1:
            return [r_type(reg(a[0]), 0, 31, 0, FUNCT["jalr"])]
        return [r_type(reg(a[1]), 0, reg(a[0]), 0, FUNCT["jalr"])]
    if mnem in ("syscall", "break", "sync"):
        return [r_type(0, 0, 0, 0, FUNCT[mnem])]
    if mnem in FUNCT:
        return [r_type(reg(a[1]), reg(a[2]), reg(a[0]), 0, FUNCT[mnem])]
    if mnem in TLB_FUNCT:
        return [(OP["cop0"] << 26) | (COP_RS["co"] << 21) | TLB_FUNCT[mnem]]
    m = re.match(r"^(d?m[ft]|[ct]f|c[ft])c([012])$", mnem)
    if m:
        kind, cop = m.group(1), int(m.group(2))
        rs = COP_RS[kind]
        rt = reg(a[0])
        if cop == 0:
            rd = cop0reg(a[1], ev)
        elif cop == 1:
            rd = freg(a[1]) if a[1].strip().lstrip("$").lower().startswith("f") else ev(a[1])
        else:
            rd = ev(a[1].strip().lstrip("$"))
        return [cop_move(cop, rs, rt, rd)]
    m = re.match(r"^([a-z]+(?:\.[lwsd])?)\.([sdwl])$", mnem)
    if m and m.group(1) in COP1_FUNCT:
        fd, fs = freg(a[0]), freg(a[1])
        ft = freg(a[2]) if len(a) > 2 else 0
        return [(OP["cop1"] << 26) | (COP1_FMT[m.group(2)] << 21) | (ft << 16) | (fs << 11)
                | (fd << 6) | COP1_FUNCT[m.group(1)]]
    if mnem == "xlog":
        return [emux(EMUX_FUNCT["xlog"], reg(a[0]), reg(a[1]) if len(a) > 1 else 0,
                     ev(a[2]) if len(a) > 2 else 0)]
    if mnem == "xioctl":
        return [emux(EMUX_FUNCT["xioctl"], code=ev(a[0]))]
    if mnem == "xdetect":
        return [emux(EMUX_FUNCT["xdetect"], reg(a[0]), code=ev(a[1]))]
    raise AsmError(f"unknown mnemonic {mnem}")


def assemble_one(text, addr=0x80000000, symbols=None):
    """Encodes a single statement; used by the self-test and by suite code."""
    env = dict(symbols or {})
    mnem, args = _split(text)
    return encode(mnem, args, addr, lambda e: int(eval(e, {"__builtins__": {}}, env)))
