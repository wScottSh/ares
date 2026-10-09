#!/usr/bin/env python3
"""Generates the N64 timing constants and spec from ares/n64/timing/behaviors.tsv.

usage: behaviors.py                 write ares/n64/timing/behaviors.hpp, docs/spec/n64-timing.md and
                                    docs/spec/map-1-closure-draft.md
       behaviors.py --check         fail unless the table, tools/n64-timing/checks.tsv, the results,
                                    the generated files and the literal lint all agree
       behaviors.py --fix-lines     rewrite each legacy row's file:line to its current code site
       behaviors.py --results RUN_DIR
                                    write docs/spec/n64-timing-results.tsv, one result per
                                    check, from one standing run of every suite
       behaviors.py --self-test     prove each --check failure fires and names its fix

The console calibration (#16): tools/n64-timing/calibration/questions.tsv lists every question a
console run answers, with the kit ROM that measures it. A row a console run decides names it as
hw:<question> in its verify column; until a capture is ingested
(tools/n64-timing/calibration/ingest.py) that check is pending:calibration-16. behaviors.py also
writes docs/calibration/inventory.md, the question table joined with every row and check the
hardware could decide.

behaviors.tsv columns: id, value, unit, basis, reference, verify, fit-from, note, code.
Every row names a reference and at least one check, and says where the code builds it. A
row with a number is built when code reads it as Timing::Behavior::<Name>, and a legacy row
is built at its literal's code site, so their code column is empty. A rule, order or map
row, or a number the code implements without reading it, names the code that implements it
in its code column: one or more `ares/n64/<path>:<symbol>`. A row whose value the code does
not use is not built: its code column reads `not-built: <what the code does instead>` and
names that code as `ares/n64/<path>:<symbol>`; its status is not-built whatever its checks
say. A check written `~id` is a guard: it
runs and can fail the row, but it never makes the row pass, because it does not measure the
row's value. det and stepcap are always written as guards: they show a run repeats, not that
a value is right. A row whose checks are all guards must be a model-choice row; its status is
model-choice. A fit row's fit-from names the
checks whose data its value was solved from; a pass on those verifies the arithmetic,
not the model, so its verify column needs another check that decides it (not a report
or a pending gate). A fit row with none starts its note with `verify-is-fit: <reason>`
and the spec labels it fit only. A legacy row is a cost today's core
still charges: its reference is the code site, the literal lint pins the literal
to it, and its note names the plan unit that replaces it. A model-choice row has
no published value; its reference states the reason for the choice. An inferred
row has no measurement or published value of its own; its note states the
inference.

checks.tsv columns: id, runner, target, selector, expect, source. A row whose id
ends in `:*` is a suite row: every id under that prefix that the suite's expected
file defines (key column = the row's selector) resolves without a row of its own,
and every explicit row whose expect is `suite` must find its target there once
the file exists.
"""
import argparse
import fnmatch
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

TABLE = "ares/n64/timing/behaviors.tsv"
CHECKS = "tools/n64-timing/checks.tsv"
HEADER = "ares/n64/timing/behaviors.hpp"
SPEC = "docs/spec/n64-timing.md"
RESULTS = "docs/spec/n64-timing-results.tsv"
CLOSURE = "docs/spec/map-1-closure-draft.md"
INVENTORY = "docs/calibration/inventory.md"
KIT = "tools/n64-timing/calibration/kit.py"
LINT = "tools/n64-timing/lint-literals.py"
COLUMNS = ["id", "value", "unit", "basis", "reference", "verify", "fit-from", "note", "code"]
CHECK_COLUMNS = ["id", "runner", "target", "selector", "expect", "source"]

BASES = {
    "measured": ("Measured", "a hardware measurement: a test ROM result or a console capture"),
    "vendor": ("Vendor", "Nintendo, NEC or SGI documentation, or a patent"),
    "datasheet": ("Datasheet", "a component datasheet"),
    "wiki": ("Wiki", "a community reference: n64brew, or a test suite author's notes"),
    "rtl": ("Rtl", "a hardware description (MiSTer RTL)"),
    "derived": ("Derived", "computed from other cited values"),
    "inferred": ("Inferred", "reasoned from cited values with no measurement or published value of its own; the note states the inference"),
    "fit": ("Fit", "fitted to measured data; rounded to the nearest 750 MHz unit"),
    "model-choice": ("ModelChoice", "no published value; the reference states why the model chose this one"),
    "legacy": ("Legacy", "a constant today's core charges; the reference is its code site and the note names the unit that replaces it"),
}
#750 MHz units per unit (ares/n64/timing/clock.hpp).
TIME_UNITS = {
    "units": 1, "tc": 3, "pclk": 8, "rclk": 12, "cop0count": 16,
    "us": 750, "ms": 750_000, "s": 750_000_000, "vclk": Fraction(5500, 357),
}
NUMBER_UNITS = {"Hz", "B", "entries", "dwords", "px", "lines", "instr", "rank", "bit",
                "B/rclk", "px/rclk", "vclk/px"}
FLAG_UNITS = {"flag"}
TEXT_UNITS = {"order", "map", "rule", "event"}
RUNNERS = {"nemu64", "bench", "thar0", "snapper", "rdpstat", "noise", "pidma", "hydra",
           "mm", "det", "stepcap", "unit", "gen", "pending", "harness", "hw"}
BARE_RUNNERS = {"det", "stepcap", "gen"}
GUARD_RUNNERS = {"det", "stepcap"}
EXPECT = re.compile(r"^(self|suite|report|equal|pass|gate|file:\S+|-?[\d.]+)$")
VERIFY_IS_FIT = re.compile(r"^verify-is-fit: \S")
LEGACY_NOTE = re.compile(r"^(replaced by T(?:\d+[a-d]?|-L)|no plan unit): \S")
ID = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9-]+)+$")
REFERENCE_SITE = re.compile(r"^(ares/n64/\S+):(\d+)$")
BEHAVIOR_USE = re.compile(r"\bBehavior::(\w+)")
CODE_POINTER = re.compile(r"\b(ares/n64/[\w./-]+):([\w:.]*\w)")
NOT_BUILT = "not-built: "
USING_BEHAVIOR = "using namespace Timing::Behavior;"
COMMENT_OR_LITERAL = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|(?<!\w)\'(?:\\.|[^\'\\\n])*\'', re.S)


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
            return "Clock", f"{{{units.numerator}}}", comment, ""
        if "/" in text:
            return "Ratio", f"{{{units.numerator}, {units.denominator}}}", comment, ""
        rounded = (units.numerator * 2 + units.denominator) // (units.denominator * 2)
        return "Clock", f"{{{rounded}}}", comment, f"{rounded} units, rounded from {float(units):g}"
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
        if row["runner"] == "bench":
            bench_rules(row["expect"][5:], header, body, errors)
    for cid, row in explicit.items():
        if row["expect"] != "suite":
            continue
        prefix = cid.split(":")[0]
        if prefix not in suites:
            errors.append(f"{CHECKS}:{row['line']}: `{cid}` takes its value from a suite, but there is no `{prefix}:*` row")
        elif prefix in suite_files and not suite_matches(suite_files[prefix], row["target"], row["selector"]):
            key = suite_files[prefix][0]
            errors.append(f"{CHECKS}:{row['line']}: `{cid}` selects {key}={row['target']} {row['selector']} "
                          f"but {suites[prefix]['expect'][5:]} has no such row. Fix the target and selector, "
                          f"or add the measurement to the suite.")
    return rows, explicit, suites, suite_files


def bench_rules(path, header, body, errors):
    """Every asserted bench row names how its value over the boot delays meets the band
    (romgen/suites/bench/report.py verdict); a report row has none."""
    from romgen.suites.bench.report import RULES
    if "rule" not in header:
        errors.append(f"{path}: no `rule` column. Name each check row's phase rule: {', '.join(RULES)}.")
        return
    for line, b in enumerate(body, 2):
        if b.get("kind") == "check" and b.get("rule") not in RULES:
            errors.append(f"{path}:{line}: check row {b.get('rom')} {b.get('point')} has rule `{b.get('rule')}`; "
                          f"use {', '.join(RULES)} (bench README, Phase).")
        elif b.get("kind") != "check" and b.get("rule") != "-":
            errors.append(f"{path}:{line}: report row {b.get('rom')} {b.get('point')} has rule `{b.get('rule')}`; write `-`.")
        if not CONDITION.match(b.get("condition", "")) or (b.get("kind") != "check" and b.get("condition") != "-"):
            errors.append(f"{path}:{line}: row {b.get('rom')} {b.get('point')} has condition `{b.get('condition')}`; write `-`, "
                          f"or on a check row the `#<issue>` of the model choice its pass rests on.")


