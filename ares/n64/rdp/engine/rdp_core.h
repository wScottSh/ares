/*
Copyright (c) 2011-2023 Ryan Holtz
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
/******************************************************************************

    rdp_core.h (from MAME video/n64.h)

    SGI/Nintendo Reality Display Processor, ISO C11 translation.

    struct rdp_t holds the renderer state, with the poly_manager as its
    first member; every operation on it is an rdp_* function taking the
    struct pointer first. The dispatch tables (m_compute_cvg,
    m_write_pixel, ...) are plain function pointers with the same
    explicit first argument. Noise comes from the position-hashed
    rdp_seeded_noise() in rdp_core.c, and the host is reached only
    through the dp_full_sync callback the glue installs.

******************************************************************************/

#ifndef RDP_CORE_H
#define RDP_CORE_H

#include <pthread.h>

#include "rdp.h"
#include "rdp_types.h"
#include "rdp_poly.h"
#include "rdp_blend.h"
#include "rdp_texpipe.h"

/*****************************************************************************/

#define PIXEL_SIZE_4BIT         0
#define PIXEL_SIZE_8BIT         1
#define PIXEL_SIZE_16BIT        2
#define PIXEL_SIZE_32BIT        3

#define CYCLE_TYPE_1            0
#define CYCLE_TYPE_2            1
#define CYCLE_TYPE_COPY         2
#define CYCLE_TYPE_FILL         3

#define FORMAT_RGBA             0
#define FORMAT_YUV              1
#define FORMAT_CI               2
#define FORMAT_IA               3
#define FORMAT_I                4

/* The far half of a doubleword -- 4 bytes, 2 halfwords or 1 word along on
   either host -- combined with the host's swizzle within the word. */
#define BYTE_XOR_DWORD_SWAP  (4 ^ BYTE_IN_WORD_XOR)
#define WORD_XOR_DWORD_SWAP  (2 ^ HWORD_IN_WORD_XOR)

/* Highest in-range index of each RDRAM view, from the installed RDRAM
   size the host passes to rdp_construct. */
#define MEM8_LIMIT  (rdp->m_mem8_limit)
#define MEM16_LIMIT (rdp->m_mem16_limit)
#define MEM32_LIMIT (rdp->m_mem32_limit)

// DPC_STATUS bits
#define DP_STATUS_XBUS_DMA      0x01
#define DP_STATUS_FREEZE        0x02
#define DP_STATUS_FLUSH         0x04
#define DP_STATUS_CBUF_READY    0x80
#define DP_STATUS_START_VALID   0x400

// The RREAD/RWRITE and HREAD/HWRITE accessor macros expand references
// to the renderer state; every function using them takes an `rdp_t *rdp`.

// Bounds-guarded RDRAM accessors. A command list may legally program a
// framebuffer or span beyond installed RDRAM, so every access is range
// checked rather than indexing the backing array blind: out-of-range
// reads return 0 and out-of-range writes are dropped, matching
// hardware's unpopulated-RDRAM behavior. The compares are
// well-predicted never-taken branches.
//
// ares port: RDRAM is ares' LSB Memory::Writable buffer, native 32-bit
// words with the bytes of each word swizzled (byte address ^ 3, halfword
// index ^ 1), the layout MAME's RDP was written for, so no byteswap is
// applied. (DMEM is big-endian bytes; see rdp_read_data.) The limit is the installed RDRAM, not the
// RDP_RDRAM_SIZE constant, because ares allocates 4 MB without the
// Expansion Pak.
static inline uint8_t rdp_guard_read8(const uint8_t *mem, uint32_t limit, uint32_t in) {
  return in <= limit ? mem[in ^ 3u] : 0;
}
static inline void rdp_guard_write8(uint8_t *mem, uint32_t limit, uint32_t in, uint8_t val) {
  if (in <= limit)
    mem[in ^ 3u] = val;
}
static inline uint16_t rdp_guard_read16(const uint16_t *mem, uint32_t limit, uint32_t in) {
  return in <= limit ? mem[in ^ 1u] : 0;
}
static inline void rdp_guard_write16(uint16_t *mem, uint32_t limit, uint32_t in,
  uint16_t val) {
  if (in <= limit)
    mem[in ^ 1u] = val;
}
static inline uint32_t rdp_guard_read32(const uint32_t *mem, uint32_t limit, uint32_t in) {
  return in <= limit ? mem[in] : 0;
}
static inline void rdp_guard_write32(uint32_t *mem, uint32_t limit, uint32_t in,
  uint32_t val) {
  if (in <= limit)
    mem[in] = val;
}

