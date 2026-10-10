# Thar0 one-image read residual (thar0:zcmp, thar0:ac-zbsame-vioff-imrd-1cyc)

Green-plan unit U-THAR0-ZC (`docs/design/green-plan.md` section 4, P1). The two checks read +2.54% and +2.55% with the same model value, 108,697 rclk, and the plan placed them in no family F1-F5 (section 2, "RDP"). This doc measures where the model spends each read and what removing one cost term does. It does not settle which term the hardware lacks. It changes no timing value.

Labels: measured (I ran it, raw file named), cited (file:line), inferred, guess.

## Result

Both configs draw a 320x240 16 bpp rectangle that reads one image and writes nothing: zcmp reads Z (Z compare, alpha compare fails), ac-zbsame-vioff-imrd-1cyc reads color (IM_RD, alpha compare fails). Each line is 10 reads of 64 B, issued one after another, because `RDP::Port::eligible` allows one read per image in flight (cited, `ares/n64/rdp/timed.cpp`, `Port::eligible`).

- The model charges each of those reads 45.16 rclk. Hardware's figure is 44.17 rclk per 64 B: Thar0 BUF avg 106000.106 / 240 lines / 10 reads (cited, `expected.tsv` row 86; row 88 gives 105998.981, the same 44.17). It is a whole-run average, not a per-read measurement, so it also contains any per-rectangle term. The steady model line period is 451.55 rclk (measured, `decompose.tsv` rows 86 and 88).
- The 45.16 splits into wire 10.67 (10.5 hit + 0.17 for 0.31 row misses per line), `rdp.mem-overhead-read` 21, `rdp.span-read-latency` 12.5, and 0.98 rclk between the port's post and the RI grant (measured). The model's per-read cost exceeds the whole-run hardware average by about the post-to-grant rounding (0.98 rclk). That match does not make the hop the excess: the first three sum to 44.17 because `rdp.mem-overhead-read` (21) and `rdp.span-read-latency` (12.5) were grid-fit over the 60 VI-off Thar0 configs, these two among them, so an equal cut in `rdp.mem-overhead-read` fits these configs as well. If the model's 327 rclk once-per-rectangle term (below) is real on hardware, the hardware per-read figure is (106000 - 327) / 2400 = 43.9 (inferred).
- The 0.98 rclk is the post-to-grant hop. On a row hit a read lands on an rclk edge: its decision is on an edge, and 10.5 + 21 + 12.5 = 44 rclk. The next read posts at that time, reaches the arbiter `ri.request-latency` (1 unit) later, and `Channel::post` rounds the decision up to the next rclk edge (cited, `ares/n64/ri/bus.hpp`, `Channel::post`; `ares/n64/timing/clock.hpp`, `nextRclkEdge`). So each read pays one whole rclk that no fit row names, on top of the fit constants. Nothing else waits on the channel in these configs, so the full rclk lands on the critical path.
- **Counterfactual (measured).** A throwaway build that drops the 1-unit hop for `DpColor` and `DpDepth` posts only (`variant-q0.diff`) moves both configs by -9.68 rclk per line, from +11.24 to +1.55 rclk per line (+2.54% to +0.35%). The steady period drops from 451.55 to 441.86 rclk, against hardware's 441.67.

Attribution: undecided. The excess of both checks matches the post-to-grant rclk rounding on a self-serialized one-image read stream, 1 rclk per 64 B read, and removing that rounding removes most of it (measured). Thar0 cannot separate the hop, the fit constants and a per-rectangle term; `hw:span-width` and `hw:imrd-zcmp-slots` decide it (see the last section). It is not one of F1-F5. The fit rows (`rdp.mem-overhead-read`, `rdp.span-read-latency`) were chosen on a grid over all 60 VI-off configs (cited, `behaviors.tsv` note of those rows). Their own reference text says one-image reads "cost about 44 rclk per 64 B". In multi-stream configs another request is usually waiting when the channel frees, which hides the rounding there; how much of it the grid absorbed into the constants for one-image configs is what Thar0 cannot tell (inferred).

## The residual tracks the term across neighbours

Each neighbour differs from zcmp or ac-zbsame-vioff-imrd-1cyc in one factor. The delta column is the counterfactual's change (q0 minus master), in rclk per line. Raw: `contrast-q0.tsv`.

