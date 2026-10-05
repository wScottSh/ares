"""Root-cause categories C1-C11 from docs/research/nemu64-timing-failures.md (branch
research/nemu64-timing-failures), as rules over a failing value's test name and description.
"""
import re

# "other" collects failures outside the interpreter baseline's categories (the recompiler's
# uncached write-buffer failures, for one).
CATEGORIES = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "other"]

LIKELY_BRANCH = re.compile(r"\b(BEQL|BNEL|BLEZL|BGTZL|BLTZL|BGEZL|BLTZALL|BGEZALL)\b")


def _first_mismatch(measured, expected):
    for m, e in zip(measured.split(","), expected.split(",")):
        if m != e:
            return int(m), int(e)
    return None


def classify(test, desc, measured="", expected=""):
    if test == "Timing: Exceptions":
        return "C1"
    if test.startswith("Timing: COP1 instruction"):
        return "C1" if ("JustFire" in desc or "Roundtrip" in desc) else "C3"
    if test == "Timing: COP1 register dependency":
        return "C3" if "trivial" in desc else "C4"
    if test in ("Timing: Cached loads and store (with warm cache)", "Timing: Data cache Size"):
        return "C2"
    if test == "Timing: Individual instructions (CPU)":
        return "C5"
    if test == "Timing: CPU register dependency":
        name = desc.split('"')[1] if '"' in desc else desc
        if "MTC0" in name:
            return "C5"
        if "CACHE" in name:
            return "C10"
        # MFC0 as the producer has no load-style interlock (C9); as a consumer after a load
        # it fails for the flat load cost (C2).
        if name.startswith(("MFC0", "DMFC0")):
            return "C9"
        # A likely branch that came out short lost its nullified delay-slot cycle (C8); one
        # that came out long paid the flat cached-load cost (C2).
        mismatch = _first_mismatch(measured, expected)
        if LIKELY_BRANCH.search(name) and mismatch and mismatch[0] < mismatch[1]:
            return "C8"
        return "C2"
    if test.startswith("Timing: Load from uncached"):
        return "C6"
    if test.startswith("Timing: Load Miss"):
        return "C7"
    if test.startswith("Timing: Likely branch"):
        return "C8"
    if test == "Compare (signalling 2)":
        return "C9"
    if test.startswith("Random"):
        return "C11"
    return "other"
