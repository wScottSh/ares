# cen64 jgemu dpc_probe measurements

Research for #25 (Obtain cen64-jgemu RDP span measurement data).

Source: full clone of https://gitlab.com/jgemu/cen64 at `2f8d7bc` (2026-09-26), 1,752 commits. The clone used for #2 was shallow, so it showed only the surviving comment.

## TL;DR

- The probe ROM, its source, and the raw tables are not in the repository or its history. No other project in the `jgemu` GitLab group contains them. The cen64 GitLab project has no issues or merge requests that mention them.
- Rupert Carmichael (GitLab `carmiker`) wrote all of the measurement commits. Contact is still needed.
- History holds two more hardware-measured laws from the same `dpc_probe` tool. Both were added on 2026-07-24 and reverted on 2026-08-06. The span law from #2 was not reverted.

## Commits

| Commit | Date | Content |
|---|---|---|
| `0f388bb` | 2026-07-24 | Fixes a phantom span in the emulator's cycle accounting. Names "the dpc_probe emulator and hardware tables": RECTN read 2357 in the emulator and 2021 on hardware. |
| `30c2459` | 2026-07-24 | Span law `14 + Σ(pixel_cycles·129/128 + 12)`. Still at `src/rdp/rdp_core.c:5346-5362`. |
| `50c9a7f` | 2026-07-24 | TMEM load law and setter cost. See below. |
| `abc292f` | 2026-08-06 | Reverts `50c9a7f`. Message: "These were based on values from real hardware, but the testing methodology needs to be verified, and the changes do verifiably break Tetris 64 (J)." |

## Reverted laws

These come from the same tool, so they carry the same provenance as the span law.

- **TMEM load.** The LOADSZ sweep used RGBA16 `load_block` with 256 to 2048 texels. It measured `42.6 + 0.832/texel` cycles per load, including the paired Sync Load. Without the sync's 25 cycles, that is about 15 fixed plus 0.418 cycles per byte. That is 3.3 times slower than the documented 8 B/clk, which #2 records as the TMEM load rate. The TILES test's TMEM counter supports it: 219502 cycles over 158 loads is 1389 per load, or 1696 texels × 0.82. Load Tile and TLUT were not measured.
- **Setters and NOP.** The SETTER sweep measured 2.68 cycles per one-word command, including fetch: (11135 − 170) / 4096. #2 records 1 cycle, from n64brew.

## Consequences for the map

- The span law and the reverted laws come from the same tool and runs. The author's doubt about the methodology may apply to the span law as well. Nothing in the repository says whether it does.
- If the load law holds, #2's "TMEM load 8 B/clk" is wrong by 3.3 times. Under the map's rule that a behavior is built from its references, this needs the author's answer or our own measurement (#16) before the RDP spec uses either rate.
- The Tetris 64 (J) breakage shows only that the emulator's timing changed. It does not show that the measurement was wrong.

## Questions for the author

1. The `dpc_probe` ROM and its source, and the raw tables for RECTW, RECTH, RECTN, SPAN, DUTY, LOADSZ, SETTER, and TILES.
2. Which counter was read: `DPC_CLOCK`, `DPC_BUFBUSY`, `DPC_PIPEBUSY`, or `DPC_TMEM`. How start and end were bracketed: from the `DPC_END` write to `END_VALID` clear, or something else.
3. The othermodes: Z compare and update, `IM_RD`, color image size, and the framebuffer and Z addresses.
4. The console: model, region, board revision, and whether an Expansion Pak was installed.
5. The methodology concern behind `abc292f`, and whether it also applies to the span law.
