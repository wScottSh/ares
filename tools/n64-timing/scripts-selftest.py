#!/usr/bin/env python3
"""Runs the harness shell scripts against a stub runner in scratch homes and checks that a failure
reaches their exit status: snapper run.sh without the snapper64 dumps, calibration/run.sh without the
Majora's Mask BENCH ROMs, standing.sh when a script it runs fails, and state-roundtrip.sh when no save
of a repeat-write ROM holds a posted repeat write. Takes about 15 s.

usage: scripts-selftest.py
"""
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd, env, timeout=120):
    """(exit status, stderr); a run past the timeout reads as status None, its process group killed."""
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, err
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return None, f"still running after {timeout} s"


def stub(path, status):
    path.write_text(f"#!/bin/sh\nexit {status}\n")
    path.chmod(0o755)
    return path


#Writes the rows, #bench line and save-state report state-roundtrip.sh reads; a state-suite ROM ends
#after field 9 (one row once it loads a state) and the TMEM poke changes trace_hash from field 31 on.
STATE_RUNNER = r"""#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
opt = lambda name: args[args.index(name) + 1] if name in args else None
script = open(opt("--script")).read().split() if opt("--script") else []
frames = int(opt("--frames"))
if "state-repeat" in args[0]:
    frames = 1 if "load-state" in script else min(frames, 10)
    print("#bench state-repeat vi-on sum=1")
if opt("--stats"):
    with open(opt("--stats"), "w") as f:
        f.write("frame\tcpu_cycles\ttrace_hash\tvi\n")
        for n in range(frames):
            f.write(f"{n}\t{n}\t{'p' if 'poke-tmem' in script and n > 30 else 'h'}{n}\t1\n")
for i, word in enumerate(script):
    if word == "save-state":
        open(script[i + 1], "wb").write(b"state")
        count = os.environ.get("STUB_POSTED")
        print(f"n64-run: save-state {script[i + 1]} frame=1" + (f" posted-repeats={count}" if count else ""), file=sys.stderr)
"""


