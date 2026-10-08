# cen64-jgemu pixel engine

Software RDP rasterizer for the N64 core, ported from the cen64 jgemu fork
(`src/rdp` at commit `2f8d7bcdfa01814d4e296cdc4596bad5b04a4692`). MAME
lineage (Ryan Holtz and others), translated to C11 and fitted to snapper64
console captures by Rupert Carmichael. BSD-3-Clause; the notices stay in
every file, `LICENSE.cen64` and `LICENSES.cen64` are the fork's license
files, and the top-level `LICENSE` carries the block.

The engine is the N64 core's only rasterizer. It runs on the emulation
thread and touches no memory of its own (plan T13). The DPC front end
(`../timed.cpp`) feeds it command words as the command DMA's RI grants land
them and steps one command per dispatch (`rdp_render_engine_step`). A
primitive's spans wait in the poly pools; the front end runs each one
(`rdp_render_span_run`) when its snapshot reads have landed, against the
windows it installs (`rdp_render_set_windows`), and writes the written runs
back as RI bursts. A TMEM load runs once its source rows, planned by a dry
run (`rdp_render_load_plan`), have landed. `RDP::power` sizes it to the
installed RDRAM. Build flag: `RDP_WQ_THREADS=1` (no worker threads).

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
- `rdp.c`: `rdp_render_init` takes the installed RDRAM size and no
  register block or interrupt callback; `m_async_on` is 0 (loads and
  Sync Full keep their in-handler drains, which the front end makes empty
  first); `cen64_log` is defined here
  with `rdp_render_set_log`; `rdp_render_pixel_count` exposes the pixel
  counter added in `rdp_occ_accumulate`.
- `rdp.h`: `enum cen64_loglevel` lives here.
- Timed dispatch (plan T12): `rdp_engine_step` reports each command's
  work (`rdp_engine_work`: pixels, 64-bit words and spans walked, TMEM
  load bytes) instead of the fork's cycle law, which moved to
  `../timed.hpp` as behavior rows. `rdp_render_engine_step` resolves an
  unsynced-write hazard hold with the following commands already in the
  FIFO (`rdp_engine_hold_open`) and then publishes the held primitive's
  spans (`rdp_engine_publish`); since plan T13 queued spans cross emulated
  time and travel in save states. The untimed
  at-END walk (`rdp_process_list`, `rdp_process_command_list`) is
  deleted.
- Unsynced writes (plan T15): the 1-/2-cycle rectangle hold collects
  Set Combine, Set Other Modes and Set Tile as well as Set Env Color. Each
  register lands at its own pipeline stage (n64brew Pipeline table,
  `rdp_haz_stage_offset`), relative to the combiner's depth, which
  `rdp_render_init` takes from `rdp.pipeline-depth` instead of the fork's
  literal 25. A write records the register's new value in the hold
  (`rdp_haz_write`); the re-renders chain one object per landing pixel.
- Save states: `rdp_render_serialize` (`rdp.c`) visits the renderer state
  that outlives a command, after the field list of the fork's
  `src/device/state.c` `ss_render`; `../serialization.cpp` calls it.
  `rdp_render_color_image` and `rdp_render_mask_image` expose the last
  image addresses.

## RDRAM touch sites (plan T13: all redirected)

Every place the renderer reads or writes RDRAM or the hidden plane goes
through the `RREAD*`, `RWRITE*`, `HREADADDR8` and `HWRITEADDR8` macros in
`rdp_core.h`. They resolve against the installed windows (`rdp_memwin`):
snapshot bytes the RI filled at a read grant, with a written flag per byte
the front end cuts write-back runs from. An access outside every window
reads 0, is dropped, and counts in `rdp_render_mem_misses` (0 over the MM
bench). The sites:

| Function | Role | Now |
|---|---|---|
| `rdp_read_data` | command fetch | deleted: `rdp_engine_feed` takes the words a DpCommand grant (or the X bus) delivered |
| `rdp_z_store`, `rdp_z_decompress`, `rdp_dz_decompress`, `rdp_z_compare` | Z and dz | the span's Z window; dz ninth bits at the Z halfword's own index (was MAME's byte-address base) |
| `rdp_read_pixel*`, `rdp_write_pixel*`, `rdp_copy_pixel*` | color image | the span's color window |
| `rdp_span_draw_fill`, `fill_write_word` | fill writes | the span's color window, written back on DpFill |
| `rdp_cmd_load_tlut`, `rdp_cmd_load_block`, `rdp_cmd_load_tile` | TMEM load sources | the load's staged rows (DpTexture); a record-mode dry run plans them |
| `rdp_fill_rect_stale_read` | fitted stale-read restore | deleted: stale reads come from the bus order |

Save states carry the queued spans (`poly_manager_serialize`, pointers as
indices and offsets); pool items, aux records and span params are handed out
zeroed so the state bytes never depend on a slot's past.
