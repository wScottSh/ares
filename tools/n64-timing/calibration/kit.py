#!/usr/bin/env python3
"""The calibration kit's data model: kit ROMs, questions, logs, and the hardware-vs-model comparison.

A kit log is what a kit ROM prints (romgen hwout.py): a `#kit` header, records, a `#kit-end`
footer. Records are keyed (rom, point):
  #bench <rom> <point> k=v ...    a measurement point (bench format); rom is the bench ROM name
  @snap <name> <size> <hash>      a dumped surface: key ("snap", name), fields size, hash
  @<test>.<value> <n> ...         a self-checking suite's result: key (<kit rom>, "<test>.<value>"), v0 ...
  #hist <test>.<value> <c>:<n>,...  the same key's averaged-run histogram, field hist (recorded, not compared)
A capture is one log from the console. The model side is the same ROM run on the fork at each
boot delay (calibration/run.sh). A question (questions.tsv) names points and metrics and a rule;
`compare` turns the console's values and the model's into pass or fail.
"""
import collections
import fnmatch
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from romgen.suites.bench import report as bench_report  # noqa: E402
import derived  # noqa: E402
import mm_bench  # noqa: E402

QUESTIONS = "tools/n64-timing/calibration/questions.tsv"
HARDWARE = "docs/calibration/hardware"
QUESTION_COLUMNS = ["id", "question", "decides", "kit", "points", "metric", "rule", "closes", "source", "boot"]
#How the console was started before the capture: power-on (a power cycle) or reset (the Reset button
#after a kit ROM ran). A capture file named *.reset.* is a reset capture.
BOOTS = ("power-on", "reset")
#One rule for every metric, or one per metric in the metric column's order.
RULE = re.compile(r"^((exact|range:(abs|rel):[\d.]+)( (exact|range:(abs|rel):[\d.]+))*|-)$")

#Every kit ROM: suite, build.py --set, and whether the fork walks boot delays for it (calib suite).
KIT_ROMS = {
    "kit-cpu": ("calib", "kit-cpu", True),
    "kit-vi": ("calib", "kit-vi", True),
    "kit-dma": ("calib", "kit-dma", True),
    "kit-hpos": ("calib", "kit-hpos", True),
    "kit-rdp": ("calib", "kit-rdp", True),
    "kit-span": ("calib", "kit-span", True),
    "kit-span2": ("calib", "kit-span2", True),
    "kit-noise": ("calib", "kit-noise", True),
    "rdpstat-1prim": ("rdpstat", "1prim", False),
    "rdpstat-dpc": ("rdpstat", "dpc", False),
    "rdpstat-systemtest": ("rdpstat", "systemtest", False),
    "rdpstat-unsynced": ("rdpstat", "unsynced", False),
    "nemu64-timing": ("nemu64", "timing", False),
    "nemu64-cycle": ("nemu64", "cycle", False),
    "nemu64-cop0hazard": ("nemu64", "cop0hazard", False),
    "kit-tex": ("calib", "kit-tex", True),
    "kit-zmem": ("calib", "kit-zmem", True),
    "kit-cpu2": ("calib", "kit-cpu2", True),
    "kit-bus": ("calib", "kit-bus", True),
    "cpu-llsc": ("cpu", "llsc", False),
    "kit-pif": ("pif", "kit-pif", False),
}
#kit-pif never sends the PIF terminate-boot command, so the PIF halts it and its log has no footer
#(romgen/suites/pif). It answers no question: its last COUNT is a report (hardware-run.md).
PIF_ROM = "kit-pif"
COUNT_HZ = 46_875_000
SRAM_BYTES = 0x8000


def read_tsv(path):
    lines = [l for l in Path(path).read_text(encoding="utf-8").split("\n") if l]
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:]]


def questions(root=ROOT):
    return read_tsv(Path(root) / QUESTIONS)


def fnv(data):
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


class Log:
    """One kit log, parsed. complete is True when the footer's byte count and FNV match the bytes."""

    def __init__(self, data):
        self.raw = data
        self.header, self.footer, self.records, self.pi, self.timeouts, self.complete = {}, {}, {}, {}, {}, False
        self.boot = "power-on"
        start = data.find(b"#kit rom=")
        if start < 0:
            return
        data = data[start:]
        end = data.find(b"#kit-end ")
        if end >= 0:
            self.footer = dict(kv.split("=", 1) for kv in data[end:].split(b"\n")[0].decode().split()[1:] if "=" in kv)
            body = data[:end]
            self.complete = (str(len(body)) == self.footer.get("bytes") and
                             f"{fnv(body):08x}" == self.footer.get("fnv"))
            data = body
        text = data.decode("ascii", errors="replace")
        first, _, rest = text.partition("\n")
        self.header = dict(kv.split("=", 1) for kv in first.split()[1:] if "=" in kv)
        self.text = text
        rom = self.header.get("rom", "?")
        for line in rest.split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "#bench":
                fields = self.records.setdefault((parts[1], parts[2]), {})
                for kv in parts[3:]:
                    key, _, value = kv.partition("=")
                    if key == "samples":
                        fields["samples"] = fields.get("samples", []) + value.split(",")
                    else:
                        fields[key] = int(value) if value.lstrip("-").isdigit() else value
            elif parts and parts[0] in ("#kit-pi", "#kit-timeout"):
                regs = {k: int(v, 16) for k, _, v in (kv.partition("=") for kv in parts[1:])}
                setattr(self, "pi" if parts[0] == "#kit-pi" else "timeouts", regs)
            elif len(parts) == 4 and parts[0] == "@snap":
                self.records[("snap", parts[1])] = {"size": int(parts[2]), "hash": parts[3]}
            elif len(parts) == 3 and parts[0] == "#hist":
                fields = self.records.setdefault((rom, parts[1]), {})
                fields["hist"] = ",".join(filter(None, [fields.get("hist"), parts[2]]))
            elif parts and re.match(r"^@\d+\.\d+$", parts[0]):
                self.records.setdefault((rom, parts[0][1:]), {}).update(
                    {f"v{i}": int(p) if p.lstrip("-").isdigit() else p for i, p in enumerate(parts[1:])})
        derive(self.records)

    @property
    def rom(self):
        return self.header.get("rom")

    @property
    def pads(self):
        """Controller ports that answered the joybus-setup probe (kit-dma), or None."""
        return self.records.get(("joybus-setup", "pads"), {}).get("mask")


