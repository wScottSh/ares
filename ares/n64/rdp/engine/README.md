# cen64-jgemu pixel engine

Software RDP rasterizer for the N64 core, ported from the cen64 jgemu fork
(`src/rdp` at commit `2f8d7bcdfa01814d4e296cdc4596bad5b04a4692`). MAME
lineage (Ryan Holtz and others), translated to C11 and fitted to snapper64
console captures by Rupert Carmichael. BSD-3-Clause; the notices stay in
every file, `LICENSE.cen64` and `LICENSES.cen64` are the fork's license
files, and the top-level `LICENSE` carries the block.

The engine is the N64 core's only rasterizer. It runs on the emulation
thread. The DPC front end (`../timed.cpp`) feeds it command words as the
command DMA lands them and steps one command per dispatch
(`rdp_render_engine_step`), which leaves the command's pixels in RDRAM
before returning. Build flag: `RDP_WQ_THREADS=1` (no worker threads; the
span queue drains on the caller). `RDP::power`
attaches it to `rdram.ram`, `rdram.hidden` (owned by `RDRAM`) and
`rsp.dmem`.

## Files dropped from the fork

- `cpu.c`, `cpu.h`, `interface.c`, `interface.h`: the cen64 bus glue
  (DPC and DPS register block, timed DPC engine, RDRAM fences). ares has
  its own register block in `../io.cpp`.
- `common/*`: replaced by `cen64_compat.h`.

## Changes from the verbatim import

The first commit of this directory is the unmodified copy; `git diff`
against it shows every change. In summary:

- `cen64_compat.h` stands in for `common/common.h`, `common/debug.h`
  and `common/endian.h` (little-endian host only).
- RDRAM accessors (`rdp_core.h`): ares stores RDRAM as native
  32-bit words with the bytes of each word swizzled (byte address `^ 3`,
  halfword index `^ 1`), the layout the MAME RDP was written for, so the
  `RREAD*`/`RWRITE*` macros index that way with no byteswap. Range checks
  use the installed RDRAM size passed to `rdp_render_init` instead of the
  8 MB constant (ares allocates 4 MB without the Expansion Pak).
- Hidden bits: `m_hidden_bits` is a pointer to ares' `HiddenRAM` plane
  (one byte per 16-bit word, bit 1 even byte, bit 0 odd byte, no swizzle)
  instead of an 8 MB array inside the renderer, so CPU and DMA writes and
  RDP writes maintain one plane. Direct `m_hidden_bits[... ^ XOR]` uses
  became `HREADADDR8`/`HWRITEADDR8`.
- `rdp_read_data`: command fetch is two word reads, native from RDRAM and
  byteswapped from DMEM, which ares stores as big-endian bytes (no atomic
  doubleword load; the renderer is single-threaded here).
- `rdp_z_store` and the fill-rect stale-read restore use the accessor
  macros instead of casting `m_rdram`.
- `rdp.c`: `rdp_render_init` takes the RDRAM size and hidden plane and
  no register block or interrupt callback; `m_async_on` is 0
  (synchronous: every dispatch settles before returning, so no fence is
  needed); `cen64_log` is defined here
  with `rdp_render_set_log`; `rdp_render_pixel_count` exposes the pixel
  counter added in `rdp_occ_accumulate`.
- `rdp.h`: `enum cen64_loglevel` lives here.
- Timed dispatch (plan T12): `rdp_engine_step` reports each command's
  work (`rdp_engine_work`: pixels, 64-bit words and spans walked, TMEM
  load bytes) instead of the fork's cycle law, which moved to
  `../timed.hpp` as behavior rows. `rdp_render_engine_step` resolves an
  unsynced-write hazard hold with the following commands already in the
  FIFO (`rdp_engine_hold_open`) and then settles (`rdp_engine_settle`), so
  no held primitive or queued span crosses emulated time. The untimed
  at-END walk (`rdp_process_list`, `rdp_process_command_list`) is
  deleted.
- Save states: `rdp_render_serialize` (`rdp.c`) visits the renderer state
  that outlives a command, after the field list of the fork's
  `src/device/state.c` `ss_render`; `../serialization.cpp` calls it.
  `rdp_render_color_image` and `rdp_render_mask_image` expose the last
  image addresses.

## RDRAM touch sites (for the timing-core memory interface, plan unit T13)

Every place the renderer reads or writes RDRAM or the hidden plane goes
through the `RREAD*`, `RWRITE*`, `HREADADDR8` and `HWRITEADDR8` macros in
`rdp_core.h`, plus `m_dmem[]` for XBUS command fetch. The functions, all
in `rdp_core.c`, with the macro-call line numbers at this commit:

| Function | Role | Lines |
|---|---|---|
| `rdp_read_data` | command fetch from RDRAM or DMEM (cen64's `read_rdram_pair` equivalent; the port has no bus) | 1358, 1364 |
| `rdp_z_store` | Z write and dz hidden bits | 1129-1130 |
| `rdp_z_decompress`, `rdp_dz_decompress`, `rdp_z_compare` | Z and dz reads | 1153, 1157-1158, 1228-1229 |
| `rdp_read_pixel8`, `rdp_read_pixel16`, `rdp_read_pixel32` | color image read (image_read_en); `rdp_read_pixel4` reads nothing | 5862, 5868, 5894, 5908 |
| `rdp_write_pixel4/8/16/32` | 1-cycle and 2-cycle color write with hidden coverage | 5728, 5749-5751, 5790-5798, 5819-5833 |
| `rdp_copy_pixel4/8/16/32` | copy-mode color write | 5934-5959 |
| `rdp_span_draw_fill`, `fill_write_word` | fill-mode writes (8/16/32 bpp runs and the byte-enabled burst law) | 7094-7095, 7321-7402 |
| `rdp_cmd_load_tlut`, `rdp_cmd_load_block`, `rdp_cmd_load_tile` | TMEM load source reads | 4119, 4230-4334, 4422-4484 |
| `rdp_fill_rect_stale_read` | rect pre-state capture and restore | 4609-4610, 4647 |

`rdp_texpipe.c` touches TMEM only. The hidden plane is also read by
`rdp_hidden_read_row` in `rdp.c` (VI support, unused by ares).
