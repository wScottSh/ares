"""Joins a romgen ROM's per-value records with its build listing.

usage: python -m romgen.report TESTS_TSV STDOUT_TXT OUT_DIR

TESTS_TSV is the <rom>.tests.tsv build.py writes; STDOUT_TXT is the ROM's guest output. Writes
OUT_DIR/values.tsv (one row per value: result, measured and expected cycles) and, for suites
with a root-cause classifier, OUT_DIR/categories.tsv; prints the category counts.
"""
import os
import re
import sys

RECORD = re.compile(r"^@(\d+)\.(\d+) (\d)((?: \d+)*)$")
RESULT = {"0": "pass", "1": "fail", "2": "exception"}


def load(tests_tsv, stdout_txt):
    listing = {}
    with open(tests_tsv, encoding="utf-8") as f:
        next(f)
        for line in f:
            index, test, desc, expected = line.rstrip("\n").split("\t")
            listing[index] = (test, desc, expected)
    rows = []
    with open(stdout_txt, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RECORD.match(line.rstrip("\n"))
            if m:
                index = f"{m.group(1)}.{m.group(2)}"
                test, desc, expected = listing[index]
                measured = ",".join(m.group(4).split())
                rows.append((index, test, desc, RESULT[m.group(3)], measured, expected))
    missing = len(listing) - len(rows)
    return rows, missing


def main():
    tests_tsv, stdout_txt, out_dir = sys.argv[1:4]
    rows, missing = load(tests_tsv, stdout_txt)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "values.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("index\ttest\tvalue\tresult\tmeasured_cycles\texpected_cycles\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    if missing:
        print(f"{missing} values have no record (ROM did not finish)")
    rom = os.path.basename(tests_tsv).split(".")[0]
    if rom == "nemu64-timing":
        from .suites.nemu64.categories import classify, CATEGORIES
        counts = {c: 0 for c in CATEGORIES}
        with open(os.path.join(out_dir, "categories.tsv"), "w", encoding="utf-8", newline="\n") as f:
            f.write("index\tcategory\ttest\tvalue\tmeasured_cycles\texpected_cycles\n")
            for index, test, desc, result, measured, expected in rows:
                if result == "pass":
                    continue
                c = classify(test, desc, measured, expected)
                counts[c] += 1
                f.write(f"{index}\t{c}\t{test}\t{desc}\t{measured}\t{expected}\n")
        print("category\tfailures\t" + "\t".join(CATEGORIES))
        print("count\t" + str(sum(counts.values())) + "\t" + "\t".join(str(counts[c]) for c in CATEGORIES))


if __name__ == "__main__":
    main()