def derive(records):
    """Adds bench report.py's derived metrics to every bench ROM's points, and the kit's own."""
    by_rom = {}
    for (rom, point), fields in records.items():
        by_rom.setdefault(rom, {})[point] = fields
    for rom, points in by_rom.items():
        try:
            for point, metrics in bench_report.derive(rom, points).items():
                points[point].update(metrics)
        except (KeyError, ZeroDivisionError, TypeError, ValueError, IndexError):
            pass
    for p in by_rom.get("uncached-vs-hpos", {}).values():
        #Every load's latency in pclk (2 per COUNT tick) by count: the console's distribution behind
        #median_pclk and the outlier metrics q24 compares (green-plan bus.md section 3, step 4).
        lats = collections.Counter(2 * int(s.split(":")[1]) for s in p.get("samples", []))
        if lats:
            p["hist_pclk"] = ",".join(f"{lat}:{n}" for lat, n in sorted(lats.items()))
    for point, p in by_rom.get("count-fields", {}).items():
        p["ticks_per_field"] = round(p["min"] / p["fields"], 3)
    for fn in derived.DERIVED:
        try:
            records.update(fn(records))
        except (KeyError, ZeroDivisionError, TypeError):
            pass
    frozen = [p["seen"] for point, p in by_rom.get("cmd-fetch", {}).items() if point.startswith("frozen-") and "seen" in p]
    if frozen:
        #A frozen RDP's CURRENT stops only where a fetch ended; the highest offset is the full FIFO,
        #so the burst is the gcd of the others (sets.py cmd_fetch_frozen).
        seen = 0
        for mask in frozen:
            seen |= mask
        offsets = [8 * i for i in range(32) if seen >> i & 1]
        inner = [o for o in offsets[:-1] if o]
        records[("cmd-fetch", "burst")] = {"burst_gcd": math.gcd(*inner) if inner else offsets[-1],
                                          "offsets": ",".join(map(str, offsets))}
    span = by_rom.get("span-width", {})
    for bpp in (16, 32):
        widths = sorted((p["w"], p["clock"]) for p in span.values() if p.get("bpp") == bpp and "clock" in p)
        pairs = [(w0, c0, w1, c1) for (w0, c0), (w1, c1) in zip(widths, widths[1:]) if w0 > 1]
        if pairs:
            #A new half shows as a width step that costs well over the per-pixel slope; the first such
            #width is the half's size in pixels.
            slope = sorted((c1 - c0) / (w1 - w0) for w0, c0, w1, c1 in pairs)[len(pairs) // 2]
            excess = [(c1 - c0 - slope * (w1 - w0), w1) for w0, c0, w1, c1 in pairs]
            top = max(e for e, _ in excess)
            records[("span-width", f"half-b{bpp}")] = {"half_px": min(w for e, w in excess if e >= top / 2)}


ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")


def normalize(data):
    """A capture's bytes as the ROM printed them. A kit log is printable ASCII and LF only, so what
    capture tools add can be undone without touching a real byte: an SRAM dump in the other byte
    order, UTF-16 from a PowerShell redirect, a UTF-8 BOM, CRLF or CR line ends from a Windows tee,
    a text-mode copy or a serial terminal, and terminal color codes."""
    if b"#kit rom=" not in data and b"tik#" in data:
        data = b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
    wide = data.find(b"#\0k\0i\0t")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or wide >= 0:
        le = data[:2] == b"\xff\xfe" or (data[:2] != b"\xfe\xff" and wide % 2 == 0)
        text = data.decode("utf-16-le" if le else "utf-16-be", errors="replace").lstrip("\ufeff")
        data = text.encode("ascii", errors="replace")
    data = data.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return ANSI.sub(b"", data).rstrip(b"\0")


def read_logs(paths):
    """Kit logs by ROM id from files: ISViewer text, SRAM dumps (.srm/.sra/.sav, either byte order)
    and transcribed screen text, each normalized first."""
    out = {}
    for path in paths:
        log = Log(normalize(Path(path).read_bytes()))
        log.boot = "reset" if ".reset." in Path(path).name else "power-on"
        if log.rom:
            out.setdefault(log.rom, []).append((Path(path), log))
    return out


#The fork runs per controller setup the joybus-setup probe can report (calibration/run.sh).
PAD_SETUPS = {None: "", 0b0001: "", 0b1111: "pads-4/"}
LAYOUT_BUILD = re.compile(r"^p(\d+)/")


def layout(log):
    """The layout pad a kit log's ROM was built at (build.py --layout-pad): build p<P>/..., else 0."""
    m = LAYOUT_BUILD.match(log.header.get("build", ""))
    return int(m.group(1)) if m else 0


def model_logs(run_dir, rom, pads=None, pad=0):
    """The fork's logs of one kit ROM in a calibration/run.sh output, one per boot delay, at layout pad
    `pad`, run with the controllers whose ports answered as `pads` did."""
    run_dir = Path(run_dir) / PAD_SETUPS[pads] / (f"p{pad}" if pad else "")
    paths = sorted(run_dir.glob(f"boot-*/{rom}.txt")) + sorted(run_dir.glob(f"single/{rom}.txt"))
    return [Log(p.read_bytes()) for p in paths]


def model_layouts(run_dir, rom, pads=None):
    """{layout pad: the fork's complete logs at that pad} for one kit ROM in a calibration/run.sh output."""
    base = Path(run_dir) / PAD_SETUPS[pads]
    found = [0] + sorted(int(d.name[1:]) for d in base.glob("p*") if re.fullmatch(r"p\d+", d.name))
    out = {pad: [m for m in model_logs(run_dir, rom, pads, pad) if m.complete] for pad in found}
    return {pad: logs for pad, logs in out.items() if logs}


def spread(question, logs):
    """{(rom/point, metric): what the question's rule compares} over logs: the value set for an exact
    rule, else the range lo..hi."""
    metrics, rules = question["metric"].split(), question["rule"].split()
    rule_of = dict(zip(metrics, rules if len(rules) > 1 else rules * len(metrics)))
    out = {}
    for pattern in question["points"].split():
        for metric in metrics:
            for key, vs in values(logs, pattern, metric).items():
                out[(key, metric)] = tuple(sorted(set(vs), key=str)) if rule_of[metric] == "exact" else (min(vs), max(vs))
    return out


def layout_moved(question, model):
    """(the compared values whose spread differs by layout pad, {pad: spread}) over the fork's
    {layout pad: logs}. A question with any such value is layout-sensitive."""
    spreads = {pad: spread(question, logs) for pad, logs in model.items()}
    keys = sorted(set().union(*spreads.values()))
    return [k for k in keys if len({spreads[pad].get(k) for pad in spreads}) > 1], spreads


def values(logs, pattern, metric):
    """(rom/point, [values]) for every point matching pattern, across the logs."""
    out = {}
    for log in logs:
        for (rom, point), fields in log.records.items():
            key = f"{rom}/{point}"
            if fnmatch.fnmatchcase(key, pattern) or (log.rom == rom and fnmatch.fnmatchcase(point, pattern)):
                if metric in fields:
                    out.setdefault(key, []).append(fields[metric])
    return out


def compare(question, hw, model):
    """(result, detail): pass or fail, from the console's logs and the model's, under the question's rule."""
    metrics, rules = question["metric"].split(), question["rule"].split()
    rule_of = dict(zip(metrics, rules if len(rules) > 1 else rules * len(metrics)))
    bad, lacking, shown_all = [], [], []
    for pattern in question["points"].split():
        for metric in metrics:
            rule = rule_of[metric]
            want = values(model, pattern, metric)
            got = values(hw, pattern, metric)
            for key in sorted(set(want) - set(got)):
                lacking.append(f"{key} {metric}")
            for key, hv in sorted(got.items()):
                mv = want.get(key)
                if mv is None:
                    continue
                if rule == "exact":
                    ok = set(hv) <= set(mv)
                    shown = f"{key} {metric} console {sorted(set(hv))} model {sorted(set(mv))}"
                else:
                    _, kind, tol = rule.split(":")
                    tol = float(tol)
                    lo, hi = min(mv), max(mv)
                    slack = tol if kind == "abs" else tol / 100 * max(abs(lo), abs(hi))
                    ok = min(hv) <= hi + slack and max(hv) >= lo - slack
                    shown = f"{key} {metric} console {min(hv)}..{max(hv)} model {lo}..{hi}"
                shown_all.append(shown)
                if not ok:
                    bad.append(shown if rule == "exact" else f"{shown} ({rule})")
    checked = len(shown_all)
    if not checked:
        return "fail", f"no console value matches {question['points']} {question['metric']}; the capture lacks the points"
    if lacking:
        return "fail", f"the capture lacks {len(lacking)} of {len(lacking) + checked} model values; first {lacking[0]}"
    if bad:
        return "fail", f"{len(bad)} of {checked} values differ; first {bad[0]}"
    return "pass", f"{checked} values agree ({question['rule']}): {'; '.join(shown_all)}"


def ext_thar0(root, model_dir, paths, points):
    """Thar0/RDP-Timing-Tests on the console (its usblog text) against the fork's run of the romgen port
    (run.sh ext/thar0.txt), per configuration's pruned average BUFBUSY and PIPEBUSY within 1%; the
    detail also counts the configurations within 1% of Thar0's own console (expected.tsv)."""
    from romgen.suites.thar0 import compare as thar0
    model_path = Path(model_dir) / "ext" / "thar0.txt"
    if not model_path.exists():
        return "missing", f"no fork run of the thar0 port in {model_path}; run tools/n64-timing/calibration/run.sh"
    console = {}
    for path in paths:
        for i, block in thar0.parse(str(path)).items():
            for key, values in block.items():
                console.setdefault(i, {}).setdefault(key, []).extend(values)
    model, published = thar0.parse(str(model_path)), thar0.load_expected()
    lacking, off_model, off_hw = [], [], 0
    for i, (sid, hw_buf, hw_pipe) in sorted(published.items()):
        c = console.get(i, {})
        if "BUF" not in c or "PIPE" not in c:
            lacking.append(sid)
            continue
        for key, hw in (("BUF", hw_buf), ("PIPE", hw_pipe)):
            avg = thar0.reduce(c[key])[1]
            mavg = thar0.reduce(model[i][key])[1]
            if abs(avg - mavg) > 0.01 * mavg:
                off_model.append(f"{sid} {key} console {avg:.1f} fork {mavg:.1f}")
            off_hw += abs(avg - hw[1]) > 0.01 * hw[1]
    if lacking:
        return "fail", f"the capture lacks {len(lacking)} of {len(published)} configurations; first {lacking[0]}"
    checked = 2 * len(published)
    detail = (f"{checked - len(off_model)} of {checked} averages within 1% of the fork, "
              f"{checked - off_hw} within 1% of Thar0's console")
    if off_model:
        return "fail", f"{detail}; first {off_model[0]}"
    return "pass", detail


def ext_snapper64(root, model_dir, paths, points):
    """snapper64's .test dumps from the console against the published console dumps byte for byte
    (romgen/suites/snapper/compare.py default_corpus), over every dump the snapper sets read."""
    from romgen.suites.snapper import compare as snap, sets as snap_sets
    corpus = Path(snap.default_corpus())
    wanted = sorted({r.id for st in snap_sets.SETS if st.set_name in snap.REFERENCE_DIGEST
                     for c in st.cases for r in c.records if c.group != snap.RW_GROUP})
    got = {p.stem: p for p in paths if p.suffix == ".test"}
    if not (corpus / f"{wanted[0]}.test").exists():
        return "missing", f"no published snapper64 dumps in {corpus} (romgen/suites/snapper/fetch.sh)"
    lacking = [w for w in wanted if w not in got]
    if lacking:
        return "fail", f"the capture lacks {len(lacking)} of {len(wanted)} dumps; first {lacking[0]}.test"
    differ = [w for w in wanted if got[w].read_bytes() != (corpus / f"{w}.test").read_bytes()]
    if differ:
        return "fail", f"{len(differ)} of {len(wanted)} dumps differ from the published console dumps; first {differ[0]}.test"
    return "pass", f"{len(wanted)} dumps equal the published console dumps"


def ext_systembench(root, model_dir, paths, points):
    """n64-systembench's ISViewer text from the console against the fork's run of the same binary, the
    hardware-era build (build-systembench-era.sh, run.sh ext/systembench.txt), every row of systembench/rows.tsv under main.c's own pass rule with the
    fork's reading as the expected value. Pointwise for that binary only: a one to three instruction
    change in a poll loop moves the poll rows by up to 10 RCP cycles (verify-83), so a console run of
    another build of the same source decides nothing here."""
    from systembench import report as sb
    model_path = Path(model_dir) / "ext" / "systembench.txt"
    if not model_path.exists():
        return "missing", (f"no fork run of n64-systembench in {model_path}; build it (build-systembench-era.sh) and run "
                           f"tools/n64-timing/calibration/run.sh")
    model = sb.parse(model_path.read_text(encoding="utf-8", errors="replace"))
    if model is None:
        return "missing", f"the fork's run in {model_path} did not print 'Benchmarks done'"
    runs = [sb.parse(normalize(p.read_bytes()).decode("ascii", errors="replace")) for p in paths]
    runs = [r for r in runs if r is not None]
    if not runs:
        return "pending:calibration-16", (f"{len(paths)} files of systembench stored, none with 'Benchmarks done': "
                                          f"a cut log or a hang")
    keys = [(r["name"], int(r["qty"])) for r in sb.read_rows()]
    lacking = [k for k in keys if any(k not in run for run in runs)]
    if lacking:
        return "fail", f"the capture lacks {len(lacking)} of {len(keys)} rows; first *** {lacking[0][0]} [{lacking[0][1]}]"
    off, hw_ok = [], 0
    for key in keys:
        unit, expected, fork = model[key]
        found = [run[key][2] for run in runs]
        if not all(sb.passes(unit, fork, f) for f in found):
            off.append(f"{key[0]} [{key[1]}] console {min(found)}..{max(found)} fork {fork} {unit}")
        hw_ok += all(sb.passes(unit, expected, f) for f in found)
    detail = (f"{len(keys) - len(off)} of {len(keys)} rows agree with the fork under main.c's rule, {hw_ok} with the "
              f"published hardware value, over {len(runs)} console runs; pointwise for this one binary")
    if off:
        return "fail", f"{detail}; first {off[0]}"
    return "pass", detail


def ext_mm_bench(root, model_dir, paths, points):
    """The Majora's Mask BENCH ROM's IS-Viewer text from the console against the fork's run of the same
    pinned per-scene ROMs (run.sh ext/mm-bench/<scene>.txt), under mm_bench.compare's rule, for the
    scenes the question's points name."""
    return mm_bench.compare(paths, model_dir, points)


#External ROMs a capture can hold: kit column `ext:<name>`, the capture file or directory name
#prefix `ext-<name>`, and the reader that compares it (None: stored, compared by hand per
#hardware-run.md until a reader exists). A reader gets the question's points: mm-bench reads them as
#scene names, the others need `-`.
EXT_ROMS = {
    "thar0": ext_thar0,
    "snapper64": ext_snapper64,
    "systembench": ext_systembench,
    "mm-bench": ext_mm_bench,
}
#External ROMs whose output names no ROM identity: ingest refuses a capture these find run on other ROMs
#than the fork's model side.
EXT_IDENTITY = {"mm-bench": mm_bench.rom_mismatch}
#The fork-side runner of each external ROM's checks (checks.tsv), so behaviors.py can tell a console run
#that repeats a row's fit data from an independent one.
EXT_SUITES = {"thar0": "thar0", "snapper64": "snapper", "systembench": "systembench", "mm-bench": "mm"}


def ext_name(path):
    """The external ROM a capture file belongs to, from its name (ext-<name>...) or, for Thar0's
    usblog text, its BUF/PIPE blocks."""
    for part in Path(path).parts:
        for name in EXT_ROMS:
            if part.startswith(f"ext-{name}"):
                return name
    return None


def ext_captures(root=ROOT):
    base = Path(root) / HARDWARE
    out = {}
    for p in sorted(base.glob("*/ext-*/**/*")) if base.exists() else []:
        if p.is_file() and ext_name(p.relative_to(base)):
            out.setdefault(ext_name(p.relative_to(base)), []).append(p)
    return out


def captures(root=ROOT):
    """Every ingested console log under docs/calibration/hardware, by kit ROM."""
    base = Path(root) / HARDWARE
    paths = sorted(base.glob("*/*.log")) if base.exists() else []
    return {rom: [log for _, log in logs] for rom, logs in read_logs(paths).items()}, sorted({p.parent.name for p in paths})


def rom_mismatch(log, model_dir):
    """Why the fork's log of the same build in model_dir (a calibration/run.sh output) is not a run of
    the ROM the console ran, or None. romgen/hwout.py rom_sha256 is the ROM's identity."""
    build = log.header.get("build", "?")
    path = Path(model_dir) / build / f"{log.rom}.txt"
    want = Log(path.read_bytes()).header.get("rom_sha256") if path.exists() else None
    got = log.header.get("rom_sha256")
    if got and got == want:
        return None
    return (f"{log.rom} {build}: the console ran rom_sha256={got or 'none'} (built at sha={log.header.get('sha', '?')}), "
            f"the fork's {path} ran {want or 'none'}; run calibration/run.sh at that commit, or rerun the console "
            f"with this run's ROMs (hardware-run.md, Build the kit)")


def result(root, run_dir, qid):
    """The hw:<qid> check's result for behaviors.py --results, from a standing run's calib/ directory."""
    return result_from(root, Path(run_dir) / "calib", qid)


def result_from(root, model_dir, qid):
    """A pending gate until a capture of the question's kit ROM is ingested, then pass or fail against
    the fork's run of the same ROM in model_dir (a calibration/run.sh output)."""
    q = next((q for q in questions(root) if q["id"] == qid), None)
    if q is None:
        return None
    kit = q["kit"]
    if kit.startswith("none"):
        return "pending:calibration-16", f"{kit}: no kit ROM"
    if kit.startswith("ext:"):
        name = kit[4:]
        paths = ext_captures(root).get(name, [])
        if not paths:
            return "pending:calibration-16", f"no console capture of {name} (capture name ext-{name}*) in {HARDWARE}"
        reader = EXT_ROMS.get(name)
        if reader is None:
            return "pending:calibration-16", (f"{len(paths)} files of {name} stored in {HARDWARE}; no reader yet, "
                                              f"compare by hand per hardware-run.md")
        return reader(root, model_dir, paths, q["points"].split())
    hw, ids = captures(root)
    boot = q.get("boot", "power-on")
    logs = [log for log in hw.get(kit, []) if log.complete and log.boot == boot]
    if not logs:
        return "pending:calibration-16", f"no complete {boot} console capture of {kit} in {HARDWARE}"
    differ = [m for m in (rom_mismatch(log, model_dir) for log in logs) if m]
    if differ:
        return "missing", f"no fork run of the console's ROM: {differ[0]}"
    hung = [log for log in logs if any(log.timeouts.values())]
    if hung:
        return "fail", (f"{kit}: the console gave up {hung[0].timeouts} waits (#kit-timeout): a PI or RDP wait never "
                        f"ended, so the points after it are not measurements; see hardware-run.md, A hang")
    paks = [log for log in logs if log.records.get(("joybus-setup", "pads"), {}).get("paks")]
    if paks:
        return "fail", (f"{kit}: a controller held a Controller Pak or Rumble Pak (paks="
                        f"{paks[0].records[('joybus-setup', 'pads')]['paks']}); the fork has none, so remove it and rerun")
    results, details = [], []
    for pads in sorted({log.pads for log in logs}, key=lambda p: -1 if p is None else p):
        group = [log for log in logs if log.pads == pads]
        if pads not in PAD_SETUPS:
            return "fail", f"{kit}: controller ports {pads:04b} answered; the fork runs 1 pad (0001) or 4 (1111)"
        model = model_layouts(model_dir, kit, pads)
        if not model:
            return "missing", f"no fork run of {kit} in {model_dir}/{PAD_SETUPS[pads]}; run tools/n64-timing/calibration/run.sh there"
        res, detail = compare_layouts(q, group, model)
        results.append(res)
        setup = "" if pads is None else f"{bin(pads).count('1')} pads: "
        details.append(f"{setup}{detail}, {len(group)} console and {sum(map(len, model.values()))} fork logs")
    res = next((r for r in ("missing", "fail", "consistent-only") if r in results), "pass")
    return res, f"{'; '.join(details)}; capture {','.join(ids)}"


def compare_layouts(q, hw, model):
    """(result, detail) of the console's logs against the fork's {layout pad: logs}, each pad's logs
    against the fork's at the same pad, under the bench layout-pad rule (docs/design/green-plan.md
    section 3, bench report.py layout_verdict): a verdict holds only if it is the same at every pad,
    else consistent-only. A question whose fork values differ by pad (layout-sensitive) needs a
    capture at every pad the fork ran; one that lacks a pad fails, as one that lacks a point does."""
    by_pad = {}
    for log in hw:
        by_pad.setdefault(layout(log), []).append(log)
    unknown = sorted(set(by_pad) - set(model))
    if unknown:
        return "missing", f"no fork run at layout pad {unknown[0]}; run tools/n64-timing/calibration/run.sh"
    sensitive = bool(layout_moved(q, model)[0])
    lacking = sorted(set(model) - set(by_pad))
    if sensitive and lacking:
        return "fail", (f"layout-sensitive (the fork's values differ by layout pad) and the capture lacks pads "
                        f"{','.join(map(str, lacking))} of {len(model)}; run every pad build (hardware-run.md, Layout pads)")
    verdicts = {pad: compare(q, logs, model[pad]) for pad, logs in sorted(by_pad.items())}
    if len(verdicts) == 1:
        return next(iter(verdicts.values()))
    res = bench_report.layout_verdict([r for r, _ in verdicts.values()])
    first = {}
    for pad, (r, d) in verdicts.items():
        first.setdefault(r, f"pad {pad}: {d}")
    return res, (f"layout pads {' '.join(f'{pad}:{r}' for pad, (r, _) in verdicts.items())}; "
                 + "; ".join(first.values()))


def pif_report(log):
    """(the last COUNT kit-pif logged, its sample number, halted). A complete log ran all its samples
    unhalted: boot was terminated before the ROM ran."""
    last = log.records.get((PIF_ROM, "count"), {})
    return last.get("count"), last.get("n"), not log.complete


def pif_line(log):
    count, n, halted = pif_report(log)
    if count is None:
        return "no COUNT line"
    if not halted:
        return (f"never halted in {count / COUNT_HZ:.3f} s of COUNT: boot was terminated before the ROM ran (a menu "
                f"launch, not sc64deployer upload)")
    return f"last COUNT {count} ({count / COUNT_HZ:.3f} s, sample {n}) before the PIF halted the CPU"


def verify_run(run_dir):
    """Errors in a calibration/run.sh output: a log without a valid footer (for kit-pif, a log the PIF did
    not halt), a cartridge SRAM copy that
    differs from the ISViewer copy (the flashcart SD path), or domain-1 PI timing that the output
    layer left changed (hwout.py PI_REGS)."""
    from romgen import hwout
    errors = []
    for txt in sorted(Path(run_dir).glob("*/**/*.txt")):
        parts = txt.relative_to(run_dir).parts
        if "roms" in parts or parts[0] == "ext":
            continue
        data = txt.read_bytes()
        log = Log(data)
        pif = log.rom == PIF_ROM
        if pif and (pif_report(log)[0] is None or not pif_report(log)[2]):
            errors.append(f"{txt}: the PIF did not halt kit-pif: {pif_line(log)}")
        if not log.complete and not pif:
            errors.append(f"{txt}: no valid #kit-end footer")
            continue
        srm = txt.with_suffix(".srm")
        if not srm.exists():
            errors.append(f"{txt}: the run left no cartridge SRAM ({srm.name})")
        elif srm.read_bytes() != data[:SRAM_BYTES].ljust(SRAM_BYTES, b"\0"):
            errors.append(f"{srm}: the SRAM copy differs from the ISViewer copy")
        if not pif and log.pi != hwout.DOM1_HEADER:
            errors.append(f"{txt}: domain-1 PI timing at the end {log.pi}, the ROM header's {hwout.DOM1_HEADER}")
        if not pif and log.timeouts != {"pi": 0, "rdp": 0}:
            errors.append(f"{txt}: #kit-timeout {log.timeouts or 'missing'}; on the fork no wait may give up")
        rom = Path(run_dir) / "roms" / log.header.get("build", "?") / f"{log.rom}.z64"
        if not rom.exists() or hwout.rom_sha256(rom.read_bytes()) != log.header.get("rom_sha256"):
            errors.append(f"{txt}: header rom_sha256={log.header.get('rom_sha256')} is not the rom_sha256 of {rom}")
    return errors


HIST_METRICS = ("hist", "hist_pclk")


def histograms(log):
    """(rom/point, metric, histogram) for every latency histogram a log records: nemu64-timing's
    averaged runs (hist, in the test's cycles) and kit-hpos's per-load latencies (hist_pclk). No
    question compares them; they are the console's distributions behind the means it does compare."""
    return [(f"{rom}/{point}", m, fields[m]) for (rom, point), fields in sorted(log.records.items())
            for m in HIST_METRICS if m in fields]


def sample_log(body="#bench dcb sw-lw pairs=16 reps=8 min=24 max=101\n#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n",
               rom_sha256="a" * 64, rom="kit-cpu", build="boot-1"):
    field = f" rom_sha256={rom_sha256}" if rom_sha256 else ""
    text = f"#kit rom={rom} sha=0{field} fmt=1 build={build} ri_mode=0xe\n{body}".encode()
    return text + f"#kit-end rom={rom} bytes={len(text)} fnv={fnv(text):08x}\n".encode()


def self_test():
    """Each capture mangling read_logs must undo, and the damage it must not accept."""
    import tempfile
    log = sample_log()
    padded = log + b"\0" * (-len(log) % 4)
    swapped = b"".join(padded[i:i + 4][::-1] for i in range(0, len(padded), 4)) + b"\0" * 64
    ansi = b"".join(b"\x1b[32m" + line + b"\x1b[0m\n" for line in log.split(b"\n") if line)
    cases = [
        ("as printed", log, True),
        ("CRLF (Windows tee, text-mode copy)", log.replace(b"\n", b"\r\n"), True),
        ("CR line ends (serial terminal)", log.replace(b"\n", b"\r"), True),
        ("UTF-16LE with BOM (PowerShell > redirect)", "\ufeff".encode("utf-16-le") + log.decode().encode("utf-16-le"), True),
        ("UTF-16BE", log.decode().encode("utf-16-be"), True),
        ("UTF-8 BOM and a listener banner line first", b"\xef\xbb\xbfsc64deployer: listening\n" + log, True),
        ("terminal color codes", ansi, True),
        ("SRAM dump, byte-swapped, zero padded", swapped, True),
        ("a value edited under the old footer", log.replace(b"min=24", b"min=25"), False),
        ("a cut log", log[:len(log) // 2], False),
        ("CRLF with a value edited", log.replace(b"min=24", b"min=25").replace(b"\n", b"\r\n"), False),
    ]
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, data, want) in enumerate(cases):
            path = Path(tmp) / f"case{i}.log"
            path.write_bytes(data)
            logs = read_logs([path]).get("kit-cpu", [])
            got = bool(logs) and logs[0][1].complete and logs[0][1].records.get(("dcb", "sw-lw"), {}).get("min") == 24
            ok = got == want
            failed += not ok
            print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} (complete={got}, want {want})")
    q = {"points": "dcb/*", "metric": "min", "rule": "range:abs:1"}
    model = [Log(log)]
    partial = sample_log("#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n")
    off = sample_log("#bench dcb sw-lw pairs=16 reps=8 min=26 max=101\n#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n")
    compares = [("a full capture that agrees", [Log(log)], "pass"),
                ("a capture holding one of the two points", [Log(partial)], "fail"),
                ("a capture 2 pclk off on one point", [Log(off)], "fail")]
    per_metric = {"points": "dcb/*", "metric": "min max", "rule": "exact range:abs:50"}
    max_off = sample_log("#bench dcb sw-lw pairs=16 reps=8 min=24 max=140\n#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n")
    min_off = sample_log("#bench dcb sw-lw pairs=16 reps=8 min=25 max=101\n#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n")
    compares += [("per-metric rules, max 39 off under its abs:50", [Log(max_off)], "pass", per_metric),
                 ("per-metric rules, min 1 off under its exact", [Log(min_off)], "fail", per_metric)]
    near = sample_log("#bench dcb sw-lw pairs=16 reps=8 min=25 max=101\n#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n")
    compares += [("a pass inside the band names each point's console and model values", [Log(near)], "pass", q,
                  "2 values agree (range:abs:1): dcb/nop-nop min console 16..16 model 16..16; "
                  "dcb/sw-lw min console 25..25 model 24..24")]
    for name, hw, want, *rule in compares:
        got, detail = compare(rule[0] if rule else q, hw, model)
        ok = got == want and (len(rule) < 2 or detail == rule[1])
        failed += not ok
        print(f"kit: self-test: compare, {name}: {'ok' if ok else 'FAILED'} ({got}: {detail})")
    cases += compares

    def at(pad, sw_lw=24):
        return Log(sample_log(f"#bench dcb sw-lw pairs=16 reps=8 min={sw_lw} max=101\n", build=f"p{pad}/boot-1" if pad else "boot-1"))
    flat, moved = {0: [at(0)], 1: [at(1)]}, {0: [at(0)], 1: [at(1, 30)]}
    layouts = [("layout pads: the fork's values agree at every pad, a pad-0 capture keeps its verdict", [at(0)], flat, "pass"),
               ("layout pads: the fork's values differ by pad, a pad-0 capture lacks pad 1", [at(0)], moved, "fail"),
               ("layout pads: a capture at every pad agrees with the fork at each", [at(0), at(1, 30)], moved, "pass"),
               ("layout pads: pass at pad 0, fail at pad 1 reads consistent-only", [at(0), at(1)], moved, "consistent-only"),
               ("layout pads: a capture at a pad the fork did not run", [at(0), at(2)], flat, "missing")]
    for name, hw, model, want in layouts:
        got, detail = compare_layouts(q, hw, model)
        ok = got == want
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {detail[:100]})")
    cases += layouts
    same, other = "a" * 64, "b" * 64
    q = {"id": "t", "kit": "kit-cpu", "points": "dcb/*", "metric": "min", "rule": "range:abs:1", "boot": "power-on"}
    roms = [("a capture of the ROM the fork ran", same, "pass"),
            ("a capture of a ROM the fork did not run (rom_sha256 differs)", other, "missing"),
            ("a capture whose header names no rom_sha256", None, "missing")]
    for name, console_sha, want in roms:
        with tempfile.TemporaryDirectory() as tmp:
            root, model = Path(tmp) / "root", Path(tmp) / "model"
            (root / QUESTIONS).parent.mkdir(parents=True)
            (root / QUESTIONS).write_text("\t".join(QUESTION_COLUMNS) + "\n" +
                                          "\t".join(q.get(c, "-") for c in QUESTION_COLUMNS) + "\n")
            (root / HARDWARE / "c").mkdir(parents=True)
            (root / HARDWARE / "c" / "kit-cpu.1.log").write_bytes(sample_log(rom_sha256=console_sha))
            (model / "boot-1").mkdir(parents=True)
            (model / "boot-1" / "kit-cpu.txt").write_bytes(sample_log(rom_sha256=same))
            got, detail = result_from(root, model, "t")
        ok = got == want
        failed += not ok
        print(f"kit: self-test: ROM identity, {name}: {'ok' if ok else 'FAILED'} ({got}: {detail})")
    cases += roms
    import subprocess
    run_store = ("import importlib.util, sys\n"
                 "spec = importlib.util.spec_from_file_location('ingest', sys.argv[1])\n"
                 "ingest = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(ingest)\n"
                 "ingest.store(*sys.argv[2:])\n")
    stores = [("ingest stores a capture of the ROM the fork ran", same, 0),
              ("ingest refuses a capture whose rom_sha256 differs and stores nothing", other, 1)]
    for name, console_sha, want in stores:
        with tempfile.TemporaryDirectory() as tmp:
            root, model, capture = Path(tmp) / "root", Path(tmp) / "model", Path(tmp) / "capture"
            (root / "tools").mkdir(parents=True)
            (root / "tools" / "n64-timing").symlink_to(HERE.parent, target_is_directory=True)
            capture.mkdir()
            (capture / "kit-cpu.isviewer.log").write_bytes(sample_log(rom_sha256=console_sha))
            (model / "boot-1").mkdir(parents=True)
            (model / "boot-1" / "kit-cpu.txt").write_bytes(sample_log(rom_sha256=same))
            proc = subprocess.run([sys.executable, "-c", run_store, str(HERE / "ingest.py"), str(root), str(capture),
                                   "c", str(model)], capture_output=True, text=True)
            stored = sorted(p.name for p in (root / HARDWARE).rglob("*") if p.is_file())
        ok = proc.returncode == want and (stored == ["kit-cpu.1.log", "manifest.tsv"] if want == 0 else not stored)
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} (exit {proc.returncode}, stored {stored or 'nothing'})")
    cases += stores
    from romgen import hwout
    rom = hwout.stamp(b"\0" * 64 + f"#kit rom=kit-cpu sha=78b4427b8d86 rom_sha256={hwout.UNSTAMPED} fmt=1\0".encode() + b"code")
    stamped = Log(rom).header["rom_sha256"]
    idents = [("a stamped ROM's header holds its rom_sha256", hwout.rom_sha256(rom) == stamped),
              ("another commit's build of the same bytes keeps the rom_sha256",
               hwout.rom_sha256(rom.replace(b"sha=78b4427b8d86", b"sha=0123456789ab")) == stamped),
              ("one changed code byte changes the rom_sha256", hwout.rom_sha256(rom.replace(b"code", b"codf")) != stamped)]
    for name, ok in idents:
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'}")
    cases += idents
    hung = Log(sample_log("#bench dcb sw-lw pairs=16 reps=8 min=24 max=101\n#kit-timeout pi=0 rdp=2\n"))
    ok = hung.complete and hung.timeouts == {"pi": 0, "rdp": 2}
    failed += not ok
    print(f"kit: self-test: a log whose RDP wait gave up twice reads timeouts rdp=2: {'ok' if ok else 'FAILED'} ({hung.timeouts})")
    cases.append(("timeouts", None, None))
    hist = Log(sample_log("#hist 51.3 41:2,42:1\n#hist 51.3 80:1\n@51.3 0 42\n"))
    ok = hist.records.get(("kit-cpu", "51.3")) == {"hist": "41:2,42:1,80:1", "v0": 0, "v1": 42}
    failed += not ok
    print(f"kit: self-test: a value's #hist lines join and survive its @ record: {'ok' if ok else 'FAILED'} "
          f"({hist.records.get(('kit-cpu', '51.3'))})")
    cases.append(("hist", None, None))
    hpos = Log(sample_log("#bench uncached-vs-hpos bank5 bank=5 lines=3 line_ticks=2981 count=3\n"
                          "#bench uncached-vs-hpos bank5 samples=0:17,24:40,64:17\n"))
    got = hpos.records.get(("uncached-vs-hpos", "bank5"), {}).get("hist_pclk")
    ok = got == "34:2,80:1"
    failed += not ok
    print(f"kit: self-test: kit-hpos samples give a per-load latency histogram in pclk: {'ok' if ok else 'FAILED'} ({got})")
    cases.append(("hpos hist", None, None))
    samples = "".join(f"#bench kit-pif count n={n} count={2922075 + 468750 * n}\n" for n in range(3))
    for name, data, want in [
            ("kit-pif cut by the PIF's halt reports its last COUNT",
             sample_log(samples, rom="kit-pif", build="single").split(b"#kit-end")[0], (3859575, 2, True)),
            ("kit-pif with a footer was never halted", sample_log(samples, rom="kit-pif", build="single"),
             (3859575, 2, False))]:
        got = pif_report(Log(data))
        ok = got == want
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {pif_line(Log(data))})")
        cases.append((name, None, None))
    llsc_q = next(q for q in questions() if q["id"] == "cpu-llsc-console")

    def llsc(bad=(), watch=0):
        body = "".join(f"@{t}.{v} {int(f'{t}.{v}' in bad)}\n" for t in (0, 1) for v in range(6))
        body += "".join(f"#bench cpu-llsc watch-fail-{op} exc={watch} exccode={23 * watch} rt_lo=0x0\n@2.{i} {watch}\n"
                        for i, op in enumerate(("sc", "scd")))
        return Log(sample_log(body, rom="cpu-llsc"))
    llscs = [("cpu-llsc: the console's verdicts match", llsc(), "pass"),
             ("cpu-llsc: test 2 (the Watch probe) differs on the console: report-only, not compared", llsc(watch=1), "pass"),
             ("cpu-llsc: the console fails the SCD ERET case", llsc(bad={"1.1"}), "fail")]
    for name, hw, want in llscs:
        got, detail = compare(llsc_q, [hw], [llsc()])
        ok = got == want and "12 values" in detail if want == "pass" else got == want
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {detail[:80]})")
    watch = llsc(watch=1).records.get(("cpu-llsc", "watch-fail-sc"), {})
    ok = watch.get("exc") == 1 and watch.get("exccode") == 23
    failed += not ok
    print(f"kit: self-test: cpu-llsc: the Watch probe's record survives parsing: {'ok' if ok else 'FAILED'} ({watch})")
    cases += llscs + [("llsc watch record", None, None)]
    span2_cases = span2_self_test()
    failed += span2_cases.count(False)
    cases += span2_cases
    noise_cases = noise_self_test()
    failed += noise_cases.count(False)
    cases += noise_cases
    latch_q = next(q for q in questions() if q["id"] == "vi-frame-latch")

    def vi_latch(late, bank2, bank3):
        pts = (("bus-vi", "base", 1104), ("bus-vi", "vvideo-outside", 1231), ("bus-vi", "vvideo-outside-late", late),
               ("bus-vi-latch", "y-late-bank2", bank2), ("bus-vi-latch", "y-late-bank3", bank3))
        return Log(sample_log("".join(f"#bench {rom} {pt} n={n}\n" for rom, pt, n in pts), rom="kit-bus"))
    fork = vi_latch(1108, 1107, 1197)
    latches = [("vi-frame-latch: a console that latches per frame (the fork's loads)", fork, "pass"),
               ("vi-frame-latch: loads 40 off the fork's on the latch side of each category",
                vi_latch(1148, 1067, 1157), "pass"),
               ("vi-frame-latch: a console that reads V_VIDEO per line (the late case at the no-fetch count)",
                vi_latch(1231, 1107, 1197), "fail"),
               ("vi-frame-latch: a console that recomputes y per line (bank 3 loses more)", vi_latch(1108, 1197, 1107), "fail")]
    for name, hw, want in latches:
        got, detail = compare(latch_q, [hw], [fork])
        ok = got == want and (want == "fail" or "2 values" in detail)
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {detail[:120]})")
    cases += latches
    vintr_q = next(q for q in questions() if q["id"] == "vi-intr-latency")

    def vintr(field=0, mean=65716, timeout=0):
        ticks = "min=0 max=0 sum=0 max2=0" if timeout else f"min=4096 max=4126 sum={mean} max2=4126"
        return Log(sample_log(f"#bench bus-vintr v-intr v_intr=256 bias=4096 reps=16 {ticks} "
                              f"v_at_intr=256 iter_ticks=30 timeout={timeout} field={field}\n", rom="kit-bus"))
    vintrs = [("vi-intr-latency: a console that boots kit-bus into field 1 (#132)", vintr(field=1), [vintr()], "pass",
               "2 values"),
              ("vi-intr-latency: a half-line interrupt (lag about 1490 ticks)", vintr(mean=65716 + 14 * 1480), [vintr()],
               "fail", "differ"),
              ("vi-intr-latency: a timed-out console point derives no lag", vintr(timeout=1), [vintr()], "fail", "lacks")]
    for name, hw, model, want, said in vintrs:
        got, detail = compare(vintr_q, [hw], model)
        ok = got == want and said in detail
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {detail[:120]})")
    cases += vintrs
    irqclr_q = next(q for q in questions() if q["id"] == "irq-clear")

    def irqclr(fired):
        return Log(sample_log("".join(f"#bench cpu2-irqclr {line}-d{d} d={d} reps=2 min=18 max=41 lo=9 hi=9 fired={f}\n"
                                      for line in ("timer", "mi") for d, f in enumerate(fired)), rom="kit-cpu2"))
    irqclrs = [("irq-clear: the console samples as the fork does (0, 4, 4)", irqclr((0, 4, 4)), "pass", "6 values"),
               ("irq-clear: the delayed CP0 write rule (4, 4, 4, scratch build)", irqclr((4, 4, 4)), "fail", "differ"),
               ("irq-clear: a line that reaches Cause one instruction late (0, 0, 4)", irqclr((0, 0, 4)), "fail", "differ")]
    for name, hw, want, said in irqclrs:
        got, detail = compare(irqclr_q, [hw], [irqclr((0, 4, 4))])
        ok = got == want and said in detail
        failed += not ok
        print(f"kit: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {detail[:120]})")
    cases += irqclrs
    mm_cases, mm_failed = mm_bench.self_test()
    cases += [None] * mm_cases
    failed += mm_failed
    print(f"kit.py: self-test: {len(cases)} cases, {failed} failed")
    return failed


