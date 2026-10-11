#!/usr/bin/env python3
"""Runs the harness shell scripts against a stub runner in scratch homes and checks that a failure
reaches their exit status: snapper run.sh without the snapper64 dumps, calibration/run.sh without the
Majora's Mask BENCH ROMs, and standing.sh when a script it runs fails. Takes about a minute.

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

    failed = 0
    for name, ok, status, detail in results:
        failed += not ok
        print(f"scripts: self-test: {name}: {'ok' if ok else 'FAILED'} (exit {status}; {detail.strip()[-200:]})")
    print(f"scripts: self-test: {len(results)} cases, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
