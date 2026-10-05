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
    uint32_t *dp_regs;
    void (*dp_interrupt)(void *);
    void *opaque;
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

// dp_full_sync callback, installed on the renderer.
static void rdp_dp_full_sync(void *opaque)
{
    (void)opaque;

    /* Async: the interrupt fires at the same emulated instant; the
     * drain is deferred to the observation fences. */
    if (s_ctx.rdp != NULL &&
        !atomic_load_explicit(&s_ctx.rdp->m_async_on, memory_order_relaxed))
        poly_manager_wait(&s_ctx.rdp->m_pool);

    if (s_ctx.dp_interrupt != NULL)
        s_ctx.dp_interrupt(s_ctx.opaque);
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
    uint32_t *dmem, uint32_t *dp_regs,
    void (*dp_interrupt)(void *opaque), void *opaque)
{
    rdp_t *rdp;

    if (!rdram || !hidden || !dmem || !dp_regs || rdram_size < 4u)
        return 1;

    // In order: construct the renderer, build internal state, wire the
    // full-sync callback, initialize the blender and texture pipe
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

    rdp->m_dp_full_sync = rdp_dp_full_sync;
    rdp->m_dp_full_sync_opaque = NULL;

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
    /* ares port: synchronous. Every command list drains before the
     * DPC_END write returns and Sync_Full drains before the DP
     * interrupt, so RDRAM is settled whenever the CPU or RSP runs and
     * no fence is needed. RDP_WQ_THREADS=1 keeps the span work on the
     * emulation thread (rdp_wqueue.c). */
    atomic_store(&rdp->m_async_on, 0);
    s_ctx.dp_regs = dp_regs;
    s_ctx.dp_interrupt = dp_interrupt;
    s_ctx.opaque = opaque;

    rdp->m_engine_drive = RDP_DP_TIMED != 0;

    return 0;
}

void rdp_render_set_fence_range_check(int on)
{
    s_ctx.fence_range_check = (on != 0);
}

/* ---- Timed DPC engine glue ----------------------------------------------
 * Thin pass-throughs for the DPC engine in rdp/interface.c. CONTRACT:
 * callers hold dp_lock (the engine event handler and the DPC write
 * handlers do), matching every other producer-side entry. */

int rdp_render_engine_active(void)
{
    return s_ctx.rdp != NULL && s_ctx.rdp->m_engine_drive;
}

unsigned rdp_render_engine_need(void)
{
    return rdp_engine_need(s_ctx.rdp);
}

unsigned rdp_render_engine_room(void)
{
    return rdp_engine_room(s_ctx.rdp);
}

/* Crashed-pipe query for the DPC status contract; safe on either
 * dispatch path and before init (reports not-crashed). */
int rdp_render_crashed(void)
{
    return s_ctx.rdp != NULL && rdp_crashed(s_ctx.rdp);
}

void rdp_render_engine_feed(uint32_t address, unsigned nwords, uint32_t xbus)
{
    rdp_engine_feed(s_ctx.rdp, address, nwords, xbus);
}

int rdp_render_engine_step(uint32_t *cycles, unsigned *cls)
{
    return rdp_engine_step(s_ctx.rdp, cycles, cls);
}

/* Raises MI_INTR_DP; the engine calls this when a Sync_Full retires. */
void rdp_render_engine_full_sync(void)
{
    if (s_ctx.dp_interrupt != NULL)
        s_ctx.dp_interrupt(s_ctx.opaque);
}

void rdp_render_destroy(void)
{    if (s_ctx.rdp != NULL) {
        poly_manager_wait(&s_ctx.rdp->m_pool);
        rdp_destroy(s_ctx.rdp);
        free(s_ctx.rdp);
    }

    s_hidden_plane = NULL;
    s_ctx.rdp = NULL;
    s_ctx.dp_regs = NULL;
    s_ctx.dp_interrupt = NULL;
    s_ctx.opaque = NULL;
}

uint8_t *rdp_hidden_plane(void)
{
    return s_hidden_plane;
}

void rdp_process_list(void)
{
    rdp_t *rdp = s_ctx.rdp;
    uint32_t *regs = s_ctx.dp_regs;
    uint32_t status_in, status_out, cleared, set;

    if (!rdp || !regs)
        return;

    // Mirror the host-visible registers into the renderer.
    status_in = regs[RDP_DPC_STATUS_REG];
    rdp->m_start = regs[RDP_DPC_START_REG];
    rdp->m_current = regs[RDP_DPC_CURRENT_REG];
    rdp->m_end = regs[RDP_DPC_END_REG];
    rdp->m_status = status_in;

    rdp_process_command_list(rdp);

    // Reflect renderer state back to the host per the DPC register
    // spec (n64brew RDP registers): DP_START and DP_END are 24-bit
    // RDRAM addresses; DP_CURRENT reports the address of the last
    // command word consumed.
    regs[RDP_DPC_START_REG] &= 0x00ffffff;
    regs[RDP_DPC_END_REG] &= 0x00ffffff;
    regs[RDP_DPC_CURRENT_REG] = rdp->m_current;

    // STATUS: apply only the delta the renderer made (in-place set/clear
    // of just the bits it changed). A blind store of m_status would clobber
    // any DPC_STATUS write the CPU (VR4300 thread) performed via MMIO
    // while this list was processing on the RCP thread -- e.g.
    // libultra's osDpSetStatus XBUS/FREEZE clears at gfx task load,
    // exactly the microcode-handoff window where OoT misbehaves.
    status_out = rdp->m_status;
    cleared = status_in & ~status_out;
    set = status_out & ~status_in;
    regs[RDP_DPC_STATUS_REG] = (regs[RDP_DPC_STATUS_REG] & ~cleared) | set;
}
