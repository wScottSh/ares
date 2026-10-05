"""nemu64-test's `timing` feature set (Level::Timing), ported.

Test order and values follow src/tests/testlist.rs; each port_* function is the matching
Test::run() translated into runtime steps and checks.
"""
from fractions import Fraction

from ...nemu import (Assembler, GPR, ExceptionTimingMode, FCSR, FCSRFlags, Status,
                     _round_to_ieee)
from ...suite import Check, Step, Test, Value, checkpoint
from ... import runtime as rt
from . import tables
from .describe import describe
from .measure import (cycles_checks, measure_step, VI_DISABLE, VI_WAIT_VSYNC)

Off, JustFire = ExceptionTimingMode.Off, ExceptionTimingMode.JustFire
FCSR_DEFAULT = FCSR.DEFAULT
FCSR_NO_INVALID = FCSR.DEFAULT.with_enable_invalid_operation(False).with_flush_denorm_to_zero(True)
FCSR_ALL_ENABLES = FCSR.DEFAULT.with_enables(FCSRFlags.ALL)


def u64(x):
    return x & 0xFFFFFFFFFFFFFFFF


def assert_cycles(suite, expected, value2, value4, status, mode, body, fcsr=FCSR_DEFAULT, res=0):
    step = measure_step(suite, body, u64(value2), u64(value4), status, mode, fcsr, res)
    return [step], cycles_checks(res, expected, mode)


def register_dependency(suite, expected, value2, value4, i1, i2, fcsr=FCSR_DEFAULT):
    """timing::test_register_dependency: five placements, each must pass in order."""
    bodies = [
        (expected, [i1, i2]),
        (expected + 1, [Assembler.make_beq(GPR.R0, GPR.R0, 4), i1, 0, 0, 0, i2]),
        (expected + 1, [Assembler.make_beql(GPR.R0, GPR.R0, 4), i1, 0, 0, 0, i2]),
        (expected + 1, [Assembler.make_beq(GPR.V1, GPR.R0, 1), i1, i2]),
        (expected + 2, [Assembler.make_addiu(GPR.A2, GPR.T9, 16), Assembler.make_jr(GPR.A2),
                        i1, 0, i2]),
    ]
    steps, checks = [], []
    for k, (cycles, body) in enumerate(bodies):
        s, c = assert_cycles(suite, cycles, value2, value4, Status.DEFAULT, Off, body, fcsr, res=2 * k)
        steps += s
        checks += c
    return steps, checks


def value(desc_value, sig, steps_checks, extra_steps=()):
    steps, checks = steps_checks
    return Value(describe(desc_value, sig), list(steps) + list(extra_steps), checks,
                 describe(desc_value, sig, full=True))


def f_bits(x, width):
    return x.bits(width)


def port_measured(suite, struct, vals):
    out = []
    for v in vals:
        sig = getattr(v, "sig", None)
        if struct == "PreciseMeasureJustNOPs":
            out.append(value(v, "u32", assert_cycles(
                suite, v, 0x12345678_ABCDEF, 0, Status.DEFAULT, Off, [0] * v)))
        elif struct == "HiLoInterlockTiming":
            _name, op, nops, expected = v
            out.append(value(v, sig, assert_cycles(
                suite, expected, 0x1234_5678_9ABC_DEF0, 0x0000_0000_7654_3210, Status.DEFAULT, Off,
                [op] + [0] * nops + [Assembler.make_mflo(GPR.A2)])))
        elif struct == "SingleInstructionCPUTiming":
            _name, expected, instruction = v
            out.append(value(v, sig, assert_cycles(
                suite, expected, 0, 0, Status.DEFAULT, Off, [instruction]),
                extra_steps=[Step("step_clear_tlb", [], 0)]))
        elif struct == "Exceptions":
            _name, value2, value4, status, mode, expected, instruction = v
            out.append(value(v, sig, assert_cycles(
                suite, expected, value2, value4, status, mode, [instruction])))
        elif struct == "CachedLoadsAndStoreTiming":
            _name, expected, instruction = v
            out.append(value(v, "(&str, u32, u32)", assert_cycles(
                suite, expected, 0, 0, Status.DEFAULT, Off, [instruction])))
        elif struct in ("COP1Instructions32", "COP1Instructions64"):
            out.append(port_cop1_instruction(suite, struct, v))
        elif struct == "UncachedWriteBufferTest":
            _name, n, instruction = v
            out.append(value(v, "(&str, u32, u32)", assert_cycles(
                suite, n, 0, 0, Status.DEFAULT, Off, [instruction] * n)))
        elif struct == "CPURegisterDependency":
            if sig == "(&str, u32, u32, u32)":
                _name, expected, i0, i1 = v
                out.append(value(v, sig, register_dependency(suite, expected, 0x123, 0x456, i0, i1)))
            else:
                _name, expected, instructions = v
                out.append(value(v, sig or "(&str, u32, Vec<u32>)", assert_cycles(
                    suite, expected, 0x123, 0x456, Status.DEFAULT, Off, instructions)))
        elif struct == "COP1RegisterDependency":
            _name, expected, a, b, i1, i2 = v
            width = 64 if "f64" in sig else 32
            out.append(value(v, sig, register_dependency(
                suite, expected, f_bits(a, width), f_bits(b, width), i1, i2, FCSR_NO_INVALID)))
        elif struct == "LikelyBranchCycleCount":
            _name, i1, i2, i3 = v
            out.append(value(v, "(&str, u32, u32, u32)", assert_cycles(
                suite, 4, 0x123, 0x456, Status.DEFAULT, Off, [i1, i2, 0, i3])))
        else:
            raise KeyError(struct)
    return out


