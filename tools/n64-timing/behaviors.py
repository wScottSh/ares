#!/usr/bin/env python3
"""Generates the N64 timing constants and spec from ares/n64/timing/behaviors.tsv.

usage: behaviors.py                 write ares/n64/timing/behaviors.hpp and docs/spec/n64-timing.md
       behaviors.py --check         fail unless the table, tools/n64-timing/checks.tsv, both
                                    generated files and the literal lint all agree
       behaviors.py --fix-lines     rewrite each legacy row's file:line to its current code site
       behaviors.py --results RUNNER=PATH... [--out FILE]
                                    per-behavior check results from harness output
       behaviors.py --self-test     prove each --check failure fires and names its fix

behaviors.tsv columns: id, value, unit, basis, reference, verify, note. Every row
names a reference and at least one check. A legacy row is a cost today's core
still charges: its reference is the code site, the literal lint pins the literal
to it, and its note names the plan unit that replaces it. A model-choice row has
no published value; its reference states the reason for the choice.

checks.tsv columns: id, runner, target, selector, expect, source. A row whose id
ends in `:*` is a suite row: every id under that prefix that the suite's expected
file defines (key column = the row's selector) resolves without a row of its own,
and every explicit row whose expect is `suite` must find its target there once
the file exists.
"""
import argparse
import importlib.util
import re
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

TABLE = "ares/n64/timing/behaviors.tsv"
CHECKS = "tools/n64-timing/checks.tsv"
HEADER = "ares/n64/timing/behaviors.hpp"
SPEC = "docs/spec/n64-timing.md"
LINT = "tools/n64-timing/lint-literals.py"
COLUMNS = ["id", "value", "unit", "basis", "reference", "verify", "note"]
CHECK_COLUMNS = ["id", "runner", "target", "selector", "expect", "source"]

BASES = {
    "measured": ("Measured", "a hardware measurement: a test ROM result or a console capture"),
    "vendor": ("Vendor", "Nintendo, NEC or SGI documentation, or a patent"),
    "datasheet": ("Datasheet", "a component datasheet"),
    "wiki": ("Wiki", "a community reference: n64brew, or a test suite author's notes"),
    "rtl": ("Rtl", "a hardware description (MiSTer RTL)"),
    "derived": ("Derived", "computed from other cited values"),
    "fit": ("Fit", "fitted to measured data; rounded to the nearest 750 MHz unit"),
    "model-choice": ("ModelChoice", "no published value; the reference states why the model chose this one"),
    "legacy": ("Legacy", "a constant today's core charges; the reference is its code site and the note names the unit that replaces it"),
}
#750 MHz units per unit (timing/clock.hpp in the design sketch).
TIME_UNITS = {
    "units": 1, "tc": 3, "tick": 4, "pclk": 8, "rclk": 12, "cop0count": 16,
    "us": 750, "ms": 750_000, "s": 750_000_000, "vclk": Fraction(5500, 357),
}
NUMBER_UNITS = {"Hz", "B", "entries", "dwords", "px", "lines", "instr", "rank", "bit",
                "B/rclk", "px/rclk", "tick/pclk", "tick/rclk", "tick/ms", "tick/s"}
FLAG_UNITS = {"flag"}
TEXT_UNITS = {"order", "map", "rule", "event"}
RUNNERS = {"nemu64", "bench", "thar0", "snapper", "rdpstat", "noise", "pidma", "hydra",
           "mm", "det", "stepcap", "unit", "gen", "pending"}
BARE_RUNNERS = {"det", "stepcap", "gen"}
EXPECT = re.compile(r"^(self|suite|report|equal|pass|gate|file:\S+|-?[\d.]+)$")
LEGACY_NOTE = re.compile(r"^(replaced by T(?:\d+[a-d]?|-L)|no plan unit): \S")
ID = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9-]+)+$")
REFERENCE_SITE = re.compile(r"^(ares/n64/\S+):(\d+)$")
BEHAVIOR_USE = re.compile(r"\bBehavior::(\w+)")


