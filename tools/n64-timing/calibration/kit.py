#!/usr/bin/env python3
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

QUESTIONS = "tools/n64-timing/calibration/questions.tsv"
HARDWARE = "docs/calibration/hardware"
QUESTION_COLUMNS = ["id", "question", "decides", "kit", "points", "metric", "rule", "closes", "source", "boot"]
#How the console was started before the capture: power-on (a power cycle) or reset (the Reset button
#after a kit ROM ran). A capture file named *.reset.* is a reset capture.
BOOTS = ("power-on", "reset")
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
    "nemu64-cycle": ("nemu64", "cycle", False),
    "nemu64-cop0hazard": ("nemu64", "cop0hazard", False),
    "kit-tex": ("calib", "kit-tex", True),
    "kit-zmem": ("calib", "kit-zmem", True),
    "kit-cpu2": ("calib", "kit-cpu2", True),
    "kit-bus": ("calib", "kit-bus", True),
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
            elif parts and re.match(r"^@\d+\.\d+$", parts[0]):
                self.records[(rom, parts[0][1:])] = {f"v{i}": int(p) if p.lstrip("-").isdigit() else p
                                                     for i, p in enumerate(parts[1:])}
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


def model_logs(run_dir, rom, pads=None):
    """The fork's logs of one kit ROM in a calibration/run.sh output, one per boot delay, run with the
    controllers whose ports answered as `pads` did."""
    run_dir = Path(run_dir) / PAD_SETUPS[pads]
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
    bad, lacking, checked = [], [], 0
    for pattern in question["points"].split():
        for metric in question["metric"].split():
            want = values(model, pattern, metric)
            got = values(hw, pattern, metric)
            for key in sorted(set(want) - set(got)):
                lacking.append(f"{key} {metric}")
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
    if lacking:
        return "fail", f"the capture lacks {len(lacking)} of {len(lacking) + checked} model values; first {lacking[0]}"
    if bad:
        return "fail", f"{len(bad)} of {checked} values differ; first {bad[0]}"
    return "pass", f"{checked} values agree ({rule})"


def ext_thar0(root, model_dir, paths):
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


def ext_snapper64(root, model_dir, paths):
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


