"""The boot delays the bench walks (README.md, Phase).

usage: python -m romgen.suites.bench.phases   prints the delays, one per line
env: N64_BENCH_DELAYS=K,K,...   replaces the delays (for a scan), in build.py, run.sh and report.py alike

Each delay is the iteration count of the runtime's BOOT_DELAY_LOOP, so a delay moves every
measurement's start against the free-running VI, refresh and poll grids without moving code.
"""
import os

DELAYS = [1]
if os.environ.get("N64_BENCH_DELAYS"):
    DELAYS = [int(k) for k in os.environ["N64_BENCH_DELAYS"].split(",")]

if __name__ == "__main__":
    print("\n".join(str(k) for k in DELAYS))
