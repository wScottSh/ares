"""Parses bench ROM output, derives the cited metrics, and joins them with expected.tsv.

usage: python -m romgen.suites.bench.report ROMS_DIR RESULTS_DIR ROM...

Reads RESULTS_DIR/boot-<K>/<rom>/stdout.txt and ROMS_DIR/boot-<K>/bench-<rom>.tests.tsv for
every boot delay K in phases.DELAYS. Writes RESULTS_DIR/measurements.tsv (every raw and derived
value per delay and point), RESULTS_DIR/phases.tsv (each expected.tsv metric at every delay) and
RESULTS_DIR/results.tsv (one row per expected.tsv entry with the phase min, median, max and mean
and its verdict under the row's rule). Exits 1 when a ROM did not print every point its listing
promises, which is the format check; value verdicts never change the exit code.

Units: COUNT ticks at 46.875 MHz; pclk = 2 ticks (VR4300 93.75 MHz); rclk = 4/3 ticks (RCP
62.5 MHz); DPC clock values are the raw DPC_CLOCK register.
"""
import os
import statistics
import sys
from dataclasses import dataclass

from . import phases

HERE = os.path.dirname(os.path.abspath(__file__))
MIB = 1 << 20
TICKS_PER_MS = 46875
#n64-systembench xcycles (main.c:8-15): one COUNT tick is 12, one pclk 6, one rclk 9.
XCYCLES = {"tick": 12, "pclk": 6, "rclk": 9}
#A cached load's whole cost on hardware (nemu64-test Cached loads and store, cpu.dcache-hit), so a
#cached-read sample less this is the harness's own overhead (research/cpu-memory-costs.md TL;DR).
CACHED_HIT_PCLK = 1
SYSBENCH_ROMS = ("pi-dma-sizes", "uncached-sizes", "rcp-reg-read", "pif-ram-read", "pi-io-read", "pi-io-write", "si-io-write", "si-dma")


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
    #Offset 0 is the HSYNC the sync loop saw. The window's first and last HSYNCs sit at its
    #edges, and the ROM's one-line estimate of `line` can be off by a refresh holdoff (2926 vs
    #2975 ticks after a 20-byte code shift), which moves an edge HSYNC in or out. So the rate
    #counts only the HSYNCs half a line or more inside both edges: lines 1 .. full_lines - 1.
    full_lines = (samples[-1][0] + samples[-1][1]) // line
    interior = [off for off, _ in outliers if line / 2 <= off < (full_lines - 0.5) * line]
    out = {"median_pclk": 2 * median, "full_lines": full_lines,
           "outliers_per_line": round(len(interior) / (full_lines - 1), 3) if full_lines > 1 else "-",
           "holdoff_rclk_max": round(max((lat - median for _, lat in outliers), default=0) * 4 / 3, 2),
           "outlier_hpos_ticks": "/".join(str(off % line) for off, _ in outliers) or "-"}
    return out


def sysbench(p):
    """n64-systembench's reported value: the mean without the lowest and highest rep in xcycles
    (TIMEIT_MULTI, main.c:105-127), in whole cycles of its unit, rounded down (main.c:640-653)."""
    x = (p["sum"] - p["min"] - p["max"]) * XCYCLES["tick"] // (p["reps"] - 2)
    return x // XCYCLES[p["unit"]]


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
        if rom in SYSBENCH_ROMS:
            per(name, f"sb_{p['unit']}", sysbench(p))
            if p.get("walk") == "poll":
                #Each rep is one poll phase: the kept reps' span is the model's range over that phase.
                per(name, f"sb_{p['unit']}_rep_min", p["min"] * XCYCLES["tick"] / XCYCLES[p["unit"]], 2)
                per(name, f"sb_{p['unit']}_rep_max", p["max2"] * XCYCLES["tick"] / XCYCLES[p["unit"]], 2)
    for name, p in points.items():
        base = points.get(f"c{p.get('bits', 32)}")
        if rom in ("uncached-sizes", "rcp-reg-read", "pif-ram-read", "pi-io-read") and base and p is not base:
            overhead = sysbench(base) - CACHED_HIT_PCLK
            per(name, "overhead_pclk", overhead)
            if p["unit"] == "pclk":
                per(name, "net_pclk", sysbench(p) - overhead)
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


RULES = ("consistent", "mean", "every")


