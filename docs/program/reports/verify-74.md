# verify-74: PR #74 (not-built)

PR comment: https://github.com/wScottSh/ares/pull/74#issuecomment-6067852599

Raw: ~/n64-timing/results/verify-74/{base,head}, worktrees ~/repos/ares-wt/verify-74{,-base}, builds ~/n64-timing/build/verify-74-{base,head}. Mutations in scratchpad copy; nothing posted to #1.


Recommendation: land after dropping the two committed `.pyc` files (note 1). Independent run: own worktrees, builds (RelWithDebInfo), private N64_TIMING_HOME, every suite ROM rebuilt from each tree. `standing.sh` ran on base then head back to back (load 4.1 and 1.4 at start).

### 1. No timing change (measured)
- MM 600 `--stats` md5 `56e118e27192798c0710bcddd61a0b59` on both.
- nemu64 timing, cycle, cop0hazard: `values.tsv` and `tests.tsv` `cmp` identical. All 7 mmbench `stats.tsv` identical. ROM sha256 lists identical (list sha d82b030db985).
- All 86 check (result, detail) pairs identical, via `behaviors.results()` on both trees against their own run.
- det x3 + MM PASS (29 files, 8219 fields); stepcap x3 + MM PASS; state round trip PASS; TMEM poke PASS; ctest 9/9 on both. pidma FAIL 23770..23808/24000 on both, summary identical.
- Wall time not retimed (no behavior change; md5 identical).
- The 5 constants the core now reads, read from the diff: `SiRead64Base.units / UnitsPerRclk` = 163200/12 = 13600 (was literal 13600). `halfPixels(image, bpp)` returns `RdpColorHalfPixels16bpp` = 32 for a 16 bpp color image, else `RdpSpanRamHalf / bpp`; the Z image still goes the old way, 32 either way. Span phase mask `RdpSpanRamSegment / 4 - 1` = 3 (was `& 3`). `clock.unit` and `ri.refresh-waits-for-burst` are `static_assert`s only (no run-time code). Value and behavior unchanged; md5 agrees.

### 2. Code column and --check (mutations run on a `git archive` copy)
- Fake row, no code use, no pointer: fails (`no code reads Timing::Behavior::PiFakeThing, and pi.fake-thing names no code`).
- Pointer symbol missing: fails (`ares/n64/pi/bus.hpp has no PI::nope`). Pointer file missing: fails (`does not exist`).
- not-built on a row the code reads (`ri.read-hit`): fails (`code reads ... so ri.read-hit is built there; clear its code column`).
- Removing the not-built mark from `pi.io-busy`: fails. A rule row (`ri.row-of`) losing its pointer: fails.
- Self-tests: `behaviors.py: self-test: 41 cases, 0 failed`; `pidma-replay: self-test: 5 cases, 0 failed`. `--check` ok.
- Limits (note 2): a comment `//Timing::Behavior::PiIoBusy` in a core file makes the row count as read (I added one, removed the not-built mark, and no read error fired). A pointer resolves if the symbol appears anywhere in the file. The two `static_assert` rows are build guards: `ri.refresh-waits-for-burst` asserts a flag nothing else implements or reads.

