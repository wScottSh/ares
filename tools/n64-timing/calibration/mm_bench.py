#!/usr/bin/env python3
"""The Majora's Mask BENCH ROM (kit.py EXT_ROMS `mm-bench`): its pinned build, its per-scene ROMs, its
IS-Viewer log, and the console-vs-fork comparison.

The BENCH build of wScottSh/mm-decomp-60fps (tools/bench/README.md there) boots into one Play scene or the
file-select screen, warms up, records per-frame values in RAM, and prints them over IS-Viewer at the end:
  BENCH START scene=<i> name=<scene> seed=0x<hex> warmup=<n> frames=<n> emux=<0|1> ...
  BENCH COLUMNS frame vi pre_ticks ... rdram_dp
  BENCH F <frame> <value> ...        one per measured frame
  BENCH END
`vi` is the VI retraces between game-frame ends (fields per game frame); `rdp_ticks` is gRDPTimeTotal,
the OSTime ticks from the gfx task's start to the DP full sync, so it includes the wait for the RSP.
`dpc_clock` and `dpc_pipebusy` are the DPC counters (RCP clocks) between game-frame ends.
A question reads the scenes its points column names (kit.py ext_mm_bench).
The scene comes from a BenchConfig block (magic BNCH) patched into a copy of the ROM, so each scene
is its own ROM file with its own sha256. build-mm-bench.sh builds the pinned commit and patches them.
"""
import hashlib
import re
import statistics
import struct
import subprocess
import sys
from pathlib import Path

REPO = "wScottSh/mm-decomp-60fps"
#mm-decomp-60fps main at the merge of #2 (bench/filesel: the file-select scenes and DPC counters).
COMMIT = "bff939cac321daee240f2d015433c44863d8eca6"
BASE_SHA256 = "7ace785964e320052e337768fd891b6290988e6c9ba597a3e78b31cf96dfea72"
#bench.py's defaults at COMMIT: 120 warmup frames, 600 measured (BENCH_MAX_FRAMES), seed 0x12345678.
WARMUP, FRAMES, SEED = 120, 600, 0x12345678
#sBenchScenes in src/code/bench.c at COMMIT: name -> (index, sha256 of the patched ROM). Scene 0 with the
#defaults is the base ROM unchanged, so its sha256 is BASE_SHA256.
SCENES = {
    "south_clock_town": (0, "7ace785964e320052e337768fd891b6290988e6c9ba597a3e78b31cf96dfea72"),
    "termina_field": (1, "cb32f3f0b3ac9df3e41a8d7bfdaafa98cd842d12882e8f90a624d0ab216ffa72"),
    "mountain_village_winter": (2, "7577eade2b2fa41ebb70d71705580ceb35587d7897374f9c72e8d502ba5ffa41"),
    "great_bay_coast": (3, "290af76ead84a5e159156d3857cfacdaa444bcdf7a514f287c6c8f37335a5bc5"),
    "file_select_empty": (4, "bf0fae558b591016aae96bb99315a3fb7cc9346f5248ab772aca3fba6f67600d"),
    "file_select_named": (5, "60f4587dc65594e69d523c42ea03b41e1a4daf1f1030b16c6deba5958429c777"),
}
CONFIG_MAGIC = b"BNCH"
#The CIC boot code checksums ROM 0x1000..0x101000, so a patch there would not boot on a console.
CHECKSUMMED_END = 0x101000
COMPARED = ("vi", "rdp_ticks")
#Reported beside the verdict, not judged: the RDP's own busy time from the DPC counters.
REPORTED = ("rdp_ticks", "dpc_pipebusy")
#Reported, not judged, when a capture holds both: the named-only work is the gap between the two
#file-select screens (prehw-plan section 3), so both sides' named-minus-empty median gap is shown.
GAP = ("file_select_empty", "file_select_named")


#The pinned commit's git objects (written by --evidence, read by behaviors.py): its first-parent history back to
#the merge of MERGED_PR, and the trees down to README. A content hash that does not match its name is an error.
OBJECTS = Path(__file__).with_name("mm-decomp-objects.txt")
MERGED_PR = 1
README = ("tools", "bench", "README.md")
#README sentences that say the bench runs on the fork and that the func_80173B48 pin is gone (wScottSh/mm-decomp-60fps#1).
README_SENTENCES = {"fork": "runs the ROM on the ares timing-model fork", "pin": "so the pin is gone"}