@dataclass
class Phase:
    """One metric over the boot delays: values in delay order, and the model's range, which a
    poll-walked point widens to the span of its kept reps (derive, `_rep_min`/`_rep_max`)."""
    values: list
    lo: float
    hi: float

    @property
    def median(self):
        return round(statistics.median(self.values), 3)

    @property
    def mean(self):
        return round(statistics.fmean(self.values), 3)


def phase_of(per_delay, key):
    values = [m.get(key) for m in per_delay]
    if not values or not all(isinstance(v, (int, float)) for v in values):
        return None
    lows = [m.get(key[:2] + (key[2] + "_rep_min",), v) for m, v in zip(per_delay, values)]
    highs = [m.get(key[:2] + (key[2] + "_rep_max",), v) for m, v in zip(per_delay, values)]
    return Phase(values, min(lows + values), max(highs + values))


def verdict(row, phase):
    """consistent: the hardware band overlaps the model's phase range (the hardware number is one
    phase). mean: the phase mean lies in the band (the hardware number averages many phases).
    every: the whole phase range lies in the band (a fixed cost holds at every phase)."""
    if phase is None:
        return "missing"
    if row["kind"] != "check":
        return "report"
    lo, hi, rule = float(row["lo"]), float(row["hi"]), row["rule"]
    ok = {"consistent": phase.lo <= hi and lo <= phase.hi,
          "mean": lo <= phase.mean <= hi,
          "every": lo <= phase.lo and phase.hi <= hi}[rule]
    return "pass" if ok else "fail"


def main():
    roms_dir, results, roms = sys.argv[1], sys.argv[2], sys.argv[3:]
    per_delay, format_ok = [], True
    with open(os.path.join(results, "measurements.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("boot_delay\trom\tpoint\tmetric\tvalue\n")
        for k in phases.DELAYS:
            measured = {}
            per_delay.append(measured)
            for rom in roms:
                points = parse(os.path.join(results, f"boot-{k}", rom, "stdout.txt"))
                promised = listing(os.path.join(roms_dir, f"boot-{k}"), rom)
                missing = [p for p in promised if p not in points]
                missing += [f"{p}(samples {len(v.get('samples', []))} of {v['count']})"
                            for p, v in points.items() if "count" in v and len(v.get("samples", [])) != v["count"]]
                format_ok &= not missing
                if missing:
                    print(f"boot-{k} {rom}: {len(promised) - len(missing)}/{len(promised)} points, missing {' '.join(missing)}")
                    continue
                derived = derive(rom, points)
                for name, p in points.items():
                    values = {k2: v for k2, v in p.items() if k2 != "samples"}
                    values.update(derived[name])
                    for metric, value in values.items():
                        measured[(rom, name, metric)] = value
                        f.write(f"{k}\t{rom}\t{name}\t{metric}\t{value}\n")
    print(f"{len(roms)} ROMs at {len(phases.DELAYS)} boot delays ({','.join(map(str, phases.DELAYS))})")
    counts = {}
    rows = [r for r in load_expected() if r["rom"] in roms]
    with open(os.path.join(results, "phases.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("rom\tpoint\tmetric\t" + "\t".join(f"boot-{k}" for k in phases.DELAYS) + "\n")
        for key in dict.fromkeys((r["rom"], r["point"], r["metric"]) for r in rows):
            f.write("\t".join(key + tuple(str(m.get(key)) for m in per_delay)) + "\n")
    with open(os.path.join(results, "results.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("rom\tpoint\tmetric\tmin\tmedian\tmax\tmean\texpected\tlo\thi\tkind\trule\tverdict\tsource\n")
        for row in rows:
            phase = phase_of(per_delay, (row["rom"], row["point"], row["metric"]))
            v = verdict(row, phase)
            counts[v] = counts.get(v, 0) + 1
            stats = [str(x) for x in (round(phase.lo, 3), phase.median, round(phase.hi, 3), phase.mean)] \
                if phase else ["None"] * 4
            f.write("\t".join([row["rom"], row["point"], row["metric"], *stats, row["expected"],
                               row["lo"], row["hi"], row["kind"], row["rule"], v, row["source"]]) + "\n")
            print(f"  {v:7} {row['rom']} {row['point']} {row['metric']} = {stats[0]}..{stats[2]} "
                  f"median {stats[1]} mean {stats[3]} (expected {row['expected']}, {row['lo']}..{row['hi']}, {row['rule']})")
    print("format: " + ("ok" if format_ok else "MISSING POINTS") + "; expected rows: "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    sys.exit(0 if format_ok else 1)


if __name__ == "__main__":
    main()
