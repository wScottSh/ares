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
//
// rdp/rdp.c: Renderer glue implementation.
//
// CEN64: Cycle-Accurate Nintendo 64 Emulator.
//
// Bridges CEN64's RDP interface (rdp/interface.c) to the renderer. The
// renderer is a singleton here: one static context plus the
// dp_full_sync callback, which drains the render work queue before
// raising the host's DP interrupt so the interrupt is never observed
// before the frame data is in RDRAM.
//

#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rdp.h"
#include "rdp_core.h"

// Singleton renderer context.
static struct {
    rdp_t *rdp;
    int fence_range_check;  /* See rdp_render_set_fence_range_check in
                               rdp.h. Not touched by init or destroy. */
} s_ctx = { .fence_range_check = 1 };

// Base of the renderer's hidden-bit plane; NULL outside init..destroy.
static uint8_t *s_hidden_plane;

static void rdp_log_stderr(int level, const char *fmt, ...)
{
    va_list va;
    (void)level;
    va_start(va, fmt);
    vfprintf(stderr, fmt, va);
    va_end(va);
}

void (*cen64_log)(int, const char *, ...) = rdp_log_stderr;

void rdp_render_set_log(void (*log)(int level, const char *fmt, ...))
{
    cen64_log = log != NULL ? log : rdp_log_stderr;
}

uint64_t rdp_render_pixel_count(void)
{
    return s_ctx.rdp != NULL ? s_ctx.rdp->m_pixels : 0;
}

/* Emulator-facing fences (see rdp_core.h). Rendering is always
 * asynchronous in the emulator: Sync Full and the per-kick list-end
 * points raise their interrupts / return at the same emulated instant
 * as the historical synchronous renderer, while the span queue
 * completes on the workers. Every emulator path that reads or writes
 * RDRAM (CPU cache fill/writeback and uncached access, RSP/PI/SI DMA,
 * VI scanout) fences first via rdp_rdram_fence() in rdp/interface.c,
 * which pairs the unlocked check below with the DP producer lock for
 * the drain. The bare renderer core defaults to the synchronous model
 * (m_async_on = 0), which is what every test tool and golden baseline
 * runs against. */
/* Stage-1 unlocked check of the two-stage fence protocol (see
 * rdp_rdram_fence in rdp/interface.c): a cheap query the hot RDRAM
 * paths can make on every access. Returns nonzero when queued span
 * work may overlap [addr, addr+len) and the caller must take the DP
 * producer lock and call rdp_fence(). A false positive (stale
 * pending observed while another fence is clearing it) only costs a
 * lock and an empty drain; a false negative is impossible because
 * pending is cleared strictly AFTER the drain completes. */
int rdp_fence_needed(uint32_t addr, uint32_t len)
{
    const rdp_t *rdp = s_ctx.rdp;
    uint32_t lo, hi;

    if (rdp == NULL)
        return 0;

    if (!atomic_load_explicit(&rdp->m_async_pending, memory_order_acquire))
        return 0;

    if (!s_ctx.fence_range_check)
        return 1;

    lo = atomic_load_explicit(&rdp->m_async_fb_lo, memory_order_relaxed);
    hi = atomic_load_explicit(&rdp->m_async_fb_hi, memory_order_relaxed);
    if (!(addr >= hi || (addr + len) <= lo))
        return 1;

    lo = atomic_load_explicit(&rdp->m_async_zb_lo, memory_order_relaxed);
    hi = atomic_load_explicit(&rdp->m_async_zb_hi, memory_order_relaxed);

    return !(addr >= hi || (addr + len) <= lo);
}

void rdp_hidden_read_row(uint32_t idx16, uint32_t n, uint8_t *dst)
{
    rdp_t *rdp = s_ctx.rdp;
    uint32_t i;

    if (rdp == NULL) {
        memset(dst, 0, n);
        return;
    }
    /* Mask like the VI's per-texel path so a framebuffer row that
     * wraps RDRAM reads identically. */
    for (i = 0; i < n; i++)
        dst[i] = HREADADDR8((idx16 + i) & 0x3FFFFFu);  /* 8MB RDRAM >> 1 */
}

void rdp_fence(uint32_t addr, uint32_t len)
{
    if (s_ctx.rdp != NULL)
        rdp_async_fence(s_ctx.rdp, addr, len);
}

