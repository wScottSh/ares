"""The VI phases the nemu64 averaged tests walk (romgen README, Phase walk).

usage: python -m romgen.suites.nemu64.phases   prints the delays, one per line

Each delay is the iteration count of measure.py's PHASE_DELAY_LOOP, which runs after the step's
VI setup. The VI-on tests wait for VSYNC first, so only their start within the VI line is free;
the VI-off tests start anywhere against the idle VI.
"""

#One loop iteration is 3 pclk (bench/phases.py). The active NTSC line is 3094 VCLK (VI_H_SYNC
#0xC15, runtime vi_init) = 5958 pclk at 48.68 MHz VCLK; the idle VI's line event is 0x800 VCLK
#= 3944 pclk (bench/phases.py). 64 delays 62 apart span 3968 iterations = 11904 pclk: two active
#lines (11916) and three idle events (11832) to within 0.6 %, at 186 pclk spacing.
DELAYS = [1 + 62 * i for i in range(64)]

if __name__ == "__main__":
    print("\n".join(str(k) for k in DELAYS))