def port_cop1_instruction(suite, struct, v):
    sig = v.sig
    fields = sig.strip("()").split(", ")
    has_mode = "ExceptionTimingMode" in fields
    expected = v[1]
    mode = v[fields.index("ExceptionTimingMode")] if has_mode else Off
    instruction = v[-1]
    if "f32" in fields or "f64" in fields:
        width = 32 if "f32" in fields else 64
        value2, value4 = f_bits(v[2], width), f_bits(v[3], width)
    else:
        value2, value4 = u64(v[2]), 0
    fcsr = FCSR_ALL_ENABLES if has_mode else FCSR_NO_INVALID
    return value(v, sig, assert_cycles(suite, expected, value2, value4, Status.DEFAULT, mode,
                                       [instruction], fcsr))


def eq(res, expected, msg):
    return Check(rt.CHK_EQ_HEX, res, expected, msg=msg)


def port_repeated_mfc0(suite):
    return [Value("", [Step("step_repeated_mfc0", [], 0)],
                  [eq(90, 0, "Expected iterating 0s and 1s (a = 16*row + column + 1 of the first mismatch)")])]


def port_half_cycle(suite):
    steps = []
    for count_value in [0, 100, 0x1234, 0x8000000, 0xFFFFFFFC, 0xFFFFFFFF]:
        steps += [Step("step_half_cycle", [count_value], 0), checkpoint([
            Check(rt.CHK_EQ_REL, 1, 0, 1, msg="2nd - 1st readback"),
            Check(rt.CHK_EQ_REL, 2, 1, 0, msg="3rd - 2nd readback"),
            Check(rt.CHK_EQ_REL, 3, 2, 1, msg="4th - 3rd readback"),
        ])]
    return [Value("", steps, [])]


def port_cache_size(suite):
    sizes = [(2048, True, "2kb should fit within data cache"),
             (4096, True, "4kb should fit within data cache"),
             (8192, True, "8kb should fit within data cache"),
             (16384, False, "16kb should not fit within data cache")]
    steps = [Step("step_cache_size", [size], k) for k, (size, _, _) in enumerate(sizes)]
    checks = [eq(k, 1 if fits else 0, msg) for k, (_, fits, msg) in enumerate(sizes)]
    return [Value("", steps, checks)]


def f32_of(x):
    """Rounds an exact rational to the nearest f32 and returns it as a Fraction."""
    bits = _round_to_ieee(x < 0, abs(Fraction(x)), 32)
    sign = -1 if bits >> 31 else 1
    exp = (bits >> 23) & 0xFF
    frac = bits & 0x7FFFFF
    if exp == 0:
        return sign * Fraction(frac, 1 << 149)
    return sign * Fraction(0x800000 | frac, 1 << 23) * Fraction(2) ** (exp - 127)


def average_sum_bounds(expected, epsilon, iterations):
    """The integer sums whose f32 average (sum as f32 / iterations as f32) satisfies the Rust
    soft_assert_eq_with_epsilon(epsilon, average, expected) in f32 arithmetic."""
    lo_bound = f32_of(f32_of(Fraction(expected)) - f32_of(Fraction(epsilon)))
    hi_bound = f32_of(f32_of(Fraction(expected)) + f32_of(Fraction(epsilon)))
    n = f32_of(Fraction(iterations))
    window = range(int((lo_bound - 1) * iterations), int((hi_bound + 1) * iterations) + 1)
    ok = [s for s in window if lo_bound <= f32_of(f32_of(Fraction(s)) / n) <= hi_bound]
    assert ok == list(range(ok[0], ok[-1] + 1))
    return ok[0], ok[-1]