def lint_module():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("lint_literals", Path(__file__).resolve().parent / "lint-literals.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_tsv(root, rel, columns, errors):
    lines = (Path(root) / rel).read_text(encoding="utf-8").split("\n")
    if lines[0].split("\t") != columns:
        errors.append(f"{rel}:1: header must be `{' '.join(columns)}` (tab-separated)")
        return []
    rows = []
    for number, line in enumerate(lines[1:], 2):
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) == len(columns) - 1:
            fields.append("")
        if len(fields) != len(columns):
            errors.append(f"{rel}:{number}: {len(fields)} fields; expected {len(columns)} tab-separated columns")
            continue
        row = dict(zip(columns, (f.strip() for f in fields)))
        row["line"] = number
        rows.append(row)
    return rows


def parse_number(text):
    if re.fullmatch(r"-?\d+/\d+", text):
        a, b = text.split("/")
        return Fraction(int(a), int(b))
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return Fraction(text)
    return None


def constant_name(row_id):
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[.-]", row_id))


def constant(row):
    """Returns (C++ type, C++ value, comment, rounding note) for a row that has a constant, else None."""
    unit, basis, text = row["unit"], row["basis"], row["value"]
    if basis == "legacy" or unit in TEXT_UNITS:
        return None
    value = parse_number(text)
    if unit in FLAG_UNITS:
        return "bool", "true" if value else "false", f"{text} {unit}", ""
    if unit in TIME_UNITS:
        units = value * TIME_UNITS[unit]
        comment = f"{text} {unit}"
        if units.denominator == 1:
            return "s64", str(units.numerator), comment, ""
        if "/" in text:
            return "Ratio", f"{{{units.numerator}, {units.denominator}}}", comment, ""
        rounded = (units.numerator * 2 + units.denominator) // (units.denominator * 2)
        return "s64", str(rounded), comment, f"{rounded} units, rounded from {float(units):g}"
    if value.denominator == 1:
        return "s64", str(value.numerator), f"{text} {unit}", ""
    return "Ratio", f"{{{value.numerator}, {value.denominator}}}", f"{text} {unit}", ""


def load_checks(root, errors):
    rows = read_tsv(root, CHECKS, CHECK_COLUMNS, errors)
    explicit, suites = {}, {}
    for row in rows:
        where = f"{CHECKS}:{row['line']}"
        cid, runner = row["id"], row["runner"]
        if cid in explicit or cid in suites:
            errors.append(f"{where}: check `{cid}` is defined twice")
        if runner not in RUNNERS:
            errors.append(f"{where}: runner `{runner}` is not one of {sorted(RUNNERS)}")
        elif runner in BARE_RUNNERS and cid != runner:
            errors.append(f"{where}: a {runner} check has the id `{runner}`")
        elif runner not in BARE_RUNNERS and not cid.startswith(runner + ":"):
            errors.append(f"{where}: check `{cid}` must start with `{runner}:`")
        for column in ("target", "selector", "expect", "source"):
            if not row[column]:
                errors.append(f"{where}: empty {column}; write `-` when it does not apply")
        if not EXPECT.match(row["expect"]):
            errors.append(f"{where}: expect `{row['expect']}` is not self, suite, report, equal, pass, gate, file:PATH or a number")
        if cid.endswith(":*"):
            if not row["expect"].startswith("file:"):
                errors.append(f"{where}: suite row `{cid}` needs expect file:<expected.tsv path>")
            suites[cid[:-2]] = row
        else:
            explicit[cid] = row
        if runner == "pending" and row["expect"] != "gate":
            errors.append(f"{where}: a pending check is a gate; its expect is `gate`")
    suite_files = {}
    for prefix, row in suites.items():
        path = Path(root) / row["expect"][5:]
        if not path.exists():
            continue
        lines = [l.split("\t") for l in path.read_text(encoding="utf-8").split("\n") if l]
        header, body = lines[0], [dict(zip(lines[0], l)) for l in lines[1:]]
        if row["selector"] not in header:
            errors.append(f"{CHECKS}:{row['line']}: suite file {row['expect'][5:]} has no key column `{row['selector']}` "
                          f"(columns: {' '.join(header)}). Set the suite row's selector to its key column.")
            continue
        suite_files[prefix] = (row["selector"], header, body)
    for cid, row in explicit.items():
        if row["expect"] != "suite":
            continue
        prefix = cid.split(":")[0]
        if prefix not in suites:
            errors.append(f"{CHECKS}:{row['line']}: `{cid}` takes its value from a suite, but there is no `{prefix}:*` row")
        elif prefix in suite_files:
            key, header, body = suite_files[prefix]
            wanted = dict(p.split("=", 1) for p in row["selector"].split() if "=" in p)
            unknown = [c for c in wanted if c not in header]
            match = [b for b in body if b.get(key) == row["target"] and all(b.get(c) == v for c, v in wanted.items())]
            if unknown or not match:
                errors.append(f"{CHECKS}:{row['line']}: `{cid}` selects {key}={row['target']} {row['selector']} "
                              f"but {suites[prefix]['expect'][5:]} has no such row. Fix the target and selector, "
                              f"or add the measurement to the suite.")
    return rows, explicit, suites, suite_files