#define RREADADDR8(in) rdp_guard_read8((const uint8_t*)rdp->m_rdram, MEM8_LIMIT, (in))
#define RREADIDX16(in) rdp_guard_read16((const uint16_t*)rdp->m_rdram, MEM16_LIMIT, (in))
#define RREADIDX32(in) rdp_guard_read32(rdp->m_rdram, MEM32_LIMIT, (in))

#define RWRITEADDR8(in, val)    rdp_guard_write8((uint8_t*)rdp->m_rdram, MEM8_LIMIT, (in), (val))
#define RWRITEIDX16(in, val)    rdp_guard_write16((uint16_t*)rdp->m_rdram, MEM16_LIMIT, (in), (val))
#define RWRITEIDX32(in, val)    rdp_guard_write32(rdp->m_rdram, MEM32_LIMIT, (in), (val))

#define GETLOWCOL(x)    (((x) & 0x3e) << 2)
#define GETMEDCOL(x)    (((x) & 0x7c0) >> 3)
#define GETHICOL(x)     (((x) & 0xf800) >> 8)

// The hidden ("9th" bit) plane is ares' HiddenRAM: one byte per 16-bit
// RDRAM word indexed by the 16-bit word index with no swizzle, bit 1 the
// even byte and bit 0 the odd byte. CPU and DMA writes maintain it on
// the ares side; the renderer reads and writes the same plane.
static inline uint8_t rdp_guard_hread(const uint8_t *plane, uint32_t limit, uint32_t in) {
  return in <= limit ? plane[in] : 0;
}
static inline void rdp_guard_hwrite(uint8_t *plane, uint32_t limit, uint32_t in, uint8_t val) {
  if (in <= limit)
    plane[in] = val;
}
#define HREADADDR8(in)          rdp_guard_hread(rdp->m_hidden_bits, MEM16_LIMIT, (in))
#define HWRITEADDR8(in, val)    rdp_guard_hwrite(rdp->m_hidden_bits, MEM16_LIMIT, (in), (val))

/* sign-extension macros: branchless fixed-width sign extend, r = (x ^ m) - m
 * with m = 1 << (b-1); UB-free and bit-identical to the former smear-multiply. */
#define SIGN22(x)   ((((x) & 0x3fffff) ^ 0x200000) - 0x200000)
#define SIGN17(x)   ((((x) & 0x1ffff)  ^ 0x10000)  - 0x10000)
#define SIGN16(x)   ((((x) & 0xffff)   ^ 0x8000)   - 0x8000)
#define SIGN9(x)    ((((x) & 0x1ff)    ^ 0x100)    - 0x100)

/* Well-defined two's-complement fixed-point arithmetic shared by the core and
 * texpipe: bit-identical to the plain signed operators, but done in uint32_t so
 * there is no signed-overflow / negative-left-shift UB for the optimizer to
 * exploit. */
static inline int32_t rdp_smul(int32_t a, int32_t b)  { return (int32_t)((uint32_t)a * (uint32_t)b); }
static inline int32_t rdp_sadd(int32_t a, int32_t b)  { return (int32_t)((uint32_t)a + (uint32_t)b); }
static inline int32_t rdp_sneg(int32_t a)             { return (int32_t)(0u - (uint32_t)a); }
static inline int32_t rdp_sshl(int32_t v, unsigned n) { return (int32_t)((uint32_t)v << n); }

