# sysbench2 report

Status: done. Branch feat/sysbench2, head 1bfc59b03, base master 0ee24be3c. PR: https://github.com/wScottSh/ares/pull/76.
Worktree: /home/wscottsh/repos/ares-wt/sysbench2. Builds: ~/n64-timing/build/sysbench2 (head) and sysbench2-base (master), plus sysbench2-chk, which built each intermediate commit. Homes: ~/n64-timing/sysbench2-home-*. Raw runs: ~/n64-timing/results/sysbench2/{before,item1,item2,pi-read,si-write,si-rom,after,wall}, with compare-before-after.txt.

## Item 1. The pi-io-write poll phase

- k_sb_while runs a2 x jitter nops after the write. a2 is the rep index, which bench_multi now passes. The 50 reps take 1 nop per step and the 10-rep points take 5, so the reps cover 50 pclk, two poll periods. The reason is stated in the asm comment, the expected.tsv source and the bench README.
- The new value is 133 rclk (pass, 132..136). It was 140 on master's runner. The reps read min 94 ticks (125.3 rclk) and max 160. The max is the cold first rep, which TIMEIT_MULTI drops. The phase mean is 133.86, which floors to 133. verify-75's sweep of N=11..35 got 133.4.
- Is the original phase-spread on hardware? Probably not (inferred). In TIMEIT_WHILE_MULTI, nothing free-running sits between reps: VI_CONTROL=0, interrupts are off (main.c:623-624), the loop and stack hit in cache, and PClock and SysClock come from one master clock. So each rep is the same deterministic function of the previous one, as in ares. The hardware 134 is then one phase of its own sawtooth. It may sit up to half a poll period (about 8 rclk) from the phase mean, and the ±2 band does not show that. This is written in the check source. PiIoBusy and sysad.register-write are not refit.
- write64 also gets the phase walk: 4065 -> 4067, pass.

## Item 2. The ports (main.c @845635c)

- U32R seq, rand and banked (main.c:270-292, 582-584) report net_pclk against 132/132/134. They are wired to cpu.uncached-read-total.
- PI I/O R (main.c:182-185, 594) is 144 rclk, wired to legacy.pi.cart-read and then cpu.pi-io-read. The code path behind ares's 181 rclk: RCP::read steps CpuRcpRegisterRead - CpuDcacheHit = 21 pclk (memory/io.hpp:6), and PI::readWord steps pclk(250) (legacy.pi.cart-read, pi/bus.hpp:63). With the 1 pclk issue that is 272 pclk = 181.3 rclk.
- SI I/O W (main.c:221-228, 600) is 2158, wired to legacy.si.bus-write and then si.io-busy. Its poll phase is walked.
- SI DMA W ROM (main.c:56, 206-214, 598) is 2144. It was a guard on si.write64, then moved to si.write64-rom.
- JOY Empty 0B/1B/4B/8B/32B/56B/63B (main.c:307-425, 602-608) are checks, because no channel gets a command and controller state cannot enter. They are wired to si.read64-base, with guards on legacy.si.dma-read-short-command.
- JOY Accessory (main.c:495-510, 613) is a check under read64-1's assumption, a controller on port 1, which n64-run connects. Hardware Accessory 36834 < 1J 37987 is consistent with a pad there (inferred). It is wired to si.read64-base, with a guard on legacy.si.dma-read-controller.

Measured on master's core: u32-seq 131 pass and u32-rand 131 pass. These fail: u32-banked 131 (134), pi-io-read 181 (144), si-io-write 2148 (2158), write64-rom 4068 (2144), empty-1b 16481 (16424), empty-4b 20728 (20644), empty-8b/32b/56b/63b 20728 (21163/21163/21170/21178), accessory 39898 (36834). empty-0b passes at 15060, at the band edge (15060.06).

## Item 3. Fixes. Each uses a published total and is local.

| Fix | Before -> after | Check |
|---|---|---|
| cpu.pi-io-read 214 pclk (derived: 144 rclk = 216 pclk less the 2 pclk harness), domain 1 only. Domain 2 keeps legacy 250 | 181 -> 142 | pass (142..146) |
| si.io-busy 2158 rclk (measured). legacy.si.bus-write row and allowlist entry deleted | 2148 -> 2158 | pass |
| si.write64-rom 2144 rclk (measured), used when the WR64B PIF address & 0x7ff < 0x7c0 | 4068 -> 2147 | pass |

These are not fixed. Each is reported as an honest fail. No local published cost exists for them:
- u32-banked. RI per-bank behavior is not traced.
- JOY empties and accessory. They are legacy pif.estimateTiming per-command costs, pending calibration-16. ares stops at channel 5, so every empty from 8B on reads 20728.
- read64-1 is unchanged at 38477.