def span2_log(period=0, stall=256, steady=60.0, at=()):
    """A kit-span2 log: 256-line write-only rectangles at 32 bpp (16 bpp: twice the pixels per period)
    whose clock grows 256 rclk per pixel plus `stall` at the first pixel of every `period` px past the
    second (0: never) or at each width in `at` (both depths), each width off by the instrument's worst error against the verdict
    (one poll period and two refreshes up on a width without a step, poll plus one refresh down on a step); and IM_RD
    rectangles costing `steady` rclk per 64 B half and line."""
    lines = 256
    body = ""
    for bpp in (32, 16):
        p = period * 32 // bpp
        clock = 1000
        for w in range(1, 81):
            step = w in at or p and w > 2 * p and w % p == 1
            clock += lines + (stall - derived.POLL_RCLK - derived.REFRESH_RCLK if step else derived.POLL_RCLK + 2 * derived.REFRESH_RCLK - 0.5)
            body += f"#bench span-write b{bpp}-w{w} bpp={bpp} w={w} h={lines} n=1 vi=off reps=4 min=1 max=1 clock={int(clock)}\n"
        for w in (160, 320):
            body += (f"#bench span-write b{bpp}-w{w} bpp={bpp} w={w} h={lines} n=1 vi=off reps=4 min=1 max=1 "
                     f"clock={int(clock + (w - 80) * lines)}\n")
    for w in (1, 8, 16, 32, 64, 128, 160, 192, 256, 320):
        body += (f"#bench span-imrd b32-w{w} bpp=32 w={w} h={lines} n=1 vi=off reps=4 min=1 max=1 "
                 f"clock={int(10000 + max(0, w // 16 - 1) * steady * lines)}\n")
    return Log(sample_log(body, rom="kit-span2"))


