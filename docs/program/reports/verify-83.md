# verify-83: PR #83 (systembench), PASS-WITH-NOTES

Head 6145930ba3b5233df457cd4fc3004332857444c3 vs base 253e1c8ea. Own worktrees `ares-wt/verify-83{,-base}`, builds `~/n64-timing/build/verify-83-{head,base}`, private homes `~/n64-timing/verify-83-home{,-base}`. Raw: `~/n64-timing/results/verify-83/{systembench,head,base,variants}`. Load 2-9. No process or container of mine is left running.

## Verdict
The harness and wiring reproduce exactly. No timing value changes (strings only), every standing check is unchanged. Two worker claims are overstated or wrong (below): "the hardware's poll phase" and the C*R explanation. Neither blocks landing; both need a wording fix or follow-up.

## 1. Build (reproduced)
`build-systembench.sh` into my own home, own clones of n64-systembench and libdragon: z64 sha256 c1c85c1357bcc01ad4dd306759cf5433269c3423c858d0ba9403171095cbf5f6 and elf 16366964925090b805f1f305892a7beee45a43f8dcc7c46f82571b14c758af43, both identical to the report. Image sha256:bbc66328...b21f, libdragon cc490afe0, sysbench 845635c (provenance.txt). A second build (my variants script, base variant) gave the same z64 sha. `git diff --name-status`: no z64/elf/main.c/license file added; libdragon Unlicense and the no-license-file reason are in the build-systembench.sh header comment (measured).

## 2. run.sh, 33 runs (reproduced)
Every row matches the report table (measured): C8R 4 (2..4), U32R rand 151, banked 133, PI DMA 8 190, 128 1582, 1 KiB 12185 (..12186), PI I/O W 130, SI DMA W ROM 2140 (2139..2140, 1/33), SI I/O W 2151, JOY all as claimed; summary 1 consistent-only, 6 fail, 24 pass, 3 report. Per row distinct values over the 33 runs: 31 of 34 rows identical in all 33; the 3 that move (c8r, pi-dma-1024, si-dma-w-rom) differ only between the unpadded ROM and the 32 shifted ROMs, and the 32 shifted ROMs agree with each other. The delay is effective: boot-1954 executes 3896 more instructions than boot-1 (9477659 vs 9473763), ROMs differ in 6 bytes. So boot delay changes nothing; layout moves 1-2 units.

## 3. Pointwise fails (reproduced)
PI I/O W 130 vs 134, SI I/O W 2151 vs 2158, PI DMA 128 1582 vs 1591, PI DMA 8 190 vs 193, SI DMA W ROM 2140 vs 2144, U32R banked 133 vs 136, all as reported. Aligned scratch build (rambuf aligned(2048), sed on main.c, same image and libdragon): U32R rand 133, PI DMA 1 KiB 12170, others unchanged (measured). The rambuf-crosses-a-row explanation holds.

## 4. Poll phase and the hardware comparison
Disassembly of `bench_piiow` (`mips64-elf-objdump` in the pinned image): `sw zero,0(s5)` then straight `mfc0; lw 16(v0)` x8 pairs, `andi`/branch tests after all 8. Cadence is one mfc0 plus one uncached PI_STATUS read per step, no other instruction between pairs, so the phase of the first poll after the write is fixed by this binary (measured).
That does not make it the hardware's phase. I built scratch variants of the same 845635c source (same image/libdragon) and ran them on the same runner:

| variant | PI I/O W (hw 134) | SI I/O W (2158) | SI DMA W ROM (2144) | PI DMA 128 (1591) | PI DMA 8 (193) |
|---|---|---|---|---|---|
| base | 130 | 2151 | 2140 | 1582 | 190 |
| 1 nop per poll step | 134 | 2159 | 2146 | 1586 | 191 |
| 2 nops | 140 | 2161 | 2147 | 1592 | 198 |
| 3 nops | 124 | 2157 | 2144 | 1583 | 188 |
| old TIMEIT_MULTI (50f5066 macros) | 130 | 2152 | 2138 | 1582 | 188 |
| old MULTI + aligned rambuf | 130 | 2150 | 2140 | 1582 | 188 |

