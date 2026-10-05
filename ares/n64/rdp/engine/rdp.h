/*
Copyright (c) 2026 Rupert Carmichael
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

#ifndef RDP_H
#define RDP_H

#include <stddef.h>
#include <stdint.h>

// SW4gbm9taW5lIFBhdHJpcywgZXQgRmlsaWksIGV0IFNwaXJpdHVzIFNhbmN0aQ==
/* Host contract.
 *
 * Memory. rdram and dmem are raw byte arrays in N64 byte order, viewed as
 * uint32_t; the renderer byteswaps on word access and applies the host
 * sub-word XOR from common/endian.h. RDP_RDRAM_SIZE bytes of RDRAM and
 * RDP_DMEM_SIZE bytes of DMEM must be mapped, and both blocks must remain
 * valid and fixed until rdp_render_destroy. A command list may legally
 * address past installed RDRAM, so accesses beyond RDP_RDRAM_SIZE are
 * range checked rather than faulted: reads return 0, writes are dropped.
 * No alignment beyond uint32_t is assumed -- doubleword fetch goes
 * through the byte view.
 *
 * Registers. The renderer never reads or writes the DPC registers; the
 * host owns them and feeds command words (rdp_render_engine_feed).
 *
 * Serialization. The renderer owns its span workers and no other threads.
 * No entry point below is internally synchronized: the host must exclude
 * concurrent callers, and must hold whatever lock serializes its command
 * producer across the second fence stage (see below). */
#define RDP_RDRAM_SIZE 0x800000u
#define RDP_DMEM_SIZE  0x1000u

// Initializes the renderer. The host contract above governs the lifetime,
// size and serialization requirements on these arguments.
//   rdram:        RDRAM block of rdram_size bytes (uint32_t view), in
//                 ares' word-swizzled layout (rdp_core.h)
//   hidden:       hidden-bit plane, rdram_size / 2 bytes (ares HiddenRAM)
//   dmem:         RDP_DMEM_SIZE-byte RSP DMEM block (uint32_t view); the
//                 command source for XBUS transfers
// Returns 0 on success.
int rdp_render_init(uint32_t *rdram, uint32_t rdram_size, uint8_t *hidden,
  uint32_t *dmem);

// Log sink for the renderer's cen64_log calls. Defaults to stderr.
enum cen64_loglevel {
  CEN64_LOG_DBG,
  CEN64_LOG_INF,
  CEN64_LOG_WRN,
  CEN64_LOG_ERR,
  CEN64_LOG_SCR
};
void rdp_render_set_log(void (*log)(int level, const char *fmt, ...));

// Pixels rasterized since init (clipped span widths summed over every
// queued primitive), for the ns/pixel measurement.
uint64_t rdp_render_pixel_count(void);

// Tears down the renderer and joins its worker threads.
void rdp_render_destroy(void);

/* A fence normally skips the drain when the host's address range does not
 * overlap the range the renderer is currently writing. Passing 0 here
 * turns that range check off, so every access drains whenever any work is
 * pending -- slower, and a bisect for tearing: a tear that survives with
 * the check off means a host fence call site is missing entirely, while a
 * tear that only appears with the check on means the renderer advertised
 * a range narrower than it wrote. On by default; independent of init, so
 * a host may set it either side of rdp_render_init, and it survives
 * rdp_render_destroy. */
void rdp_render_set_fence_range_check(int on);

/* Observation fences. Rendering is asynchronous: Sync_Full raises the DP
 * interrupt without draining, so any host access to RDRAM bytes queued
 * span work may still be writing must fence first. Two stages:
 *
 *   1. rdp_fence_needed(addr, len), unlocked -- a couple of atomic loads,
 *      and the whole per-access cost when nothing overlaps.
 *   2. rdp_fence(addr, len), or rdp_fence_all() where no range applies,
 *      with the host's command producer excluded.
 *
 * Stage 2's exclusion is a precondition, not an optimization: the drain
 * resets the poly pools and consumes the pending flag, which is unsound
 * while a command walk can enqueue concurrently. */
int  rdp_fence_needed(uint32_t addr, uint32_t len);
void rdp_fence(uint32_t addr, uint32_t len);
void rdp_fence_all(void);

