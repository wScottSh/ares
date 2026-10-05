"""Writes expected.tsv from Thar0/RDP-Timing-Tests' hardware results.

usage: python -m romgen.suites.thar0.import_hw CLONE_DIR [OUT_TSV]

Reads `hw_data` from CLONE_DIR/compare.py as text (ast, never executed) and checks it against
the per-spec values in CLONE_DIR/sample_results.txt. Both give milliseconds from analyze.py's
rdp_clk_to_ms (clk / 62500); expected.tsv stores RDP counter clocks, min and max exact.
"""
import ast
import os
import re
import sys

from .configs import SPECS

CLK_PER_MS = 62500
HEADER = ["index", "id", "buf_min", "buf_avg", "buf_max", "pipe_min", "pipe_avg", "pipe_max", "desc"]


def hw_data(compare_py):
    tree = ast.parse(open(compare_py, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "hw_data":
            return ast.literal_eval(node.value)
    raise SystemExit(f"{compare_py}: no hw_data")


def sample_results(path):
    rows = []
    pending = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*(Buf|Pipe):\s+([\d.]+)ms, ([\d.]+)ms, ([\d.]+)ms", line)
        if not m:
            continue
        values = tuple(float(v) for v in m.group(2, 3, 4))
        if m.group(1) == "Buf":
            pending = values
        else:
            rows.append((pending, values))
    return rows


def clocks(ms):
    return ms * CLK_PER_MS


def main():
    clone = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "expected.tsv")
    hw = hw_data(os.path.join(clone, "compare.py"))
    sample = sample_results(os.path.join(clone, "sample_results.txt"))
    assert len(hw) == len(SPECS) == len(sample) == 100, (len(hw), len(sample))
    mismatched = [i for i, (h, s) in enumerate(zip(hw, sample)) if h != s]
    print(f"hw_data vs sample_results.txt: {100 - len(mismatched)}/100 specs identical"
          + (f"; differ at {mismatched}" if mismatched else ""))
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(HEADER) + "\n")
        for i, (spec, (buf, pipe)) in enumerate(zip(SPECS, hw)):
            cols = []
            for lo, avg, hi in (buf, pipe):
                for v in (lo, hi):
                    assert abs(clocks(v) - round(clocks(v))) < 1e-6, (i, v)
                cols += [str(round(clocks(lo))), f"{clocks(avg):.3f}", str(round(clocks(hi)))]
            f.write("\t".join([str(i), spec.id, *cols, spec.desc]) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