| idx | config | factor changed | hw/line | master res/line | q0 res/line | delta | master % | q0 % |
|---|---|---|---|---|---|---|---|---|
| 86 | ac-zcmp-zbsame-vioff-noimrd-1cyc (thar0:zcmp) | - | 441.67 | +11.24 | +1.55 | -9.68 | +2.54 | +0.35 |
| 88 | ac-zbsame-vioff-imrd-1cyc | - | 441.66 | +11.24 | +1.56 | -9.68 | +2.55 | +0.35 |
| 84 | ac-zbsame-vioff-noimrd-1cyc | no read | 324.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 94 | ac-zcmp-zbsep-vioff-noimrd-1cyc | Z in its own bank | 441.67 | +11.24 | +1.56 | -9.68 | +2.54 | +0.35 |
| 96 | ac-zbsep-vioff-imrd-1cyc | Z in its own bank | 441.66 | +11.25 | +1.57 | -9.68 | +2.55 | +0.35 |
| 12, 16 | zbr-fail-*-vioff-noimrd-1cyc | Z read via Z-fail, not alpha | 441.67 | +11.24 | +1.55 | -9.68 | +2.54 | +0.35 |
| 36, 40 | zbrw-fail-*-vioff-noimrd-1cyc | Z update on, all fail | 442.42 | +10.48 | +0.80 | -9.68 | +2.37 | +0.18 |
| 87 | ac-zcmp-zbsame-vioff-noimrd-2cyc | 2-cycle | 734.75 | -86.86 | -86.89 | -0.03 | -11.82 | -11.83 |
| 89 | ac-zbsame-vioff-imrd-2cyc | 2-cycle | 659.03 | -11.14 | -11.17 | -0.03 | -1.69 | -1.70 |
| 90 | ac-zcmp-zbsame-vioff-imrd-1cyc | both images read | 794.15 | +6.88 | -10.12 | -17.00 | +0.87 | -1.27 |
| 98 | ac-zcmp-zbsep-vioff-imrd-1cyc | both images, own banks | 693.13 | +16.83 | +11.46 | -5.37 | +2.43 | +1.65 |
| 52-64 | zbrw-fail-*-vi{sep,same}-noimrd-1cyc | VI on | 444.87-455.55 | +9.37..+15.23 | -0.95..+2.85 | -10.32..-12.37 | +2.06..+3.42 | -0.21..+0.64 |

- Every 1-cycle config that reads one image and writes nothing carries the same +10.5..+11.2 rclk per line with VI off. The counterfactual removes 9.68 of it in each, about 10 reads x 0.97 rclk.
- With no read (84) there is no term and no residual.
- In 2-cycle (87, 89) the line is compute-bound (646 rclk of shading against 452 of reads), so the hop is off the critical path. The counterfactual moves them 0.03. The 2-cycle Z residual is F3, as the plan says.
- With two read streams (90, 98) the counterfactual moves the result 5 to 17 rclk per line and overshoots on the same-bank config. Those configs are F2 (stream overlap order), and the hop is only one of the terms that compete there.

## What is left

After the counterfactual, both configs still sit +373 rclk (+0.35%) above hardware, outside a band about 0.14% wide (105,940..106,088). The steady period is 0.19 rclk per line above hardware's whole-run average (46 rclk over 240 lines). The other 327 rclk is a once-per-rectangle term (measured as model BUF minus 240 x period: 325 on master, 327 on q0). The likely cause is the first span's reads before shading starts plus the last span's shading (inferred). Thar0 has one rectangle size, so it cannot separate a hardware per-rectangle term from a per-line term. This remainder is unexplained.

## Why the checks stay failing

Removing the hop is not a fix this unit can make.

- It changes `ri.request-latency`, a model choice that exists so that a decision never races an equal-time post (cited, `behaviors.tsv` row `ri.request-latency`). No reference says when the RDP's next read issues relative to the previous landing.
- It moves every Thar0 config that the fit rows were chosen on: mean |residual| 5.16% to 5.37%, still 4 in band (measured, `contrast-q0.tsv` last line). Taking the hop out and then regridding the three mem constants would fit Thar0 to Thar0 again (plan section 8, pref 21).

The hardware question that decides it is in the kit. `imrd-zcmp-slots` and `span-width` (calibration #16) measure 1-cycle read cost against span width. A per-read cost of 44 vs 45 rclk at small widths separates this term from the per-rectangle term.

## Setup and reproduction

- Tree: origin/master 78b4427b8. Builds in `~/n64-timing/build/u-thar0-zc` (master plus `memlog.diff`) and `~/n64-timing/build/u-thar0-zc-q0` (plus `variant-q0.diff`). Raw outputs are in `~/n64-timing/results/u-thar0-zc/`.
- ROMs built from this tree with `romgen/build.py --suite thar0` (sha256 a01bcc95...ebcf7, identical to plan-rdp and the standing ROM) and with `--define RUNS=2` for the traces (sha256 6bbb0210...cc994).
- `memlog.diff` adds host-side logging behind `ARES_MEMLOG=<file>` and never changes emulation. Measured: the Thar0 `compare.tsv` of the master build, of the instrumented build without the variable, and plan-rdp's v0 are byte-identical.
- `decompose.py mem.tsv compare.tsv 2` gives `decompose.tsv`: the per-read wait, wire, overhead, latency and gap for each config. Its `match` column flags configs whose traced total differs from the model BUF by more than 0.1%. Those are zbrw-pass (Z state carries across runs at RUNS=2) and 4 VI-on configs (VI phase). None of the configs above is flagged.
- `contrast.py master/compare.tsv q0/compare.tsv` gives `contrast-q0.tsv`.
- Load average during runs: 92-107 on 32 cores. Emulated counts do not depend on host load.
