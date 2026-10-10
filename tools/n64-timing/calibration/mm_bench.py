#!/usr/bin/env python3
"""The Majora's Mask BENCH ROM (kit.py EXT_ROMS `mm-bench`): its pinned build, its per-scene ROMs, its
IS-Viewer log, and the console-vs-fork comparison.

The BENCH build of wScottSh/mm-decomp-60fps (tools/bench/README.md there) boots into one Play scene,
warms up, records per-frame values in RAM, and prints them over IS-Viewer at the end:
  BENCH START scene=<i> name=<scene> seed=0x<hex> warmup=<n> frames=<n> emux=<0|1> ...
  BENCH COLUMNS frame vi pre_ticks ... rdram_dp
  BENCH F <frame> <value> ...        one per measured frame
  BENCH END
`vi` is the VI retraces between game-frame ends (fields per game frame); `rdp_ticks` is gRDPTimeTotal,
the OSTime ticks from the gfx task's start to the DP full sync. The build prints no DPC_CLOCK.
The scene comes from a BenchConfig block (magic BNCH) patched into a copy of the ROM, so each scene
is its own ROM file with its own sha256. build-mm-bench.sh builds the pinned commit and patches them.
"""
import hashlib
import statistics
import struct
import sys
from pathlib import Path

REPO = "wScottSh/mm-decomp-60fps"
#Merge of mm-decomp-60fps#1 (bench/fork 7ab7fdd1, same tree): tools/bench on the fork, no func_80173B48 pin.
COMMIT = "707602c67646c6e553a3c50f4ccb74641e8b5dfe"
BASE_SHA256 = "b58e49e939a70c332745f5619747ff1bc1f0ca44bf6f12917cad1ca013022e52"
#bench.py's defaults at COMMIT: 120 warmup frames, 600 measured (BENCH_MAX_FRAMES), seed 0x12345678.
WARMUP, FRAMES, SEED = 120, 600, 0x12345678
#sBenchScenes in src/code/bench.c at COMMIT: name -> (index, sha256 of the patched ROM). Scene 0 with the
#defaults is the base ROM unchanged, so its sha256 is BASE_SHA256.
SCENES = {
    "south_clock_town": (0, "b58e49e939a70c332745f5619747ff1bc1f0ca44bf6f12917cad1ca013022e52"),
    "termina_field": (1, "7d3bb5245f54b0b8c5d5202f6178c37b81cf9a672cb097499727727ffb5d8f6e"),
    "mountain_village_winter": (2, "6a9cf42962cf4487976c80b8d489af0434634cac823bd3913c7a777a1110fa27"),
    "great_bay_coast": (3, "5cc5949fbcd459f27af12546692fa24502b78964753a91d616ca651e81df055c"),
}
CONFIG_MAGIC = b"BNCH"
#The CIC boot code checksums ROM 0x1000..0x101000, so a patch there would not boot on a console.
CHECKSUMMED_END = 0x101000
COMPARED = ("vi", "rdp_ticks")


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
        name = rom_name(run.scene) if run.scene in SCENES else f"mm-bench-{run.scene}.z64"
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


def compare(paths, model_dir):
    """(result, detail). Per scene the capture holds: each complete console run's median `vi` and
    `rdp_ticks` must lie within the fork's per-frame min..max of the same column over its run of the
    same ROM. The fork's run is one deterministic boot phase, so its 600-frame range is the spread it
    has; the medians and the mean fields per game frame of both sides are reported."""
    mismatch = rom_mismatch(paths, model_dir)
    if mismatch:
        return "fail", mismatch
    runs = console_runs(paths)
    if not runs:
        return "pending:calibration-16", f"{len(paths)} files of mm-bench stored, none with a BENCH START line"
    cut = [r for r in runs if not r.complete]
    if cut:
        return "fail", f"{len(cut)} of {len(runs)} console runs end early (no BENCH END or fewer frames); first {cut[0].scene}"
    off, notes = [], []
    for scene in sorted({r.scene for r in runs}):
        model = model_run(model_dir, scene)
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
                off.append(f"{scene} {col} console median {min(meds)}..{max(meds)} outside fork {lo}..{hi}")
        fpf = [sum(r.values("vi")) / len(r.rows) for r in mine]
        notes.append(f"{scene} fields/frame console {min(fpf):.3f}..{max(fpf):.3f} fork "
                     f"{sum(model.values('vi')) / len(model.rows):.3f}, rdp_ticks median console "
                     f"{min(statistics.median(r.values('rdp_ticks')) for r in mine)} fork {statistics.median(model.values('rdp_ticks'))}")
    detail = f"{len(runs)} console runs of {len({r.scene for r in runs})} scenes; " + "; ".join(notes)
    if off:
        return "fail", f"{len(off)} medians outside the fork's range; first {off[0]}; {detail}"
    return "pass", f"median vi and rdp_ticks within the fork's per-frame range; {detail}"


def sample(scene="south_clock_town", vi=(3, 3, 4, 3), rdp=(1500000, 1600000, 1700000, 1650000), end=True):
    """A BENCH log as the ROM prints it, with the given per-frame vi and rdp_ticks."""
    lines = [f"BENCH START scene={SCENES[scene][0]} name={scene} seed=0x{SEED:08X} warmup={WARMUP} frames={len(vi)} "
             f"emux=1 retrace_ticks=783000 counter_hz=46875000", "BENCH COLUMNS frame vi rdp_ticks"]
    lines += [f"BENCH F {i} {v} {r}" for i, (v, r) in enumerate(zip(vi, rdp))]
    return "\n".join(lines + (["BENCH END"] if end else [])) + "\n"


def self_test():
    """(cases, failed): the reader's verdicts and ingest's refusal of a capture of other ROMs."""
    import subprocess
    import tempfile
    pinned = f"{SCENES['south_clock_town'][1]}  {rom_name('south_clock_town')}\n"
    other = f"{'b' * 64}  {rom_name('south_clock_town')}\n"
    cases = [("a capture that agrees", sample(), pinned, "pass", "within the fork's per-frame range"),
             ("a capture whose median rdp_ticks is above the fork's range", sample(rdp=(1800000,) * 4), pinned, "fail",
              "rdp_ticks console median 1800000"),
             ("a capture whose median vi is above the fork's range", sample(vi=(5, 5, 5, 3)), pinned, "fail",
              "vi console median 5"),
             ("a cut capture (no BENCH END)", sample(end=False), pinned, "fail", "end early"),
             ("a capture of another ROM (rom-sha256.txt differs)", sample(), other, "fail", f"sha256={'b' * 64}"),
             ("a capture without rom-sha256.txt", sample(), None, "fail", "no rom-sha256.txt")]
    failed = 0
    for name, text, shas, want, why in cases:
        with tempfile.TemporaryDirectory() as tmp:
            model, capture = Path(tmp) / "model", Path(tmp) / "ext-mm-bench"
            (model / "ext" / "mm-bench").mkdir(parents=True)
            (model / "ext" / "mm-bench" / "south_clock_town.txt").write_text(sample())
            (model / "rom-sha256.txt").write_text(pinned)
            capture.mkdir()
            (capture / "sct.isviewer.log").write_text(text.replace("\n", "\r\n"))
            if shas:
                (capture / "rom-sha256.txt").write_text(shas)
            got, detail = compare(sorted(capture.iterdir()), model)
        ok = got == want and why in detail
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
    else:
        sys.exit("usage: mm_bench.py --commit | --patch BASE_ROM OUT_DIR")