def span2_self_test():
    """kit-span2's derived categories under the instrument's worst error, and the question rows' rule."""
    out = []
    for name, log, key, field, want in [
            ("a 1 rclk per line stall every 4 px at 32 bpp reads segment", span2_log(4), "release-b32", "release", "segment"),
            ("... and every 8 px at 16 bpp", span2_log(4), "release-b16", "release", "segment"),
            ("a stall every 16 px reads half", span2_log(16), "release-b32", "release", "half"),
            ("no stall reads no-step under the worst error", span2_log(0), "release-b32", "release", "no-step"),
            ("a stall the error could make reads no-step", span2_log(16, stall=60), "release-b32", "release", "no-step"),
            ("a stall every 8 px at 32 bpp reads period-8", span2_log(8), "release-b32", "release", "period-8"),
            ("one stall at 40 px reads single-40", span2_log(at={40}), "release-b32", "release", "single-40"),
            ("step spacings 6 and 4 tied as most common read their gcd, period-2",
             span2_log(at={10, 16, 22, 26, 30}), "release-b32", "release", "period-2"),
            ("IM_RD at 21.5 rclk per half reads wire-bound", span2_log(steady=21.5), "port", "port", "wire-bound"),
            ("IM_RD at 22 rclk per half reads above-wire", span2_log(steady=22), "port", "port", "above-wire")]:
        rom = "span-imrd" if key == "port" else "span-write"
        got = log.records.get((rom, key), {}).get(field)
        out.append(got == want)
        print(f"kit: self-test: kit-span2: {name}: {'ok' if got == want else 'FAILED'} ({got})")
    rows = {q["id"]: q for q in questions()}
    for qid, hw, model, want in [("span-write-release", span2_log(4), span2_log(16), "fail"),
                                 ("span-write-release", span2_log(16), span2_log(16), "pass"),
                                 ("mem-overhead-pipelined", span2_log(steady=18), span2_log(), "fail")]:
        got, detail = compare(rows[qid], [hw], [model])
        out.append(got == want)
        print(f"kit: self-test: kit-span2: {qid}, want {want}: {'ok' if got == want else 'FAILED'} ({got}: {detail[:90]})")
    return out


