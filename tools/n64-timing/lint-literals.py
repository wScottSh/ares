#!/usr/bin/env python3
"""Rejects timing literals in ares/n64 that do not come from ares/n64/timing/behaviors.tsv.

usage: lint-literals.py [--root DIR] [--emit]

A timing literal is a nonzero number in an expression that charges or schedules
time: the arguments of step(), queueInsert() or a *Queue() call, the right side
of an assignment to a name ending in clock, cycle, duration, period, latency,
delay, frequency, timing or timeout, a return inside a function with such a
name, or any line that uses a *Ms millisecond constant.

Today's core still has such literals. tools/n64-timing/literal-allowlist.tsv pins
each one to the legacy behavior row that records it, and the row's value must
appear on the line (as a literal, or as the value of a constant expression such
as `10240 * 8`). An entry bound to `-` is a number in a timing expression that is
not a cost (a register encoding, a division guard, a host-only debugger poll);
its note says which. The allowlist only shrinks: a unit that replaces a legacy
cost deletes its entries and its row, and plan T13 empties it.

--emit prints every unlisted site as an allowlist line with an empty rows column.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ALLOWLIST = "tools/n64-timing/literal-allowlist.tsv"
BEHAVIORS = "ares/n64/timing/behaviors.tsv"
GENERATED = "ares/n64/timing/behaviors.hpp"
SCAN_ROOT = "ares/n64"
#Not part of the target console (map #1: NTSC retail NUS-001 with Expansion Pak).
OUT_OF_SCOPE = {
    "ares/n64/dd/": "64DD add-on drive",
    "ares/n64/aleck64/": "Aleck 64 arcade board",
}

TIMING_WORD = r"(?:[Cc]locks?|[Cc]ycles?|[Dd]uration|[Pp]eriod|[Ll]atency|[Dd]elay|[Ff]requency|[Tt]iming|[Tt]imeout)"
FUNCTION = re.compile(r"^\s*(?:inline\s+|static\s+)*auto\s+([\w:]+)\s*\(")
CALL = re.compile(r"\b(?:step|queueInsert|queue\.insert|\w*Queue)\s*\(")
ASSIGN = re.compile(r"\b\w*" + TIMING_WORD + r"\s*(?:[-+*/]=|<<=|>>=|=(?!=))")
MILLISECONDS = re.compile(r"\b\w+Ms\b")
RETURN = re.compile(r"\breturn\b")
TIMING_FUNCTION = re.compile(TIMING_WORD)
NUMBER = re.compile(r"(?<![\w.'])(0[xX][0-9a-fA-F']+|\d[\d']*(?:\.\d+)?)[uUlLfF]*(?![\w.'])")
NOT_TIME = re.compile(r"\.(?:bit|byte|field)\s*\([^()]*\)|\[[^\[\]]*\]")
CONSTANT_EXPRESSION = re.compile(r"^[\s\d'xXa-fA-F()+\-*/<>]+$")


def strip_code(text):
    """Blanks comments, string and character literals; keeps line breaks."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in text[i:j]))
            i = j
        elif c in "\"'" and not (c == "'" and i > 0 and text[i - 1].isalnum()):
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(" " * (min(j + 1, n) - i))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def expression(code, start, inside_call):
    """Returns code from start to the call's closing parenthesis, or to the end of the assigned expression."""
    depth = 0
    for i in range(start, len(code)):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                return code[start:i]
            depth -= 1
        elif c in ";," and depth == 0 and not inside_call:
            return code[start:i]
    return code[start:]


def timing_expressions(code, function):
    if FUNCTION.match(code):
        return []
    if MILLISECONDS.search(code):
        return [code]
    parts = [expression(code, m.end(), True) for m in CALL.finditer(code)]
    parts += [expression(code, m.end(), False) for m in ASSIGN.finditer(code)]
    if TIMING_FUNCTION.search(function):
        parts += [expression(code, m.end(), False) for m in RETURN.finditer(code)]
    return parts


def as_number(token):
    token = token.replace("'", "")
    value = int(token, 16) if token.lower().startswith("0x") else float(token)
    return int(value) if value == int(value) else value


def literals(part):
    return [v for v in map(as_number, NUMBER.findall(NOT_TIME.sub(" ", part))) if v != 0]


def constant_value(part):
    """The value of a timing expression made only of literals, such as `10240 * 8`, else None."""
    for piece in (part, part.split(",")[-1]):
        piece = piece.strip()
        if piece and CONSTANT_EXPRESSION.match(piece) and NUMBER.search(piece):
            python = NUMBER.sub(lambda m: str(as_number(m.group(1))), piece).replace("/", "//")
            try:
                return eval(python, {"__builtins__": {}})
            except Exception:
                return None
    return None


