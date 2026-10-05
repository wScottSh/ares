#!/usr/bin/env python3
"""Parses one nemu64-test run's guest output into per-test results.

usage: nemu64-results.py STDOUT_TXT OUT_DIR

Writes OUT_DIR/tests.tsv (test name, failed value count, pass/fail) and
OUT_DIR/failures.txt (every failure message, in order), and prints the ROM's own
category summary lines ("Timing: Failed X of Y tests ...") to stdout.
"""
import re
import sys
from collections import OrderedDict

RUNNING = re.compile(r"^Running (.+)\.\.\.$")
FAILURE = re.compile(r"^Test '.+ failed")
SUMMARY = re.compile(r"(Base|Timing|Cycle|CP0-hazards|Poorly-understood-quirk): Failed (\d+) of (\d+) tests")


def main():
    stdout_path, out_dir = sys.argv[1:3]
    text = open(stdout_path, encoding="utf-8", errors="replace").read()

    failures = OrderedDict()
    order = []
    failure_lines = []
    summary = []
    current = None
    for line in text.splitlines():
        if m := RUNNING.match(line):
            current = m.group(1)
            order.append(current)
            failures.setdefault(current, 0)
        elif FAILURE.match(line):
            # A failure line names its test, but the name can contain quotes. The
            # enclosing "Running" block is the authoritative owner.
            failures[current] = failures.get(current, 0) + 1
            failure_lines.append(line)
        elif m := SUMMARY.search(line):
            summary.append(line[m.start():].strip())

    with open(f"{out_dir}/tests.tsv", "w", encoding="utf-8", newline="\n") as out:
        out.write("test\tfailed_values\tresult\n")
        for name in order:
            count = failures[name]
            out.write(f"{name}\t{count}\t{'fail' if count else 'pass'}\n")
    with open(f"{out_dir}/failures.txt", "w", encoding="utf-8", newline="\n") as out:
        out.write("\n".join(failure_lines) + ("\n" if failure_lines else ""))

    finished = any(line.startswith("n64-systemtest ") for line in text.splitlines())
    if not finished:
        print("no final summary in guest output (ROM did not finish)")
    for line in summary:
        print(line)
    print(f"tests run: {len(order)}, tests with failures: {sum(1 for n in order if failures[n])}, failure lines: {len(failure_lines)}")


if __name__ == "__main__":
    main()