def suite_matches(suite_file, target, selector):
    key, header, body = suite_file
    wanted = dict(p.split("=", 1) for p in selector.split() if "=" in p)
    if any(c not in header for c in wanted):
        return []
    return [b for b in body if b.get(key) == target and all(b.get(c) == v for c, v in wanted.items())]


def verify_checks(row):
    """(check id, guard) for each check in the row's verify column."""
    return [(c[1:], True) if c.startswith("~") else (c, False) for c in row["verify"].split()]


def decides(cid, explicit, suite_files):
    """False for a check that cannot fail: a pending gate, a report with no asserted row, or a hardware
    check, which decides nothing until a console capture is ingested."""
    row = explicit.get(cid)
    prefix, _, rest = cid.partition(":")
    if prefix == "hw":
        return False
    if row is None:
        rows = suite_matches(suite_files[prefix], rest, "-") if prefix in suite_files else []
    elif row["expect"] == "suite" and prefix in suite_files:
        rows = suite_matches(suite_files[prefix], row["target"], row["selector"])
    else:
        return row is not None and row["expect"] not in ("report", "gate")
    return any(r.get("kind", "check") != "report" for r in rows)


def check_defined(cid, explicit, suite_files):
    if cid in explicit:
        return True
    prefix, _, rest = cid.partition(":")
    if prefix in suite_files:
        key, _, body = suite_files[prefix]
        return any(b.get(key) == rest for b in body)
    return False


def uncommented(text):
    """C++ source with each comment blanked and its newlines kept, so a name in a comment reads as no use
    and line numbers stay put. String and character literals are kept whole: a `//` inside one is not a
    comment, and a digit separator (0x1fc0'0000) starts no literal."""
    def blank(m):
        return m.group(0) if m.group(0)[0] in "\"'" else re.sub(r"[^\n]", " ", m.group(0))
    return COMMENT_OR_LITERAL.sub(blank, text)