#The values one noise state gives each noise use, per source that reads the a, b and c LFSRs
#(docs/research/rdp-noise.md:39-41). ad is G_AD_NOISE: Angrylion (noise >> 6) & 7, MiSTer random2 & '1'.
#cd is G_CD_NOISE and ac the G_AC_DITHER threshold: Angrylion's irand and MiSTer's own LFSR read none of
#a, b and c, so no cited mapping exists for a reader to test.
NOISE_MAPPINGS = {"ad": {"angrylion": tuple(range(8)), "mister-odd": (1, 3, 5, 7)}, "cd": {}, "ac": {}}
#Every value a use can take from any source: 3 bits of alpha, 3 bits per color channel, an 8-bit threshold.
NOISE_RANGE = {"ad": range(8), "cd": range(8), "ac": range(256)}
#prehw-plan.md U-NOISE-READER: (2K+1) x mappings x 2^-b must be below this.
NOISE_RATE_MAX = 1e-6


def noise_draw(name, width, bpp, commands):
    """A kit-noise draw's noise uses and constants, decoded from the command list the ROM runs."""
    from romgen.suites.calib import sets
    op = {c >> 56: c for c in commands}
    if op.get(0xFC) != sets.prim_combiner():
        raise ValueError(f"{name}: not drawn with the PRIMITIVE combiner")
    mode0, mode1 = op[0xEF] >> 32 & 0xFFFFFF, op[0xEF] & 0xFFFFFFFF
    uses = [u for u, on in (("cd", mode0 >> 6 & 3 == 2), ("ad", mode0 >> 4 & 3 == 2), ("ac", mode1 & 3 == 3)) if on]
    return {"width": width, "bits16": bpp == 2, "uses": uses, "compare": mode1 & 1 == 1,
            "prim": (op[0xFA] & 0xFFFFFFFF).to_bytes(4, "big"), "blend_a": op.get(0xF9, 0) & 0xFF}


