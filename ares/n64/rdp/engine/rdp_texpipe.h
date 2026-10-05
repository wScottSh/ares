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

    SGI/Nintendo Reality Display Texture Fetch Unit (TF)
    -------------------

    by Ryan Holtz
    based on initial C code by Ville Linde
    contains additional improvements from angrylion, Ziggy, Gonetz and Orkin

    Provenance of the three lines above: they are MAME's own file header,
    kept verbatim. They describe how MAME's Reality Display Processor came
    to be, which this file is an ISO C11 translation of -- they are not a
    statement about this project's sources. angrylion, Ziggy, Gonetz and
    Orkin contributed to MAME's code, and that work reached this file
    through MAME's BSD-3-Clause tree.

    m_texel_fetch[] and m_cycle[] are plain function-pointer dispatch
    tables, built by rdp_texpipe_init() in rdp_texpipe.c along with the
    expansion and LOD lookup tables. Fetchers and cycle handlers are
    static in the .c file; only the entry points the RDP core calls are
    declared here.

******************************************************************************/

#ifndef RDP_TEXPIPE_H
#define RDP_TEXPIPE_H

#include "rdp_types.h"

typedef struct rdp_texpipe_t rdp_texpipe_t;

extern uint16_t rdp_lod_lookup[0x80000];

typedef void (*texel_fetcher_t)(rgbaint_t* out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
/* Per-span invariant operands for the texel cyclers.
 *
 * The cyclers are called once or twice per pixel through a function
 * pointer. At nine parameters the SysV ABI put three on the stack, so
 * every pixel paid three pushq plus a stack adjust, and the pressure
 * spilled the call target itself -- perf annotate showed the indirect
 * call issuing from 0x198(%rsp), a load feeding a branch the BTB
 * cannot resolve until it retires.
 *
 * tp, userdata and object are fixed for the whole span, and cycle is
 * fixed per call site, so all four move here. What remains is exactly
 * six arguments: rdi, rsi, rdx, rcx, r8, r9, and nothing on the stack.
 * The context is built once per span alongside the hoisted cycler
 * pointer. */
typedef struct
{
    rdp_texpipe_t   *tp;
    rdp_span_aux         *userdata;
    const rdp_poly_state *object;
    uint32_t              cycle;
} texel_cycle_ctx_t;

typedef void (*texel_cycler_t)(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum);

struct rdp_texpipe_t
{
        texel_cycler_t      m_cycle[4];

        // Indexed by (format << 4) | (size << 2) | (en_tlut << 1) |
        // tlut_type. Format is a 3-bit tile field, so the table must
        // cover all 8 values (formats 5-7 are encodable and games do
        // reference tiles carrying them); an 80-entry table indexed by
        // such a tile reads out of bounds.
        texel_fetcher_t     m_texel_fetch[16*8];

        struct rdp_t*     m_rdp;

};

void rdp_texpipe_init(rdp_texpipe_t *tp, struct rdp_t *rdp);


/* The copy pipe samples one fixed tile per span, so the tile, its fetcher
 * and the destination are span constants. Resolving them once also takes
 * the fetcher table index -- three shifts, two m_other_modes loads and a
 * dependent m_texel_fetch[] load -- off the per-pixel path. */
typedef struct
{
    rdp_texpipe_t        *tp;
    const rdp_poly_state *object;
    rdp_span_aux         *userdata;
    const rdp_tile_t     *tile;
    texel_fetcher_t       fetch;
    rgbaint_t            *out;
} rdp_copy_ctx_t;

void rdp_texpipe_copy_ctx_init(rdp_copy_ctx_t *ctx, rdp_texpipe_t *tp,
    const rdp_poly_state *object, rdp_span_aux *userdata, rgbaint_t *out,
    uint32_t tilenum);
void rdp_texpipe_copy(const rdp_copy_ctx_t *ctx, int32_t sss, int32_t sst,
    int32_t s_offset);
void rdp_texpipe_calculate_clamp_diffs(uint32_t prim_tile, rdp_span_aux* userdata, const rdp_poly_state *object);
/* Unified LOD pipeline (former lod_1cycle / lod_2cycle /
 * lod_2cycle_limited). mode selects the deviations; TEXPIPE_LOD_PEEK
 * is the next-pixel probe form, which takes no userdata side effects
 * (ctx->userdata is NULL there). When a stash is supplied to the PEEK
 * form it additionally captures the raw next-pixel divide and the LOD
 * fraction, allowing the caller to apply the peek's results as the NEXT
 * pixel's LOD evaluation instead of recomputing it from identical inputs
 * (the 2-cycle span pipeline dedup). */
typedef struct rdp_lod_stash
{
    int32_t   raw_next_s;
    int32_t   raw_next_t;
    rgbaint_t lod_fraction;
} rdp_lod_stash;
enum { TEXPIPE_LOD_1CYCLE = 0, TEXPIPE_LOD_2CYCLE = 1, TEXPIPE_LOD_PEEK = 2,
       /* 1-cycle at the second-to-last walked pixel of a span whose four
        * sublines are all valid: the LOD pair is centered, (P-1, P+1),
        * instead of the pipelined (P+1, P+2). */
       TEXPIPE_LOD_1CYCLE_SPANEND = 3 };

/* Per-span invariant operands, as texel_cycle_ctx_t does for the cyclers
 * and for the same reason: at seventeen parameters eleven went on the
 * stack, once or twice per pixel. The out destinations are span-scope
 * locals in every caller, so their addresses are stable for the walk.
 * Leaves s/t/w and mode: five arguments, all in registers. */
typedef struct
{
    rdp_texpipe_t        *tp;
    const rdp_poly_state *object;
    rdp_span_aux         *userdata;   /* NULL in the peek form */
    rdp_lod_stash        *stash;      /* peek only; NULL otherwise */
    int32_t              *sss;        /* in/out: clamped fetch S */
    int32_t              *sst;        /* in/out: clamped fetch T */
    int32_t              *t1;         /* out: promoted first tile */
    int32_t              *t2;         /* out: promoted second tile (2-cycle) */
    int32_t               dsinc;
    int32_t               dtinc;
    int32_t               dwinc;
    int32_t               prim_tile;
    bool                  need_lod;
} rdp_lod_ctx_t;

void rdp_texpipe_lod(const rdp_lod_ctx_t *ctx, const int32_t s,
    const int32_t t, const int32_t w, const int mode);

#endif