def git_hash(kind, body):
    return hashlib.sha1(f"{kind} {len(body)}\0".encode() + body).hexdigest()


def tree_entries(text):
    """`git cat-file -p` tree text as [(mode, sha, name)]."""
    return [(head.split()[0], head.split()[2], name) for head, _, name in
            (line.partition("\t") for line in text.decode().split("\n") if line)]


def tree_raw(text):
    return b"".join(f"{mode.lstrip('0')} {name}\0".encode() + bytes.fromhex(sha) for mode, sha, name in tree_entries(text))


def read_objects(path=OBJECTS):
    """{sha: (kind, body)} from an objects file, and the errors: a body that does not hash to its sha is an error
    and is left out, so it proves nothing."""
    data, objects, errors, at = Path(path).read_bytes(), {}, [], 0
    while at < len(data):
        end = data.index(b"\n", at)
        head, at = data[at:end].decode(), end + 1
        if head.startswith("#"):
            continue
        kind, sha, size = head.split()
        body, at = data[at:at + int(size)], at + int(size) + 1
        if git_hash(kind, tree_raw(body) if kind == "tree" else body) != sha:
            errors.append(f"{Path(path).name}: the {kind} named {sha[:9]} does not hash to its name; rewrite the file "
                          f"with mm_bench.py --evidence <{REPO} checkout>")
        else:
            objects[sha] = (kind, body)
    return objects, errors


def commit_fields(body):
    head, _, message = body.decode().partition("\n\n")
    fields = {}
    for line in head.split("\n"):
        key, _, value = line.partition(" ")
        fields.setdefault(key, []).append(value)
    return fields, message.split("\n")[0]


def sentence(text, needle):
    """The sentence of a Markdown text that holds needle, or None."""
    flat = " ".join(line.lstrip("> ").strip() for line in text.split("\n"))
    return next((s for s in re.split(r"(?<=\.)\**\s+", flat) if needle in s), None)


def pin_evidence(path=OBJECTS, commit=COMMIT):
    """What the objects file proves about the pinned commit, and its errors: merge is (sha, subject) of the merge
    of MERGED_PR in commit's first-parent history, or None; readme maps each README_SENTENCES key to the sentence
    of README at commit that holds it, or None."""
    objects, errors = read_objects(path)
    merge, at, tree = None, commit, None
    while at in objects and merge is None:
        fields, subject = commit_fields(objects[at][1])
        tree = tree or fields["tree"][0]
        if subject.startswith(f"Merge pull request #{MERGED_PR} from "):
            merge = (at, subject)
        at = fields.get("parent", [None])[0]
    if commit not in objects:
        errors.append(f"{Path(path).name} has no commit object {commit[:9]} (mm_bench.py COMMIT); run mm_bench.py "
                      f"--evidence <{REPO} checkout>")
    for name in README:
        tree = next((sha for _, sha, entry in tree_entries(objects[tree][1]) if entry == name), None) if tree in objects else None
    text = objects[tree][1].decode() if tree in objects else ""
    return {"merge": merge, "readme": {k: sentence(text, v) for k, v in README_SENTENCES.items()}}, errors


def write_evidence(repo, path=OBJECTS):
    """Writes the objects pin_evidence reads, from a checkout of REPO, read-only (git cat-file)."""
    def cat(*args):
        return subprocess.run(["git", "-C", str(repo), "cat-file", *args], capture_output=True, check=True).stdout
    out, at = [b"# wScottSh/mm-decomp-60fps git objects: `<type> <sha> <bytes>`, then the body (a tree as cat-file -p "
               b"text). Written by mm_bench.py --evidence; behaviors.py checks each hash.\n"], COMMIT
    while at:
        body = cat("commit", at)
        out.append(f"commit {at} {len(body)}\n".encode() + body + b"\n")
        fields, subject = commit_fields(body)
        at = None if subject.startswith(f"Merge pull request #{MERGED_PR} from ") else fields["parent"][0]
    tree = commit_fields(cat("commit", COMMIT))[0]["tree"][0]
    for name in README:
        body = cat("-p", tree)
        out.append(f"tree {tree} {len(body)}\n".encode() + body + b"\n")
        tree = next(sha for _, sha, entry in tree_entries(body) if entry == name)
    body = cat("blob", tree)
    out.append(f"blob {tree} {len(body)}\n".encode() + body + b"\n")
    Path(path).write_bytes(b"".join(out))


