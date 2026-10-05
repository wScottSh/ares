"""Approximates nemu64-test's value_desc (src/tests/mod.rs): " with '<{:x?} of the value>'".

The Rust formats each value with Debug + hex integers. This keeps the same shape (quoted
strings, hex integers, enum names) so failure lines read the same; float and Status fields
print as their bit patterns. Value types the Rust doesn't list print " with unknown arguments".
"""
from ...nemu import ExceptionTimingMode, FBits, FLit, Status

# Tuple signatures nemu64-test's value_desc() knows how to print.
KNOWN = {
    "(&str, u32, u32)", "(&str, u32, u32, u32)", "(&str, u32, Vec<u32>)", "(&str, u32, i32, u32)",
    "(&str, u32, i32, ExceptionTimingMode, u32)", "(&str, u32, i64, u32)",
    "(&str, u32, i64, ExceptionTimingMode, u32)", "(&str, u32, f32, f32, u32)",
    "(&str, u32, f32, f32, u32, u32)", "(&str, u32, f64, f64, u32, u32)",
    "(&str, u32, f64, f64, u32)", "(&str, u64, u64, Status, ExceptionTimingMode, u32, u32)",
    "(&str, u32, f32, f32, ExceptionTimingMode, u32)",
    "(&str, u32, f64, f64, ExceptionTimingMode, u32)", "u32", "bool", "(u32, u32)",
    "(bool, u32, f32)", "()",
}


def _fmt(x, width=None):
    if isinstance(x, str):
        return '"' + x + '"'
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, ExceptionTimingMode):
        return x.name
    if isinstance(x, Status):
        return f"Status({x.raw:#x})"
    if isinstance(x, (FLit, FBits)):
        w = width or (x.width if isinstance(x, FBits) else 32)
        return f"f{w}({x.bits(w):#x})"
    if isinstance(x, int):
        return f"{x & 0xFFFFFFFFFFFFFFFF:x}" if x < 0 else f"{x:x}"
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(_fmt(e) for e in x) + "]"
    return str(x)


def describe(value, sig, full=False):
    """The ROM's description text; full=True also renders types the Rust prints as unknown."""
    if sig == "()":
        return ""
    if sig not in KNOWN and not full:
        return " with unknown arguments"
    width = 64 if "f64" in sig else 32 if "f32" in sig else None
    if isinstance(value, tuple):
        return " with '(" + ", ".join(_fmt(e, width) for e in value) + ")'"
    return f" with '{_fmt(value, width)}'"
