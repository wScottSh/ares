#!/usr/bin/env python3
"""Generates the N64 timing constants and spec from ares/n64/timing/behaviors.tsv.

usage: behaviors.py                 write ares/n64/timing/behaviors.hpp, docs/spec/n64-timing.md and
                                    docs/spec/map-1-closure-draft.md
       behaviors.py --check         fail unless the table, tools/n64-timing/checks.tsv, the results,
                                    the generated files and the literal lint all agree
       behaviors.py --fix-lines     rewrite each legacy row's file:line to its current code site
       behaviors.py --results RUN_DIR
                                    write docs/spec/n64-timing-results.tsv, one result per
                                    check, from one standing run of every suite, and beside
                                    it n64-timing-fork.tsv (the fork's side of every kit
                                    question) and n64-timing-dry-run.tsv (each hw:* check
                                    after calibration/dry-run.sh on the run's calib/)
       behaviors.py --failing RUN_DIR
                                    print each suite with a check that fails or did not run in
                                    one standing run, and exit 1 if any; writes nothing
       behaviors.py --self-test     prove each --check failure fires and names its fix

The console calibration (#16): tools/n64-timing/calibration/questions.tsv lists every question a
console run answers, with the kit ROM that measures it. A row a console run decides names it as
hw:<question> in its verify column; until a capture is ingested
(tools/n64-timing/calibration/ingest.py) that check is pending:calibration-16. behaviors.py also
writes docs/calibration/inventory.md, the question table joined with every row and check the
hardware could decide.

PREHW_COMPLETE (docs/design/prehw-plan.md section 1): tools/n64-timing/calibration/blockers.tsv has
one row per open item (a check that does not pass, a SOFTWARE_READY or MAP_GREEN clause that does
not hold, a row that is not verified), with columns id, kind, class, seed, decider, unit, separates,
signed, searched. blockers-seed.tsv holds each id's class at the seed commit, the commit that added
it; neither file is edited to move the seed. blocker_audit() states the rules; a unit that opens or
closes an item updates its row.

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
import math
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
RUNNERS = {"nemu64", "cpu", "bench", "systembench", "thar0", "snapper", "rdpstat", "noise", "pidma", "hydra",
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
            if not row["expect"].startswith("file:") and row["expect"] != "self":
                errors.append(f"{where}: suite row `{cid}` needs expect file:<expected.tsv path>, or `self` when its "
                              f"runner judges each check itself")
            suites[cid[:-2]] = row
        else:
            explicit[cid] = row
        if runner == "pending" and row["expect"] != "gate":
            errors.append(f"{where}: a pending check is a gate; its expect is `gate`")
    suite_files = {}
    for prefix, row in suites.items():
        if not row["expect"].startswith("file:"):
            continue
        path = Path(root) / row["expect"][5:]
        if not path.exists():
            errors.append(f"{CHECKS}:{row['line']}: suite row `{prefix}:*` expects {row['expect'][5:]}, which does not "
                          f"exist. Point it at the suite's expected file, or write `self` when its runner judges each "
                          f"check itself")
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


def check_target(cid, explicit, suites):
    """(runner, target, selector) a check runs: two ids with the same one are one check."""
    row = explicit.get(cid)
    if row:
        return row["runner"], row["target"], row["selector"]
    prefix, _, rest = cid.partition(":")
    return (suites[prefix]["runner"] if prefix in suites else prefix), rest, "-"


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
    checks, explicit, suites, suite_files = load_checks(root, errors)
    lint_errors, sites = lint_module().lint(root)
    errors += lint_errors
    wall_rows(root, errors)
    decomp_pin(root, errors)
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
    measures = {}
    for cid in referenced_checks(rows, checks):
        if check_defined(cid, explicit, suite_files):
            measures.setdefault(check_target(cid, explicit, suites), []).append(cid)
    for same in measures.values():
        if len(same) > 1:
            errors.append(f"{TABLE}: checks {' and '.join(f'`{c}`' for c in same)} measure the same thing (runner, target and "
                          f"selector). Keep one and name it in every row that names the others.")
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
    "consistent-only": "no check failed, but a check passed its consistent rule while the model's phase mean missed the band, "
                       "or a bench or hardware check's verdict differs between code-layout pads: some phase or layout of the model agrees "
                       "with the hardware number, not every one does. Consistent with the hardware, not agreement",
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


def render_spec(rows, checks, found, reports):
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
        "delays misses the band: consistent with the hardware number, not agreement. A bench check is also consistent-only "
        "when its verdict is not the same at every code-layout pad (8 pads, one 32 B I-cache line); its detail names each "
        "pad's verdict. Every bench range is joint over the pads and boot delays. A hardware check follows the same layout "
        "rule: each pad's console capture is compared with the fork's run at that pad, and a question whose fork values "
        "differ by pad fails until the console has run every pad. A bench check's detail gives each consistent "
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
    out += ["", "## Green predicates", "",
            f"From `{CLOSURE}`, which gives each clause and its evidence (`docs/design/green-plan.md` section 1).", ""]
    out += [f"- {predicate_line(n, c)}" for n, c in reports.items()]
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
            "From `tools/n64-timing/checks.tsv`. A `:*` row names a suite whose expected file defines every check under its prefix, or `self` when the suite's runner judges each check itself.", "",
            "| Check | Runner | Target | Selector | Expectation | Source |", "|---|---|---|---|---|---|"]
    for c in checks:
        out.append(f"| `{c['id']}` | {c['runner']} | {cell(c['target'])} | {cell(c['selector'])} | {cell(c['expect'])} | {cell(c['source'])} |")
    return "\n".join(out) + "\n"


def results_source(found):
    return found.get("#source", ("", ""))[1]


COMMIT = re.compile(r"\b[0-9a-f]{7,40}\b")
WALL_BUDGET = "tools/n64-timing/mmbench/wall-budget.tsv"
WALL_COLUMNS = ["run", "wall_s", "commit", "same_tree_as", "date", "load", "user_s", "instructions_u", "source"]
BUDGET_S = 120
MM_BENCH = "tools/n64-timing/calibration/mm_bench.py"


def decomp_pin(root, errors):
    """mm_bench.py's pinned mm-decomp-60fps commit and what its stored git objects prove about it (pin_evidence)."""
    spec = importlib.util.spec_from_file_location("calibration_mm_bench", Path(root) / MM_BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence, problems = module.pin_evidence(module.OBJECTS, module.COMMIT)
    errors += problems
    return module, evidence


def decomp_merged(root):
    """MAP_GREEN's mm-decomp-60fps#1 clause as (holds, evidence)."""
    pin, evidence = decomp_pin(root, [])
    where = f"`{MM_BENCH}` pins {pin.REPO} {pin.COMMIT[:9]}"
    if evidence["merge"] is None:
        return False, f"{where}; its first-parent history in `{CALIBRATION}/{pin.OBJECTS.name}` holds no merge of #{pin.MERGED_PR}"
    sha, subject = evidence["merge"]
    return True, f"{where}; its first-parent history in `{CALIBRATION}/{pin.OBJECTS.name}` holds {sha[:9]} \"{subject}\""


def wall_rows(root, errors):
    """same_tree_as is `-` or a standing-run commit whose tree outside docs/ equals the timed commit's."""
    rows = read_tsv(root, WALL_BUDGET, WALL_COLUMNS, errors)
    for r in rows:
        if not COMMIT.fullmatch(r["commit"]):
            errors.append(f"{WALL_BUDGET}:{r['line']}: commit `{r['commit']}` is not a 7- to 40-hex commit")
        if r["same_tree_as"] != "-" and not COMMIT.fullmatch(r["same_tree_as"]):
            errors.append(f"{WALL_BUDGET}:{r['line']}: same_tree_as `{r['same_tree_as']}` is not `-` or a 7- to 40-hex commit")
    return rows


def current_walls(root):
    """wall-budget.tsv keeps every timing, oldest first; a run's last row is its current one."""
    rows = wall_rows(root, [])
    last = {r["run"]: i for i, r in enumerate(rows)}
    return [r for i, r in enumerate(rows) if last[r["run"]] == i]


def found_result(found, cid):
    return found.get(cid, ("missing", ""))


def destination(root, found):
    """The map #1 Destination items as (item, result, evidence)."""
    det, stepcap = found_result(found, "det"), found_result(found, "stepcap")
    walls = current_walls(root)
    slow = max(walls, key=lambda r: float(r["wall_s"]))
    filesel = [(c, found_result(found, c)) for c in ("mm:filesel-empty", "mm:filesel-named")]
    pin, evidence = decomp_pin(root, [])
    merged, merge_evidence = decomp_merged(root)
    readme = evidence["readme"]
    return [
        ("Timing is bit-deterministic across runs", "pass" if det[0] == stepcap[0] == "pass" else "fail",
         f"`det` {det[0]}: {det[1]}; `stepcap` {stepcap[0]}: {stepcap[1]}"),
        ("A 600-frame MM bench run takes <= 2 min", "pass" if float(slow["wall_s"]) <= BUDGET_S else "fail",
         f"slowest scene {slow['run']} {float(slow['wall_s']):g} s of {BUDGET_S} s; "
         + ", ".join(f"{r['run']} {float(r['wall_s']):g}" for r in walls) + f" s ({WALL_BUDGET}: {slow['source']})"),
        ("MM file select (#11): empty files <= 1.05 and named files 1.90-2.10 fields per game frame, both must pass",
         "pass" if all(r[0] == "pass" for _, r in filesel) else "fail",
         "; ".join(f"`{c}` {r[0]}: {r[1]}" for c, r in filesel)),
        ("MM bench integration: point `tools/bench` at the fork, remove the `func_80173B48` pin",
         "done" if merged and all(readme.values()) else "not done",
         f"{merge_evidence}. `{'/'.join(pin.README)}` there: "
         + "; ".join(f"{key}: " + (f"\"{s}\"" if s else f"no sentence holds \"{pin.README_SENTENCES[key]}\"")
                     for key, s in readme.items())),
    ]


def ids(items):
    return ", ".join(f"`{i}`" for i in items) or "none"


def predicates(root, rows, checks, found):
    """The three reports of docs/design/green-plan.md section 1 and PREHW_COMPLETE (docs/design/prehw-plan.md
    section 1), as {report: [(clause, holds, evidence, members)]}. holds is None for a clause the repository cannot
    decide. members lists the open items (checks, rows, clauses) that keep an open clause from holding, or is None
    when the clause can be open for a reason no single item carries."""
    kit = kit_module(root)
    _, explicit, _, _ = load_checks(root, [])
    qs = {q["id"]: q for q in question_rows(root)}
    links = question_links(root)
    reasons = {u["id"]: u["reason"] for u in calibration_tsv(root, "undecidable.tsv")}
    excluded = {i for i, r in reasons.items() if r.startswith(UNDECIDABLE_PREFIX)}
    out_of_kit = {i for i, r in reasons.items() if r.startswith(KIT_LIMIT_PREFIX)}
    status = {r["id"]: row_status(r, found) for r in rows}
    result = {c: res for c, (res, _) in found.items() if c != "#source"}
    fit_data = {c for r in rows for c in r["fit-from"].split()}
    open_rows = [r for r in rows if r["id"] not in excluded | out_of_kit]

    non_green = sorted(c for c, res in result.items() if res != "pass" and not c.startswith("hw:"))
    undecided = [c for c in non_green if c not in links and c not in reasons]
    fit_green = [r["id"] for r in rows if status[r["id"]] == "pass" and all(
        c in fit_data for c, guard in verify_checks(r) if not guard and c not in r["fit-from"].split() and result.get(c) == "pass")]
    no_rom = sorted(c for c, res in result.items() if res == "pending:no-rom")
    no_reader = sorted(c for c in result if c.startswith("hw:") and c[3:] in qs and not comparable(kit, qs[c[3:]]))
    complete = [
        ("every P0-P4 unit has landed or is closed with a stated reason", None,
         "not computed from the repository: docs/design/green-plan.md section 4 lists the units, and the program ledger tracks them",
         None),
        ("every non-green check names the kit question or console condition that decides it", not undecided,
         f"{len(non_green) - len(undecided)} of {len(non_green)} non-green checks (hw:* excluded: each is its own console "
         f"question) are in a question's closes column or {CALIBRATION}/undecidable.tsv; missing: {ids(undecided)}", None),
        ("no check is green through its own fit data or a fitted third-party threshold", not fit_green,
         f"no row passes through its own fit data (its status is then fit only); rows that pass only through checks another "
         f"row's value was fit to, so a joint fit can hide their error: {ids(fit_green)}. A fitted third-party threshold is not "
         f"machine-readable: each check's source in {CHECKS} names its own", None),
        ("no check is dead (no ROM, no reader, or duplicate)", not no_rom and not no_reader,
         f"no ROM: {ids(no_rom)}; hw checks whose question has no reader: {ids(no_reader)}; duplicates: none, since "
         f"--check fails on two ids for one check", None),
    ]

    det, stepcap = found_result(found, "det")[0], found_result(found, "stepcap")[0]
    walls = current_walls(root)
    slow = max(walls, key=lambda r: float(r["wall_s"]))
    run_commits = COMMIT.findall(results_source(found))
    named = {r["run"]: [c for c in (r["commit"], r["same_tree_as"]) if c != "-"] for r in walls}
    wall_commits = {c for cs in named.values() for c in cs}
    stale = [run for run, cs in named.items() if not any(a.startswith(b) or b.startswith(a) for a in run_commits for b in cs)]
    retimed = bool(run_commits) and not stale
    weak = sorted(c for c, res in result.items() if WEAK.match(res))
    failing = sorted(c for c, res in result.items() if res == "fail")
    other_gates = sorted(c for c, res in result.items() if res.startswith("pending:") and res != "pending:calibration-16")
    uncomparable = sorted(c for c in result if c.startswith("hw:") and result[c] == "pending:calibration-16"
                          and not (c[3:] in qs and comparable(kit, qs[c[3:]])))
    named_by = {}
    for r in rows:
        for c, _ in verify_checks(r):
            named_by.setdefault(c, []).append(r["id"])
    gated = sorted(c for c, res in result.items() if res in ("pending:report-only", "pending:no-rom")
                   and any(rid not in excluded | out_of_kit for rid in named_by.get(c, [c])))
    no_corpus = [r["id"] for r in open_rows if "pending:no-corpus" in r["verify"].split()]

    def independent_question(r):
        return any(c.startswith("hw:") and not guard and c[3:] in qs and comparable(kit, qs[c[3:]])
                   and not reruns_fit(kit, qs[c[3:]], r, explicit) for c, guard in verify_checks(r))
    no_question = [r["id"] for r in open_rows if status[r["id"]] != "pass" and not independent_question(r)]
    ready = [
        (f"det and stepcap pass, and the 600-field MM run takes <= {BUDGET_S} s, re-timed on current master",
         det == stepcap == "pass" and float(slow["wall_s"]) <= BUDGET_S and retimed,
         f"det {det}, stepcap {stepcap}; slowest scene {slow['run']} {float(slow['wall_s']):g} s; the wall times name "
         f"{ids(sorted(wall_commits))} and the standing run {ids(run_commits)}, and the clause holds only when every scene's "
         f"last row names the run's commit in its commit or same_tree_as column; scenes whose last row does not: {ids(stale)}", None),
        ("no check is fail", not failing, f"{len(failing)} fail: {ids(failing)}", failing),
        ("no check is consistent-only or pass-conditional", not weak,
         f"{len(weak)}: " + ", ".join(f"`{c}` {result[c]}" for c in weak) if weak else "none", weak),
        ("every pending check is pending:calibration-16 on a kit question a tool can compare", not other_gates and not uncomparable,
         f"other gates: {ids(other_gates)}; hw checks whose question no tool compares: {ids(uncomparable)}",
         other_gates + uncomparable),
        ("no check is report-only, no-rom or no-corpus, except on excluded or out-of-kit rows", not gated and not no_corpus,
         f"report-only or no-rom checks: {ids(gated)}; rows gated on no-corpus: {ids(no_corpus)}", gated + no_corpus),
        ("every row that is not verified names a hardware question independent of its fit data", not no_question,
         f"{len(no_question)} rows that are not excluded or out of kit, do not pass, and name no hw:<question> a tool compares "
         f"that does not re-run their fit: {ids(no_question)}", no_question),
    ]

    hw = sorted(c for c in result if c.startswith("hw:"))
    filesel = [(c, found_result(found, c)[0]) for c in ("mm:filesel-empty", "mm:filesel-named")]
    verified = [r for r in rows if r["id"] not in excluded and status[r["id"]] == "pass"]
    in_scope = [r for r in rows if r["id"] not in excluded]
    held = sum(1 for _, h, _, _ in ready if h)
    green = [
        ("SOFTWARE_READY", held == len(ready), f"{held} of {len(ready)} clauses hold",
         [clause_id("SOFTWARE_READY", n) for n, (_, h, _, _) in enumerate(ready, 1) if h is not True]),
        ("mm:filesel-empty and mm:filesel-named pass", all(r == "pass" for _, r in filesel),
         ", ".join(f"`{c}` {r}" for c, r in filesel), [c for c, r in filesel if r != "pass"]),
        ("wScottSh/mm-decomp-60fps#1 is merged", *decomp_merged(root), None),
        ("every hw:* check is ingested and passes", all(result[c] == "pass" for c in hw),
         f"{sum(1 for c in hw if result[c] == 'pass')} of {len(hw)} pass, "
         f"{sum(1 for c in hw if result[c] == 'pending:calibration-16')} pending:calibration-16",
         [c for c in hw if result[c] != "pass"]),
        ("every row that is not excluded or out-of-kit is verified", len(verified) == len(in_scope),
         f"{len(verified)} of {len(in_scope)} rows that are not excluded pass, counting the "
         f"{sum(1 for r in rows if r['id'] in out_of_kit)} out-of-kit rows in scope until Scott rules (decision D1); "
         f"{sum(1 for r in rows if r['id'] in excluded)} rows are excluded as not hardware-decidable",
         [r["id"] for r in in_scope if status[r["id"]] != "pass"]),
    ]
    reports = {"SOFTWARE_COMPLETE": complete, "SOFTWARE_READY": ready, "MAP_GREEN": green}
    reports["PREHW_COMPLETE"] = prehw(root, rows, checks, found, reports)
    return reports


BLOCKERS = "tools/n64-timing/calibration/blockers.tsv"
BLOCKERS_SEED = "tools/n64-timing/calibration/blockers-seed.tsv"
BLOCKER_COLUMNS = ["id", "kind", "class", "seed", "decider", "unit", "separates", "signed", "searched"]
SEED_COLUMNS = ["id", "class"]
BLOCKER_CLASSES = ("A", "B", "C", "D", "follows")
OPEN_CLAUSES = {"SOFTWARE_READY": "sr", "MAP_GREEN": "mg"}
PLAN = "docs/design/prehw-plan.md"
FORK = "docs/spec/n64-timing-fork.tsv"
FORK_COLUMNS = ["question", "key", "metric", "rule", "model"]
DRY_RUN = "docs/spec/n64-timing-dry-run.tsv"
DRY_RUN_COLUMNS = ["check", "result"]
#The decider of clause:mg-4 (every hw:* check ingested and passing): no one question decides ingestion.
HW_RUN = "hw-run"
INGESTION_CLAUSE = "clause:mg-4"
RETIME_CLAUSE = "clause:sr-1"
#The unit whose resolution mutation a fit row with no published alternative takes (prehw-plan D9).
RESOLUTION_UNIT = "U-SEPARATES"
#An alternative more than this many tolerances from the fork must be a printed number cited by line.
ALT_BOUND = 4
#A mut that is one quantum of a named model parameter: step=1<unit>, the parameter's own unit, or step=<n><unit>;eq=1
#when n stored units is the first step that changes the output, the effective quantum (clause 3).
STEP = re.compile(r"(\d+)([A-Za-z][\w/-]*)")
QUANTUM = ("param", "step")
EFFECTIVE = "eq"
LINE_CITE = re.compile(r"\S:\d+\b|#L\d+")


def clause_id(report, n):
    return f"clause:{OPEN_CLAUSES[report]}-{n}"


def open_items(rows, found, reports):
    """PREHW_COMPLETE's open set N as {id: kind}: every check whose result is not pass (a hw:* check that is only
    pending:calibration-16 waits on the console run, not on software), every SOFTWARE_READY and MAP_GREEN clause that
    does not hold (`clause:sr-<n>`, `clause:mg-<n>`), and every behavior row that is not verified. Excluded rows stay
    in N: their class D row records why no console decides them."""
    items = {c: "check" for c, (res, _) in found.items()
             if c != "#source" and res != "pass" and not (c.startswith("hw:") and res == "pending:calibration-16")}
    items.update({clause_id(name, n): "clause" for name in OPEN_CLAUSES
                  for n, (_, holds, _, _) in enumerate(reports[name], 1) if holds is not True})
    items.update({r["id"]: "row" for r in rows if row_status(r, found) != "pass"})
    return items


def git_text(root, *args):
    """git's stdout in the checkout whose history answers for root (GIT_ROOT maps a scratch copy to it), or None
    when git cannot answer."""
    try:
        proc = subprocess.run(["git", "-C", str(GIT_ROOT.get(str(root), root)), *args], capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def tsv_text_rows(text, columns):
    """The rows of a tsv text whose header is columns, `#` lines skipped; None for another header."""
    lines = [l for l in text.split("\n") if l and not l.startswith("#")]
    if not lines or lines[0].split("\t") != columns:
        return None
    return [dict(zip(columns, l.split("\t"))) for l in lines[1:]]


def blocker_seed(root):
    """(seed commit, {id: seed class}, {id: undecidable.tsv reason at the seed}), or (None, None, None) when git
    cannot answer. The seed is the oldest first-parent commit that adds blockers-seed.tsv: computed from history,
    never read from a file, so no edit moves it."""
    log = git_text(root, "log", "--first-parent", "--diff-filter=A", "--format=%H", "HEAD", "--", BLOCKERS_SEED)
    if not log or not log.split():
        return None, None, None
    seed = log.split()[-1]
    classes = tsv_text_rows(git_text(root, "show", f"{seed}:{BLOCKERS_SEED}") or "", SEED_COLUMNS) or []
    reasons = tsv_text_rows(git_text(root, "show", f"{seed}:{CALIBRATION}/undecidable.tsv") or "", ["id", "reason"]) or []
    return seed, {r["id"]: r["class"] for r in classes}, {r["id"]: r["reason"] for r in reasons}


def unit_scopes(root):
    """{unit: its Scope cell} from the tables of docs/design/prehw-plan.md section 4, cells split on unescaped |."""
    path = Path(root) / PLAN
    if not path.exists():
        return {}
    section = path.read_text(encoding="utf-8").partition("\n## 4. ")[2].partition("\n## 5. ")[0]
    scopes, at = {}, None
    for line in section.split("\n"):
        if not line.startswith("|"):
            at = None
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if cells[0] == "Unit":
            at = cells.index("Scope") if "Scope" in cells else None
        elif at is not None and cells[0].startswith("U-"):
            scopes[cells[0]] = cells[at]
    return scopes


def names_id(text, iid):
    """True when text names iid as a whole word (a sentence's final period does not join it)."""
    return re.search(rf"(?<![\w.:/-]){re.escape(iid)}(?![\w:/-]|\.\w)", text) is not None


def model_text(values, exact=False):
    """A fork value as FORK stores it: `lo..hi`, or the value set `a,b,...` for an exact rule."""
    def one(v):
        return f"{v:.10g}" if isinstance(v, float) else str(v)
    return ",".join(one(v) for v in values) if exact else f"{one(values[0])}..{one(values[1])}"


def mm_bench_rule(kit):
    """(metric, rule) cells of an ext:mm-bench question: the columns mm_bench.compare judges, each range:abs:<t>."""
    tol = kit.mm_bench.TOLERANCE
    return " ".join(tol), " ".join(f"range:abs:{t}" for t in tol.values())


def fork_values(root, model_dir):
    """[(question, key, metric, rule, model)]: the fork's side of every question a tool compares, from a
    calibration/run.sh output, as kit.py compares it: lo..hi (a set for an exact rule) over boot delays and layout
    pads. Keys of the four-controller runs start `pads-4:`. mm-bench gives each scene's per-frame min..max of each
    judged column from its one fork run (key = scene). thar0 gives each configuration's pruned BUF and PIPE
    average under its 1% rule; systembench each row's reading under main.c's rule (`systembench:<unit>`)."""
    kit = kit_module(root)
    model_dir = Path(model_dir)
    out = []
    for q in question_rows(root):
        if q["kit"] in kit.KIT_ROMS:
            metrics, rules = q["metric"].split(), q["rule"].split()
            rule_of = dict(zip(metrics, rules if len(rules) > 1 else rules * len(metrics)))
            for prefix, pads in (("", None), ("pads-4:", 0b1111)):
                merged = {}
                for logs in kit.model_layouts(model_dir, q["kit"], pads).values():
                    for (key, metric), v in kit.spread(q, logs).items():
                        old = merged.get((key, metric))
                        merged[(key, metric)] = v if old is None else (
                            tuple(sorted(set(old) | set(v), key=str)) if rule_of[metric] == "exact"
                            else (min(old[0], v[0]), max(old[1], v[1])))
                out += [(q["id"], prefix + key, metric, rule_of[metric], model_text(v, rule_of[metric] == "exact"))
                        for (key, metric), v in sorted(merged.items())]
        elif q["kit"] == "ext:mm-bench":
            for scene in q["points"].split():
                run = kit.mm_bench.model_run(model_dir, scene)
                if run is not None and run.complete:
                    out += [(q["id"], scene, metric, f"range:abs:{t}",
                             model_text((min(run.values(metric)), max(run.values(metric)))))
                            for metric, t in kit.mm_bench.TOLERANCE.items()]
        elif q["kit"] == "ext:thar0" and (model_dir / "ext/thar0.txt").exists():
            from romgen.suites.thar0 import compare as thar0
            model = thar0.parse(str(model_dir / "ext/thar0.txt"))
            for i, (sid, _, _) in sorted(thar0.load_expected().items()):
                for metric in ("BUF", "PIPE"):
                    if metric in model.get(i, {}):
                        avg = thar0.reduce(model[i][metric])[1]
                        out.append((q["id"], sid, metric, "range:rel:1", model_text((avg, avg))))
        elif q["kit"] == "ext:systembench" and (model_dir / "ext/systembench.txt").exists():
            from systembench import report as sb
            model = sb.parse((model_dir / "ext/systembench.txt").read_text(encoding="utf-8", errors="replace")) or {}
            for r in sb.read_rows():
                if (r["name"], int(r["qty"])) in model:
                    unit, _, fork = model[(r["name"], int(r["qty"]))]
                    out.append((q["id"], r["row"], "reading", f"systembench:{unit}", model_text((fork, fork))))
    return out


def write_fork_values(root, run, commit):
    lines = [f"# standing run {run_label(run)} on {commit}", "\t".join(FORK_COLUMNS)]
    lines += ["\t".join(map(str, v)) for v in fork_values(root, Path(run) / "calib")]
    (Path(root) / FORK).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines) - 2


DRY_RUN_LINE = re.compile(r"^ingest: (hw:\S+): \S+ -> (\S+)$", re.M)


def write_dry_run(root, run, commit):
    """Runs calibration/dry-run.sh on the run's calib/ directory and records each hw:* check's result after it, so
    PREHW_COMPLETE can read whether the dry run moved every one to pass."""
    proc = subprocess.run(["bash", str(Path(root) / CALIBRATION / "dry-run.sh"), str(Path(run) / "calib")],
                          capture_output=True, text=True)
    moved = dict(DRY_RUN_LINE.findall(proc.stdout))
    lines = [f"# standing run {run_label(run)} on {commit}", "\t".join(DRY_RUN_COLUMNS)]
    if proc.returncode == 0:
        lines += [f"{c}\t{r}" for c, r in sorted(moved.items())]
    (Path(root) / DRY_RUN).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    tail = (proc.stderr or proc.stdout).strip().split("\n")[-1:]
    return proc.returncode, len(moved), tail


def run_record(root, rel, columns):
    """(header line, rows) of a file --results writes beside the results, or (None, None) when it is absent."""
    path = Path(root) / rel
    if not path.exists():
        return None, None
    text = path.read_text(encoding="utf-8")
    return text.split("\n")[0], tsv_text_rows(text, columns) or []


def judge(rule, model, value):
    """(accepts, tolerances outside the fork's range or None for an exact rule) when the console reads value and
    the fork's side is model (lo..hi, a value set for exact), under a question's rule."""
    if rule == "exact":
        return value in model.split(","), None
    lo, _, hi = model.partition("..")
    lo, hi, v = float(lo), float(hi), float(value)
    if rule.startswith("systembench:"):
        from systembench import report as sb
        unit = rule.partition(":")[2]
        tol = max(sb.MEAS_ERROR[unit], 0.002 * abs(lo))
        return sb.passes(unit, lo, v), abs(v - lo) / tol
    _, kind, tol = rule.split(":")
    slack = float(tol) if kind == "abs" else float(tol) / 100 * max(abs(lo), abs(hi))
    return lo - slack <= v <= hi + slack, max(lo - v, v - hi, 0) / slack if slack else math.inf


def separates_problems(b, row, fork, scopes):
    """What keeps a C row's separates cell from showing its question tells the fork from an alternative (section 1
    clause 3): at=<question> <key> <metric>;fork=<value>;alt=<value>;cite=<reference>, or mut=<value>;cite=<unit>,
    optionally with param=<parameter>;step=<n><unit>[;eq=1] naming the model parameter the mutation steps."""
    fields = dict(f.split("=", 1) for f in b["separates"].split(";") if "=" in f)
    shape = ("fork", "alt", "cite") if "alt" in fields else ("fork", "mut", "cite")
    if shape[1] == "mut" and any(f in fields for f in QUANTUM):
        missing = [f for f in QUANTUM if not fields.get(f)]
        if missing:
            return [f"names a mut with {' and '.join(f'{f}=' for f in QUANTUM if f not in missing)} but no "
                    f"{' or '.join(f'{f}=' for f in missing)}; a stepped mut names both the parameter and the step"]
        shape += QUANTUM + ((EFFECTIVE,) if EFFECTIVE in fields else ())
    if set(fields) != {"at", *shape}:
        return [f"separates must read `at=<question> <key> <metric>;fork=<value>;alt=<value>;cite=<reference>` or "
                f"`...;mut=<value>;cite=<unit>[;param=<parameter>;step=<n><unit>[;eq=1]]`; it reads `{b['separates']}`"]
    step = STEP.fullmatch(fields["step"]) if "step" in fields else None
    if "step" in fields and step is None:
        return [f"separates step=`{fields['step']}` must read <count><unit>, such as step=1pclk"]
    if step is not None and int(step[1]) < 1:
        return [f"separates step=`{fields['step']}` must have a count of 1 or more"]
    if fields.get(EFFECTIVE, "1") != "1":
        return [f"separates eq=`{fields[EFFECTIVE]}` must read eq=1: the step is the parameter's effective quantum"]
    quantum = step is not None and (int(step[1]) == 1 or EFFECTIVE in fields)
    at = fields["at"].split()
    if len(at) != 3 or at[0] not in b["decider"].split():
        return [f"separates at=`{fields['at']}` must name one of its deciders, a key and a metric"]
    known = fork.get(tuple(at))
    if known is None:
        return [f"separates at=`{fields['at']}` has no fork value in {FORK}, the standing run's model side"]
    rule, model = known
    if fields["fork"] != model:
        return [f"separates fork=`{fields['fork']}` is not the standing run's model side `{model}` ({FORK})"]
    kind = shape[1]
    try:
        rejects, away = judge(rule, model, fields[kind])
        accepts_fork = all(judge(rule, model, v)[0] for v in (model.split("..") if rule != "exact" else model.split(",")))
    except (ValueError, KeyError):
        return [f"separates {kind}=`{fields[kind]}` is not a value rule `{rule}` can compare"]
    rejects = not rejects
    out = []
    if not accepts_fork:
        out.append(f"the rule `{rule}` does not accept the fork's own value")
    if not rejects:
        out.append(f"the rule `{rule}` accepts {kind}={fields[kind]} against the fork's {model}, so the console "
                   f"cannot tell them apart")
    if kind == "alt":
        if b["signed"] in ("", "-"):
            out.append("names an alt with an empty signed; the unit verifier who opened its cite names a report there")
        if away is not None and away > ALT_BOUND and not LINE_CITE.search(fields["cite"]):
            out.append(f"names an alt {away:.1f} tolerances from the fork, past {ALT_BOUND}, whose cite `{fields['cite']}` "
                       f"points at no line (path:line or #L<n>)")
    else:
        if quantum and b["signed"] in ("", "-"):
            out.append(f"names a one-quantum mut of `{fields['param']}` with an empty signed; the unit verifier who "
                       f"confirmed the parameter, its quantum {fields['step']} and the one-quantum step names a report there")
        if not quantum and away is not None and away > ALT_BOUND:
            out.append(f"names a mut {away:.1f} tolerances from the fork, past {ALT_BOUND}: the question cannot resolve "
                       f"it (U-SEPARATES outcome (b))")
        if fields["cite"] not in scopes:
            out.append(f"names a mut whose cite `{fields['cite']}` is no section 4 unit, the unit that fixed the mutation")
        if row is not None and row["basis"] == "fit" and (fields["cite"] != RESOLUTION_UNIT or b["searched"] in ("", "-")):
            out.append(f"is a fit row with a mut and no alt, which counts only with cite {RESOLUTION_UNIT} and the alt "
                       f"search in searched (D9)")
    return out


def blocker_audit(root, rows, found, reports):
    """Joins calibration/blockers.tsv to the open items N. Returns (items, table, problems, errors, seed): table maps
    each open id to its row, problems maps an id to [(PREHW_COMPLETE clause, what is wrong)], errors is what --check
    reports, and seed is the seed commit or None when git cannot name it.

    A row's class says what still blocks its item: A and B are software work (a unit), C is console data, D is
    nothing (excluded), and follows is a clause open only through other open items. A row's seed class is its class
    in blockers-seed.tsv at the seed commit; an id with none joined N later and counts as B. A row seeded A or B names
    a unit of prehw-plan.md section 4 whose Scope names the id, so relabeling alone moves nothing to C. A C row's
    decider is one or more questions.tsv ids, each comparable, closing the item and not re-running a fit row's fit,
    and its separates names a value the question's rule rejects (separates_problems); or the item's own
    `not decidable by this kit` undecidable.tsv entry, which needs a signed resolution limit when the row was seeded
    A or B or is U-SEPARATES'. A D row was D at the seed, on its own `not-hardware-decidable` entry unchanged since.
    clause:mg-4 is C on hw-run: every hw:* question comparable and the standing run's dry run passing them all."""
    errors, problems = [], {}
    items = open_items(rows, found, reports)
    if not (Path(root) / BLOCKERS).exists():
        return items, {}, problems, [(1, f"{BLOCKERS} is missing. Add one row per open item ({', '.join(BLOCKER_COLUMNS)}).")], None
    kit = kit_module(root)
    qs = {q["id"]: q for q in question_rows(root)}
    _, explicit, _, _ = load_checks(root, [])
    reasons = {u["id"]: u["reason"] for u in calibration_tsv(root, "undecidable.tsv")}
    by_id = {r["id"]: r for r in rows}
    members = {clause_id(name, n): m for name in OPEN_CLAUSES for n, (_, _, _, m) in enumerate(reports[name], 1)}
    scopes = unit_scopes(root)
    seed, seed_class, seed_reasons = blocker_seed(root)
    results_head = (Path(root) / RESULTS).read_text(encoding="utf-8").split("\n")[0] if (Path(root) / RESULTS).exists() else None
    fork_head, fork_rows = run_record(root, FORK, FORK_COLUMNS)
    fork = {(f["question"], f["key"], f["metric"]): (f["rule"], f["model"]) for f in fork_rows or []
            if fork_head == results_head}
    if fork_head is not None and fork_head != results_head:
        errors.append((1, f"{FORK} is from `{fork_head}`, not the results' `{results_head}`; behaviors.py --results writes both"))
    if seed is not None:
        here = tsv_text_rows((Path(root) / BLOCKERS_SEED).read_text(encoding="utf-8"), SEED_COLUMNS) \
            if (Path(root) / BLOCKERS_SEED).exists() else None
        if here != [{"id": i, "class": c} for i, c in seed_class.items()]:
            errors.append((1, f"{BLOCKERS_SEED} differs from the file its seed commit {seed[:9]} added. The seed is fixed: "
                          f"restore it, and record a class change in {BLOCKERS}"))
    table, shape = {}, []
    for b in read_tsv(root, BLOCKERS, BLOCKER_COLUMNS, shape):
        bid, where = b["id"], f"{BLOCKERS}:{b['line']}"

        def bad(clause, why, error=True):
            problems.setdefault(bid, []).append((clause, why))
            if error:
                errors.append((clause, f"{where}: `{bid}` {why}"))
        if bid in table:
            errors.append((1, f"{where}: `{bid}` has a second row; keep one"))
            continue
        if bid not in items:
            errors.append((1, f"{where}: `{bid}` is not an open item: no check, row or clause by that id fails to pass. "
                          f"Delete the row."))
            continue
        table[bid] = b
        if b["kind"] != items[bid]:
            bad(1, f"is a {items[bid]}, not a {b['kind']}; write kind `{items[bid]}`")
        if b["class"] not in BLOCKER_CLASSES:
            bad(1, f"has class `{b['class']}`; write one of {', '.join(BLOCKER_CLASSES)}")
            continue
        seeded = None if seed is None else seed_class.get(bid)
        if seed is not None and b["seed"] != (seeded or "-"):
            bad(1, f"has seed `{b['seed']}`, but its class in {BLOCKERS_SEED} at the seed commit {seed[:9]} is "
                   f"`{seeded or '-'}` (`-`: not in the seed); the seed column copies it")
        deciders = [d for d in b["decider"].split() if d != "-"]
        own_entry = deciders == [bid] and bid in reasons
        if seed is not None and (seeded in ("A", "B") or seeded is None and b["class"] == "C"):
            unit = b["unit"]
            if unit not in scopes or not names_id(scopes[unit], bid):
                bad(3, f"was {seeded or 'not in the seed, so counts as B'} at the seed, so its unit must be a "
                       f"{PLAN} section 4 unit whose Scope names `{bid}`; `{unit}` "
                       + ("is no such unit" if unit not in scopes else "does not name it"))
        if bid == RETIME_CLAUSE and b["class"] != "A":
            bad(5, f"is class {b['class']}; the re-time clause is A whenever it fails (re-time the scenes), never C")
        if b["class"] in ("A", "B"):
            if b["unit"] in ("", "-"):
                bad(2, f"is class {b['class']}, software work, but names no unit; name the unit that does it")
            for d in deciders:
                if d not in qs and d not in reasons:
                    bad(2, f"names decider `{d}`, which is no questions.tsv or undecidable.tsv id")
        elif b["class"] == "D":
            if seed is None:
                pass
            elif seeded != "D":
                bad(4, f"is class D, but was `{seeded or '-'}` at the seed commit {seed[:9]}; a row cannot become D "
                       f"after the seed")
            elif deciders != [bid] or not reasons.get(bid, "").startswith(UNDECIDABLE_PREFIX):
                bad(4, f"is class D, so its decider must be its own {CALIBRATION}/undecidable.tsv entry starting "
                       f"`{UNDECIDABLE_PREFIX.strip()}`; it names `{b['decider']}`")
            elif reasons[bid] != seed_reasons.get(bid):
                bad(4, f"is class D, but its undecidable.tsv entry differs from the one at the seed commit {seed[:9]}; "
                       f"an exclusion is fixed at the seed")
        elif b["class"] == "follows":
            m = members.get(bid)
            if not m:
                bad(5, "is class follows, which only a SOFTWARE_READY or MAP_GREEN clause open through other open items "
                       "can be; give it its own class")
            elif any(x not in items for x in m):
                bad(5, f"is class follows, but {ids([x for x in m if x not in items])} keep it open and are not open "
                       f"items; give it its own class")
        elif b["kind"] == "clause":
            if bid != INGESTION_CLAUSE or deciders != [HW_RUN]:
                bad(5, f"is a clause of class C, which only {INGESTION_CLAUSE} can be, with decider `{HW_RUN}`")
            else:
                hw = [c for c, (res, _) in found.items() if c.startswith("hw:")]
                blind = [c for c in hw if not (c[3:] in qs and comparable(kit, qs[c[3:]]))]
                dry_head, dry = run_record(root, DRY_RUN, DRY_RUN_COLUMNS)
                passed = {d["check"] for d in dry or [] if d["result"] == "pass"} if dry_head == results_head else set()
                if blind:
                    bad(5, f"names {HW_RUN}, but no tool compares {ids(blind)}", error=False)
                if sorted(set(hw) - passed):
                    bad(5, f"names {HW_RUN}, but the standing run's dry run ({DRY_RUN}, "
                           f"{'from another run' if dry_head and dry_head != results_head else 'absent' if dry_head is None else 'current'}) "
                           f"did not move {ids(sorted(set(hw) - passed)[:5])}{' and more' if len(set(hw) - passed) > 5 else ''} "
                           f"to pass", error=False)
        elif not deciders:
            bad(3, "is class C but names no decider; name the questions.tsv question whose console run decides it")
        elif own_entry:
            reason = reasons[bid]
            if not reason.startswith(KIT_LIMIT_PREFIX) or "would decide" not in reason.lower():
                bad(3, f"is class C on its undecidable.tsv entry, which must start `{KIT_LIMIT_PREFIX.strip()}` and say "
                       f"what would decide it")
            elif (seeded in ("A", "B") or seeded is None or b["unit"] == RESOLUTION_UNIT) and b["signed"] in ("", "-"):
                bad(3, f"is out-of-kit, seeded {seeded or '-'} with unit `{b['unit']}`, so its entry must cite an "
                       f"instrument-resolution limit that the unit verifier signs in signed; signed is empty", error=False)
        else:
            for d in deciders:
                q = qs.get(d)
                if q is None:
                    bad(3, f"names decider `{d}`, which is no questions.tsv id")
                elif not comparable(kit, q):
                    bad(3, f"names question `{d}`, whose kit `{q['kit']}` no tool compares")
                elif bid not in q["closes"].split():
                    bad(3, f"names question `{d}`, whose closes column does not list `{bid}`")
                elif items[bid] == "row" and reruns_fit(kit, q, by_id[bid], explicit):
                    bad(3, f"names question `{d}`, which re-runs the row's fit, so it decides nothing (pref 21)")
            if bid not in problems and b["separates"] not in ("", "-"):
                for why in separates_problems(b, by_id.get(bid), fork, scopes):
                    bad(3, why, error=False)
    errors += [(1, e) for e in shape]
    for bid, b in table.items():
        lacking = [x for x in members.get(bid) or [] if x not in table] if b["class"] == "follows" else []
        if lacking:
            problems.setdefault(bid, []).append((5, f"is class follows, but {ids(lacking)} have no row"))
    for iid, kind in sorted(items.items()):
        if iid not in table:
            errors.append((1, f"{BLOCKERS}: open {kind} `{iid}` has no row. Add `{iid}` with its class (A, B, C, D or "
                          f"follows), seed, decider, unit, separates, signed and searched."))
    return items, table, problems, errors, seed


GIT_ROOT = {}


def run_is_current(root, found):
    """True when the emulator and the tools at HEAD are the standing run's tree (blockers.tsv aside), False when they
    differ, None when git cannot tell."""
    commits = COMMIT.findall(results_source(found))
    if not commits:
        return False
    try:
        proc = subprocess.run(["git", "-C", str(GIT_ROOT.get(str(root), root)), "diff", "--quiet", commits[0], "HEAD", "--", "ares",
                               "tools/n64-timing", f":(exclude){BLOCKERS}"], capture_output=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(proc.returncode)


def prehw(root, rows, checks, found, reports):
    """PREHW_COMPLETE (docs/design/prehw-plan.md section 1), clauses 1 to 7. A missing input (no blockers.tsv, a
    check with no result, no git for the seed) fails or leaves a clause not computed, so an open set that a failed
    read emptied never holds."""
    items, table, problems, errors, seed = blocker_audit(root, rows, found, reports)
    wanted = [c for c in referenced_checks(rows, checks, root) if not c.startswith("pending:")]
    unread = [c for c in wanted if c not in found]
    missing = sorted(i for i in items if i not in table)

    def failing(clause, among=None):
        return sorted(i for i, ps in problems.items() if any(c == clause for c, _ in ps) and (among is None or i in among))
    shape = [e for c, e in errors if c == 1 and not e.startswith(f"{BLOCKERS}: open ")]
    kinds = {k: sum(1 for v in items.values() if v == k) for k in ("check", "row", "clause")}
    by_class = {c: sorted(i for i, b in table.items() if b["class"] == c) for c in BLOCKER_CLASSES}
    c_rows = [i for i in by_class["C"] if items[i] != "clause"]
    unwritten = [i for i in c_rows if table[i]["decider"] != i
                 and any(table[i][col] in ("", "-") for col in ("separates", "searched"))]
    complete = reports["SOFTWARE_COMPLETE"][1:]
    det, stepcap = found_result(found, "det")[0], found_result(found, "stepcap")[0]
    current = run_is_current(root, found)
    results_head = (Path(root) / RESULTS).read_text(encoding="utf-8").split("\n")[0] if (Path(root) / RESULTS).exists() else None
    dry_head, dry = run_record(root, DRY_RUN, DRY_RUN_COLUMNS)
    hw = sorted(c for c in found if c.startswith("hw:"))
    unmoved = [c for c in hw if dry_head != results_head or c not in {d["check"] for d in dry if d["result"] == "pass"}]
    settled = all(h for _, h, _, _ in complete) and det == stepcap == "pass" and not unmoved
    bad3, bad4, bad5 = failing(3, c_rows + by_class["A"] + by_class["B"]), failing(4), failing(5)
    seedless = ("not computed: git names no seed commit" if seed is None
                else f"seed classes from the commit that added {BLOCKERS_SEED}")
    return [
        ("every open item has exactly one blocker row, and no row names an item that is not open",
         not unread and not missing and not shape,
         f"{len(items)} open items ({kinds['check']} checks, {kinds['row']} rows, {kinds['clause']} clauses), "
         f"{len(table)} with a row in {BLOCKERS}; no row: {ids(missing)}; checks with no result: {ids(unread)}; "
         f"other {BLOCKERS} errors: {len(shape)}", None),
        ("no open item is class A or B: no software-doable work is left",
         not missing and not by_class["A"] and not by_class["B"],
         f"class A: {ids(by_class['A'])}; class B: {ids(by_class['B'])}; no row: {len(missing)}", None),
        ("every class C row names a console measurement a tool compares that closes it, a value its rule rejects "
         "that the fork does not give, and the sources searched; every row seeded A or B names a unit whose Scope "
         "names it",
         None if seed is None else not bad3 and not unwritten,
         f"{seedless}; {len(c_rows)} C rows; failing a rule: {len(bad3)} ({ids(bad3)}); with no separates or "
         f"searched: {len(unwritten)} ({ids(unwritten)})", None),
        ("every class D row was D at the seed, on its own not-hardware-decidable entry unchanged since",
         None if seed is None else not bad4,
         f"{seedless}; {len(by_class['D'])} D rows: {ids(by_class['D'])}; failing: {ids(bad4)}", None),
        ("every clause row has a decider PRED can check: follows with its members' rows, or clause:mg-4 on hw-run",
         not bad5, f"clause rows: {ids(sorted(i for i in table if items[i] == 'clause'))}; failing: {ids(bad5)}", None),
        ("SOFTWARE_COMPLETE clauses 2 to 4 hold, det and stepcap pass, the standing run is the current tree, and its "
         "dry run moves every hw:* check to pass",
         False if not settled or current is False else current,
         f"SOFTWARE_COMPLETE clauses 2 to 4: {', '.join('yes' if h else 'no' for _, h, _, _ in complete)}; det {det}, "
         f"stepcap {stepcap}; the results header `{results_source(found)}`: ares/ and tools/n64-timing/ at HEAD "
         + {True: "equal its commit", False: "differ from its commit (or it names none)",
            None: "not compared (no git)"}[current]
         + f"; dry run ({DRY_RUN}): {len(hw) - len(unmoved)} of {len(hw)} hw:* checks pass"
         + ("" if dry_head == results_head else " (absent or from another run)"), None),
        ("every unit has landed or is closed with a stated reason, and every open issue but #1 and #16 is closed or a "
         "C decider", None, "not computed from the repository: the program ledger tracks units and issues", None),
    ]


def predicate_line(name, clauses):
    decided = [h for _, h, _, _ in clauses if h is not None]
    held = sum(1 for h in decided if h)
    if name == "SOFTWARE_READY":
        return f"SOFTWARE_READY: {held} of {len(clauses)} clauses hold."
    unknown = len(clauses) - len(decided)
    verdict = "does not hold" if held < len(decided) else "not decided" if unknown else "holds"
    if name == "PREHW_COMPLETE":
        return (f"PREHW_COMPLETE: {held} of {len(decided)} computed clauses hold; {unknown} not computed from the "
                f"repository; {verdict}. Open software work, {clauses[1][2]}.")
    return f"{name}: {verdict}. {held} of {len(decided)} computed clauses hold" + (
        f"; {unknown} {'is' if unknown == 1 else 'are'} not computed from the repository." if unknown else ".")


def render_predicates(reports):
    out = ["## Green predicates", "",
           "The three reports of `docs/design/green-plan.md` section 1 and PREHW_COMPLETE of `docs/design/prehw-plan.md` "
           "section 1, computed from the tables and the results. "
           "SOFTWARE_COMPLETE is the software-only end state; SOFTWARE_READY cannot hold without the console run (#16); "
           "MAP_GREEN is the map's destination. PREHW_COMPLETE holds when every open item (a check that does not pass, "
           "a clause above that does not hold, a row that is not verified) has one row in "
           f"`{BLOCKERS}` and only console data, or nothing, decides it.", ""]
    out += [f"- {predicate_line(n, c)}" for n, c in reports.items()]
    for name, clauses in reports.items():
        out += ["", f"### {name}", "", "| Clause | Holds | Evidence |", "|---|---|---|"]
        out += [f"| {cell(c)} | {'not computed' if h is None else 'yes' if h else '**no**'} | {cell(e)} |" for c, h, e, _ in clauses]
    return out


def render_closure(root, rows, checks, found, reports):
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
           "does instead." if by_status.get("not-built") else
           "Every behavior that is not a legacy cost is built: the code reads each value or implements each rule.")
        + f" The {sum(1 for r in rows if r['basis'] == 'legacy')} legacy rows are a third class, apart from built and not-built "
        "rows: constants today's core charges with no hardware reference (Legacy costs in today's core, in the spec).",
        "",
    ] + render_predicates(reports) + [
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
            "misses the band, or a bench or hardware check's verdict differs between code-layout pads, so it is consistent with the hardware "
            "number, not agreement. pass-conditional:#<issue>: the "
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
    """(errors, outputs, blocker errors). The blocker table's errors fail --check, never generation, so ingesting a
    capture that turns items green still regenerates the spec."""
    errors, rows, checks, sites = validate(root)
    found = load_results(root, rows, checks, errors)
    errors += calibration_errors(root, rows, checks, found)
    reports = predicates(root, rows, checks, found)
    blockers = [e for _, e in blocker_audit(root, rows, found, reports)[3]]
    return errors, {HEADER: render_header(rows), SPEC: render_spec(rows, checks, found, reports),
                    CLOSURE: render_closure(root, rows, checks, found, reports),
                    INVENTORY: render_inventory(root, rows, checks, found)}, blockers


CALIBRATION = "tools/n64-timing/calibration"
UNDECIDABLE_PREFIX = "not-hardware-decidable: "
#An entry a console could decide, but not with this kit's ROMs and a flashcart; the reason names what would.
KIT_LIMIT_PREFIX = "not decidable by this kit: "


def calibration_tsv(root, name):
    path = Path(root) / CALIBRATION / name
    if not path.exists():
        return []
    lines = [l for l in path.read_text(encoding="utf-8").split("\n") if l]
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t")), line=n) for n, l in enumerate(lines[1:], 2)]


def hardware_needs(root, rows, found):
    """(id, why, where) for everything a console could have to decide: every behavior row (one that
    rests on a fit, a model choice or an inference, and one whose reference a console run would
    confirm), checks with a failing, consistent-only or conditional result, rows no corpus or only a
    report checks, and the hardware items of issues and follow-ups (calibration/items.tsv)."""
    out = []
    for r in rows:
        why = []
        if r["basis"] in ("fit", "model-choice", "inferred"):
            why.append(r["basis"])
        else:
            why.append(f"{r['basis']} reference")
        if "verify-is-fit" in r["verify"] + " " + r["note"]:
            why.append("verify-is-fit")
        if re.search(r"\binferred\b", r["note"] + " " + r["reference"], re.I) and "inferred" not in why:
            why.append("an inference in its reference or note")
        weak = [c for c, _ in verify_checks(r) if not c.startswith("hw:") and
                (found.get(c, ("",))[0] == "fail" or WEAK.match(found.get(c, ("",))[0]))]
        if weak:
            why.append(f"check {', '.join(weak)} {found[weak[0]][0]}")
        status = row_status(r, found)
        for gate in ("pending:no-corpus", "pending:report-only"):
            if gate in status:
                why.append(gate)
        if why:
            out.append((r["id"], "; ".join(why), f"{TABLE}:{r['line']}"))
    for c in sorted(found):
        res = found[c][0]
        if c != "#source" and not c.startswith("hw:") and (res == "fail" or WEAK.match(res)):
            out.append((c, f"result {res}", RESULTS))
    for item in calibration_tsv(root, "items.tsv"):
        out.append((f"item:{item['id']}", item["source"], f"{CALIBRATION}/items.tsv:{item['line']}"))
    return out


def calibration_errors(root, rows, checks, found):
    """The calibration inventory's rules: no row waits on calibration #16 without a kit question that
    measures it, every question names a kit ROM (or says why none exists), a valid rule, and only
    rows, checks, items or issues in its closes column; a row's hw check is one its question closes, and
    a row a comparable question closes names its hw check unless that question re-runs the row's fit;
    and everything a console could decide (hardware_needs) has a question or a stated reason that no
    console run, or no run of this kit, can decide it (calibration/undecidable.tsv)."""
    errors = []
    kit = kit_module(root)
    qs = {q["id"]: q for q in question_rows(root)}
    _, explicit, _, suite_files = load_checks(root, [])
    ids = {r["id"] for r in rows} | {f"item:{i['id']}" for i in calibration_tsv(root, "items.tsv")}
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
                if not comparable(kit, q):
                    errors.append(f"{where}: `{r['id']}` names {cid}, whose kit is `{q['kit']}`, not an in-repo kit ROM "
                                  f"({', '.join(kit.KIT_ROMS)}) or an ext: ROM with a reader (calibration/kit.py EXT_ROMS). "
                                  f"A row's hardware check needs a ROM ingestion can compare.")
                if r["id"] not in q["closes"].split():
                    errors.append(f"{where}: `{r['id']}` names {cid}, but the question's closes column does not list it. "
                                  f"Add `{r['id']}` there.")
    by_id = {r["id"]: r for r in rows}
    for q in qs.values():
        where = f"tools/n64-timing/calibration/questions.tsv:{q['line']}"
        for rid in q["closes"].split():
            r = by_id.get(rid)
            if r and comparable(kit, q) and f"hw:{q['id']}" not in {c for c, _ in verify_checks(r)} and not reruns_fit(kit, q, r, explicit):
                errors.append(f"{TABLE}:{r['line']}: `{rid}` is closed by hw:{q['id']}, but its verify column does not "
                              f"name it, so a console result never reaches the row. Add `hw:{q['id']}` there.")
        if q["kit"] not in kit.KIT_ROMS and not q["kit"].startswith(("ext:", "none: ")):
            errors.append(f"{where}: kit `{q['kit']}` is not a kit ROM ({', '.join(kit.KIT_ROMS)}), `ext:<rom>` or "
                          f"`none: <reason>`")
        if q["kit"] == "ext:mm-bench" and not (q["points"].split() and set(q["points"].split()) <= set(kit.mm_bench.SCENES)):
            errors.append(f"{where}: points `{q['points']}` must name the BENCH scenes the question reads "
                          f"({' '.join(kit.mm_bench.SCENES)})")
        if q["kit"] == "ext:mm-bench":
            want = mm_bench_rule(kit)
            if (q["metric"], q["rule"]) != want:
                errors.append(f"{where}: metric `{q['metric']}` and rule `{q['rule']}` must be `{want[0]}` and "
                              f"`{want[1]}`, the columns and tolerances mm_bench.compare judges (TOLERANCE)")
        elif not kit.RULE.match(q.get("rule", "")) or (q["kit"] in kit.KIT_ROMS) == (q.get("rule") == "-"):
            errors.append(f"{where}: rule `{q.get('rule')}` must be exact or range:abs|rel:<tolerance> for a kit ROM "
                          f"question, `-` otherwise")
        elif len(q["rule"].split()) not in (1, len(q["metric"].split())):
            errors.append(f"{where}: rule `{q['rule']}` names {len(q['rule'].split())} rules for "
                          f"{len(q['metric'].split())} metrics; give one rule, or one per metric")
        for c in q["closes"].split():
            if c != "-" and c not in ids and not check_defined(c, explicit, suite_files) and not re.match(r"^#\d+$", c):
                errors.append(f"{where}: closes `{c}`, which is no behavior row, check, item:<id> or #issue")
    links = question_links(root)
    undecidable = {}
    for u in calibration_tsv(root, "undecidable.tsv"):
        where = f"{CALIBRATION}/undecidable.tsv:{u['line']}"
        undecidable[u["id"]] = u
        reason = u.get("reason", "")
        prefix = next((p for p in (UNDECIDABLE_PREFIX, KIT_LIMIT_PREFIX) if reason.startswith(p)), None)
        if prefix is None or len(reason) < len(prefix) + 10:
            errors.append(f"{where}: `{u['id']}` needs a reason `{UNDECIDABLE_PREFIX}<why no console run can decide it>` "
                          f"or `{KIT_LIMIT_PREFIX}<what would decide it>`")
        if u["id"] not in ids and not check_defined(u["id"], explicit, suite_files) and u["id"] not in found:
            errors.append(f"{where}: `{u['id']}` is no behavior row, check or item:<id>")
        if u["id"] in links:
            errors.append(f"{where}: `{u['id']}` is closed by hw:{links[u['id']][0]} and also listed as undecidable; "
                          f"keep one")
    for nid, why, where in hardware_needs(root, rows, found):
        if nid not in links and nid not in undecidable:
            errors.append(f"{where}: `{nid}` ({why}) has no hardware question. Add it to the closes column of the "
                          f"tools/n64-timing/calibration/questions.tsv question whose kit points decide it (adding the "
                          f"points to a kit ROM if none does), or to {CALIBRATION}/undecidable.tsv with "
                          f"`{UNDECIDABLE_PREFIX}<reason>` or `{KIT_LIMIT_PREFIX}<what would decide it>`.")
    return errors


def comparable(kit, q):
    """True when ingestion can compare a console capture for the question: a kit ROM, or an ext: ROM
    with a reader."""
    return q["kit"] in kit.KIT_ROMS or (q["kit"].startswith("ext:") and kit.EXT_ROMS.get(q["kit"][4:]) is not None)


def reruns_fit(kit, q, r, explicit):
    """True when the question's ROM is the one the row's fit-from checks run, so its console run repeats
    the fit's own measurement and is no independent check of the row (pref 21: such a row stays fit only)."""
    fit = r["fit-from"].split()
    if q["kit"].startswith("ext:"):
        return any(c.startswith(kit.EXT_SUITES[q["kit"][4:]] + ":") for c in fit)
    suite, set_name, _ = kit.KIT_ROMS[q["kit"]]
    return suite != "calib" and any(explicit.get(c, {}).get("runner") == suite and explicit[c].get("target") == set_name
                                    for c in fit)


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
        "that the procedure runs and ingestion stores; calibration/kit.py EXT_ROMS compares the ones with a reader. "
        "`none:` is a question with no kit ROM, with the reason.",
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
    undecidable = {u["id"]: u["reason"] for u in calibration_tsv(root, "undecidable.tsv")}
    items = {f"item:{i['id']}": i["item"] for i in calibration_tsv(root, "items.tsv")}
    needs = hardware_needs(root, rows, found)
    out += ["", "## Coverage", "",
            f"Everything a console could have to decide: every behavior row (a fit, a model choice or an inference, "
            f"and a reference a console run would confirm), checks with a failing, consistent-only or conditional "
            f"result, rows that no corpus or only a report checks, and the hardware items of issues and follow-ups "
            f"({CALIBRATION}/items.tsv). `behaviors.py --check` fails unless each one has a question or a reason in "
            f"{CALIBRATION}/undecidable.tsv: `{UNDECIDABLE_PREFIX.strip()}` when no console run can decide it, "
            f"`{KIT_LIMIT_PREFIX.strip()}` when a console could but this kit cannot, with what would. {len(needs)} entries: "
            f"{sum(1 for n, _, _ in needs if n in links)} with a question, "
            f"{sum(1 for n, _, _ in needs if undecidable.get(n, '').startswith(UNDECIDABLE_PREFIX))} not hardware-decidable "
            f"(no console run can decide them), "
            f"{sum(1 for n, _, _ in needs if undecidable.get(n, '').startswith(KIT_LIMIT_PREFIX))} not decidable by this kit "
            f"(a console could, with what the reason names).", "",
            "| Entry | Why | Question or reason |", "|---|---|---|"]
    for nid, why, _ in needs:
        what = f"{cell(why)}: {cell(items[nid])}" if nid in items else cell(why)
        answer = asked(nid) if nid in links else cell(undecidable.get(nid, "**none**"))
        out.append(f"| `{nid}` | {what} | {answer} |")
    gaps = [q for q in qs if q["kit"].startswith(("ext:", "none"))]
    out += ["", "## Questions without an in-repo kit ROM", "",
            "These run outside the kit's mechanical comparison: an external ROM the procedure names, or no ROM yet.",
            "", "| Question | Kit | Closes |", "|---|---|---|"]
    out += [f"| `{q['id']}` | {cell(q['kit'])} | {' '.join(f'`{c}`' for c in q['closes'].split())} |" for q in gaps]
    return "\n".join(out) + "\n"


def check(root):
    errors, outputs, blockers = generated(root)
    errors += blockers
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


def nemu64_phase_result(base, row):
    """An averaged test over the VI phases (romgen/suites/nemu64/phase.py): the model's phase mean
    against the ROM's own average band, its min, max and median at every phase."""
    selector, _, value = row["selector"].partition(" @")
    picked = [r for r in tsv_rows(base / "phase.tsv") if r["test"] in selector.split("|") and value in r["value"]]
    if not picked:
        return "missing", f"no `{row['selector']}` value in nemu64/{row['target']}/phase.tsv"
    verdict, detail = tally([r["result"] for r in picked], "values")
    return verdict, detail + "; " + "; ".join(
        f"{r['value'].strip()}: phase mean {r['phase_mean']} over {r['phases']} phases (band {r['band_mean']}), "
        f"mean {r['mean']}, median {r['median']} (band {r['band_median']}) {r['result']}"
        + (f" on {r['failed']}" if r["failed"] != "-" else "") for r in picked)


def nemu64_result(run, row):
    base = run / "nemu64" / row["target"]
    if (base / "phase.tsv").exists():
        return nemu64_phase_result(base, row)
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


def cpu_result(run, row):
    """A cpu suite ROM's own verdict (romgen/suites/cpu/run.sh): its `CPU: Failed X of Y` line. A summary
    without that line is a ROM that never finished, so it fails."""
    base = run / "cpu" / row["target"]
    summary = text(base / "summary.txt")
    if summary is None:
        return None
    m = re.search(r"^CPU: Failed (\d+) of (\d+) tests", summary, re.M)
    if not m:
        return "fail", f"no `CPU: Failed X of Y` line in cpu/{row['target']}/summary.txt; the ROM did not finish"
    failed, total = int(m.group(1)), int(m.group(2))
    failing = [r["test"] for r in tsv_rows(base / "tests.tsv") if r["result"] != "pass"] if (base / "tests.tsv").exists() else []
    detail = f"{total - failed} of {total} tests pass" + (f"; failing: {', '.join(failing)}" if failing else "")
    return ("pass" if failed == 0 and total else "fail"), detail


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
    """A bench value over the layout pads and boot delays: the one value when every point agrees, else
    its joint range, and each pad's verdict when they differ."""
    text = r["min"] if r["min"] == r["max"] else f"{r['min']}..{r['max']} median {r['median']} mean {r['mean']}"
    by_pad = pad_labels(r)
    if len(set(by_pad.values())) > 1:
        text += " (pads " + " ".join(f"{p}:{v}" for p, v in by_pad.items()) + ")"
    return text


def pad_labels(r):
    """Each layout pad's verdict, recomputed from its range and mean (report.py pad_phases_text)."""
    from romgen.suites.bench.report import label
    if r["kind"] != "check" or r["pad_phases"] == "-":
        return {}
    out = {}
    for entry in r["pad_phases"].split():
        pad, lo, hi, mean = re.fullmatch(r"(\d+):(\S+)\.\.(\S+)/(\S+)", entry).groups()
        out[pad] = label(r, float(lo), float(hi), float(mean))
    return out


def window_text(r):
    """A consistent row's acceptance window and the mean rule's verdict (bench README, Phase)."""
    return f"window ±{r['window_pct']}%, mean rule {r['mean_verdict']}" if r.get("window_pct", "-") != "-" else ""


def bench_label(r):
    """The row's verdict, recomputed from each layout pad's range and mean with report.py's label and
    layout rule, so a results.tsv that calls a consistent-only point pass cannot pass it here."""
    from romgen.suites.bench.report import layout_verdict
    if r["kind"] != "check" or r["min"] == "None":
        return r["verdict"]
    return layout_verdict(list(pad_labels(r).values()))


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


def systembench_result(run, row):
    """The original n64-systembench on the fork, under its own rule at the unpadded ROM and every boot delay
    (systembench/report.py)."""
    if not (run / "systembench" / "results.tsv").exists():
        return None
    picked = [r for r in tsv_rows(run / "systembench" / "results.tsv") if r["row"] == row["target"]]
    if not picked:
        return None
    r = picked[0]
    spread = "" if r["min"] == r["max"] else f", {r['min']}..{r['max']} over the boot delays"
    offset = int(r["pristine"]) - int(r["expected"])
    return r["verdict"], (f"{r['name']} [{r['qty']}] {r['pristine']} {r['unit']} cycles{spread} (hardware {r['expected']}, "
                          f"{offset:+d}, {offset * 100 / int(r['expected']):+.2f}%); main.c rule holds in {r['runs_pass']} of {r['runs']} runs")


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
    prefixes = row["selector"].split("|")
    picked = [r for r in tsv_rows(path) if prefixes == ["-"] or r["test"].startswith(tuple(prefixes))]
    if not picked:
        return "missing", f"no test `{row['selector']}` in rdpstat/{row['target']}"
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
        and all(re.search(rf"^{tool}: self-test: \d+ cases, 0 failed$", log, re.M)
                for tool in ("behaviors.py", "pidma-replay", "systembench report", "kit.py", "scripts"))
    return ("pass" if ok else "fail"), ("behaviors.py --check and --self-test, lint-literals.py, pidma-replay.py, "
                                        "systembench/report.py, calibration/kit.py --self-test and scripts-selftest.py")


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
        scene = module.ROWS[index][2]
        ok, measured = module.row_verdict(run / "mmbench", index)
        return ("missing" if ok is None else "pass" if ok else "fail"), f"{scene}: {measured}"
    scene = summary.get(MM_SCENES.get(row["selector"], row["selector"]))
    return ("report", f"{scene['scene']}: {scene['fields_per_gframe_mean']} fields per game frame, "
                      f"{scene['rsp_busy_clocks_per_field_mean']} RSP busy clocks per field") if scene else None


def pidma_result(run, row):
    m = re.search(r"^pidma: (PASS|FAIL|UNCHECKED): (.*)$", text(run / "pidma" / "summary.txt") or "", re.M)
    if not m:
        return None
    return {"PASS": "pass", "FAIL": "fail", "UNCHECKED": "pending:replay-unchecked"}[m.group(1)], m.group(2)


READERS = {"nemu64": nemu64_result, "cpu": cpu_result, "det": lambda run, row: suite_runs(run, "det-*.txt", "determinism"),
           "stepcap": lambda run, row: suite_runs(run, "stepcap-*.txt", "stepcap"),
           "bench": bench_result, "systembench": systembench_result, "thar0": thar0_result, "rdpstat": rdpstat_result, "snapper": snapper_result,
           "unit": ctest_result, "noise": noise_result, "gen": gen_result, "mm": mm_result, "pidma": pidma_result,
           "harness": rdpstat_result}
ROM_FILES = {"bench": "./bench/pad-*/boot-*/bench-{}.z64", "systembench": "./systembench/n64-systembench.z64", "rdpstat": "./rdpstat-{}.z64", "snapper": "./snapper-{}.z64",
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


def failing_suites(out):
    """The checks of one scored run that fail or did not run, grouped by the suite (runner) that ran them."""
    suites = {}
    for cid, result, _ in out:
        if result in ("fail", "not-run"):
            suites.setdefault(cid.partition(":")[0], []).append(f"{cid} {result}")
    return suites


def run_label(path):
    """A run directory without the local part of its path: its last two components."""
    return "/".join(Path(path).resolve().parts[-2:])


RUN_COMMIT = "run-commit.txt"


def run_commit(run, given=None):
    """The commit a standing run was built and run from: standing.sh records it in RUN_COMMIT as `<sha>` or
    `<sha> dirty`. A run made before that record existed needs --run-commit. Never the scoring tree's HEAD,
    which is rarely the tree that ran."""
    recorded = (text(Path(run) / RUN_COMMIT) or "").split()
    if recorded and given and not (recorded[0].startswith(given) or given.startswith(recorded[0])):
        return None, (f"{run_label(run)}/{RUN_COMMIT} records {recorded[0]} but --run-commit names {given}. "
                      f"Drop --run-commit; the record is the run's own.")
    if recorded:
        return recorded[0] + (" with uncommitted changes" if recorded[1:] == ["dirty"] else ""), None
    if given:
        return given, None
    return None, (f"{run_label(run)} has no {RUN_COMMIT}, so the commit it ran is unknown. Pass --run-commit <sha> "
                  f"naming the tree that built and ran it (see tools/n64-timing/README.md), or rerun standing.sh.")


def write_results(root, run, out, commit):
    head = f"# standing run {run_label(run)} on {commit}"
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
    GIT_ROOT[str(work)] = root
    try:
        shutil.copytree(root / "ares/n64", work / "ares/n64")
        shutil.copytree(root / "tools/n64-timing", work / "tools/n64-timing", ignore=shutil.ignore_patterns("__pycache__"))
        (work / SPEC).parent.mkdir(parents=True)
        (work / INVENTORY).parent.mkdir(parents=True)
        (work / PLAN).parent.mkdir(parents=True)
        for rel in (SPEC, RESULTS, CLOSURE, INVENTORY, PLAN, FORK, DRY_RUN):
            shutil.copy(root / rel, work / rel)

        def edit(rel, change):
            path = work / rel
            before = path.read_text(encoding="utf-8")
            path.write_text(change(before), encoding="utf-8", newline="\n")
            return lambda: path.write_text(before, encoding="utf-8", newline="\n")

        def row_field(row_id, column, value):
            def change(text):
                lines = text.split("\n")
                at = lines[0].split("\t").index(column)
                for i, line in enumerate(lines):
                    fields = line.split("\t")
                    if fields[0] == row_id:
                        fields[at] = value
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
        run_commit = COMMIT.findall(text(work / RESULTS).split("\n")[0])[0]
        stale_commit = ("0" if run_commit[0] != "0" else "1") + run_commit[1:]

        def wall_edit(change):
            def apply(t):
                head, *body = t.split("\n")
                rows = []
                for line in body:
                    if line:
                        row = dict(zip(WALL_COLUMNS, line.split("\t")))
                        change(row)
                        line = "\t".join(row[c] for c in WALL_COLUMNS)
                    rows.append(line)
                return "\n".join([head, *rows])
            return apply

        def regenerated_closure(_):
            return generated(work)[1][CLOSURE]

        def blocker(rid, **cells):
            def change(t):
                for column, value in cells.items():
                    t = row_field(rid, column, value)(t)
                return t
            return change

        def fork_cell(question, key, metric):
            return next(f["model"] for f in run_record(work, FORK, FORK_COLUMNS)[1]
                        if (f["question"], f["key"], f["metric"]) == (question, key, metric))
        undecidable = f"{CALIBRATION}/undecidable.tsv"
        failing_timeline = lambda t: re.sub(r"^unit:timeline\tpass\t", "unit:timeline\tfail\t", t, flags=re.M)  # noqa: E731
        cases = [
            ("the committed tree", None, None, None),
            ("a row waiting on calibration #16 with no kit test", TABLE, row_field("cpu.dcb", "verify", "pending:calibration-16"),
             "waits on pending:calibration-16 with no kit test. Name the hw:<question>"),
            ("a hardware check its question does not close", TABLE, row_field("ri.read-hit", "verify", "unit:ri-cost-table hw:dcb"),
             "but the question's closes column does not list it"),
            ("a row's hardware check without a kit ROM", "tools/n64-timing/calibration/questions.tsv",
             row_field("dcb", "kit", "none: self-test"), "`cpu.dcb` names hw:dcb, whose kit is `none: self-test`, not an in-repo kit ROM"),
            ("an mm-bench question with no points", "tools/n64-timing/calibration/questions.tsv",
             row_field("mm-filesel", "points", ""), "points `` must name the BENCH scenes the question reads"),
            ("an mm-bench rule wider than mm_bench.compare's tolerance", "tools/n64-timing/calibration/questions.tsv",
             row_field("mm-bench", "rule", "range:abs:0 range:abs:2"),
             "rule `range:abs:0 range:abs:2` must be `vi rdp_ticks` and `range:abs:0 range:abs:1`"),
            ("a question closing an unknown id", "tools/n64-timing/calibration/questions.tsv",
             lambda t: t.replace("\tcpu.dcb\t", "\tcpu.no-such-row\t", 1), "closes `cpu.no-such-row`, which is no behavior row"),
            ("a question with more rules than metrics", "tools/n64-timing/calibration/questions.tsv",
             lambda t: t.replace("\texact range:abs:14\t", "\texact range:abs:14 exact\t", 1),
             "names 3 rules for 2 metrics; give one rule, or one per metric"),
            ("a model-choice row with neither a question nor a reason", "tools/n64-timing/calibration/undecidable.tsv",
             lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("scheduler.tie-rank\t")),
             "`scheduler.tie-rank` (model-choice) has no hardware question"),
            ("a not-hardware-decidable entry without its reason", "tools/n64-timing/calibration/undecidable.tsv",
             lambda t: t.replace("scheduler.tie-rank\tnot-hardware-decidable: ", "scheduler.tie-rank\t", 1),
             "`scheduler.tie-rank` needs a reason `not-hardware-decidable: "),
            ("an issue item no question closes", "tools/n64-timing/calibration/items.tsv",
             lambda t: t + "self-test-item\tissue #16\ta hardware item added without a question\n",
             "`item:self-test-item` (issue #16) has no hardware question"),
            ("a row a comparable question closes, without its hw check", TABLE,
             row_field("rdp.sync-pipe", "verify", "bench:rdp-sync-sweep"),
             "`rdp.sync-pipe` is closed by hw:rdp-sync-setter, but its verify column does not name it"),
            ("a fit row whose fit ROM no longer matches, without the hw check", TABLE,
             row_field("cpu.ctc1-fpe-ce", "fit-from", "bench:pi-dma-sizes"),
             "`cpu.ctc1-fpe-ce` is closed by hw:nemu64-cycle-console, but its verify column does not name it"),
            ("a referenced passing row no question closes", "tools/n64-timing/calibration/questions.tsv",
             lambda t: t.replace(" clock.unit ", " ", 1), "`clock.unit` (derived reference) has no hardware question"),
            ("a not-decidable-by-this-kit entry without what would decide it", "tools/n64-timing/calibration/undecidable.tsv",
             lambda t: t.replace("legacy.cart.rtc-tick\tnot decidable by this kit: ", "legacy.cart.rtc-tick\t", 1),
             "`legacy.cart.rtc-tick` needs a reason `not-hardware-decidable: "),
            ("an inferred row without its inference", TABLE, row_field("cpu.ifill-stall", "note", ""),
             "inferred row `cpu.ifill-stall` has no note. State the inference"),
            ("removing a reference", TABLE, row_field("ri.read-hit", "reference", ""), "has no reference. Cite the hardware reference"),
            ("an unknown check id", TABLE, row_field("ri.read-hit", "verify", "bench:no-such-rom"), "check `bench:no-such-rom` is not defined in tools/n64-timing/checks.tsv. Add a row there"),
            ("two ids for one check", TABLE,
             row_field("rdp.read-gate", "verify", "thar0:imrd-1cycle thar0:nozb-vioff-imrd-1cyc thar0:zcmp hw:thar0-console"),
             "checks `thar0:imrd-1cycle` and `thar0:nozb-vioff-imrd-1cyc` measure the same thing"),
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
            ("an older, slower timing kept as history", WALL_BUDGET,
             lambda t: t.replace("\n", "\nfilesel-rotate\t999\t0000000" + "\t-" * (len(WALL_COLUMNS) - 3) + "\n", 1), None),
            ("one scene re-timed on the standing run, the others stale", (WALL_BUDGET, CLOSURE, WALL_BUDGET),
             (wall_edit(lambda r: r.update(commit=run_commit, same_tree_as="-")), regenerated_closure,
              wall_edit(lambda r: r.update(commit=stale_commit) if r["run"] != "filesel-rotate" else None)),
             f"{CLOSURE} differs from the generated output"),
            ("an empty wall commit", WALL_BUDGET, row_field("sct", "commit", ""), "commit `` is not a 7- to 40-hex commit"),
            ("a short wall commit that prefixes the run's", WALL_BUDGET, row_field("sct", "commit", run_commit[:3]),
             f"commit `{run_commit[:3]}` is not a 7- to 40-hex commit"),
            ("a malformed same_tree_as", WALL_BUDGET, row_field("sct", "same_tree_as", run_commit[:3]),
             f"same_tree_as `{run_commit[:3]}` is not `-` or a 7- to 40-hex commit"),
            ("a scene whose source only mentions the run commit", (WALL_BUDGET, CLOSURE, WALL_BUDGET),
             (wall_edit(lambda r: r.update(commit=run_commit, same_tree_as="-") if r["run"] != "sct" else
                        r.update(commit=stale_commit, same_tree_as=run_commit, source=f"tree identical to {run_commit}")),
              regenerated_closure,
              wall_edit(lambda r: r.update(same_tree_as="-", source=f"not {run_commit}") if r["run"] == "sct" else None)),
             f"{CLOSURE} differs from the generated output"),
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
            ("a suite row whose expected file does not exist", CHECKS,
             lambda t: t.replace("file:tools/n64-timing/romgen/suites/thar0/expected.tsv", "file:tools/n64-timing/no-such.tsv", 1),
             "expects tools/n64-timing/no-such.tsv, which does not exist"),
            ("a bench check without a phase rule", suite_file, lambda t: t.replace("\tcheck\tmean\t", "\tcheck\t-\t", 1),
             "has rule `-`; use consistent, mean, every"),
            ("a bench condition that names no issue", suite_file, lambda t: t.replace("\tcheck\tmean\t#77\t", "\tcheck\tmean\tidle-vi\t", 1),
             "has condition `idle-vi`; write `-`"),
            ("an open item with no blocker row", BLOCKERS, lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("cpu.dcb\t")),
             "open row `cpu.dcb` has no row"),
            ("a blocker row for a check that passes", BLOCKERS, lambda t: t + "unit:timeline\tcheck\tC\t-\tdcb\t-\t-\t-\t-\n",
             "`unit:timeline` is not an open item"),
            ("a C row whose question does not close it", BLOCKERS, row_field("rdp.read-gate", "decider", "ifill"),
             "names question `ifill`, whose closes column does not list `rdp.read-gate`"),
            ("a C row whose question no tool compares", (BLOCKERS, "tools/n64-timing/calibration/questions.tsv"),
             (blocker("cpu.dcb", **{"class": "C"}), row_field("dcb", "kit", "none: self-test")),
             "names question `dcb`, whose kit `none: self-test` no tool compares"),
            ("a C row naming no question", BLOCKERS, row_field("rdp.read-gate", "decider", "no-such-question"),
             "names decider `no-such-question`, which is no questions.tsv id"),
            ("a C row whose question re-runs the row's fit", BLOCKERS,
             lambda t: row_field("rdp.mem-overhead-write", "class", "C")(row_field("rdp.mem-overhead-write", "decider", "thar0-console")(t)),
             "names question `thar0-console`, which re-runs the row's fit"),
            ("a D row on another id's entry", BLOCKERS, row_field("scheduler.tie-rank", "decider", "ri.request-latency"),
             "`scheduler.tie-rank` is class D, so its decider must be its own"),
            ("a check written as follows", BLOCKERS, row_field("thar0:imrd-1cycle", "class", "follows"),
             "`thar0:imrd-1cycle` is class follows, which only a SOFTWARE_READY or MAP_GREEN clause"),
            ("an A row relabeled C on a question that does not close it", BLOCKERS,
             lambda t: row_field("bench:mi-memset-repeat", "class", "C")(row_field("bench:mi-memset-repeat", "decider", "dirty-row")(t)),
             "names question `dirty-row`, whose closes column does not list `bench:mi-memset-repeat`"),
            ("an A row relabeled C with no decider", BLOCKERS,
             lambda t: row_field("legacy.cart.rtc-tick", "class", "C")(row_field("legacy.cart.rtc-tick", "decider", "-")(t)),
             "`legacy.cart.rtc-tick` is class C but names no decider"),
            ("a D row added after the seed, on an entry rewritten not-hardware-decidable", (BLOCKERS, undecidable),
             (blocker("vi.fetch-overrun", **{"class": "D", "decider": "vi.fetch-overrun"}),
              lambda t: t.replace("vi.fetch-overrun\tnot decidable by this kit: ", "vi.fetch-overrun\tnot-hardware-decidable: ", 1)),
             "`vi.fetch-overrun` is class D, but was `B` at the seed commit"),
            ("a D row whose undecidable.tsv entry changed after the seed", undecidable,
             lambda t: t.replace("scheduler.tie-rank\tnot-hardware-decidable: ", "scheduler.tie-rank\tnot-hardware-decidable: now ", 1),
             "`scheduler.tie-rank` is class D, but its undecidable.tsv entry differs from the one at the seed commit"),
            ("an id not in the seed written as D", (BLOCKERS, RESULTS),
             (lambda t: t + "unit:timeline\tcheck\tD\t-\tunit:timeline\t-\t-\t-\t-\n", failing_timeline),
             "`unit:timeline` is class D, but was `-` at the seed commit"),
            ("an id not in the seed made C on a unit whose Scope does not name it", (BLOCKERS, RESULTS),
             (lambda t: t + "unit:timeline\tcheck\tC\t-\tdcb\tU-DOCS\t-\t-\t-\n", failing_timeline),
             "`unit:timeline` was not in the seed, so counts as B at the seed"),
            ("a row seeded A relabeled C with no unit", BLOCKERS,
             blocker("bench:mi-memset-repeat", **{"class": "C", "unit": "-"}),
             "`bench:mi-memset-repeat` was A at the seed, so its unit must be a docs/design/prehw-plan.md section 4 unit whose Scope names `bench:mi-memset-repeat`; `-` is no such unit"),
            ("a row seeded A whose unit's Scope does not name it", BLOCKERS, row_field("bench:mi-memset-repeat", "unit", "U-DOCS"),
             "Scope names `bench:mi-memset-repeat`; `U-DOCS` does not name it"),
            ("a seed cell edited after the seed", BLOCKERS, row_field("cpu.dcb", "seed", "C"),
             "`cpu.dcb` has seed `C`, but its class in tools/n64-timing/calibration/blockers-seed.tsv at the seed commit"),
            ("a blockers-seed.tsv line edited after the seed", BLOCKERS_SEED, lambda t: t.replace("cpu.dcb\tB", "cpu.dcb\tC"),
             "blockers-seed.tsv differs from the file its seed commit"),
            ("a failing clause with no row", BLOCKERS, lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("clause:mg-1\t")),
             "open clause `clause:mg-1` has no row"),
            ("a clause other than mg-4 decided by hw-run", BLOCKERS, blocker("clause:mg-5", **{"class": "C", "decider": "hw-run"}),
             "`clause:mg-5` is a clause of class C, which only clause:mg-4 can be"),
            ("the re-time clause written as C", (RESULTS, BLOCKERS),
             (lambda t: t.replace(run_commit, "0000000", 1),
              lambda t: "".join(l + "\n" for l in t.split("\n") if l and not l.startswith("clause:sr-1\t"))
              + "clause:sr-1\tclause\tC\t-\thw-run\t-\t-\t-\t-\n"),
             "`clause:sr-1` is class C; the re-time clause is A whenever it fails"),
            ("fork values from another run", FORK, lambda t: t.replace(run_commit, "0000000", 1),
             "n64-timing-fork.tsv is from `# standing run"),
            ("a blocker row of the wrong kind", BLOCKERS, row_field("cpu.dcb", "kind", "check"), "`cpu.dcb` is a row, not a check"),
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
            if isinstance(rel, tuple):
                undo = [edit(r, c) for r, c in zip(rel, change)]
                restore = lambda: [u() for u in reversed(undo)]  # noqa: E731
            else:
                restore = edit(rel, change) if rel else None
            errors = check(work) if rel in (None, WALL_BUDGET) or expected is not None else validate(work)[0]
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
        for name, rel, change, want in [
            ("the committed tree, whose A rows only keep clause 2 from holding", None, None, [True, False]),
            ("no blocker table", BLOCKERS, lambda t: None, [False, False]),

            ("a results file whose reader lost every check", RESULTS, lambda t: t.split("\n")[0] + "\ncheck\tresult\tdetail\n",
             [False, False]),
            ("a results file that lost one console question", RESULTS,
             lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("hw:dcb\t")), [False, False]),
            ("the A and B rows relabeled C on the questions that close them", BLOCKERS,
             lambda t: re.sub(r"^([^\t]+\t[^\t]+\t)[AB]\t", r"\1C\t", t, flags=re.M), [True, True, False]),
            ("a checkout whose git history cannot name the seed", "git", None, [True, False, None, None]),
        ]:
            if rel == "git":
                GIT_ROOT[str(work)] = work / "no-such-checkout"
                rel = None
            restore = edit(rel, change if rel != BLOCKERS or name != "no blocker table" else lambda t: t) if rel else None
            if name == "no blocker table":
                (work / BLOCKERS).unlink()
            errors, rows, checks, _ = validate(work)
            found = load_results(work, rows, checks, errors)
            got = [h for _, h, _, _ in predicates(work, rows, checks, found)["PREHW_COMPLETE"]][:len(want)]
            ok = got == want
            print(f"self-test: PREHW_COMPLETE clauses for {name}: {'ok' if ok else 'FAILED'}: {got} (expected {want})")
            failures += not ok
            ran += 1
            GIT_ROOT[str(work)] = root
            if restore:
                restore()
        pin, _ = decomp_pin(work, [])
        objects = f"{CALIBRATION}/{pin.OBJECTS.name}"
        merge_parents = pin.commit_fields(pin.read_objects(pin.OBJECTS)[0][pin.pin_evidence()[0]["merge"][0]][1])[0]["parent"]
        before_merge = f"tree {pin.commit_fields(pin.read_objects(pin.OBJECTS)[0][pin.COMMIT][1])[0]['tree'][0]}\n" \
                       f"parent {merge_parents[0]}\nauthor self-test <self-test@invalid> 0 +0000\n\nself-test: a pin before #1\n"
        fake = pin.git_hash("commit", before_merge.encode())
        repin = lambda sha: lambda t: t.replace(f'COMMIT = "{pin.COMMIT}"', f'COMMIT = "{sha}"')  # noqa: E731
        for name, rel, change, want, expected in [
            ("the committed pin, whose history holds the merge of #1", None, None, (True, "done"), None),
            ("a pin whose history stops before the merge of #1", (MM_BENCH, objects),
             (repin(fake), lambda t: t + f"commit {fake} {len(before_merge)}\n{before_merge}\n"), (False, "not done"),
             f"{CLOSURE} differs from the generated output"),
            ("a pin with no stored commit object", MM_BENCH, repin("0" * 40), (False, "not done"), "has no commit object 0000000"),
            ("a README sentence edited in the stored objects", objects, lambda t: t.replace("so the pin is gone", "so the pin is kept"),
             (True, "not done"), "does not hash to its name"),
        ]:
            undo = [edit(r, c) for r, c in zip(rel, change)] if isinstance(rel, tuple) else [edit(rel, change)] if rel else []
            merged = decomp_merged(work)[0]
            row = next(r for i, r, _ in destination(work, load_results(work, *validate(work)[1:3], [])) if "tools/bench" in i)
            errors = check(work)
            hits = [e for e in errors if expected in e] if expected else errors
            ok = (merged, row) == want and (bool(hits) == (expected is not None))
            print(f"self-test: the mm-decomp-60fps#1 clause and tools/bench row for {name}: {'ok' if ok else 'FAILED'}: "
                  f"clause {merged}, row {row}; {hits[0] if hits else 'no errors'}")
            failures += not ok
            ran += 1
            for u in undo:
                u()
        def only_named(*scenes):
            return wall_edit(lambda r: r.update(commit=run_commit, same_tree_as="-") if r["run"] in scenes
                             else r.update(commit=stale_commit, same_tree_as="-"))
        every_scene = [r["run"] for r in current_walls(work)]
        for name, scenes, want in [
            ("every scene's last wall row names the run's commit", every_scene, True),
            ("only the first scene's last wall row names the run's commit", every_scene[:1], False),
            ("all but one scene's last wall row names the run's commit", every_scene[:-1], False),
            ("no scene's last wall row names the run's commit", [], False),
        ]:
            restore = edit(WALL_BUDGET, only_named(*scenes))
            errors, rows, checks, _ = validate(work)
            found = load_results(work, rows, checks, errors)
            got = predicates(work, rows, checks, found)["SOFTWARE_READY"][0][1]
            ok = got is want
            print(f"self-test: SOFTWARE_READY clause 1 when {name}: {'ok' if ok else 'FAILED'}: {got} (expected {want})")
            failures += not ok
            ran += 1
            restore()
        repeat = ("memset-vi", "mi-memset-repeat/vi-on", "min")
        repeat_fork = fork_cell(*repeat)
        repeat_hi = float(repeat_fork.partition("..")[2])
        uncached = ("memset-vi", "mi-memset-uncached/vi-off", "min")
        uncached_fork = fork_cell(*uncached)
        uncached_hi = float(uncached_fork.partition("..")[2])

        def relabeled(alt, cite="asm.py:170", signed="verify-self-test", fork=repeat_fork, kind="alt"):
            return blocker("bench:mi-memset-repeat", **{
                "class": "C", "decider": "memset-vi", "signed": signed,
                "separates": f"at={' '.join(repeat)};fork={fork};{kind}={alt:g};cite={cite}"})

        def fit_mut(step, cite="U-SEPARATES", searched="NEC VR4300 UM: no value", quantum="", signed="-"):
            return blocker("sysad.rdram-write-period", searched=searched, decider="memset-vi", signed=signed,
                           **{"class": "C"}, separates=f"at={' '.join(uncached)};fork={uncached_fork};"
                                                       f"mut={uncached_hi + step:g};cite={cite}{quantum}")
        one_pclk = ";param=sysad.rdram-write-period;step=1pclk"
        effective = ";param=sysad.rdram-write-period;step=12unit;eq=1"
        for name, rel, change, rid, expected in [
            ("a row seeded A relabeled C on its closing question with a rejected, cited, signed alt", BLOCKERS,
             relabeled(repeat_hi * 1.01), "bench:mi-memset-repeat", None),
            ("a row seeded A relabeled C whose rule accepts its alt", BLOCKERS, relabeled(repeat_hi),
             "bench:mi-memset-repeat", "accepts alt="),
            ("a row seeded A relabeled C on the question that closes it, with free-text separates", BLOCKERS,
             blocker("bench:mi-memset-repeat", **{"class": "C", "decider": "memset-vi", "separates": "the fork against hardware"}),
             "bench:mi-memset-repeat", "separates must read"),
            ("an alt with an empty signed", BLOCKERS, relabeled(repeat_hi * 1.01, signed="-"), "bench:mi-memset-repeat",
             "names an alt with an empty signed"),
            ("an alt of 10x the fork whose cite points at no line", BLOCKERS,
             relabeled(repeat_hi * 10, cite="n64brew MIPS_Interface"), "bench:mi-memset-repeat", "points at no line"),
            ("a fork= cell that differs from the standing run's value", BLOCKERS,
             relabeled(repeat_hi * 1.01, fork=f"{repeat_hi:g}..{repeat_hi + 1:g}"), "bench:mi-memset-repeat",
             "is not the standing run's model side"),
            ("separates on a question that is not the row's decider", BLOCKERS,
             lambda t: relabeled(repeat_hi * 1.01)(t).replace("at=memset-vi ", "at=dirty-row "), "bench:mi-memset-repeat",
             "must name one of its deciders"),
            ("a fit row with mut, no alt, and a cite other than U-SEPARATES", BLOCKERS, fit_mut(8000, cite="U-SB-PR2"),
             "sysad.rdram-write-period", "is a fit row with a mut and no alt"),
            ("a fit row with mut, no alt, and an empty searched", BLOCKERS, fit_mut(8000, searched="-"),
             "sysad.rdram-write-period", "is a fit row with a mut and no alt"),
            ("a fit row's resolution mutation within 4 tolerances, cited U-SEPARATES with its search", BLOCKERS,
             fit_mut(8000), "sysad.rdram-write-period", None),
            ("a mut past 4 tolerances", BLOCKERS, fit_mut(30000), "sysad.rdram-write-period", "past 4: the question cannot resolve"),
            ("a one-quantum mut far past 4 tolerances, signed", BLOCKERS,
             fit_mut(300000, quantum=one_pclk, signed="verify-self-test"), "sysad.rdram-write-period", None),
            ("a one-quantum mut far past 4 tolerances with an empty signed", BLOCKERS, fit_mut(300000, quantum=one_pclk),
             "sysad.rdram-write-period", "names a one-quantum mut of `sysad.rdram-write-period` with an empty signed"),
            ("a two-quantum mut past 4 tolerances, signed", BLOCKERS,
             fit_mut(300000, quantum=one_pclk.replace("step=1", "step=2"), signed="verify-self-test"),
             "sysad.rdram-write-period", "past 4: the question cannot resolve"),
            ("a one-quantum mut with no param", BLOCKERS,
             fit_mut(300000, quantum=";step=1pclk", signed="verify-self-test"), "sysad.rdram-write-period",
             "but no param="),
            ("a one-quantum mut whose step names no unit", BLOCKERS,
             fit_mut(300000, quantum=one_pclk.replace("1pclk", "1"), signed="verify-self-test"),
             "sysad.rdram-write-period", "must read <count><unit>"),
            ("a one-quantum mut the rule accepts", BLOCKERS,
             fit_mut(0, quantum=one_pclk, signed="verify-self-test"), "sysad.rdram-write-period", "accepts mut="),
            ("an effective-quantum mut (eq=1, 12 stored units) far past 4 tolerances, signed", BLOCKERS,
             fit_mut(300000, quantum=effective, signed="verify-self-test"), "sysad.rdram-write-period", None),
            ("an effective-quantum mut with an empty signed", BLOCKERS, fit_mut(300000, quantum=effective),
             "sysad.rdram-write-period", "names a one-quantum mut of `sysad.rdram-write-period` with an empty signed"),
            ("a 12-unit mut without eq=1 past 4 tolerances, signed", BLOCKERS,
             fit_mut(300000, quantum=effective.replace(";eq=1", ""), signed="verify-self-test"),
             "sysad.rdram-write-period", "past 4: the question cannot resolve"),
            ("an eq= other than 1", BLOCKERS,
             fit_mut(300000, quantum=effective.replace("eq=1", "eq=2"), signed="verify-self-test"),
             "sysad.rdram-write-period", "must read eq=1"),
            ("an eq=1 effective-quantum mut with step count 0", BLOCKERS,
             fit_mut(300000, quantum=effective.replace("12unit", "0unit"), signed="verify-self-test"),
             "sysad.rdram-write-period", "must have a count of 1 or more"),
            ("an eq=1 with no param or step", BLOCKERS, fit_mut(300000, quantum=";eq=1", signed="verify-self-test"),
             "sysad.rdram-write-period", "separates must read"),
            ("an effective-quantum mut the rule accepts", BLOCKERS,
             fit_mut(0, quantum=effective, signed="verify-self-test"), "sysad.rdram-write-period", "accepts mut="),
            ("a mut whose cite is no unit", BLOCKERS, fit_mut(8000, cite="scratch-build"), "sysad.rdram-write-period",
             "whose cite `scratch-build` is no section 4 unit"),
            ("an out-of-kit row whose unit is U-SEPARATES with an empty signed", BLOCKERS,
             blocker("legacy.cart.rtc-tick", **{"class": "C", "decider": "legacy.cart.rtc-tick", "unit": "U-SEPARATES"}),
             "legacy.cart.rtc-tick", "signed is empty"),
            ("an out-of-kit row seeded A on its own unit with an empty signed", BLOCKERS,
             blocker("legacy.cart.rtc-tick", **{"class": "C", "decider": "legacy.cart.rtc-tick"}),
             "legacy.cart.rtc-tick", "signed is empty"),
            ("an out-of-kit row seeded A with its limit signed", BLOCKERS,
             blocker("legacy.cart.rtc-tick", **{"class": "C", "decider": "legacy.cart.rtc-tick", "signed": "verify-self-test"}),
             "legacy.cart.rtc-tick", None),
            ("clause:mg-4 without the dry-run result", DRY_RUN, lambda t: "\n".join(t.split("\n")[:2]) + "\n",
             INGESTION_CLAUSE, "did not move"),
        ]:
            restore = edit(rel, change)
            errors, rows, checks, _ = validate(work)
            found = load_results(work, rows, checks, errors)
            _, _, problems, _, _ = blocker_audit(work, rows, found, predicates(work, rows, checks, found))
            mine = [why for _, why in problems.get(rid, [])]
            hits = mine if expected is None else [w for w in mine if expected in w]
            ok = not mine if expected is None else bool(hits)
            print(f"self-test: blocker rule for {name}: {'ok' if ok else 'FAILED'}: "
                  f"{(hits or mine or ['no problem'])[0] if ok or expected is None else f'no problem contains `{expected}`; got {mine[:2]}'}")
            failures += not ok
            ran += 1
            restore()
        seed = blocker_seed(work)[0]
        restore = [edit(rel, lambda t: t + "# seed 0000000000000000000000000000000000000000\n") for rel in (BLOCKERS, BLOCKERS_SEED)]
        moved = blocker_seed(work)[0]
        ok = seed is not None and moved == seed
        print(f"self-test: a `# seed` line in either file leaves the computed seed: {'ok' if ok else 'FAILED'}: {seed} -> {moved}")
        failures += not ok
        ran += 1
        for undo in restore:
            undo()
        restore = edit(RESULTS, lambda t: re.sub(r"^(hw:[^\t]+)\tpending:calibration-16\t", r"\1\tpass\t", t, flags=re.M))
        gen, _, blockers = generated(work)
        ok = not gen and any("is not an open item" in e for e in blockers)
        print(f"self-test: a console run that passes every hw:* check regenerates the spec (ingest, dry-run.sh) and "
              f"leaves its closed items' blocker rows to --check: {'ok' if ok else 'FAILED'}: {len(gen)} generation errors, "
              f"{sum('is not an open item' in e for e in blockers)} stale rows")
        failures += not ok
        ran += 1
        restore()
        for rule, model, value, want in [("exact", "3,5", "5", (True, None)), ("exact", "3,5", "4", (False, None)),
                                         ("range:abs:2", "10..12", "14", (True, 1.0)), ("range:abs:2", "10..12", "15", (False, 1.5)),
                                         ("range:rel:1", "200..200", "203", (False, 1.5)),
                                         ("systembench:RCP", "193..193", "195", (True, 2 / 2)),
                                         ("systembench:RCP", "193..193", "196", (False, 3 / 2))]:
            got = judge(rule, model, value)
            ok = got[0] == want[0] and (got[1] is None) == (want[1] is None) and (got[1] is None or abs(got[1] - want[1]) < 1e-9)
            print(f"self-test: rule {rule} on fork {model}, console {value}: {'ok' if ok else 'FAILED'}: {got} (expected {want})")
            failures += not ok
            ran += 1
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
                "verdict", "mean_verdict", "window_pct", "pad_verdicts", "pad_phases", "source"]
        stale = ["r", "p8", "m", "180.0", "189.0", "194.67", "189.0", "193", "191.07", "194.93", "check", "consistent", "-",
                 "pass", "-", "-", "pass,pass", "0:180.0..194.67/189.0 4:180.0..194.67/189.0", "s"]
        split = ["r", "rspdma", "m", "6.272", "6.498", "6.502", "6.494", "6.5", "6.49", "6.515", "check", "mean", "-",
                 "pass", "-", "-", "pass,pass", "0:6.492..6.501/6.498 4:6.272..6.502/6.489", "s"]
        (run / "bench" / "results.tsv").write_text("\n".join("\t".join(r) for r in (cols, stale, split)) + "\n", encoding="utf-8")
        for name, selector in (("a consistent pass whose mean misses the band", "point=p8"),
                               ("a pass at layout pad 0 and a fail at pad 4", "point=rspdma")):
            got = bench_result(run, {"target": "r", "selector": selector})
            ok = got is not None and got[0] == "consistent-only"
            print(f"self-test: {name}, in a results.tsv that calls it pass: {'ok' if ok else 'FAILED'}: {got} (expected consistent-only)")
            failures += not ok
            ran += 1
        (run / "cpu" / "s").mkdir(parents=True)
        for name, summary, want in [
            ("a cpu ROM whose tests all pass", "CPU: Failed 0 of 12 tests (100% success rate)\n", "pass"),
            ("a cpu ROM with one failing test", "CPU: Failed 1 of 12 tests (91% success rate)\n", "fail"),
            ("a cpu ROM that never printed its verdict", "n64-run: stop=wall-limit\n", "fail"),
        ]:
            (run / "cpu" / "s" / "summary.txt").write_text(summary, encoding="utf-8")
            got = cpu_result(run, {"target": "s"})
            listed = "cpu" in failing_suites([("cpu:s", got[0], got[1])])
            ok = got[0] == want and listed == (want != "pass")
            print(f"self-test: {name}: {'ok' if ok else 'FAILED'}: {got}, failing list {'names' if listed else 'omits'} cpu "
                  f"(expected {want})")
            failures += not ok
            ran += 1
        (run / "systembench").mkdir()
        cols = ["row", "name", "qty", "unit", "expected", "pristine", "min", "max", "runs", "runs_pass", "verdict", "kind", "port"]
        sb = [["a", "A", "4", "RCP", "134", "134", "134", "134", "33", "33", "pass", "check", "r p"],
              ["b", "B", "4", "RCP", "134", "130", "129", "130", "33", "0", "fail", "check", "r p"]]
        (run / "systembench" / "results.tsv").write_text("\n".join("\t".join(r) for r in [cols] + sb) + "\n", encoding="utf-8")
        got = systembench_result(run, {"target": "b"})
        ok = got is not None and got[0] == "fail" and "130 RCP cycles, 129..130" in got[1] and "-4" in got[1]
        print(f"self-test: a systembench row that fails at every run: {'ok' if ok else 'FAILED'}: {got} (expected fail, 130, -4)")
        failures += not ok
        ran += 1
        (run / "pidma").mkdir()
        for word, want in (("PASS", "pass"), ("FAIL", "fail"), ("UNCHECKED", "pending:replay-unchecked")):
            (run / "pidma" / "summary.txt").write_text(f"24512 points timed\npidma: {word}: exact COUNT replay\n", encoding="utf-8")
            got = pidma_result(run, {})
            ok = got is not None and got[0] == want
            print(f"self-test: a pidma replay that reads {word}: {'ok' if ok else 'FAILED'}: {got} (expected {want})")
            failures += not ok
            ran += 1
        git = ["git", "-C", str(work), "-c", "user.name=self-test", "-c", "user.email=self-test@invalid"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "scoring tree"], check=True)
        head = subprocess.run(git + ["rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        elsewhere = "0123abcde" if not head.startswith("0123abcde") else "fedc98765"
        stamp = work / "self-test-stamp" / "standing"
        stamp.mkdir(parents=True)
        for name, record, given, want in [
            ("a run made on another commit", f"{elsewhere}\n", None, f"on {elsewhere}"),
            ("a run made on a dirty tree", f"{elsewhere} dirty\n", None, f"on {elsewhere} with uncommitted changes"),
            ("a run with no record, given --run-commit", None, elsewhere, f"on {elsewhere}"),
            ("a run with no record", None, None, "--run-commit"),
            ("a record that --run-commit contradicts", f"{elsewhere}\n", "fedcba987", "Drop --run-commit"),
        ]:
            (stamp / RUN_COMMIT).unlink(missing_ok=True)
            if record:
                (stamp / RUN_COMMIT).write_text(record, encoding="utf-8")
            (work / RESULTS).unlink(missing_ok=True)
            cmd = [sys.executable, str(work / "tools/n64-timing/behaviors.py"), "--root", str(work), "--results", str(stamp)]
            proc = subprocess.run(cmd + (["--run-commit", given] if given else []), capture_output=True, text=True)
            first = text(work / RESULTS)
            first = (first or proc.stderr).split("\n")[0]
            ok = want in first and head not in first and (want.startswith("on ") or not (work / RESULTS).exists())
            print(f"self-test: the results header for {name}: {'ok' if ok else 'FAILED'}: {first.strip()[:160]} "
                  f"(expected `{want}`, never the scoring HEAD {head})")
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
    parser.add_argument("--failing", metavar="RUN_DIR")
    parser.add_argument("--run-commit", metavar="SHA", help=f"the commit a --results run was made on, for a run without {RUN_COMMIT}")
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
    if args.failing:
        suites = failing_suites(results(root, args.failing)[1])
        for suite, checks in sorted(suites.items()):
            print(f"failing suite {suite}: {len(checks)} check(s): {', '.join(checks)}")
        print(f"behaviors.py: failing: {len(suites)} suite(s) in {run_label(args.failing)}")
        return 1 if suites else 0
    if args.results:
        commit, error = run_commit(args.results, args.run_commit)
        if error:
            return report([error], "results")
        errors, out = results(root, args.results)
        write_results(root, args.results, out, commit)
        print(f"behaviors.py: wrote {RESULTS} ({len(out)} checks); run behaviors.py to regenerate the spec")
        print(f"behaviors.py: wrote {FORK} ({write_fork_values(root, args.results, commit)} fork values)")
        status, moved, tail = write_dry_run(root, args.results, commit)
        print(f"behaviors.py: wrote {DRY_RUN} ({moved} hw checks after calibration/dry-run.sh)")
        if status:
            errors.append(f"calibration/dry-run.sh on {run_label(args.results)}/calib exited {status}: {tail[0] if tail else ''}")
        return report(errors, "results") if errors else 0
    errors, outputs, _ = generated(root)
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