def rom_name(scene):
    return f"mm-bench-{scene}.z64"


def patch(base, scene):
    """The base BENCH ROM with BenchConfig set to the scene and the pinned warmup, frames and seed."""
    at = base.find(CONFIG_MAGIC)
    if at < 0 or base.find(CONFIG_MAGIC, at + 1) >= 0:
        raise SystemExit("mm_bench: BenchConfig magic BNCH not found exactly once; not a BENCH=1 ROM")
    if at < CHECKSUMMED_END:
        raise SystemExit(f"mm_bench: BenchConfig at 0x{at:x}, inside the checksummed boot region")
    config = struct.pack(">4s4I", CONFIG_MAGIC, SCENES[scene][0], WARMUP, FRAMES, SEED)
    return base[:at] + config + base[at + len(config):]


def write_roms(base_path, out):
    """Writes every scene's ROM and rom-sha256.txt to out; fails on any sha256 other than the pin."""
    base = Path(base_path).read_bytes()
    got = hashlib.sha256(base).hexdigest()
    if got != BASE_SHA256:
        raise SystemExit(f"mm_bench: {base_path} has sha256 {got}, not the pinned {BASE_SHA256} ({REPO} {COMMIT[:9]})")
    lines, bad = [], []
    for scene, (_, want) in SCENES.items():
        rom = patch(base, scene)
        (Path(out) / rom_name(scene)).write_bytes(rom)
        sha = hashlib.sha256(rom).hexdigest()
        lines.append(f"{sha}  {rom_name(scene)}")
        if sha != want:
            bad.append(f"{rom_name(scene)} {sha}, pinned {want or 'none'}")
    (Path(out) / "rom-sha256.txt").write_text("\n".join(lines) + "\n")
    if bad:
        raise SystemExit("mm_bench: patched ROMs differ from the pin: " + "; ".join(bad))


class Run:
    """One BENCH log: the START line's fields, the per-frame rows, and whether BENCH END arrived."""

    def __init__(self, start):
        self.start = dict(kv.split("=", 1) for kv in start.split()[2:] if "=" in kv)
        self.columns, self.rows, self.ended = [], [], False

    @property
    def scene(self):
        return self.start.get("name")

    @property
    def complete(self):
        return self.ended and len(self.rows) == int(self.start.get("frames", -1))

    def config(self):
        return tuple(self.start.get(k) for k in ("name", "seed", "warmup", "frames"))

    def values(self, column):
        return [r[column] for r in self.rows]


def parse(text):
    """Every BENCH run in an IS-Viewer text, in order."""
    runs = []
    for line in text.splitlines():
        if line.startswith("BENCH START"):
            runs.append(Run(line))
        elif not runs:
            continue
        elif line.startswith("BENCH COLUMNS"):
            runs[-1].columns = line.split()[2:]
        elif line.startswith("BENCH F "):
            runs[-1].rows.append(dict(zip(runs[-1].columns, map(int, line.split()[2:]))))
        elif line.startswith("BENCH END"):
            runs[-1].ended = True
    return runs


def read_shas(paths):
    """file name -> sha256 from every rom-sha256.txt (sha256sum format) among paths."""
    out = {}
    for p in paths:
        if Path(p).name == "rom-sha256.txt":
            for line in Path(p).read_text().splitlines():
                sha, _, name = line.strip().partition("  ")
                out[Path(name).name] = sha
    return out


def rom_mismatch(paths, model_dir):
    """Why the console's BENCH runs are not runs of the pinned ROMs the fork ran, or None. A BENCH log
    names no ROM identity, so the capture carries the rom-sha256.txt of the files that were flashed."""
    shas = read_shas(paths)
    model_shas = read_shas([Path(model_dir) / "rom-sha256.txt"]) if (Path(model_dir) / "rom-sha256.txt").exists() else {}
    if not shas:
        return "the capture has no rom-sha256.txt for the BENCH ROMs it ran (hardware-run.md, Majora's Mask bench)"
    for run in console_runs(paths):
        name = rom_name(run.scene)
        pin = SCENES.get(run.scene, (None, None))[1]
        if not (shas.get(name) == pin == model_shas.get(name)):
            return (f"mm-bench {run.scene}: the console ran {name} sha256={shas.get(name, 'none')}, the fork ran "
                    f"{model_shas.get(name, 'none')}, the pin ({REPO} {COMMIT[:9]}) is {pin or 'none'}; build with "
                    f"calibration/build-mm-bench.sh and run calibration/run.sh")
    return None