#define SPAN_R      (0)
#define SPAN_G      (1)
#define SPAN_B      (2)
#define SPAN_A      (3)
#define SPAN_S      (4)
#define SPAN_T      (5)
#define SPAN_W      (6)
#define SPAN_Z      (7)
/* RH#001 support: start S/T/W of the NEXT scanline's span within the
 * same primitive (dpdx of SPAN_NS doubles as the validity flag).
 * Filled by render_spans on the walk thread; consumed by the 1-cycle
 * span end-of-span pipelined TEXEL1 fetch. */
#define SPAN_NS     (8)
#define SPAN_NT     (9)
#define SPAN_NW     (10)

#define EXTENT_AUX_COUNT            (sizeof(rdp_span_aux)*(480*192)) // Screen coverage *192, more or less

/*****************************************************************************/

typedef struct rdp_t rdp_t;

// Dispatch table signatures.
typedef void (*write_pixel_t)(rdp_t *rdp, uint32_t curpixel, rgbaint_t* color, rdp_span_aux* userdata, const rdp_poly_state *object);
typedef void (*read_pixel_t)(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object);
typedef void (*copy_pixel_t)(rdp_t *rdp, uint32_t curpixel, rgbaint_t* color, const rdp_poly_state *object);

#define TMEM_POOL_SLOTS 64

/* Unsynced register-write hazard state, 1-/2-cycle rectangles; holds one
 * primitive unqueued while the window is open, so it is renderer state,
 * not scratch. Command-walk thread only. Model derivation is at the
 * implementation in rdp_core.c. */
#define HAZ_MAX_SEG 8

typedef struct
{
    int             active;
    rdp_poly_state *object;
    poly_rect       clip;
    int32_t         start, end, offset;
    int32_t         lo;
    int32_t         w, h, n;
    int32_t         span, lead;
    int32_t         cyc;
    int32_t         clock;
    int32_t         nseg;
    int32_t         seg_px[HAZ_MAX_SEG];
    rgbaint_t       seg_env[HAZ_MAX_SEG];
} rdp_haz_state;

/* Unsynced Set Fill Color hazard state, FILL-mode rectangles.
 *
 * The same command-processor lead as the 1-/2-cycle case, but the fill colour
 * latches once per span, so a write recolours a whole number of trailing rows
 * and never part of one. The primitive is held unqueued while the window is
 * open. Command-walk thread only; model derivation is at the implementation
 * in rdp_core.c. */
#define FILL_HAZ_MAX_SEG 8

/* Largest lead the model produces: 35 + W + phi at one block, where a
 * one-block row is at most eight words. Once the command processor has run
 * this far past the primitive no write can reach it. */
#define FILL_HAZ_MAX_LEAD 44

typedef struct
{
    int             active;
    rdp_poly_state *object;
    poly_rect       clip;
    int32_t         start, end, offset;
    int32_t         h;
    int32_t         x0, x1;       /* span pixel bounds, inclusive           */
    int32_t         fbsize;       /* m_fb_size of the colour image          */
    int32_t         clock;        /* GCLK since the command processor woke  */
    int32_t         nseg;
    int32_t         seg_row[FILL_HAZ_MAX_SEG];  /* first row taking the new */
    uint32_t        seg_fill[FILL_HAZ_MAX_SEG]; /* fill word               */
} rdp_fill_haz_state;

/* Stale-read hazard hold for back-to-back identical rectangles.
 * See rdp_fill_rect_stale_read in rdp_core.c. */
typedef struct rdp_rect_stale_state
{
    uint64_t w1;            /* last eligible rectangle's command word */
    uint32_t idx[32];       /* footprint, 16-bit RDRAM indices */
    uint16_t pre[32];       /* pre-image of the footprint */
    uint8_t  n;
    uint8_t  valid;
} rdp_rect_stale_state;

