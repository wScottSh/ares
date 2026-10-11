# Literal span RAM halves: built, measured, closed (U-SPANRAM)

Green-plan unit U-SPANRAM (`docs/design/green-plan.md` section 4, P3). The unit built span RAM as two literal 64 B halves per image, as `span-ram.md` describes, and closed without landing. The code is on branch `feat/u-spanram` (head 1068b861f, closed draft PR [#133](https://github.com/wScottSh/ares/pull/133)). Master keeps `rdp.span-slots` (model-choice) and the whole-span window snapshot.

Labels: measured (a run, raw file named), cited (file:line or doc), inferred, guess. Raw files are under `~/n64-timing/results/u-spanram` (the unit's runs) and `~/n64-timing/results/verify-133` (the independent verifier's runs, own builds).

## Result

The cited structure, with no new fitted constant, moves the named F3 check away from its band. It also turns `mm:filesel-empty` and `noise:rect-1016` from pass to fail. The F3 miss does not come from the extra rules the build needed: with the write gate removed, F3 still moves away (verify-133, measured). Literal halves leave the 2-cycle Z read fully hidden behind shading, so they cannot produce the partial exposure the console shows. `green-plan/rdp.md`'s guess that U-SPANRAM brings the 2-cycle Z family under 3% is refuted.

## What was built

- Each image (color, Z) has a stream of half instances. Instance n lives in half n & 1 (cited, span-ram.md rows 3-5: two 64 B halves alternating, packed across spans).
- Spans are admitted once their first half is usable, and each span is cut into one segment per half instance it touches.
- A segment's read posts when its half is usable. One read per image is in flight, as on master.
- A chunk starts shading when its half is usable and its read has landed.
- Content stays exact per pixel: a span is drawn again from landed bytes whenever later pixels need writing back. snapper 2592/2592, rdpstat, det, stepcap and the state round trip are unchanged or pass (measured, u-spanram report).
- `rdp.span-slots` is removed. `rdp.span-ram-half` (64 B, cited) bounds run-ahead instead.

The build needed four rules that no reference states (verify-133 found each in the diff):

| Rule | What it does | Reference |
|---|---|---|
| n-2 drain write gate | instance n becomes usable only once instance n-2 has drained: shaded, and its write-backs landed (`dataEnd`, RI wire time). A chunk also waits for its half's previous instance to drain | none; span-ram.md row 8 states only the stall condition, as [inference] |
| fill/copy wait | fill and copy spans run once the previous span's writes are posted | none; chosen from span-ram.md row 13 ("committed straight to RDRAM") because run-ahead needed a bound once span-slots was gone (130 fill spans queued without one, measured) |
| span start floor | a span starts no earlier than its admission | none; it existed on master as `slot.ready` = prefetch time, and keeps the 1PRIMITIVE barrier |
| ring sizes | span ring 2 x rdp.span-ram-half + 2 = 130 entries (the most 1+ px spans two halves hold at 8 bpp); 256 segments per image | sizing only; binds only for runs of 0 px spans |

## Before and after

Before is master bde8d6119 (with map-1-closure-draft.md regenerated, the #125 + #127 race, no code change). After is 1068b861f. All numbers measured.

Thar0 mean |residual| of BUF avg per family. Families are `green-plan/rdp.md`'s; F3 is rdp.md's index list, F3all every 2-cycle Z_CMP config. Raw: `u-spanram/families.py u-spanram/before/thar0/compare.tsv u-spanram/after/thar0/compare.tsv` (rerun for this doc, same output).

| Family | n | Before | After |
|---|---|---|---|
| F1 | 6 | 3.03% | 2.88% |
| F2 | 14 | 3.55% | 5.01% |
| F3 | 20 | 8.73% | 9.96% |
| F3all | 36 | 7.90% | 8.35% |
| F4 | 44 | 5.29% | 6.38% |
| F5 | 40 | 5.71% | 7.09% |
| all | 100 | 5.16% | 5.94% |

In band: 4 of 100 before and after.

Named checks. Raw: `u-spanram/{before,after}/thar0/compare.tsv`, scored in `u-spanram/{before,after}-results.tsv`.

| Check | Before | After |
|---|---|---|
| thar0:zbrw-fail-zbsame-visame-imrd-2cyc (F3, the acceptance check) | 199078, -4.68% | 190197, -8.94% (console 208861, 208473..209121) |
| thar0:imrd-1cycle | +8.07% | -9.49% |
| thar0:nozb-visep-imrd-1cyc | +4.05% | -12.78% |
| thar0:ac-zcmp-zbsep-vioff-imrd-1cyc | +2.43% | -7.10% |
| thar0:separate-bank | -0.19% | -2.98% |
| thar0:zbrw-pass-zbsep-visep-noimrd-1cyc | -5.28% | -7.05% |
| thar0:nozb-visame-noimrd-1cyc | -4.91% | -4.41% |
| thar0:zcmp | +2.54% | +2.27% |
| thar0:ac-zbsame-vioff-imrd-1cyc | +2.55% | +2.27% |
| mm:filesel-empty | pass, 1.0113 fields per game frame, 98.9% of 444 at 1 | **fail**, 1.0845, 91.5% of 414 at 1 |
| mm:filesel-named | fail, 1.6941, 69.4% of 353 at 2 | fail, 1.8833, 88.3% of 317 at 2 |
| mm:filesel-options | pass, 1.0000 | pass, 1.0000 |
| noise:rect-1016 | pass | **fail**: "pixels off the LFSRs at one clock per pixel" |
| rdpstat:1prim (8 px) | pass, 2 of 2 | pass, 2 of 2 |
| snapper | 2592/2592 | 2592/2592 |

All nine thar0 named checks fail before and after. The scored results change on exactly two lines, `mm:filesel-empty` and `noise:rect-1016` (diff of `u-spanram/before-results.tsv` and `after-results.tsv`). Counts: pass 90 to 88, fail 21 to 23; consistent-only 2, pass-conditional:#77 1, pending:calibration-16 85 and pending:report-only 18 are unchanged.

Stale-read width sweep (20 cases, 8-256 px, both cycle modes, raw `u-spanram/stale-width-sweep.txt`): master reads stale at every width and fails 14 of 20; the halves read stale at 8-48 px, fresh from 64 px, and fail 4 of 20. The snapshot no longer covers a whole span.

Wall time, MM 600 fields, runners copied to fresh files, interleaved (raw `u-spanram/wall.tsv`, one run per binary per pair, phase spread not walked):

| Pair | Base | Head | 1-min load before base .. after head |
|---|---|---|---|
| 1 | 29.9 s | 44.2 s | 36.3 .. 32.7 |
| 2 | 23.6 s | 38.4 s | 32.7 .. 27.7 |
| 3 | 25.7 s | 37.9 s | 27.7 .. 25.6 |

Head is about 14 s (55%) slower, inside the 120 s budget. The cost is the redraws: mm600 render_ms 5316 to 16332 (measured, u-spanram report).

## Which rule causes which change (verify-133)

verify-133 built an env-gated copy of head and switched each unreferenced rule off in turn (measured, raw `verify-133/var-{a,b,c}/{thar0.txt,noise.txt,compare.tsv}`; var-c is head as control).

| Variant | noise:rect-1016 | F3 check (model BUF avg) | Thar0 mean | thar0:imrd-1cycle |
|---|---|---|---|---|
| head (var-c) | fail | 190197.4, -8.94% | 5.94% | -9.49% |
| no fill/copy wait (var-a) | fail | 190208.6, -8.94% | not scored | -9.49% |
| no write gate (var-b) | pass | 192716.7, -7.73% | 5.74% | +9.09% |

- The fill/copy wait changes nothing measurable.
- The write gate causes the `noise:rect-1016` fail and the 1-cycle IM_RD sign flip. Inferred cause: under the fitted `rdp.mem-overhead-write` (19.5) plus wire, a 64 B write holds the port for about 28.5 rclk, but a 32 bpp half fills in 16 clocks. Gated on its write-back, a write-only 32 bpp span stalls, and the console's noise pixels show it does not. In 1-cycle IM_RD the next half's read now waits behind the previous half's write-back, so the line becomes port-bound at about 60 rclk per half (inferred from the per-op costs).
- With the gate off, MM file select reads 1.6447 fields per game frame (measured, `verify-133/var-b/mmbench`). Content accounting was not tested with the gate off, so treat that number as indicative only.
- The F3 miss is independent of the write gate: F3 moves away from the band in every variant.

## Why the F3 check cannot move with literal halves

Config 13 (zbr-fail-zbsame-vioff-noimrd-2cyc, a 2-cycle line that reads only Z and writes nothing) reads 155089 rclk on the model after, 155493 before, and 176339 on the console (BUF avg; measured, `u-spanram/{before,after}/thar0/compare.tsv` row 13). The after gap is 21250 rclk, 88.5 rclk per line over 240 lines, about 8.9 rclk per 64 B Z half (10 halves per 320 px line at 16 bpp). The model exposes none.

In 2-cycle a 64 B Z half shades in 64 clocks (32 px x 2). One read costs about 44 rclk: wire 10.5 + `rdp.mem-overhead-read` 21 + `rdp.span-read-latency` 12.5 (inferred from the fit rows). With one read per image in flight and a read posted as soon as its half is usable, half 2's read lands inside half 1's shading, so every read but the first is hidden. kit-zmem zmem-read2 shows the same on the model (measured, raw `u-spanram/zmem2cyc.tsv`): the per-line cost at 320 px, from 16 lines less 8, is 645.4 rclk after against 645.25 before, and only the once-per-rectangle cost moves.

Literal halves therefore cannot produce a partial 2-cycle Z exposure. Whatever the console spends there (734.7 rclk per Z-read-only line against 659.0 per color-read-only line, cited `green-plan/rdp.md` F3 row) needs a mechanism no reference names yet.

## Why the unit closed

Plan acceptance item 1 requires the F3 check to move toward its band; it moves away, and that failure belongs to the cited read structure itself, not to the extra rules. Getting `mm:filesel-empty` and `noise:rect-1016` back would need a refit of the write overhead (forbidden: plan section 8, pref 21) or an unreferenced write buffer (pref 7). The fits made under span-slots (`rdp.mem-overhead-read`, `-write`, `rdp.span-read-latency`, `rdp.port-lookahead`) were not re-derived under the new structure, because the only data to re-derive them from is the data that checks them.

## What the console run should decide

Two choices could remove the write-gate regressions without a refit. Neither is referenced and neither was built:

- write-back released per 16 B segment rather than per 64 B half (span-ram.md row 6 and open question 4);
- memory overhead modeled as pipelined latency rather than port occupancy.

Both are #16 items (`item:16.span-write-release`, `item:16.mem-overhead-pipelined` in `tools/n64-timing/calibration/items.tsv`). The older kit points constrain them but do not separate them. Kit ROM `kit-span2` (U-SPAN-KIT) adds the points that do, under two questions in `tools/n64-timing/calibration/questions.tsv`:

- `span-write-release`: 256-line write-only 1-cycle rectangles at every width 1-80 px, at 32 and 16 bpp. Each answer is one category, the spacing of DPC_CLOCK's stall steps: `segment` (4 px at 32 bpp), `half` (16 px), `no-step`, or `period-<px>` / `single-<width>`. The step threshold comes from the DPC_CLOCK poll and refresh bounds, not from the fork.
- `mem-overhead-pipelined`: the same rectangles with IM_RD, out to 320 px. The steady cost per 64 B half is compared with 21.6 rclk, the datasheet wire time of one read and one write-back. `wire-bound` refutes occupancy. `above-wire` is what occupancy predicts, but a pipelined RDP with too few halves to hide its latency would also read `above-wire`, so that answer alone does not decide.

The questions' rows give the derivations, and they say why span-width and kit-zmem's plain points cannot decide either question. The existing questions span-width, imrd-zcmp-slots(-2cyc) and zread-2cyc decide the half and ordering details around them.