def noise_draws():
    """Every kit-noise draw that feeds noise to G_AD_NOISE, G_CD_NOISE or G_AC_DITHER (sets.NOISE_CASES)."""
    from romgen.suites.calib import sets
    out = {}
    for name, width, bpp, draws in sets.NOISE_CASES:
        try:
            out[name] = noise_draw(name, width, bpp, draws[0][1])
        except ValueError:
            continue
    return out


def noise_pixel(draw, ad=0, cd=0, ac=0):
    """What one pixel of the draw stores for the given noise values: None when alpha compare rejects it."""
    *rgb, a = draw["prim"]
    if "cd" in draw["uses"]:
        #ParaLLEl rgb_dither (the fork's rdp_blend.c rdp_blender_dither_color): up to the next multiple of
        #8 iff the low 3 bits exceed the dither value.
        rgb = [min(c - (c & 7) + 8, 255) if (c & 7) > cd else c for c in rgb]
    if draw["bits16"]:
        rgb = [c >> 3 for c in rgb]
    if "ad" in draw["uses"]:
        a = min(a + ad, 255)
    if draw["compare"] and a < (ac if "ac" in draw["uses"] else draw["blend_a"]):
        return None
    return tuple(rgb)


def noise_bits(draw):
    """An upper bound on b, the logged pixel bits two mappings can disagree on: 0 when every noise value
    any source could give stores the same pixel, else every pixel of the draw."""
    import itertools
    ranges = [NOISE_RANGE[u] if u in draw["uses"] else (0,) for u in ("ad", "cd", "ac")]
    stored = {noise_pixel(draw, *v) for v in itertools.product(*ranges)}
    return draw["width"] if len(stored) > 1 else 0


