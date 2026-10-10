# Domain-2 PI read from the BSD registers: attempt, closed

Green-plan unit U-DOM2 (docs/design/green-plan.md section 4, P4; pending.md section 4). The unit asked for a PI bus read cost derived from the BSD_DOMx registers. The formula had to reproduce domain 1's measured 144 rclk with no fitted term before it could replace domain 2's legacy `pclk(250)` (ares/n64/pi/bus.hpp:66-68). It does not reproduce it. Domain 2 stays legacy (preference 7: do not invent parameters).

## Result

The best published formula gives 141 rclk for the systembench PI I/O R reading. Hardware reads 144 rclk. The 3 rclk gap is outside both pass rules that check this number:

- systembench's own rule allows 1 CPU or 2 RCP cycles, or 0.2 % (tools/n64-timing/systembench/rows.tsv, questions.tsv `systembench`).
- `bench:pi-io-read` allows 142..146 rclk (docs/spec/n64-timing-results.tsv:15).

Closing the gap needs a 3 rclk term that no reference names. That is a fit, so the unit stops at step 2.

## Terms and their sources

| Term | Value for domain 1 | Source |
|---|---|---|
| LAT | RCP cycles minus 1 after the address is sent; retail 0x40 | n64brew Peripheral_Interface, BSD_DOMn_LAT (cited) |
| PWD | RCP cycles minus 1 that /RD is held low; retail 0x12 | n64brew Peripheral_Interface, BSD_DOMn_PWD (cited) |
| RLS | RCP cycles minus 1 that /RD is held high; retail 3 | n64brew Peripheral_Interface, BSD_DOMn_RLS (cited) |
| PGS | page size 2^(PGS+2) B; retail 7 | n64brew Peripheral_Interface. "Page Size only matters for DMA transfers; all direct accesses via the PI are only ever 32 bits wide" (cited). Not a term of a word read. |
| Address phase | 14 + (LAT+1) rclk | research/dma-timing.md:19, 51 (the DMA page-setup term, `pi.page-setup`). n64brew gives the 14 only as a minimum: /ALEL "will be high for at least 14 FSB cycles, each time a new address is loaded" (cited). |
| Halfword | (PWD+1) + (RLS+1) rclk, two per word | research/dma-timing.md:20, 51 (`pi.halfword-bias`) |
| CPU side | 22 pclk | `cpu.rcp-register-read`, measured from systembench VI_CONTROL (ares/n64/timing/behaviors.tsv:68). No published reference splits the SysAD round trip of a PI read from an RCP register read. Using this value is itself an assumption (inferred). |
| Harness | 2 pclk | the same harness `cpu.pi-io-read` subtracts (behaviors.tsv:70) |
| Measured total | 144 rclk | n64-systembench main.c PI I/O R (cited); the fork reads 144 under `systembench:pi-io-r` (results.tsv:185) |

n64brew gives no cycle count for a direct (non-DMA) read and no domain-2 timing (cited, page read 2026-10-10).

## Arithmetic

Retail domain 1 is LAT 0x40, PWD 0x12, RLS 3 (research/dma-timing.md:22). One rclk is 1.5 pclk.

| Variant | Bus (rclk) | + CPU side + harness (rclk) | vs 144 |
|---|---|---|---|
| A. 14 + LAT+1 address, 2 halfwords (dma-timing.md formula) | 79 + 46 = 125 | 141.0 | -3.0 |
| B. LAT address only (MiSTer `PI.vhd:598`, per dma-timing.md:142) | 64 + 46 = 110 | 126.0 | -18.0 |
| C. LAT+1 address only | 65 + 46 = 111 | 127.0 | -17.0 |
| D. A without the trailing RLS | 121 | 137.0 | -7.0 |

Variant A is the only one that comes near, and it misses by 3 rclk. Every variant lands below hardware. The same formula also runs short on small PI DMAs: the model misses 12 rclk at 8-31 B (questions.tsv `pi-dma-small`, cited). That a shared per-access term is missing from the formula is inferred. No reference names it.

The numbers come from this command (computed, not run on the emulator):

```
python3 -I -c "
from fractions import Fraction as F
p=F(2,3); side=24*p
for name,addr in [('A',14+0x40+1),('B',0x40),('C',0x40+1)]:
  print(name, float(addr+2*(0x12+1+3+1)+side))
print('D', float(14+0x40+1+2*(0x12+1)+(3+1)+side))"
```

## What domain 2 would get (not applied)

With the kit's domain-2 timing, LAT 5, PWD 12, RLS 2 (questions.tsv `dom2-read`), variant A gives 20 + 32 = 52 rclk on the bus plus 22 pclk, about 100 pclk. MM's flash timing is LAT 5, PWD 0x0C, RLS 2 (decomp include/PR/os_flash.h:11-14, per dma-timing.md:104), which gives the same 100 pclk. The legacy charge is 250 pclk. That figure is for information only. It inherits variant A's unexplained 3 rclk shortfall on domain 1, so it is not built.

## What would decide it

`hw:dom2-read` (calibration run #16) measures an uncached domain-2 word read on a console. That is hardware-only (preference 7). With that reading and the existing domain-1 reading, the missing term could be checked against two points instead of fitted to one.
