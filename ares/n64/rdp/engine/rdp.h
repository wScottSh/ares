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
 * Registers. dp_regs is an array of RDP_NUM_DP_REGISTERS words indexed by
 * enum rdp_dp_register and owned by the host. The renderer reads
 * START/CURRENT/END/STATUS, and writes back CURRENT, the two 24-bit
 * masked address registers, and the STATUS bits it changed. It does not
 * model the register block, and never reads or writes CLOCK, BUFBUSY,
 * PIPEBUSY or TMEM.
 *
 * Serialization. The renderer owns its span workers and no other threads.
 * No entry point below is internally synchronized: the host must exclude
 * concurrent callers, and must hold whatever lock serializes its command
 * producer across the second fence stage (see below). dp_interrupt is
 * invoked on whichever thread retires Sync_Full. */
#define RDP_RDRAM_SIZE 0x800000u
#define RDP_DMEM_SIZE  0x1000u

/* Timed DPC engine. Default on; build with -DRDP_DP_TIMED=0 for the
   instantaneous at-END walk, which retires a whole command list inside
   rdp_process_list instead of dispatching against elapsed time. The two
   paths are an A/B for the hardware validation pass and differ in
   observable timing, not in pixels. */
#ifndef RDP_DP_TIMED
#define RDP_DP_TIMED 0  /* ares port: the DPC front end is ares' (T12 adds time) */
#endif

// DP register indices, in MMIO address order (0x0410_0000 base, offset >> 2).
// DP_REGISTER_LIST in rdp/cpu.h must match this ordering.
enum rdp_dp_register {
  RDP_DPC_START_REG,
  RDP_DPC_END_REG,
  RDP_DPC_CURRENT_REG,
  RDP_DPC_STATUS_REG,
  RDP_DPC_CLOCK_REG,
  RDP_DPC_BUFBUSY_REG,
  RDP_DPC_PIPEBUSY_REG,
  RDP_DPC_TMEM_REG,
  RDP_NUM_DP_REGISTERS,
};

// Initializes the renderer. The host contract above governs the lifetime,
// size and serialization requirements on these arguments.
//   rdram:        RDRAM block of rdram_size bytes (uint32_t view), in
//                 ares' word-swizzled layout (rdp_core.h)
//   hidden:       hidden-bit plane, rdram_size / 2 bytes (ares HiddenRAM)
//   dmem:         RDP_DMEM_SIZE-byte RSP DMEM block (uint32_t view); the
//                 command source for XBUS transfers
//   dp_regs:      RDP_NUM_DP_REGISTERS-word DP register array
//   dp_interrupt: invoked on Sync_Full, after all outstanding render work
//                 has been flushed to RDRAM
//   opaque:       passed through to dp_interrupt
// Returns 0 on success.
int rdp_render_init(uint32_t *rdram, uint32_t rdram_size, uint8_t *hidden,
  uint32_t *dmem, uint32_t *dp_regs,
  void (*dp_interrupt)(void *opaque), void *opaque);

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

/* Timed DPC engine glue; the host drives these with its command producer
 * excluded. need = 64-bit words required to complete the next command (0 = a
 * command is ready to step); feed fetches nwords from RDRAM (or DMEM
 * when xbus) into the command accumulator; step dispatches one command
 * and reports its occupancy in GCLK cycles plus its class (0 normal,
 * 1 TMEM load, 2 Sync_Full), returning 1 on dispatch, 0 when starved,
 * -1 when the pipeline is crashed. full_sync invokes dp_interrupt.
 * active reports whether the engine owns dispatch (RDP_DP_TIMED). */
int      rdp_render_engine_active(void);
unsigned rdp_render_engine_need(void);
unsigned rdp_render_engine_room(void);
int      rdp_render_crashed(void);
void     rdp_render_engine_feed(uint32_t address, unsigned nwords, uint32_t xbus);
int      rdp_render_engine_step(uint32_t *cycles, unsigned *cls);
void     rdp_render_engine_full_sync(void);

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

// Processes the command list delimited by DPC_CURRENT_REG..DPC_END_REG,
// in full at the call. Untimed path; not used when the engine is active.
void rdp_process_list(void);

#endif