def state_roundtrip(tmp, env, posted):
    """(exit status, stdout) of state-roundtrip.sh on the stub runner reporting `posted` at each save."""
    runner = tmp / "state-run"
    runner.write_text(STATE_RUNNER)
    runner.chmod(0o755)
    out = tmp / f"srt-{posted}"
    env = dict(env, N64_RUN=str(runner), OUT=str(out))
    if posted is not None:
        env["STUB_POSTED"] = str(posted)
    proc = subprocess.run([str(HERE / "state-roundtrip.sh"), str(tmp / "mm.z64"), "600"], env=env,
                          capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def main():
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        runner = stub(tmp / "n64-run", 0)
        home = tmp / "home"
        (home / "roms").mkdir(parents=True)
        for s in ("span-tri", "test-mode-rw"):
            (home / "roms" / f"snapper-{s}.z64").write_bytes(b"\0" * 16)
        env = {k: v for k, v in os.environ.items()
               if k not in ("MM_BENCH_ROMS", "PIDMA_DIR", "SNAPPER_ROMS", "SNAPPER_RESULTS", "SYSBENCH_ROMS")}
        env.update(N64_TIMING_HOME=str(home), N64_RUN=str(runner), N64_BUILD_DIR=str(tmp / "build"))
        snapper = str(HERE / "romgen/suites/snapper/run.sh")

        status, err = run([snapper, "span-tri"], env)
        results.append(("snapper run.sh without the snapper64 dumps exits nonzero and names the set",
                        status not in (0, None) and "the comparison failed for: span-tri" in err, status, err))
        status, err = run([snapper, "test-mode-rw"], env)
        results.append(("snapper run.sh on a set that needs no dumps exits 0", status == 0, status, err))

        mm = tmp / "mm-bench"
        mm.mkdir()
        calib = tmp / "calib"
        status, err = run([str(HERE / "calibration/run.sh"), str(calib)], dict(env, MM_BENCH_ROMS=str(mm)), timeout=60)
        results.append(("calibration/run.sh without the BENCH ROMs exits nonzero before it builds a kit ROM",
                        status not in (0, None) and "build-mm-bench.sh" in err and not (calib / "roms").exists(), status, err))

        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name in ("python", "python3", "docker"):
            stub(bin_dir / name, 1)
        (mm / "mm-bench-south_clock_town.z64").write_bytes(b"\0" * 16)
        out = tmp / "standing"
        status, err = run([str(HERE / "standing.sh"), str(out), str(tmp / "mm.z64")],
                          dict(env, MM_BENCH_ROMS=str(mm), PATH=f"{bin_dir}:{os.environ['PATH']}"), timeout=300)
        failing = (out / "failing.txt").read_text() if (out / "failing.txt").exists() else ""
        stamp = (out / "n64-run.txt").read_text() if (out / "n64-run.txt").exists() else ""
        results.append(("standing.sh exits nonzero when a script fails, and failing.txt names it",
                        status not in (0, None) and "romgen-nemu64" in failing.split("\n")[0], status,
                        failing.split("\n")[0] or err))
        want = subprocess.run(["sha256sum", str(runner)], capture_output=True, text=True).stdout.split()[0]
        results.append(("standing.sh records the sha256 of the runner it was given",
                        stamp.startswith(f"{want}  {runner}  given as N64_RUN"), status, stamp or "no n64-run.txt"))
        named = failing.split("\n")[0].split(":", 1)[-1].split()
        silent = ["ctest", "det-mm", "stepcap-mm", "det-nemu64-timing", "stepcap-nemu64-cop0hazard"]
        results.append(("standing.sh counts ctest and determinism.sh when they write no verdict",
                        all(n in named for n in silent), status, failing.split("\n")[0] or err))

        verdicts = tmp / "verdicts"
        verdicts.mkdir()
        (verdicts / "python").write_text('#!/bin/sh\ncase "$1" in -c) echo 0; exit 0;; -) echo "$4: FAIL"; exit 1;; esac\nexit 1\n')
        (verdicts / "python").chmod(0o755)
        (verdicts / "ctest").write_text("#!/bin/sh\necho '50% tests passed, 1 tests failed out of 2'\nexit 8\n")
        (verdicts / "ctest").chmod(0o755)
        (tmp / "build").mkdir()
        out = tmp / "standing-verdicts"
        status, err = run([str(HERE / "standing.sh"), str(out), str(tmp / "mm.z64")],
                          dict(env, MM_BENCH_ROMS=str(mm), PATH=f"{verdicts}:{bin_dir}:{os.environ['PATH']}"), timeout=300)
        first = (out / "failing.txt").read_text().split("\n")[0] if (out / "failing.txt").exists() else ""
        named = first.split(":", 1)[-1].split()
        results.append(("standing.sh does not count a failing ctest or determinism verdict as a script failure",
                        bool(first) and not any(n == "ctest" or n.startswith(("det-", "stepcap-")) for n in named),
                        status, first or err))

        status, text = state_roundtrip(tmp, env, 1)
        results.append(("state-roundtrip.sh passes when a save holds a posted repeat write",
                        status == 0 and text.count(": PASS") == 4, status, text))
        status, text = state_roundtrip(tmp, env, 0)
        results.append(("state-roundtrip.sh fails when no save holds a posted repeat write",
                        status not in (0, None) and "no save held a posted repeat write" in text
                        and "round trip: PASS" in text and "from the plain run" not in text, status, text))
        status, text = state_roundtrip(tmp, env, None)
        results.append(("state-roundtrip.sh fails when the runner reports no posted-repeats count",
                        status not in (0, None) and "reported no posted-repeats count" in text, status, text))

    failed = 0
    for name, ok, status, detail in results:
        failed += not ok
        print(f"scripts: self-test: {name}: {'ok' if ok else 'FAILED'} (exit {status}; {detail.strip()[-200:]})")
    print(f"scripts: self-test: {len(results)} cases, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
