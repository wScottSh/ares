"""The boot delays the bench walks (README.md, Phase).

usage: python -m romgen.suites.bench.phases   prints the delays, one per line
env: N64_BENCH_DELAYS=K,K,...   replaces the delays (for a scan), in build.py, run.sh and report.py alike

Each delay is the iteration count of the runtime's BOOT_DELAY_LOOP, so a delay moves every
measurement's start against the free-running VI, refresh and poll grids without moving code.
"""
import os

#One loop iteration is 3 pclk, and every boot-phase effect repeats with the idle VI's
#0x800-VCLK line event, 3944 pclk = 1313 iterations (measured: the mi-memset-rspdma dips at K =
#1-4, 1298-1311, 2611-2624, 3924-3937 over 872 delays; README.md, Phase). 32 delays 41 apart
#cover that period at 123 pclk spacing, which also lands them at 32 different phases of a
#26 pclk poll loop (123 mod 26 = 19).
DELAYS = [1 + 41 * i for i in range(32)]
if os.environ.get("N64_BENCH_DELAYS"):
    DELAYS = [int(k) for k in os.environ["N64_BENCH_DELAYS"].split(",")]

if __name__ == "__main__":
    print("\n".join(str(k) for k in DELAYS))