/* DPS Test-Mode span-buffer stream model.
 *
 * The DP span buffer is CPU-visible through the DPS BUFTEST registers
 * (n64brew RDP Interface); after a draw it holds the span pipeline's
 * staged framebuffer words. Hardware law (snapper64 "RDP Test-Mode -
 * Span Tri", 216/216 reference captures exact):
 *
 *   - One stream position per rasterized pixel, S = 0 at primitive
 *     start, phase-locked S == x (mod 4); slot = S mod 16, CPU-visible
 *     when S/16 is even. The value is the write-stage word image,
 *     (r<<24)|(g<<16)|(b<<8)|(((cvg-1)&7)<<5), coverage-0 included.
 *   - Spans align the first pixel to its phase (odd x0: a head slot at
 *     phase x0-1) and pad through phase 3 at the end; every skipped
 *     position takes the value last emitted at the same phase.
 *   - The first span's residual-less head stays pending: canceled by
 *     any later write at its position mod 32, else committed at
 *     primitive end with the final residual.
 *   - Fully y-scissored spans, and spans whose raw edge range misses
 *     the x-scissor (a raw right equal to the scissor left is kept),
 *     consume nothing; clipped pixels of surviving spans likewise.
 *
 * The producer schedules the final window at triangle setup (any 32
 * consecutive positions cover all 16 slots, so a 40-position window
 * plus four residual-seed pixels reconstructs the final state), the
 * 1-cycle span walk captures the scheduled word images at disjoint
 * indices, and the host accessor fences and merges over the stored
 * prefill. Armed by the first DPS register write; unarmed costs one
 * branch per triangle. Provisional: fractional drop-rule edges,
 * cross-primitive carryover (modeled as a reset), rectangles (hazard
 * reordering), non-1-cycle/non-32bpp modes, interlace parity, and
 * residual-write pending cancellation (indistinguishable from
 * pixel-write cancellation in the corpus). */
#define RDP_DPS_WIN   40u
#define RDP_DPS_ROWS  4096u

typedef struct
{
    /* Serialized in device/state.c (post-quiesce, captures settled). */
    uint32_t armed;                 /* a DPS register write has occurred */
    uint32_t valid;                 /* schedule complete, take() pending */
    uint32_t total;                 /* stream length at primitive end */
    uint32_t base;                  /* first scheduled window position */
    uint32_t pend_pos1;             /* pending head position + 1; 0 none */
    uint32_t pend_alive;            /* survives to primitive end */
    uint8_t  sched[RDP_DPS_WIN];    /* 0 none, 1 pixel, 2 residual */
    uint32_t val[RDP_DPS_WIN];      /* worker-captured pixel word images */
    uint8_t  val_set[RDP_DPS_WIN];
    uint32_t seed_val[4];           /* residual state at window entry */
    uint8_t  seed_set[4];
    /* Setup-transient row scratch, dead between primitives; not
     * serialized. */
    uint32_t nrows;
    int16_t  row_x0[RDP_DPS_ROWS];
    int16_t  row_x1[RDP_DPS_ROWS];
    int32_t  row_span[RDP_DPS_ROWS];
} rdp_dps_model_t;

/* DPS span-buffer merge (implementation and group layout in rdp_core.c;
 * host contract in rdp.h). The caller fences the span workers first. */
int rdp_dps_take(rdp_t *rdp, uint32_t words[32]);

// Save states: force-close the SetEnvColor clock-frame hazard window,
// publishing any held spans. A state saved mid-window loses the
// window's retroactive reach into the cycles after the boundary --
// microscopic, and continuation from the load stays deterministic.
void rdp_state_quiesce(rdp_t *rdp);

struct rdp_t
{
    // Span scheduler; must stay first.
    poly_manager m_pool;