### 3. Not-built rows and deletions (confirmed from code)
- `pi.io-busy`: `ares/n64/pi/bus.hpp:77` `scheduleAfter(EventKind::PI_BUS_Write, pclk(200))` in `PI::writeWord`; no reader of `PiIoBusy`.
- `cpu.pif-ram-read`: bus.hpp routes 0x1fc0'0000-0x1fcf'ffff to `si.read`; `si` is the RCP register device, whose `read` steps `CpuRcpRegisterRead - CpuDcacheHit` (memory/io.hpp:6), 22 pclk. Inferred from code; no ROM.
- `cpu.uncached-read-dword-total`: `SysAD::read<Size>` uses `ReadPath` for every size through the RI (sysad.cpp:169-175); `ReadPath` is derived from the 32 pclk word total (sysad.hpp:56). Inferred from code; no ROM. (A Dual read outside RDRAM freezes the CPU, bus.hpp:6, so the dword row only concerns RDRAM.)
- Deleted `sp.dma-rate-check`: bench `expected.tsv` line 9 already asserts 6.5 B/rclk (n64brew, `check`); only a design sketch and a historical codemod still name it. Deleted `legacy.si.dma-read-base`: same 13600 as `si.read64-base`, its allowlist line removed and the literal now reads the constant.
- Scan of the constant-less rows: 24 rule/order/map rows plus legacy; I checked all 8 that had no citation against code: `cpu.random-rule` (getControlRandom, period 32-W or 96-W), `vi.register-sample` and `vi.fetch-overrun` (VI::startFetch re-reads io each line, returns while a fetch is in flight), `vi.unfetched-sample` (VI::compose zero past `fetched`), `vi.aa-mode-lines` (Fetch::start uses fixed `Lines`, nothing reads `io.antialias` in the fetch), `vi.display-window` (VI::window), `rdp.attribute-stage` (`rdp_haz_stage_offset` table), `rdp.write-run` (RDP::writeBack). All present and match the row text.

### 4. pidma
- `calibrate(meas, printed, gold)` no longer raises on empty `printed`. Self-test case 1 is `calibrate({}, {}, {})`.
- I reproduced the SUCCESS-run claim with my own synthetic run (every point's mean at the golden midpoint, nothing printed): 7168 fitting offsets, read shift -216..231 (448 units = 28 ticks), worst offset fails 830/24000 points, best offset fails 0/24000. So the rule "every calibrated offset within 3%" is reachable only if the offset is pinned; at a pinned correct offset a perfect model passes. The check source (`pidma:logs`) says this, and says the 16-unit tick is not the limit (1 tick = 0.63% of 158 ticks); both are true. The verdict rule is unchanged.

### 5. Regeneration
`behaviors.py --results` on my head run, `behaviors.py`, `--check` ok. `git diff` is exactly one line in each of `n64-timing-results.tsv`, `n64-timing.md`, `map-1-closure-draft.md` (the provenance line). Counts reproduce: 147 behaviors, 30 fail, 10 fit only, 3 model-choice, 3 not-built, 60 pass, 11 calibration-16, 16 no-corpus, 4 no-rom, 10 report-only. The closure draft's first paragraph names `cpu.uncached-read-dword-total`, `cpu.pif-ram-read`, `pi.io-busy`; a "Behaviors not built" table follows. Not posted: issue #1 has 0 comments. `mm-bench.md` regeneration not rerun by me.

### 6. Gate text
`rdp.tmem-load-rate` reference now says 0.418 clocks per byte; jgemu-dpc-probe.md line 26: "about 15 fixed plus 0.418 cycles per byte" (0.832 per RGBA16 texel). Correct. `calibration-16` wording now covers the vendor figure (cpu.dcb) and the guarded totals (legacy.si.dma-read-*). `mm:south-clock-town`, `thar0:fill-mode`, `bench:rdp-loadsz-sweep` sources now name a value or say none. `mm:file-select` (report) still names neither; no row references it.

### Notes
1. Two `.pyc` files are committed: `tools/n64-timing/__pycache__/behaviors.cpython-314.pyc` (112 KB) and `pidma-replay.cpython-314.pyc` (18 KB), added in 0977b444d. They are tracked, so any tool run rewrites them and dirties the tree (it happened in my worktree after standing.sh). `git rm` them and add `__pycache__/` to `.gitignore`.
2. The "read" test is textual (comments count; bare-name match in `using namespace` files). It catches the verify-72/73 gaps, not a deliberate evasion. The `ri.refresh-waits-for-burst` static_assert is vacuous as a behavior check.
3. `mm:file-select` source wording (above).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Not reproduced: wall time, mm-bench.md regeneration, MM performance. No background process of mine remains.
