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
} s_ctx;

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

void rdp_render_dps_arm(void)
{
    if (s_ctx.rdp != NULL)
        s_ctx.rdp->m_dps.armed = 1;
}

int rdp_render_dps_take(uint32_t words[32])
{
    if (s_ctx.rdp == NULL || !s_ctx.rdp->m_dps.valid)
        return 0;
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
}

int rdp_render_init(uint32_t rdram_size)
{
    rdp_t *rdp;

    if (rdram_size < 4u)
        return 1;

    // In order: construct the renderer, build internal state,
    // initialize the blender and texture pipe
    // against the live RDP, then allocate the span aux buffer.
    rdp = (rdp_t *)malloc(sizeof(rdp_t));
    if (rdp == NULL)
        return 1;

    if (rdp_construct(rdp, rdram_size)) {
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
    /* ares port: no worker threads. Spans run when the host calls
     * rdp_render_span_run, on the emulation thread; loads and Sync Full
     * keep their in-handler drains, which the host makes empty by running
     * every queued span first (rdp_render_engine_drains). */
    atomic_store(&rdp->m_async_on, 0);

    return 0;
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

void rdp_render_engine_feed(const uint64_t *words, unsigned nwords)
{
    if (s_ctx.rdp != NULL)
        rdp_engine_feed(s_ctx.rdp, words, nwords);
}

/* Steps one command, then every following buffered command a held hazard
 * primitive's window still collects, so the hold resolves inside this
 * call; works[] receives one entry per command (at most `capacity`).
 * Then publishes any held hazard primitive, so its spans queue for the
 * host. Returns the command count, 0 when starved, -1 when the pipeline
 * is crashed. */
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
    rdp_engine_publish(rdp);
    return (int)count;
}

int rdp_render_span_peek(unsigned ahead, rdp_span_info *info)
{
    poly_span span;
    const rdp_poly_state *o;
    int32_t a, b;

    if (s_ctx.rdp == NULL || !poly_manager_peek(&s_ctx.rdp->m_pool, ahead, &span))
        return 0;
    o = span.primitive->m_object;
    a = span.extent->startx;
    b = span.extent->stopx;
    info->y = span.scanline;
    info->x0 = a < b ? a : b;
    info->x1 = a < b ? b : a;
    if (info->x0 < 0) info->x0 = 0;
    if (info->x1 >= (int32_t)o->m_misc_state.m_fb_width) info->x1 = (int32_t)o->m_misc_state.m_fb_width - 1;
    info->primitive = o->m_primitive_offset;
    info->fb_address = o->m_misc_state.m_fb_address;
    info->fb_width = o->m_misc_state.m_fb_width;
    info->fb_size = o->m_misc_state.m_fb_size;
    info->zb_address = o->m_misc_state.m_zb_address;
    info->cycle_type = o->m_other_modes.cycle_type;
    info->image_read = o->m_other_modes.image_read_en;
    info->z_compare = o->m_other_modes.z_compare_en;
    info->z_update = o->m_other_modes.z_update_en;
    info->atomic = o->m_other_modes.atomic_prim;
    return 1;
}

void rdp_render_span_run(void)
{
    if (s_ctx.rdp != NULL)
        poly_manager_run_next(&s_ctx.rdp->m_pool);
}

void rdp_render_set_windows(const rdp_memwin *windows, unsigned count)
{
    if (s_ctx.rdp == NULL)
        return;
    s_ctx.rdp->m_win = windows;
    s_ctx.rdp->m_nwin = count;
    s_ctx.rdp->m_win_last = 0;
}

uint64_t rdp_render_mem_misses(void)
{
    return s_ctx.rdp != NULL ? s_ctx.rdp->m_mem_miss : 0;
}

int rdp_render_engine_next(void)
{
    return s_ctx.rdp != NULL ? rdp_engine_next(s_ctx.rdp) : -1;
}

int rdp_render_engine_drains(void)
{
    return s_ctx.rdp != NULL && rdp_engine_drains(s_ctx.rdp);
}

unsigned rdp_render_load_plan(rdp_memrange *ranges, unsigned max)
{
    return s_ctx.rdp != NULL ? rdp_engine_load_plan(s_ctx.rdp, ranges, max) : 0;
}

void rdp_render_destroy(void)
{    if (s_ctx.rdp != NULL) {
        poly_manager_wait(&s_ctx.rdp->m_pool);
        rdp_destroy(s_ctx.rdp);
        free(s_ctx.rdp);
    }

    s_ctx.rdp = NULL;
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
 * ares pixel counter is included. Hazard holds never outlive
 * rdp_render_engine_step; queued spans travel with the poly pools. */
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

    /* Plan T13: spans wait in the poly pools across emulated time. Their
     * aux records hold the walker's edge data; rdp_span_aux_init rebuilds
     * the rest when each span runs. */
    if (loading && rdp->m_aux_buf_ptr > EXTENT_AUX_COUNT)
        rdp->m_aux_buf_ptr = 0;
    io(ctx, rdp->m_aux_buf, rdp->m_aux_buf_ptr);
    {
        uint32_t n;
        poly_render_cb const *callbacks = rdp_span_callbacks(&n);
        poly_manager_serialize(&rdp->m_pool, io, ctx, loading, rdp->m_aux_buf, rdp->m_tmem_pool, callbacks, n);
    }
#undef RDP_STATE
}