    /* Asynchronous rendering (opt-in; default off = behavior identical
     * to the historical synchronous model). When on, Sync Full raises
     * the DP interrupt at the same emulated instant as before but does
     * NOT drain the span queue; rendering completes on the workers
     * while emulation continues, and observers call the fence entry
     * points before touching RDRAM the queued work may write.
     * The watermark is two independent RDRAM byte ranges -- the color
     * image targets (m_async_fb_*) and the z-buffer targets
     * (m_async_zb_*) of all pending span writes -- accumulated at
     * primitive enqueue on the command-walk thread and retired (after
     * the drain) by the fences and the walk's own pipeline drains.
     * Keeping the two apart matters: folding them into one span
     * bridges everything between the color image and the z-buffer,
     * and ordinary CPU/RSP traffic in that gap then fences (and
     * drains) constantly, serializing the emulated threads and
     * forfeiting the async gain. Fences must exclude the producer
     * (the emulator uses dp_lock; see rdp/interface.c). m_wait_lock
     * serializes every poly_manager_wait so only one thread ever runs
     * work items as threadid 0 (worker state is indexed by it). */
    _Atomic uint32_t  m_async_on;
    _Atomic uint32_t  m_async_pending;
    _Atomic uint32_t  m_async_fb_lo;
    _Atomic uint32_t  m_async_fb_hi;
    _Atomic uint32_t  m_async_zb_lo;
    _Atomic uint32_t  m_async_zb_hi;
    /* Image geometry the pending watermark was folded under (command-
     * walk thread; observers that reset it hold dp_lock). Span order
     * within the queue is by scanline bucket, so RDRAM written under
     * one (address, width, size) is only ordered against later work on
     * the same geometry; an image switch onto pending bytes under a
     * different geometry drains first. mixed = folds under more than
     * one geometry since the last reset. */
    uint32_t          m_async_fbg_addr;
    uint32_t          m_async_fbg_width;
    uint32_t          m_async_fbg_size;
    uint32_t          m_async_fbg_mixed;
    uint32_t          m_async_zbg_addr;
    uint32_t          m_async_zbg_width;
    uint32_t          m_async_zbg_mixed;
    pthread_mutex_t   m_wait_lock;

    misc_state_t m_misc_state;

    // Color constants
    rgbaint_t       m_blend_color;          /* constant blend color */
    rgbaint_t       m_prim_color;           /* flat primitive color */
    rgbaint_t       m_prim_alpha;           /* flat primitive alpha */
    rgbaint_t       m_env_color;            /* generic color constant ('environment') */
    rgbaint_t       m_env_alpha;            /* generic alpha constant ('environment') */
    rgbaint_t       m_fog_color;            /* generic color constant ('fog') */
    rgbaint_t       m_key_scale;            /* color-keying constant */
    rgbaint_t       m_key_center;           /* color-keying center */
    rgbaint_t       m_key_width;            /* color-keying width */
    rgbaint_t       m_lod_fraction;         /* Z-based LOD fraction for this poly */
    rgbaint_t       m_prim_lod_fraction;    /* fixed LOD fraction for this poly */

    rgbaint_t       m_one;
    rgbaint_t       m_onecc;
    rgbaint_t       m_zero;

    uint32_t          m_fill_color;

    other_modes_t   m_other_modes;

    rdp_blender_t   m_blender;

    rdp_texpipe_t m_tex_pipe;

    /* ares port: the host's hidden plane and installed RDRAM size
     * (see the accessor notes above). */
    uint8_t*  m_hidden_bits;
    uint32_t  m_mem8_limit;
    uint32_t  m_mem16_limit;
    uint32_t  m_mem32_limit;

    /* ares port: pixels rasterized (clipped span widths summed), for
     * the ns/pixel measurement. */
    uint64_t  m_pixels;

    uint16_t m_dzpix_normalize[0x10000];

    rectangle_t     m_scissor;
    span_base_t     m_span_base;

    uint8_t*          m_aux_buf;
    uint32_t          m_aux_buf_ptr;

    // Set when certain illegal operations permanently halt RDP command
    // execution, as on real hardware (n64brew RDP pipeline: some
    // operations hang/crash the RDP), rather than aborting the host.
    bool              m_pipeline_crashed;

#define CMD_DATA_WORDS 0x8000u
    uint64_t          m_cmd_data[CMD_DATA_WORDS];
    uint32_t          m_cmd_ptr;
    uint32_t          m_cmd_cur;

    /* What the command rdp_engine_step is dispatching asks of the
     * pipeline (rdp.h); zeroed before each dispatch. */
    rdp_engine_work   m_work;

    rdp_tile_t      m_tiles[8];

    write_pixel_t     m_write_pixel[4];
    read_pixel_t      m_read_pixel[4];
    copy_pixel_t      m_copy_pixel[4];

    uint32_t          m_primitive_counter;   /* monotonic per-primitive index (noise hash) */

    uint32_t*         m_rdram;
    uint32_t*         m_dmem;


    combine_modes_t m_combine;
    bool            m_pipe_clean;

