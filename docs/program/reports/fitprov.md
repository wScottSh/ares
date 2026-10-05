# fitprov report

Status: done. Branch feat/fitprov, head 58a53b96ca9fbb48ed2668d3d688f973efe27685, PR https://github.com/wScottSh/ares/pull/53 (base master 4f1c6d97f).

## Changes
- behaviors.tsv: new `fit-from` column (after verify). Filled for all 5 fit rows:
  - ri.overhead-read: bench:sp-dma-sweep
  - ri.overhead-write: bench:mi-memset-rspdma bench:sp-dma-sweep
  - rdp.primitive-base, rdp.span-dead-pixels, rdp.span-line-gap: thar0:alpha-fail-1cycle thar0:alpha-fail-2cycle
- No value changes. behaviors.hpp differs only in the note strings of those 5 rows. The struct is unchanged.
- behaviors.py --check fails on each of the following, and each message names the fix:
  - a fit row with an empty fit-from;
  - a fit row with no independent deciding check (outside fit-from, not a report or a pending gate) and no `verify-is-fit: <reason>` note prefix;
  - a stale verify-is-fit flag beside an independent check;
  - fit-from or the flag on a row that is not a fit row;
  - a fit-from id that is not defined.
- The spec Checks cell shows "(fit from ...)". Flagged rows are labeled "**fit only, no independent check:**".
- All 5 fit rows are flagged, each with a reason. Measured or cited:
  - Thar0 92/93 have the same hardware values as 84/85, so they are the same compute-only rectangle.
  - The other configs need memory time (t12: 4 of 100 in band).
  - bench:rdp-rectn is kind=report.
  - The hcs64 read point is a report.
  - The sp-dma-sweep write check is the same n64brew 6.5 B/rclk number as mi-memset-rspdma.
- The span-dead-pixels note says the n64brew dead cycle supports existence (1 slot), not the magnitude 2.
- README and docstring updated.

## Check list
- --self-test --check: pass. 20 cases ok plus `check: ok` (base: 16 ok). Raw: n64-timing/results/fitprov/{before,after}/selftest.txt.
- Negative cases fail as required (4 new self-test cases). Mutation: disabling the circular rule made 3 cases FAILED; making `decides` always true made 2 FAILED.
- Build green: build.sh with dir build/fitprov. The n64-timing-gen step printed `behaviors.py: check: ok`.
- det unchanged:
  - before: PASS, 27 files, 8307 fields.
  - after: PASS, 27 files, 8307 fields.
  - Cross-build run1 compared with run1: 34 files. 27 are identical. The 7 rdp.txt files differ only in host-time fields (ns_per_*, render_ms). Raw: results/fitprov/crossbuild.txt.
- MM wall time: det script 349 s before, 348 s after. mmbench wall_s total 174.0 before, 173.2 after. Both builds ran on the same host at once.
- Not run: nemu64, stepcap, thar0. No emulation code or constant changed.

## DEVIATIONS
- The independent set excludes report-only and pending checks, a stricter rule than "verify ⊆ fit-from". Without it, rdp.primitive-base would pass on bench:rdp-rectn, which only reports.
- The flag is a note prefix, not a column. This mirrors the legacy note prefix and keeps the flag next to its reason.
- The ri.overhead-read/write rows were also flagged. The rule covers every fit row, and they are circular the same way.
- Commit trailer: the commit used the session's attribution line (Claude Opus 5.5) rather than the brief's plain `Co-Authored-By: Claude`.

## FOLLOW-UPS
- RDP fits need an asserted check at another rectangle size, or the cen64 RECTN data once its provenance is settled. T13 memory-time configs may decide them.
- ri overhead fits: no read-direction DMA rate is asserted anywhere.

## Next unit must know
- behaviors.tsv now has 8 columns. A new fit row needs fit-from, plus an independent check or a `verify-is-fit: <reason>` note.
- When a later unit adds a deciding check to a flagged row, --check fails until the flag is removed. That is intended.