def averaged(suite, rng, median, average, epsilon, pre, execute, vi_flags):
    step = measure_step(suite, execute, 0, 0, Status.DEFAULT, Off, FCSR_DEFAULT, 0,
                        preconditions=pre, repeat=1000, vi_flags=vi_flags)
    lo, hi = average_sum_bounds(average, epsilon, 1000)
    checks = [
        Check(rt.CHK_RANGE, 0, rng[0], rng[1], msg="Cycle count (min and max): min"),
        Check(rt.CHK_RANGE, 1, rng[0], rng[1], msg="Cycle count (min and max): max"),
        Check(rt.CHK_RANGE, 2, median - 1, median + 1, msg="Median cycle count"),
        Check(rt.CHK_RANGE, 3, lo, hi, msg=f"Average cycle count (sum of 1000; expected {average} +/- {epsilon})"),
    ]
    return [step], checks


def lui_ori(base):
    return [Assembler.make_lui(GPR.T2, (base >> 16) & 0xFFFF),
            Assembler.make_ori(GPR.T2, GPR.T2, base & 0xFFFF)]


FRONTBUFFER_BANK = rt.FB0 & 0x00700000
MEMORY_SIZE = 8 * 1024 * 1024


def port_load_miss_vi_enabled(suite):
    out = []
    for same_bank in (True, False):
        bank = FRONTBUFFER_BANK if same_bank else (FRONTBUFFER_BANK + 0x100000) & (MEMORY_SIZE - 1)
        base = 0x80000000 | bank
        pre = lui_ori(base) + [Assembler.make_lw(GPR.R0, 8 * 1024, GPR.T2)]
        out.append(value(same_bank, "bool", averaged(
            suite, (38, 103), 42, 43.25, 1.0, pre, [Assembler.make_lw(GPR.R0, 0, GPR.T2)],
            VI_WAIT_VSYNC)))
    return out


def port_load_miss_vi_disabled(suite):
    out = []
    for mb in range(8):
        base = 0x80000000 + mb * 0x100000
        pre = lui_ori(base) + [Assembler.make_lw(GPR.R0, 8 * 1024, GPR.T2)]
        out.append(value(base, "u32", averaged(
            suite, (41, 103), 41, 42.5, 0.5, pre, [Assembler.make_lw(GPR.R0, 0, GPR.T2)],
            VI_DISABLE)))
    return out


def port_uncached_vi_enabled(suite):
    out = []
    for same_bank, median, average in ((True, 36, "36.3"), (False, 32, "32.5")):
        bank = FRONTBUFFER_BANK if same_bank else (FRONTBUFFER_BANK + 0x100000) & (MEMORY_SIZE - 1)
        base = 0xA0000000 | bank
        out.append(value((same_bank, median, f"{average}f32"), "(bool, u32, f32)", averaged(
            suite, (32, 93), median, Fraction(average), 4.0, lui_ori(base),
            [Assembler.make_lw(GPR.R0, 0, GPR.T2)], VI_WAIT_VSYNC)))
    return out


def port_uncached_vi_disabled(suite):
    out = []
    for mb in list(range(8)) + [7]:
        base = 0xA0000000 + mb * 0x100000
        out.append(value(base, "u32", averaged(
            suite, (32, 93), 32, Fraction("32.54"), 1.0, lui_ori(base),
            [Assembler.make_lw(GPR.R0, 0, GPR.T2)], VI_DISABLE)))
    return out


def simulate_random(cycles, wired):
    random = 31
    for _ in range(cycles):
        random = 31 if random == wired else (random - 1) & 63
    return random


def port_random_decrement(suite):
    checks = []
    for wired in range(64):
        for k, n in enumerate((1, 16, 31, 100)):
            checks.append(eq(4 * wired + k, simulate_random(n, wired),
                             f"Random, {n} instruction{'s' if n > 1 else ''} after setting Wired = {wired}"))
    return [Value("", [Step("step_random_decrement", [], 0)], checks)]


def port_random_masking(suite):
    return [Value("", [Step("step_random_masking", [], 0)], [eq(0, 27,
            "Random was written as 0xFFFFFFFF, Wired written as 32, expecting Random write to be ignored")])]


def port_count_overflow(suite):
    return [Value("", [Step("step_count_overflow", [], 0)], [
        eq(0, 0, "MFC0 COUNT after DMTC0 COUNT <- 0x00000000_FFFFFFFD and wait until overflow (upper 32 bits)"),
        Check(rt.CHK_RANGE, 1, 0, 0x200, msg="MFC0 COUNT after DMTC0 COUNT <- 0x00000000_FFFFFFFD and wait until overflow"),
        eq(2, 0, "DMFC0 COUNT after DMTC0 COUNT <- 0x00000000_FFFFFFFD and wait until overflow (upper 32 bits)"),
        Check(rt.CHK_RANGE, 3, 0, 0x200, msg="DMFC0 COUNT after DMTC0 COUNT <- 0x00000000_FFFFFFFD and wait until overflow"),
    ])]


