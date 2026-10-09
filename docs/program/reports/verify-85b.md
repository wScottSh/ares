# verify-85b: PR #85 calib-kit at 17729ddfa (after calib-kit-fix)

## Verdict: PASS-WITH-NOTES. Recommendation: land, then follow-up with scope (below). Merge master into the branch first (6 textual conflicts, mechanical).

The blocking defect is fixed and proven three ways. The kit is now comprehensive against my independent enumeration, with a short list of residuals that the worker mostly disclosed. Nothing found that makes a console run unsafe or invalid.

Setup: worktree /home/wscottsh/repos/ares-wt/verify-85b (detached at head), build /home/wscottsh/n64-timing/build/verify-85b, private N64_TIMING_HOME /home/wscottsh/n64-timing/verify-85b-home (libdragon ipl3_compat copied in, sha256 f522db2e...a068), results /home/wscottsh/n64-timing/results/verify-85b/. Host load 0.5-5.

## 0. Master moved (#83)
`git merge-tree --write-tree 17729ddfa origin/master` (master 1081af9f8): CONFLICTS in 6 files, all textual: ares/n64/timing/behaviors.hpp, behaviors.tsv (3 hunks, same rows edited on both sides: #85 appends hw: checks, #83 edits systembench rows), docs/spec/map-1-closure-draft.md, docs/spec/n64-timing.md (generated, regenerate), tools/n64-timing/behaviors.py (RUNNERS set needs both "systembench" and "hw"; the standing-checks tool list needs both systembench/report.py and kit.py --self-test), tools/n64-timing/standing.sh (keep both lines). I did not resolve it. My runs are on the head as-is. After the merge: hw:systembench (ext) can get a reader on top of #83's systembench/report.py and rows.tsv (today it is store-only and the doc says "run report.py by hand"); the dry-run count stays 74/79 until then.

## 1. Blocking fix: PASS
- Disassembly (mips-linux-gnu-objdump, boot-1/kit-span.z64, 0x80003624..0x80003668): `lui a0,0xa460; ori a0,a0,0x10` (PI_STATUS wait), then `lui a0,0xa460; ori a0,a0,0x0`, then `sw t3,0(a0)` (DRAM_ADDR), `sw t3,4(a0)` (CART_ADDR, 0x08000000+off), `sw t7,8(a0)` (RD_LEN). Stores now hit DRAM_ADDR/CART_ADDR/RD_LEN.
- `n64-run --dump-sram` exists (n64-run.cpp +9 lines, acts after the stop). calibration/run.sh: `kit: 103 SRAM copies checked, 0 errors` (measured, 1 min wall).
- Old hw_out (scratch copy, `li $a0, PI_BASE` removed, 3 ROMs on my fork): 6 errors, "SRAM copy differs from the ISViewer copy" x3 and DOM1 regs wrong, e.g. kit-dma lat 8 / pwd 127 (should be 0x40/0x12), kit-span lat 168. So the check detects the old bug.
- `#kit-pi dom1_lat=0x40 dom1_pwd=0x12 dom1_pgs=0x7 dom1_rls=0x3` at the end of boot-1/kit-dma.
- PI kit points vs standalone bench (pif-joy/after, all boot delays): 23 shared points (pi-dma-sizes, pi-io-read/write, uncached-sizes, rcp-reg-read, pif-ram-read, si-io-write) all overlap; cart-to-ram-8 kit min 135 (all 8 delays) vs bench 135..136; old hw_out 254. cart-to-ram-1024 9117/9117, -128 1181/1181, -65536 583749..583751 both.
- MM 600 frames --stats md5 with and without --dump-sram: 9629185039701bddcdbd90c248a4f38b both (measured, concurrent runs).

## 2. Ingest normalization: PASS
- kit.py --self-test: 14 cases, 0 failed (CRLF, CR, UTF-16LE+BOM, UTF-16BE, UTF-8 BOM + banner, ANSI, byte-swapped zero-padded SRAM, value edit under old footer, cut log, CRLF+edit, 3 compare cases).
- Mutations in a scratch copy: remove the `\r\n` replace -> CRLF case FAILED (1 failed); remove ANSI.sub -> color-code case FAILED; force utf-16-le -> UTF-16BE case FAILED. Restored: 14/14.
- dry-run.sh end to end (CRLF kit-vi, byte-swapped .sav, SRAM .srm, cut log stored not compared, pads4, ext thar0, ext snapper64): 74 hardware checks and 26 behaviors changed; the same 74 of 79. The 5 not flipped are systembench, pidma-offset, mm-filesel (no reader) and vi-mid-field-blank, vi-unfetched-video (`none:`). 

## 3. Comprehensiveness: PASS with residuals
Counts: questions.tsv 79 data rows (80 lines), items.tsv 47 items (48 lines), undecidable.tsv 16 (17 lines).
My enumeration (all 149 behaviors rows, all checks, all verify-85 2b/2c items): 
- Every 2b fit/model-choice/inferred row and every #16 sub-item and follow-up verify-85 listed is closed by a question or is in undecidable.tsv; I mapped each of the 47 items to its question(s) (none `??`). Triangle setup is built for fill/Z/shade/shade-Z; textured types are not (disclosed).
- 8 `none:` ROMs from verify-85 now all have kit points. Questions with `none:` are 2 (vi-mid-field-blank blocked on #84, vi-unfetched-video needs a capture); ext: 5 (thar0-console, snapper64 have readers; systembench, pidma-offset, mm-filesel have none).
- Rule mutations (scratch tree) fire: remove question ri-reorder -> 3 errors (checks undefined, item:16.ri-reorder "has no hardware question", inventory drift); remove undecidable legacy.cart.rtc-tick -> "has no hardware question"; blank count-per-field closes -> 3 errors (clock.vclk, item:16.count-per-field, drift). Restored: --check ok.
- 3 fit-only rows (cpu.count-write-hold, cpu.fetch-ahead-slots, cpu.ctc1-fpe-ce): handled honestly. They name no hw: check in verify, the inventory shows them "fit only" with the console-re-run question beside them, and the dry-run does not flip them. (Other fit rows, e.g. eret, irq-sample, exc-fpu-detect, do flip because they also name an independent hw check; that is consistent with pref 21.)
- The 16 undecidable reasons: scheduler.tie-rank, ri.request-latency (1.3 ns unit, fork results do not move with it), legacy.cpu.sysad-frozen-step, legacy.pif.step-quantum (emulator quanta), legacy.clock.vclk-pal (outside NTSC target), fu.pif-ram-dword (fork CPU freeze, measured) and legacy.cpu.nmi-entry (no start timestamp): sound. legacy.pif.boot-timeout and the 8 legacy.cart.* are sound as "not by this kit/flashcart" but wording "not-hardware-decidable" is stronger than true: a console with retail cartridges or a modified IPL3 could decide them. Suggest rewording to "not decidable by the kit". Scott should know these 9 are a hardware-possible but out-of-kit set.
Residuals (mine, not blocking):
 a. 40 passing rows with an independent reference (wiki/vendor/derived/measured) are not named in any closes: ri.refresh-clean/dirty, ri.rank.refresh, vi.vclk-per-pixel (all via bench:uncached-vs-hpos, which kit-hpos runs but its question does not close), cpu.pi-io-read, si.write64-rom, pif.joybus-byte, rdp.span-1cycle/2cycle (thar0), rdp.noise-step/reset, rsp.slot, ri.max-burst, clock.unit, plus ~25 nemu64 `measured` cpu rows (covered implicitly because nemu64-console compares all 1605 values). The coverage rule only enumerates fit/model-choice/inferred/weak rows, so these cannot go missing from the rule but their hw: link is absent. Cheap follow-up: add the bench:/row ids to the closes of vi-cpu-contention, cpu-reads, joybus-pads, thar0-console, noise-*.
 b. hw:cpu-exceptions bundles the Watch points (fork fired=0, a known fork gap) with eret/irq/AdE points. I edited a copy of the fork log so Watch fired=4 and nothing else differs: hw:cpu-exceptions -> fail, and cpu.issue pass->fail, cpu.eret fit only->fail, cpu.irq-sample fit only->fail. A correct console will therefore flip those three rows to fail for the Watch gap alone. The detail text names the point, but split Watch into its own question closing only fu.exc-entry before the console run.
 c. vi-first-line first_ticks tolerance +-24 left wide (worker disclosed, NOT DONE). sp-dma-direction cannot decide 8-128 B (disclosed). textured triangles, G_AD_NOISE range beyond one threshold (disclosed).
 d. Question text says cmd-fetch-burst walks "8 poll phases", the worker report says 16; cosmetic.

## 4. Six kit points end to end
1. cmd-fetch-burst (kit-rdp): ROM kcm/kff in calib/asm.py (frozen RDP, 512-NOP list, 64 polls, spin 0..15 walks the phase); fork offsets `0,128,240`, burst_gcd 128. Mutant fork (tsv value 64 + regenerated, built as build/verify-85b-mut64): offsets `0,64,128,192,240`, burst_gcd 64, hw:cmd-fetch-burst and rdp.cmd-fetch-burst -> fail; head vs head passes. (The mutant also moved hw:rdp-atomic and hw:rdp-sync-setter, expected: fetch burst changes every list.) Caveat: gcd rests on the poll landing on a 128-offset; a console with a different burst could show only multiples (inferred).
2. 4-pad (kit-dma): fork 1 pad mask=1 read64-4 73461, pads-4 mask=15 read64-4 80143; 4-pad log vs a model whose pads-4 is 1-pad data -> hw:joybus-pads fail; vs real pads-4 -> pass.
3. kit-tex tmem-load-rate: DPC_TMEM per load fit (fork 0.7028 clk/B + 7, rule rel:3). Scaling tmembusy of the block lines by 1.2 with a recomputed footer -> hw:tmem-load-rate and hw:loadtile-rows fail.
4. kit-bus ri-reorder: bus-derived own-minus-bank5 = client_ticks 2798-2566 = 232 (range:abs:10). client_ticks 2798->2600 -> hw:ri-reorder fail. (My first edit hit the wrong field and passed; the metric uses client_ticks.)
5. kit-zmem write-granularity: fork run_slope 15.405 / 36.784 rclk per run, r2 0.959/0.979, reject_saving 1259/3606, as the question states. Not mutated; rule is range:rel:15 (wide, but the two hypotheses differ by 2x+).
6. kit-cpu2 cpu-exceptions: values match the question text (AdEL/AdES/TLBS/Mod 6, fetch AdE 4, jr 3, CTC1 FPE 2, irq-sw 4, eret 4, Watch fired 0). See 3b.

## 5. Console safety
- emux: scanned all 95 ROMs under calib/roms (every word after 0x1000, COP0-CO with emux functs 0x20,0x25,0x27,0x28,0x29,0x2a,0x2c): 18 hits, all ASCII data ("C= ", "BEQ ", "CPU)", "B.S ", "Cycl", "C1 (" ...), 0 instructions. hwout.transform also raises on any surviving emux mnemonic (worker claim, not re-mutated).
- IPL3: build.py refuses an altered stub for --hw and for --suite calib (flipped 1 byte: both builds exit with "not the pinned ipl3_compat.z64 (libdragon e356bf3f..., sha256 f522db2e...)"). Pinned file sha matches.
- PIF LD: no 64-bit load from PIF/RCP space; `ld`/`k_sb_ld` is used only on SB_BUF (RDRAM); pif-ram-read uses lw. fu.pif-ram-dword is in undecidable.tsv.
- Bounded waits: bus.py (BUS_POLLS), zmem.py (TIMEOUT 100 ms), cpu2.py pi_wait (2^17). Unbounded: k_rdp `krd_wait` and `kcm_poll` (DP interrupt, in kit-rdp and kit-tex), hw_out/hw_init PI_STATUS waits. A hang there leaves no SRAM write (the ED64 X7 path gets nothing) and only a partial ISViewer log; recoverable by power cycle, no state damage. Worth bounding when someone next touches asm.py.
- COP2: cpu2.py sets CU2 (Status bit 30) only inside the ldi points and clears it after. Watch: WatchLo set to a RDRAM address and cleared after; exceptions patch 0x80000000/0x80000180 with a stub, I-cache invalidated (cache 0x10), restored by vec_off; handler clears Status.IE and erets to k0. Not verifiable on hardware: MTC2/MFC2 with CU2 on a VR4300, Watch behavior, the AI DMA points (kit-bus) audio output.
- Nothing writes to PIF boot ROM or flash. Joybus frames are read/status.

## 6. hardware-run.md
Followable end to end for SC64 USB, and for ED64 X7 via SRAM. Covered: boot stub clone+pin+sha, build, SD copy lists (11 + 7 = 18 ROMs, matches KIT_ROMS), ED64 save-type header and Reset-to-flush, power cycle before every ROM (explicit warm-boot reason), required 2 runs per ROM, recommended 7 boot-delay builds with rename, reset run for noise-reset, kit-dma with 1 and 4 pads, pak removal, CRLF/UTF-16 handling, photo fallback limited to logs <= 2 KB (table), ext ROMs. ingest.py identifies ROMs by header content so capture file names only matter for `.reset.` and `ext-`.
Gaps: (1) sc64deployer option names (`--save-type sram`, `debug --isv`, `download save`) are unverified; the doc says to check --help. (2) the Thar0 and snapper64 builds and systembench from an unmerged PR are by-reference. (3) The ED64 gamedata path is "confirm on the first ROM". (4) ED64 users cannot see a hang until a blank save; say that an empty/zero save means a hang. (5) "Four controllers" is listed as required but only kit-dma uses them; a user with one pad should skip pads-4 rather than stop. None blocks.

## 7. Standing
- MM md5 9629185039701bddcdbd90c248a4f38b.
- nemu64 values.tsv vs pif-joy/after: timing 1605 lines, cycle 14, cop0hazard 6, all `cmp` identical. ROM sha256 prefixes bd946fb1, ae9c83aa, 9518d316.
- behaviors.py --check ok; --self-test 56 cases 0 failed; romgen/selftest.py 72/72; lint-literals ok; kit.py --self-test 14/14.
- run.sh whole kit on the fork: 1 min wall, 95 ROMs built, 103 SRAM copies verified.
- dry-run 74/79 to pass (above).
- behaviors.tsv diff base..head: 149 rows both sides; only the `verify` column changed (82 rows); no value, unit or code change; behaviors.hpp diff is verify strings only. n64-run change is --dump-sram only.
- Not run: determinism/stepcap/state-roundtrip/mmbench (standing.sh); core emulation did not change (verified by md5 and by the diff).

## Follow-up scope (land, then)
1. Merge master (#83) into the branch, resolving the 6 files; wire hw:systembench to systembench/report.py.
2. Split Watch out of hw:cpu-exceptions.
3. Add hw: links for the 40 referenced-and-passing rows (3a).
4. Reword the 9 legacy.cart/boot-timeout undecidable reasons to "not decidable by the kit".
5. Bound krd_wait/kcm_poll.
6. Disclosed leftovers: vi-first-line tolerance, small SP DMA, textured triangles, #86.

## Not reproduced / unverifiable
All hardware behavior; sc64deployer option names; the worker's claim the mutant (burst 64) also read 128 with the spin before END (I did not rebuild that earlier variant); the worker's Watch/CU2 safety (no hardware).
No background processes of mine remain (pgrep checked); scratch worktree verify-85b-mut removed.