/* What one dispatched command asked of the pipeline. The engine reports
 * work, not time: the host's timing model turns it into clocks. pixels and
 * lines are the clipped spans the primitive walked (rdp_occ_accumulate);
 * words is the 64-bit words those spans cover in fill and copy mode;
 * load_bytes is what a TMEM load moves. */
typedef struct rdp_engine_work {
  uint64_t word;        /* the command's first word */
  uint32_t command;     /* opcode, 0x00-0x3f */
  uint32_t cycle_type;  /* other modes cycle type at dispatch: 0 1-cycle, 1 2-cycle, 2 copy, 3 fill */
  uint32_t pixels;
  uint32_t words;
  uint32_t lines;
  uint32_t load_bytes;
} rdp_engine_work;

/* Timed DPC engine glue. need = 64-bit words required to complete the next
 * command (0 = a command is ready to step); buffered = words waiting in the
 * command accumulator (the host's command FIFO); feed fetches nwords from RDRAM (or DMEM when xbus)
 * into it; step dispatches the next command plus any commands an unsynced
 * write hazard draws into it, filling one work entry per command, and
 * returns the count, 0 when starved, or -1 when the pipeline is crashed
 * (rdp.c has the contract). */
unsigned rdp_render_engine_need(void);
unsigned rdp_render_engine_buffered(void);
int      rdp_render_crashed(void);
void     rdp_render_engine_feed(uint32_t address, unsigned nwords, uint32_t xbus);
int      rdp_render_engine_step(rdp_engine_work *works, unsigned capacity);

/* VI scanout support: copy `n` consecutive entries of the renderer's
 * hidden coverage plane (2 bits per 16-bit framebuffer word) starting at
 * idx16 into dst. idx16 is the 16-bit-word index, i.e. (byte address >>
 * 1) -- the same convention the span writers use. The caller must have
 * fenced the framebuffer region first (the same drain that stabilizes
 * the color bytes stabilizes the hidden plane). */
void rdp_hidden_read_row(uint32_t idx16, uint32_t n, uint8_t *dst);

/* Base of the hidden ("9th" bit) plane, or NULL outside init..destroy.
 * Hosts cache it once after init rather than calling per access. */
uint8_t *rdp_hidden_plane(void);

/* DPS Test-Mode span buffer (model at rdp_dps_model_t in rdp_core.h).
 * arm: a DPS register write occurred; the renderer models the
 * CPU-visible window on every eligible primitive (sticky; unarmed
 * costs one branch per triangle). take: with a modeled draw pending,
 * fences the workers, composes the post-draw 32-word window over
 * `words` (the host's stored buffer, supplying the prefill under
 * untouched slots), clears the draw, returns 1; else returns 0 with
 * `words` untouched. Callers exclude the command producer (the fence
 * precondition above); the draw also zeroes reads of words 32..127,
 * applied by the host from the return value. */
void rdp_render_dps_arm(void);
int  rdp_render_dps_take(uint32_t words[32]);

// Save states: the live renderer instance (NULL before init or with a
// non-soft backend), and the pre-serialization quiesce: closes the
// SetEnvColor hazard window and drains the span workers so RDRAM, the
// hidden plane, and TMEM are settled.
struct rdp_t *rdp_render_instance(void);
void rdp_render_quiesce(void);

/* ares port: save states. Visits every piece of renderer state that
 * outlives a command (modes, colors, tiles, scissor, TMEM, the buffered
 * command words, the held hazard primitives, the noise counter, the
 * stale-read and DPS models) in a fixed order, passing each block to io.
 * With loading set, io fills the blocks and TMEM lands in pool slot zero.
 * Saving never mutates the renderer. */
typedef void (*rdp_state_io)(void *ctx, void *data, size_t size);
void rdp_render_serialize(rdp_state_io io, void *ctx, int loading);

/* ares port: the last Set_Color_Image and Set_Mask_Image addresses, and
 * the 4 KB TMEM image the next primitive samples. */
uint32_t rdp_render_color_image(void);
uint32_t rdp_render_mask_image(void);
uint8_t *rdp_render_tmem(void);

#endif