def ext_systembench(root, model_dir, paths):
    """n64-systembench's ISViewer text from the console against the fork's run of the same binary
    (run.sh ext/systembench.txt), every row of systembench/rows.tsv under main.c's own pass rule with the
    fork's reading as the expected value. Pointwise for that binary only: a one to three instruction
    change in a poll loop moves the poll rows by up to 10 RCP cycles (verify-83), so a console run of
    another build of the same source decides nothing here."""
    from systembench import report as sb
    model_path = Path(model_dir) / "ext" / "systembench.txt"
    if not model_path.exists():
        return "missing", (f"no fork run of n64-systembench in {model_path}; build it (build-systembench.sh) and run "
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


#External ROMs a capture can hold: kit column `ext:<name>`, the capture file or directory name
#prefix `ext-<name>`, and the reader that compares it (None: stored, compared by hand per
#hardware-run.md until a reader exists).
EXT_ROMS = {
    "thar0": ext_thar0,
    "snapper64": ext_snapper64,
    "systembench": ext_systembench,
    #The published ROM logs no COUNT, and its source carries no license, so no build of it can.
    "pi_dma_test": None,
    #The fork side needs Scott's BENCH build of mm-decomp-60fps run on n64-run; no in-repo tool builds it.
    "mm-bench": None,
}
#The fork-side runner of each external ROM's checks (checks.tsv), so behaviors.py can tell a console run
#that repeats a row's fit data from an independent one.
EXT_SUITES = {"thar0": "thar0", "snapper64": "snapper", "systembench": "systembench", "pi_dma_test": "pidma",
              "mm-bench": "mm"}


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
        return reader(root, model_dir, paths)
    hw, ids = captures(root)
    boot = q.get("boot", "power-on")
    logs = [log for log in hw.get(kit, []) if log.complete and log.boot == boot]
    if not logs:
        return "pending:calibration-16", f"no complete {boot} console capture of {kit} in {HARDWARE}"
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
        model = [m for m in model_logs(model_dir, kit, pads) if m.complete]
        if not model:
            return "missing", f"no fork run of {kit} in {model_dir}/{PAD_SETUPS[pads]}; run tools/n64-timing/calibration/run.sh there"
        res, detail = compare(q, group, model)
        results.append(res)
        setup = "" if pads is None else f"{bin(pads).count('1')} pads: "
        details.append(f"{setup}{detail}, {len(group)} console and {len(model)} fork logs")
    res = "fail" if "fail" in results else "pass"
    return res, f"{'; '.join(details)}; capture {','.join(ids)}"


def verify_run(run_dir):
    """Errors in a calibration/run.sh output: a log without a valid footer, a cartridge SRAM copy that
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
        if not log.complete:
            errors.append(f"{txt}: no valid #kit-end footer")
            continue
        srm = txt.with_suffix(".srm")
        if not srm.exists():
            errors.append(f"{txt}: the run left no cartridge SRAM ({srm.name})")
        elif srm.read_bytes() != data[:SRAM_BYTES].ljust(SRAM_BYTES, b"\0"):
            errors.append(f"{srm}: the SRAM copy differs from the ISViewer copy")
        if log.pi != hwout.DOM1_HEADER:
            errors.append(f"{txt}: domain-1 PI timing at the end {log.pi}, the ROM header's {hwout.DOM1_HEADER}")
        if log.timeouts != {"pi": 0, "rdp": 0}:
            errors.append(f"{txt}: #kit-timeout {log.timeouts or 'missing'}; on the fork no wait may give up")
    return errors


def sample_log(body="#bench dcb sw-lw pairs=16 reps=8 min=24 max=101\n#bench dcb nop-nop pairs=16 reps=8 min=16 max=16\n"):
    text = f"#kit rom=kit-cpu sha=0 fmt=1 ri_mode=0xe\n{body}".encode()
    return text + f"#kit-end rom=kit-cpu bytes={len(text)} fnv={fnv(text):08x}\n".encode()


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
    for name, hw, want in compares:
        got, detail = compare(q, hw, model)
        ok = got == want
        failed += not ok
        print(f"kit: self-test: compare, {name}: {'ok' if ok else 'FAILED'} ({got}: {detail})")
    cases += compares
    hung = Log(sample_log("#bench dcb sw-lw pairs=16 reps=8 min=24 max=101\n#kit-timeout pi=0 rdp=2\n"))
    ok = hung.complete and hung.timeouts == {"pi": 0, "rdp": 2}
    failed += not ok
    print(f"kit: self-test: a log whose RDP wait gave up twice reads timeouts rdp=2: {'ok' if ok else 'FAILED'} ({hung.timeouts})")
    cases.append(("timeouts", None, None))
    print(f"kit.py: self-test: {len(cases)} cases, {failed} failed")
    return failed


PHOTO_BYTES = 2048


def run_table(run_dir, root=ROOT):
    """hardware-run.md's run-order table from a calibration/run.sh output: each console build's fork
    run time, log size, whether it is short enough to film, and the questions it answers."""
    run_dir = Path(run_dir)
    asks = {}
    for q in questions(root):
        asks.setdefault(q["kit"], []).append(q["id"])
    out = ["| # | ROM | Runs for | Log | Film it? | Answers |", "|---|---|---|---|---|---|"]
    for n, (rom, (_, _, walks)) in enumerate(KIT_ROMS.items(), 1):
        base = run_dir / ("boot-1" if walks else "single") / rom
        err = base.with_suffix(".err").read_text(errors="replace")
        secs = float(re.search(r"emulated_s=([\d.]+)", err).group(1))
        size = len(base.with_suffix(".txt").read_bytes())
        out.append(f"| {n} | `{rom}` | {secs:.1f} s | {size / 1000:.1f} KB | {'yes' if size <= PHOTO_BYTES else 'no'} | "
                   f"{', '.join(f'`{q}`' for q in asks.get(rom, []))} |")
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--table"]:
        print(run_table(sys.argv[2]))
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
    sys.exit("usage: kit.py --verify-run RUN_DIR | --table RUN_DIR | --self-test")
