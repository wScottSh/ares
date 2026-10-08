"""Parses bench ROM output, derives the cited metrics, and joins them with expected.tsv.

usage: python -m romgen.suites.bench.report ROMS_DIR RESULTS_DIR ROM...

Reads RESULTS_DIR/<rom>/stdout.txt and ROMS_DIR/bench-<rom>.tests.tsv. Writes
RESULTS_DIR/measurements.tsv (every raw and derived value per point) and RESULTS_DIR/results.tsv
(one row per expected.tsv entry with its verdict). Exits 1 when a ROM did not print every point
its listing promises, which is the format check; value verdicts never change the exit code.

Units: COUNT ticks at 46.875 MHz; pclk = 2 ticks (VR4300 93.75 MHz); rclk = 4/3 ticks (RCP
62.5 MHz); DPC clock values are the raw DPC_CLOCK register.
"""
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIB = 1 << 20
TICKS_PER_MS = 46875


def parse(stdout_txt):
    points = {}
    with open(stdout_txt, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3 or parts[0] != "#bench":
                continue
            fields = points.setdefault(parts[2], {})
            for kv in parts[3:]:
                key, _, value = kv.partition("=")
                if key == "samples":
                    fields["samples"] = fields.get("samples", []) + value.split(",")
                else:
                    fields[key] = int(value) if value.lstrip("-").isdigit() else value
    return points


def listing(roms_dir, rom):
    with open(os.path.join(roms_dir, f"bench-{rom}.tests.tsv"), encoding="utf-8") as f:
        next(f)
        return [line.rstrip("\n").split("\t")[2] for line in f]


def hpos(p):
    samples = [tuple(int(x) for x in s.split(":")) for s in p["samples"]]
    lats = [lat for _, lat in samples]
    median = statistics.median(lats)
    outliers = [(off, lat) for off, lat in samples if lat >= median + 20]
    line = p["line_ticks"]
    #Offset 0 is the HSYNC the sync loop saw, so the window holds one HSYNC per
    #whole line after it. The line length is measured, so an HSYNC near the window
    #end can sit past full_lines * line: count every outlier, not only those before it.
    full_lines = (samples[-1][0] + samples[-1][1]) // line
    out = {"median_pclk": 2 * median, "full_lines": full_lines,
           "outliers_per_line": round(len(outliers) / full_lines, 3) if full_lines else "-",
           "holdoff_rclk_max": round(max((lat - median for _, lat in outliers), default=0) * 4 / 3, 2),
           "outlier_hpos_ticks": "/".join(str(off % line) for off, _ in outliers) or "-"}
    return out


def derive(rom, points):
    out = {name: {} for name in points}

    def per(name, metric, value, digits=3):
        out[name][metric] = round(value, digits)

    for name, p in points.items():
        if "min" in p:
            per(name, "pclk", 2 * p["min"])
            per(name, "rclk", p["min"] * 4 / 3, 2)
        if rom.startswith("mi-memset-"):
            per(name, "ms_per_mib", p["min"] / TICKS_PER_MS * MIB / p["bytes"], 4)
            per(name, "b_per_rclk", p["bytes"] / (p["min"] * 4 / 3))
            if rom == "mi-memset-uncached":
                per(name, "pclk_per_sd", 2 * p["min"] / (p["bytes"] / 8))
            if rom == "mi-memset-cached":
                per(name, "pclk_per_line", 2 * p["min"] / (p["bytes"] / 16))
        if rom == "sp-dma-sweep" and p["bytes"]:
            per(name, "b_per_rclk", p["bytes"] / (p["min"] * 4 / 3))
            per(name, "rclk_net", (p["min"] - points["poll"]["min"]) * 4 / 3, 2)
        if rom == "uncached-vs-hpos":
            out[name].update(hpos(p))
    if rom in ("dirty-row-sweep", "dirty-miss-isolated"):
        for name in points:
            if name.startswith("dirty-"):
                clean = "clean-" + name[len("dirty-"):]
                per(name, "dirty_minus_clean_pclk", 2 * (points[name]["min"] - points[clean]["min"]))
    if rom in ("rdp-sync-sweep", "rdp-setter-sweep"):
        for name, p in points.items():
            n = p["n"]
            if not n or p["kind"] == "rect":
                continue
            base = points["none-0"] if not p["kind"].startswith("rect+") else points[f"rect-{n}"]
            metric = "per_sync_clk" if rom == "rdp-sync-sweep" else "per_cmd_clk"
            per(name, metric, (p["clock"] - base["clock"]) / n)
    if rom == "rdp-atomic-sweep":
        for name, p in points.items():
            if p["atomic"]:
                off = points[name.replace("atomic1", "atomic0")]
                per(name, "per_prim_extra_clk", (p["clock"] - off["clock"]) / p["n"])
    return out


def load_expected():
    rows = []
    with open(os.path.join(HERE, "expected.tsv"), encoding="utf-8") as f:
        header = next(f).rstrip("\n").split("\t")
        for line in f:
            if line.strip() and not line.startswith("#"):
                rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def verdict(row, value):
    if not isinstance(value, (int, float)):
        return "missing"
    if row["kind"] != "check":
        return "report"
    return "pass" if float(row["lo"]) <= float(value) <= float(row["hi"]) else "fail"


def main():
    roms_dir, results, roms = sys.argv[1], sys.argv[2], sys.argv[3:]
    measured, format_ok = {}, True
    with open(os.path.join(results, "measurements.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("rom\tpoint\tmetric\tvalue\n")
        for rom in roms:
            points = parse(os.path.join(results, rom, "stdout.txt"))
            promised = listing(roms_dir, rom)
            missing = [p for p in promised if p not in points]
            missing += [f"{p}(samples {len(v.get('samples', []))} of {v['count']})"
                        for p, v in points.items() if "count" in v and len(v.get("samples", [])) != v["count"]]
            format_ok &= not missing
            print(f"{rom}: {len(promised) - len(missing)}/{len(promised)} points"
                  + (f", missing {' '.join(missing)}" if missing else ""))
            if missing:
                continue
            derived = derive(rom, points)
            for name, p in points.items():
                values = {k: v for k, v in p.items() if k != "samples"}
                values.update(derived[name])
                for metric, value in values.items():
                    measured[(rom, name, metric)] = value
                    f.write(f"{rom}\t{name}\t{metric}\t{value}\n")
    counts = {}
    with open(os.path.join(results, "results.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("rom\tpoint\tmetric\tvalue\texpected\tlo\thi\tkind\tverdict\tsource\n")
        for row in load_expected():
            if row["rom"] not in roms:
                continue
            value = measured.get((row["rom"], row["point"], row["metric"]))
            v = verdict(row, value)
            counts[v] = counts.get(v, 0) + 1
            f.write("\t".join([row["rom"], row["point"], row["metric"], str(value), row["expected"],
                               row["lo"], row["hi"], row["kind"], v, row["source"]]) + "\n")
            print(f"  {v:7} {row['rom']} {row['point']} {row['metric']} = {value} "
                  f"(expected {row['expected']}, {row['lo']}..{row['hi']})")
    print("format: " + ("ok" if format_ok else "MISSING POINTS") + "; expected rows: "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    sys.exit(0 if format_ok else 1)


if __name__ == "__main__":
    main()
