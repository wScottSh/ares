# PI DMA: a first block that writes no byte

Green-plan unit U-ROWEND. Question: what does the PI do on the RDRAM side when a DMA's first block holds no more bytes than its RDRAM misalignment? This happens when the first block ends within 8 B of a 2 KiB row end at a misaligned address (RAM 0x7fc, 0x7fe), and when a DMA is shorter than its misalignment.

Labels: **cited** (file:line or URL), **measured** (run on the built emulator in this unit), **inferred**.

## What the references say

- **n64brew Parallel Interface, DMA Transfers** (https://n64brew.dev/wiki/Parallel_Interface, fetched 2026-10-10, cited):
  - Every block is filled from the PI bus and then written back to RDRAM ("Internal process").
  - "The exact format of RDRAM writes is unknown at the moment"; 64-bit writes are assumed.
  - The first block "possibly" uses "smaller, masked writes" ("Internal process: first block").
  - The hardware counts the first block's write "starting from index 0 of the buffer", even though the data sits from the misalignment index on, "and even though masking is performed correctly". With misalignment 6 and length 8, only bytes 6..8 land.
  - The page calls the whole description a match "in observable behavior", not the circuit.
- **rasky/n64_pi_dma_test** README and golden logs (cited): the data and timing source the wiki section rests on. The README gives no timing model.
- **ares upstream `bea395b24`** (rasky, PR #2139, reverted by `807ef0300`, cited): a per-block timing formula with "+21" for a masked write and "+6" row open. Those constants pass the same golden logs at 10 % tolerance, so they are fit to the data this unit checks against. They also charge every misaligned block, not only an empty one. Not used.
- **ares upstream master** `ares/n64/pi/dma.cpp` (3c63fbcfb, cited): one-shot timing, no per-block RDRAM cost.
- **MiSTer `rtl/PI.vhd`** (cited): byte-enable writes to DDR3. It shows the functional mask, not RDRAM timing.
- **dma-timing.md, green-plan/pisi.md item 3(c), followups.md (t8/verify-57)**: the residual (hardware about 29 rclk more at these points) and the two candidate mechanisms. None states the hardware behavior.

No reference states the empty case directly.

## The inference

The wiki's process, applied to a first block of length L ≤ misalignment m, gives one write that covers buffer indexes 0..L-1, all inside the first octbyte, with every byte masked off. The RI counts octbytes from the length and Adr[2:0] (rdram-bus-arbitration.md B2, `RiBus::octbytes`), so a 0-byte burst at a misaligned address is one octbyte on the wire. Before this unit the fork skipped the write (`PI::dmaStep`, from T8 `c0712e727`). That skip has no reference.

The rule adds no constant. The empty write costs what the bus model charges any one-octbyte write. The row is `pi.first-block-empty-write`, basis inferred.

## Independent check (measured)

Exact pidma replay (`tools/n64-timing/pidma-replay.py`), master `7fd39bf97` against this rule; the standing runs on master `f474e9875` and on this branch give the same two tables. Raw tables are in `~/n64-timing/results/u-rowend/before/pidma/points.tsv` and `head-pidma/points.tsv`.

| Points | Master | With the rule |
|---|---|---|
| RAM 0x7fc, sizes 8-382 (excl. 305-352): failures, mean deviation from the hardware midpoint | 12, -3.94 % | 0, -0.32 % |
| RAM 0x7fe, same sizes | 9, -3.46 % | 0, +0.45 % |
| Every other offset, sizes 8-63, mean deviation | -0.22 % | -0.20 % |
| Sizes 1-7 whose first block writes no byte (196 points, outside the pass rule) | 131 within 3 %, mean -7.43 % | 193 within 3 %, mean -1.62 % |
| Sizes 1-7 whose first block writes bytes (252 points, the control) | 249, mean -1.69 % | 249, mean -1.43 % |
| ROM self-check | 1 failure | 0 failures |
| Sizes 8-382 within 3 % | 23960 / 24000 | 23975 / 24000 |

The sizes 1-7 set is a second, independent population: an empty first block that does not sit at a row end. It moves from -7.4 % to the control's -1.4..-1.6 %.

**Phase coupling (measured).** The ROM runs its points in one timeline, so any change to an early DMA shifts the bus phase of every later point. The rule first acts at RAM 0x782 size 1, and 9262 later points change by -29 to +36 ticks, symmetric about zero. Failures outside 0x7f8..0x7fe go from 15 to 21, and 0x7f8 size 40 moves from inside the band to +3.47 %. That block holds 8 bytes, so the rule does not touch it. A diagnostic build that applies the rule only at row ends leaves every point before 0x7fa bit-identical. It gives 0x7fc and 0x7fe 1 failure (0x7fc size 12, +3.67 %) instead of 0, which is the size of that phase lottery at the target points.

## What would decide it on hardware

Kit question `pi-row-end` (kit-dma `pi-dma-rowend/*`) now also runs its 8, 128 and 1024 B DMAs 4 B before a row end. That is the empty case; its 8 B and 64 B points never reach it.
