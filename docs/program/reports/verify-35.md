## Verify PR #35 (T9 pixel engine port): PASS-WITH-NOTES

Independent run on head `7b2ce41cd` and base `feat/design` (`9136cea32`), each built fresh with `tools/n64-timing/build.sh` into `C:\Users\Scott\n64-timing\build\verify-35-{head,base}`. Raw outputs and scripts: `C:\Users\Scott\n64-timing\results\verify-35\` (`run-mm.sh`, `run-attrib.sh`, logs).

### License (BSD-3)
- Import commit `20e75e713` is byte-identical to jgcen64 `2f8d7bc` `src/rdp/*`, `LICENSE`, `LICENSES` for all 17 files (compared with CR stripped; the scratch checkout has CRLF).
- The leading notice block of all 15 imported source files is unchanged at head (md5 of the first comment block, import vs head).
- Copyright holders in file headers: Holtz; Crabb, Holtz; Linde, Giles; Carmichael. All appear in the block appended to `LICENSE`, together with Stachecki, Ryan, Benaim. `LICENSE.cen64` and `LICENSES.cen64` are kept.

### Determinism and timing (MM, 600 fields, interpreter)
| run | wall_s | stats.tsv md5 |
|---|---|---|
| soft 1 | 15.600 | b36ae7fe2ecac1a29fd73ce1fc3956f0 |
| soft 2 | 12.411 | b36ae7fe2ecac1a29fd73ce1fc3956f0 |
| vulkan 1 | 10.791 | e1e7a170d3a0a92039ba36648b4991fc |
| vulkan 2 | 11.374 | e1e7a170d3a0a92039ba36648b4991fc |
| none 1 | 10.620 | 07d7535d784c9d9efeb462fd1b43abb3 |
| base none | 16.956 | n/a (no rdp_pixels column) |
| base vulkan | 13.133 | n/a |

- The soft md5 matches the worker's `b36ae7fe...`. fb_hash takes 235 distinct values under soft and 4 under none.
- `cpu_cycles` and `rsp_busy_clocks` are identical per field across head soft, vulkan, none and base none, vulkan. Head none equals base none on all of columns 1-7, fb_hash included. Head vulkan equals base vulkan on every column, fb_hash included.
- Soft vs vulkan is identical on every column except fb_hash and rdp_pixels. Soft vs none also differs in `cimg`/`zimg`: the ares-side command parser that fills `rdp.set.*` is bypassed in soft mode, the same as in vulkan mode. These are diagnostic columns, not timing.
- mmbench sct `--rdp soft`, two runs: `fields.tsv`, `gframes.tsv`, `summary.tsv` and `sct/stats.tsv` are byte-identical.
- Host load was shared with other workers, so the wall times are noisy.

### MM frame diffs, soft vs vulkan (5 of the 20 fields)
| field | differing px | worker |
|---|---|---|
| 29 | 0 | 0 |
| 119 | 440 | 440 |
| 269 | 612 | 612 |
| 449 | 4456 | (in range) |
| 599 | 54192 (17.64%) | 54192 |

The vulkan f119 dump and the soft f599 dump are byte-identical to the worker's `after2` dumps.

I checked the attribution with the worker's instrumented binary (`build/t9-attrib`). Without toggles it produces dumps identical to the head soft dumps (f119, f599). Diffs against my vulkan dumps:

| toggle | f119 | f269 | f449 | f599 |
|---|---|---|---|---|
| none | 440 | 612 | 4456 | 54192 |
| ATTRIB_CUR_ALPHA_REF | **0** | 612 | 4456 | 54192 |
| ATTRIB_PRIMCOUNT_ALL | 440 | **0** | **0** | **0** |
| both | 0 | 0 | 0 | 0 |

Each toggle removes exactly the region attributed to it. I read the code paths:
- `rdp_core.c:6736-6751`, `6888`: the reference is the next pixel's cycle-0 alpha, citing n64brew.
- `rdp_core.c:64` (`rdp_seeded_noise`, a port of paraLLEl `noise.h reseed_noise`) and `rdp_core.c:5519`: the counter is incremented in `rdp_render_spans` after the clip early-return at `5484`.
- `git diff 20e75e713 7b2ce41cd -- ares/n64/rdp/engine` touches none of these sites.

### hydra (field 59, soft vs vulkan)
blender 42484 px (13.83%). With ATTRIB_ZERO_SHADE: **0**. overflowing_primitives 40 px. noise 0. The overflow cause is still inferred from the dumps, as the PR says; no toggle checks it.

### ns/px (host time inside rdp_process_list / clipped span px)
- MM intro: 89,477,643 px, 25.96 and 22.61 ns/px (worker 19.96-24.59).
- sct whole run: 104,032,250 px, 125,247 calls, 45.19 and 30.69 ns/px (worker 33.3 / 39.7 / 44.6). Window pixels 68,771,762, the same as the worker's.
- Pixel counts are exact matches. My ns/px figures fall in the worker's range on a loaded host. The min-of-runs estimate holds at about 30-33 ns/px for sct.

### RDRAM touch-site table
I mapped every `RREAD*`/`RWRITE*`/`HREADADDR8`/`HWRITEADDR8`/`m_rdram`/`m_dmem[]`/`m_hidden_bits` line in `rdp_core.c` (77 lines) to its enclosing function with awk. Each falls inside a listed row and line range. No other engine file touches RDRAM except `rdp.c`.

### Diff notes (non-blocking)
1. `ares/n64/rdp/engine/rdp.c:156`: `rdp_hidden_read_row` reads the hidden plane through `HREADADDR8` with a hardcoded `& 0x3FFFFF` (8 MB) mask. The table names only `rdp.c:245`, the pointer. It is unused by ares, but T13 should know this read exists.
2. Engine state (TMEM, tiles, modes) is not serialized. `rdp/serialization.cpp` is untouched, so a save state taken mid-frame in soft mode loses engine state. This is outside the plan, and n64-run does not use states.
3. `rdp_core.c:7312`: the stale upstream comment the worker already flagged.
4. Declared deviations (`rdp_pixels`, mmbench `--rdp`, `Software RDP` under `#if defined(VULKAN)`, the DPC status delta not fed back) match the code.

### Not rerun
- nemu64 suite. Instead, cpu_cycles and rsp_busy_clocks are identical base vs head per field.
- snapper items (pending R3).
- 15 of the 20 MM fields.
- 4 of the hydra tests (joined_primitives, weird_triangles, depth/peach, plus the second dump field).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