def noise_rate(snaps, draws):
    """(verdict, detail) for one question over its kit-noise snaps. Only a snap whose every noise use has
    a cited mapping can be tested. The false-match rate at K = 0, mappings x 2^-b with b bounded above by
    noise_bits, is a floor: any K multiplies it by 2K+1. No testable snap, or a floor at or above
    NOISE_RATE_MAX, leaves the question report-only."""
    untestable = [s for s in snaps if not all(NOISE_MAPPINGS[u] for u in draws[s]["uses"])]
    testable = [s for s in snaps if s not in untestable]
    reasons = [f"{s}: no cited a/b/c mapping for {' '.join(u for u in draws[s]['uses'] if not NOISE_MAPPINGS[u])}"
               for s in untestable]
    if not testable:
        return "report-only", "; ".join(reasons + ["no snap left to test"])
    mappings = math.prod(len(NOISE_MAPPINGS[u]) for u in sorted({u for s in testable for u in draws[s]["uses"]}))
    bits = sum(noise_bits(draws[s]) for s in testable)
    floor = mappings * 2.0 ** -bits
    if floor >= NOISE_RATE_MAX:
        reasons.append(f"{' '.join(testable)}: false-match rate >= {floor:.3g} at K = 0 ({mappings} mappings, b <= {bits})")
        return "report-only", "; ".join(reasons)
    return "not ruled out", "; ".join(reasons + [f"{' '.join(testable)}: rate floor {floor:.3g} ({mappings} mappings, "
                                                 f"b <= {bits}); the offset reader is not built"])