def core_sources(root):
    """(path, text) for every core source file, comments blanked (uncommented)."""
    for path in sorted((Path(root) / "ares/n64").rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.suffix in (".cpp", ".hpp") and rel != HEADER:
            yield rel, uncommented(path.read_text(encoding="utf-8", errors="replace"))


def behavior_uses(root):
    uses = []
    for rel, text in core_sources(root):
        for number, line in enumerate(text.split("\n"), 1):
            for name in BEHAVIOR_USE.findall(line):
                uses.append((name, f"{rel}:{number}"))
    return uses


def constants_read(root, names):
    """The constant names the core reads: as Timing::Behavior::<Name>, or bare in a file that says
    `using namespace Timing::Behavior`."""
    read = {name for name, _ in behavior_uses(root)}
    for _, text in core_sources(root):
        if USING_BEHAVIOR in text:
            read |= names & set(re.findall(r"\w+", text))
    return read


def pointer_error(root, path, symbol):
    """None when `symbol` names something in `path`, else the reason it does not."""
    file = Path(root) / path
    if not file.is_file():
        return f"{path} does not exist"
    if not re.search(rf"(?<!\w){re.escape(symbol)}(?!\w)", uncommented(file.read_text(encoding="utf-8", errors="replace"))):
        return f"{path} has no `{symbol}`"
    return None


def not_built(row):
    return row["code"].startswith(NOT_BUILT)


def code_errors(root, row, read, where):
    """A row's code column against what the code reads (see the module docstring)."""
    rid, code = row["id"], row["code"]
    name = f"Timing::Behavior::{constant_name(rid)}"
    pointers = CODE_POINTER.findall(code)
    errors = [f"{where}: `{rid}` code pointer {path}:{symbol} does not resolve: {reason}. Point at the function or "
              f"name that implements it." for path, symbol in pointers for reason in [pointer_error(root, path, symbol)] if reason]
    if row["basis"] == "legacy":
        if code:
            errors.append(f"{where}: legacy row `{rid}` is built at its literal-allowlist code site; clear its code column.")
    elif read:
        if code:
            errors.append(f"{where}: code reads {name}, so `{rid}` is built there; clear its code column.")
    elif not code:
        what = f"no code reads {name}, and `{rid}` names no code" if constant(row) else \
            f"`{rid}` ({row['value']} {row['unit']}) has no constant, and it names no code that implements it"
        errors.append(f"{where}: {what}. Read the constant where the cost is charged, name the code that implements "
                      f"it (ares/n64/<path>:<symbol>), or write `{NOT_BUILT}<what the code does instead, "
                      f"ares/n64/<path>:<symbol>>`.")
    elif not pointers:
        errors.append(f"{where}: `{rid}` code `{code}` names no ares/n64/<path>:<symbol>. "
                      + ("Name the code that does instead." if not_built(row) else "Name the code that implements it."))
    elif not not_built(row) and CODE_POINTER.sub("", code).strip():
        errors.append(f"{where}: `{rid}` code `{code}` is not a list of ares/n64/<path>:<symbol> pointers. A row whose "
                      f"value the code does not use starts with `{NOT_BUILT}`.")
    return errors


def validate(root):
    """Returns (errors, rows, checks, sites)."""
    errors = []
    rows = read_tsv(root, TABLE, COLUMNS, errors)
    checks, explicit, _, suite_files = load_checks(root, errors)
    lint_errors, sites = lint_module().lint(root)
    errors += lint_errors
    seen = {}
    read = constants_read(root, {constant_name(r["id"]) for r in rows if constant(r)})
    for row in rows:
        where = f"{TABLE}:{row['line']}"
        rid = row["id"]
        errors += code_errors(root, row, constant(row) is not None and constant_name(rid) in read, where)
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
        for cid, guard in verify_checks(row):
            if not check_defined(cid, explicit, suite_files):
                errors.append(f"{where}: check `{cid}` is not defined in {CHECKS}. Add a row there "
                              f"(id, runner, target, selector, expect, source), or land the suite file that defines it.")
            elif guard and cid.startswith("pending:"):
                errors.append(f"{where}: `~{cid}` marks a gate as a guard. A gate is not a check; write `{cid}`.")
            elif not guard and explicit.get(cid, {}).get("runner") in GUARD_RUNNERS:
                errors.append(f"{where}: `{cid}` shows a run repeats, not that `{rid}`'s value is right. "
                              f"Write `~{cid}` so it guards the row without passing it.")
        if row["verify"] and basis != "model-choice" and all(guard for _, guard in verify_checks(row)):
            errors.append(f"{where}: every check of `{rid}` is a guard, so nothing decides its value. Name a check "
                          f"that measures it, or the pending:<gate> that keeps one from running.")
        fit_from, flagged = row["fit-from"].split(), bool(VERIFY_IS_FIT.match(row["note"]))
        for cid in fit_from:
            if not check_defined(cid, explicit, suite_files):
                errors.append(f"{where}: fit-from check `{cid}` is not defined in {CHECKS}. Name the check whose data the fit solved.")
        if basis != "fit" and (fit_from or flagged):
            errors.append(f"{where}: only a fit row has fit-from or a verify-is-fit note. Clear them, or mark the basis fit.")
        elif basis == "fit":
            independent = [c for c, guard in verify_checks(row)
                           if not guard and c not in fit_from and decides(c, explicit, suite_files)]
            if not fit_from:
                errors.append(f"{where}: fit row `{rid}` has no fit-from. Name the checks whose data the value was solved "
                              f"from in the fit-from column.")
            elif not independent and not flagged:
                errors.append(f"{where}: every check of fit row `{rid}` is its fit data ({row['fit-from']}), a report or a "
                              f"pending gate, so a pass verifies the arithmetic, not the model. Add a check that decides it "
                              f"from other data, or start the note with `verify-is-fit: <reason>`; the spec then labels the row fit only.")
            elif independent and flagged:
                errors.append(f"{where}: fit row `{rid}` says verify-is-fit, but `{independent[0]}` decides it from other data. "
                              f"Remove the verify-is-fit note.")
        if basis == "inferred" and not row["note"]:
            errors.append(f"{where}: inferred row `{rid}` has no note. State the inference and what it rests on.")
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
        "//disagree with the table. Times are Clock values (timing/clock.hpp), in 750 MHz units.",
        "",
        "namespace Timing {",
        "",
        "enum class Basis : u8 { " + ", ".join(v[0] for v in BASES.values()) + " };",
        "inline constexpr const char* basisNames[] = { " + ", ".join(cpp_string(b) for b in BASES) + " };",
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
    if cid.startswith("~"):
        return check_cell(cid[1:]) + " (guard)"
    return f"pending ({cid[8:]})" if cid.startswith("pending:") else f"`{cid}`"


def hw_decided(row, found):
    """True when a hardware check of the row has a console result, which ends a verify-is-fit note."""
    return any(c.startswith("hw:") and found.get(c, ("",))[0] in ("pass", "fail") for c, _ in verify_checks(row))


def checks_cell(row, found=None):
    text = " ".join(check_cell(c) for c in row["verify"].split())
    if row["fit-from"]:
        text += " (fit from " + " ".join(check_cell(c) for c in row["fit-from"].split()) + ")"
    if VERIFY_IS_FIT.match(row["note"]) and not (found and hw_decided(row, found)):
        text = "**fit only, no independent check:** " + text
    return text


def code_cell(row):
    if row["code"]:
        return cell(row["code"])
    return "" if row["basis"] == "legacy" else f"reads `Timing::Behavior::{constant_name(row['id'])}`"


def value_cell(row):
    c = constant(row)
    text = f"{row['value']} {row['unit']}"
    if c and c[3]:
        text += f" ({c[3]})"
    return cell(text)


def result_word(cid, found):
    if cid.startswith("~"):
        return result_word(cid[1:], found) + " (guard)"
    return check_cell(cid) if cid.startswith("pending:") else f"`{cid}` {found.get(cid, ('missing', ''))[0]}"


def result_cell(row, found):
    return f"**{row_status(row, found)}**: " + "; ".join(result_word(c, found) for c in row["verify"].split())


STATUS_MEANING = {
    "pass": "a check other than the row's fit data passed, and none failed",
    "fail": "at least one check failed; the detail in Check results gives the residual",
    "fit only": "only the checks the value was fitted to passed (verify-is-fit)",
    "consistent-only": "no check failed, but a check passed its consistent rule while the model's phase mean missed the band: "
                       "some phase of the model agrees with the hardware number, the average does not. Consistent with the "
                       "hardware, not agreement",
    "pass-conditional": "no check failed, but a check passes only through a model choice with no hardware reference (the "
                        "issue named); it is not independent hardware agreement until the issue resolves",
    "model-choice": "a model-choice row whose only checks are guards: they passed, which shows the choice is built and runs the "
                    "same every time, not that its value is right",
    "not-built": "the code does not use the row's value; its code column says what the code does instead. Its checks "
                 "measure that code, not the row",
}


def status_meaning(status):
    return STATUS_MEANING.get(status.split(":")[0] if status.startswith("pass-conditional:") else status)


def statuses(rows, found):
    count = {}
    for r in rows:
        s = row_status(r, found)
        count[s] = count.get(s, 0) + 1
    return count


def render_spec(rows, checks, found):
    count = {b: sum(1 for r in rows if r["basis"] == b) for b in BASES}
    gates = {c["id"]: c for c in checks if c["runner"] == "pending"}
    out = [
        f"<!-- GENERATED by tools/n64-timing/behaviors.py from {TABLE}, {CHECKS} and {RESULTS}. "
        "Do not edit; behaviors.py --check fails on any manual change. -->",
        "",
        "# N64 timing spec",
        "",
        "This is the timing model's specification (map [#1](https://github.com/wScottSh/ares/issues/1)). "
        "Each row is one behavior: its value, the basis of that value, the reference it comes from, the checks that decide it, and their results. "
        "There is no unverified status. A behavior is built from its reference (or, as a model choice, from the reason its "
        "reference states), or it is not built. The Code column says where it is built: the constant the code reads, or the "
        "code that implements a rule. A row whose value the code does not use is not built, and its Code column says what "
        "the code does instead. "
        "A check written `pending (gate)` names a corpus the program cannot run yet, and it never counts as verified. "
        "A fit row names the checks its value was solved from (fit from). A pass on those verifies the arithmetic, not the model, "
        "so a fit row whose other checks only report is labeled **fit only, no independent check**, and its note says why. "
        "A check marked (guard) runs and can fail its row, but it never passes it, because it does not measure the row's value: "
        "det and stepcap show a run repeats, not that a value is right.",
        "",
        f"Results come from `behaviors.py --results` over one standing run of every suite, recorded in `{RESULTS}`. "
        "A check is pass, fail, or pending on a named gate. A check that reports its number but asserts none is pending on "
        "report-only. Two results are weaker than pass and never count as one. A bench check is consistent-only when a point "
        "passes its consistent rule (the hardware band overlaps the model's phase range) but the model's mean over the boot "
        "delays misses the band: consistent with the hardware number, not agreement. Its detail gives each consistent "
        "point's acceptance window (half the band plus half the model's phase range, as a % of the hardware number) and the "
        "mean rule's verdict. A check is pass-conditional:#<issue> when it passes only through a model choice with no "
        "hardware reference, tracked in that issue. A Thar0 check passes when the model's count lies inside the console's minimum..maximum "
        "over its runs. A row's status is fail when any of its checks fails, pass when a check other than its fit data and "
        "its guards passes and none passes only weakly (then it takes that weak result), fit only when only its fit data passes, model-choice when a model-choice row has only guards, "
        "and otherwise the gates of its pending checks.",
        "",
        "| Basis | Meaning | Rows |",
        "|---|---|---|",
    ]
    out += [f"| {b} | {meaning} | {count[b]} |" for b, (_, meaning) in BASES.items()]
    out += ["", "| Status | Meaning | Rows |", "|---|---|---|"]
    for s, n in sorted(statuses(rows, found).items()):
        meaning = status_meaning(s) or "no check decided the row: " + "; ".join(
            f"{g[8:]}: {gates[g]['source']}" for g in s.split() if g in gates)
        out.append(f"| {s} | {cell(meaning)} | {n} |")
    groups = {}
    for row in rows:
        if row["basis"] != "legacy":
            groups.setdefault(row["id"].split(".")[0], []).append(row)
    out += ["", "## Behaviors"]
    for group, members in groups.items():
        out += ["", f"### {group}", "", "| Behavior | Value | Basis | Reference | Checks | Result | Code | Note |",
                "|---|---|---|---|---|---|---|---|"]
        for r in members:
            out.append(f"| `{r['id']}` | {value_cell(r)} | {r['basis']} | {cell(r['reference'])} | "
                       f"{checks_cell(r, found)} | {cell(result_cell(r, found))} | {code_cell(r)} | {cell(r['note'])} |")
    unbuilt = [r for r in rows if not_built(r)]
    out += ["", "## Not built", ""] + ([
            "The code does not use these rows' values. Each says what the code does instead; their checks measure that code.", "",
            "| Behavior | Value | Basis | What the code does instead | Checks |", "|---|---|---|---|---|"]
            if unbuilt else ["None: the code reads each value or implements each rule."])
    for r in unbuilt:
        out.append(f"| `{r['id']}` | {value_cell(r)} | {r['basis']} | {cell(r['code'][len(NOT_BUILT):])} | "
                   f"{cell('; '.join(result_word(c, found) for c in r['verify'].split()))} |")
    out += ["", "## Legacy costs in today's core", "",
            "Each row is a constant that today's core still charges. `tools/n64-timing/literal-allowlist.tsv` pins the literal "
            "at its code site to the row, so the code and this table cannot disagree. The plan unit in the note replaces the cost "
            "and deletes the row.", "",
            "| Behavior | Value | Code site | Checks | Result | Note |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["basis"] == "legacy":
            out.append(f"| `{r['id']}` | {value_cell(r)} | {cell(r['reference'])} | "
                       f"{' '.join(check_cell(c) for c in r['verify'].split())} | {cell(result_cell(r, found))} | {cell(r['note'])} |")
    out += ["", "## Check results", "",
            f"One line per check a behavior names, from `{RESULTS}` ({cell(results_source(found))}).", "",
            "| Check | Result | Detail |", "|---|---|---|"]
    for cid, (result, detail) in sorted(found.items()):
        if cid != "#source":
            out.append(f"| `{cid}` | {result} | {cell(detail)} |")
    out += ["", "## Checks", "",
            "From `tools/n64-timing/checks.tsv`. A `:*` row names a suite whose expected file defines every check under its prefix.", "",
            "| Check | Runner | Target | Selector | Expectation | Source |", "|---|---|---|---|---|---|"]
    for c in checks:
        out.append(f"| `{c['id']}` | {c['runner']} | {cell(c['target'])} | {cell(c['selector'])} | {cell(c['expect'])} | {cell(c['source'])} |")
    return "\n".join(out) + "\n"


def results_source(found):
    return found.get("#source", ("", ""))[1]


WALL_BUDGET = "tools/n64-timing/mmbench/wall-budget.tsv"
BUDGET_S = 120
TOOLS_BENCH = (
    "mm-decomp-60fps `tools/bench` (untracked in the checkout at 56fa21dd) still runs `ares` from PATH "
    "through `tools/ares/ares-headless.sh` and records the upstream ares revision, and its BENCH build still pins "
    "`func_80173B48` (`src/code/game.c`, `tools/bench/README.md`). The fork measures MM with its own "
    "`tools/n64-timing/mmbench` instead, on the retail NTSC-U 1.0 ROM (mmbench.py checks MD5 {md5}), where "
    "`func_80173B48` is the unpinned retail code. Per-behavior provenance is in `docs/spec/mm-bench.md`.")


def found_result(found, cid):
    return found.get(cid, ("missing", ""))


def destination(root, found):
    """The map #1 Destination items as (item, result, evidence)."""
    det, stepcap = found_result(found, "det"), found_result(found, "stepcap")
    walls = tsv_rows(Path(root) / WALL_BUDGET)
    slow = max(walls, key=lambda r: float(r["wall_s"]))
    filesel = [(c, found_result(found, c)) for c in ("mm:filesel-empty", "mm:filesel-named")]
    md5 = re.search(r'ROM_MD5 = "(\w+)"', (Path(root) / "tools/n64-timing/mmbench/mmbench.py").read_text(encoding="utf-8"))
    return [
        ("Timing is bit-deterministic across runs", "pass" if det[0] == stepcap[0] == "pass" else "fail",
         f"`det` {det[0]}: {det[1]}; `stepcap` {stepcap[0]}: {stepcap[1]}"),
        ("A 600-frame MM bench run takes <= 2 min", "pass" if float(slow["wall_s"]) <= BUDGET_S else "fail",
         f"slowest scene {slow['run']} {float(slow['wall_s']):g} s of {BUDGET_S} s; "
         + ", ".join(f"{r['run']} {float(r['wall_s']):g}" for r in walls) + f" s ({WALL_BUDGET}: {slow['source']})"),
        ("MM file select (#11): empty files <= 1.05 and named files 1.90-2.10 fields per game frame, both must pass",
         "pass" if all(r[0] == "pass" for _, r in filesel) else "fail",
         "; ".join(f"`{c}` {r[0]}: {r[1]}" for c, r in filesel)),
        ("MM bench integration: point `tools/bench` at the fork, remove the `func_80173B48` pin", "not done",
         TOOLS_BENCH.format(md5=md5.group(1) if md5 else "?")),
    ]


def render_closure(root, rows, checks, found):
    gates = {c["id"]: c for c in checks if c["runner"] == "pending"}
    by_status = {}
    for r in rows:
        by_status.setdefault(row_status(r, found), []).append(r)
    count = statuses(rows, found)
    out = [
        f"<!-- GENERATED by tools/n64-timing/behaviors.py from {TABLE}, {CHECKS}, {RESULTS} and {WALL_BUDGET}. "
        "A draft for a comment on map #1; not posted. -->",
        "",
        "# Map #1 closure (draft)",
        "",
        f"The spec is `{SPEC}`: {len(rows)} behaviors, each with a basis, a reference, the checks that decide it and their "
        f"results ({cell(results_source(found))}). "
        + ", ".join(f"{n} {s}" for s, n in sorted(count.items())) + ". "
        + (f"{len(by_status.get('not-built', []))} behaviors are not built: the code does not use their value ("
           + ", ".join(f"`{r['id']}`" for r in by_status.get("not-built", [])) + "). Behaviors not built says what the code "
           "does instead." if by_status.get("not-built") else "Every behavior is built: the code reads each value or implements each rule."),
        "",
        "## Destination",
        "",
        "| Item | Result | Evidence |",
        "|---|---|---|",
    ]
    out += [f"| {item} | **{result}** | {cell(evidence)} |" for item, result, evidence in destination(root, found)]
    failing = sorted(c for c, (result, _) in found.items() if result == "fail")
    out += ["", "## Failing checks", "",
            "Every check whose result is fail, with its residual, and the rows that name it.", "",
            "| Check | Detail | Rows (verify) | Rows (fit from) |", "|---|---|---|---|"]
    for c in failing:
        verify = [r["id"] for r in rows if c in (x for x, _ in verify_checks(r))]
        fit = [r["id"] for r in rows if c in r["fit-from"].split()]
        out.append(f"| `{c}` | {cell(found[c][1])} | {' '.join(f'`{x}`' for x in verify) or '-'} | "
                   f"{' '.join(f'`{x}`' for x in fit) or '-'} |")
    weak = sorted(c for c, (result, _) in found.items() if WEAK.match(result))
    results_count = {}
    for c, (result, _) in found.items():
        if c != "#source":
            kind = result if result in ("pass", "fail") or WEAK.match(result) else "pending"
            results_count[kind] = results_count.get(kind, 0) + 1
    out += ["", "## Checks that pass only weakly", "",
            "Check results: " + ", ".join(f"{n} {k}" for k, n in sorted(results_count.items())) + ". "
            "A weak pass counts apart from pass. consistent-only: a point passes its consistent rule while the model's mean "
            "misses the band, so it is consistent with the hardware number, not agreement. pass-conditional:#<issue>: the "
            "pass rests on a model choice with no hardware reference.", ""]
    if weak:
        out += ["| Check | Result | Detail | Rows (verify) | Rows (fit from) |", "|---|---|---|---|---|"]
    else:
        out.append("None.")
    for c in weak:
        verify = [r["id"] for r in rows if c in (x for x, _ in verify_checks(r))]
        fit = [r["id"] for r in rows if c in r["fit-from"].split()]
        out.append(f"| `{c}` | {found[c][0]} | {cell(found[c][1])} | {' '.join(f'`{x}`' for x in verify) or '-'} | "
                   f"{' '.join(f'`{x}`' for x in fit) or '-'} |")
    out += ["", "## Behaviors not built", ""] + ([
            "The code does not use these rows' values, so no check result says anything about them.", "",
            "| Behavior | Basis | Value | What the code does instead |", "|---|---|---|---|"]
            if by_status.get("not-built") else ["None."])
    for r in by_status.get("not-built", []):
        out.append(f"| `{r['id']}` | {r['basis']} | {value_cell(r)} | {cell(r['code'][len(NOT_BUILT):])} |")
    out += ["", "## Rows whose checks fail", "", "| Behavior | Basis | Failing checks |", "|---|---|---|"]
    for r in by_status.get("fail", []):
        bad = [c for c, _ in verify_checks(r) if found_result(found, c)[0] == "fail"]
        out.append(f"| `{r['id']}` | {r['basis']} | {cell('; '.join(f'`{c}`: {found[c][1]}' for c in bad))} |")
    out += ["", "## Model choices that only guards check", "",
            "No published value exists for these, and no check measures them: their checks are guards that passed.", "",
            "| Behavior | Guards |", "|---|---|"]
    for r in by_status.get("model-choice", []):
        out.append(f"| `{r['id']}` | {' '.join(f'`{c}`' for c, _ in verify_checks(r))} |")
    out += ["", "## Rows checked only against their fit data", "", "| Behavior | Fit from |", "|---|---|"]
    for r in by_status.get("fit only", []):
        out.append(f"| `{r['id']}` | {' '.join(f'`{c}`' for c in r['fit-from'].split())} |")
    out += ["", "## Pending rows and their gates", "",
            "| Behavior | Basis | Gate | What closes it |",
            "|---|---|---|---|"]
    for s, members in sorted(by_status.items()):
        if status_meaning(s):
            continue
        for r in members:
            out.append(f"| `{r['id']}` | {r['basis']} | {', '.join(g[8:] for g in s.split())} | "
                       f"{cell('; '.join(gates[g]['source'] for g in s.split() if g in gates))} |")
    out += ["", "## Pending checks inside rows that pass, fail or are fit only", "",
            "These checks are gated too, but another check already decides their row.", "",
            "| Behavior | Status | Pending checks |", "|---|---|---|"]
    for r in rows:
        s = row_status(r, found)
        pend = [c for c, _ in verify_checks(r) if (c if c.startswith("pending:") else found_result(found, c)[0]).startswith("pending:")]
        if status_meaning(s) and s != "not-built" and pend:
            out.append(f"| `{r['id']}` | {s} | " + "; ".join(
                check_cell(c) if c.startswith("pending:") else f"`{c}` pending ({found[c][0][8:]})" for c in pend) + " |")
    return "\n".join(out) + "\n"


def generated(root):
    errors, rows, checks, sites = validate(root)
    errors += calibration_errors(root, rows, checks)
    found = load_results(root, rows, checks, errors)
    return errors, {HEADER: render_header(rows), SPEC: render_spec(rows, checks, found),
                    CLOSURE: render_closure(root, rows, checks, found),
                    INVENTORY: render_inventory(root, rows, checks, found)}


def calibration_errors(root, rows, checks):
    """The calibration inventory's rules: no row waits on calibration #16 without a kit question that
    measures it, every question names a kit ROM (or says why none exists), a valid rule, and only
    rows, checks or issues in its closes column; a row's hw check is one its question closes."""
    errors = []
    kit = kit_module(root)
    qs = {q["id"]: q for q in question_rows(root)}
    _, explicit, _, suite_files = load_checks(root, [])
    ids = {r["id"] for r in rows}
    for r in rows:
        where = f"{TABLE}:{r['line']}"
        for cid, _ in verify_checks(r):
            if cid == "pending:calibration-16":
                errors.append(f"{where}: `{r['id']}` waits on pending:calibration-16 with no kit test. Name the "
                              f"hw:<question> that measures it on the console; add the question to "
                              f"tools/n64-timing/calibration/questions.tsv and its points to a kit ROM if none does.")
            elif cid.startswith("hw:"):
                q = qs.get(cid[3:])
                if q is None:
                    continue
                if q["kit"] not in kit.KIT_ROMS:
                    errors.append(f"{where}: `{r['id']}` names {cid}, whose kit is `{q['kit']}`, not an in-repo kit ROM "
                                  f"({', '.join(kit.KIT_ROMS)}). A row's hardware check needs a ROM ingestion can compare.")
                if r["id"] not in q["closes"].split():
                    errors.append(f"{where}: `{r['id']}` names {cid}, but the question's closes column does not list it. "
                                  f"Add `{r['id']}` there.")
    for q in qs.values():
        where = f"tools/n64-timing/calibration/questions.tsv:{q['line']}"
        if q["kit"] not in kit.KIT_ROMS and not q["kit"].startswith(("ext:", "none: ")):
            errors.append(f"{where}: kit `{q['kit']}` is not a kit ROM ({', '.join(kit.KIT_ROMS)}), `ext:<rom>` or "
                          f"`none: <reason>`")
        if not kit.RULE.match(q.get("rule", "")) or (q["kit"] in kit.KIT_ROMS) == (q.get("rule") == "-"):
            errors.append(f"{where}: rule `{q.get('rule')}` must be exact or range:abs|rel:<tolerance> for a kit ROM "
                          f"question, `-` otherwise")
        for c in q["closes"].split():
            if c != "-" and c not in ids and not check_defined(c, explicit, suite_files) and not re.match(r"^#\d+$", c):
                errors.append(f"{where}: closes `{c}`, which is no behavior row, check or #issue")
    return errors


def question_links(root):
    """Behavior row or check id -> the questions that close it."""
    out = {}
    for q in question_rows(root):
        for c in q["closes"].split():
            out.setdefault(c, []).append(q["id"])
    return out


def render_inventory(root, rows, checks, found):
    qs = question_rows(root)
    links = question_links(root)
    kit = kit_module(root)
    _, explicit, _, suite_files = load_checks(root, [])
    asked = lambda key: ", ".join(f"`hw:{q}`" for q in links.get(key, [])) or "**no kit question**"  # noqa: E731
    out = [
        f"<!-- GENERATED by tools/n64-timing/behaviors.py from tools/n64-timing/calibration/questions.tsv, {TABLE}, "
        f"{CHECKS} and {RESULTS}. Do not edit; behaviors.py --check fails on any manual change. -->",
        "",
        "# Calibration inventory",
        "",
        "Every question a console run can answer for the timing model (calibration #16), the kit ROM that measures "
        "it, and the spec rows and checks its answer closes. [hardware-run.md](hardware-run.md) is the procedure. "
        "A question's result is its `hw:<id>` check: pending:calibration-16 until "
        "`tools/n64-timing/calibration/ingest.py` stores a console capture, then pass when the console's values "
        "fall in the fork's range over its boot delays under the question's rule, fail otherwise. "
        f"Kit ROMs: {', '.join(f'`{k}`' for k in kit.KIT_ROMS)}. `ext:` names a ROM outside the repository "
        "that the procedure runs and a person compares; `none:` is a question with no kit ROM yet.",
        "",
        "## Questions",
        "",
        "| Question | Asks | Decided by | Kit ROM | Points | Output | Rule | Closes | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in qs:
        res = found.get(f"hw:{q['id']}", ("missing", ""))
        output = f"{q['metric']} per point" if q["metric"] != "-" else "-"
        out.append(f"| `{q['id']}` | {cell(q['question'])} | {cell(q['decides'])} | {cell(q['kit'])} | "
                   f"{cell(q['points'])} | {cell(output)} | {cell(q['rule'])} | "
                   f"{' '.join(f'`{c}`' for c in q['closes'].split())} | {res[0]} |")
    status = {r["id"]: row_status(r, found) for r in rows}
    sections = [
        ("Rows pending calibration #16", "Rows whose checks wait on the console run.",
         [r for r in rows if "pending:calibration-16" in status[r["id"]]]),
        ("Fit-only rows", "Rows whose only passing checks are their own fit data.",
         [r for r in rows if status[r["id"]] == "fit only"]),
        ("Model-choice rows", "Rows with no published value: the console decides the choice.",
         [r for r in rows if r["basis"] == "model-choice"]),
        ("Rows pending a report-only check", "Rows whose deciding check reports a number and asserts none.",
         [r for r in rows if "pending:report-only" in status[r["id"]]]),
    ]
    for title, intro, chosen in sections:
        out += ["", f"## {title}", "", f"{intro} {len(chosen)} rows, {sum(1 for r in chosen if r['id'] in links)} "
                f"with a kit question.", "", "| Behavior | Status | Checks | Question |", "|---|---|---|---|"]
        out += [f"| `{r['id']}` | {status[r['id']]} | {cell(' '.join(r['verify'].split()))} | {asked(r['id'])} |"
                for r in chosen]
    weak = [(c, found[c]) for c in sorted(found) if c != "#source" and not c.startswith("hw:") and
            (found[c][0] == "fail" or WEAK.match(found[c][0]))]
    out += ["", "## Failing and weakly passing checks", "",
            f"Checks that fail, pass only consistent with the console, or pass on a model choice. Each residual's "
            f"cause is open until a console measurement isolates it. {len(weak)} checks, "
            f"{sum(1 for c, _ in weak if c in links)} with a kit question.", "",
            "| Check | Result | Detail | Question |", "|---|---|---|---|"]
    out += [f"| `{c}` | {r} | {cell(d[:200])} | {asked(c)} |" for c, (r, d) in weak]
    gaps = [q for q in qs if q["kit"].startswith(("ext:", "none"))]
    out += ["", "## Questions without an in-repo kit ROM", "",
            "These run outside the kit's mechanical comparison: an external ROM the procedure names, or no ROM yet.",
            "", "| Question | Kit | Closes |", "|---|---|---|"]
    out += [f"| `{q['id']}` | {cell(q['kit'])} | {' '.join(f'`{c}`' for c in q['closes'].split())} |" for q in gaps]
    return "\n".join(out) + "\n"


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


def tsv_rows(path):
    lines = [l for l in Path(path).read_text(encoding="utf-8").split("\n") if l]
    return [dict(zip(lines[0].split("\t"), l.split("\t"))) for l in lines[1:]]


def text(path):
    path = Path(path)
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None


def tally(verdicts, noun):
    failed = sum(1 for v in verdicts if v != "pass")
    return ("fail" if failed else "pass"), f"{len(verdicts) - failed} of {len(verdicts)} {noun} pass"


def nemu64_result(run, row):
    base = run / "nemu64" / row["target"]
    if not (base / "tests.tsv").exists():
        return None
    selector, _, category = row["selector"].partition(" #")
    selector, _, value = selector.partition(" @")
    tests = {l.split("\t")[0]: l.split("\t")[-1] for l in (base / "tests.tsv").read_text(encoding="utf-8").split("\n")[1:] if l}
    if selector.startswith("re:"):
        names = [n for n in tests if re.search(selector[3:], n)]
    else:
        names = [n for n in selector.split("|") if n in tests]
    if not names:
        return "missing", f"no test `{selector}` in nemu64/{row['target']}/tests.tsv"
    if category:
        rows = [l.split("\t") for l in (base / "categories.tsv").read_text(encoding="utf-8").split("\n")[1:] if l]
        failed = sum(1 for r in rows if r[1] == category and r[2] in names)
        return ("fail", f"{failed} {category} values fail") if failed else ("pass", f"no {category} value fails")
    if value:
        rows = [l.split("\t") for l in (base / "values.tsv").read_text(encoding="utf-8").split("\n")[1:] if l]
        picked = [r for r in rows if r[1] in names and value in r[2]]
        if not picked:
            return "missing", f"no `{value}` value of {names[0]}"
        return tally([r[3] for r in picked], "values")
    return tally([tests[n] for n in names], "tests")


def suite_runs(run, pattern, label):
    files = sorted(run.glob(pattern))
    if not files:
        return None
    verdicts, parts = [], []
    for f in files:
        m = re.search(rf"{label}: (PASS|FAIL)[^\n]*", f.read_text(encoding="utf-8", errors="replace"))
        verdicts.append("pass" if m and m.group(1) == "PASS" else "fail")
        parts.append(f"{f.stem}: {m.group(0) if m else 'no verdict line'}")
    return tally(verdicts, "runs")[0], "; ".join(parts)


def phase_text(r):
    """A bench value over the boot delays: the one value when every delay agrees, else its range."""
    if r["min"] == r["max"]:
        return r["min"]
    return f"{r['min']}..{r['max']} median {r['median']} mean {r['mean']}"


def window_text(r):
    """A consistent row's acceptance window and the mean rule's verdict (bench README, Phase)."""
    return f"window ±{r['window_pct']}%, mean rule {r['mean_verdict']}" if r.get("window_pct", "-") != "-" else ""


def bench_label(r):
    """The row's verdict, recomputed from its phase range and mean with report.py's label, so a
    results.tsv that calls a consistent-only point pass cannot pass it here."""
    from romgen.suites.bench.report import label
    if r["kind"] != "check" or r["min"] == "None":
        return r["verdict"]
    return label(r, float(r["min"]), float(r["max"]), float(r["mean"]))


def bench_tally(verdicts):
    """fail over any weak pass over pass: one consistent-only point keeps the check from passing."""
    for v in verdicts:
        if v != "pass" and not WEAK.match(v):
            return "fail"
    weak = [v for v in verdicts if WEAK.match(v)]
    return weak[0] if weak else "pass"


def bench_result(run, row):
    if not (run / "bench" / "results.tsv").exists():
        return None
    wanted = dict(p.split("=", 1) for p in row["selector"].split() if "=" in p)
    picked = [{**r, "verdict": bench_label(r)} for r in tsv_rows(run / "bench" / "results.tsv")
              if r["rom"] == row["target"] and all(r.get(k) == v for k, v in wanted.items())]
    if not picked:
        return None
    checked = [r for r in picked if r["kind"] == "check"]
    shown = checked if checked else picked
    detail = "; ".join(f"{r['point']} {r['metric']} {phase_text(r)} (expected {r['expected']}"
                       + (f", {r['lo']}..{r['hi']}, {r['rule']}" if r["lo"] != "-" else "")
                       + (f", {window_text(r)}" if window_text(r) else "") + f") {r['verdict']}" for r in shown[:3])
    if len(shown) > 3 and not checked:
        detail += f"; {len(shown) - 3} more report points"
    elif len(shown) > 3:
        failing = [r for r in shown if r["verdict"] != "pass"]
        counts = {}
        for r in shown:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        detail = f"{counts.pop('pass', 0)} of {len(shown)} points pass" + "".join(f", {n} {v}" for v, n in sorted(counts.items())) + \
            (f"; first not passing {failing[0]['point']} {failing[0]['metric']} {phase_text(failing[0])} "
             f"(expected {failing[0]['expected']}, {failing[0]['lo']}..{failing[0]['hi']}) {failing[0]['verdict']}" if failing else "")
        windows = [f"{r['point']} {window_text(r)}" for r in shown if window_text(r)]
        if windows:
            detail += "; " + "; ".join(windows)
    return bench_tally([r["verdict"] for r in checked]) if checked else "report", detail


def thar0_result(run, row):
    if not (run / "thar0" / "compare.tsv").exists():
        return None
    picked = [r for r in tsv_rows(run / "thar0" / "compare.tsv") if r["id"] == row["target"]]
    if not picked:
        return None
    r = picked[0]
    model = float(r["model_buf"].split("/")[1])
    lo, avg, hi = (float(x) for x in r["hw_buf"].split("/"))
    ok = lo <= model <= hi
    return ("pass" if ok else "fail"), (f"model {model:g} vs console {avg:g} ({lo:g}..{hi:g}), "
                                        f"{(model - avg) / avg * 100:+.2f}%")


def rdpstat_result(run, row):
    path = run / "rdpstat" / row["target"] / "values.tsv"
    if not path.exists():
        return None
    selector = row["selector"]
    picked = [r for r in tsv_rows(path) if selector == "-" or r["test"].startswith(selector)]
    if not picked:
        return "missing", f"no test `{selector}` in rdpstat/{row['target']}"
    result, detail = tally([r["result"] for r in picked], "tests")
    failing = sorted({r["test"] for r in picked if r["result"] != "pass"})
    return result, detail + (f"; failing: {', '.join(failing)}" if failing else "")


def snapper_result(run, row):
    summary = text(run / "snapper" / "summary.txt")
    if summary is None:
        return None
    counts = re.findall(rf"^snapper:{re.escape(row['target'])} (.*): (\d+)/(\d+) match$", summary, re.M)
    if not counts:
        return None
    return ("pass" if all(a == b for _, a, b in counts) else "fail"), "; ".join(f"{d}: {a}/{b} match" for d, a, b in counts)


def ctest_result(run, row):
    log = text(run / "ctest.txt")
    m = re.search(rf"Test +#\d+: {re.escape(row['id'])} \.+\** *(\w+)", log or "")
    return (("pass" if m.group(1) == "Passed" else "fail"), f"ctest {m.group(1)}") if m else None


def noise_result(run, row):
    m = re.search(rf"^{re.escape(row['id'])} (pass|fail)$", text(run / "noise" / "summary.txt") or "", re.M)
    return (m.group(1), "noise/summary.txt") if m else ctest_result(run, row)


def gen_result(run, row):
    log = text(run / "behaviors.txt")
    if log is None:
        return None
    ok = all(line in log for line in ("behaviors.py: check: ok", "lint-literals: ok")) and "FAILED" not in log \
        and all(re.search(rf"^{tool}: self-test: \d+ cases, 0 failed$", log, re.M) for tool in ("behaviors.py", "pidma-replay"))
    return ("pass" if ok else "fail"), "behaviors.py --check and --self-test, lint-literals.py, pidma-replay.py --self-test"


MM_SCENES = {"file-select": "filesel", "south-clock-town": "sct"}


def mm_result(run, row):
    path = run / "mmbench" / "summary.tsv"
    if not path.exists():
        return None
    summary = {r["scene"]: r for r in tsv_rows(path)}
    m = re.match(r"filesel_check\.py row=(\w+)", row["selector"])
    if m:
        spec = importlib.util.spec_from_file_location("filesel_check", Path(__file__).resolve().parent / "mmbench/filesel_check.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        index = {"empty": 0, "options": 1, "named": 2}[m.group(1)]
        _, _, scene, evaluate = module.ROWS[index]
        if scene not in summary:
            return None
        ok, measured = evaluate(summary[scene])
        return ("pass" if ok else "fail"), f"{scene}: {measured}"
    scene = summary.get(MM_SCENES.get(row["selector"], row["selector"]))
    return ("report", f"{scene['scene']}: {scene['fields_per_gframe_mean']} fields per game frame, "
                      f"{scene['rsp_busy_clocks_per_field_mean']} RSP busy clocks per field") if scene else None


def pidma_result(run, row):
    m = re.search(r"^pidma: (PASS|FAIL): (.*)$", text(run / "pidma" / "summary.txt") or "", re.M)
    return (m.group(1).lower(), m.group(2)) if m else None


READERS = {"nemu64": nemu64_result, "det": lambda run, row: suite_runs(run, "det-*.txt", "determinism"),
           "stepcap": lambda run, row: suite_runs(run, "stepcap-*.txt", "stepcap"),
           "bench": bench_result, "thar0": thar0_result, "rdpstat": rdpstat_result, "snapper": snapper_result,
           "unit": ctest_result, "noise": noise_result, "gen": gen_result, "mm": mm_result, "pidma": pidma_result,
           "harness": rdpstat_result}
ROM_FILES = {"bench": "./bench/boot-*/bench-{}.z64", "rdpstat": "./rdpstat-{}.z64", "snapper": "./snapper-{}.z64",
             "harness": "./rdpstat-{}.z64"}
RESULT = re.compile(r"^(pass|fail|consistent-only|pass-conditional:#\d+|pending:[a-z0-9-]+)$")
#A check that passes, but weakly: consistent with the hardware number at some phase while the model's mean misses it,
#or passing only through a model choice with no hardware reference (bench README, Phase). Never counted as pass.
WEAK = re.compile(r"^(consistent-only|pass-conditional:#\d+)$")
CONDITION = re.compile(r"^(-|#\d+)$")


def gate_for(row, explicit, suite_files, built):
    """The gate that keeps a check from deciding anything, or None when it can run and decide. A
    hardware check's reader returns its own gate (calibration/kit.py result)."""
    if row["runner"] == "hw":
        return None
    if not decides(row["id"], explicit, suite_files):
        return "pending:report-only"
    pattern = ROM_FILES.get(row["runner"])
    if pattern and not fnmatch.filter(built, pattern.format(row["target"])):
        return "pending:no-rom"
    return None


def kit_module(root):
    spec = importlib.util.spec_from_file_location("calibration_kit", Path(root) / KIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def question_rows(root):
    path = Path(root) / "tools/n64-timing/calibration/questions.tsv"
    if not path.exists():
        return []
    lines = [l for l in path.read_text(encoding="utf-8").split("\n") if l]
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t")), line=n) for n, l in enumerate(lines[1:], 2)]


def referenced_checks(rows, checks, root=None):
    """Every check a behavior names, every harness check (it guards the measuring tools, not a behavior),
    and every hardware question (each one is a result of the calibration run, named by a row or not)."""
    named = {c.lstrip("~") for r in rows for c in (r["verify"] + " " + r["fit-from"]).split()}
    hw = {f"hw:{q['id']}" for q in question_rows(root)} if root else set()
    return sorted(named | hw | {c["id"] for c in checks if c["runner"] == "harness"})


def results(root, run):
    """Reads one standing run (see tools/n64-timing/README.md) into one result per referenced check."""
    errors, rows, checks, _ = validate(root)
    _, explicit, _, suite_files = load_checks(root, [])
    run = Path(run)
    built = set((text(run / "rom-sha256.txt") or "").split())
    out = []
    kit = kit_module(root)
    readers = dict(READERS, hw=lambda run, row: kit.result(root, run, row["target"]))
    for cid in referenced_checks(rows, checks, root):
        if cid.startswith("pending:"):
            continue
        prefix, _, rest = cid.partition(":")
        row = explicit.get(cid) or {"id": cid, "runner": prefix, "target": rest, "selector": "-", "expect": "suite"}
        measured = readers[row["runner"]](run, row)
        gate = gate_for(row, explicit, suite_files, built)
        if gate:
            result, detail = gate, (measured[1] if measured else "")
        elif measured is None or measured[0] in ("missing", "report"):
            result, detail = "not-run", measured[1] if measured else f"no {row['runner']} output for it in {run_label(run)}"
            errors.append(f"{cid}: {detail}. Rerun the standing set into {run}, or fix the check's target and selector.")
        else:
            result, detail = measured
        out.append((cid, result, detail))
    return errors, out


def run_label(path):
    """A run directory without the local part of its path: its last two components."""
    return "/".join(Path(path).resolve().parts[-2:])


def write_results(root, run, out):
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = f"# standing run {run_label(run)} on {commit or 'an unknown commit'}"
    lines = [head, "check\tresult\tdetail"] + [f"{c}\t{r}\t{d}" for c, r, d in out]
    (Path(root) / RESULTS).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def load_results(root, rows, checks, errors):
    path = Path(root) / RESULTS
    if not path.exists():
        errors.append(f"{RESULTS} is missing. Run tools/n64-timing/behaviors.py --results <standing run dir>.")
        return {}
    text_lines = [l for l in path.read_text(encoding="utf-8").split("\n") if l]
    lines = [l for l in text_lines if not l.startswith("#")]
    found = {"#source": ("", text_lines[0][2:] if text_lines and text_lines[0].startswith("# ") else "")}
    gates = {c["id"] for c in checks if c["runner"] == "pending"}
    for number, line in enumerate(lines[1:], 2):
        cid, result, detail = (line.split("\t") + ["", ""])[:3]
        found[cid] = (result, detail)
        if not RESULT.match(result):
            errors.append(f"{RESULTS}: `{cid}` has result `{result}`. A result is pass, fail or pending:<gate>; "
                          f"rerun the check, or name the gate that keeps it from running.")
        elif result.startswith("pending:") and result not in gates:
            errors.append(f"{RESULTS}: `{cid}` is {result}, which is not a pending row in {CHECKS}. Add the gate there.")
    wanted = [c for c in referenced_checks(rows, checks, root) if not c.startswith("pending:")]
    for cid in wanted:
        if cid not in found:
            errors.append(f"{RESULTS}: check `{cid}` has no result. Rerun tools/n64-timing/behaviors.py --results "
                          f"<standing run dir>; every check a behavior names needs a result or a gate.")
    for cid in sorted(set(found) - set(wanted) - {"#source"}):
        errors.append(f"{RESULTS}: `{cid}` is not a check any behavior names. Rerun --results to drop it.")
    return found


def row_status(row, found):
    """not-built, pass, fail, consistent-only, pass-conditional:#<issue>, fit only, model-choice or pending:<gates> for
    one behavior, from its code column and its checks' results. A guard can fail the row but never pass it. A weak
    pass (WEAK) of any check other than the fit data keeps the row from passing."""
    if not_built(row):
        return "not-built"
    fit_from = set(row["fit-from"].split())
    res = [(c, guard, c if c.startswith("pending:") else found.get(c, ("missing", ""))[0]) for c, guard in verify_checks(row)]
    if any(r == "fail" for _, _, r in res):
        return "fail"
    weak = [r for c, guard, r in res if WEAK.match(r) and not guard and c not in fit_from]
    if weak:
        return weak[0]
    passed = [c for c, guard, r in res if r == "pass" and not guard]
    if any(c not in fit_from for c in passed):
        return "pass"
    if passed:
        return "fit only"
    undecided = sorted({r for _, guard, r in res if not guard})
    return " ".join(undecided) if undecided else "model-choice"


def self_test(root):
    """Copies the inputs to a scratch tree, breaks each rule once, and checks the failure names its fix."""
    root = Path(root)
    work = Path(tempfile.mkdtemp(prefix="behaviors-self-test-"))
    try:
        shutil.copytree(root / "ares/n64", work / "ares/n64")
        shutil.copytree(root / "tools/n64-timing", work / "tools/n64-timing", ignore=shutil.ignore_patterns("__pycache__"))
        (work / SPEC).parent.mkdir(parents=True)
        (work / INVENTORY).parent.mkdir(parents=True)
        for rel in (SPEC, RESULTS, CLOSURE, INVENTORY):
            shutil.copy(root / rel, work / rel)

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

        def unread_row(code):
            return lambda t: t.rstrip("\n") + f"\npi.self-test-unread\t1\tpclk\tmeasured\tself-test\tunit:timeline\t\t\t{code}\n"

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
            ("a row waiting on calibration #16 with no kit test", TABLE, row_field("cpu.dcb", "verify", "pending:calibration-16"),
             "waits on pending:calibration-16 with no kit test. Name the hw:<question>"),
            ("a hardware check its question does not close", TABLE, row_field("ri.read-hit", "verify", "unit:ri-cost-table hw:dcb"),
             "but the question's closes column does not list it"),
            ("a row's hardware check without a kit ROM", TABLE, row_field("ri.read-hit", "verify", "unit:ri-cost-table hw:ri-priority"),
             "not an in-repo kit ROM"),
            ("a question closing an unknown id", "tools/n64-timing/calibration/questions.tsv",
             lambda t: t.replace("\tcpu.dcb\t", "\tcpu.no-such-row\t", 1), "closes `cpu.no-such-row`, which is no behavior row"),
            ("an inferred row without its inference", TABLE, row_field("cpu.ifill-stall", "note", ""),
             "inferred row `cpu.ifill-stall` has no note. State the inference"),
            ("removing a reference", TABLE, row_field("ri.read-hit", "reference", ""), "has no reference. Cite the hardware reference"),
            ("an unknown check id", TABLE, row_field("ri.read-hit", "verify", "bench:no-such-rom"), "check `bench:no-such-rom` is not defined in tools/n64-timing/checks.tsv. Add a row there"),
            ("an empty check list", TABLE, row_field("ri.write-hit", "verify", ""), "has no check. Name the check"),
            ("adding a timing literal", "ares/n64/cpu/memory.cpp", lambda t: t + new_function, "timing literal [7, 2, 14] in `step(7 * 2);`. Add a row to ares/n64/timing/behaviors.tsv"),
            ("changing a legacy literal", "ares/n64/pi/bus.hpp", lambda t: t.replace("thread.step(pclk(250));", "thread.step(pclk(251));", 1), "If the code no longer charges this cost, delete the entry"),
            ("changing a legacy row's value", TABLE, row_field("legacy.pi.cart-read", "value", "251"), "Make ares/n64/timing/behaviors.tsv and the code agree"),
            ("referencing a value-less row", "ares/n64/cpu/memory.cpp", lambda t: t + "\nstatic auto selfTestRule = Timing::Behavior::RiArbitration;\n", "which has no numeric value"),
            ("referencing an unknown row", "ares/n64/cpu/memory.cpp", lambda t: t + "\nstatic auto selfTestRule = Timing::Behavior::RiNoSuchRow;\n", "matches no row"),
            ("a model choice without a reason", TABLE, row_field("ri.rank.vi", "reference", ""), "or mark the basis model-choice and state the reason"),
            ("an inexact time value", TABLE, row_field("ri.read-hit", "value", "10.5"), "is not a whole number of 750 MHz units"),
            ("a fit row without fit-from", TABLE, row_field("rdp.span-line-gap", "fit-from", ""), "has no fit-from. Name the checks"),
            ("a fit row checked only by its fit data", TABLE, row_field("rdp.span-line-gap", "note", "Applied to fill and copy spans"),
             "so a pass verifies the arithmetic, not the model. Add a check that decides it"),
            ("a fit row whose other check only reports", TABLE, row_field("rdp.primitive-base", "note", "One rectangle size"),
             "so a pass verifies the arithmetic, not the model"),
            ("verify-is-fit beside an independent check", TABLE,
             row_field("rdp.span-line-gap", "verify", "thar0:alpha-fail-1cycle thar0:alpha-fail-2cycle thar0:zcmp"),
             "but `thar0:zcmp` decides it from other data. Remove the verify-is-fit note"),
            ("det named without ~", TABLE, row_field("ri.request-latency", "verify", "det ~stepcap"),
             "Write `~det` so it guards the row without passing it"),
            ("a gate written as a guard", TABLE,
             row_field("cpu.dcb", "verify", "~nemu64:timing/cpu-register-dependency ~pending:calibration-16"),
             "marks a gate as a guard"),
            ("only guards on a row that is not a model choice", TABLE,
             row_field("cpu.dcb", "verify", "~nemu64:timing/cpu-register-dependency"), "is a guard, so nothing decides its value"),
            ("a fit row whose only other check is a guard", TABLE,
             lambda t: row_field("rdp.span-line-gap", "note", "Applied to fill and copy spans")(
                 row_field("rdp.span-line-gap", "verify", "thar0:alpha-fail-1cycle thar0:alpha-fail-2cycle ~thar0:zcmp")(t)),
             "so a pass verifies the arithmetic, not the model"),
            ("editing the generated spec", SPEC, lambda t: t + "manual edit\n", "docs/spec/n64-timing.md differs from the generated output"),
            ("editing the closure draft", CLOSURE, lambda t: t + "manual edit\n", f"{CLOSURE} differs from the generated output"),
            ("a check with no result", RESULTS, lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("unit:timeline\t")),
             "check `unit:timeline` has no result"),
            ("a check that did not run", RESULTS, lambda t: t.replace("unit:timeline\tpass", "unit:timeline\tnot-run", 1),
             "has result `not-run`. A result is pass, fail or pending:<gate>"),
            ("a result on an undefined gate", RESULTS, lambda t: t.replace("unit:timeline\tpass", "unit:timeline\tpending:no-such-gate", 1),
             "is pending:no-such-gate, which is not a pending row"),
            ("editing the generated header", HEADER, lambda t: t.replace("= 30;", "= 31;", 1), "ares/n64/timing/behaviors.hpp differs from the generated output"),
            ("a legacy code site moving", "ares/n64/pi/bus.hpp", lambda t: "\n" + t, "Run tools/n64-timing/behaviors.py --fix-lines"),
            ("a constant no code reads", TABLE, unread_row(""), "no code reads Timing::Behavior::PiSelfTestUnread"),
            ("a constant named only in a comment", "ares/n64/timing/timeline.cpp",
             lambda t: re.sub(r"static_assert\(Timing::Behavior::ClockUnit[^\n]*", "//Timing::Behavior::ClockUnit", t),
             "no code reads Timing::Behavior::ClockUnit"),
            ("removing the code that reads a constant", "ares/n64/timing/timeline.cpp",
             lambda t: "\n".join(l for l in t.split("\n") if "ClockUnit" not in l), "no code reads Timing::Behavior::ClockUnit"),
            ("a rule that names no code", TABLE, row_field("vi.display-window", "code", ""),
             "has no constant, and it names no code that implements it"),
            ("a code pointer to a missing symbol", TABLE, row_field("vi.display-window", "code", "ares/n64/vi/vi.cpp:VI::noSuchWindow"),
             "ares/n64/vi/vi.cpp has no `VI::noSuchWindow`"),
            ("not-built on a row the code reads", TABLE, row_field("ri.read-hit", "code", "not-built: ares/n64/ri/bus.hpp:wire"),
             "so `ri.read-hit` is built there; clear its code column"),
            ("not-built that names no code", TABLE, unread_row("not-built: nothing charges it"),
             "names no ares/n64/<path>:<symbol>. Name the code that does instead"),
            ("a code column on a legacy row", TABLE, row_field("legacy.pi.cart-read", "code", "ares/n64/pi/bus.hpp:PI::writeWord"),
             "is built at its literal-allowlist code site; clear its code column"),
            ("a bench check without a phase rule", suite_file, lambda t: t.replace("\tcheck\tmean\t", "\tcheck\t-\t", 1),
             "has rule `-`; use consistent, mean, every"),
            ("a bench condition that names no issue", suite_file, lambda t: t.replace("\tcheck\tmean\t#77\t", "\tcheck\tmean\tidle-vi\t", 1),
             "has condition `idle-vi`; write `-`"),
        ]
        if landed:
            cases += [
                ("a check defined only by a landed suite file", TABLE, row_field("ri.read-hit", "verify", "bench:self-test-rom"), None),
                ("a suite file that lacks a selected row", suite_file,
                 lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("mi-memset-uncached")),
                 "selects rom=mi-memset-uncached point=vi-on metric=pclk_per_sd but"),
            ]
        failures, ran = 0, 0
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
            ran += 1
            if name == "a legacy code site moving" and ok:
                fix_lines(work)
                after = check(work)
                drift = [e for e in after if "--fix-lines" in e]
                print(f"self-test: --fix-lines repairs it: {'ok' if not drift else 'FAILED'}")
                failures += bool(drift)
                ran += 1
                shutil.copy(root / TABLE, work / TABLE)
            if restore:
                restore()
        found = {"det": ("pass", ""), "stepcap": ("pass", ""), "x:pass": ("pass", ""), "x:fail": ("fail", ""),
                 "x:pass2": ("pass", ""), "x:consistent": ("consistent-only", ""), "x:cond": ("pass-conditional:#77", "")}
        for name, row, want in [
            ("a model choice that passes only det and stepcap", ("model-choice", "~det ~stepcap", "", ""), "model-choice"),
            ("a guard that passes beside a gate", ("vendor", "~x:pass pending:calibration-16", "", ""), "pending:calibration-16"),
            ("a guard that fails", ("vendor", "~x:fail pending:calibration-16", "", ""), "fail"),
            ("a fit row with a passing guard", ("fit", "x:pass ~det", "x:pass", ""), "fit only"),
            ("a check that decides beside a guard", ("model-choice", "x:pass ~det", "", ""), "pass"),
            ("a not-built row whose check passes", ("measured", "x:pass", "", "not-built: ares/n64/pi/bus.hpp:PI::writeWord"),
             "not-built"),
            ("a consistent-only check beside a pass", ("measured", "x:pass x:consistent", "", ""), "consistent-only"),
            ("a conditional pass", ("wiki", "x:cond", "", ""), "pass-conditional:#77"),
            ("a fail beside a weak pass", ("wiki", "x:consistent x:fail", "", ""), "fail"),
            ("a fit row whose weak check is its fit data", ("fit", "x:pass x:consistent", "x:consistent", ""), "pass"),
        ]:
            got = row_status(dict(zip(("basis", "verify", "fit-from", "code"), row)), found)
            print(f"self-test: status of {name}: {'ok' if got == want else 'FAILED'}: {got} (expected {want})")
            failures += got != want
            ran += 1
        run = work / "self-test-run"
        (run / "bench").mkdir(parents=True)
        cols = ["rom", "point", "metric", "min", "median", "max", "mean", "expected", "lo", "hi", "kind", "rule", "condition",
                "verdict", "mean_verdict", "window_pct", "source"]
        stale = ["r", "p8", "m", "180.0", "189.0", "194.67", "189.0", "193", "191.07", "194.93", "check", "consistent", "-",
                 "pass", "-", "-", "s"]
        (run / "bench" / "results.tsv").write_text("\t".join(cols) + "\n" + "\t".join(stale) + "\n", encoding="utf-8")
        got = bench_result(run, {"target": "r", "selector": "point=p8"})
        ok = got is not None and got[0] == "consistent-only"
        print(f"self-test: a consistent pass whose mean misses the band, in a results.tsv that calls it pass: "
              f"{'ok' if ok else 'FAILED'}: {got} (expected consistent-only)")
        failures += not ok
        ran += 1
        print(f"behaviors.py: self-test: {ran} cases, {failures} failed")
        return failures
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fix-lines", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--results", metavar="RUN_DIR")
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
        errors, out = results(root, args.results)
        write_results(root, args.results, out)
        print(f"behaviors.py: wrote {RESULTS} ({len(out)} checks); run behaviors.py to regenerate the spec")
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
