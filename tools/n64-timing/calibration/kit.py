"""The calibration kit's data model: kit ROMs, questions, logs, and the hardware-vs-model comparison.

A kit log is what a kit ROM prints (romgen hwout.py): a `#kit` header, records, a `#kit-end`
footer. Records are keyed (rom, point):
  #bench <rom> <point> k=v ...    a measurement point (bench format); rom is the bench ROM name
  @snap <name> <size> <hash>      a dumped surface: key ("snap", name), fields size, hash
  @<test>.<value> <n> ...         a self-checking suite's result: key (<kit rom>, "<test>.<value>"), v0 ...
A capture is one log from the console. The model side is the same ROM run on the fork at each
boot delay (calibration/run.sh). A question (questions.tsv) names points and metrics and a rule;
`compare` turns the console's values and the model's into pass or fail.
"""
import fnmatch
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
from romgen.suites.bench import report as bench_report  # noqa: E402

QUESTIONS = "tools/n64-timing/calibration/questions.tsv"
HARDWARE = "docs/calibration/hardware"
QUESTION_COLUMNS = ["id", "question", "decides", "kit", "points", "metric", "rule", "closes", "source"]
RULE = re.compile(r"^(exact|range:(abs|rel):[\d.]+|-)$")

#Every kit ROM: suite, build.py --set, and whether the fork walks boot delays for it (calib suite).
KIT_ROMS = {
    "kit-cpu": ("calib", "kit-cpu", True),
    "kit-vi": ("calib", "kit-vi", True),
    "kit-dma": ("calib", "kit-dma", True),
    "kit-hpos": ("calib", "kit-hpos", True),
    "kit-rdp": ("calib", "kit-rdp", True),
    "kit-span": ("calib", "kit-span", True),
    "kit-noise": ("calib", "kit-noise", True),
    "rdpstat-1prim": ("rdpstat", "1prim", False),
    "rdpstat-dpc": ("rdpstat", "dpc", False),
    "rdpstat-systemtest": ("rdpstat", "systemtest", False),
    "rdpstat-unsynced": ("rdpstat", "unsynced", False),
    "nemu64-timing": ("nemu64", "timing", False),
}
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
        self.header, self.footer, self.records, self.complete = {}, {}, {}, False
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
            elif len(parts) == 4 and parts[0] == "@snap":
                self.records[("snap", parts[1])] = {"size": int(parts[2]), "hash": parts[3]}
            elif parts and re.match(r"^@\d+\.\d+$", parts[0]):
                self.records[(rom, parts[0][1:])] = {f"v{i}": int(p) if p.lstrip("-").isdigit() else p
                                                     for i, p in enumerate(parts[1:])}
        derive(self.records)

    @property
    def rom(self):
        return self.header.get("rom")


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
    for point, p in by_rom.get("count-fields", {}).items():
        p["ticks_per_field"] = round(p["min"] / p["fields"], 3)
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


def read_logs(paths):
    """Kit logs by ROM id from files: ISViewer text, SRAM dumps (.srm/.sra/.sav, either byte order)
    and transcribed screen text."""
    out = {}
    for path in paths:
        data = Path(path).read_bytes()
        if b"#kit rom=" not in data and b"k#ti" in data:
            data = b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
        log = Log(data.rstrip(b"\0"))
        if log.rom:
            out.setdefault(log.rom, []).append((Path(path), log))
    return out


def model_logs(run_dir, rom):
    """The fork's logs of one kit ROM in a calibration/run.sh output, one per boot delay."""
    run_dir = Path(run_dir)
    paths = sorted(run_dir.glob(f"boot-*/{rom}.txt")) + sorted(run_dir.glob(f"single/{rom}.txt"))
    return [Log(p.read_bytes()) for p in paths]


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
    rule = question["rule"]
    bad, checked = [], 0
    for pattern in question["points"].split():
        for metric in question["metric"].split():
            want = values(model, pattern, metric)
            got = values(hw, pattern, metric)
            for key, hv in sorted(got.items()):
                mv = want.get(key)
                if mv is None:
                    continue
                checked += 1
                if rule == "exact":
                    ok = set(hv) <= set(mv)
                    shown = f"{key} {metric} console {sorted(set(hv))} model {sorted(set(mv))}"
                else:
                    _, kind, tol = rule.split(":")
                    tol = float(tol)
                    lo, hi = min(mv), max(mv)
                    slack = tol if kind == "abs" else tol / 100 * max(abs(lo), abs(hi))
                    ok = min(hv) <= hi + slack and max(hv) >= lo - slack
                    shown = f"{key} {metric} console {min(hv)}..{max(hv)} model {lo}..{hi} ({rule})"
                if not ok:
                    bad.append(shown)
    if not checked:
        return "fail", f"no console value matches {question['points']} {question['metric']}; the capture lacks the points"
    if bad:
        return "fail", f"{len(bad)} of {checked} values differ; first {bad[0]}"
    return "pass", f"{checked} values agree ({rule})"


def captures(root=ROOT):
    """Every ingested console log under docs/calibration/hardware, by kit ROM."""
    base = Path(root) / HARDWARE
    paths = sorted(base.glob("*/*.log")) if base.exists() else []
    return {rom: [log for _, log in logs] for rom, logs in read_logs(paths).items()}, sorted({p.parent.name for p in paths})


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
    if kit.startswith(("ext:", "none")):
        return "pending:calibration-16", f"{kit}: no in-repo kit ROM; hardware-run.md says how to run and read it"
    hw, ids = captures(root)
    logs = [log for log in hw.get(kit, []) if log.complete]
    if not logs:
        return "pending:calibration-16", f"no complete console capture of {kit} in {HARDWARE}"
    model = [m for m in model_logs(model_dir, kit) if m.complete]
    if not model:
        return "missing", f"no fork run of {kit} in {model_dir}; run tools/n64-timing/calibration/run.sh there"
    res, detail = compare(q, logs, model)
    return res, f"{detail}; capture {','.join(ids)}, {len(logs)} console and {len(model)} fork logs"