Moved standing values, per commit, all measured:
- **ROM-only commits 1-2 (same core, bench ROM bytes moved).** sp-dma-sweep wr-4096-off0 6.169 -> 6.508 -> 6.495 B/rclk (fail -> pass -> pass). pi-dma-sizes cart-to-ram-8 197.33 -> 196.0 -> 197.33. rcp-reg-read 22 -> 21 (pass). mi-memset values moved under 0.03 %. setter env-color-4096 1.227 -> 1.235. The dirty-* and hpos report rows each moved by ±2.
- **cpu.pi-io-read.** MM frame 0 cpu_cycles 58278904 -> 58219744 (-59160). That is about 1020 boot CPU cart reads at 58 pclk each, inferred to be IPL2 copying IPL3. Frame 599 moved -59196.
  - MM md5 be54e666 -> 06fbb0b7, and fb_hash differs on 378 frames.
  - mmbench: filesel-named 1.6723 -> 1.6932, filesel-rotate 1.0886 -> 1.0919, sct 1692429.8 -> 1711920.3. The other scenes moved under 0.1 %.
  - Bench: sp-dma-sweep 6.495 -> 6.334 (pass -> fail). mi-memset-rspdma 6.498 -> 6.493 (pass).
  - Other suites: 40 of the 100 thar0 rows moved. pidma 23769..23828 -> 23776..23833 (FAIL both). noise's first pixel follows the boot.
- **si.io-busy.** MM md5 -> 210d0d46. cpu_cycles differ on 16 rows from frame 3, then reconverge by frame 599. fb_hash is identical.
  - mmbench: filesel-named 1.6932 -> 1.6798, filesel-rotate 1.0919 -> 1.0896.
  - Bench: mi-memset-rspdma vi-on 6.493 -> 6.423 (pass -> fail, 6.49..6.515). sp-dma-sweep 6.334 -> 6.169. hpos bank5 median 36 -> 34.
  - Other suites: 1 thar0 row moved. noise's first pixel +78 clocks.
- **si.write64-rom.** Nothing else moved. MM md5 is the same.
- **Net master -> head.**
  - MM: md5 be54e666 -> 210d0d46. filesel-named 1.6723 -> 1.6798 (target 1.90-2.10, FAIL both).
  - Bench: mi-memset-rspdma pass -> fail. sp-dma-sweep 6.169 on both.
  - Other suites: 40 thar0 rows moved. pidma FAIL on both.
- **Unchanged on every run.**
  - The nemu64 timing/cycle/cop0hazard values.tsv are identical.
  - rdpstat and snapper are identical except emulated_s.
  - det and stepcap PASS (nemu64 x3; MM 29 files, 8219 fields). The round trip PASSes at 150/300/457. The TMEM poke PASSes.
  - ctest 9/9. --check is ok, --self-test runs 42 cases with 0 failed, and lint is ok.

Row status master -> head:
- pi.io-busy fail -> pass.
- cpu.pi-io-read, si.io-busy and si.write64-rom are new and pass.
- cpu.uncached-read-total pass -> fail, from u32-banked.
- legacy.si.bus-write is deleted.
- Counts: pass 64 -> 67, fail 36 -> 36, no-corpus 16 -> 15.

## Item 4. Cleanups

- **ri/bus.hpp.** The orphan comment moved onto post()'s `Clock d = ...` line, which is what it describes.
- **expected.tsv.** "its's" is fixed in all 4 rows.
- **LD from PIF RAM.** No reference times it. n64brew Memory map (SI external bus) says access size is ignored as for the RCP registers, where "64-bit reads ... will completely freeze the VR4300". n64-systemtest pif_memory/mod.rs:14 says "LD and SD are untested". Decision: keep the double charge and label it inferred in the cpu.pif-ram-read note. The note also records the 7 boot reads from PR #75's verification.

## Standing set

- **ROM sha256 list.** before fa2357d4 (33 ROMs), after df296edc (35 ROMs). The 2 new ROMs are pi-io-read and si-io-write. Every bench ROM changed bytes. Every non-bench ROM is identical.
- **Load.** before 6.07 -> 1.61. after 16.38 -> 7.73 (the commit build was running alongside).
- **MM wall.** Copied runners, interleaved, load 6.1-8.4. Base 22.84 / 22.99 / 23.23 s, head 22.85 / 23.00 / 23.61 s. The medians are 22.99 and 23.00 s.

## Deviations

- Commits 1-2 take their results from composite runs: master's standing run with the bench suite rerun on the same runner from that commit's ROMs. The core is identical and every non-bench ROM is byte-identical. Commits 3-5 each have a full standing run. Commit 6 is comment and note only, and the head run `after` equals `si-rom` on every value.
- legacy.pi.cart-read is kept for domain 2.
- write64 gets the phase walk too, for consistency, at 5 nops per rep.
- Interim commits build. Each commit was compiled and checked in a scratch worktree, and all passed.

## Follow-ups

- sp-dma-sweep wr-4096 and mi-memset-rspdma read one boot phase. sp-dma-sweep read 6.169..6.508 across 4 layouts with one model, so their pass/fail is boot-phase noise. Give them a phase walk.
- U32R banked 131 vs 134: the cause is not traced.
- JOY: ares's estimateTiming stops at channel 5 and its per-command costs are legacy. The empties and accessory are now the hardware data for a rebuild.
- A BSD-derived PI CPU read: 15+LAT + 2x(PWD+RLS+2) + 22 pclk ≈ 140 rclk at retail (inferred). It would cover domain 2.
- empty-0b passes at the band edge.

## For the next unit

- MM baseline is now md5 210d0d46 (boot cart reads are cheaper and the PIF write busy is +8 rclk).
- New bench ROMs pi-io-read and si-io-write.
- No background processes of mine are running. Scratch worktrees are removed.
