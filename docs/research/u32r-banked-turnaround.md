# Read turnaround between RDRAM devices (u32r-banked)

Green-plan unit U-RES (docs/design/green-plan.md section 4, P1). Question: does the NEC RDRAM datasheet give a read-to-read turnaround when consecutive reads go to different devices, which could explain why `systembench:u32r-banked` reads 134 against hardware 136 and `bench:uncached-sizes-u32-banked` reads 131..132 against 134?

## Answer

No different-device read turnaround exists in the datasheet. The datasheet gives one gap after a memory read, 2 tCYCLE, and it applies to the next transaction whatever device that transaction goes to. The model already charges it on every read (`ri.post-read-gap`). The datasheet therefore gives no cost that separates banked reads from sequential reads. The 1 COUNT tick difference stays unmodeled and unreferenced until the console run (#16 q18 `cpu-reads`, q35 `systembench`).

## Source

NEC µPD488170L 18M-bit Rambus DRAM, preliminary data sheet, document M10801EJ4V0DSU1. URL: https://datasheet.datasheetarchive.com/originals/library/Datasheet-048/DSA0080865.pdf (49 pages; printed page numbers equal PDF page numbers; the copy read for this note has sha256 9870b405...6130). This is the datasheet that research/rdram-bus-arbitration.md row B8 cites.

**Page 44, "Transaction Timing Characteristics" table** (quoted):

| Symbol | Parameter | MIN. | Unit |
|---|---|---|---|
| tPostRegWriteDelay | Delay from the end of the current transaction to the beginning of the next transaction if the current transaction is a write to register space and the next transaction is made to the same device. Use zero delay if the next transaction is to a different device. | 6 | tCYCLE |
| tPostMemWriteDelay | Delay from the end of the current transaction to the beginning of the next transaction if the current transaction is a write to memory space and the next transaction is made to the same device. Use zero delay if the next transaction is to a different device. | 4 | tCYCLE |
| tPostMemReadDelay | Delay from the end of the current memory read transaction to the beginning of the next transaction. | 2 | tCYCLE |

The two write gaps name the device and fall to zero for a different device. The read gap names no device, so it holds for the next transaction to any device.

**Page 31, section 7.1 "Read Transactions" and Figure 7-1.** The read data packet starts tReadDelay after the request packet ends. tReadDelay "is not required to be the same for all devices within a Rambus system, but the difference (tReadDelay - tAckDelay) is required to be the same". The figure shows no next-transaction timing that depends on the device.

**Pages 32-36, sections 7.2-7.6.** Only the write figures (7-2, 7-4, 7-6) draw "Next transaction to same device" and "Next transaction to different device". The text of 7.2 says "The next request packet can be transmitted in the following clock cycle except for the case in which a register or memory space write to a device is followed by any other transaction to that device." Neither the read sections nor their figures (7-1, 7-3, 7-5) describe a device-dependent gap.

**Page 45, "Hit, Retry and Miss Delay Characteristics".** tReadHit is 10 tCYCLE from request start to read data start for a row hit. The table gives one value per device and no figure for a bank switch or a device switch. Each of the device's two banks keeps its own row in the sense-amp cache (section 8; research/rdram-bus-arbitration.md B6, B7), so a hit in either bank costs the same tReadHit.

The datasheet hands the remaining detail to the "Rambus DRAM user's manual (Reference Manual)" (pages 31-36). That manual is not in the repo, and no copy was found online for this note.

## What this means for the two checks

- The banked point reads the first word of banks 0-3, at 0x000000, 0x100000, 0x200000 and 0x300000 (tools/n64-timing/romgen/suites/bench/benches.py:273; n64-systembench main.c:286-292 as cited in expected.tsv). With 2 MiB modules (B6), banks 0-1 are device 0 and banks 2-3 are device 1. Each rep makes two same-device bank switches (0 to 1, 2 to 3) and one device switch (1 to 2), plus a second device switch (3 to 0) when reps run back to back.
- After the first rep each bank's row is open, so every read is a row hit, the same as the sequential point. From the datasheet, a banked read and a sequential read cost the same on the wire (inferred from pages 44-45).
- The gap to explain is 2 pclk per four loads (1 COUNT tick; bus.md section F). Even if the full 2 tCYCLE read gap were charged a second time on each of the two device switches, that adds 4 tc = 1 rclk = 1.5 pclk (inferred arithmetic, 1 rclk = 4 tc, 1 pclk = 2/3 rclk). The datasheet supports no such charge, so this is only a bound.
- Do not add a device-switch or bank-switch read penalty (green-plan.md section 8; bus.md F.6). The checks stay as they are: `systembench:u32r-banked` consistent-only and `bench:uncached-sizes-u32-banked` failing, each with the reason "one COUNT tick; no datasheet turnaround".

## Not checked

- The OKI MSM5718B70 datasheet at the URL in research/rdram-bus-arbitration.md returned an empty file on 2026-10-10. Its transaction timing table was not re-read for this note.
- The Toshiba TC59R1809 copy is a 10-page scan with no text layer. It was not read.
- Other causes of the tick named in bus.md F.3 (the RI MultiBank field, the RI's own bank tracking, SysAD or MI behavior) are not in a device datasheet. They need the console run.