def scan(root):
    """Yields one dict per timing-literal site: path, line, function, occurrence, source, values."""
    root = Path(root)
    files = sorted(p for p in (root / SCAN_ROOT).rglob("*") if p.suffix in (".cpp", ".hpp"))
    for path in files:
        rel = path.relative_to(root).as_posix()
        if rel == GENERATED or rel.startswith(tuple(OUT_OF_SCOPE)):
            continue
        raw = path.read_text(encoding="utf-8", errors="replace").split("\n")
        code = strip_code("\n".join(raw)).split("\n")
        function = "-"
        occurrences = Counter()
        for number, (source, stripped) in enumerate(zip(raw, code), 1):
            if m := FUNCTION.match(stripped):
                function = m.group(1).split("::")[-1]
            parts = timing_expressions(stripped, function)
            values = [v for part in parts for v in literals(part)]
            if not values:
                continue
            values += [v for v in map(constant_value, parts) if v is not None and v not in values]
            occurrences[(function, source.strip())] += 1
            yield {"path": rel, "line": number, "function": function,
                   "occurrence": occurrences[(function, source.strip())], "source": source.strip(), "values": values}


def load_allowlist(root):
    """Returns entries: dicts with path, function, occurrence (None = every occurrence), source, rows, note, entry."""
    entries = []
    path = Path(root) / ALLOWLIST
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if number == 1 or not line:
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            raise SystemExit(f"{ALLOWLIST}:{number}: expected 5 tab-separated columns (path function line rows note)")
        rel, function, source, rows, note = fields
        function, _, occurrence = function.partition("#")
        entries.append({"path": rel, "function": function, "occurrence": int(occurrence) if occurrence else None,
                        "source": source, "rows": rows.split(), "note": note, "entry": number})
    return entries


def find_entry(entries, site):
    for e in entries:
        if (e["path"], e["function"], e["source"]) == (site["path"], site["function"], site["source"]) and \
                e["occurrence"] in (None, site["occurrence"]):
            return e
    return None


def load_values(root):
    values = {}
    lines = (Path(root) / BEHAVIORS).read_text(encoding="utf-8").split("\n")
    for line in lines[1:]:
        if line:
            fields = line.split("\t")
            values[fields[0]] = fields[1] if len(fields) > 1 else ""
    return values


def number_of(text):
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value == int(value) else value


def lint(root):
    """Returns (errors, sites); sites maps each behavior id to the [(path, line)] sites bound to it."""
    entries = load_allowlist(root)
    values = load_values(root)
    errors = []
    sites = {}
    used = set()
    for site in scan(root):
        where = f"{site['path']}:{site['line']}"
        entry = find_entry(entries, site)
        if entry is None:
            errors.append(
                f"{where}: timing literal {site['values']} in `{site['source']}`. Add a row to {BEHAVIORS}, run "
                f"tools/n64-timing/behaviors.py, and read the value as Timing::Behavior::<Name> from {GENERATED}.")
            continue
        used.add(entry["entry"])
        if entry["rows"] == ["-"]:
            if not entry["note"]:
                errors.append(f"{ALLOWLIST}:{entry['entry']}: a `-` entry needs a note saying why the number is not a cost.")
            continue
        for row in entry["rows"]:
            sites.setdefault(row, []).append((site["path"], site["line"]))
            if row not in values:
                errors.append(f"{ALLOWLIST}:{entry['entry']}: row `{row}` is not in {BEHAVIORS}. Name an existing legacy row.")
            elif number_of(values[row]) is None:
                errors.append(f"{ALLOWLIST}:{entry['entry']}: row `{row}` has no numeric value. Bind the site to a row with a number.")
            elif number_of(values[row]) not in site["values"]:
                errors.append(
                    f"{where}: row `{row}` = {values[row]} but `{site['source']}` holds {site['values']}. "
                    f"Make {BEHAVIORS} and the code agree.")
    for entry in entries:
        if entry["entry"] not in used:
            errors.append(
                f"{ALLOWLIST}:{entry['entry']}: no line `{entry['source']}` in {entry['path']} function {entry['function']}. "
                f"If the code no longer charges this cost, delete the entry, and delete its legacy row once no entry names it.")
    return errors, sites


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    if args.emit:
        entries = load_allowlist(args.root) if (Path(args.root) / ALLOWLIST).exists() else []
        for site in scan(args.root):
            if find_entry(entries, site) is None:
                print(f"{site['path']}\t{site['function']}#{site['occurrence']}\t{site['source']}\t\t{site['values']}")
        return 0
    errors, _ = lint(args.root)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"lint-literals: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("lint-literals: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