def console_runs(paths):
    from kit import normalize
    return [run for p in paths if Path(p).name != "rom-sha256.txt"
            for run in parse(normalize(Path(p).read_bytes()).decode("ascii", errors="replace"))]


def model_run(model_dir, scene):
    path = Path(model_dir) / "ext" / "mm-bench" / f"{scene}.txt"
    runs = parse(path.read_text(errors="replace")) if path.exists() else []
    return runs[-1] if runs else None


def num(x):
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def span(xs):
    lo, hi = min(xs), max(xs)
    return num(lo) if lo == hi else f"{num(lo)}..{num(hi)}"


def deciles(values):
    """p10 and p90 of one run's per-frame values."""
    q = statistics.quantiles(values, n=10, method="inclusive")
    return q[0], q[8]


def compare(paths, model_dir, scenes):
    """(result, detail). Per scene of `scenes` the capture holds: each complete console run's median `vi`
    and `rdp_ticks` must lie within the fork's per-frame min..max of the same column over its run of the
    same ROM. The fork's run is one deterministic boot phase, so its 600-frame range is the spread it
    has. Reported, not judged: the mean fields per game frame, the median, p10 and p90 of each REPORTED
    column on both sides, and with both GAP scenes their named-minus-empty median gap on both sides.
    A console value given as lo..hi spans its runs."""
    mismatch = rom_mismatch(paths, model_dir)
    if mismatch:
        return "fail", mismatch
    runs = [r for r in console_runs(paths) if r.scene in scenes]
    if not runs:
        return "pending:calibration-16", (f"{len(paths)} files of mm-bench stored, no BENCH run of "
                                          f"{' '.join(scenes)}")
    cut = [r for r in runs if not r.complete]
    if cut:
        return "fail", f"{len(cut)} of {len(runs)} console runs end early (no BENCH END or fewer frames); first {cut[0].scene}"
    off, notes, models = [], [], {}
    for scene in sorted({r.scene for r in runs}):
        model = models[scene] = model_run(model_dir, scene)
        if model is None or not model.complete:
            return "missing", f"no complete fork run of mm-bench {scene} in {model_dir}/ext/mm-bench; run calibration/run.sh"
        mine = [r for r in runs if r.scene == scene]
        if any(r.config() != model.config() for r in mine):
            return "fail", f"mm-bench {scene}: console config {mine[0].config()}, fork {model.config()}"
        for col in COMPARED:
            mv = model.values(col)
            lo, hi = min(mv), max(mv)
            meds = [statistics.median(r.values(col)) for r in mine]
            if not all(lo <= m <= hi for m in meds):
                off.append(f"{scene} {col} console median {num(min(meds))}..{num(max(meds))} outside fork {lo}..{hi}")
        fpf = [sum(r.values("vi")) / len(r.rows) for r in mine]
        cols = [col for col in REPORTED if col in model.columns]
        notes.append(f"{scene} fields/frame console {min(fpf):.3f}..{max(fpf):.3f} fork "
                     f"{sum(model.values('vi')) / len(model.rows):.3f}, " + ", ".join(
                         f"{col} median console {span([statistics.median(r.values(col)) for r in mine])} fork "
                         f"{num(statistics.median(model.values(col)))}, "
                         f"p10 console {span([deciles(r.values(col))[0] for r in mine])} fork {num(deciles(model.values(col))[0])}, "
                         f"p90 console {span([deciles(r.values(col))[1] for r in mine])} fork {num(deciles(model.values(col))[1])}"
                         for col in cols))
    if set(GAP) <= set(models):
        empty, named = ([r for r in runs if r.scene == scene] for scene in GAP)
        for col in [col for col in REPORTED if all(col in models[scene].columns for scene in GAP)]:
            console = [statistics.median(n.values(col)) - statistics.median(e.values(col)) for e in empty for n in named]
            fork = statistics.median(models[GAP[1]].values(col)) - statistics.median(models[GAP[0]].values(col))
            notes.append(f"named-minus-empty median {col} console {span(console)} fork {num(fork)}, "
                         f"console minus fork {span([c - fork for c in console])}")
    detail = f"{len(runs)} console runs of {len({r.scene for r in runs})} scenes; " + "; ".join(notes)
    if off:
        return "fail", f"{len(off)} medians outside the fork's range; first {off[0]}; {detail}"
    return "pass", f"median vi and rdp_ticks within the fork's per-frame range; {detail}"