def preset_cop2_steps(res):
    """cop0::preset_cause_to_copindex2; a failure returns before the test body runs."""
    return [Step("step_preset_cop2", [], res),
            checkpoint([Check(rt.CHK_EQ_HEX, res, 1, msg="Failed to preset Cause.copindex to 2")])]


def port_compare_signalling2(suite):
    nop = 0
    set_compare = Assembler.make_mtc0(GPR.A2, 11)
    branch = Assembler.make_b(1)
    ops = {0: (set_compare, nop, nop), 1: (set_compare, branch, nop), 2: (branch, set_compare, nop)}
    out = []
    for offset, mode in ((2000, 0), (500, 0), (100, 0), (50, 0), (4, 0), (4, 1), (4, 2)):
        step = Step("step_compare_signalling", [offset, *ops[mode]], 0)
        checks = [Check(rt.CHK_GE_REL, 2, 1, msg="COUNT must be >= the target compare value"),
                  eq(0, (offset - 2) // 3, "Loop iterations")]
        out.append(Value(describe((offset, mode), "(u32, u32)"), preset_cop2_steps(10) + [step],
                         checks,
                         describe((offset, mode), "(u32, u32)")))
    return out


def port_rsp_clock_vs_cpu(suite):
    expected = 100000 * 4 // 3
    return [Value("", [Step("step_dp_clock_vs_cpu", [], 0)], [Check(
        rt.CHK_RANGE, 0, expected - 20, expected + 20,
        msg="Expected RDP cycles that pass during 100000 cpu cycles")])]


def port_rsp_clock_write(suite):
    return [Value("", [Step("step_dp_clock_write", [], 0)], [Check(
        rt.CHK_LE, 0, 100, msg="RDP Clock should be write-only")])]


def port_rsp_clock_masked(suite):
    return [Value("", [Step("step_dp_clock_masked", [], 0)], [
        Check(rt.CHK_NE_REL, 0, 1, msg="RDP clock is not advancing. Returning early, but this is a fail"),
        Check(rt.CHK_RANGE, 2, 0, 0xFFFFFF, msg="Clock is just 24 bit"),
        Check(rt.CHK_RANGE, 3, 0, 0xFFFFFF, msg="Clock is just 24 bit"),
    ])]


def port_rsp_sll(suite):
    return [Value("", [Step("step_rsp_sll", [], 0)], [eq(0, 1, "Expected cycle count")])]


def build(suite):
    tables._FNADDR.update(instant_return_function=suite.symbols["instant_return_function"],
                          one_nop_then_return_function=suite.symbols["one_nop_then_return_function"])
    translated = {struct: (name, fn) for struct, name, _level, fn in tables.TESTS}

    def measured(struct):
        name, fn = translated[struct]
        return Test(name, port_measured(suite, struct, fn()))

    # src/tests/testlist.rs order, Level::Timing entries only
    suite.tests += [
        Test("Random (decrement)", port_random_decrement(suite)),
        Test("Random (masking)", port_random_masking(suite)),
        Test("Count (overflow)", port_count_overflow(suite)),
        Test("Compare (signalling 2)", port_compare_signalling2(suite)),
        Test(translated["RepeatedMFC0Count"][0], port_repeated_mfc0(suite)),
        Test(translated["HalfCycleExactCalibration"][0], port_half_cycle(suite)),
    ]
    for struct in ["PreciseMeasureJustNOPs", "SingleInstructionCPUTiming", "HiLoInterlockTiming",
                   "Exceptions", "CachedLoadsAndStoreTiming", "COP1Instructions32",
                   "COP1Instructions64", "UncachedWriteBufferTest", "CPURegisterDependency",
                   "COP1RegisterDependency", "LikelyBranchCycleCount"]:
        suite.tests.append(measured(struct))
    suite.tests += [
        Test("Timing: Data cache Size", port_cache_size(suite)),
        Test("Timing: Load Miss (with VI enabled)", port_load_miss_vi_enabled(suite)),
        Test("Timing: Load Miss (with VI disabled)", port_load_miss_vi_disabled(suite)),
        Test("Timing: Load from uncached (with VI enabled)", port_uncached_vi_enabled(suite)),
        Test("Timing: Load from uncached (with VI disabled)", port_uncached_vi_disabled(suite)),
        Test("RSP Timing: Clock CPU vs RDP", port_rsp_clock_vs_cpu(suite)),
        Test("RSP Timing: Clock must be readonly", port_rsp_clock_write(suite)),
        Test("RSP Timing: Clock is just 24 bit", port_rsp_clock_masked(suite)),
        Test("RSP Timing: SLL", port_rsp_sll(suite)),
    ]