def check_defined(cid, explicit, suite_files):
    if cid in explicit:
        return True
    prefix, _, rest = cid.partition(":")
    if prefix in suite_files:
        key, _, body = suite_files[prefix]
        return any(b.get(key) == rest for b in body)
    return False


def behavior_uses(root):
    uses = []
    for path in sorted((Path(root) / "ares/n64").rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.suffix not in (".cpp", ".hpp") or rel == HEADER:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
            for name in BEHAVIOR_USE.findall(line):
                uses.append((name, f"{rel}:{number}"))
    return uses


def validate(root):
    """Returns (errors, rows, checks, sites)."""
    errors = []
    rows = read_tsv(root, TABLE, COLUMNS, errors)
    checks, explicit, _, suite_files = load_checks(root, errors)
    lint_errors, sites = lint_module().lint(root)
    errors += lint_errors
    seen = {}
    for row in rows:
        where = f"{TABLE}:{row['line']}"
        rid = row["id"]
        if not ID.match(rid):
            errors.append(f"{where}: id `{rid}` must be lowercase dotted words, like ri.read-hit")
        if rid in seen:
            errors.append(f"{where}: id `{rid}` repeats line {seen[rid]}")
        seen[rid] = row["line"]
        basis, unit = row["basis"], row["unit"]
        if basis not in BASES:
            errors.append(f"{where}: basis `{basis}` is not one of {', '.join(BASES)}")
        if (basis == "legacy") != rid.startswith("legacy."):
            errors.append(f"{where}: legacy rows, and only they, have ids starting with `legacy.`")
        known = unit in TIME_UNITS or unit in NUMBER_UNITS or unit in FLAG_UNITS or unit in TEXT_UNITS
        if not known:
            errors.append(f"{where}: unit `{unit}` is unknown. Use one of the units in {Path(__file__).name} "
                          f"(TIME_UNITS, NUMBER_UNITS, FLAG_UNITS, TEXT_UNITS) or add it there.")
        if not row["value"]:
            errors.append(f"{where}: `{rid}` has no value. A behavior is built from its reference or not built; "
                          f"give the value its reference states.")
        elif known and unit not in TEXT_UNITS:
            value = parse_number(row["value"])
            if value is None:
                errors.append(f"{where}: value `{row['value']}` is not a number, which unit `{unit}` needs")
            elif unit in FLAG_UNITS and value not in (0, 1):
                errors.append(f"{where}: a flag is 0 or 1")
            elif unit in TIME_UNITS and basis not in ("fit", "legacy") and "/" not in row["value"] and \
                    (value * TIME_UNITS[unit]).denominator != 1:
                errors.append(f"{where}: {row['value']} {unit} is not a whole number of 750 MHz units. "
                              f"Only a fit row may round; write an exact fraction or mark the basis fit.")
        if not row["reference"]:
            errors.append(f"{where}: `{rid}` has no reference. Cite the hardware reference (document and section), "
                          f"or mark the basis model-choice and state the reason in the reference.")
        if not row["verify"]:
            errors.append(f"{where}: `{rid}` has no check. Name the check that decides it from {CHECKS}, "
                          f"or pending:<gate> when its corpus cannot run yet.")
        for cid in row["verify"].split():
            if not check_defined(cid, explicit, suite_files):
                errors.append(f"{where}: check `{cid}` is not defined in {CHECKS}. Add a row there "
                              f"(id, runner, target, selector, expect, source), or land the suite file that defines it.")
        if basis == "legacy":
            if not LEGACY_NOTE.match(row["note"]):
                errors.append(f"{where}: a legacy note starts with `replaced by T<unit>: ` or `no plan unit: `")
            here = sorted(set(sites.get(rid, [])))
            m = REFERENCE_SITE.match(row["reference"])
            if not here:
                errors.append(f"{where}: legacy row `{rid}` has no code site in tools/n64-timing/literal-allowlist.tsv. "
                              f"If its unit replaced the cost, delete the row.")
            elif not m or (m.group(1), int(m.group(2))) not in here:
                errors.append(f"{where}: legacy row `{rid}` cites {row['reference']}, which is not one of its code sites "
                              f"({', '.join(f'{p}:{n}' for p, n in here[:3])}). Run tools/n64-timing/behaviors.py --fix-lines.")
    legacy_ids = {r["id"] for r in rows if r["basis"] == "legacy"}
    for rid in sorted(set(sites) - legacy_ids):
        if rid in seen:
            errors.append(f"tools/n64-timing/literal-allowlist.tsv: `{rid}` is not a legacy row. Code reads a "
                          f"non-legacy row as Timing::Behavior::{constant_name(rid)}, never through the allowlist.")
    by_name = {constant_name(r["id"]): r for r in rows}
    for name, where in behavior_uses(root):
        row = by_name.get(name)
        if row is None:
            errors.append(f"{where}: Timing::Behavior::{name} matches no row in {TABLE}. Add the row and run behaviors.py.")
        elif constant(row) is None:
            errors.append(f"{where}: Timing::Behavior::{name} refers to row `{row['id']}`, which has no numeric value "
                          f"({row['value']} {row['unit']}, basis {row['basis']}). Give the row a number, or implement "
                          f"the rule in code that cites the row.")
    return errors, rows, checks, sites


def cpp_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_header(rows):
    out = [
        f"//GENERATED by tools/n64-timing/behaviors.py from {TABLE}. Do not edit.",
        "//behaviors.py --check fails when this file, docs/spec/n64-timing.md or tools/n64-timing/checks.tsv",
        "//disagree with the table. Times are in 750 MHz units; a unit is 1/750 MHz.",
        "",
        "namespace Timing {",
        "",
        "struct Ratio { s64 numerator; s64 denominator; };",
        "",
        "enum class Basis : u8 { " + ", ".join(v[0] for v in BASES.values()) + " };",
        "",
        "struct BehaviorInfo {",
        "  const char* id;",
        "  Basis basis;",
        "  const char* value;",
        "  const char* unit;",
        "  const char* reference;",
        "  const char* verify;",
        "  const char* note;",
        "};",
        "",
        "namespace Behavior {",
    ]
    for row in rows:
        c = constant(row)
        if c:
            kind, value, comment, rounding = c
            out.append(f"  constexpr {kind} {constant_name(row['id'])} = {value};  //{comment}{'; ' + rounding if rounding else ''}")
    out += ["}", "", "inline constexpr BehaviorInfo behaviors[] = {"]
    for row in rows:
        fields = [cpp_string(row["id"]), f"Basis::{BASES[row['basis']][0]}"] + \
                 [cpp_string(row[k]) for k in ("value", "unit", "reference", "verify", "note")]
        out.append("  {" + ", ".join(fields) + "},")
    out += ["};", "", "}", ""]
    return "\n".join(out)


def cell(text):
    return text.replace("|", "\\|") if text else ""


def check_cell(cid):
    return f"pending ({cid[8:]})" if cid.startswith("pending:") else f"`{cid}`"


def value_cell(row):
    c = constant(row)
    text = f"{row['value']} {row['unit']}"
    if c and c[3]:
        text += f" ({c[3]})"
    return cell(text)


def render_spec(rows, checks):
    count = {b: sum(1 for r in rows if r["basis"] == b) for b in BASES}
    out = [
        f"<!-- GENERATED by tools/n64-timing/behaviors.py from {TABLE} and {CHECKS}. "
        "Do not edit; behaviors.py --check fails on any manual change. -->",
        "",
        "# N64 timing spec",
        "",
        "This is the timing model's specification (map [#1](https://github.com/wScottSh/ares/issues/1)). "
        "Each row is one behavior: its value, the basis of that value, the reference it comes from, and the checks that decide it. "
        "There is no unverified status. A behavior is built from its reference, or it is a model choice whose reference states the reason. "
        "A check written `pending (gate)` names a corpus the program cannot run yet, and it never counts as verified. "
        "Per-check results come from `behaviors.py --results` (plan T17).",
        "",
        "| Basis | Meaning | Rows |",
        "|---|---|---|",
    ]
    out += [f"| {b} | {meaning} | {count[b]} |" for b, (_, meaning) in BASES.items()]
    groups = {}
    for row in rows:
        if row["basis"] != "legacy":
            groups.setdefault(row["id"].split(".")[0], []).append(row)
    out += ["", "## Behaviors"]
    for group, members in groups.items():
        out += ["", f"### {group}", "", "| Behavior | Value | Basis | Reference | Checks | Note |", "|---|---|---|---|---|---|"]
        for r in members:
            out.append(f"| `{r['id']}` | {value_cell(r)} | {r['basis']} | {cell(r['reference'])} | "
                       f"{' '.join(check_cell(c) for c in r['verify'].split())} | {cell(r['note'])} |")
    out += ["", "## Legacy costs in today's core", "",
            "Each row is a constant that today's core still charges. `tools/n64-timing/literal-allowlist.tsv` pins the literal "
            "at its code site to the row, so the code and this table cannot disagree. The plan unit in the note replaces the cost "
            "and deletes the row.", "",
            "| Behavior | Value | Code site | Checks | Note |", "|---|---|---|---|---|"]
    for r in rows:
        if r["basis"] == "legacy":
            out.append(f"| `{r['id']}` | {value_cell(r)} | {cell(r['reference'])} | "
                       f"{' '.join(check_cell(c) for c in r['verify'].split())} | {cell(r['note'])} |")
    out += ["", "## Checks", "",
            "From `tools/n64-timing/checks.tsv`. A `:*` row names a suite whose expected file defines every check under its prefix.", "",
            "| Check | Runner | Target | Selector | Expectation | Source |", "|---|---|---|---|---|---|"]
    for c in checks:
        out.append(f"| `{c['id']}` | {c['runner']} | {cell(c['target'])} | {cell(c['selector'])} | {cell(c['expect'])} | {cell(c['source'])} |")
    return "\n".join(out) + "\n"


def generated(root):
    errors, rows, checks, sites = validate(root)
    return errors, {HEADER: render_header(rows), SPEC: render_spec(rows, checks)}


def check(root):
    errors, outputs = generated(root)
    for rel, text in outputs.items():
        path = Path(root) / rel
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            errors.append(f"{rel} differs from the generated output. Edit {TABLE} or {CHECKS}, then run "
                          f"tools/n64-timing/behaviors.py; never edit the generated file.")
    return errors


def fix_lines(root):
    errors, rows, _, sites = validate(root)
    path = Path(root) / TABLE
    lines = path.read_text(encoding="utf-8").split("\n")
    changed = 0
    for row in rows:
        here = sorted(set(sites.get(row["id"], [])))
        if row["basis"] != "legacy" or not here:
            continue
        m = REFERENCE_SITE.match(row["reference"])
        if m and (m.group(1), int(m.group(2))) in here:
            continue
        fields = lines[row["line"] - 1].split("\t")
        fields[4] = f"{here[0][0]}:{here[0][1]}"
        lines[row["line"] - 1] = "\t".join(fields)
        changed += 1
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return changed


def nemu64_result(path, row):
    target, selector = row["target"], row["selector"]
    base = Path(path) / target
    if not (base / "tests.tsv").exists():
        return "not run"
    selector, _, category = selector.partition(" #")
    selector, _, value = selector.partition(" @")
    tests = {l.split("\t")[0]: l.split("\t")[-1] for l in (base / "tests.tsv").read_text(encoding="utf-8").split("\n")[1:] if l}
    if selector.startswith("re:"):
        names = [n for n in tests if re.search(selector[3:], n)]
    else:
        names = [n for n in selector.split("|") if n in tests]
    if not names:
        return "missing"
    if category:
        rows = [l.split("\t") for l in (base / "categories.tsv").read_text(encoding="utf-8").split("\n")[1:] if l]
        failed = sum(1 for r in rows if r[1] == category and r[2] in names)
        return f"fail ({failed} {category} values)" if failed else "pass"
    if value:
        rows = [l.split("\t") for l in (base / "values.tsv").read_text(encoding="utf-8").split("\n")[1:] if l]
        picked = [r for r in rows if r[1] in names and value in r[2]]
        if not picked:
            return "missing"
        return "pass" if all(r[3] == "pass" for r in picked) else "fail"
    failing = [n for n in names if tests[n] != "pass"]
    return f"fail ({len(failing)} of {len(names)} tests)" if failing else "pass"


def det_result(path, row):
    text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).exists() else ""
    m = re.search(r"determinism: (PASS|FAIL)[^\n]*", text)
    return m.group(0).replace("determinism: ", "").lower() if m else "not run"


