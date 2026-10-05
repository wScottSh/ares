"""Translates nemu64-test's Rust test-value tables into Python modules.

Reads a nemu64-test checkout (thelemmy/nemu64-test, pinned commit below), finds every
`impl Test for X` in the given source files, and rewrites each `values()` body into Python
that builds the same list of values through romgen.nemu's port of the Rust API. Only the
data tables are translated; each test's run() logic is ported by hand in suites/nemu64.
The source is read as text and never compiled or run.

usage: python -m romgen.import_nemu64 NEMU64_TEST_DIR
Writes romgen/suites/nemu64/tables.py.
"""
import os
import re
import subprocess
import sys

PINNED_COMMIT = "9a8b9f7"
SOURCES = ["src/tests/timing/mod.rs"]

TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>0x[0-9A-Fa-f_]+(?:u8|u16|u32|u64|usize|i8|i16|i32|i64|isize)?
               |\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][-+]?\d+)?(?:u8|u16|u32|u64|usize|i8|i16|i32|i64|isize|f32|f64)?)
  | (?P<path>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*!?)
  | (?P<punct>[()\[\]{},;.&=:<>*/+-])
""", re.X | re.S)

PATH_MAP = {
    "Box::new": "_box",
    "Vec::new": "list",
    "crate::tests::boxed_values": "list",
    "true": "True",
    "false": "False",
}


def translate_expr(src):
    """Rewrites one Rust expression (a table literal or builder call) into Python source."""
    src = re.sub(r"(\w+) as extern \"C\" fn\(\) as u32", r'_fnaddr("\1")', src)
    src = src.replace("u32::MAX as i32", "-1i32")
    src = src.replace("i64::MAX as f64", "9223372036854775807.0f64")
    src = src.replace("f64::INFINITY as f64", "f64::INFINITY")
    out = []
    pos = 0
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise SyntaxError(f"cannot tokenize near {src[pos:pos + 40]!r}")
        pos = m.end()
        kind, text = m.lastgroup, m.group()
        if kind in ("ws", "comment"):
            out.append(" ")
        elif kind == "string":
            out.append(text)
        elif kind == "number":
            out.append(_number(text))
        elif kind == "path":
            if text == "vec!":
                continue
            if text == "as":
                raise SyntaxError(f"cast in table: {src[max(0, pos - 60):pos + 20]!r}")
            out.append(PATH_MAP.get(text, text.replace("::", ".")))
        elif text == "&":
            continue
        else:
            out.append(text)
    return "".join(out)


def _number(text):
    text = text.replace("_", "")
    if text.startswith("0x"):
        return str(int(re.sub(r"(u|i)\w+$", "", text), 16))
    m = re.match(r"^([\d.eE+-]+?)(f32|f64|u8|u16|u32|u64|usize|i8|i16|i32|i64|isize)?$", text)
    digits, suffix = m.group(1), m.group(2)
    if suffix in ("f32", "f64") or "." in digits or "e" in digits.lower():
        return f'_flit("{digits}")'
    return str(int(digits))


def split_statements(body):
    """Splits a Rust block body on top-level semicolons."""
    depth, cur, out = 0, "", []
    i = 0
    while i < len(body):
        m = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*').match(body, i)
        if m:
            cur += m.group()
            i = m.end()
            continue
        ch = body[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == ";" and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def strip_comments(s):
    return re.sub(r'("(?:[^"\\]|\\.)*")|//[^\n]*', lambda m: m.group(1) or "", s).strip()


def translate_values(body):
    lines = []
    statements = split_statements(body)
    for i, stmt in enumerate(statements):
        stmt = strip_comments(stmt)
        last = i == len(statements) - 1
        if m := re.match(r"^const (\w+): (.+?) = (.*)$", stmt, re.S):
            name, rust_type, expr = m.groups()
            rust_type = " ".join(rust_type.split())
            if rust_type.startswith("&["):
                sig = rust_type[2:-1]
                lines.append(f"{name} = _typed({sig!r}, {translate_expr(expr)})")
            else:
                lines.append(f"{name} = {translate_expr(expr)}")
        elif m := re.match(r"^let mut (\w+) = (.*)$", stmt, re.S):
            lines.append(f"{m.group(1)} = {translate_expr(m.group(2))}")
        elif m := re.match(r"^(\w+)\.push\((.*)\)$", stmt, re.S):
            lines.append(f"{m.group(1)}.append({translate_expr(m.group(2))})")
        elif m := re.match(r"^(\w+)\.extend\((.*)\)$", stmt, re.S):
            lines.append(f"{m.group(1)}.extend({translate_expr(m.group(2))})")
        elif last:
            lines.append(f"return {translate_expr(stmt)}")
        else:
            raise SyntaxError(f"unhandled statement: {stmt[:80]!r}")
    return lines


def find_block(src, start):
    """Returns the index just past the brace block that opens at or after `start`."""
    i = src.index("{", start)
    depth = 0
    pattern = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*|[{}]')
    for m in pattern.finditer(src, i):
        t = m.group()
        if t == "{":
            depth += 1
        elif t == "}":
            depth -= 1
            if depth == 0:
                return i, m.end()
    raise SyntaxError("unbalanced braces")


def extract_tests(src):
    tests = []
    for m in re.finditer(r"impl Test for (\w+) \{", src):
        struct = m.group(1)
        _, end = find_block(src, m.start())
        impl = src[m.start():end]
        name = re.search(r'fn name\(&self\) -> &str \{\s*"((?:[^"\\]|\\.)*)"', impl).group(1)
        level = re.search(r"fn level\(&self\) -> Level \{\s*Level::(\w+)", impl).group(1)
        vm = re.search(r"fn values\(&self\) -> Vec<Box<dyn Any>> \{", impl)
        open_i, close_i = find_block(impl, vm.start())
        body = impl[open_i + 1:close_i - 1]
        tests.append((struct, name, level, body))
    return tests


def main():
    root = sys.argv[1]
    commit = subprocess.run(["git", "-C", root, "rev-parse", "--short=7", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    if commit != PINNED_COMMIT:
        sys.exit(f"{root} is at {commit}, expected {PINNED_COMMIT}")
    out = [
        f'"""Test-value tables translated from nemu64-test @ {PINNED_COMMIT} ({", ".join(SOURCES)}).',
        "",
        "Generated by romgen/import_nemu64.py; do not edit. nemu64-test is MIT licensed",
        '(suites/nemu64/LICENSE.nemu64-test)."""',
        "# fmt: off",
        "from ...nemu import *  # noqa: F401,F403",
        "from ...nemu import FLit",
        "from fractions import Fraction",
        "",
        "",
        "def _flit(s):",
        "    return FLit(False, Fraction(s))",
        "",
        "",
        "def _box(x):",
        "    return x",
        "",
        "",
        "class Typed(tuple):",
        "    sig = None",
        "",
        "",
        "def _typed(sig, rows):",
        "    out = []",
        "    for row in rows:",
        "        t = Typed(row)",
        "        t.sig = sig",
        "        out.append(t)",
        "    return out",
        "",
        "",
        "_FNADDR = {}",
        "",
        "",
        "def _fnaddr(name):",
        "    return _FNADDR[name]",
        "",
        "",
        "TESTS = []",
    ]
    for source in SOURCES:
        src = open(os.path.join(root, source), encoding="utf-8").read()
        for struct, name, level, body in extract_tests(src):
            out += ["", "", f"def values_{struct}():"]
            out += ["    " + line for line in translate_values(body)]
            out.append(f"TESTS.append(({struct!r}, {name!r}, {level!r}, values_{struct}))")
    target = os.path.join(os.path.dirname(__file__), "suites", "nemu64", "tables.py")
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
