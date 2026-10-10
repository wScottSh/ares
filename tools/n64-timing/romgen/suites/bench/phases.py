"""The phase points the bench walks: each layout pad at each boot delay (README.md, Phase).

usage: python -m romgen.suites.bench.phases   prints each point's directory (pad-<P>/boot-<K>), one per line
env: N64_BENCH_DELAYS=K,K,...   replaces the delays (for a scan), in build.py, run.sh and report.py alike
     N64_BENCH_PADS=P,P,...     replaces the pads the same way

Each delay is the iteration count of the runtime's BOOT_DELAY_LOOP, so a delay moves every
measurement's start against the free-running VI, refresh and poll grids without moving code.
Each pad is the word count of the runtime's layout pad (runtime.layout_pad), so a pad moves
every instruction after boot against the 32 B I-cache lines.
"""
import os

#One loop iteration is 3 pclk, and every boot-phase effect repeats with the idle VI's
#0x800-VCLK line event, 3944 pclk = 1314.7 iterations (measured: mi-memset-rspdma dips start at
#K = 1292, 2606, 3921, 5236, 6550, 7865, 1314 or 1315 apart; verify-78, README.md, Phase). 32 delays 41 apart
#cover that period at 123 pclk spacing, which also lands them at 32 different phases of a
#26 pclk poll loop (123 mod 26 = 19).
DELAYS = [1 + 41 * i for i in range(32)]
if os.environ.get("N64_BENCH_DELAYS"):
    DELAYS = [int(k) for k in os.environ["N64_BENCH_DELAYS"].split(",")]

#A VR4300 I-cache line is 32 B, 8 words; a pad of 8 words gives pad 0's values exactly (verify-79).
PADS = list(range(8))
if os.environ.get("N64_BENCH_PADS"):
    PADS = [int(p) for p in os.environ["N64_BENCH_PADS"].split(",")]

POINTS = [(p, k) for p in PADS for k in DELAYS]


def point_dir(pad, delay):
    return f"pad-{pad}/boot-{delay}"


if __name__ == "__main__":
    print("\n".join(point_dir(p, k) for p, k in POINTS))