Reading: a 1 to 3 instruction change in the poll step moves the poll rows by up to 10 units (PI I/O W spans 124..140, the port's own phase range is 125.3..142.7, one poll period ~17 rclk), and 1 nop lands PI I/O W exactly on 134 and puts SI I/O W within +1. The observed 4-9 gaps are inside codegen sensitivity. Caveat: the nops also shift code size and so rambuf and layout (SI DMA W RAM moved 4065 to 4074 at 1 nop), so this is a sensitivity bound, not a fit. GCC 12 vs GCC 16.2 codegen is not compared (no GCC 12 image), so whether the hardware binary had a different cadence is unknown (guess).
The 4b538eb rewrite does not explain the poll rows: restoring the pre-rewrite macros (taken from 50f5066, `timeit_average` array version) leaves them unchanged (130 / 2152 / 2138 / 1582). It does explain the cheap rows: C16R..C64R read 3 (hw 3), C8R 2, U8R..U32R 35 (hw 34), U32R seq 134 (hw 134), rand 134 (hw 134), banked 134 (hw 136). So the report's "hardware 3, fork 2, inferred parity" for C*R is better explained, measured, by the rewrite.
Conclusion: pointwise comparison to hardware for poll rows is valid only as "this binary", not "hardware's binary". Poll-row fails (PI I/O W, SI I/O W, SI DMA W ROM, PI DMA 8/128) are real disagreements at one binary, with unquantified-by-hardware codegen uncertainty of ~±10. They are not evidence of a model error of size 4-9. The follow-up in the report (build 50f5066 with GCC 12) stays the right way to settle it; #16 same-binary run is the clean one.

## 5. Wiring
Reproduced: `behaviors.py --results` over my standing run regenerates `n64-timing-results.tsv` byte-identical to the committed file except the one-line provenance header (130 checks). `--check` ok on the committed tree. Status counts in the spec: pass 69, fail 33, consistent-only 1 (matches). pi.io-busy pass->fail, si.io-busy pass->fail, si.write64-rom pass->consistent-only, si.write64 stays pass (4065). The four bench rows are removed from checks.tsv (bench ROM still runs them). Pref 21: the added systembench checks go into verify columns; fit-from additions only for the systembench twins of existing fit points (pi.block-writeback 128/1K/64K, si.read64-base, joybus-skip/escape/handshake/no-device), and pi.block-writeback's note says the 128/1K/64K twins are fit data and pi-dma-8 is independent. pi.page-setup/halfword-bias get all four PI DMA checks in verify without fit-from although the same hardware numbers were used to set pi.block-writeback; acceptable since those two rows are wiki-basis, not fit. Honest enough. Note (not a blocker): the 4 rewritten notes say "the poll phase its own code fixes ... compares the model with hardware at the hardware's poll phase". Per section 4 that overstates; should read "at this binary's poll phase (codegen-sensitive, ~±10 rclk)". The pass->fail flips are artifacts of replacing a lenient phase-window check with a one-binary check, not a regression of the model.

## 6. Standing (head vs base, both rebuilt by me, standing.sh)
- MM 600 `--stats` md5 9629185039701bddcdbd90c248a4f38b on base and head.
- nemu64 timing, cycle, cop0hazard `values.tsv`: byte-identical base vs head, and vs the worker's after run. thar0 `compare.tsv`, bench `results.tsv`, mmbench `summary.tsv`: byte-identical base vs head.
- rom-sha256 list: identical base/head excluding systembench ROMs; head 688 ROMs, list sha256 f3c63c4bacb0 (same as the worker's).
- det and stepcap: PASS (MM 29 files / 8219 fields; nemu64 x3), round trip PASS (600 fields, saves at 150/300/457), TMEM poke PASS (first diff field 31), ctest 9/9 (base and head).
- head: `--check` ok, `--self-test` 50 cases 0 failed, lint ok, pidma-replay 5/5, systembench report 11/11.
- Systembench results from the standing run identical to my standalone run.

## Diff findings
- ares/n64/timing/behaviors.tsv (notes of pi.io-busy, si.io-busy, si.write64, si.write64-rom) and the generated spec: "hardware's own poll phase" wording, see 5.
- tools/n64-timing/README.md (n64-systembench section): "instruction sequence very likely the same" is unverified; section 4 shows 1 nop moves the rows. The 4b538eb bullet is accurate but does not say its effect on the cheap rows (above).
- No dead code, no timing constants added (behaviors.hpp strings only), no committed third-party code.

## Not reproduced / not done
- GCC 12 vs 16.2 codegen comparison and the 50f5066-era build: not possible with the pinned image; variants are a sensitivity probe only.
- Worker's wall-time comparison (MM 22.9 vs 23.3 s) not re-timed; core is byte-identical in output and differs only in strings.

## Recommendation
Land. Ask for (optional, small) wording fixes in the four notes and README, and the C*R explanation (4b538eb, measured). Follow-ups: hardware-era build (50f5066 + GCC 12) or the #16 same-binary hardware run before refitting pi.io-busy / si.io-busy / si.write64-rom / pi.block-writeback; do not refit to the fork's 130/2151 numbers.