READERS = {"nemu64": nemu64_result, "det": det_result}


def results(root, sources):
    errors, rows, checks, _ = validate(root)
    by_id = {c["id"]: c for c in checks}
    out = ["| Behavior | Basis | Check | Result |", "|---|---|---|---|"]
    tally = {}
    for row in rows:
        for cid in row["verify"].split():
            c = by_id.get(cid)
            if cid.startswith("pending:"):
                result = f"pending ({cid[8:]})"
            elif c is None or c["runner"] not in sources:
                result = "not run"
            elif c["runner"] in READERS:
                result = READERS[c["runner"]](sources[c["runner"]], c)
            else:
                result = f"no reader for {c['runner']} yet"
            status = re.match(r"not run|no reader|pass|fail|pending|missing", result)
            key = status.group(0) if status else result
            tally[key] = tally.get(key, 0) + 1
            out.append(f"| `{row['id']}` | {row['basis']} | `{cid}` | {cell(result)} |")
    summary = ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))
    return errors, "\n".join([f"Results: {summary}", ""] + out) + "\n"


def self_test(root):
    """Copies the inputs to a scratch tree, breaks each rule once, and checks the failure names its fix."""
    root = Path(root)
    work = Path(tempfile.mkdtemp(prefix="behaviors-self-test-"))
    try:
        shutil.copytree(root / "ares/n64", work / "ares/n64")
        shutil.copytree(root / "tools/n64-timing", work / "tools/n64-timing", ignore=shutil.ignore_patterns("__pycache__"))
        (work / SPEC).parent.mkdir(parents=True)
        shutil.copy(root / SPEC, work / SPEC)

        def edit(rel, change):
            path = work / rel
            before = path.read_text(encoding="utf-8")
            path.write_text(change(before), encoding="utf-8", newline="\n")
            return lambda: path.write_text(before, encoding="utf-8", newline="\n")

        def row_field(row_id, column, value):
            def change(text):
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    fields = line.split("\t")
                    if fields[0] == row_id:
                        fields[COLUMNS.index(column)] = value
                        lines[i] = "\t".join(fields)
                return "\n".join(lines)
            return change

        new_function = "\nauto CPU::selfTestCost() -> void {\n  step(7 * 2);\n}\n"
        suite_file = "tools/n64-timing/romgen/suites/bench/expected.tsv"
        bench_rows = [c for c in read_tsv(work, CHECKS, CHECK_COLUMNS, []) if c["expect"] == "suite" and c["runner"] == "bench"]
        suite_lines = ["rom\tpoint\tmetric\texpected", "self-test-rom\tp\tm\t1"]
        for c in bench_rows:
            wanted = dict(p.split("=", 1) for p in c["selector"].split() if "=" in p)
            suite_lines.append(f"{c['target']}\t{wanted.get('point', '-')}\t{wanted.get('metric', '-')}\t1")
        if not (work / suite_file).exists():
            (work / suite_file).parent.mkdir(parents=True, exist_ok=True)
            (work / suite_file).write_text("\n".join(suite_lines) + "\n", encoding="utf-8", newline="\n")
            landed = True
        else:
            landed = False
        cases = [
            ("the committed tree", None, None, None),
            ("removing a reference", TABLE, row_field("ri.read-hit", "reference", ""), "has no reference. Cite the hardware reference"),
            ("an unknown check id", TABLE, row_field("ri.read-hit", "verify", "bench:no-such-rom"), "check `bench:no-such-rom` is not defined in tools/n64-timing/checks.tsv. Add a row there"),
            ("an empty check list", TABLE, row_field("ri.write-hit", "verify", ""), "has no check. Name the check"),
            ("adding a timing literal", "ares/n64/cpu/memory.cpp", lambda t: t + new_function, "timing literal [7, 2, 14] in `step(7 * 2);`. Add a row to ares/n64/timing/behaviors.tsv"),
            ("changing a legacy literal", "ares/n64/cpu/dcache.cpp", lambda t: t.replace("cpu.step(40 * 2);", "cpu.step(41 * 2);", 1), "If the code no longer charges this cost, delete the entry"),
            ("changing a legacy row's value", TABLE, row_field("legacy.cpu.div", "value", "36"), "Make ares/n64/timing/behaviors.tsv and the code agree"),
            ("referencing a value-less row", "ares/n64/cpu/memory.cpp", lambda t: t + "\nstatic auto selfTestRule = Timing::Behavior::RiArbitration;\n", "which has no numeric value"),
            ("referencing an unknown row", "ares/n64/cpu/memory.cpp", lambda t: t + "\nstatic auto selfTestRule = Timing::Behavior::RiNoSuchRow;\n", "matches no row"),
            ("a model choice without a reason", TABLE, row_field("ri.rank.vi", "reference", ""), "or mark the basis model-choice and state the reason"),
            ("an inexact time value", TABLE, row_field("ri.read-hit", "value", "10.5"), "is not a whole number of 750 MHz units"),
            ("editing the generated spec", SPEC, lambda t: t + "manual edit\n", "docs/spec/n64-timing.md differs from the generated output"),
            ("editing the generated header", HEADER, lambda t: t.replace("= 30;", "= 31;", 1), "ares/n64/timing/behaviors.hpp differs from the generated output"),
            ("a legacy code site moving", "ares/n64/cpu/dcache.cpp", lambda t: "\n" + t, "Run tools/n64-timing/behaviors.py --fix-lines"),
        ]
        if landed:
            cases += [
                ("a check defined only by a landed suite file", TABLE, row_field("ri.read-hit", "verify", "bench:self-test-rom"), None),
                ("a suite file that lacks a selected row", suite_file,
                 lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("mi-memset-uncached")),
                 "selects rom=mi-memset-uncached point=vi-on metric=pclk_per_sd but"),
            ]
        failures = 0
        for name, rel, change, expected in cases:
            restore = edit(rel, change) if rel else None
            errors = check(work) if rel is None or expected is not None else validate(work)[0]
            if expected is None:
                ok = not errors
                detail = errors[0] if errors else "no errors"
            else:
                hits = [e for e in errors if expected in e]
                ok = bool(hits)
                detail = hits[0] if hits else f"no error contains `{expected}`; got {errors[:2]}"
            print(f"self-test: {name}: {'ok' if ok else 'FAILED'}: {detail}")
            failures += not ok
            if name == "a legacy code site moving" and ok:
                fix_lines(work)
                after = check(work)
                drift = [e for e in after if "--fix-lines" in e]
                print(f"self-test: --fix-lines repairs it: {'ok' if not drift else 'FAILED'}")
                failures += bool(drift)
                shutil.copy(root / TABLE, work / TABLE)
            if restore:
                restore()
        return failures
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fix-lines", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--results", nargs="+", metavar="RUNNER=PATH")
    parser.add_argument("--out")
    args = parser.parse_args()
    root = args.root

    def report(errors, what):
        for e in errors:
            print(e, file=sys.stderr)
        print(f"behaviors.py: {what}: {len(errors)} error(s)" if errors else f"behaviors.py: {what}: ok",
              file=sys.stderr if errors else sys.stdout)
        return 1 if errors else 0

    if args.self_test:
        status = 1 if self_test(root) else 0
        if not args.check:
            return status
        return report(check(root), "check") or status
    if args.check:
        return report(check(root), "check")
    if args.fix_lines:
        print(f"behaviors.py: --fix-lines rewrote {fix_lines(root)} reference(s)")
        return 0
    if args.results:
        sources = dict(s.split("=", 1) for s in args.results)
        errors, text = results(root, sources)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(text)
        return report(errors, "results") if errors else 0
    errors, outputs = generated(root)
    if errors:
        return report(errors, "generate")
    for rel, text in outputs.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"behaviors.py: wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
