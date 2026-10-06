#!/usr/bin/env python3
"""Rewrites the operative program files under docs/program/ from the original
Windows machine's paths to a Linux host's. Rerunnable: a second run changes nothing.
Reports under docs/program/reports/ are a historical record and are not rewritten.

usage: program-paths.py [--home /home/wscottsh] [--check]
"""
import argparse
import pathlib
import re
import sys

FILES = ["README.md", "handoff.md", "preferences.md", "followups.md", "resolve.sh", "map_add.py"]
SEP = r"[\\/]"
WIN_HOME = r"(?:C:[\\/]Users[\\/]Scott|/c/Users/Scott)"
LEFTOVER = re.compile(r"C:[\\/]|/c/Users|Windows 11|Git Bash|C:/ form")


def rules(home):
    mm_rom = f"{home}/repos/mm-decomp-60fps/baseroms/n64-us/baserom.z64"
    return [
        (WIN_HOME + SEP + r"PARA" + SEP + r"3-Resources" + SEP + r"Emulation" + SEP + r"ROMs" + SEP + r"N64" + SEP
         + r"Legend of Zelda - Majora's Mask\.v64", mm_rom),
        (WIN_HOME + SEP + r"AppData" + SEP + r"Local" + SEP + r"Temp" + SEP + r"claude" + SEP + r"[^\s`]*?" + SEP
         + r"scratchpad" + SEP + r"jgcen64", f"{home}/n64-timing/scratch/jgcen64"),
        (WIN_HOME + SEP + r"\.claude" + SEP + r"plugins" + SEP + r"cache" + SEP + r"pstack-claude" + SEP + r"pstack"
         + SEP + r"0\.9\.67", f"{home}/.claude/plugins/cache/pstack-claude/pstack/<installed-version>"),
        (r"\s*\((?:pass in )?C:/ form(?:; apostrophe)?\)", ""),
        (r"\s*\(gotcha: pass the ROM as C:/\.\.\. path; apostrophe in the name\)", ""),
        (r"Platform: Windows 11, Git Bash(?: for the Bash tool)?(?: \(PowerShell also available\))?\.",
         "Platform: Linux (Ubuntu), bash."),
        (r"Windows 11, x86-64 desktop", "Linux, 32-core x86-64 host"),
        (r"n64-run\.exe", "n64-run"),
        (WIN_HOME + r"((?:" + SEP + r"[^\s`'\")\]]*)?)", None),
    ]


def rewrite(text, home):
    for pattern, repl in rules(home):
        if repl is None:
            text = re.sub(pattern, lambda m: home + m.group(1).replace("\\", "/"), text)
        else:
            text = re.sub(pattern, repl, text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default="/home/wscottsh")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = pathlib.Path(__file__).resolve().parents[2] / "docs" / "program"
    paths = [root / f for f in FILES] + sorted((root / "briefs").glob("*.md"))
    changed = []
    for p in paths:
        old = p.read_text(encoding="utf-8")
        new = rewrite(old, args.home)
        if new != old:
            changed.append(p.name)
            if not args.check:
                p.write_text(new, encoding="utf-8", newline="\n")
    print(f"{'would change' if args.check else 'changed'}: {changed or 'nothing'}")
    # harness.md is the finished pilot's brief; its Windows toolchain text is the record of what it ran on.
    leftover = [f"{p.name}:{i}: {line.strip()}" for p in paths if p.name != "harness.md"
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if LEFTOVER.search(line)]
    for line in leftover:
        print("leftover:", line)
    sys.exit(1 if (args.check and changed) or leftover else 0)


if __name__ == "__main__":
    main()
