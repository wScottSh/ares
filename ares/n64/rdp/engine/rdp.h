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
 * Memory (ares port, plan T13). The renderer owns no memory view. The host
 * installs windows (rdp_memwin) before it runs a span or a TMEM load: byte
 * ranges an RI read grant filled, which the host's write-back bursts drain.
 * Command words arrive through rdp_render_engine_feed.
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

// Initializes the renderer for rdram_size bytes of installed RDRAM.
// Returns 0 on success.
int rdp_render_init(uint32_t rdram_size);

/* One RDRAM byte range as the renderer sees it. lo and hi are 8-aligned
 * byte addresses. data holds the bytes in ares' RDRAM layout (byte a at
 * data[(a - lo) ^ 3]), hidden the ninth bits (halfword a >> 1 at
 * hidden[(a - lo) >> 1]), written one flag per byte the renderer wrote
 * (written[a - lo]). */
typedef struct rdp_memwin
{
    uint32_t lo, hi;
    uint8_t *data;
    uint8_t *hidden;
    uint8_t *written;
} rdp_memwin;

typedef struct rdp_memrange
{
    uint32_t lo, hi;
} rdp_memrange;

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
void     rdp_render_engine_feed(const uint64_t *words, unsigned nwords);
int      rdp_render_engine_step(rdp_engine_work *works, unsigned capacity);

/* Plan T13: the host drives the pixel pipeline. Primitives queue their
 * spans at dispatch; each span runs only when the host calls
 * rdp_render_span_run, against the windows it installed. */
typedef struct rdp_span_info {
  int32_t  y, x0, x1;       /* pixel range the span can touch; x1 < x0 when empty */
  int32_t  pixels;          /* pixels the pipeline draws (rdp_occ_accumulate's width) */
  uint8_t  phantom;         /* no span at all: no pixels, no time */
  uint32_t primitive;       /* index of the span's primitive */
  uint32_t fb_address, fb_width, fb_size, zb_address;
  uint32_t cycle_type;
  uint8_t  image_read, z_compare, z_update, atomic;
} rdp_span_info;

/* The queued span `ahead` places past the next one to run; 0 when none. */
int      rdp_render_span_peek(unsigned ahead, rdp_span_info *info);
/* Runs the next queued span against the installed windows. */
void     rdp_render_span_run(void);
void     rdp_render_set_windows(const rdp_memwin *windows, unsigned count);
/* Accesses that fell outside every installed window (a footprint bug). */
uint64_t rdp_render_mem_misses(void);
/* Opcode of the next buffered complete command, or -1. */
int      rdp_render_engine_next(void);
/* The next command would run queued spans inside its handler. */
int      rdp_render_engine_drains(void);
/* RDRAM ranges the next command (a TMEM load) reads; count returned. */
unsigned rdp_render_load_plan(rdp_memrange *ranges, unsigned max);

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
 * command words, the noise counter, the DPS model, the queued spans) in a
 * fixed order, passing each block to io.
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