void rdp_fence_all(void)
{
    if (s_ctx.rdp != NULL)
        rdp_async_fence_all(s_ctx.rdp);
}

void rdp_render_dps_arm(void)
{
    if (s_ctx.rdp != NULL)
        s_ctx.rdp->m_dps.armed = 1;
}

int rdp_render_dps_take(uint32_t words[32])
{
    if (s_ctx.rdp == NULL || !s_ctx.rdp->m_dps.valid)
        return 0;
    /* The drain orders the worker capture stores before the merge. */
    rdp_async_fence_all(s_ctx.rdp);
    return rdp_dps_take(s_ctx.rdp, words);
}

struct rdp_t *rdp_render_instance(void)
{
    return s_ctx.rdp;
}

void rdp_render_quiesce(void)
{
    if (s_ctx.rdp == NULL)
        return;

    rdp_state_quiesce(s_ctx.rdp);
    rdp_async_fence_all(s_ctx.rdp);
}

int rdp_render_init(uint32_t *rdram, uint32_t rdram_size, uint8_t *hidden,
    uint32_t *dmem)
{
    rdp_t *rdp;

    if (!rdram || !hidden || !dmem || rdram_size < 4u)
        return 1;

    // In order: construct the renderer, build internal state,
    // initialize the blender and texture pipe
    // against the live RDP, then allocate the span aux buffer.
    rdp = (rdp_t *)malloc(sizeof(rdp_t));
    if (rdp == NULL)
        return 1;

    if (rdp_construct(rdp, rdram, rdram_size, hidden, dmem)) {
        free(rdp);
        return 1;
    }

    if (rdp_init_internal_state(rdp)) {
        /* Nothing to tear down beyond what rdp_construct() built: the
         * internal state releases its own acquisitions on failure, and
         * rdp_destroy() cannot be used here because it would destroy a
         * m_wait_lock that does not exist. */
        poly_manager_destroy(&rdp->m_pool);
        free(rdp);
        return 1;
    }

    rdp_blender_init(&rdp->m_blender);
    rdp_texpipe_init(&rdp->m_tex_pipe, rdp);

    rdp->m_aux_buf = (uint8_t *)calloc(1, EXTENT_AUX_COUNT);
    if (rdp->m_aux_buf == NULL) {
        rdp_destroy(rdp);
        free(rdp);
        return 1;
    }

    s_ctx.rdp = rdp;
    s_hidden_plane = rdp->m_hidden_bits;
    /* ares port: synchronous. The host settles the renderer after every
     * dispatch (rdp_render_engine_step), so RDRAM is current whenever
     * another device runs and no fence is needed. RDP_WQ_THREADS=1 keeps
     * the span work on the emulation thread (rdp_wqueue.c). */
    atomic_store(&rdp->m_async_on, 0);

    return 0;
}

void rdp_render_set_fence_range_check(int on)
{
    s_ctx.fence_range_check = (on != 0);
}

/* ---- Timed DPC engine glue ----------------------------------------------
 * Thin pass-throughs for the host's DPC front end (ares rdp/timed.cpp). */

unsigned rdp_render_engine_need(void)
{
    return s_ctx.rdp != NULL ? rdp_engine_need(s_ctx.rdp) : 1;
}

unsigned rdp_render_engine_buffered(void)
{
    return s_ctx.rdp != NULL ? s_ctx.rdp->m_cmd_ptr - s_ctx.rdp->m_cmd_cur : 0;
}

/* Crashed-pipe query for the DPC status contract; safe on either
 * dispatch path and before init (reports not-crashed). */
int rdp_render_crashed(void)
{
    return s_ctx.rdp != NULL && rdp_crashed(s_ctx.rdp);
}

void rdp_render_engine_feed(uint32_t address, unsigned nwords, uint32_t xbus)
{
    if (s_ctx.rdp != NULL)
        rdp_engine_feed(s_ctx.rdp, address, nwords, xbus);
}

/* Steps one command, then every following buffered command a held hazard
 * primitive's window still collects, so the hold resolves inside this
 * call; works[] receives one entry per command (at most `capacity`).
 * Then settles the renderer: no held primitive and no queued span
 * outlives the call, so emulated time never passes with renderer work
 * in flight and saving needs no mutation. Returns the command count, 0
 * when starved, -1 when the pipeline is crashed. */