def noise_table(run_dir=None, root=ROOT):
    """The reader's report for every question over a noise-mapping snap. With a calibration/run.sh output,
    also the fork's distinct dumps of each snap over every layout pad and boot delay: a snap whose bound
    is b = 0 must store one dump however far apart the logs' noise offsets are (rect-1016 shows how far)."""
    draws = noise_draws()
    logs = [log for pad_logs in model_layouts(run_dir, "kit-noise").values() for log in pad_logs] if run_dir else []
    dumps = lambda snap: len({log.records.get(("snap", snap), {}).get("hash") for log in logs})  # noqa: E731
    out = ["| Question | Snap | Noise uses | Bits that can differ (bound) | Fork dumps over logs |", "|---|---|---|---|---|"]
    verdicts, contradicted = [], []
    for q in questions(root):
        snaps = [p.removeprefix("snap/") for p in q["points"].split() if p.removeprefix("snap/") in draws]
        if q["kit"] != "kit-noise" or not snaps:
            continue
        for s in snaps:
            seen = f"{dumps(s)} of {len(logs)} (rect-1016: {dumps('rect-1016')})" if logs else "-"
            if logs and not noise_bits(draws[s]) and dumps(s) > 1:
                contradicted.append(s)
            out.append(f"| `{q['id']}` | `{s}` | {' '.join(draws[s]['uses'])} | {noise_bits(draws[s])} | {seen} |")
        verdicts.append(f"{q['id']}: " + ": ".join(noise_rate(snaps, draws)))
    out += [""] + verdicts
    out += [f"fork contradicts b = 0 for {', '.join(contradicted)}"] if contradicted else []
    return "\n".join(out), not contradicted


def noise_self_test():
    """The reader's bound on the kit's own draws, and on mutated draws that do carry noise."""
    draws = noise_draws()
    from romgen import rcp
    from romgen.suites.calib import sets

    def mutated(name, prim):
        width, bpp, lists = next((w, b, d) for n, w, b, d in sets.NOISE_CASES if n == name)
        commands = [rcp.set_prim_color(prim, level_frac=0xFF) if c >> 56 == 0xFA else c for c in lists[0][1]]
        return {**draws, name: noise_draw(name, width, bpp, commands)}

    out = []
    for name, snaps, among, want in [
            ("ad-noise-threshold: alpha 0x78 + 7 < 0x80 stores nothing for any value", ["ad-noise-threshold"], draws, "report-only"),
            ("cd-noise-16: gray 0x80 has low bits 0, so no dither rounds it", ["cd-noise-16"], draws, "report-only"),
            ("ac-dither: no source maps the threshold", ["ac-dither"], draws, "report-only"),
            ("mutation: alpha 0x7F, written iff the value is not 0, is not ruled out",
             ["ad-noise-threshold"], mutated("ad-noise-threshold", 0xFFFFFF7F), "not ruled out"),
            ("mutation: gray 0x84 carries noise but still has no cited mapping",
             ["cd-noise-16"], mutated("cd-noise-16", 0x848484FF), "report-only")]:
        got, detail = noise_rate(snaps, among)
        out.append(got == want)
        print(f"kit: self-test: noise reader: {name}: {'ok' if got == want else 'FAILED'} ({got}: {detail})")
    for name, draw, want in [("gray 0x80 bounds b at 0", draws["cd-noise-16"], 0),
                             ("gray 0x84 bounds b at 256", mutated("cd-noise-16", 0x848484FF)["cd-noise-16"], 256)]:
        bits = noise_bits(draw)
        out.append(bits == want)
        print(f"kit: self-test: noise reader: {name}: {'ok' if bits == want else 'FAILED'} ({bits})")
    return out


def layout_rows(run_dir, root=ROOT):
    """(question, controller setup, values that differ by pad, all compared values, pads whose fork logs
    read as a capture fail against pad 0's, {pad: spread}) for every kit-ROM question in a
    calibration/run.sh output."""
    for q in questions(root):
        if q["kit"] not in KIT_ROMS:
            continue
        for pads in [None, 0b1111] if q["kit"] == "kit-dma" else [None]:
            model = model_layouts(run_dir, q["kit"], pads)
            moved, spreads = layout_moved(q, model)
            flips = [pad for pad in model if pad and compare(q, model[pad], model[0])[0] != "pass"]
            yield q, pads, moved, sorted(set().union(*spreads.values())), flips, spreads


def layout_table(run_dir, root=ROOT):
    """Each kit question's layout sensitivity in a calibration/run.sh output: how many of its compared
    values differ by layout pad, the pads at which the fork's own logs, read as a capture, fail against
    pad 0's (a verdict a pad-0 console run could not see), and the value whose range moves most."""
    out = ["| Question | Kit | Controllers | Layout-sensitive | Values that differ by pad | Pads whose fork logs fail against pad 0 | Widest: value, pad 0, all pads |",
           "|---|---|---|---|---|---|---|"]
    numeric = lambda vs: vs and all(isinstance(v, (int, float)) for v in vs)  # noqa: E731
    show = lambda vs: f"{min(vs)}..{max(vs)}" if numeric(vs) else f"{len(set(vs))} distinct"  # noqa: E731
    for q, pads, moved, keys, flips, spreads in layout_rows(run_dir, root):
        widest = "-"
        if moved:
            joint = lambda k, among=spreads: [v for pad in among for v in spreads[pad].get(k, ())]  # noqa: E731
            width = lambda vs: max(vs) - min(vs) if numeric(vs) else len(set(vs))  # noqa: E731
            k = max(moved, key=lambda k: (width(joint(k)) - width(joint(k, [0]) or [0]), k))
            widest = f"{k[0]} {k[1]}: {show(joint(k, [0]))}, {show(joint(k))}"
        out.append(f"| `{q['id']}` | `{q['kit']}` | {4 if pads else 1} | {'yes' if moved else 'no'} | {len(moved)} of {len(keys)} | "
                   f"{','.join(map(str, flips)) or 'none'} | {widest} |")
    return "\n".join(out)


PHOTO_BYTES = 2048


def run_table(run_dir, root=ROOT):
    """hardware-run.md's run-order table from a calibration/run.sh output: each console build's fork
    run time (kit-pif's: to its last COUNT), log size, whether it is short enough to film, the layout pads
    the console runs it at (every pad when one of its questions is layout-sensitive, see compare_layouts),
    and the questions it answers."""
    run_dir = Path(run_dir)
    asks = {}
    for q in questions(root):
        asks.setdefault(q["kit"], []).append(q["id"])
    padded = {q["kit"] for q, _, moved, *_ in layout_rows(run_dir, root) if moved}
    pads = sorted(model_layouts(run_dir, "kit-cpu"))
    out = ["| # | ROM | Runs for | Log | Film it? | Layout pads | Answers |", "|---|---|---|---|---|---|---|"]
    for n, (rom, (_, _, walks)) in enumerate(KIT_ROMS.items(), 1):
        base = run_dir / ("boot-1" if walks else "single") / rom
        err = base.with_suffix(".err").read_text(errors="replace")
        secs = float(re.search(r"emulated_s=([\d.]+)", err).group(1))
        if rom == PIF_ROM:
            secs = pif_report(Log(base.with_suffix(".txt").read_bytes()))[0] / COUNT_HZ
        size = len(base.with_suffix(".txt").read_bytes())
        layouts = f"{pads[0]}-{pads[-1]}" if rom in padded and len(pads) > 1 else "0"
        out.append(f"| {n} | `{rom}` | {secs:.1f} s | {size / 1000:.1f} KB | {'yes' if size <= PHOTO_BYTES else 'no'} | "
                   f"{layouts} | {', '.join(f'`{q}`' for q in asks.get(rom, [])) or 'a report, no question'} |")
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--table"]:
        print(run_table(sys.argv[2]))
        sys.exit(0)
    if sys.argv[1:2] == ["--layout"]:
        print(layout_table(sys.argv[2]))
        sys.exit(0)
    if sys.argv[1:2] == ["--noise-rate"]:
        table, consistent = noise_table(sys.argv[2] if sys.argv[2:] else None)
        print(table)
        sys.exit(0 if consistent else 1)
    if sys.argv[1:2] == ["--hist"] and sys.argv[2:]:
        for path, log in sorted((p, l) for logs in read_logs(sys.argv[2:]).values() for p, l in logs):
            for key, metric, hist in histograms(log):
                print(f"{path}\t{key}\t{metric}\t{hist}")
        sys.exit(0)
    if sys.argv[1:2] == ["--self-test"]:
        sys.exit(1 if self_test() else 0)
    if sys.argv[1:2] == ["--verify-run"]:
        errs = verify_run(Path(sys.argv[2]))
        for e in errs:
            print(e, file=sys.stderr)
        print(f"kit: {len(list(Path(sys.argv[2]).glob('*/**/*.srm')))} SRAM copies checked, {len(errs)} errors",
              file=sys.stderr)
        sys.exit(1 if errs else 0)
    sys.exit("usage: kit.py --verify-run RUN_DIR | --table RUN_DIR | --layout RUN_DIR | --noise-rate [RUN_DIR] | --hist LOG... | --self-test")
