# verify-60: PR #60 (L0 Linux harness port), head 4ee9e1bf4

Verdict: PASS-WITH-NOTES. Notes: Windows path checked by reading only; pidma replay not rerun; MM wall time measured only under heavy foreign load.

## Ran (own build, g++ on Linux, build/verify-60-head, worktree ares-wt/verify-60)
- build.sh: n64-run, n64-timing-tests, n64-timing-dpc-regs built; runner at rundir/bin/n64-run.
- Data: reused ~/n64-timing/{roms,corpora}; results into scratch/v60home (not the worker's dirs).
- nemu64 failed: timing 453/1604, cycle 9/13, cop0hazard 5/5. Same as Windows baseline.
- snapper: 432+32+2048+80 = 2592/2592 match.
- rdpstat failed: 0/7, 0/2, 0/21.
- thar0: cfg 84 and 92 = 77772, cfg 85 and 93 = 155052 (min=avg=max).
- determinism (MM 600, 27 files, 8158 fields) PASS; step-cap PASS; nemu64 det and step-cap PASS for all 3 ROMs.
- state round trip PASS (600 fields); TMEM poke PASS.
- ctest 5/5. behaviors --check ok, lint-literals ok.
- bench: fail 10, pass 11, report 19; rspdma 6.473 fail as in worker's report.
- MM 600 field direct run x3: 30.04, 30.23, 29.89 s wall; stats TSVs byte-identical to each other AND to the worker's gcc and clang stats (different build dirs/compilers). Budget 120 s. Load average was 64-67 (foreign jobs, 32 cores) during the runs, so Linux wall here is slower than the worker's 18.7-22 s at load 6; Windows 11.3-11.8 s was the worker's figure, not rechecked.
- Determinism runs at load 68 took 3m02 and 4m30 (27 parallel scenes), not a bench.

## Worker claims checked
- (c) Self-test: at origin/master, behaviors.py --self-test has exactly 3 FAILED (changing a legacy literal, changing a legacy row's value, a legacy code site moving). At 1326f3f40^ (826e1fb1b) all ok. At head 0 FAILED. Master's table has no legacy.cpu.mult/div rows now, legacy.pi.cart-read (bus.hpp:63, 250 pclk) exists, and the retarget edits `thread.step(pclk(250))` in pi/bus.hpp, row value 251, and a leading blank line. Sound. Claim confirmed.
- (d) rdram-private: with `private:` flipped to `public:` at ares/n64/rdram/rdram.hpp:285, unit:rdram-private FAILED (restored afterwards, worktree clean). With the file as is it passes under gcc, so the new regex matches gcc's text.
- (b) Diff: 16 files, all under tools/n64-timing. No core source (ares/, nall/, desktop-ui) edit; no emulator behavior change. Also mode 644->755 on scripts, which is fine on Linux.
- Windows by reading: host.sh uses cygpath to pick `<build>/n64-run/rundir/n64-run.exe`, same as the old default; build.sh clang64 branch keeps msys PATH, clang/clang++, same cmake flags and targets; `python` is preferred over python3. Dropped: the old `[ -x runner ] || runner=${runner%.exe}` fallback (not needed, n64_target is exact per host). determinism.sh tr set reordered ('._\n-') which is correct for both tr flavors. Not run on Windows.

## Findings
- None blocking. Minor: fetch.sh LFS fallback uses `command -v python || python3` inline instead of host.sh (fetch.sh doesn't source it); harmless.
- Not reproduced: pidma replay (worker also skipped), Windows run, clang build, snapper fetch (reused existing 7094 dumps, no refetch), the worker's Linux 18.7-22 s MM wall (load differed).