int rdp_render_engine_step(rdp_engine_work *works, unsigned capacity)
{
    rdp_t *rdp = s_ctx.rdp;
    unsigned count = 0;
    int r;

    if (rdp == NULL || capacity == 0)
        return 0;

    r = rdp_engine_step(rdp, &works[count]);
    if (r <= 0)
        return r;
    count++;
    while (count < capacity && rdp_engine_hold_open(rdp)) {
        if (rdp_engine_step(rdp, &works[count]) <= 0)
            break;
        count++;
    }
    rdp_engine_settle(rdp);
    return (int)count;
}

void rdp_render_destroy(void)
{    if (s_ctx.rdp != NULL) {
        poly_manager_wait(&s_ctx.rdp->m_pool);
        rdp_destroy(s_ctx.rdp);
        free(s_ctx.rdp);
    }

    s_hidden_plane = NULL;
    s_ctx.rdp = NULL;
}

uint8_t *rdp_hidden_plane(void)
{
    return s_hidden_plane;
}

uint32_t rdp_render_color_image(void)
{
    return s_ctx.rdp != NULL ? s_ctx.rdp->m_misc_state.m_fb_address : 0;
}

uint32_t rdp_render_mask_image(void)
{
    return s_ctx.rdp != NULL ? s_ctx.rdp->m_misc_state.m_zb_address : 0;
}

uint8_t *rdp_render_tmem(void)
{
    return s_ctx.rdp != NULL ? s_ctx.rdp->m_tmem : NULL;
}

/* Field list after cen64-jgemu src/device/state.c ss_render (same commit as
 * the import). Differences: whole structs travel as blocks, so the scissor
 * fractions upstream drops survive; the hidden plane is ares' and travels
 * with RDRAM; only the live prefix of the command accumulator travels; the
 * ares pixel counter is included. Hazard holds and queued spans never
 * outlive rdp_render_engine_step, so neither needs saving. */
void rdp_render_serialize(rdp_state_io io, void *ctx, int loading)
{
    rdp_t *rdp = s_ctx.rdp;

    if (rdp == NULL)
        return;

#define RDP_STATE(field) io(ctx, &rdp->field, sizeof(rdp->field))
    RDP_STATE(m_misc_state);
    RDP_STATE(m_blend_color);
    RDP_STATE(m_prim_color);
    RDP_STATE(m_prim_alpha);
    RDP_STATE(m_env_color);
    RDP_STATE(m_env_alpha);
    RDP_STATE(m_fog_color);
    RDP_STATE(m_key_scale);
    RDP_STATE(m_key_center);
    RDP_STATE(m_key_width);
    RDP_STATE(m_lod_fraction);
    RDP_STATE(m_prim_lod_fraction);
    RDP_STATE(m_k02);
    RDP_STATE(m_k13);
    RDP_STATE(m_k4);
    RDP_STATE(m_k5);
    RDP_STATE(m_fill_color);
    RDP_STATE(m_other_modes);
    RDP_STATE(m_combine);
    RDP_STATE(m_tiles);
    RDP_STATE(m_scissor);
    RDP_STATE(m_span_base);
    RDP_STATE(m_aux_buf_ptr);
    RDP_STATE(m_pipeline_crashed);
    RDP_STATE(m_primitive_counter);
    RDP_STATE(m_pixels);
    RDP_STATE(m_rect_stale);
    RDP_STATE(m_pipe_clean);
    RDP_STATE(m_start);
    RDP_STATE(m_end);
    RDP_STATE(m_current);
    RDP_STATE(m_status);

    RDP_STATE(m_cmd_cur);
    RDP_STATE(m_cmd_ptr);
    if (loading && (rdp->m_cmd_ptr > CMD_DATA_WORDS || rdp->m_cmd_cur > rdp->m_cmd_ptr))
        rdp->m_cmd_ptr = rdp->m_cmd_cur = 0;
    io(ctx, rdp->m_cmd_data, rdp->m_cmd_ptr * sizeof(rdp->m_cmd_data[0]));

    /* The setup-transient row scratch from nrows on is dead between
     * primitives. */
    io(ctx, &rdp->m_dps, offsetof(rdp_dps_model_t, nrows));

    if (loading) {
        rdp->m_tmem = rdp->m_tmem_pool;
        rdp->m_tmem_cows = 0;
    }
    io(ctx, rdp->m_tmem, 0x1000);
#undef RDP_STATE
}