    /* See rdp_haz_state. */
    rdp_haz_state   m_haz;
    rdp_fill_haz_state m_fill_haz;
    rdp_rect_stale_state m_rect_stale;

    cv_mask_derivative_t cvarray[(1 << 8)];

    uint16_t  m_z_com_table[0x40000]; //precalced table of compressed z values, 18b: 512 KB array!
    uint32_t  m_z_complete_dec_table[0x4000]; //the same for decompressed z values, 14b
    uint8_t   m_compressed_cvmasks[0x10000]; //16bit cvmask -> to byte

    uint64_t  m_temp_rect_data[0x800];

    // Span extent scratch buffer for draw_triangle; kept off the stack
    // to stay within small default thread stacks (e.g. musl's 128KiB).
    extent_t m_spans[4096];

    uint32_t  m_start;
    uint32_t  m_end;
    uint32_t  m_current;
    uint32_t  m_status;

    /* TMEM snapshot ring. m_tmem points at the CURRENT 4KB slot inside
     * m_tmem_pool; queued primitives capture it as their m_tmem_src
     * snapshot. In async mode a load with work in flight copies the
     * current slot to the next one and mutates the copy, so consumers
     * keep sampling an intact snapshot with no drain (their tile
     * descriptors are already per-object copies). m_tmem_cows counts
     * live snapshots; the ring reclaims when the queue is observed
     * complete or at any pipeline drain, and exhaustion falls back to
     * a drain. Producer-thread state, like the rest of TMEM. */
    uint8_t*  m_tmem;
    uint8_t*  m_tmem_pool;
    uint32_t  m_tmem_cows;

    /* See rdp_dps_model_t. */
    rdp_dps_model_t m_dps;

    // YUV factors
    rgbaint_t m_k02;
    rgbaint_t m_k13;
    rgbaint_t m_k4;
    rgbaint_t m_k5;

};

/*****************************************************************************/

// Construction/destruction. rdp_construct initializes caller-allocated
// storage and returns nonzero on allocation failure.
int         rdp_construct(rdp_t *rdp, uint32_t* rdram, uint32_t rdram_size,
                uint8_t* hidden, uint32_t* dmem);
void        rdp_destroy(rdp_t *rdp);
/* Async fences: drain if pending work may have written [addr, addr+len)
 * of RDRAM (fence) or unconditionally (fence_all). Cheap no-ops when
 * async is off or nothing is pending. Safe from any thread. */
void        rdp_async_fence(rdp_t *rdp, uint32_t addr, uint32_t len);
void        rdp_async_fence_all(rdp_t *rdp);

int         rdp_init_internal_state(rdp_t *rdp);


/* Timed DPC engine entry points (see rdp_core.c). The host (ares
 * rdp/timed.cpp) feeds fetched command words as emulated time passes and
 * steps one command at a time, receiving each command's work. These never
 * touch the DPC registers, which the host owns. */
unsigned    rdp_engine_need(rdp_t *rdp);
int         rdp_crashed(rdp_t *rdp);
void        rdp_engine_feed(rdp_t *rdp, uint32_t address,
                unsigned nwords, uint32_t xbus);
int         rdp_engine_step(rdp_t *rdp, rdp_engine_work *work);
int         rdp_engine_hold_open(rdp_t *rdp);
void        rdp_engine_settle(rdp_t *rdp);

// YUV conversion factors, from Set Convert.
static inline void rdp_set_yuv_factors(rdp_t *rdp, rgbaint_t k02, rgbaint_t k13, rgbaint_t k4, rgbaint_t k5) { rdp->m_k02 = k02; rdp->m_k13 = k13; rdp->m_k4 = k4; rdp->m_k5 = k5; }

// Texture coordinate perspective division, and the LOD shift it feeds.
void        rdp_tc_div(rdp_t *rdp, int32_t ss, int32_t st, int32_t sw, int32_t* sss, int32_t* sst);
void        rdp_tc_div_no_perspective(int32_t ss, int32_t st, int32_t sw, int32_t* sss, int32_t* sst);
uint32_t    rdp_get_log2(uint32_t lod_clamp);

#endif