def sample(scene="south_clock_town", vi=(3, 3, 4, 3), rdp=(1500000, 1600000, 1700000, 1650000), end=True, pipe=None):
    """A BENCH log as the ROM prints it, with the given per-frame vi and rdp_ticks, and dpc_pipebusy if given."""
    lines = [f"BENCH START scene={SCENES[scene][0]} name={scene} seed=0x{SEED:08X} warmup={WARMUP} frames={len(vi)} "
             f"emux=1 retrace_ticks=783000 counter_hz=46875000",
             "BENCH COLUMNS frame vi rdp_ticks" + (" dpc_pipebusy" if pipe else "")]
    lines += [f"BENCH F {i} {v} {r}" + (f" {pipe[i]}" if pipe else "") for i, (v, r) in enumerate(zip(vi, rdp))]
    return "\n".join(lines + (["BENCH END"] if end else [])) + "\n"


def self_test():
    """(cases, failed): the reader's verdicts and ingest's refusal of a capture of other ROMs."""
    import tempfile
    pinned = "".join(f"{SCENES[s][1]}  {rom_name(s)}\n" for s in ("south_clock_town", "file_select_empty", "file_select_named"))
    other = f"{'b' * 64}  {rom_name('south_clock_town')}\n"
    sct, filesel = ("south_clock_town",), ("file_select_empty", "file_select_named")
    cases = [("a capture that agrees", sample(), pinned, "pass", "within the fork's per-frame range"),
             ("a capture whose median rdp_ticks is above the fork's range", sample(rdp=(1800000,) * 4), pinned, "fail",
              "rdp_ticks console median 1800000"),
             ("a capture whose median vi is above the fork's range", sample(vi=(5, 5, 5, 3)), pinned, "fail",
              "vi console median 5"),
             ("a cut capture (no BENCH END)", sample(end=False), pinned, "fail", "end early"),
             ("a capture of another ROM (rom-sha256.txt differs)", sample(), other, "fail", f"sha256={'b' * 64}"),
             ("a capture without rom-sha256.txt", sample(), None, "fail", "no rom-sha256.txt"),
             ("a capture without the question's scenes", sample(), pinned, "pending:calibration-16",
              "no BENCH run of file_select_empty file_select_named", filesel),
             ("a capture with another scene's run, which the question does not read",
              sample() + sample("file_select_named", vi=(5, 5, 5, 5)), pinned, "pass", "1 console runs of 1 scenes")]
    #The fork's file-select runs: medians 1125000 and 1625000 rdp_ticks (gap 500000), 900000 and 1050000
    #dpc_pipebusy (gap 150000); inclusive deciles of 4 frames interpolate at 0.3 and 2.7 sorted places.
    def empty(shift=0):
        return sample("file_select_empty", vi=(1, 2, 1, 1), rdp=tuple(v + shift for v in (1000000, 1100000, 1200000, 1150000)),
                      pipe=(800000, 900000, 1000000, 900000))

    def named(shift=0):
        return sample("file_select_named", vi=(2, 2, 1, 2), rdp=tuple(v + shift for v in (1500000, 1600000, 1700000, 1650000)),
                      pipe=(1000000, 1100000, 1000000, 1100000))
    fork = {"south_clock_town": sample(), "file_select_empty": empty(), "file_select_named": named()}
    cases += [("a file-select capture equal to the fork: gap 0 on both columns, each scene's p10 and p90",
               empty() + named(), pinned, "pass",
               ("named-minus-empty median rdp_ticks console 500000 fork 500000, console minus fork 0",
                "named-minus-empty median dpc_pipebusy console 150000 fork 150000, console minus fork 0",
                "file_select_empty fields/frame console 1.250..1.250 fork 1.250, rdp_ticks median console 1125000 "
                "fork 1125000, p10 console 1030000 fork 1030000, p90 console 1185000 fork 1185000, dpc_pipebusy median "
                "console 900000 fork 900000, p10 console 830000 fork 830000, p90 console 970000 fork 970000",
                "file_select_named fields/frame console 1.750..1.750 fork 1.750, rdp_ticks median console 1625000 "
                "fork 1625000, p10 console 1530000 fork 1530000, p90 console 1685000 fork 1685000"), filesel),
              ("a capture whose named rdp_ticks run 50000 above the fork's: the gap shows it, the verdict does not",
               empty() + named(50000), pinned, "pass",
               ("named-minus-empty median rdp_ticks console 550000 fork 500000, console minus fork 50000",
                "named-minus-empty median dpc_pipebusy console 150000 fork 150000, console minus fork 0",
                "rdp_ticks median console 1675000 fork 1625000, p10 console 1580000 fork 1530000"), filesel),
              ("two console runs of each screen: every pairing's gap and each run's deciles as a range",
               empty() + empty(20000) + named() + named(50000), pinned, "pass",
               ("4 console runs of 2 scenes", "named-minus-empty median rdp_ticks console 480000..550000 fork 500000, "
                "console minus fork -20000..50000", "p10 console 1530000..1580000 fork 1530000"), filesel),
              ("a capture of the named screen alone has no gap", named(), pinned, "pass",
               ("1 console runs of 1 scenes", "!named-minus-empty"), filesel)]
    failed = 0
    for name, text, shas, want, why, *scenes in cases:
        with tempfile.TemporaryDirectory() as tmp:
            model, capture = Path(tmp) / "model", Path(tmp) / "ext-mm-bench"
            (model / "ext" / "mm-bench").mkdir(parents=True)
            for scene, log in fork.items():
                (model / "ext" / "mm-bench" / f"{scene}.txt").write_text(log)
            (model / "rom-sha256.txt").write_text(pinned)
            capture.mkdir()
            (capture / "sct.isviewer.log").write_text(text.replace("\n", "\r\n"))
            if shas:
                (capture / "rom-sha256.txt").write_text(shas)
            got, detail = compare(sorted(capture.iterdir()), model, scenes[0] if scenes else sct)
        whys = (why,) if isinstance(why, str) else why
        ok = got == want and all((w[1:] not in detail) if w.startswith("!") else (w in detail) for w in whys)
        failed += not ok
        print(f"mm_bench: self-test: {name}: {'ok' if ok else 'FAILED'} ({got}: {detail})")
    run_store = ("import importlib.util, sys\n"
                 "spec = importlib.util.spec_from_file_location('ingest', sys.argv[1])\n"
                 "ingest = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(ingest)\n"
                 "ingest.store(*sys.argv[2:])\n")
    here = Path(__file__).resolve().parent
    for name, shas, want in [("ingest stores a BENCH capture of the pinned ROMs", pinned, 0),
                             ("ingest refuses a BENCH capture of other ROMs and stores nothing", other, 1)]:
        with tempfile.TemporaryDirectory() as tmp:
            root, model, capture = Path(tmp) / "root", Path(tmp) / "model", Path(tmp) / "capture"
            (root / "tools").mkdir(parents=True)
            (root / "tools" / "n64-timing").symlink_to(here.parent, target_is_directory=True)
            (capture / "ext-mm-bench").mkdir(parents=True)
            (capture / "ext-mm-bench" / "sct.isviewer.log").write_text(sample())
            (capture / "ext-mm-bench" / "rom-sha256.txt").write_text(shas)
            (model / "ext" / "mm-bench").mkdir(parents=True)
            (model / "ext" / "mm-bench" / "south_clock_town.txt").write_text(sample())
            (model / "rom-sha256.txt").write_text(pinned)
            proc = subprocess.run([sys.executable, "-c", run_store, str(here / "ingest.py"), str(root), str(capture),
                                   "c", str(model)], capture_output=True, text=True)
            stored = sorted(p.name for p in (root / "docs").rglob("*") if p.is_file()) if (root / "docs").exists() else []
        ok = proc.returncode == want and (bool(stored) == (want == 0))
        failed += not ok
        print(f"mm_bench: self-test: {name}: {'ok' if ok else 'FAILED'} (exit {proc.returncode}, stored {stored or 'nothing'})")
        cases.append(name)
    return len(cases), failed


if __name__ == "__main__":
    if sys.argv[1:2] == ["--commit"]:
        print(COMMIT)
    elif sys.argv[1:2] == ["--patch"] and len(sys.argv) == 4:
        write_roms(sys.argv[2], sys.argv[3])
    elif sys.argv[1:2] == ["--evidence"] and len(sys.argv) == 3:
        write_evidence(sys.argv[2])
    else:
        sys.exit("usage: mm_bench.py --commit | --patch BASE_ROM OUT_DIR | --evidence MM_DECOMP_CHECKOUT")
