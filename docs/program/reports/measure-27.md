# Report: measure-27 (#27 run-to-run determinism)

**Status: DONE.** The research doc is pushed. There is no PR, per the brief. The worktree core is reverted, and the instrumentation exists only as a patch file in the docs.

- Branch: `research/determinism` (worktree `C:\Users\Scott\repos\ares-wt\measure-27`, based on origin/feat/harness c8592d16a)
- Head SHA: `30ead9e4349aa818f19ddf2f7f1410c093162d72`
- Doc: https://github.com/wScottSh/ares/blob/research/determinism/docs/research/determinism.md
- Artifacts: `docs/research/determinism/{measure.patch,run.sh,cmp.py,window.py,batch1-3.sh}`. The pushed patch applies cleanly to feat/harness (verified with `git apply --check`).
- Raw results: `C:\Users\Scott\n64-timing\results\measure-27\*.tsv|*.err`. Build dir: `C:\Users\Scott\n64-timing\build\measure-27`.

## Map gist (one line)

Entropy-off is the only host input that changed MM state over 3,600 fields: it causes a boot-time shift, which changes the `osGetTime` seed of MM's game RNG. That is the likely source of the 1% South Clock Town noise (inferred). paraLLEl's RDRAM writes race host time (measured), but MM never reads a target before SyncFull.

## Key measured numbers (MM, 3,600 fields, interpreter unless noted)

- Baseline A1, A2, A3 (A3 next to 12 busy loops): all columns identical, including the full-RDRAM hash and the CPU GPR hash.
- Entropy off, B1 vs B2: differ from field 0. The first VI field lands 157,759 PClock apart. `degrade()` ran 840 vs 880 times (800 with entropy on). Max per-120-field RSP busy difference 0.084%, final −0.0089%.
- Vulkan, harness mode (C2, C3 loaded): fully identical. Desktop-like vulkan with the screen thread on (G2 vs G3): CPU and timing identical, but `rdram_hash` differs on 506 of 3,600 fields. 1,088 target reads, 0 of them before SyncFull.
- Recompiler D1, D2, D3: identical to each other. Against the interpreter, RSP busy is +1.33% (the #10/#28 gap).
- Heap fill 0xA5 vs 0x5A, two random flash saves, screen and audio paths on with `--rdp none`: all identical. RTC, CP0 Random, SP_PC random and pak format each had 0 calls.

## Decisions

- Workload: 3,600 fields instead of 600. This reaches MM's 3D attract sequence (RSP load rises after field 1,800). With no input scripting, gameplay scenes were out of reach.
- Measurement patch: it adds runner options and probe counters, and the doc includes it as a rerunnable artifact. The core was reverted before the commit.
- Harness caveat: in `--rdp vulkan` mode the runner hashes the scanout, and that wait serializes the GPU once per field. This hides the paraLLEl race the desktop has. Later units should not read harness vulkan determinism as GPU independence.

## Open questions

- Confirming the South Clock Town cause needs gameplay: the MM bench unit should rerun B/B2 with entropy on (expect an exact match), or run `--entropy off` twice on the bench ROM.
- Removing the PRNG, not just pinning it, needs hardware references for the RDRAM calibration thresholds and decay, CP0 Random stepping (VR4300 manual, Random register; I did not check the page), and SP_PC reads while the RSP runs.
- No RTC ROM was available (Doubutsu no Mori), so the RTC host-time path is analyzed from code only.
- The bench harness `mm-decomp-60fps/tools/bench` is not on this machine. The claims about the original bench config come from recompiler-parity.md and the desktop defaults.

## Denials / deviations

- No permission denials.
- The desktop `ares` settings file used by the original bench was not found. The only one on this machine is the stock v148 install (no DeterministicEntropy key).
