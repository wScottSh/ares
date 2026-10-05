## Independent verification of T6 (PR #51, head 9cb6723cc): PASS-WITH-NOTES

Built head myself (RelWithDebInfo, clang64, build dir `build\verify-51-head`). Base numbers come from the worker's saved master (071e024a1) run in `results\t6\before-master` (I did not rebuild base). Raw: `C:\Users\Scott\n64-timing\results\verify-51\`.

### Reproduced
- `ctest -R unit:` : timeline, ri-cost-table, dpc-regs all pass.
- ri-cost-table expected values vs `rdram-bus-arbitration.md` s.2/B8 table: read hit 14/18/26/42/74, write hit 8/12/20/36/68, read miss clean 36/40/48/64/96 and dirty 44/48/56/72/104, write miss clean 30/34/42/58/90 and dirty 38/42/50/66/98, refresh 52/54 rclk. All match the NEC derivation line by line.
- Mutations (applied to my worktree, reverted): `bank.dirty = false` gives 12 failures; rank compare removed gives 4 failures. Both match the worker. Unmutated: ok.
- nemu64: Timing 909, Cycle 9, CP0 5 (master 922/9/5). Output identical to worker's.
- Classification script (`results\verify-51\classify.py`, `c2.py`) over base and head `values.tsv`, same 1588 keys: 164 fixed, 158 broke. All 158: measured is expected minus 1 in every element; the first instruction is a load/store opcode. Decoded register overlap (load rt vs later word rs/rt): 153 overlap, 1 is the BEQL case (ADDIU depends on the load), 4 do not overlap by decode: `LB $A2; MTC0 $A3/$R0, _Unused7` and the DMTC0 twins (expected 3, now 2). Same load-then-next-instruction shape, but not a register dependency, so "every one is a dependent instruction" is slightly overstated; they are still the same 1-pclk shortfall. Which cause (load-use interlock vs a CP0 rule) is T7a's to settle.
- Load from uncached VI off: 8/8 values pass; Load Miss VI off: 1 fail, bank 0x80400000 mean 41999 vs 42000 (a=0xa40f); Load Miss VI on pass; Load from uncached VI on: 1 fail (median 33, exp 35-37, expected until T11); Uncached write buffer 16/16 pass; Cached loads and store 19/19.
- Bench (my exe): mi-memset-uncached 18.277 pclk/SD (band 18.346-18.418, FAIL); mi-memset-cached 70.999 pclk/line (band 71.17-71.31, FAIL); dirty-miss-isolated clean 46, dirty 46, gap0 24 (before 46/86/40); pi-dma-sizes cart-to-ram-8 189.33 (was 193.33, band 191.07-194.93, newly FAIL). Totals pass 9 / fail 12 / report 19 (master 10/11/19). Bench lines identical to the worker's.
- determinism (MM, 27 files, 8138 fields): PASS. stepcap MM: PASS (27 files, 8138 fields). stepcap nemu64 timing/cycle/cop0hazard: PASS (25/2/1 fields). state-roundtrip 600 fields: PASS; tmem poke first differs at field 31, trace_hash only.
- gen: `behaviors.py --self-test --check`, `lint-literals.py`, `clock-rebase.py --check` all ok.

### Trace-fold change (timeline.hpp): needed and correct
I reverted it in my worktree (fold per batch as in T5, `record()` a no-op), rebuilt, and ran `determinism.sh --step-cap` on the three nemu64 ROMs: all three FAIL at frame 0, column trace_hash. With the change they PASS. So the per-event and per-step fold is required for stepcap once the Bus and SysAD actors add steps. Code reads right: advance() folds the first step, each later step is folded by `record()` (RSP/RDP loops, and the CPU's own grant in `postAndDecide`), and each event in `fireEvents`. Note: the "call record() for each later step" rule is convention, enforced only by stepcap failing.

### Source review (ri/, cpu/sysad)
- Bytes move only at grant: `RI::run` does every `rdram.ram` read/write for CPU-sized bursts after `channel.decide()`; `rdram.ram` is private with named friends (RI, MI, Loader, AI, PI, PIF, RSP, VI, RDP). MI repeat/EBus keep a direct path, documented.
- Reads behind older writes: `SysAD::read/fill` call `drain()` (await no non-Done entry) before posting.
- Dirty miss: `DataCache::Line::fill` copies the victim, calls `sysad.fill`, then `sysad.writeback`. Bench: dirty-single == clean-single == 46.
- Arbitration in rows: `ri.rank.*`/`ri.arbitration` in behaviors.tsv drive `rank()`; mutation 2 above shows the test depends on it.
- No host-order dependence: pending bursts hold a tag (no host pointers), per-requester sequence is serialized, `canonicalize()` sorts live entries on write, `decide()` removes by shift. Roundtrip and stepcap PASS.

### Notes (not blocking)
1. Refresh-only-while-VI-active is a real behavior choice that conflicts with `rdram-bus-arbitration.md` B11 ("Before VI is configured ... 10.8 ms", refresh runs pre-VI) and n64brew RDRAM_Interface. It is justified only in a comment at `ares/n64/vi/vi.cpp:58-61` (which cites the VI page, not the conflicting source) and in the worker's report. `ri.refresh-trigger` still reads `hsync ... one SetRR per VI HSYNC (B11)` with no note. The conflict should be recorded in that row's note (and so in the spec), since the behavior contradicts the row's own cited source.
2. Fit rows `sysad.rdram-write-period` / `sysad.rdram-block-write-period` have fit-from and verify-is-fit notes. Good. But the row text states "the rest is VI fetch contention (plan T11)" as fact; it is an inference (the worker's report says so; the row does not). The two memset benches stay out of band (-0.56%, -0.34%) against the fit's own data, so they are not independent evidence.
3. `sysad.register-write` 5 rclk is model-choice, no corpus, labeled honestly. `ri.request-latency` is model-choice, honest.
4. D-fill path is derived at a clean row miss (nemu64's loop) while systembench saw no row penalty on uncached reads; this tension is in the worker's report (deviation 5) but not in `cpu.dfill-total`'s note.
5. Plan's own check bands for mi-memset-uncached/cached (18.4 / 71.2) and Load Miss VI-off bank 4 (mean 41.999) are not met; the worker reported them as short, with causes labeled inferred. The inferred causes (T11 VI fetch, harness bank-4 traffic) I did not test.
6. pi-dma-sizes cart-to-ram-8 regression 193.33 to 189.33 is real (reproduced); worker attributes it to PI_STATUS poll quantization (inferred), T8 owns it.

Not run: wall-time claims (shared host), MM idle-loop explanation, mmbench sct grant counts.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
