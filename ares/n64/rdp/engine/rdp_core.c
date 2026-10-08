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

    SGI/Nintendo Reality Display Processor
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

*******************************************************************************/

#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#include "cen64_compat.h"
#include "rdp_core.h"

/* Noise (plan T14). The span's j-th pixel in walk order samples the host's
 * LFSRs at its own RDP clock (rdp_render_set_span_clock). */
static inline rdp_noise_bits rdp_pixel_noise(const rdp_t *rdp, int32_t j)
{
    return rdp_noise(rdp->m_noise_clock + (uint64_t)j * rdp->m_noise_step);
}

/* Combiner NOISE: abc100000, a b c the three LFSR outputs (Thar0/RDP-Noise). */
static inline uint32_t rdp_noise_combiner(rdp_noise_bits n) {
    return (n.a >> 31) << 8 | (n.b >> 31) << 7 | (n.c >> 31) << 6 | 0x20u;
}

/* G_AD_NOISE: the same three bits, a highest (rdp.noise-alpha-dither). */
static inline uint32_t rdp_noise_dither_alpha(rdp_noise_bits n) {
    return (n.a >> 31) << 2 | (n.b >> 31) << 1 | (n.c >> 31);
}

/* G_CD_NOISE takes 3 bits per channel and the G_AC_DITHER threshold 8 bits;
 * neither source is known, so both read the top three bits of a, b and c
 * (rdp.noise-dither-bits). */
static inline uint32_t rdp_noise_dither_color(rdp_noise_bits n) {
    return (n.a >> 29) << 6 | (n.b >> 29) << 3 | (n.c >> 29);
}

static inline uint32_t rdp_noise_threshold(rdp_noise_bits n) {
    return rdp_noise_dither_color(n) >> 1;
}

/* RDP span-setup patterns (generic rdp_s* helpers live in rdp_core.h). */
static inline int32_t rdp_grad_diff(int32_t de, int32_t dy) {   /* de*0x180 - dy*0x180 */
    return (int32_t)(((uint32_t)de << 8) + ((uint32_t)de << 7)
                   - ((uint32_t)dy << 8) - ((uint32_t)dy << 7));
}
static inline int32_t rdp_attr_start(int32_t v, int32_t diff, int32_t xfrac, int32_t dxh) {
    return (int32_t)(((uint32_t)(v >> 9) << 9) + (uint32_t)diff
                   - (uint32_t)xfrac * (uint32_t)dxh) & ~0x3ff;
}
static inline int32_t rdp_pix_correct(int32_t v, int32_t sx, int32_t sy) {  /* (v<<2)+sx+sy */
    return (int32_t)(((uint32_t)v << 2) + (uint32_t)sx + (uint32_t)sy);
}

_Static_assert(sizeof(unsigned) == 4, "rdp assumes 32-bit unsigned int");

// Forward declarations: file-internal dispatch targets referenced by the
// tables and span callbacks that are built before their definitions.
static uint16_t rdp_decompress_cvmask_frombyte(rdp_t *rdp, uint8_t x);
static void rdp_render_spans(rdp_t *rdp, int32_t start, int32_t end, int32_t tilenum, bool flip, extent_t* spans, bool rect, rdp_poly_state* object);
static void rdp_write_pixel4(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_write_pixel8(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_write_pixel16(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_write_pixel32(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_read_pixel4(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_read_pixel8(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_read_pixel16(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_read_pixel32(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_copy_pixel4(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object);
static void rdp_copy_pixel8(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object);
static void rdp_copy_pixel16(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object);
static void rdp_copy_pixel32(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object);
static void rdp_span_draw_1cycle(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid);
static void rdp_span_draw_2cycle(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid);
static void rdp_span_draw_copy(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid);
static void rdp_span_draw_fill(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid);
static void rdp_fill_haz_publish(rdp_t *rdp);

static void rdp_fill_haz_pre(rdp_t *rdp, int32_t cmd);
static void rdp_fill_haz_post(rdp_t *rdp, int32_t cmd);

/*****************************************************************************/
/* Unsynced register-write hazard, 1-/2-cycle rectangles.
 *
 * The command processor runs ahead of the pixel pipeline, so a register
 * written without an intervening sync lands part-way through the PREVIOUS
 * primitive. Derived from the snapper64 hardware surfaces (RDPRectNoSync1C /
 * 2C), adjudicated per rect against every reference in both groups at
 * 7332/7332 exact (100.00%).
 *
 * The model is in GCLKs, over the command BOX: W = xl-xh+1 columns by
 * H = yl-yh+1 rows. The final column and row are dead -- they cost pipeline
 * clocks but are never committed, which is the exclusive-xl/yl rule -- so
 * live pixels are (r,c) with r < H-1, c < W-1. With cyc the cycle count per
 * pixel (1 or 2):
 *
 *     L    = max(cyc*W + cyc - 1, 4)      clocks per span
 *     D    = min(3*L - 2, depth) + OFF    clocks of command-processor lead
 *
 *     live pixel (r,c) is emitted at clock   r*L + cyc*c
 *     the primitive's nominal end is         (H-1)*L
 *     the k'th following command executes at (H-1)*L - D + k
 *
 * and a write takes effect at the first live pixel emitted at or after its
 * clock. 3*L - 2 is a three-deep span buffer; depth is the sampling stage's
 * fixed pixel-pipeline latency, the SAME constant in both cycle modes (see
 * below for where it comes from); the floor of 4 on span cost
 * bites only for very narrow spans, and is what collapses all three writes
 * onto one pixel there. Each command costs one clock (n64brew Pipeline: NOPs
 * and attribute setters execute in one pipeline cycle).
 *
 * OFF is 1 when 2-cycle mode consumes the environment colour in the second
 * combiner cycle and not the first, which samples the register one clock
 * later; it is 0 otherwise. In 2-cycle that one clock is what decides which
 * of three consecutive writes survives: with L odd, an even D lands a write
 * exactly on a pixel and the next write one clock later falls through to the
 * following pixel, while an odd D lands between pixels so the next write
 * overwrites it in place. A landing in the dead end-of-line slot collapses
 * all three. Every shape the hardware produces follows from that arithmetic.
 *
 * The primitive is held unqueued until the window closes, collecting the
 * writes that land inside it, then emitted as the base primitive plus one
 * re-render per change. Each re-render carries its own object snapshot, so
 * published objects stay immutable and the worker race-freedom argument is
 * untouched. Sub-scanline boundaries are cut by narrowing the clip rectangle
 * rather than by mutating m_spans: poly_manager_render_extents clamps BOTH
 * endpoints into the clip, so raising min_x moves the left edge whichever of
 * startx/stopx happens to hold it.
 *
 * For the combiner, which samples the environment colour, depth is
 * rdp.pipeline-depth (m_pipeline_depth, 25). Every other register in the n64brew
 * Pipeline table "Effect of unsynced attribute changes" is sampled at its own
 * stage, and the table's offsets give each stage's depth relative to the
 * combiner's (rdp_haz_stage_offset), so a write to it lands with
 *
 *     D(stage) = min(3*L - 2, rdp.pipeline-depth + offset(stage) - offset(combiner))
 *
 * One Set Other Modes write lands at a different pixel for each stage it
 * changes. A stage at offset 0 (the colour image, image_read_en and the Z
 * enables) lands past the last live pixel, so it never reaches the previous
 * primitive, as the table says.
 *
 * Scope: rectangles, 1-/2-cycle. The captures cover the environment colour;
 * the other stages are built from the table alone. Set Convert (the table's
 * "convert" at the combiner's offset) is not collected: its handler drains
 * the span queue. Command-walk thread only; storage is rdp->m_haz (see
 * rdp_core.h). */

/* Cycles of the previous primitive an unsynced write corrupts, 1-cycle and
 * 2-cycle, per stage: n64brew Reality_Display_Processor/Pipeline, "Effect of
 * unsynced attribute changes" (docs/research/rdp-command-timing.md s.3.7).
 * The environment colour sits at the combiner's offset. */
static const int32_t rdp_haz_stage_offset[HAZ_STAGES][2] =
{
    [HAZ_ENV]       = { 24, 22 },
    [HAZ_PERSP]     = {  7,  4 },
    [HAZ_TILE]      = { 13, 10 },
    [HAZ_LOD]       = { 13, 12 },
    [HAZ_SAMPLE]    = { 17, 14 },
    [HAZ_TLUT_EN]   = { 18, 16 },
    [HAZ_TLUT_TYPE] = { 20, 18 },
    [HAZ_MID_TEXEL] = { 21, 18 },
    [HAZ_COMBINE]   = { 24, 22 },
    [HAZ_CVG_ALPHA] = { 25, 24 },
    [HAZ_BLENDER]   = { 26, 24 },
    [HAZ_ZMODE]     = { 27, 26 },
    [HAZ_CVG_DEST]  = { 28, 28 },
    [HAZ_DITHER]    = { 29, 28 },
};

/* Copies the Set Other Modes fields sampled at `stage` from src into dst.
 * The table names the fields; dither_alpha_en goes with alpha_compare_en,
 * the alpha compare it selects the threshold of. */
static void rdp_haz_copy_modes(other_modes_t *dst, const other_modes_t *src, int32_t stage)
{
    switch (stage)
    {
    case HAZ_PERSP:     dst->persp_tex_en = src->persp_tex_en; break;
    case HAZ_LOD:       dst->tex_lod_en = src->tex_lod_en; break;
    case HAZ_SAMPLE:    dst->sample_type = src->sample_type; break;
    case HAZ_TLUT_EN:   dst->en_tlut = src->en_tlut; break;
    case HAZ_TLUT_TYPE: dst->tlut_type = src->tlut_type; break;
    case HAZ_MID_TEXEL: dst->mid_texel = src->mid_texel; break;
    case HAZ_CVG_ALPHA:
        dst->alpha_cvg_select = src->alpha_cvg_select;
        dst->cvg_times_alpha  = src->cvg_times_alpha;
        dst->key_en           = src->key_en;
        dst->z_source_sel     = src->z_source_sel;
        dst->alpha_dither_sel = src->alpha_dither_sel;
        break;
    case HAZ_BLENDER:
        dst->blend_m1a_0 = src->blend_m1a_0; dst->blend_m1a_1 = src->blend_m1a_1;
        dst->blend_m1b_0 = src->blend_m1b_0; dst->blend_m1b_1 = src->blend_m1b_1;
        dst->blend_m2a_0 = src->blend_m2a_0; dst->blend_m2a_1 = src->blend_m2a_1;
        dst->blend_m2b_0 = src->blend_m2b_0; dst->blend_m2b_1 = src->blend_m2b_1;
        break;
    case HAZ_ZMODE:
        dst->z_mode       = src->z_mode;
        dst->force_blend  = src->force_blend;
        dst->blend_shift  = src->blend_shift;
        dst->antialias_en = src->antialias_en;
        break;
    case HAZ_CVG_DEST:
        dst->cvg_dest     = src->cvg_dest;
        dst->color_on_cvg = src->color_on_cvg;
        break;
    case HAZ_DITHER:
        dst->rgb_dither_sel    = src->rgb_dither_sel;
        dst->alpha_compare_en  = src->alpha_compare_en;
        dst->dither_alpha_en   = src->dither_alpha_en;
        dst->alpha_dither_mode = (dst->alpha_compare_en << 1) | dst->dither_alpha_en;
        break;
    }
}

static int rdp_haz_modes_differ(const other_modes_t *a, const other_modes_t *b, int32_t stage)
{
    other_modes_t t = *a;
    rdp_haz_copy_modes(&t, b, stage);
    return memcmp(&t, a, sizeof(t)) != 0;
}

static void rdp_haz_apply(rdp_poly_state *o, const rdp_haz_write *w)
{
    switch (w->stage)
    {
    case HAZ_ENV:
        o->m_env_color = w->v.env.color;
        o->m_env_alpha = w->v.env.alpha;
        break;
    case HAZ_COMBINE:
        o->m_combine = w->v.combine;
        break;
    case HAZ_TILE:
        o->m_tiles[w->tile] = w->v.tile;
        break;
    default:
        rdp_haz_copy_modes(&o->m_other_modes, &w->v.modes, w->stage);
        break;
    }
}

/* Does the given combiner cycle read the environment colour? Environment is
 * mux value 5 in every combiner input field; the 5-bit RGB multiply field
 * additionally selects ENVIRONMENT_ALPHA at 12 (n64brew, Set Combine Mode). */
static int rdp_haz_env_in_cycle(const combine_modes_t *c, int cycle)
{
    if (cycle == 0)
    {
        return c->sub_a_rgb0 == 5 || c->sub_b_rgb0 == 5 ||
               c->mul_rgb0   == 5 || c->mul_rgb0   == 12 ||
               c->add_rgb0   == 5 || c->sub_a_a0   == 5 ||
               c->sub_b_a0   == 5 || c->mul_a0     == 5 ||
               c->add_a0     == 5;
    }

    return c->sub_a_rgb1 == 5 || c->sub_b_rgb1 == 5 ||
           c->mul_rgb1   == 5 || c->mul_rgb1   == 12 ||
           c->add_rgb1   == 5 || c->sub_a_a1   == 5 ||
           c->sub_b_a1   == 5 || c->mul_a1     == 5 ||
           c->add_a1     == 5;
}

static void rdp_haz_publish(rdp_t *rdp)
{
    rdp_haz_state *const h = &rdp->m_haz;
    const rdp_poly_state *prev;
    extent_t *spans;
    poly_render_cb cb;
    int32_t nlines, i, j;

    if (!h->active)
        return;
    h->active = 0;

    spans  = rdp->m_spans;
    cb     = (h->cyc == 1) ? rdp_span_draw_1cycle : rdp_span_draw_2cycle;
    nlines = (h->end - h->start) + 1;

    poly_manager_render_extents(&rdp->m_pool, &h->clip, cb,
        h->start, nlines, spans + h->offset);

    /* Stages land out of command order; a stable sort keeps the writes to
     * one stage in order. */
    for (i = 1; i < h->nseg; i++)
    {
        rdp_haz_write w = h->seg[i];
        for (j = i; j > 0 && h->seg[j - 1].px > w.px; j--)
            h->seg[j] = h->seg[j - 1];
        h->seg[j] = w;
    }

    prev = h->object;
    for (i = 0; i < h->nseg;)
    {
        const int32_t p   = h->seg[i].px;
        const int32_t k   = p / h->w;
        const int32_t col = p - k * h->w;
        rdp_poly_state *o;
        int32_t k2;

        if (p >= h->n || k >= nlines)
            break;

        o = poly_manager_object_next(&rdp->m_pool);
        memcpy(o, prev, sizeof(rdp_poly_state));
        for (; i < h->nseg && h->seg[i].px == p; i++)
            rdp_haz_apply(o, &h->seg[i]);
        prev = o;

        if (col > 0)
        {
            poly_rect c2 = h->clip;
            if (h->lo + col > c2.min_x)
                c2.min_x = h->lo + col;
            poly_manager_render_extents(&rdp->m_pool, &c2, cb,
                h->start + k, 1, spans + h->offset + k);
        }

        k2 = (col > 0) ? (k + 1) : k;
        if (k2 < nlines)
        {
            poly_manager_render_extents(&rdp->m_pool, &h->clip, cb,
                h->start + k2, nlines - k2, spans + h->offset + k2);
        }
    }
}

void rdp_state_quiesce(rdp_t *rdp)
{
    rdp_haz_publish(rdp);
    rdp_fill_haz_publish(rdp);
}

/* The commands an open window collects: the register writes of the table,
 * each one GCLK in the command processor. */
static int rdp_haz_collects(int32_t cmd)
{
    return cmd == 0x3b || cmd == 0x3c || cmd == 0x2f || cmd == 0x35;
}

static void rdp_haz_pre(rdp_t *rdp, int32_t cmd)
{
    rdp_haz_state *const h = &rdp->m_haz;

    if (h->active && !rdp_haz_collects(cmd))
        rdp_haz_publish(rdp);
    if (h->active && cmd == 0x2f)
        h->modes_before = rdp->m_other_modes;

    rdp_fill_haz_pre(rdp, cmd);
}

/* Resolve a command-processor clock to the first LIVE box pixel emitted at or
 * after it, as a box pixel index. Returns -1 when the clock falls past the
 * last live pixel, i.e. the write misses this primitive entirely. A clock
 * landing in a dead end-of-line slot resolves forward to the first pixel of
 * the next row, which is why consecutive writes can collapse. */
static int32_t rdp_haz_land(const rdp_haz_state *h, int32_t t)
{
    int32_t r, rem, c;

    if (t < 0)
        t = 0;

    r   = t / h->span;
    rem = t - r * h->span;
    c   = (rem + h->cyc - 1) / h->cyc;
    if (c > h->w - 2)
    {
        r++;
        c = 0;
    }
    if (r > h->h - 2)
        return -1;

    return r * h->w + c;
}

/*****************************************************************************/
/* Unsynced Set Fill Color hazard, FILL-mode rectangles.
 *
 * Same cause as the 1-/2-cycle case above -- the command processor resumes
 * before the pixel pipeline has drained -- but FILL latches the fill colour
 * once per span, so a write recolours a whole number of trailing rows and
 * never part of one.
 *
 * The model is in GCLK. Writing lambda_j for the latch offset of the row j
 * back from the last, a write landing k GCLK after the command processor
 * resumes recolours every row whose lambda is at or above k. With bpp the
 * colour image's bits per pixel:
 *
 *     ppw  = 64 / bpp                 pixels per 64-bit word
 *     W    = covered 64-bit words
 *     phi  = 1 when (x0 mod ppw) > (x1 mod ppw), else 0
 *     Wc   = W - phi                  words spanned, independent of phase
 *     B    = 64-byte blocks of the colour image the row touches
 *     P    = max(9, Wc + 1)           interior period
 *
 *     B == 1:  L = 35 + W + phi,   G = max(9, 2*W + 6)
 *     B == 2:  L = 34 + phi,       G = W + 5
 *     B >= 3:  L = 51 - 8*B + phi, G = Wc + 1
 *              L is one lower when the row is flush with its blocks
 *
 *     lambda_0     = L
 *     lambda_j     = L - G - (j-1)*P            1 <= j <= h-1
 *     lambda_{h-1} -= E                         first row of the primitive
 *     E            = P - 1, and one less again when G is at its floor
 *
 * The lead keys on the block count, not on the width: the regime changes
 * where a row crosses a 64-byte boundary, and past that the lead is
 * independent of the width. From B = 7 up -- a row longer than 384 bytes,
 * which is any full-width clear -- the lead is negative and no row is
 * reachable.
 *
 * A single-row primitive is its own case: the lead is 21 GCLK regardless of
 * width, and from B = 5 up no row is reachable at all.
 *
 * Scope is FILL-mode rectangles. The arithmetic reads byte addresses rather
 * than pixels, so all four colour image sizes take the same form. */

/* Rows of a FILL rectangle, counted from the last, that take a fill colour
 * written k GCLK after the command processor resumed. */
static int32_t rdp_fill_haz_rows(int32_t fbsize, int32_t x0, int32_t x1,
                                 int32_t h, int32_t k)
{
    static const int32_t bpp_of[4] = { 4, 8, 16, 32 };
    int32_t bpp, ppw, b0, b1, w, phi, wc, blk, per, lead, gap, e, j, n;

    if (h <= 0 || x1 < x0 || k < 0 || (unsigned)fbsize > 3u)
        return 0;

    bpp = bpp_of[fbsize];
    ppw = 64 / bpp;

    b0  = (x0 * bpp) >> 3;
    b1  = (((x1 + 1) * bpp) >> 3) - 1;
    w   = (b1 >> 3) - (b0 >> 3) + 1;
    phi = ((x0 % ppw) > (x1 % ppw)) ? 1 : 0;
    wc  = w - phi;
    blk = (b1 >> 6) - (b0 >> 6) + 1;

    /* One row: the whole steady-state structure is replaced by a fixed lead,
     * and nothing is reachable once the row spans five blocks. */
    if (h == 1)
        return (blk <= 4 && k <= 21) ? 1 : 0;

    per = (wc + 1 > 9) ? (wc + 1) : 9;

    if (blk == 1)
    {
        lead = 35 + w + phi;
        gap  = (2 * w + 6 > 9) ? (2 * w + 6) : 9;
    }
    else if (blk == 2)
    {
        lead = 34 + phi;
        gap  = w + 5;
    }
    else
    {
        lead = 51 - 8 * blk + phi;
        gap  = wc + 1;

        /* A row flush with its blocks at both ends latches its last span one
         * GCLK earlier. */
        if ((b0 & 63) == 0 && ((b1 + 1) & 63) == 0)
            lead--;
    }

    /* The first row of a primitive enters an empty pipeline and latches ahead
     * of the progression of the rows behind it. */
    e = per - 1;
    if (2 * w + 6 < 9)
        e--;
    n = 0;
    for (j = 0; j < h; j++)
    {
        int32_t lam = (j == 0) ? lead : lead - gap - (j - 1) * per;

        if (j == h - 1)
            lam -= e;
        if (lam >= k)
            n++;
    }
    return n;
}

/* GCLK a command occupies while a FILL primitive drains. Negative means the
 * command ends the window: pipeline fences and anything that starts new
 * pipeline work cannot leave a write in flight behind them. */
static int32_t rdp_fill_haz_cost(int32_t cmd)
{
    switch (cmd)
    {
        case 0x26: return 25;   /* Sync Load, documented 25 GCLK stall */
        case 0x27:              /* Sync Pipe -- fence */
        case 0x29:              /* Sync Full -- fence */
        case 0x08: case 0x09: case 0x0a: case 0x0b:
        case 0x0c: case 0x0d: case 0x0e: case 0x0f:
        case 0x24: case 0x25: case 0x36:
        case 0x30: case 0x33: case 0x34:
            return -1;
        default:   return 1;    /* No-op and the attribute setters */
    }
}

static void rdp_fill_haz_publish(rdp_t *rdp)
{
    rdp_fill_haz_state *const f = &rdp->m_fill_haz;
    extent_t *spans;
    int32_t nlines, i;

    if (!f->active)
        return;
    f->active = 0;

    spans  = rdp->m_spans;
    nlines = (f->end - f->start) + 1;

    /* The base primitive first, whole. FILL writes unconditionally, so a
     * recoloured tail is an exact overdraw of the rows it covers and needs no
     * range arithmetic against its predecessor. */
    poly_manager_render_extents(&rdp->m_pool, &f->clip, rdp_span_draw_fill,
        f->start, nlines, spans + f->offset);

    for (i = 0; i < f->nseg; i++)
    {
        const int32_t r = f->seg_row[i];
        rdp_poly_state *o;

        if (r >= nlines)
            break;

        o = poly_manager_object_next(&rdp->m_pool);
        memcpy(o, f->object, sizeof(rdp_poly_state));
        o->m_fill_color = f->seg_fill[i];
        poly_manager_render_extents(&rdp->m_pool, &f->clip,
            rdp_span_draw_fill, f->start + r, nlines - r,
            spans + f->offset + r);
    }
}

static void rdp_fill_haz_pre(rdp_t *rdp, int32_t cmd)
{
    rdp_fill_haz_state *const f = &rdp->m_fill_haz;
    int32_t cost;

    if (!f->active || cmd == 0x37)
        return;

    cost = rdp_fill_haz_cost(cmd);
    if (cost < 0)
    {
        rdp_fill_haz_publish(rdp);
        return;
    }

    f->clock += cost;

    /* Past the largest lead nothing can land. Closing here bounds how long a
     * primitive stays unqueued, which the timed engine needs: it runs the
     * command walk against a live VI rather than between frames. */
    if (f->clock > FILL_HAZ_MAX_LEAD)
        rdp_fill_haz_publish(rdp);
}

static void rdp_fill_haz_post(rdp_t *rdp, int32_t cmd)
{
    rdp_fill_haz_state *const f = &rdp->m_fill_haz;
    int32_t n, row, nlines;

    if (!f->active || cmd != 0x37)
        return;

    nlines = (f->end - f->start) + 1;
    n = rdp_fill_haz_rows(f->fbsize, f->x0, f->x1, f->h, f->clock);
    f->clock++;
    if (f->clock > FILL_HAZ_MAX_LEAD && n <= 0)
    {
        rdp_fill_haz_publish(rdp);
        return;
    }

    if (n <= 0)
    {
        /* The write missed the primitive, and the landing row only moves
         * further back as the clock runs, so nothing later can reach it. */
        rdp_fill_haz_publish(rdp);
        return;
    }

    row = f->h - n;
    if (row < 0)
        row = 0;
    if (row >= nlines || f->nseg >= FILL_HAZ_MAX_SEG)
    {
        rdp_fill_haz_publish(rdp);
        return;
    }

    f->seg_row[f->nseg]  = row;
    f->seg_fill[f->nseg] = rdp->m_fill_color;
    f->nseg++;
}
/*****************************************************************************/

/* Records a write sampled at `stage` from the pixel it lands on. Returns 0
 * when the window is full and has been published. */
static int rdp_haz_push(rdp_t *rdp, int32_t stage, int32_t tile)
{
    rdp_haz_state *const h = &rdp->m_haz;
    rdp_haz_write *w;
    const int32_t px = rdp_haz_land(h, (h->h - 1) * h->span - h->lead[stage] + h->clock);

    if (px < 0)
        return 1;
    if (h->nseg >= HAZ_MAX_SEG)
    {
        rdp_haz_publish(rdp);
        return 0;
    }
    w = &h->seg[h->nseg++];
    memset(w, 0, sizeof(*w));  /* the union's unused bytes */
    w->px    = px;
    w->stage = stage;
    w->tile  = tile;
    switch (stage)
    {
    case HAZ_ENV:
        w->v.env.color = rdp->m_env_color;
        w->v.env.alpha = rdp->m_env_alpha;
        break;
    case HAZ_COMBINE:
        w->v.combine = rdp->m_combine;
        break;
    case HAZ_TILE:
        w->v.tile = rdp->m_tiles[tile];
        break;
    default:
        w->v.modes = rdp->m_other_modes;
        break;
    }
    return 1;
}

static void rdp_haz_post(rdp_t *rdp, int32_t cmd, const uint64_t *cmd_buf)
{
    rdp_haz_state *const h = &rdp->m_haz;
    int ok = 1;
    int32_t stage;

    if (!h->active || !rdp_haz_collects(cmd))
        return;

    switch (cmd)
    {
    case 0x3b: ok = rdp_haz_push(rdp, HAZ_ENV, 0); break;
    case 0x3c: ok = rdp_haz_push(rdp, HAZ_COMBINE, 0); break;
    case 0x35: ok = rdp_haz_push(rdp, HAZ_TILE, (int32_t)(cmd_buf[0] >> 24) & 0x7); break;
    case 0x2f:
        for (stage = HAZ_PERSP; ok && stage < HAZ_STAGES; stage++)
            if (stage != HAZ_TILE && stage != HAZ_COMBINE &&
                rdp_haz_modes_differ(&h->modes_before, &rdp->m_other_modes, stage))
                ok = rdp_haz_push(rdp, stage, 0);
        break;
    }
    if (!ok)
        return;
    h->clock++;

    /* Closed once the deepest stage's next write would miss. */
    if (rdp_haz_land(h, (h->h - 1) * h->span - h->lead_max + h->clock) < 0)
        rdp_haz_publish(rdp);
}

static void rdp_haz_post_all(rdp_t *rdp, int32_t cmd, const uint64_t *cmd_buf)
{
    rdp_haz_post(rdp, cmd, cmd_buf);
    rdp_fill_haz_post(rdp, cmd);
}
/*****************************************************************************/

// Chroma-key alpha (SET_KEY_R / SET_KEY_GB; N64 programming manual, chroma
// key). When keying, the combiner produces (texel - key_center) per channel
// as a signed 17-bit value; this measures its distance from the key against
// the key width. keyalpha is the per-channel minimum, clamped to [0,0xff].
//
// The width is a 4.8 half-width (n64brew RDP/Commands, Set Key R), so the
// comparison lattice sits 0x10 coarser than the combiner output measured
// against it. A positive output is negated to be added to the width term,
// and the borrow out of its low nibble is suppressed when that nibble is
// exactly 0x8 -- the lattice midpoint, where the negation ties -- leaving
// the distance 0x10 above a full two's complement negation. A negative
// output does not tie and is added as it stands.
static inline int32_t chroma_key_channel(int32_t comb, int32_t width)
{
    comb &= 0x1ffff;
    if (comb & 0x10000)
        comb -= 0x20000;    // sign-extend 17-bit

    if (comb > 0)
        comb = ((comb & 0xf) == 8) ? (0x10 - comb) : -comb;

    return (width << 4) + comb;
}
static int32_t rdp_chroma_key_alpha(rdp_t *rdp, const rgbaint_t *combined, rdp_span_aux* userdata)
{
    (void)rdp;
    const int32_t r = chroma_key_channel(rgbaint_get_r32(combined), rgbaint_get_r32(&userdata->m_key_width));
    const int32_t g = chroma_key_channel(rgbaint_get_g32(combined), rgbaint_get_g32(&userdata->m_key_width));
    const int32_t b = chroma_key_channel(rgbaint_get_b32(combined), rgbaint_get_b32(&userdata->m_key_width));

    int32_t keyalpha = (r < g) ? r : g;
    keyalpha = (b < keyalpha) ? b : keyalpha;

    /* Branchless clamp to [0, 0xff]: mask off when negative, then min with 0xff. */
    keyalpha &= ~(keyalpha >> 31);
    keyalpha += (0xff - keyalpha) & ((0xff - keyalpha) >> 31);
    return keyalpha;
}
static int32_t rdp_get_alpha_cvg(rdp_t *rdp, int32_t comb_alpha, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    (void)rdp;
    /* 9-bit promotion: opaque alpha (0xff) becomes 0x100 before the coverage
     * multiply. comb_alpha is pre-clamped to [0,0xff], so this is ParaLLEl-RDP's
     * branchless expanded_alpha = a + ((a + 1) >> 8) (only 0xff carries to 0x100). */
    int32_t temp = comb_alpha + ((comb_alpha + 1) >> 8);
    int32_t temp2 = userdata->m_current_pix_cvg;
    int32_t temp3 = 0;

    if (object->m_other_modes.cvg_times_alpha)
    {
        temp3 = (temp * temp2) + 4;
        userdata->m_current_pix_cvg = (temp3 >> 8) & 0xf;
    }
    if (object->m_other_modes.alpha_cvg_select)
    {
        temp = (object->m_other_modes.cvg_times_alpha) ? (temp3 >> 3) : (temp2 << 5);
    }
    else if (object->m_other_modes.key_en)
    {
        // With chroma keying enabled, the keyed alpha
        // replaces the combined alpha (and no dither seed is added).
        temp = userdata->m_keyalpha;
    }
    /* Branchless min(temp, 0xff): temp is non-negative here. */
    temp += (0xff - temp) & ((0xff - temp) >> 31);
    return temp;
}

/*****************************************************************************/

// (renderer startup lives in rdp.c: rdp_construct +
// rdp_init_internal_state + blender/texpipe init + aux buffer alloc.)

/*****************************************************************************/
void rdp_tc_div_no_perspective(int32_t ss, int32_t st, int32_t sw, int32_t* sss, int32_t* sst)
{
    (void)sw;
    *sss = (SIGN16(ss)) & 0x1ffff;
    *sst = (SIGN16(st)) & 0x1ffff;
}
static const int32_t s_norm_point_rom[64];
static const int32_t s_norm_slope_rom[64];

/* Perspective-divide reciprocal LUT. Everything tc_div derives from W --
 * the normalization shift search, the norm-ROM point/slope lookups and the
 * slope interpolation -- is a pure function of the 15-bit masked W. The
 * tables below hold, for every possible masked W, the exact shift and
 * tlu_rcp the original arithmetic produces (generated at init FROM that
 * arithmetic, so bit-exact by construction). This replaces an up-to-14-step
 * shift-search loop plus two ROM reads and a multiply-add on every divide
 * with two table loads. ~160KB, indexed by span-coherent W values. */
static int32_t s_tcdiv_rcp[0x8000];
static uint8_t s_tcdiv_shift[0x8000];
static bool s_tcdiv_lut_built = false;

static void rdp_tcdiv_lut_init(void)
{
    if (s_tcdiv_lut_built)
        return;
    for (int32_t sw = 0; sw < 0x8000; sw++)
    {
        int32_t shift;
        for (shift = 1; shift <= 14 && !((sw << shift) & 0x8000); shift++);
        shift -= 1;

        int32_t normout = (sw << shift) & 0x3fff;
        int32_t wnorm = (normout & 0xff) << 2;
        normout >>= 8;

        const int32_t temppoint = s_norm_point_rom[normout];
        const int32_t tempslope = s_norm_slope_rom[normout];

        s_tcdiv_rcp[sw] = ((-(tempslope * wnorm)) >> 10) + temppoint;
        s_tcdiv_shift[sw] = (uint8_t)shift;
    }
    s_tcdiv_lut_built = true;
}

void rdp_tc_div(rdp_t *rdp, int32_t ss, int32_t st, int32_t sw, int32_t* sss, int32_t* sst)
{
    (void)rdp;
    int32_t w_carry = 0;
    if ((sw & 0x8000) || !(sw & 0x7fff))
    {
        w_carry = 1;
    }

    sw &= 0x7fff;

    const int32_t shift = s_tcdiv_shift[sw];
    const int32_t tlu_rcp = s_tcdiv_rcp[sw];

    int32_t sprod = rdp_smul(SIGN16(ss), tlu_rcp);
    int32_t tprod = rdp_smul(SIGN16(st), tlu_rcp);
    int32_t tempmask = ((1 << (shift + 1)) - 1) << (29 - shift);
    int32_t shift_value = 13 - shift;

    int32_t outofbounds_s = sprod & tempmask;
    int32_t outofbounds_t = tprod & tempmask;
    if (shift == 0xe)
    {
        *sss = rdp_sshl(sprod, 1);
        *sst = rdp_sshl(tprod, 1);
    }
    else
    {
        *sss = sprod = (sprod >> shift_value);
        *sst = tprod = (tprod >> shift_value);
    }
    //compute clamp flags
    int32_t under_s = 0;
    int32_t under_t = 0;
    int32_t over_s = 0;
    int32_t over_t = 0;

    if (outofbounds_s != tempmask && outofbounds_s != 0)
    {
        if (sprod & (1 << 29))
        {
            under_s = 1;
        }
        else
        {
            over_s = 1;
        }
    }

    if (outofbounds_t != tempmask && outofbounds_t != 0)
    {
        if (tprod & (1 << 29))
        {
            under_t = 1;
        }
        else
        {
            over_t = 1;
        }
    }

    over_s |= w_carry;
    over_t |= w_carry;

    *sss = (*sss & 0x1ffff) | (over_s << 18) | (under_s << 17);
    *sst = (*sst & 0x1ffff) | (over_t << 18) | (under_t << 17);
}
static void rdp_set_suba_input_rgb(rdp_t *rdp, rgbaint_t** input, int32_t code, rdp_span_aux* userdata)
{
    switch (code & 0xf)
    {
        case 0:     *input = &userdata->m_combined_color; break;
        case 1:     *input = &userdata->m_texel0_color; break;
        case 2:     *input = &userdata->m_texel1_color; break;
        case 3:     *input = &userdata->m_prim_color; break;
        case 4:     *input = &userdata->m_shade_color; break;
        case 5:     *input = &userdata->m_env_color; break;
        case 6:     *input = &rdp->m_onecc; break;
        case 7:     *input = &userdata->m_noise_color; break;
        default:    *input = &rdp->m_zero; break;
    }
}
static void rdp_set_subb_input_rgb(rdp_t *rdp, rgbaint_t** input, int32_t code, rdp_span_aux* userdata)
{
    switch (code & 0xf)
    {
        case 0:     *input = &userdata->m_combined_color; break;
        case 1:     *input = &userdata->m_texel0_color; break;
        case 2:     *input = &userdata->m_texel1_color; break;
        case 3:     *input = &userdata->m_prim_color; break;
        case 4:     *input = &userdata->m_shade_color; break;
        case 5:     *input = &userdata->m_env_color; break;
        case 6:     *input = &userdata->m_key_center; break;
        case 7:     *input = &userdata->m_k4; break;
        default:    *input = &rdp->m_zero; break;
    }
}
static void rdp_set_mul_input_rgb(rdp_t *rdp, rgbaint_t** input, int32_t code, rdp_span_aux* userdata)
{
    switch (code & 0x1f)
    {
        case 0:     *input = &userdata->m_combined_color; break;
        case 1:     *input = &userdata->m_texel0_color; break;
        case 2:     *input = &userdata->m_texel1_color; break;
        case 3:     *input = &userdata->m_prim_color; break;
        case 4:     *input = &userdata->m_shade_color; break;
        case 5:     *input = &userdata->m_env_color; break;
        case 6:     *input = &userdata->m_key_scale; break;
        case 7:     *input = &userdata->m_combined_alpha; break;
        case 8:     *input = &userdata->m_texel0_alpha; break;
        case 9:     *input = &userdata->m_texel1_alpha; break;
        case 10:    *input = &userdata->m_prim_alpha; break;
        case 11:    *input = &userdata->m_shade_alpha; break;
        case 12:    *input = &userdata->m_env_alpha; break;
        case 13:    *input = &userdata->m_lod_fraction; break;
        case 14:    *input = &userdata->m_prim_lod_fraction; break;
        case 15:    *input = &userdata->m_k5; break;
        default:    *input = &rdp->m_zero; break;
    }
}
static void rdp_set_add_input_rgb(rdp_t *rdp, rgbaint_t** input, int32_t code, rdp_span_aux* userdata)
{
    switch (code & 0x7)
    {
        case 0:     *input = &userdata->m_combined_color; break;
        case 1:     *input = &userdata->m_texel0_color; break;
        case 2:     *input = &userdata->m_texel1_color; break;
        case 3:     *input = &userdata->m_prim_color; break;
        case 4:     *input = &userdata->m_shade_color; break;
        case 5:     *input = &userdata->m_env_color; break;
        case 6:     *input = &rdp->m_onecc; break;
        case 7:     *input = &rdp->m_zero; break;
    }
}
static void rdp_set_sub_input_alpha(rdp_t *rdp, rgbaint_t** input, int32_t code, rdp_span_aux* userdata)
{
    switch (code & 0x7)
    {
        case 0:     *input = &userdata->m_combined_alpha; break;
        case 1:     *input = &userdata->m_texel0_alpha; break;
        case 2:     *input = &userdata->m_texel1_alpha; break;
        case 3:     *input = &userdata->m_prim_alpha; break;
        case 4:     *input = &userdata->m_shade_alpha; break;
        case 5:     *input = &userdata->m_env_alpha; break;
        case 6:     *input = &rdp->m_onecc; break;
        case 7:     *input = &rdp->m_zero; break;
    }
}
static void rdp_set_mul_input_alpha(rdp_t *rdp, rgbaint_t** input, int32_t code, rdp_span_aux* userdata)
{
    switch (code & 0x7)
    {
        case 0:     *input = &userdata->m_lod_fraction; break;
        case 1:     *input = &userdata->m_texel0_alpha; break;
        case 2:     *input = &userdata->m_texel1_alpha; break;
        case 3:     *input = &userdata->m_prim_alpha; break;
        case 4:     *input = &userdata->m_shade_alpha; break;
        case 5:     *input = &userdata->m_env_alpha; break;
        case 6:     *input = &userdata->m_prim_lod_fraction; break;
        case 7:     *input = &rdp->m_zero; break;
    }
}
static void rdp_set_blender_input(rdp_t *rdp, int32_t cycle, int32_t which, rgbaint_t** input_rgb, rgbaint_t** input_a, int32_t a, int32_t b, rdp_span_aux* userdata)
{
    switch (a & 0x3)
    {
        case 0:
            *input_rgb = cycle == 0 ? &userdata->m_pixel_color : &userdata->m_blended_pixel_color;
            break;

        case 1:
            *input_rgb = &userdata->m_memory_color;
            break;

        case 2:
            *input_rgb = &userdata->m_blend_color;
            break;

        case 3:
            *input_rgb = &userdata->m_fog_color;
            break;
    }

    if (which == 0)
    {
        switch (b & 0x3)
        {
            case 0:     *input_a = &userdata->m_pixel_color; break;
            case 1:     *input_a = &userdata->m_fog_color; break;
            case 2:     *input_a = &userdata->m_shade_color; break;
            case 3:     *input_a = &rdp->m_zero; break;
        }
    }
    else
    {
        switch (b & 0x3)
        {
            case 0:     *input_a = &userdata->m_inv_pixel_color; break;
            case 1:     *input_a = &userdata->m_memory_color; break;
            case 2:     *input_a = &rdp->m_one; break;
            case 3:     *input_a = &rdp->m_zero; break;
        }
    }
}

static uint8_t const s_bayer_matrix[16] =
{ /* Bayer matrix */
    0, 4, 1, 5,
    4, 0, 5, 1,
    3, 7, 2, 6,
    7, 3, 6, 2
};

static uint8_t const s_magic_matrix[16] =
{ /* Magic square matrix */
    0, 6, 1, 7,
    4, 2, 5, 3,
    3, 5, 2, 4,
    7, 1, 6, 0
};

/* ParaLLEl-RDP ordering: dither_matrices[0] = magic, [1] = bayer. */
static uint8_t const * const s_dither_matrix[2] = { s_magic_matrix, s_bayer_matrix };

static z_decompress_entry_t const m_z_dec_table[8] =
{
    { 6, 0x00000 },
    { 5, 0x20000 },
    { 4, 0x30000 },
    { 3, 0x38000 },
    { 2, 0x3c000 },
    { 1, 0x3e000 },
    { 0, 0x3f000 },
    { 0, 0x3f800 },
};

/*****************************************************************************/
static void rdp_z_build_com_table(rdp_t *rdp)
{
    uint16_t altmem = 0;
    for(int32_t z = 0; z < 0x40000; z++)
    {
        switch((z >> 11) & 0x7f)
        {
            case 0x00:
            case 0x01:
            case 0x02:
            case 0x03:
            case 0x04:
            case 0x05:
            case 0x06:
            case 0x07:
            case 0x08:
            case 0x09:
            case 0x0a:
            case 0x0b:
            case 0x0c:
            case 0x0d:
            case 0x0e:
            case 0x0f:
            case 0x10:
            case 0x11:
            case 0x12:
            case 0x13:
            case 0x14:
            case 0x15:
            case 0x16:
            case 0x17:
            case 0x18:
            case 0x19:
            case 0x1a:
            case 0x1b:
            case 0x1c:
            case 0x1d:
            case 0x1e:
            case 0x1f:
            case 0x20:
            case 0x21:
            case 0x22:
            case 0x23:
            case 0x24:
            case 0x25:
            case 0x26:
            case 0x27:
            case 0x28:
            case 0x29:
            case 0x2a:
            case 0x2b:
            case 0x2c:
            case 0x2d:
            case 0x2e:
            case 0x2f:
            case 0x30:
            case 0x31:
            case 0x32:
            case 0x33:
            case 0x34:
            case 0x35:
            case 0x36:
            case 0x37:
            case 0x38:
            case 0x39:
            case 0x3a:
            case 0x3b:
            case 0x3c:
            case 0x3d:
            case 0x3e:
            case 0x3f:
                altmem = (z >> 4) & 0x1ffc;
                break;
            case 0x40:
            case 0x41:
            case 0x42:
            case 0x43:
            case 0x44:
            case 0x45:
            case 0x46:
            case 0x47:
            case 0x48:
            case 0x49:
            case 0x4a:
            case 0x4b:
            case 0x4c:
            case 0x4d:
            case 0x4e:
            case 0x4f:
            case 0x50:
            case 0x51:
            case 0x52:
            case 0x53:
            case 0x54:
            case 0x55:
            case 0x56:
            case 0x57:
            case 0x58:
            case 0x59:
            case 0x5a:
            case 0x5b:
            case 0x5c:
            case 0x5d:
            case 0x5e:
            case 0x5f:
                altmem = ((z >> 3) & 0x1ffc) | 0x2000;
                break;
            case 0x60:
            case 0x61:
            case 0x62:
            case 0x63:
            case 0x64:
            case 0x65:
            case 0x66:
            case 0x67:
            case 0x68:
            case 0x69:
            case 0x6a:
            case 0x6b:
            case 0x6c:
            case 0x6d:
            case 0x6e:
            case 0x6f:
                altmem = ((z >> 2) & 0x1ffc) | 0x4000;
                break;
            case 0x70:
            case 0x71:
            case 0x72:
            case 0x73:
            case 0x74:
            case 0x75:
            case 0x76:
            case 0x77:
                altmem = ((z >> 1) & 0x1ffc) | 0x6000;
                break;
            case 0x78://uncompressed z = 0x3c000
            case 0x79:
            case 0x7a:
            case 0x7b:
                altmem = (z & 0x1ffc) | 0x8000;
                break;
            case 0x7c://uncompressed z = 0x3e000
            case 0x7d:
                altmem = ((z << 1) & 0x1ffc) | 0xa000;
                break;
            case 0x7e://uncompressed z = 0x3f000
                altmem = ((z << 2) & 0x1ffc) | 0xc000;
                break;
            case 0x7f://uncompressed z = 0x3f000
                altmem = ((z << 2) & 0x1ffc) | 0xe000;
                break;
        }

    rdp->m_z_com_table[z] = altmem;

    }
}
static void rdp_precalc_cvmask_derivatives(rdp_t *rdp)
{
    const uint8_t yarray[16] = {0, 0, 1, 0, 2, 0, 1, 0, 3, 0, 1, 0, 2, 0, 1, 0};
    const uint8_t xarray[16] = {0, 3, 2, 2, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0};

    for (int32_t i = 0; i < 0x10000; i++)
    {
        rdp->m_compressed_cvmasks[i] = (i & 1) | ((i & 4) >> 1) | ((i & 0x20) >> 3) | ((i & 0x80) >> 4) |
        ((i & 0x100) >> 4) | ((i & 0x400) >> 5) | ((i & 0x2000) >> 7) | ((i & 0x8000) >> 8);
    }

    for (int32_t i = 0; i < 0x100; i++)
    {
        uint16_t mask = rdp_decompress_cvmask_frombyte(rdp, i);
        rdp->cvarray[i].cvg = rdp->cvarray[i].cvbit = 0;
        rdp->cvarray[i].cvbit = (i >> 7) & 1;
        for (int32_t k = 0; k < 8; k++)
        {
            rdp->cvarray[i].cvg += ((i >> k) & 1);
        }

        uint16_t masky = 0;
        for (int32_t k = 0; k < 4; k++)
        {
            masky |= ((mask & (0xf000 >> (k << 2))) > 0) << k;
        }
        uint8_t offy = yarray[masky];

        uint16_t maskx = (mask & (0xf000 >> (offy << 2))) >> ((offy ^ 3) << 2);
        uint8_t offx = xarray[maskx];

        rdp->cvarray[i].xoff = offx;
        rdp->cvarray[i].yoff = offy;
    }
}
static uint16_t rdp_decompress_cvmask_frombyte(rdp_t *rdp, uint8_t x)
{
    (void)rdp;
    uint16_t y = (x & 1) | ((x & 2) << 1) | ((x & 4) << 3) | ((x & 8) << 4) |
        ((x & 0x10) << 4) | ((x & 0x20) << 5) | ((x & 0x40) << 7) | ((x & 0x80) << 8);
    return y;
}
static void rdp_lookup_cvmask_derivatives(rdp_t *rdp, uint32_t mask, uint8_t* offx, uint8_t* offy, rdp_span_aux* userdata)
{
    const unsigned index = rdp->m_compressed_cvmasks[mask];
    userdata->m_current_pix_cvg = rdp->cvarray[index].cvg;
    userdata->m_current_cvg_bit = rdp->cvarray[index].cvbit;
    *offx = rdp->cvarray[index].xoff;
    *offy = rdp->cvarray[index].yoff;
}
static void rdp_z_store(rdp_t *rdp, const rdp_poly_state *object, uint32_t zcurpixel, uint32_t dzcurpixel, uint32_t z, uint32_t enc)
{
    (void)object;
    unsigned zval = rdp->m_z_com_table[z & 0x3ffff]|(enc >> 2);
    RWRITEIDX16(zcurpixel, zval);
    HWRITEADDR8(dzcurpixel, enc & 3);
}
static int32_t rdp_normalize_dzpix(int32_t sum)
{
    if (sum & 0xc000)
    {
        return 0x8000;
    }
    if (!(sum & 0xffff))
    {
        return 1;
    }
    for(int32_t count = 0x2000; count > 0; count >>= 1)
    {
        if (sum & count)
        {
            return(count << 1);
        }
    }
    return 0;
}
static uint32_t rdp_z_decompress(rdp_t *rdp, uint32_t zcurpixel)
{
    return rdp->m_z_complete_dec_table[(RREADIDX16(zcurpixel) >> 2) & 0x3fff];
}
static uint32_t rdp_dz_decompress(rdp_t *rdp, uint32_t zcurpixel, uint32_t dzcurpixel)
{
    const unsigned zval = RREADIDX16(zcurpixel);
    const unsigned dzval = HREADADDR8(dzcurpixel);
    const unsigned dz_compressed = ((zval & 3) << 2) | (dzval & 3);
    return (1 << dz_compressed);
}
static uint32_t rdp_dz_compress(uint32_t value)
{
    int32_t j = 0;
    for (; value > 1; j++, value >>= 1);
    return j;
}
static void rdp_get_dither_values(rdp_t *rdp, int32_t x, int32_t y, int32_t j, int32_t* cdith, int32_t* adith, const rdp_poly_state *object)
{
    /* Port of ParaLLEl-RDP dither_coefficients (shaders/dither.h). The RGB
     * dither is a packed 9-bit value (3 bits per channel via DITHER_SPLAT for
     * the matrix modes, or the per-channel noise bits); the alpha dither is a
     * single 3-bit value. The noise modes read the LFSRs at the pixel's
     * clock (rdp_pixel_noise). */
    const int32_t idx        = (((y >> object->m_scissor.m_field) & 3) << 2) | (x & 3);
    const int32_t rgb_mode   = object->m_other_modes.rgb_dither_sel;
    const int32_t alpha_mode = object->m_other_modes.alpha_dither_sel;
    rdp_noise_bits noise = {0, 0, 0};
    if (rgb_mode == 2 || alpha_mode == 2)
        noise = rdp_pixel_noise(rdp, j);
    const int32_t DITHER_SPLAT = (1 << 0) | (1 << 3) | (1 << 6);

    if (rgb_mode < 2)
        *cdith = s_dither_matrix[rgb_mode][idx] * DITHER_SPLAT;
    else if (rgb_mode == 2)
        *cdith = (int32_t)rdp_noise_dither_color(noise);
    else
        *cdith = 0;

    if (alpha_mode == 3)
    {
        *adith = 0;
    }
    else if (alpha_mode == 2)
    {
        *adith = (int32_t)rdp_noise_dither_alpha(noise);
    }
    else
    {
        *adith = (rgb_mode >= 2) ? s_dither_matrix[rgb_mode & 1][idx] : (*cdith & 7);
        if (alpha_mode == 1)
            *adith = (~*adith) & 7;
    }
}

static int32_t rdp_clamp32(int32_t v, int32_t min, int32_t max)
{
    if (v < min) return min;
    if (v > max) return max;
    return v;
}
static bool rdp_z_compare(rdp_t *rdp, uint32_t zcurpixel, uint32_t dzcurpixel, uint32_t sz, uint16_t dzpix, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    bool force_coplanar = false;
    sz &= 0x3ffff;

    uint32_t oz;
    uint32_t dzmem;
    uint32_t zval;
    int32_t rawdzmem;

    if (object->m_other_modes.z_compare_en)
    {
        oz = rdp_z_decompress(rdp, zcurpixel);
        dzmem = rdp_dz_decompress(rdp, zcurpixel, dzcurpixel);
        zval = RREADIDX16(zcurpixel);
        rawdzmem = ((zval & 3) << 2) | (HREADADDR8(dzcurpixel) & 3);
    }
    else
    {
        oz = 0;
        dzmem = 1 << 0xf;
        zval = 0x3;
        rawdzmem = 0xf;
    }

    userdata->m_dzpix_enc = rdp_dz_compress(dzpix & 0xffff);
    userdata->m_shift_a = rdp_clamp32(userdata->m_dzpix_enc - rawdzmem, 0, 4);
    userdata->m_shift_b = rdp_clamp32(rawdzmem - userdata->m_dzpix_enc, 0, 4);

    int32_t precision_factor = (zval >> 13) & 0xf;
    if (precision_factor < 3)
    {
        int32_t dzmemmodifier = 16 >> precision_factor;
        if (dzmem == 0x8000)
        {
            force_coplanar = true;
        }
        dzmem <<= 1;
        if (dzmem <= (uint32_t)dzmemmodifier)
        {
            dzmem = dzmemmodifier;
        }
        if (!dzmem)
        {
            dzmem = 0xffff;
        }
    }
    if (dzmem > 0x8000)
    {
        dzmem = 0xffff;
    }

    unsigned dznew = (dzmem > dzpix) ? dzmem : (uint32_t)dzpix;
    unsigned dznotshift = dznew;
    dznew <<= 3;

    bool farther = (sz + dznew) >= oz;
    bool infront = sz < oz;

    if (force_coplanar)
    {
        farther = true;
    }

    bool overflow = ((userdata->m_current_mem_cvg + userdata->m_current_pix_cvg) & 8) > 0;
    userdata->m_blend_enable = (object->m_other_modes.force_blend || (!overflow && object->m_other_modes.antialias_en && farther)) ? 1 : 0;
    userdata->m_pre_wrap = overflow;

    int32_t cvgcoeff = 0;
    unsigned dzenc = 0;

    if (object->m_other_modes.z_mode == 1 && infront && farther && overflow)
    {
        dzenc = rdp_dz_compress(dznotshift & 0xffff);
        cvgcoeff = ((oz >> dzenc) - (sz >> dzenc)) & 0xf;
        userdata->m_current_pix_cvg = ((cvgcoeff * userdata->m_current_pix_cvg) >> 3) & 0xf;
    }

    if (!object->m_other_modes.z_compare_en)
    {
        return true;
    }

    int32_t diff = (int32_t)sz - (int32_t)dznew;
    bool nearer = diff <= (int32_t)oz;
    bool max = (oz == 0x3ffff);
    if (force_coplanar)
    {
        nearer = true;
    }

    switch(object->m_other_modes.z_mode)
    {
    case 0:
        return (max || (overflow ? infront : nearer));
    case 1:
        return (max || (overflow ? infront : nearer));
    case 2:
        return (infront || max);
    case 3:
        return (farther && nearer && !max);
    }

    return false;
}
/* Every caller of rdp_get_log2 passes (lod >> 5) & 0xff, so the domain
 * is 0..255: a 256-entry table replaces the descending bit-scan loop.
 * Entries are exactly what the loop computed: 0 for inputs < 2, otherwise
 * the index of the highest set bit (1..7). */
static const uint8_t s_log2_lut[256] = {
        0, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3,
        4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
};

uint32_t rdp_get_log2(uint32_t lod_clamp)
{
    return s_log2_lut[lod_clamp & 0xff];
}

/*****************************************************************************/
static int32_t const s_rdp_command_length[64] =
{
    8,          // 0x00, No Op
    8,          // 0x01, ???
    8,          // 0x02, ???
    8,          // 0x03, ???
    8,          // 0x04, ???
    8,          // 0x05, ???
    8,          // 0x06, ???
    8,          // 0x07, ???
    32,         // 0x08, Non-Shaded Triangle
    32+16,      // 0x09, Non-Shaded, Z-Buffered Triangle
    32+64,      // 0x0a, Textured Triangle
    32+64+16,   // 0x0b, Textured, Z-Buffered Triangle
    32+64,      // 0x0c, Shaded Triangle
    32+64+16,   // 0x0d, Shaded, Z-Buffered Triangle
    32+64+64,   // 0x0e, Shaded+Textured Triangle
    32+64+64+16,// 0x0f, Shaded+Textured, Z-Buffered Triangle
    8,          // 0x10, ???
    8,          // 0x11, ???
    8,          // 0x12, ???
    8,          // 0x13, ???
    8,          // 0x14, ???
    8,          // 0x15, ???
    8,          // 0x16, ???
    8,          // 0x17, ???
    8,          // 0x18, ???
    8,          // 0x19, ???
    8,          // 0x1a, ???
    8,          // 0x1b, ???
    8,          // 0x1c, ???
    8,          // 0x1d, ???
    8,          // 0x1e, ???
    8,          // 0x1f, ???
    8,          // 0x20, ???
    8,          // 0x21, ???
    8,          // 0x22, ???
    8,          // 0x23, ???
    16,         // 0x24, Texture_Rectangle
    16,         // 0x25, Texture_Rectangle_Flip
    8,          // 0x26, Sync_Load
    8,          // 0x27, Sync_Pipe
    8,          // 0x28, Sync_Tile
    8,          // 0x29, Sync_Full
    8,          // 0x2a, Set_Key_GB
    8,          // 0x2b, Set_Key_R
    8,          // 0x2c, Set_Convert
    8,          // 0x2d, Set_Scissor
    8,          // 0x2e, Set_Prim_Depth
    8,          // 0x2f, Set_Other_Modes
    8,          // 0x30, Load_TLUT
    8,          // 0x31, ???
    8,          // 0x32, Set_Tile_Size
    8,          // 0x33, Load_Block
    8,          // 0x34, Load_Tile
    8,          // 0x35, Set_Tile
    8,          // 0x36, Fill_Rectangle
    8,          // 0x37, Set_Fill_Color
    8,          // 0x38, Set_Fog_Color
    8,          // 0x39, Set_Blend_Color
    8,          // 0x3a, Set_Prim_Color
    8,          // 0x3b, Set_Env_Color
    8,          // 0x3c, Set_Combine
    8,          // 0x3d, Set_Texture_Image
    8,          // 0x3e, Set_Mask_Image
    8           // 0x3f, Set_Color_Image
};

/*****************************************************************************/

static uint32_t rightcvghex(uint32_t x, uint32_t fmask)
{
    unsigned stickybit = ((x >> 1) & 0x1fff) > 0;
    unsigned covered = ((x >> 14) & 3) + stickybit;
    covered = (0xf0 >> covered) & 0xf;
    return (covered & fmask);
}

static uint32_t leftcvghex(uint32_t x, uint32_t fmask)
{
    unsigned stickybit = ((x >> 1) & 0x1fff) > 0;
    unsigned covered = ((x >> 14) & 3) + stickybit;
    covered = 0xf >> covered;
    return (covered & fmask);
}

/* Consolidation of the former compute_cvg_noflip / compute_cvg_flip
 * mirror pair: every difference between them was a left/right edge
 * role swap (which array bounds the purge window, the step length
 * sign, the fringe CLIPs, and which edge takes leftcvghex vs
 * rightcvghex -- the samecvg AND commutes). The callers pass the
 * minor/major arrays in left/right roles according to flip. */
static void rdp_compute_cvg(rdp_t *rdp, rdp_span_aux* userdata, const int32_t* leftx, const int32_t* rightx, const int32_t* leftxint, const int32_t* rightxint, int32_t scanline, int32_t yh, int32_t yl)
{
    (void)rdp;
    int32_t purgestart = 0xfff;
    int32_t purgeend = 0;
    const bool writablescanline = !(scanline & ~0x3ff);
    const int32_t scanlinespx = scanline << 2;

    if (!writablescanline) return;

    for(int32_t i = 0; i < 4; i++)
    {
        if (leftxint[i] < purgestart)
        {
            purgestart = leftxint[i];
        }
        if (rightxint[i] > purgeend)
        {
            purgeend = rightxint[i];
        }
    }

    purgestart = rdp_clamp32(purgestart, 0, 1023);
    purgeend = rdp_clamp32(purgeend, 0, 1023);
    int32_t length = purgeend - purgestart;

    if (length < 0) return;

    memset(&userdata->m_cvg[purgestart], 0, (length + 1) << 1);

    for(int32_t i = 0; i < 4; i++)
    {
        int32_t leftcur = leftx[i];
        int32_t rightcur = rightx[i];
        int32_t leftcurint = leftxint[i];
        int32_t rightcurint = rightxint[i];
        length = rightcurint - leftcurint;

        int32_t fmask = (i & 1) ? 5 : 0xa;
        int32_t maskshift = (i ^ 3) << 2;
        int32_t fmaskshifted = fmask << maskshift;
        /* The interior fill spans the whole 1024-pixel coverage line, as
         * the purge and the per-edge writes above do (all bounded by
         * 0x3ff). A 640-wide bound leaves every interior pixel right of
         * x=647 at zero coverage, which antialias_en then discards
         * (PRDP 16:0/16:1/16:2, 1024-wide RGBA32). */
        int32_t fleft = rdp_clamp32(leftcurint + 1, 0, 1023);
        int32_t fright = rdp_clamp32(rightcurint - 1, 0, 1023);
        bool valid_y = ((scanlinespx + i) >= yh && (scanlinespx + i) < yl);
        if (valid_y && length >= 0)
        {
            if (leftcurint != rightcurint)
            {
                if (!(leftcurint & ~0x3ff))
                {
                    userdata->m_cvg[leftcurint] |= (leftcvghex(leftcur, fmask) << maskshift);
                }
                if (!(rightcurint & ~0x3ff))
                {
                    userdata->m_cvg[rightcurint] |= (rightcvghex(rightcur, fmask) << maskshift);
                }
            }
            else
            {
                if (!(rightcurint & ~0x3ff))
                {
                    int32_t samecvg = leftcvghex(leftcur, fmask) & rightcvghex(rightcur, fmask);
                    userdata->m_cvg[rightcurint] |= (samecvg << maskshift);
                }
            }
            for (; fleft <= fright; fleft++)
            {
                userdata->m_cvg[fleft] |= fmaskshifted;
            }
        }
    }
}

/* Deferred pipeline drain (see the scheduling notes in rdp_poly.h):
 * per-primitive state is snapshotted into the pool-allocated
 * rdp_poly_state and the span aux slots before any work is queued, and
 * render_extents copies every extent into the work units, so queued
 * primitives are self-contained. The renderer therefore only needs to
 * wait for the queue when (a) the command stream is about to mutate
 * state the workers read live -- TMEM, via the load commands, which also
 * read RDRAM that queued primitives may still be writing
 * (render-to-texture) -- (b) completion is externally observable
 * (Sync Full raises the DP interrupt; the end of a command list is when
 * the frontend and every test tool read RDRAM), or (c) the aux/object
 * pools are under pressure. Everything else -- attribute setters, tile
 * descriptors, scissor, othermodes -- is snapshotted and requires no
 * synchronization, which is also how the hardware behaves: the RDP
 * keeps consuming commands while earlier primitives are still in the
 * pixel pipeline. poly_manager_wait early-outs when nothing is queued,
 * so unconditional drains at the hazard points are cheap. */
/* Serialized queue drain: the lock keeps a single threadid-0 waiter at
 * a time (worker state is indexed by threadid). The emulation thread is
 * the only caller, so it never contends. */
static void rdp_wait_locked(rdp_t *rdp)
{
    pthread_mutex_lock(&rdp->m_wait_lock);
    poly_manager_wait(&rdp->m_pool);
    pthread_mutex_unlock(&rdp->m_wait_lock);
}

static void rdp_pipeline_drain(rdp_t *rdp)
{
    rdp_haz_publish(rdp);
    /* Defensive: every current drain site is already preceded by a
     * publish through the hazard cost table (loads, syncs and draws all
     * close the window). */
    rdp_fill_haz_publish(rdp);
    rdp_wait_locked(rdp);
    rdp->m_aux_buf_ptr = 0;
}

/* TMEM load gate: a load mutates TMEM, which queued primitives sample,
 * and reads RDRAM they may still be writing (render-to-texture), so it
 * drains the span queue first. Command-walk thread only. */
static void rdp_tmem_load_gate(rdp_t *rdp)
{
    if (rdp->m_mem_record)
        return;
    rdp_pipeline_drain(rdp);
}

/* A triangle command carries a shade / texture / Z coefficient block only when
 * its flag is set; an absent block is not present in the command stream, so it
 * must contribute 0 rather than the following command's words (reading past the
 * declared length otherwise pulls in the neighbouring command). Force absent
 * blocks to 0 branchlessly: -(present) is 0 or ~0. */
static inline int32_t rdp_tri_attr(bool present, uint64_t x)
{
    return -(int32_t)present & (int32_t)x;
}

/* Triangle coefficient lanes. Every RGBA/STW coefficient is a 16.16 value
 * split across two doublewords -- integer halves in one, fraction halves
 * in the other -- with the channels in descending 16-bit lanes (R/S top,
 * A bottom). So a lane index plus one pair of doubleword offsets names any
 * coefficient. `present` is the command's shade/texture/zbuffer flag;
 * absent blocks read as zero, not as the shorter command's leftovers. */
enum { RDP_TRI_R = 0, RDP_TRI_G = 1, RDP_TRI_B = 2, RDP_TRI_A = 3 };
enum { RDP_TRI_S = 0, RDP_TRI_T = 1, RDP_TRI_W = 2 };
/* doubleword offsets of the (integer, fraction) pair for each gradient */
#define RDP_TRI_START   0, 2
#define RDP_TRI_DX      1, 3
#define RDP_TRI_DE      4, 6
#define RDP_TRI_DY      5, 7

static inline int32_t rdp_tri_coeff(const uint64_t *blk, unsigned ihalf,
    unsigned fhalf, unsigned lane, bool present)
{
    const unsigned sh = 48u - 16u * lane;
    const uint64_t v = (((blk[ihalf] >> sh) & 0xffffu) << 16)
                     |  ((blk[fhalf] >> sh) & 0xffffu);
    return rdp_tri_attr(present, v);
}

/* A triangle command without a shade block still loads the shade registers:
 * every coefficient doubleword read returns the command's header word, so
 * each channel's START, DX, DE and DY registers hold the header's 16-bit
 * lane in both the integer and fraction halves. The R lane therefore
 * carries lft/level/tile, G carries yl, B carries ym and A carries yh, and
 * the walked shade is the plane those registers define. (Hardware:
 * snapper64 "RDP Undefined Shade 1C", bit-exact across the group.)
 * Measured for triangle commands only; the synthesized rectangle setups
 * pass hdr 0 and keep reading zero. */
static inline int32_t rdp_tri_shade_coeff(const uint64_t *blk, unsigned ihalf,
    unsigned fhalf, unsigned lane, bool present, uint64_t hdr)
{
    if (present)
        return rdp_tri_coeff(blk, ihalf, fhalf, lane, true);
    const uint32_t hl = (uint32_t)(hdr >> (48u - 16u * lane)) & 0xffffu;
    return (int32_t)((hl << 16) | hl);
}

/* ---- FILL-mode triangle burst model -----------------------------------
 *
 * Hardware does not fill a triangle span as one contiguous run: the fill
 * unit is driven by an internal subpixel resume pointer whose trajectory
 * splits many scanlines into a first burst plus a trailing tail, inserts
 * fragment rows around the terminal region, and gates the end-word byte
 * enables on comparators over span-start history. The model below was
 * reverse-engineered exclusively from the snapper64 hardware reference
 * captures (RDP Fill Mode Tri Sweep, RGBA32) and adjudicated per row
 * against the capture database at 96960/96960 row exactness (100.00%);
 * it applies to fill-mode triangles whose minor edges do not move in X
 * (dxhdy == dxmdy == 0) and whose spans walk right-to-left (lmajor
 * clear), the family the hardware data covers: a vertical h/m edge on
 * the right, a moving l edge on the left. With lmajor set the geometry
 * is mirrored -- the vertical edge is on the left and the moving edge
 * drives the right terminus -- and the span extents arrive reversed
 * (startx is the screen-right column), so neither the machine's driver
 * nor its word geometry holds. Other fill triangles keep the
 * single-burst byte-enable path in rdp_span_draw_fill.
 *
 * The machine's state is sequential across a primitive's scanlines, so it
 * runs on the command-processing thread during edge walking and attaches a
 * per-span write plan to the span's aux slot; the (parallel) span workers
 * execute the plan verbatim. Rendering therefore stays thread-invariant.
 *
 * The machine's block tests -- the arming and fragment comparators on
 * px & 15, the edge landings on (xl >> 16) & 15, and the block indices
 * xl >> 20 -- are all anchored at the row's column 0, and read it as a
 * 64 byte block boundary. That holds for every row only when the color
 * image base and its pitch are themselves block-aligned, hence the
 * gate: fb_address % 64 == 0 and fb_width % 16 == 0. Off that grid the
 * block phase differs per row and the cross-row index differences stop
 * meaning anything, so the model declines and the span takes the
 * generic write law instead.
 *
 * The gate is an evidence boundary, not a hardware one. Whether the
 * block grid is RDRAM-absolute or restarts at each row is undetermined:
 * the captures are block-aligned, where the two readings coincide. An
 * unaligned pitch separates them.
 *
 * Family B needs none of this. Every quantity it carries is anchored at
 * the scissor column or at a span terminus and its drops are pointer
 * deltas, so nothing it computes depends on where the row sits in the
 * block grid; its own gate covers only the word alignment its trim
 * parities need.
 *
 * Machine summary (px = pixels, values 16.16 unless noted; W0/W1 = 64-bit
 * word index of span start/end, words relative to the row base):
 *  - Arming: the first span whose start pixel lands on a 16 px block
 *    boundary arms the machine; the resume pointer seeds 2*W1 + 19 px
 *    above the row base with the clipped edge's fraction.
 *  - Every armed row applies the PREVIOUS row's clipped-edge advance
 *    (lagged climb), then the drop machinery: an onset staircase
 *    (T = 2 -> -28 -> -12) of strict comparators over 2*W1 + T + 1 px,
 *    then a steady phase (T == -12) driven by lagged RAW-edge block
 *    crossings with per-crossing 16 px drops gated at 2*W1 - 20 px and
 *    a forced drop for rows entering below the 2*W1 - 28 window floor.
 *    Scissor-clip release rows, fast unclipped arms and T == 2
 *    multi-drop signatures take their own drop shapes.
 *  - Burst rows split into first burst [W0 .. E] (E snapped 8 words
 *    below the resume word S = R >> 17) and a tail [S .. W1] with a
 *    parity-selected partial first word; the tail trims to W1 - 7 on
 *    the row the pointer climbs off the window bottom (grazing entries
 *    relax the boundary), the tail end word keeps the close byte on
 *    stalled and deep-entry head landings, and narrow spans take the
 *    dead-zone fallback (blank when the pointer overshoots the close
 *    word; the last row takes its own trims and composites).
 *  - Terminal (S <= W0): an entry row (with an open trim when the
 *    pre-drop pointer lands one pixel below the span start, and the
 *    -29 lattice anti-drop write shape on non-last entries), fragment
 *    rows, blank/emit gating after T == 2 entries, a FIFO partial
 *    queue that flushes launch-band partials into later rows, k=0
 *    close suppression with last-row and aged refinements, and re-arm
 *    one row after a fresh block landing (postterm rows then take the
 *    trim-fragment shapes).
 */

typedef struct fill_burst_state
{
    int      active;
    int      armed;
    int64_t  R;              /* subpixel resume pointer, px units, 16.16 */
    int64_t  climb_pending;  /* previous row's clipped-edge advance */
    int      T;              /* staircase phase: 2, -28, -12 */
    int64_t  xl_prev, xl_prev2, xl_prev3;   /* clipped left edge history */
    int64_t  xlr_prev, xlr_prev2;           /* raw (wrapped) left edge history */
    int      terminal;       /* -1 = not terminal; else rows since entry */
    int      rearm_pending;
    int64_t  park;
    int64_t  tfrag_ref;
    int      tfrag_gate;
    int      tfrag_first;
    int32_t  prev_px0;       /* previous span's start pixel */
    int32_t  prev_px0_2;     /* span start two rows back */
    int64_t  prev_S;         /* previous burst row's resume word */
    int32_t  prev_W1;
    int64_t  term_pdR;       /* previous terminal row's pre-drop dR */
    int      term_pRodd;     /* previous terminal row's pre-drop parity */
    int      postterm;       /* row after a terminal re-arm */
    int      rel2;           /* T==2 clip-release signature latched */
    int      rel2lo;         /* ... with the low-edge variant */
    int      just_armed;     /* the arm happened on the previous row */
    int      t2cross;        /* T==2-transition entry latch (blank gate) */
} fill_burst_state;

#define FILL_BURST_NONE64  INT64_MIN
#define FILL_BURST_NONE32  INT32_MIN

/* k=0 close suppression thresholds (raw sub3-sub0 spread, 16.16):
 * KZ_REARM 2.500 px, bracket [160782, 164694];
 * KZ_TERM ~4.92 px, bracket [321732, 323532], last row, term <= 2. */
#define FILL_BURST_KZ_REARM  163840
#define FILL_BURST_KZ_TERM   322560

static uint8_t fill_burst_open_mask(int32_t px0)
{
    return (px0 & 1) ? 0xf8u : 0xffu;
}

static uint8_t fill_burst_close_mask(int32_t px1)
{
    return (px1 & 1) ? 0x01u : 0x1fu;
}

/* The empty plan, and the initializer every other plan builds on: the
 * aux pool is never cleared, so every field the executor can reach is
 * written here rather than left as residue from an earlier span. Both
 * runs are empty (lo > hi), so the trim bytes are unreachable on a
 * blank plan and their values are arbitrary; writing them keeps the
 * record self-describing. */
static void fill_burst_plan_blank(rdp_span_aux *ud)
{
    ud->m_fill_plan = 1;
    ud->m_fill_b1lo = 1;
    ud->m_fill_b1hi = 0;
    ud->m_fill_open  = 0xffu;
    ud->m_fill_close = 0xffu;
    ud->m_fill_pw   = -1;
    ud->m_fill_pm   = 0;
    ud->m_fill_t2lo = 1;
    ud->m_fill_t2hi = 0;
    ud->m_fill_t2close = 0xffu;
}

static void fill_burst_plan_run1(rdp_span_aux *ud, int32_t lo, int32_t hi,
                                 uint8_t open_be, uint8_t close_be)
{
    fill_burst_plan_blank(ud);
    ud->m_fill_b1lo  = (int16_t)lo;
    ud->m_fill_b1hi  = (int16_t)hi;
    ud->m_fill_open  = open_be;
    ud->m_fill_close = close_be;
}

/* The pre-arm span pattern: a single burst [W0 .. W1] with parity trims at
 * both ends (a one-word span intersects them). */
static void fill_burst_plan_normal(rdp_span_aux *ud, int32_t W0, int32_t W1,
                                   int32_t px0, int32_t px1)
{
    if (W1 < W0)
    {
        fill_burst_plan_blank(ud);
        return;
    }
    fill_burst_plan_run1(ud, W0, W1, fill_burst_open_mask(px0),
                         fill_burst_close_mask(px1));
}

/* FILL-mode triangle burst model, family B: fixed left edge, moving right
 * (h/m) edge (dxldy == 0, dxhdy/dxmdy != 0, lft == 0), adjudicated against
 * the snapper64 Fill Mode Tri Sweep hardware captures (96960/96960 rows
 * exact over 1024 traces). The mechanism engages when the raw right edge
 * runs off the scissor:
 *  - From the first row where any valid subline's raw right edge reaches
 *    the scissor column, the rendered span end is min(raw, clipx2)
 *    (inclusive of the scissor column itself, one past the normal clamp).
 *  - The machine arms when the last subline's integer X passes the
 *    scissor column (r3i >= clipx2 + 1). A resume pointer R rides a
 *    reference line, line = 2*clipx2 - 32 - even(r3i of the previous
 *    row), starting D = 48 px above it and dropping 16 px per row
 *    (D = max(D - 16, 0); R = line + D).
 *  - Burst rows: first burst [W0 .. E] with the opening trim suppressed,
 *    close trim from the scissor column parity at E = W1c - 8 *
 *    ceil((W1c - (S - 2)) / 8) for S = R >> 1; a parity partial at S and
 *    a full tail to the clamped raw end. Writes clamp at the row's last
 *    framebuffer word; nothing wraps.
 *  - Adjacency: once D <= 16 and r3i >= clipx2 + 8, rows render the
 *    first burst immediately followed by the tail (no gap, no partial),
 *    with R parked 16 px above the line and E anchored at S - 1.
 *  - The machine ends at r3i >= clipx2 + 24 (r3i >= clipx2 + 40 when
 *    already past at arming; single-sided bracket [40, 44] from the
 *    captures), on the final row of the window, and on rows whose last
 *    subline is invalid: those rows render the full row.
 *  - If the arming row is the final row, the machine's first burst row
 *    flushes into the same row's write stream (visible as the tail
 *    partial OR'd over the close trim when S lands on the last word). */
typedef struct fill_famb_state
{
    int      active;
    int      phase;          /* 0 pre-arm, 1 machine, 2 park, 3 done */
    int32_t  D;              /* px above the reference line */
    int32_t  prev_r3i;       /* previous row's last-subline integer X */
    int32_t  clip;           /* scissor right column (m_xl_raw >> 2) */
    int32_t  w1c;            /* last plan word: min(clip >> 1, row words - 1) */
    int32_t  lastj;          /* final row of the render window */
    int32_t  w1row;          /* last word of the framebuffer row */
} fill_famb_state;

static void fill_famb_plan(rdp_span_aux *ud, int32_t b1lo, int32_t b1hi,
                           uint8_t open_be, uint8_t close_be,
                           int32_t pw, uint8_t pm, int32_t t2lo, int32_t t2hi)
{
    ud->m_fill_plan  = 1;
    ud->m_fill_b1lo  = (int16_t)b1lo;
    ud->m_fill_b1hi  = (int16_t)b1hi;
    ud->m_fill_open  = open_be;
    ud->m_fill_close = close_be;
    ud->m_fill_pw    = (int16_t)pw;
    ud->m_fill_pm    = pm;
    ud->m_fill_t2lo  = (int16_t)t2lo;
    ud->m_fill_t2hi  = (int16_t)t2hi;
    /* The aux pool is never cleared and the executor consults the
     * family-A tail close byte on every plan: default it off. */
    ud->m_fill_t2close = 0xffu;
}

/* Anchored single-burst span [px0 .. px1]: nwr = ceil(npx / 2) words ending
 * at the word of the last pixel byte (the committed fill write law). */
static void fill_famb_plan_normal(rdp_span_aux *ud, int32_t px0, int32_t px1,
                                  int32_t w1row, int noopen)
{
    const int32_t npx = px1 - px0 + 1;
    if (npx <= 0)
    {
        fill_burst_plan_blank(ud);
        return;
    }
    int32_t wlast  = px1 >> 1;
    int32_t wfirst = wlast - ((npx + 1) / 2 - 1);
    uint8_t open_be  = noopen ? 0xffu : fill_burst_open_mask(px0);
    uint8_t close_be = fill_burst_close_mask(px1);
    /* Writes clamp at the row bounds; a trim word that falls outside the
     * row is dropped, not migrated to the boundary word. */
    if (wlast > w1row)
    {
        wlast = w1row;
        close_be = 0xffu;
    }
    if (wfirst < 0)
    {
        wfirst = 0;
        open_be = 0xffu;
    }
    fill_famb_plan(ud, wfirst, wlast, open_be, close_be, -1, 0u, 1, 0);
}

/* Block snap, shared by both fill-triangle families: the last word at
 * or below w1c that sits a whole number of 8-word blocks below the
 * resume word S, taken from S - anchor. The burst's first run ends
 * here; anchor selects how far under the resume word the snap starts
 * (2 for a gapped burst, 1 for the adjacent-tail regime). */
static int64_t fill_burst_e_snap(int64_t S, int64_t anchor, int64_t w1c)
{
    if (S - anchor >= w1c)
        return w1c;
    const int64_t dd = w1c - (S - anchor);
    return w1c - 8 * ((dd + 7) / 8);
}

static void fill_famb_row(fill_famb_state *st, int anyvalid,
                          int32_t px0, int32_t xr_raw_max, int32_t xr_raw3,
                          int r3_valid, int32_t j, rdp_span_aux *ud)
{
    if (!anyvalid)
    {
        /* Invalid scanline: nothing rendered, machine state frozen. */
        fill_burst_plan_blank(ud);
        return;
    }

    const int32_t clip = st->clip;
    const int32_t w1c = st->w1c;
    const int32_t W0 = px0 >> 1;
    const int32_t b1lo0 = W0 < 0 ? 0 : W0;
    const uint8_t cmask = fill_burst_close_mask(clip);
    const int32_t r3 = r3_valid ? xr_raw3 : xr_raw_max;
    const int32_t r3i = r3 >> 16;

    if (st->phase == 0)
    {
        const int32_t rmi = xr_raw_max >> 16;
        if (r3i >= clip + 1)
        {
            st->phase = 1;
            st->D = 48;
            if (r3i >= clip + 40)
            {
                /* Already far past the scissor at arming: straight to the
                 * terminal full-row regime. */
                st->phase = 3;
                fill_famb_plan(ud, b1lo0, w1c, 0xffu, 0xffu, -1, 0u, 1, 0);
            }
            else if (j == st->lastj)
            {
                /* Final-row arming: the machine's first burst row flushes
                 * into this row's write stream. Its close trim and gap all
                 * land inside the full run; only a tail partial on the
                 * last word stays visible. */
                const int32_t line0 = 2 * clip - 32 - (r3i & ~1);
                const int32_t R0 = line0 + 32;
                const int32_t S0 = R0 >> 1;
                const int32_t px1 = rmi < clip ? rmi : clip;
                const int32_t npx = px1 - px0 + 1;
                if (npx <= 0)
                {
                    fill_burst_plan_blank(ud);
                }
                else
                {
                    int32_t wlast = px1 >> 1;
                    int32_t wfirst = wlast - ((npx + 1) / 2 - 1);
                    if (wfirst > b1lo0) wfirst = b1lo0;
                    if (wfirst < 0) wfirst = 0;
                    uint8_t close_be = fill_burst_close_mask(px1);
                    if (wlast > st->w1row)
                    {
                        wlast = st->w1row;
                        close_be = 0xffu;
                    }
                    if (S0 < w1c)
                        close_be = 0xffu;
                    else if (S0 == w1c)
                        close_be |= (R0 & 1) ? 0x80u : 0xf8u;
                    fill_famb_plan(ud, wfirst, wlast, 0xffu, close_be,
                                   -1, 0u, 1, 0);
                }
            }
            else
            {
                fill_famb_plan_normal(ud, px0, rmi < clip ? rmi : clip,
                                      st->w1row, 1);
            }
        }
        else if (rmi >= clip)
        {
            /* Scissor-touch quirk: the rendered end is the scissor column
             * itself, one past the normal exclusive clamp. */
            fill_famb_plan_normal(ud, px0, clip, st->w1row, 0);
        }
        /* else: default single-burst path (plan 0), identical output. */
        st->prev_r3i = r3i;
        return;
    }

    if (!r3_valid || j == st->lastj)
    {
        /* Partial or final row: the full row renders; the machine state
         * itself does not advance to the terminal regime. */
        fill_famb_plan(ud, b1lo0, w1c, 0xffu, 0xffu, -1, 0u, 1, 0);
        st->prev_r3i = r3i;
        return;
    }

    if (st->phase == 3 || r3i >= clip + 24)
    {
        st->phase = 3;
        fill_famb_plan(ud, b1lo0, w1c, 0xffu, 0xffu, -1, 0u, 1, 0);
        st->prev_r3i = r3i;
        return;
    }

    const int32_t line = 2 * clip - 32 - (st->prev_r3i & ~1);

    if (st->phase == 2)
    {
        const int32_t R = line + 16;
        const int32_t S = R >> 1;
        const int32_t E = (int32_t)fill_burst_e_snap(S, 1, w1c);
        fill_famb_plan(ud, b1lo0, E < b1lo0 ? b1lo0 - 1 : E, 0xffu, cmask,
                       -1, 0u,
                       (E + 1) > b1lo0 ? (E + 1) : b1lo0, w1c);
        st->prev_r3i = r3i;
        return;
    }

    /* Phase 1: staircase onto the line. */
    st->D = st->D > 16 ? st->D - 16 : 0;
    const int32_t R = line + st->D;
    const int32_t S = R >> 1;
    const int32_t E = (int32_t)fill_burst_e_snap(S, 2, w1c);

    if (st->D <= 16 && r3i >= clip + 8)
    {
        st->phase = 2;
        fill_famb_plan(ud, b1lo0, E < b1lo0 ? b1lo0 - 1 : E, 0xffu, cmask,
                       -1, 0u,
                       (E + 1) > b1lo0 ? (E + 1) : b1lo0, w1c);
    }
    else if (S > w1c)
    {
        fill_famb_plan_normal(ud, px0, clip, st->w1row, 1);
    }
    else
    {
        const int32_t rmw = xr_raw_max >> 17;
        const int32_t w1m = rmw < w1c ? rmw : w1c;
        int32_t pw = -1;
        uint8_t pm = 0u;
        int32_t t2lo = S;
        if (S <= w1m && S >= W0 && S >= 0)
        {
            pw = S;
            pm = (R & 1) ? 0x80u : 0xf8u;
            t2lo = S + 1;
        }
        if (t2lo < b1lo0) t2lo = b1lo0;
        fill_famb_plan(ud, b1lo0, E < b1lo0 ? b1lo0 - 1 : E, 0xffu, cmask,
                       pw, pm, t2lo, S <= w1m ? w1m : t2lo - 1);
    }
    st->prev_r3i = r3i;
}

/* Python-semantics modulo (non-negative result) for the last-row block
 * drop lattice test. */
static int64_t fill_burst_mod16(int64_t x)
{
    int64_t m = x % 16;
    return (m < 0) ? m + 16 : m;
}

/* Drop the resume pointer by 16 px while it sits at or above limit_px,
 * at most maxdrops times (maxdrops < 0 = unlimited). Every drop loop in
 * the machine is this comparator with a different (limit, count) pair. */
static void fill_burst_drop_while(fill_burst_state *st, int64_t limit_px,
                                  int64_t maxdrops)
{
    while (maxdrops != 0 && (st->R >> 16) >= limit_px)
    {
        st->R -= (int64_t)16 << 16;
        maxdrops--;
    }
}

/* Seed (or re-seed) the burst pointer and staircase at an arm point:
 * R = 2*W1 + 19 px above the row base (+ the clipped edge's fraction on
 * a first arm; a terminal re-arm seeds at the integer), lagged climb
 * cleared, edge history rotated, T = 2. */
static void fill_burst_seed(fill_burst_state *st, int32_t W1,
                            int64_t xl_now, int64_t xlr_now, int with_frac)
{
    st->R = ((int64_t)(2 * W1 + 19) << 16) +
            (with_frac ? (xl_now & 0xffff) : 0);
    st->climb_pending = 0;
    st->xl_prev2 = st->xl_prev;
    st->xl_prev = xl_now;
    st->xlr_prev2 = st->xlr_prev;
    st->xlr_prev = xlr_now;
    st->T = 2;
}

/* Terminal FIFO flush comparator: a partial queued while the live R sat
 * in the [2*W1-16, 2*W1-15] launch band flushes into the current row's
 * stream when R vaults to >= 2*W1-13, landing at W1 with the LAUNCH
 * row's Rpx parity (pdR=-15 -> 0x80, pdR=-16 -> 0xf8). 121/121 with
 * 0/204 at pdR=-14 and 0/29 at pdR<=-17 in refs. */
static int fill_burst_fifo_flush(const fill_burst_state *st, int64_t dR_now)
{
    return st->term_pdR != FILL_BURST_NONE64 &&
           (st->term_pdR == -16 || st->term_pdR == -15) &&
           dR_now >= -13;
}

/* Dead-zone routed fragment emission (terminal fragment rows and the
 * postterm descent share it verbatim): the trimmed fragment W0 .. W1-7
 * where it fits, the full close run at width <= 5 words, blank in the
 * 6-7 word gap. */
static void fill_burst_plan_deadzone(rdp_span_aux *ud, int32_t W0,
                                     int32_t W1, uint8_t open_be,
                                     int32_t px1)
{
    if (W1 - 7 >= W0)
        fill_burst_plan_run1(ud, W0, W1 - 7, open_be, 0xffu);
    else if (W1 - W0 <= 4)
        fill_burst_plan_run1(ud, W0, W1, 0xffu,
                             fill_burst_close_mask(px1));
    else
        fill_burst_plan_blank(ud);
}

static void fill_burst_row(fill_burst_state *st, int anyvalid,
                           int32_t px0, int32_t px1,
                           int64_t xl_now, int64_t xlr_now,
                           int32_t spread, int is_last, rdp_span_aux *ud)
{
    if (!anyvalid)
    {
        /* Invalid scanline: nothing rendered, machine state frozen. */
        fill_burst_plan_blank(ud);
        return;
    }

    const int32_t W0 = px0 >> 1;
    const int32_t W1 = px1 >> 1;
    const int32_t pp = st->prev_px0;     /* previous span's start pixel */
    const int32_t pp2 = st->prev_px0_2;  /* two rows back */
    st->prev_px0_2 = pp;
    st->prev_px0 = px0;

    /* One-pixel spans render only when the span start moved by 2+ px. */
    if (px0 == px1 && (pp == FILL_BURST_NONE32 || px0 - pp < 2))
    {
        fill_burst_plan_blank(ud);
        return;
    }

    if (!st->armed)
    {
        fill_burst_plan_normal(ud, W0, W1, px0, px1);
        if ((px0 & 15) == 0)
        {
            /* Arm: the arming row itself renders the normal single-burst
             * pattern. */
            st->armed = 1;
            st->just_armed = 1;
            fill_burst_seed(st, W1, xl_now, xlr_now, 1);
        }
        else
        {
            st->xl_prev = xl_now;
            st->xlr_prev = xlr_now;
        }
        return;
    }

    const int64_t R_entry_px = st->R >> 16;
    const int T_entry = st->T;

    /* Clip-release catch-up climb: on the row after a scissor-
     * clip release (clamped edge stationary two rows back: xl_prev2 ==
     * xl_prev3, and moving again: xl_prev > xl_prev2) at T == -28, the
     * FIFO climb catches up to the LIVE edge instead of the lagged one
     * iff the previous edge's subpixel sits in the low band
     * ((xl_prev >> 12) & 7 <= 2). 5/5 catch-up vs 6/6 lagged in refs. */
    const int relsig = (st->T == -28 && st->xl_prev2 != FILL_BURST_NONE64 &&
                        st->xl_prev3 != FILL_BURST_NONE64 &&
                        st->xl_prev2 == st->xl_prev3 &&
                        st->xl_prev > st->xl_prev2 &&
                        st->xlr_prev != FILL_BURST_NONE64 &&
                        st->xlr_prev2 != FILL_BURST_NONE64 &&
                        st->xlr_prev - st->xlr_prev2 >= ((int64_t)16 << 16));
    if (relsig && ((st->xl_prev >> 12) & 7) <= 2)
        st->climb_pending = xl_now - st->xl_prev2;

    /* T==2 clip-release multi-drop signature: edge was scissor-
     * clamped two rows back (clamped != raw), released last row (clamped
     * == raw), fast raw slope. Computed pre-rotation. */
    const int relsig2 = (st->T == 2 && st->xl_prev2 != FILL_BURST_NONE64 &&
                         st->xlr_prev2 != FILL_BURST_NONE64 &&
                         st->xl_prev2 != st->xlr_prev2 &&
                         st->xl_prev == st->xlr_prev &&
                         st->xlr_prev - st->xlr_prev2 >= ((int64_t)16 << 16));
    const int rel2lo_now = st->rel2lo;

    /* Fast first-armed-row: when the arm row was NOT clipped
     * (xl_prev == xlr_prev) and the live edge delta is fast (>= 12 px;
     * corpus bracket (8, 14.78], clean band [10, 14]), the first armed
     * row climbs by the live delta instead of the arm zero, and the drop
     * is the per-compare multi-drop at Tpx. 2/2 in refs; clipped arms
     * excluded (their release machinery owns those rows). */
    const int ja = st->just_armed;
    st->just_armed = 0;
    int fastarm = 0;
    if (ja && st->xl_prev != FILL_BURST_NONE64 &&
        st->xlr_prev != FILL_BURST_NONE64 &&
        st->xl_prev == st->xlr_prev &&
        (xl_now - st->xl_prev) >= ((int64_t)12 << 16))
    {
        st->climb_pending = xl_now - st->xl_prev;
        fastarm = 1;
    }
    if (relsig2)
    {
        st->rel2 = 1;
        if (st->xl_prev < ((int64_t)16 << 16))
            st->rel2lo = 1;
    }
    if (rel2lo_now && st->T == 2)
    {
        st->rel2lo = 0;
        st->climb_pending = xl_now - st->xl_prev2;
    }

    /* Apply the lagged climb; the crossing features below are computed
     * from the PRE-rotation edge history (a twice-hit lag trap). */
    st->R += st->climb_pending;
    const int64_t Rpx_preT = st->R >> 16;

    int64_t nblocks = 0;
    if (st->xl_prev2 != FILL_BURST_NONE64)
    {
        nblocks = (st->xl_prev >> 20) - (st->xl_prev2 >> 20);
        if (nblocks < 0)
            nblocks = 0;
    }
    const int rawcrossed_lag = (st->xlr_prev2 != FILL_BURST_NONE64) &&
        ((st->xlr_prev >> 20) != (st->xlr_prev2 >> 20));
    int64_t rawnblocks = 0;
    if (st->xlr_prev2 != FILL_BURST_NONE64)
    {
        rawnblocks = (st->xlr_prev >> 20) - (st->xlr_prev2 >> 20);
        if (rawnblocks < 0)
            rawnblocks = 0;
    }
    st->climb_pending = xl_now - st->xl_prev;
    st->xl_prev3 = st->xl_prev2;
    st->xl_prev2 = st->xl_prev;
    st->xl_prev = xl_now;
    st->xlr_prev2 = st->xlr_prev;
    st->xlr_prev = xlr_now;

    if (st->T == -12)
    {
        /* T=-12 steady-phase drops, three parts pinned by hardware refs:
         *  (a) the drop gate is strictly Rpx > 2*W1 - 20: rows parked at
         *      exactly 2*W1 - 20 with a crossing take no drop (5/5),
         *  (b) multi-crossing rows take one 16 px drop per crossing, each
         *      drop individually gated on the CURRENT Rpx (6/6 incl. a
         *      2-crossing row that takes both),
         *  (c) if the pointer ENTERED the row below the window floor
         *      2*W1 - 28, one drop is forced even without a crossing
         *      (3/3; the same gate excludes slow steady rows since a
         *      small climb from below the floor cannot exceed
         *      2*W1 - 20). */
        fill_burst_drop_while(st, 2 * W1 - 19,
                              rawcrossed_lag ? rawnblocks
                              : ((R_entry_px < 2 * W1 - 28) ? 1 : 0));
    }
    else
    {
        const int64_t Tpx = 2 * W1 + st->T + 1;
        int tpx_consumed = 0;
        if (rel2lo_now && st->T == 2)
        {
            fill_burst_drop_while(st, 2 * W1 - 7, -1);
            if ((st->R >> 16) < 2 * W1 - 12)
                st->T = -12;
            tpx_consumed = 1;
        }
        if (fastarm)
        {
            fill_burst_drop_while(st, Tpx, -1);
            tpx_consumed = 1;
        }
        if (!tpx_consumed)
        {
            /* On the clip-release row at T == -28 the burst
             * pointer multi-drops into the [2*W1-28, 2*W1-12) window (one
             * 16 px drop per compare, repeated), instead of the steady
             * single drop. Reproduces all 11 release-row landings exactly
             * (k = 1..6). */
            if ((relsig || (st->rel2 && st->T == -28)) &&
                (st->R >> 16) >= 2 * W1 - 12)
            {
                fill_burst_drop_while(st, 2 * W1 - 12, -1);
                st->T = -12;
            }
            else if ((st->R >> 16) >= Tpx)
            {
                st->R -= (int64_t)16 << 16;
                if (st->T == -28)
                    st->T = -12;
                /* On the T==2 clip-release row the drop repeats, each
                 * compare individually gated on Rpx >= Tpx (the steady
                 * multi-drop shape at the T=2 threshold). 2/2 exact;
                 * non-clipped fast traces keep the single drop. */
                else if (st->rel2)
                    fill_burst_drop_while(st, Tpx, -1);
            }
        }
        if (st->T == 2 && (st->R >> 16) < 2 * W1 - 12)
            st->T = -28;
    }
    /* Staircase-phase concurrent crossing: a clipped-edge block crossing
     * while still in the T=2 phase, gated above 2*W1 + 13 px, fires the
     * per-block drop and hands the machine straight to steady. */
    if (st->T == 2 && nblocks > 0 && (st->R >> 16) > 2 * W1 + 13)
    {
        st->R -= ((int64_t)16 << 16) * nblocks;
        st->T = -12;
    }

    int64_t Rpx = st->R >> 16;
    int64_t S = Rpx >> 1;

    /* The -29 lattice signature (entry exactly one px below the -28
     * window floor) keys two behaviors: the last-row tail-trim cancel
     * below, and the non-last anti-drop terminal entry. */
    const int m29 = (R_entry_px - 2 * W1 == -29);

    /* Armed-stay graze: a would-be terminal entry whose PREVIOUS
     * row's pointer grazed the window floor (prev_S - (W1-15) in [0, 4])
     * and whose own landing barely reaches the span (S - W0 >= -1) does
     * NOT enter terminal; the row emits the armed tail instead. 4/4 with
     * 0 counterexamples in the 1029-entry terminal census at d <= 5.
     * One-row flag only; the left_bottom boundary relax below is scoped
     * to graze rows (a global relax regresses 19404 rows against the
     * captures). */
    const int graze = (st->terminal < 0 && S <= W0 &&
                       st->prev_S != FILL_BURST_NONE64 &&
                       st->prev_S - ((int64_t)W1 - 15) >= 0 &&
                       st->prev_S - ((int64_t)W1 - 15) <= 4 &&
                       S - W0 >= -1);
    const int entering = (st->terminal < 0 && S <= W0 && !graze);

    /* Non-last -29-entry anti-drop shape: an armed T==-12 row
     * entering at the -29 lattice that takes a terminal entry does NOT
     * emit the plain age-0 run. The write stream instead reflects the
     * pre-drop pointer vaulted one window UP (R_anti = Rpx_preT + 16):
     * trimmed head fragment W0 .. W1-7 full, the pointer partial at
     * S_anti by parity, and the W1 word full (no close). The PARKED
     * state is unchanged (the following row matches the ordinary
     * terminal model). 1/1 with 21493/21493 non-entering -29 controls
     * and the sole last-row -29 entry both unaffected. */
    const int anti29 = (entering && T_entry == -12 && !is_last && m29);

    /* Terminal transition: the resume pointer reached the span start. */
    if (entering)
    {
        st->terminal = 0;
        st->park = st->R;
        /* Fragment gate: R sits exactly 1 px under a lagged edge that
         * freshly landed on a 16 px block. */
        st->tfrag_gate = (st->xl_prev2 != FILL_BURST_NONE64 &&
                          st->xl_prev3 != FILL_BURST_NONE64 &&
                          (st->R - st->xl_prev2) == -((int64_t)1 << 16) &&
                          ((st->xl_prev2 >> 16) & 15) == 0 &&
                          ((st->xl_prev3 >> 16) & 15) != 0);
        st->tfrag_first = 1;
        st->tfrag_ref = st->park;
        st->term_pdR = FILL_BURST_NONE64;
        /* Blank-gate latch: terminal entered on the T==2 transition row with
         * the park exactly 1 px below a block-aligned clamped edge (same
         * d==-1/a2==0 signature as the tfrag gate, a3 unconstrained). */
        st->t2cross = (T_entry == 2 && st->xl_prev2 != FILL_BURST_NONE64 &&
                       (st->R - st->xl_prev2) == -((int64_t)1 << 16) &&
                       ((st->xl_prev2 >> 16) & 15) == 0);
    }

    if (st->terminal >= 0)
    {
        const int64_t dR_now = Rpx_preT - 2 * W1;

        /* Mid-terminal event: a lagged clipped-edge block crossing with
         * the edge freshly one-past the boundary blanks the row (with the
         * queued FIFO partial flushing through); only the 6-word
         * dead-zone width manifests. */
        if (st->terminal >= 1 &&
            st->xl_prev2 != FILL_BURST_NONE64 &&
            st->xl_prev3 != FILL_BURST_NONE64 &&
            (st->xl_prev2 >> 20) != (st->xl_prev3 >> 20) &&
            ((st->xl_prev2 >> 16) & 15) == 1 &&
            (W1 - W0 + 1) == 6)
        {
            fill_burst_plan_blank(ud);
            if (fill_burst_fifo_flush(st, dR_now))
            {
                ud->m_fill_pw = (int16_t)W1;
                ud->m_fill_pm = st->term_pRodd ? 0x80u : 0xf8u;
            }
            st->term_pdR = dR_now;
            st->term_pRodd = (int)(Rpx_preT & 1);
            st->terminal++;
            if ((px0 & 15) == 0)
                st->rearm_pending = 1;
            st->prev_S = S;
            st->prev_W1 = W1;
            return;
        }

        /* Open-trim comparator: stale px0 takes the trim, EXCEPT the
         * first stale row of a 6-word span (110/110 no-trim in refs;
         * second-and-later stale rows and all other widths trim).
         * Fresh-entry sub-span landing trim: when the entry
         * row's PRE-DROP pointer lands exactly one pixel below the span
         * start (Rpx_preT == px0 - 1; only reachable with odd px0,
         * pointer at the even word head 2*W0), the full-row open byte
         * takes the trim as well. 1/1 vs 3/3 dpre==0 controls landing
         * at/above px0 opening full; landing census: no other corpus
         * terminal entry reaches below px0 within word W0. (The
         * open_mask and partial-parity readings are observationally
         * degenerate here -- both force 0xf8.) */
        const int stale_trim = (pp != FILL_BURST_NONE32 && pp == px0 &&
                                !((W1 - W0 + 1) == 6 &&
                                  (pp2 == FILL_BURST_NONE32 || pp2 != px0)));
        const uint8_t ob_stale = stale_trim ? fill_burst_open_mask(px0)
                                            : 0xffu;
        const uint8_t ob_full =
            (stale_trim || (st->terminal == 0 && Rpx_preT == px0 - 1))
                ? fill_burst_open_mask(px0) : 0xffu;
        const int will_rearm = ((px0 & 15) != 0 && st->rearm_pending);
        /* Lag-2 block-landing fragment: at terminal index 1 with
         * px0&15 == 1 and no rearm pending, the row fragments iff the
         * edge two rows back was block-aligned (29/29 vs 0/22). */
        const int frag_lag2 = (st->terminal == 1 && (px0 & 15) == 1 &&
                               !st->rearm_pending &&
                               st->xl_prev3 != FILL_BURST_NONE64 &&
                               ((st->xl_prev3 >> 16) & 15) == 0);
        /* Block-landing fragment also fires at terminal index 1 when a
         * re-arm is already latched (19/19, zero counterexamples). */
        const int blockfrag = ((px0 & 15) == 0 &&
                               (st->terminal >= 2 ||
                                (st->terminal >= 1 && st->rearm_pending)));

        /* Second terminal row (age 1) after a T==2-transition
         * narrow entry: the row is BLANK iff the parked pointer crosses an
         * integer pixel boundary this row (frac(park)+climb >= 1). 6/6
         * blanks vs 7/7 emitters exact; T==-28 entries excluded (they
         * close-emit even when crossing). */
        if (st->terminal == 1 && st->t2cross && !st->tfrag_gate &&
            (W1 - W0) >= 5 && (W1 - W0) <= 6 &&
            Rpx_preT > (st->park >> 16))
        {
            fill_burst_plan_blank(ud);
        }
        else if ((will_rearm || blockfrag || frag_lag2) && W1 - 7 >= W0)
        {
            /* frag_lag2 and the tfrag machinery detect the same hardware
             * event; consume tfrag_first so the next row doesn't
             * re-frag. */
            if (frag_lag2)
                st->tfrag_first = 0;
            fill_burst_plan_run1(ud, W0, W1 - 7, ob_stale, 0xffu);
        }
        else if (anti29 && W1 - 7 >= W0)
        {
            /* Anti-drop emission override (see the entry-flag comment above). */
            const int64_t Ranti = Rpx_preT + 16;
            const int64_t Santi = Ranti >> 1;
            fill_burst_plan_run1(ud, W0, W1 - 7, 0xffu, 0xffu);
            if (Santi >= W0 && Santi <= W1)
            {
                ud->m_fill_pw = (int16_t)Santi;
                ud->m_fill_pm = (Ranti & 1) ? 0x80u : 0xf8u;
            }
            ud->m_fill_t2lo = (int16_t)W1;
            ud->m_fill_t2hi = (int16_t)W1;
        }
        else if (st->terminal >= 1 && st->tfrag_gate && !is_last &&
                 !(st->terminal == 1 && st->t2cross &&
                   Rpx_preT <= (st->park >> 16)) &&
                 (st->tfrag_first ||
                  xl_now < st->tfrag_ref + ((int64_t)2 << 16)))
        {
            /* Fragment rows: fire at least once on the gate, continue
             * while the edge is inside park + 2 px; the dead-zone routing
             * covers narrow spans. On the LAST row the
             * fragment/blank behaviors give way to the plain full run
             * with close -- the is_last exclusion here. The terminal >= 1
             * guard is explicit rather than implied by branch order: the
             * age-0 entry row always emits the full run. */
            st->tfrag_first = 0;
            fill_burst_plan_deadzone(ud, W0, W1, ob_stale, px1);
        }
        else
        {
            /* Terminal full rows (entry row included): the stale-span-
             * start trim comparator, plus the fresh-entry landing trim
             * above. */
            fill_burst_plan_run1(ud, W0, W1, ob_full,
                                 fill_burst_close_mask(px1));
        }

        /* k=0 close suppression (deferred close lost at the event) --
         * UNLESS a FIFO partial launches or flushes on this row: the
         * queued-partial write carries the close through. Brackets:
         * kz&flush 1/1 CLOSE|PART; kz&band&last 3/3 CLOSE|PART vs
         * band&last no-kz 12/12 plain CLOSE; kz alone 47/50 FF.
         * On a FRESH terminal entry (age 0) on the last row,
         * the close suppression is decided by the entry T, not the
         * spread: T==-12 suppresses (19/19), T==2/-28 closes (19/19).
         * Ages 1-2 keep the banked spread-based rule.
         * Shallow width-4 exception: a 4-word span whose
         * parked R entered at dR >= -22 keeps the close (the five
         * suppressed width-4 rows all entered at dR <= -23; width 2-3
         * rows are unaffected).
         * Aged terminal close suppression: at ages 3-4 with
         * T==-12, when the pointer crosses the window ceiling into the
         * [2*W1-12, 2*W1-11] band this row, the close is lost (6/6 vs
         * 10/10 closing above the band; 27 age>=5 band rows close, hence
         * the age bracket). */
        const int flush = fill_burst_fifo_flush(st, dR_now);
        const int kz =
            ((will_rearm && spread >= FILL_BURST_KZ_REARM) ||
             (is_last && st->terminal == 0 && T_entry == -12) ||
             (is_last && st->terminal >= 1 && st->terminal <= 2 &&
              spread >= FILL_BURST_KZ_TERM &&
              !(W1 - W0 == 3 && R_entry_px - 2 * W1 >= -22)) ||
             (st->terminal >= 3 && st->terminal <= 4 && st->T == -12 &&
              R_entry_px < 2 * W1 - 12 &&
              Rpx_preT >= 2 * W1 - 12 && Rpx_preT <= 2 * W1 - 11));
        const int launch_dump = kz && is_last &&
                                (dR_now == -16 || dR_now == -15);
        if (kz && !(flush || launch_dump) &&
            ud->m_fill_b1hi == (int16_t)W1)
        {
            /* The suppression maps the W1 word of the emitted run to a
             * full write (open trim included when the run is W1 alone);
             * runs not reaching W1 -- fragments, blanks -- are read
             * straight off the plan and left untouched. */
            ud->m_fill_close = 0xffu;
            if (ud->m_fill_b1lo == (int16_t)W1)
                ud->m_fill_open = 0xffu;
        }
        if (flush)
        {
            ud->m_fill_pw = (int16_t)W1;
            ud->m_fill_pm = st->term_pRodd ? 0x80u : 0xf8u;
        }
        if (launch_dump)
        {
            ud->m_fill_pw = (int16_t)W1;
            ud->m_fill_pm = (dR_now & 1) ? 0x80u : 0xf8u;
        }
        st->term_pdR = dR_now;
        st->term_pRodd = (int)(Rpx_preT & 1);
        st->terminal++;

        /* Re-arm one row after a fresh 16 px block landing. */
        if ((px0 & 15) == 0)
        {
            st->rearm_pending = 1;
        }
        else if (st->rearm_pending)
        {
            st->terminal = -1;
            st->rearm_pending = 0;
            st->postterm = 1;
            fill_burst_seed(st, W1, xl_now, xlr_now, 0);
        }
        return;
    }

    /* Postterm descent rows with the pointer above the close word take
     * the trim-fragment/blank shapes; the LAST row instead takes the
     * plain full run with close (7/7 in refs, width<=4 close path
     * 18/18). */
    if (st->postterm && S > W1)
    {
        const uint8_t ob = (pp != FILL_BURST_NONE32 && pp == px0)
            ? fill_burst_open_mask(px0) : 0xffu;
        st->prev_S = S;
        st->prev_W1 = W1;
        if (is_last)
            fill_burst_plan_run1(ud, W0, W1, ob,
                                 fill_burst_close_mask(px1));
        else
            fill_burst_plan_deadzone(ud, W0, W1, ob, px1);
        return;
    }

    /* Burst row: first burst [W0 .. E] with E snapped 8 words below the
     * resume word, then the tail [S .. W1]. */
    int64_t E = fill_burst_e_snap(S, 2, W1);
    /* Narrow-span dead zone / postterm landing: spans of at most 5 words
     * (and postterm descent landings) revert to a full first burst where
     * the burst geometry cannot fit. */
    int post_fallback = 0;
    int narrow_fall = 0;
    if (E < W0 && ((W1 - W0) <= 4 || st->postterm))
    {
        post_fallback = st->postterm;
        narrow_fall = !st->postterm;
        E = W1;
    }
    st->postterm = 0;

    /* Narrow-fallback overshoot blank: when the narrow (width
     * <= 5 word) fallback raises E to W1 but the burst pointer sits
     * STRICTLY ABOVE the close word (S > W1), the row emits nothing.
     * 1/1 vs 28/28 narrow-fallback controls at S <= W1 rendering; the
     * postterm fallback family is untouched (owned by the branch
     * above). */
    if (narrow_fall && S > W1)
    {
        st->prev_S = S;
        st->prev_W1 = W1;
        fill_burst_plan_blank(ud);
        return;
    }

    fill_burst_plan_blank(ud);
    if (E >= W0)
    {
        /* Postterm landing rows (E raised to W1 via the descent fallback)
         * take the stale-span-start open trim like terminal rows do:
         * 64/64 stale rows trim, 8/8 fresh rows don't, in refs.
         * Last-row narrow-fallback with the burst pointer
         * strictly INSIDE the span (W0 < S < W1): the open byte takes
         * the 0xf8 trim and the close is suppressed. 1/1; this is the
         * only last-row inside occurrence in the corpus. */
        const int inside_trim = (narrow_fall && is_last && S > W0 && S < W1);
        const uint8_t ob = (post_fallback && pp != FILL_BURST_NONE32 &&
                            pp == px0) ? fill_burst_open_mask(px0) : 0xffu;
        fill_burst_plan_run1(ud, W0, (int32_t)E,
                             inside_trim ? 0xf8u : ob,
                             inside_trim ? 0xffu
                                         : fill_burst_close_mask(px1));
        /* Pointer-at-close composite: on the LAST row, when the
         * burst pointer parks exactly at the close word (S == W1), the
         * queued tail partial co-writes with the close byte
         * (close | 0x80/0xf8 by Rpx parity). 1/1 with 0 counterexamples:
         * no other corpus row has S == W1 on a last-row armed close
         * emission. */
        if (narrow_fall && is_last && S == W1 && E == W1)
            ud->m_fill_close |= (Rpx & 1) ? 0x80u : 0xf8u;
    }

    /* Generalized tail trim: fires whenever the pointer ENTERED the row
     * from below the -28 window floor (prev post-drop S at or below
     * W1 - 15) and now sits above it -- the ==W1-15 form was the
     * steady-state special case (fast climbs can jump from S 44..46
     * too). Grazing entries relax the boundary to >=. Last-row -29
     * entry (the m29 lattice signature): the trim is cancelled (tail
     * runs to W1, no close). 14/14 at dR_entry==-29 vs 0/222 across
     * -28..-17; trim cancel 11/11. */
    const int left_bottom = (st->prev_S != FILL_BURST_NONE64 &&
                             st->prev_S <= (int64_t)st->prev_W1 - 15 &&
                             (graze ? (S >= (int64_t)W1 - 15)
                                    : (S > (int64_t)W1 - 15)) &&
                             !(is_last && m29));
    /* Last-row block drop to the -28 lattice: when the span start sits
     * within 3 px of a block boundary (px0&15 <= 2), the burst pointer
     * takes one extra 16 px drop, landing one below the nearest
     * -28-lattice boundary strictly under Rpx, plus px0's pixel parity:
     *   R' = base - 1 + (px0 & 1),  base = max(2*W1-28-16k) < Rpx.
     * Parked (no drop) when Rpx sits at the lattice or lattice+1 (3/3
     * park rows at mod==1 vs 0 fired; the 30/30 fired evidence is
     * mod >= 13). Even px0 lands odd (0x80 partial), odd px0 lands even
     * (0xf8); W0 clip takes the open mask. */
    if (is_last && st->T == -12 && (px0 & 15) <= 2 &&
        fill_burst_mod16(Rpx - (2 * W1 - 28)) >= 2)
    {
        int64_t base = 2 * W1 - 28;
        while (base >= Rpx)
            base -= 16;
        Rpx = base - 1 + (px0 & 1);
        S = Rpx >> 1;
    }
    const int64_t tail_end = left_bottom ? (int64_t)W1 - 7 : (int64_t)W1;
    /* Close-on-stalled-tail: when the burst pointer stalls (S == prev
     * row's S) one drop above landing (S - W0 == 7) with an exactly
     * two-block tail (W1 - S == 15), the tail's end word takes the close
     * mask. 131/131 vs 0/248 (unstalled) and 0/589 (dW1=14) in refs.
     * Deep-entry head-landing close survival: on an armed row
     * entering STRICTLY below the -28 window floor (R_entry - 2*W1 <=
     * -29) whose pointer lands in the span head, the tail's close byte
     * survives too. Head test: S - W0 <= 2 unconditionally, or
     * S - W0 <= 7 with the pointer stalled (S == prev_S). 3/3; the sole
     * unstalled depth-7 deep entry in the corpus keeps 0xff; every other
     * head landing sits at dR >= -28. */
    const int stalled = (st->prev_S != FILL_BURST_NONE64 &&
                         S == st->prev_S);
    const int tail_close =
        ((stalled && S - W0 == 7 && (int64_t)W1 - S == 15) ||
         (R_entry_px - 2 * W1 <= -29 &&
          (S - W0 <= 2 || (S - W0 <= 7 && stalled))));
    if (S <= tail_end && E < W1)
    {
        if (S >= W0)
        {
            ud->m_fill_pw = (int16_t)S;
            ud->m_fill_pm = (Rpx & 1) ? 0x80u : 0xf8u;
        }
        const int64_t t2lo = (S + 1 > W0) ? S + 1 : W0;
        if (t2lo <= tail_end)
        {
            ud->m_fill_t2lo = (int16_t)t2lo;
            ud->m_fill_t2hi = (int16_t)tail_end;
            if (tail_close && tail_end == W1)
                ud->m_fill_t2close = fill_burst_close_mask(px1);
        }
    }
    st->prev_S = S;
    st->prev_W1 = W1;
}

/*****************************************************************************/
/* DPS Test-Mode span-buffer stream model; law and provisional list at
 * rdp_dps_model_t. All producer-thread except rdp_dps_span_capture. */

/* One skipped stream position: a residual write when the phase has been
 * seen, canceling a pending head at the same position mod 32, scheduled
 * into the window when emitting. */
static void rdp_dps_slot(rdp_dps_model_t *m, uint32_t S, uint32_t phase_seen,
    uint32_t pend, uint32_t *pend_alive, int emit)
{
    if (!(phase_seen & (1u << (S & 3u))))
        return;
    if (*pend_alive && ((S & 31u) == ((pend - 1u) & 31u)))
        *pend_alive = 0;
    if (emit && S >= m->base && S - m->base < RDP_DPS_WIN)
        m->sched[S - m->base] = 2;
}

/* Replays the stream arithmetic over the collected rows; returns the
 * stream length. emit == 0 measures (pending head and its fate);
 * emit != 0 fills sched[] and the per-span capture plans from
 * m_dps.base. */
static uint32_t rdp_dps_walk(rdp_t *rdp, extent_t *spans, int emit)
{
    rdp_dps_model_t *m = &rdp->m_dps;
    uint32_t S = 0, phase_seen = 0, pend = 0, pend_alive = 0;
    int32_t  seed_row[4] = { -1, -1, -1, -1 };
    int16_t  seed_x[4]   = { 0, 0, 0, 0 };

    for (uint32_t i = 0; i < m->nrows; i++)
    {
        const int32_t x0 = m->row_x0[i];
        const int32_t x1 = m->row_x1[i];
        const uint32_t w = (uint32_t)(x1 - x0 + 1);
        const uint32_t target = (uint32_t)(x0 - (x0 & 1)) & 3u;

        while ((S & 3u) != target)
            rdp_dps_slot(m, S++, phase_seen, pend, &pend_alive, emit);
        if (x0 & 1)
        {
            /* Head slot: residual commit, or the primitive's one
             * pending word. */
            if (phase_seen & (1u << (S & 3u)))
                rdp_dps_slot(m, S, phase_seen, pend, &pend_alive, emit);
            else if (pend == 0)
            {
                pend = S + 1u;
                pend_alive = 1;
            }
            S++;
        }

        /* Pixel run [x0..x1] at [S..S+w). */
        if (pend_alive && (w >= 32u || ((((pend - 1u) - S) & 31u) < w)))
            pend_alive = 0;
        if (emit && S + w > m->base)
        {
            /* Capture plan: this row's pixels at or past the window. */
            rdp_span_aux *ud = (rdp_span_aux *)spans[m->row_span[i]].userdata;
            ud->m_dps_cap = 1;
            ud->m_dps_cap_x0 = (int16_t)((S >= m->base)
                ? x0 : x0 + (int32_t)(m->base - S));
            ud->m_dps_cap_x1 = (int16_t)x1;
            ud->m_dps_voff = (int32_t)S - x0 - (int32_t)m->base;
            for (uint32_t p = (S >= m->base) ? S : m->base; p < S + w; p++)
                if (p - m->base < RDP_DPS_WIN)
                    m->sched[p - m->base] = 1;
        }
        if (emit && S < m->base)
        {
            /* Residual-seed candidates: per phase, the latest pixel
             * below the window; later rows override. */
            const uint32_t nb = (m->base - S < w) ? (m->base - S) : w;
            const int32_t xcap = x0 + (int32_t)nb - 1;
            for (uint32_t k = 0; k < 4; k++)
            {
                const int32_t x = xcap - (int32_t)(((uint32_t)xcap - k) & 3u);
                if (x >= x0)
                {
                    seed_row[k] = (int32_t)i;
                    seed_x[k] = (int16_t)x;
                }
            }
        }
        if (w >= 4u)
            phase_seen = 0xfu;
        else
            for (int32_t x = x0; x <= x1; x++)
                phase_seen |= 1u << ((uint32_t)x & 3u);
        S += w;

        while (S & 3u)
            rdp_dps_slot(m, S++, phase_seen, pend, &pend_alive, emit);
    }

    if (!emit)
    {
        m->pend_pos1 = pend;
        m->pend_alive = pend_alive;
    }
    else
    {
        for (uint32_t k = 0; k < 4; k++)
        {
            rdp_span_aux *ud;
            if (seed_row[k] < 0)
                continue;
            ud = (rdp_span_aux *)spans[m->row_span[seed_row[k]]].userdata;
            if (!ud->m_dps_cap)
            {
                /* Seed-only row: empty window range, live seed list. */
                ud->m_dps_cap = 1;
                ud->m_dps_cap_x0 = 1;
                ud->m_dps_cap_x1 = 0;
                ud->m_dps_voff = 0;
            }
            ud->m_dps_seed_x[ud->m_dps_seed_n] = seed_x[k];
            ud->m_dps_seed_k[ud->m_dps_seed_n] = (uint8_t)k;
            ud->m_dps_seed_n++;
        }
    }
    return S;
}

/* Schedules the primitive just set up, before its spans are submitted.
 * A primitive whose rows all consume nothing leaves the model -- and
 * any prior draw's pending image -- untouched, like the buffer. */
static void rdp_dps_schedule(rdp_t *rdp, extent_t *spans)
{
    rdp_dps_model_t *m = &rdp->m_dps;
    if (m->nrows == 0)
        return;
    memset(m->sched, 0, sizeof m->sched);
    memset(m->val_set, 0, sizeof m->val_set);
    memset(m->seed_set, 0, sizeof m->seed_set);
    m->total = rdp_dps_walk(rdp, spans, 0);
    m->base = (m->total > RDP_DPS_WIN - 4u)
        ? ((m->total - (RDP_DPS_WIN - 4u)) & ~3u) : 0;
    rdp_dps_walk(rdp, spans, 1);
    m->valid = 1;
}

/* Worker-side capture of a scheduled pixel's write-stage word image
 * (value law at rdp_dps_model_t). Scheduled positions are disjoint
 * across spans, so concurrent workers never store to the same index. */
static void rdp_dps_span_capture(rdp_t *rdp, rdp_span_aux *userdata, int32_t x,
                                 int32_t fbsize)
{
    rdp_dps_model_t *m = &rdp->m_dps;
    const uint32_t cvg = (uint32_t)userdata->m_current_pix_cvg;
    const uint32_t r = (uint32_t)rgbaint_get_r(&userdata->m_pixel_color);
    const uint32_t g = (uint32_t)rgbaint_get_g(&userdata->m_pixel_color);
    const uint32_t b = (uint32_t)rgbaint_get_b(&userdata->m_pixel_color);
    /* The staged image is the write-stage word for the colour image's own
     * size: RGBA8888 with the coverage residue in the alpha byte at 32
     * bits, RGBA5551 with the coverage msb in the low bit at 16. A 16-bit
     * column carries two of them, the even pixel in the high half -- the
     * halfword order the colour writes use. */
    uint32_t word, half = 0;
    int32_t c = x;

    if (fbsize == 2)
    {
        word = ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) |
               ((((cvg - 1u) & 7u) >> 2) & 1u);
        c = x >> 1;
        half = (x & 1) ? 0u : 16u;
        word <<= half;
    }
    else
    {
        word = (r << 24) | (g << 16) | (b << 8) | (((cvg - 1u) & 7u) << 5);
    }

    if (c >= userdata->m_dps_cap_x0 && c <= userdata->m_dps_cap_x1)
    {
        const uint32_t i = (uint32_t)(c + userdata->m_dps_voff);
        if (i < RDP_DPS_WIN)
        {
            /* A column straddling the span's edge takes only the half its
             * rasterized pixel supplies; the other keeps the prefill. */
            m->val[i] = (fbsize == 2 && m->val_set[i]) ? (m->val[i] | word)
                                                       : word;
            m->val_set[i] = 1;
        }
    }
    for (uint32_t k = 0; k < userdata->m_dps_seed_n; k++)
    {
        if (userdata->m_dps_seed_x[k] == c)
        {
            const uint32_t sk = userdata->m_dps_seed_k[k];
            m->seed_val[sk] = (fbsize == 2 && m->seed_set[sk])
                ? (m->seed_val[sk] | word) : word;
            m->seed_set[sk] = 1;
        }
    }
}

/* Composes the post-draw CPU-visible window over the host's stored
 * words (contract in rdp.h; the public wrapper fences first). Word 4g
 * and 4g+1 carry the two slots of group g, 4g+2 the hidden ("9th")
 * bit image -- one nibble per slot from the halfword low bits, the
 * RDRAM hidden-plane write law -- and 4g+3 reads zero. */
int rdp_dps_take(rdp_t *rdp, uint32_t words[32])
{
    rdp_dps_model_t *m = &rdp->m_dps;
    uint32_t res[4], ring[16];
    uint8_t res_ok[4];
    uint32_t ring_ok = 0;

    if (!m->valid)
        return 0;

    for (uint32_t k = 0; k < 4; k++)
    {
        res[k] = m->seed_val[k];
        res_ok[k] = m->seed_set[k];
    }

    for (uint32_t i = 0; i < RDP_DPS_WIN && m->base + i < m->total; i++)
    {
        const uint32_t pos = m->base + i;
        uint32_t v = 0;
        int have = 0;

        if (m->sched[i] == 1 && m->val_set[i])
        {
            v = m->val[i];
            res[pos & 3u] = v;
            res_ok[pos & 3u] = 1;
            have = 1;
        }
        else if (m->sched[i] == 2 && res_ok[pos & 3u])
        {
            v = res[pos & 3u];
            have = 1;
        }
        if (have && !((pos >> 4) & 1u))
        {
            ring[pos & 15u] = v;
            ring_ok |= 1u << (pos & 15u);
        }
    }

    /* A surviving pending head commits with the final residual. */
    if (m->pend_alive && m->pend_pos1 != 0)
    {
        const uint32_t pos = m->pend_pos1 - 1u;
        if (res_ok[pos & 3u] && !((pos >> 4) & 1u))
        {
            ring[pos & 15u] = res[pos & 3u];
            ring_ok |= 1u << (pos & 15u);
        }
    }

    for (uint32_t g = 0; g < 8; g++)
    {
        uint32_t hid = words[4 * g + 2] & 0xffu;
        for (uint32_t h = 0; h < 2; h++)
        {
            const uint32_t sl = 2 * g + h;
            uint32_t nib;
            if (!(ring_ok & (1u << sl)))
                continue;
            words[4 * g + h] = ring[sl];
            nib = ((((ring[sl] >> 16) & 1u) * 3u) << 2)
                | ((ring[sl] & 1u) * 3u);
            hid = h ? ((hid & 0xf0u) | nib) : ((hid & 0x0fu) | (nib << 4));
        }
        words[4 * g + 2] = hid;
        words[4 * g + 3] = 0;
    }

    m->valid = 0;
    return 1;
}

static void rdp_draw_triangle(rdp_t *rdp, uint64_t *cmd_buf, bool shade, bool texture, bool zbuffer, bool rect)
{
    /* Worst-case primitive footprint is 4096 spans (the spanidx bound
     * below); drain when the aux pool cannot fit one, so span setup can
     * carve slots without per-span lifetime concerns. */
    if (rdp->m_aux_buf_ptr + 4096u * sizeof(rdp_span_aux) > EXTENT_AUX_COUNT)
        rdp_pipeline_drain(rdp);

    const uint64_t* cmd_data = rect ? rdp->m_temp_rect_data : cmd_buf;
    const uint64_t w1 = cmd_data[0];

    int32_t flip = (int32_t)(w1 >> 55) & 1;
    rdp->m_misc_state.m_max_level = (uint32_t)(w1 >> 51) & 7;
    int32_t tilenum = (int32_t)(w1 >> 48) & 0x7;

    int32_t dsdiff = 0, dtdiff = 0, dwdiff = 0, drdiff = 0, dgdiff = 0, dbdiff = 0, dadiff = 0, dzdiff = 0;
    int32_t dsdeh = 0, dtdeh = 0, dwdeh = 0, drdeh = 0, dgdeh = 0, dbdeh = 0, dadeh = 0, dzdeh = 0;
    int32_t dsdxh = 0, dtdxh = 0, dwdxh = 0, drdxh = 0, dgdxh = 0, dbdxh = 0, dadxh = 0, dzdxh = 0;
    int32_t dsdyh = 0, dtdyh = 0, dwdyh = 0, drdyh = 0, dgdyh = 0, dbdyh = 0, dadyh = 0, dzdyh = 0;

    /* Span x extents, accumulated over the four sublines of a scanline.
     * startx tracks the major edge and endx the minor; which of the two is
     * the numeric min and which the max is what `flip` selects. */
    int32_t startx = 0;
    int32_t endx = 0;

    int32_t shade_base = 4;
    int32_t texture_base = 4;
    int32_t zbuffer_base = 4;
    if(shade)
    {
        texture_base += 8;
        zbuffer_base += 8;
    }
    if(texture)
    {
        zbuffer_base += 8;
    }

    uint64_t w2 = cmd_data[1];
    uint64_t w3 = cmd_data[2];
    uint64_t w4 = cmd_data[3];

    int32_t yl = (int32_t)(w1 >> 32) & 0x3fff;
    int32_t ym = (int32_t)(w1 >> 16) & 0x3fff;
    int32_t yh = (int32_t)(w1 >>  0) & 0x3fff;
    /* Edge X coefficients are latched by hardware at 28 bits (12.16, sign at
     * bit 27), not the field's full 32: a coordinate beyond +/-2048 px wraps
     * at parse time. ParaLLEl-RDP sign-extends the X words from bit 27
     * (sext<28>) when building its triangle setup. The attribute anchor and
     * the walked edge both start from this wrapped value. */
    int32_t xl = (int32_t)(w2 >> 32) & 0x0fffffff;
    int32_t xh = (int32_t)(w3 >> 32) & 0x0fffffff;
    int32_t xm = (int32_t)(w4 >> 32) & 0x0fffffff;
    // Inverse slopes in 16.16 format
    int32_t dxldy = (int32_t)w2;
    int32_t dxhdy = (int32_t)w3;
    int32_t dxmdy = (int32_t)w4;

    if (yl & 0x2000)  yl |= 0xffffc000;
    if (ym & 0x2000)  ym |= 0xffffc000;
    if (yh & 0x2000)  yh |= 0xffffc000;

    if (xl & 0x08000000)  xl |= 0xf0000000;
    if (xm & 0x08000000)  xm |= 0xf0000000;
    if (xh & 0x08000000)  xh |= 0xf0000000;

    const uint64_t *const shd = cmd_data + shade_base;
    const uint64_t *const tex = cmd_data + texture_base;
    const uint64_t *const zbf = cmd_data + zbuffer_base;

    int32_t r = rdp_tri_shade_coeff(shd, RDP_TRI_START, RDP_TRI_R, shade, rect ? 0 : w1);
    int32_t g = rdp_tri_shade_coeff(shd, RDP_TRI_START, RDP_TRI_G, shade, rect ? 0 : w1);
    int32_t b = rdp_tri_shade_coeff(shd, RDP_TRI_START, RDP_TRI_B, shade, rect ? 0 : w1);
    int32_t a = rdp_tri_shade_coeff(shd, RDP_TRI_START, RDP_TRI_A, shade, rect ? 0 : w1);
    const int32_t drdx = rdp_tri_shade_coeff(shd, RDP_TRI_DX, RDP_TRI_R, shade, rect ? 0 : w1);
    const int32_t dgdx = rdp_tri_shade_coeff(shd, RDP_TRI_DX, RDP_TRI_G, shade, rect ? 0 : w1);
    const int32_t dbdx = rdp_tri_shade_coeff(shd, RDP_TRI_DX, RDP_TRI_B, shade, rect ? 0 : w1);
    const int32_t dadx = rdp_tri_shade_coeff(shd, RDP_TRI_DX, RDP_TRI_A, shade, rect ? 0 : w1);
    const int32_t drde = rdp_tri_shade_coeff(shd, RDP_TRI_DE, RDP_TRI_R, shade, rect ? 0 : w1);
    const int32_t dgde = rdp_tri_shade_coeff(shd, RDP_TRI_DE, RDP_TRI_G, shade, rect ? 0 : w1);
    const int32_t dbde = rdp_tri_shade_coeff(shd, RDP_TRI_DE, RDP_TRI_B, shade, rect ? 0 : w1);
    const int32_t dade = rdp_tri_shade_coeff(shd, RDP_TRI_DE, RDP_TRI_A, shade, rect ? 0 : w1);
    const int32_t drdy = rdp_tri_shade_coeff(shd, RDP_TRI_DY, RDP_TRI_R, shade, rect ? 0 : w1);
    const int32_t dgdy = rdp_tri_shade_coeff(shd, RDP_TRI_DY, RDP_TRI_G, shade, rect ? 0 : w1);
    const int32_t dbdy = rdp_tri_shade_coeff(shd, RDP_TRI_DY, RDP_TRI_B, shade, rect ? 0 : w1);
    const int32_t dady = rdp_tri_shade_coeff(shd, RDP_TRI_DY, RDP_TRI_A, shade, rect ? 0 : w1);

    int32_t s = rdp_tri_coeff(tex, RDP_TRI_START, RDP_TRI_S, texture);
    int32_t t = rdp_tri_coeff(tex, RDP_TRI_START, RDP_TRI_T, texture);
    int32_t w = rdp_tri_coeff(tex, RDP_TRI_START, RDP_TRI_W, texture);
    const int32_t dsdx = rdp_tri_coeff(tex, RDP_TRI_DX, RDP_TRI_S, texture);
    const int32_t dtdx = rdp_tri_coeff(tex, RDP_TRI_DX, RDP_TRI_T, texture);
    const int32_t dwdx = rdp_tri_coeff(tex, RDP_TRI_DX, RDP_TRI_W, texture);
    const int32_t dsde = rdp_tri_coeff(tex, RDP_TRI_DE, RDP_TRI_S, texture);
    const int32_t dtde = rdp_tri_coeff(tex, RDP_TRI_DE, RDP_TRI_T, texture);
    const int32_t dwde = rdp_tri_coeff(tex, RDP_TRI_DE, RDP_TRI_W, texture);
    const int32_t dsdy = rdp_tri_coeff(tex, RDP_TRI_DY, RDP_TRI_S, texture);
    const int32_t dtdy = rdp_tri_coeff(tex, RDP_TRI_DY, RDP_TRI_T, texture);
    const int32_t dwdy = rdp_tri_coeff(tex, RDP_TRI_DY, RDP_TRI_W, texture);

    /* Z is a lone 16.16 pair per doubleword, not a four-lane block.
     *
     * A triangle WITHOUT a z block still runs the z pipe (othermode
     * decides z compare/update, not the opcode), and the coefficient
     * loader neither zeroes the registers nor leaves them stale from the
     * previous z-carrying primitive: it latches the triangle's own header
     * doubleword into BOTH z-block slots, so z0 = dzde = hi32(w1) and
     * dzdx = dzdy = lo32(w1) -- the edge opcode/y fields reinterpreted as
     * z fixed-point, one bus word duplicated across the two slots. The
     * latch is self-contained per triangle; it carries nothing from the
     * preceding pipeline state. Adjudicated by the PRDP 9:21 stale-z
     * replay, which this law reproduces at 1043/1043 captured z cells
     * exact -- coverage-offset corrections, clamps and inter-triangle
     * compares included -- while the two-word (w1/w2) reading misses 655.
     *
     * Rectangles keep zeroed coefficients: their alias source would be
     * the synthesized temp rect words, an emulator artifact with no
     * hardware adjudication. */
    const uint64_t zsrc0 = zbuffer ? zbf[0] : (rect ? 0 : cmd_data[0]);
    const uint64_t zsrc1 = zbuffer ? zbf[1] : (rect ? 0 : cmd_data[0]);
    int32_t z = (int32_t)(uint32_t)(zsrc0 >> 32);
    const int32_t dzdx = (int32_t)(uint32_t)zsrc0;
    const int32_t dzde = (int32_t)(uint32_t)(zsrc1 >> 32);
    const int32_t dzdy = (int32_t)(uint32_t)zsrc1;

    const int32_t dzdy_dz = (dzdy >> 16) & 0xffff;
    const int32_t dzdx_dz = (dzdx >> 16) & 0xffff;

    // The span extent buffer lives in the rdp_t object rather than on
    // the stack: at ~80 bytes per extent_t, 4096 extents is ~320KiB,
    // which overflows the default thread stack on platforms like musl
    // (128KiB). draw_triangle only runs on the command-processing
    // thread, and render_extents() deep-copies extents into the poly
    // manager's work units before queueing, so a single member buffer
    // is safe.
    extent_t* spans = rdp->m_spans;

    rdp->m_span_base.m_span_drdy = drdy;
    rdp->m_span_base.m_span_dgdy = dgdy;
    rdp->m_span_base.m_span_dbdy = dbdy;
    rdp->m_span_base.m_span_dady = dady;
    rdp->m_span_base.m_span_dzdy = rdp->m_other_modes.z_source_sel ? 0 : dzdy;

    unsigned temp_dzpix = ((dzdy_dz & 0x8000) ? ((~dzdy_dz) & 0x7fff) : dzdy_dz) + ((dzdx_dz & 0x8000) ? ((~dzdx_dz) & 0x7fff) : dzdx_dz);
    rdp->m_span_base.m_span_dr = drdx & ~0x1f;
    rdp->m_span_base.m_span_dg = dgdx & ~0x1f;
    rdp->m_span_base.m_span_db = dbdx & ~0x1f;
    rdp->m_span_base.m_span_da = dadx & ~0x1f;
    /* Hardware steps S/T/W across the span with the low 5 gradient bits
     * cleared, exactly like RGBA (ParaLLEl-RDP interpolation:
     * stw += (dstzw_dx.xyw & ~0x1f) * dx; Z alone steps at full precision).
     * Stepping raw lets S/T drift by the low bits per pixel relative to
     * hardware -- sparse one-LSB texel deltas that grow along the span
     * whenever a gradient carries low bits. */
    rdp->m_span_base.m_span_ds = dsdx & ~0x1f;
    rdp->m_span_base.m_span_dt = dtdx & ~0x1f;
    rdp->m_span_base.m_span_dw = dwdx & ~0x1f;
    /* Per-scanline (vertical) texture derivatives, kept for the LOD Y-term.
     * ParaLLEl-RDP folds |st_dy - st| into the LOD alongside the X-term, where
     * st_dy uses dstzw_dy (the triangle DsDy row) masked & ~0x7fff. */
    rdp->m_span_base.m_span_dsdy = dsdy;
    rdp->m_span_base.m_span_dtdy = dtdy;
    rdp->m_span_base.m_span_dwdy = dwdy;
    rdp->m_span_base.m_span_dz = rdp->m_other_modes.z_source_sel ? 0 : dzdx;
    rdp->m_span_base.m_span_dymax = 0;
    rdp->m_span_base.m_span_dzpix = rdp->m_dzpix_normalize[temp_dzpix & 0xffff];

    int32_t xleft_inc = (dxmdy >> 2) & ~1;
    int32_t xright_inc = (dxhdy >> 2) & ~1;

    int32_t xright = xh & ~1;
    int32_t xleft = xm & ~1;

    const int32_t sign_dxhdy = (dxhdy & 0x80000000) ? 1 : 0;
    const int32_t do_offset = !(sign_dxhdy ^ (flip));

    if (do_offset)
    {
        dsdeh = dsde >> 9;  dsdyh = dsdy >> 9;
        dtdeh = dtde >> 9;  dtdyh = dtdy >> 9;
        dwdeh = dwde >> 9;  dwdyh = dwdy >> 9;
        drdeh = drde >> 9;  drdyh = drdy >> 9;
        dgdeh = dgde >> 9;  dgdyh = dgdy >> 9;
        dbdeh = dbde >> 9;  dbdyh = dbdy >> 9;
        dadeh = dade >> 9;  dadyh = dady >> 9;
        dzdeh = dzde >> 9;  dzdyh = dzdy >> 9;

        dsdiff = rdp_grad_diff(dsdeh, dsdyh);
        dtdiff = rdp_grad_diff(dtdeh, dtdyh);
        dwdiff = rdp_grad_diff(dwdeh, dwdyh);
        drdiff = rdp_grad_diff(drdeh, drdyh);
        dgdiff = rdp_grad_diff(dgdeh, dgdyh);
        dbdiff = rdp_grad_diff(dbdeh, dbdyh);
        dadiff = rdp_grad_diff(dadeh, dadyh);
        dzdiff = rdp_grad_diff(dzdeh, dzdyh);
    }
    else
    {
        dsdiff = dtdiff = dwdiff = drdiff = dgdiff = dbdiff = dadiff = dzdiff = 0;
    }

    /* Per-pixel gradient term for the span-start xfrac correction: hardware
     * clears the low bit of the >>8'd gradient (ParaLLEl-RDP span setup:
     * interpolate_snapped((d_dx >> 8) & ~1, xfrac)). */
    /* Per-pixel gradient term for the span-start xfrac correction: hardware
     * clears the low bit of the >>8'd gradient (ParaLLEl-RDP span setup:
     * interpolate_snapped((d_dx >> 8) & ~1, xfrac)). */
    dsdxh = (dsdx >> 8) & ~1;
    dtdxh = (dtdx >> 8) & ~1;
    dwdxh = (dwdx >> 8) & ~1;
    drdxh = (drdx >> 8) & ~1;
    dgdxh = (dgdx >> 8) & ~1;
    dbdxh = (dbdx >> 8) & ~1;
    dadxh = (dadx >> 8) & ~1;
    dzdxh = (dzdx >> 8) & ~1;

    const int32_t ycur = yh & ~3;
    const int32_t ylfar = yl | 3;
    /* Effective per-subline y-window: in 1-/2-cycle hardware masks
     * individual quarter lines against the raw (10.2) scissor bounds, so
     * a fractional top or bottom edge renders its boundary row with
     * partial subpixel coverage rather than dropping or filling the row
     * wholesale. Copy and fill ignore the fractional bits (n64brew
     * SET_SCISSOR) and keep the plain triangle bounds. Adjudicated by
     * PRDP 10:9 (scissor 140.5,100.25..180.75,140). */
    int32_t yh_eff = yh;
    int32_t yl_eff = yl;
    if (rdp->m_other_modes.cycle_type == CYCLE_TYPE_1 ||
        rdp->m_other_modes.cycle_type == CYCLE_TYPE_2)
    {
        const int32_t sylo = (int32_t)rdp->m_scissor.m_yh_raw;
        const int32_t syhi = (int32_t)rdp->m_scissor.m_yl_raw;
        if (yh_eff < sylo) yh_eff = sylo;
        if (yl_eff > syhi) yl_eff = syhi;
    }
    const int32_t ldflag = (sign_dxhdy ^ flip) ? 0 : 3;
    int32_t majorx[4];
    int32_t minorx[4];
    int32_t majorxint[4];
    int32_t minorxint[4];

    int32_t xfrac = ((xright >> 8) & 0xff);

    const int32_t clipy1 = rdp->m_scissor.m_yh;
    const int32_t clipy2 = rdp->m_scissor.m_yl_clip;

    // Trivial reject
    if((ycur >> 2) >= clipy2 && (ylfar >> 2) >= clipy2)
    {
        return;
    }
    if((ycur >> 2) < clipy1 && (ylfar >> 2) < clipy1)
    {
        return;
    }

    bool new_object = true;
    rdp_poly_state* object = NULL;
    bool valid = false;

    /* FILL-mode triangle burst model (see fill_burst_row above): runs on
     * this thread only, feeding rows in scanline order exactly as
     * render_spans will emit them (same y-window clamp), and only for the
     * hardware-adjudicated family: fill cycle type, 32-bit color image,
     * vertical minor edges, lmajor clear, 8-byte-aligned rows. */
    fill_burst_state fburst = {
        .active = (!rect &&
                   rdp->m_other_modes.cycle_type == CYCLE_TYPE_FILL &&
                   rdp->m_misc_state.m_fb_size == 3 &&
                   dxhdy == 0 && dxmdy == 0 &&
                   !flip &&
                   (rdp->m_misc_state.m_fb_address & 63u) == 0 &&
                   (rdp->m_misc_state.m_fb_width & 15u) == 0),
        /* "nothing seen yet" sentinels; every other field starts at zero */
        .terminal   = -1,
        .xl_prev    = FILL_BURST_NONE64,
        .xl_prev2   = FILL_BURST_NONE64,
        .xl_prev3   = FILL_BURST_NONE64,
        .xlr_prev   = FILL_BURST_NONE64,
        .xlr_prev2  = FILL_BURST_NONE64,
        .prev_S     = FILL_BURST_NONE64,
        .term_pdR   = FILL_BURST_NONE64,
        .prev_px0   = FILL_BURST_NONE32,
        .prev_px0_2 = FILL_BURST_NONE32,
    };

    /* Family B (fill_famb_row above): fixed left edge, moving right edge.
     * Disjoint from the family-A gate (which requires both right-edge
     * slopes zero). The model's positional laws are expressed relative to
     * the scissor column; the hardware captures exercise the 508-wide
     * scissor, so other scissor widths follow the same relative laws. */
    fill_famb_state famb = {
        .active = (!rect &&
                   rdp->m_other_modes.cycle_type == CYCLE_TYPE_FILL &&
                   rdp->m_misc_state.m_fb_size == 3 &&
                   dxldy == 0 && (dxhdy != 0 || dxmdy != 0) &&
                   !flip &&
                   (rdp->m_misc_state.m_fb_address & 7u) == 0 &&
                   (rdp->m_misc_state.m_fb_width & 1u) == 0),
        .clip  = (int32_t)rdp->m_scissor.m_xl_raw >> 2,
        .w1row = (int32_t)(rdp->m_misc_state.m_fb_width >> 1) - 1,
    };
    famb.w1c = rdp_min32(famb.clip >> 1, famb.w1row);

    int32_t fburst_start = yh >> 2;
    int32_t fburst_end = yl >> 2;
    {
        /* Mirror the render_spans y-window clamp (fill mode: clipy1 is
         * the floor'd upper scissor edge). */
        if (clipy2 <= 0)
            fburst.active = 0;
        if (fburst_start < clipy1) fburst_start = clipy1;
        if (fburst_start >= clipy2) fburst_start = clipy2 - 1;
        if (fburst_end < clipy1) fburst_end = clipy1;
        if (fburst_end >= clipy2) fburst_end = clipy2 - 1;
        if (clipy2 <= 0)
            famb.active = 0;
    }
    famb.lastj = (yl - 1) >> 2;
    if (famb.lastj > fburst_end) famb.lastj = fburst_end;
    int32_t fburst_xlraw0 = 0;
    int32_t fburst_xlclip0 = 0;
    int32_t fburst_spread = 0;
    bool fburst_anyvalid = false;
    /* DPS row collection (rdp_dps_model_t): armed hosts, adjudicated
     * family only. Rectangles excluded -- the SetEnvColor hazard
     * window can defer their spans out of stream order. */
    const bool dps_on = rdp->m_dps.armed != 0 &&
        rdp->m_other_modes.cycle_type == CYCLE_TYPE_1 &&
        (rdp->m_misc_state.m_fb_size == 3 ||
         rdp->m_misc_state.m_fb_size == 2) && !rect;
    /* Stream positions index 32-bit span-buffer COLUMNS, not pixels: the
     * buffer's row is 72 bits -- two colour columns plus one coverage byte
     * (n64brew RDP Interface, span buffer layout) -- so a 32-bit colour
     * image puts one pixel in a column and a 16-bit one puts two. Working
     * in columns makes the pairing, phase and window arithmetic below
     * size-independent. */
    const int32_t dps_sh = (rdp->m_misc_state.m_fb_size == 2) ? 1 : 0;
    int32_t dps_rawl = 0, dps_rawr = 0;
    bool dps_rawset = false;
    if (dps_on)
        rdp->m_dps.nrows = 0;
    /* Last valid row of the fed window (the last-row behaviors key on it).
     * Row validity is a pure function of the y clamps and the interlace
     * field parity -- identical to the walker's valid_y with the x terms
     * removed (valid_y never depends on x). */
    int32_t fburst_lastj = fburst_start - 1;
    if (fburst.active)
    {
        for (int32_t lj = fburst_end; lj >= fburst_start; lj--)
        {
            if (4 * lj + 3 < yh || 4 * lj >= yl)
                continue;
            if (rdp->m_scissor.m_field &&
                (uint8_t)(lj & 1) != rdp->m_scissor.m_keep_odd)
                continue;
            fburst_lastj = lj;
            break;
        }
    }
    int32_t famb_xrmax = INT32_MIN;
    int32_t famb_xr3 = 0;
    int famb_r3valid = 0;

    for (int32_t k = ycur; k <= ylfar; k++)
    {
        if (k == ym)
        {
            xleft = xl & ~1;
            xleft_inc = (dxldy >> 2) & ~1;
        }

        /* Edge X clip: the hardware edge coordinate is finite-width, so a
         * walked edge that runs past it wraps rather than growing without
         * bound. Reduce the per-scanline snapshot to the hardware's 28-bit
         * signed X (12 integer + 16 fraction; sign at bit 27) before it feeds
         * the span bounds and coverage; a full-precision walk would not wrap
         * and would leave a garbage column on an underflowing left edge.
         * Follows ParaLLEl-RDP span_setup.comp, which does
         * bitfieldExtract(x, 0, 28) at native resolution. A no-op unless the
         * edge exceeds +/-2048 px, so normal primitives are unchanged. */
        const int32_t xleft_w  = (int32_t)((uint32_t)xleft  << 4) >> 4;
        const int32_t xright_w = (int32_t)((uint32_t)xright << 4) >> 4;

        /* The span SHAPE -- extents and coverage -- is scissored: per subpixel,
         * first reject an inverted span (screen-left beyond screen-right at
         * quarter-pixel granularity -- e.g. a wrapped underflowed edge; such a
         * span must contribute nothing, or its unpurged coverage buffer is
         * read stale by the span draw and writes garbage columns), then clamp
         * both edges into the raw (10.2) scissor X range so the
         * partial-coverage mask at a scissor boundary column is computed from
         * the clamped edge position, as hardware does. Same ordering and
         * dataflow as ParaLLEl-RDP span_setup.comp: invalid_line from the
         * unclamped quantized X, then xleft/xright clamped to
         * [lo_scissor, hi_scissor], with invalid subpixels given an inverted
         * pair; the clamped, masked values feed both the coverage masks and
         * the span start/end. */
        const int32_t sxlo = (int32_t)rdp->m_scissor.m_xh_raw << 14; /* 10.2 -> 16.16 */
        const int32_t sxhi = (int32_t)rdp->m_scissor.m_xl_raw << 14;
        int32_t scr_l = flip ? xright_w : xleft_w;   /* screen-left edge */
        int32_t scr_r = flip ? xleft_w  : xright_w;  /* screen-right edge */
        if ((scr_l >> 14) > (scr_r >> 14))
        {
            scr_l = 0xfff << 16;
            scr_r = 0;
        }
        else
        {
            scr_l = scr_l < sxlo ? sxlo : (scr_l > sxhi ? sxhi : scr_l);
            scr_r = scr_r < sxlo ? sxlo : (scr_r > sxhi ? sxhi : scr_r);
        }
        const int32_t xleft_c  = flip ? scr_r : scr_l;
        const int32_t xright_c = flip ? scr_l : scr_r;
        const int32_t xstart = xleft_c >> 16;
        const int32_t xend = xright_c >> 16;

        /* The ATTRIBUTE ANCHOR, in contrast, is the RAW walked X -- neither
         * scissored NOR wrapped: span_draw steps texture/shade/Z from the
         * true major-edge position (m_unscissored_rx) and skips writes
         * outside the scissor, so the per-pixel attributes stay aligned to
         * the primitive even when an edge exits the scissor or the 12-bit
         * coordinate range. ParaLLEl-RDP derives interpolation_base_x from
         * the full-precision xh before the width reduction is applied to the
         * span-bound copies; anchoring at the wrapped position instead
         * offsets every attribute by a multiple of 4096 px worth of gradient
         * (wrong texels down the visible columns of a wrapped span -- the
         * F-Zero X garbage column), and anchoring at the scissored position
         * warps every scissor-crossing triangle. */
        const int32_t xend_unsc = xright >> 16;
        const int32_t j = k >> 2;
        const int32_t spanidx = (k - ycur) >> 2;
        const int32_t  spix = k & 3;
        bool valid_y = !(k < yh_eff || k >= yl_eff);
        /* Interlaced field scissoring: only scanlines matching the SET_SCISSOR
         * field parity are rasterized (n64brew SET_SCISSOR; ParaLLEl-RDP
         * invalidates mismatching lines in span setup). */
        if (rdp->m_scissor.m_field && (uint8_t)(j & 1) != rdp->m_scissor.m_keep_odd)
            valid_y = false;

        if (spanidx >= 0 && spanidx < 4096)
        {
            majorxint[spix] = xend;
            minorxint[spix] = xstart;
            majorx[spix] = xright_c;
            minorx[spix] = xleft_c;

            if (spix == 0)
            {
                startx = flip ? 0 : 0xfff;
                endx = flip ? 0xfff : 0;
                /* Burst model samples the subline-0 left edge. */
                fburst_xlraw0 = xleft_w;
                fburst_xlclip0 = xleft_c;
                fburst_anyvalid = false;
                dps_rawset = false;
                /* Family B samples the raw screen-right edge per subline. */
                famb_xrmax = INT32_MIN;
                famb_xr3 = 0;
                famb_r3valid = 0;
            }

            if (valid_y)
            {
                fburst_anyvalid = true;
                if (dps_on)
                {
                    /* Raw screen-edge integers over the y-valid
                     * sublines: the whole-span drop test operands. */
                    const int32_t drl = (flip ? xright_w : xleft_w) >> 16;
                    const int32_t drr = (flip ? xleft_w : xright_w) >> 16;
                    if (!dps_rawset)
                    {
                        dps_rawl = drl;
                        dps_rawr = drr;
                        dps_rawset = true;
                    }
                    else
                    {
                        if (drl < dps_rawl) dps_rawl = drl;
                        if (drr > dps_rawr) dps_rawr = drr;
                    }
                }
                const int32_t famb_xr = flip ? xleft_w : xright_w;
                if (famb_xr > famb_xrmax)
                    famb_xrmax = famb_xr;
                if (spix == 3)
                {
                    famb_xr3 = famb_xr;
                    famb_r3valid = 1;
                }
                if (flip)
                {
                    startx = rdp_max32(xstart, startx);
                    endx = rdp_min32(xend, endx);
                }
                else
                {
                    startx = rdp_min32(xstart, startx);
                    endx = rdp_max32(xend, endx);
                }
            }

            if (spix == 0)
            {
                if(new_object)
                {
                    object = poly_manager_object_next(&rdp->m_pool);
                    new_object = false;
                }

                spans[spanidx].userdata = (void*)((uint8_t*)rdp->m_aux_buf + rdp->m_aux_buf_ptr);
                /* ares port, plan T13: a record carved fresh is zero, so the
                 * bytes a save state carries never depend on a slot's past */
                memset(spans[spanidx].userdata, 0, sizeof(rdp_span_aux));
                memset(spans[spanidx].param, 0, sizeof(spans[spanidx].param));
                valid = true;
                /* The aux pool is never cleared: default the fill plan off
                 * so a fill span without one (rects, non-adjudicated
                 * triangle families) cannot read a stale plan. */
                ((rdp_span_aux*)spans[spanidx].userdata)->m_fill_plan = 0;
                /* Same aux-residue rule as the fill plan. */
                ((rdp_span_aux*)spans[spanidx].userdata)->m_dps_cap = 0;
                ((rdp_span_aux*)spans[spanidx].userdata)->m_dps_seed_n = 0;
                rdp->m_aux_buf_ptr += sizeof(rdp_span_aux);

                /* Unreachable by construction: this function drains on entry
                 * unless the pool can still fit 4096 aux slots, and spanidx
                 * is bounded to 4096, so m_aux_buf_ptr cannot pass
                 * EXTENT_AUX_COUNT. An exact fit is in bounds -- the slot
                 * just carved ends at the limit, nothing overflowed. */

                /* The producer's per-span work is carving the slot,
                 * storing the coverage edge data below, and assembling
                 * the extent parameters. Aux initialization (combine
                 * memcpy, TMEM pointer, 13 color constants, 20
                 * combiner/blender input resolutions) belongs to the
                 * WORKER at span entry (rdp_span_aux_init), sourced from
                 * the per-primitive snapshot in rdp_poly_state: it keeps
                 * the producer core off the small-primitive ceiling. */
            }

            if (spix == 3)
            {
                spans[spanidx].startx = startx;
                spans[spanidx].stopx = endx;
                if (dps_on && rdp->m_dps.nrows < RDP_DPS_ROWS)
                {
                    /* Consuming rows only: within the y-scissor and
                     * interlace clamp render_spans applies, the raw
                     * edge range meeting the x-scissor (raw right ==
                     * scissor left kept), nonempty clamped range. */
                    const int32_t cx1 = (int32_t)rdp->m_scissor.m_xh_clip;
                    const int32_t cx2 = (int32_t)rdp->m_scissor.m_xl_clip;
                    const int32_t exlo = startx < endx ? startx : endx;
                    const int32_t exhi = startx < endx ? endx : startx;
                    const int32_t px0 = exlo < cx1 ? cx1 : exlo;
                    const int32_t px1 = exhi >= cx2 ? cx2 - 1 : exhi;
                    const bool dps_yvis = j >= clipy1 && j < clipy2 &&
                        !(rdp->m_scissor.m_field &&
                          (uint8_t)(j & 1) != rdp->m_scissor.m_keep_odd);
                    if (dps_yvis && dps_rawset && dps_rawr >= cx1 &&
                        dps_rawl < cx2 && px0 <= px1)
                    {
                        rdp_dps_model_t *dm = &rdp->m_dps;
                        dm->row_x0[dm->nrows] = (int16_t)(px0 >> dps_sh);
                        dm->row_x1[dm->nrows] = (int16_t)(px1 >> dps_sh);
                        dm->row_span[dm->nrows] = spanidx;
                        dm->nrows++;
                    }
                }
                /* Coverage belongs to the workers: store this
                 * scanline's subpixel edge values and let the span
                 * callback replay compute_cvg from them. Fill and copy
                 * never read m_cvg, so those spans skip coverage work
                 * entirely. */
                rdp_span_aux* cvg_ud = (rdp_span_aux*)spans[spanidx].userdata;
                for (int32_t cvg_k = 0; cvg_k < 4; cvg_k++)
                {
                    cvg_ud->m_cvg_majorx[cvg_k] = majorx[cvg_k];
                    cvg_ud->m_cvg_minorx[cvg_k] = minorx[cvg_k];
                    cvg_ud->m_cvg_majorxint[cvg_k] = majorxint[cvg_k];
                    cvg_ud->m_cvg_minorxint[cvg_k] = minorxint[cvg_k];
                }

                /* Burst model: feed rows in the render window, in order.
                 * spread is the raw left edge's sub3 - sub0 delta (the k=0
                 * close-suppression comparand); is_last marks the final
                 * valid row (the last-row behavior group). */
                if (fburst.active && j >= fburst_start && j <= fburst_end)
                {
                    fburst_spread = xleft_w - fburst_xlraw0;
                    fill_burst_row(&fburst, fburst_anyvalid ? 1 : 0,
                                   startx, endx,
                                   (int64_t)fburst_xlclip0,
                                   (int64_t)fburst_xlraw0,
                                   fburst_spread,
                                   (j == fburst_lastj) ? 1 : 0, cvg_ud);
                }
                if (famb.active && j >= fburst_start && j <= fburst_end)
                {
                    fill_famb_row(&famb, fburst_anyvalid ? 1 : 0,
                                  startx, famb_xrmax, famb_xr3,
                                  famb_r3valid, j, cvg_ud);
                }
            }

            if (spix == ldflag)
            {
                ((rdp_span_aux*)spans[spanidx].userdata)->m_unscissored_rx = xend_unsc;
                xfrac = ((xright >> 8) & 0xff);
                /* Hardware clears the low 10 bits of every span-start
                 * attribute (ParaLLEl-RDP span setup masks the assembled
                 * RGBA and STZW span-start vectors & ~0x3ff alike). An
                 * S/T/W-only & ~0x1f keeps junk low bits that shift the
                 * per-pixel carry chain: one-LSB texel/shade deltas when
                 * the gradients carry low bits. */
                spans[spanidx].param[SPAN_R].start = rdp_attr_start(r, drdiff, xfrac, drdxh);
                spans[spanidx].param[SPAN_G].start = rdp_attr_start(g, dgdiff, xfrac, dgdxh);
                spans[spanidx].param[SPAN_B].start = rdp_attr_start(b, dbdiff, xfrac, dbdxh);
                spans[spanidx].param[SPAN_A].start = rdp_attr_start(a, dadiff, xfrac, dadxh);
                spans[spanidx].param[SPAN_S].start = rdp_attr_start(s, dsdiff, xfrac, dsdxh);
                spans[spanidx].param[SPAN_T].start = rdp_attr_start(t, dtdiff, xfrac, dtdxh);
                spans[spanidx].param[SPAN_W].start = rdp_attr_start(w, dwdiff, xfrac, dwdxh);
                spans[spanidx].param[SPAN_Z].start = rdp_attr_start(z, dzdiff, xfrac, dzdxh);
            }
        }

        if (spix == 3)
        {
            r = rdp_sadd(r, drde);
            g = rdp_sadd(g, dgde);
            b = rdp_sadd(b, dbde);
            a = rdp_sadd(a, dade);
            s = rdp_sadd(s, dsde);
            t = rdp_sadd(t, dtde);
            w = rdp_sadd(w, dwde);
            z = rdp_sadd(z, dzde);
        }
        xleft += xleft_inc;
        xright += xright_inc;
    }

    if(!new_object && valid)
    {
        if (dps_on)
            rdp_dps_schedule(rdp, spans);
        object->m_cvg_yh = yh_eff;
        object->m_cvg_yl = yl_eff;
        rdp_render_spans(rdp, yh >> 2, yl >> 2, tilenum, flip ? true : false, spans, rect, object);
    }
    /* No per-primitive wait: the aux slots this primitive carved stay
     * valid until the next rdp_pipeline_drain (loads, Sync Full, end
     * of command list, or the pool-pressure check above); m_aux_buf_ptr
     * grows monotonically between drains, so in-flight userdata is never
     * recycled while workers hold it, leaving cross-primitive parallelism
     * intact. */
}

/*****************************************************************************/

////////////////////////
// RDP COMMANDS
////////////////////////
/* None of the command handlers below drain the span queue. Ordering
 * against in-flight spans is enforced where it is actually needed --
 * rdp_tmem_load_gate for TMEM sources, the aux-buffer lifetime for span
 * state, and rdp_pipeline_drain at the coarse boundaries -- so a
 * per-command wait would only serialize the walk against work that
 * cannot observe it. */
static void rdp_triangle(rdp_t *rdp, uint64_t *cmd_buf, bool shade, bool texture, bool zbuffer)
{
    rdp_draw_triangle(rdp, cmd_buf, shade, texture, zbuffer, false);
    rdp->m_pipe_clean = false;
}
/* Shared body of tex_rect / tex_rect_flip: the two differed only in the
 * synthesized command opcode and in which screen axis each texture
 * derivative feeds (flip swaps dsdx into the edge/Y slots and dtdy into
 * the X slots). Field packings preserved verbatim per variant. */
static void rdp_cmd_tex_rect_common(rdp_t *rdp, uint64_t *cmd_buf, const int flip)
{
    const uint64_t w1 = cmd_buf[0];
    const uint64_t w2 = cmd_buf[1];

    const uint64_t tilenum = (w1 >> 24) & 0x7;
    const uint64_t xh = (w1 >> 12) & 0xfff;
    const uint64_t xl = (w1 >> 44) & 0xfff;
    const uint64_t yh = (w1 >>  0) & 0xfff;
    uint64_t yl       = (w1 >> 32) & 0xfff;

    const uint64_t s  = (w2 >> 48) & 0xffff;
    const uint64_t t  = (w2 >> 32) & 0xffff;
    const uint64_t dsdx = SIGN16((w2 >> 16) & 0xffff);
    const uint64_t dtdy = SIGN16((w2 >>  0) & 0xffff);

    if (rdp->m_other_modes.cycle_type == CYCLE_TYPE_FILL || rdp->m_other_modes.cycle_type == CYCLE_TYPE_COPY)
    {
        yl |= 3;
    }

    const uint64_t xlint = (xl >> 2) & 0x3ff;
    const uint64_t xhint = (xh >> 2) & 0x3ff;

    uint64_t* ewdata = rdp->m_temp_rect_data;
    ewdata[0] = ((uint64_t)(flip ? 0x25 : 0x24) << 56) | ((0x80L | tilenum) << 48) | (yl << 32) | (yl << 16) | yh;   // command, flipped, tile, yl
    ewdata[1] = (xlint << 48) | ((xl & 3) << 46);               // xl, xl frac, dxldy (0), dxldy frac (0)
    ewdata[2] = (xhint << 48) | ((xh & 3) << 46);               // xh, xh frac, dxhdy (0), dxhdy frac (0)
    ewdata[3] = (xlint << 48) | ((xl & 3) << 46);               // xm, xm frac, dxmdy (0), dxmdy frac (0)
    memset(&ewdata[4], 0, 8 * sizeof(uint64_t));                // shade
    ewdata[12] = (s << 48) | (t << 32);                         // s, t, w (0)
    ewdata[14] = 0;                                             // s frac (0), t frac (0), w frac (0)
    if (!flip)
    {
        ewdata[13] = (dsdx >> 5) << 48;                         // dsdx, dtdx, dwdx (0)
        ewdata[15] = (dsdx & 0x1f) << 59;                       // dsdx frac, dtdx frac, dwdx frac (0)
        ewdata[16] = ((dtdy >> 5) & 0xffff) << 32;              // dsde, dtde, dwde (0)
        ewdata[17] = ((dtdy >> 5) & 0xffff) << 32;              // dsdy, dtdy, dwdy (0)
        ewdata[18] = ((dtdy & 0x1f) << 11) << 32;               // dsde frac, dtde frac, dwde frac (0)
        ewdata[19] = ((dtdy & 0x1f) << 11) << 32;               // dsdy frac, dtdy frac, dwdy frac (0)
    }
    else
    {
        ewdata[13] = ((dtdy >> 5) & 0xffff) << 32;              // dsdx, dtdx, dwdx (0)
        ewdata[15] = ((dtdy & 0x1f) << 43);                     // dsdx frac, dtdx frac, dwdx frac (0)
        ewdata[16] = (dsdx >> 5) << 48;                         // dsde, dtde, dwde (0)
        ewdata[17] = (dsdx >> 5) << 48;                         // dsdy, dtdy, dwdy (0)
        ewdata[18] = (dsdx & 0x1f) << 59;                       // dsde frac, dtde frac, dwde frac (0)
        ewdata[19] = (dsdx & 0x1f) << 59;                       // dsdy frac, dtdy frac, dwdy frac (0)
    }
    // ewdata[40-43] = 0;                                       // depth

    rdp_draw_triangle(rdp, cmd_buf, true, true, false, true);
}

static void rdp_cmd_tex_rect(rdp_t *rdp, uint64_t *cmd_buf)
{
    rdp_cmd_tex_rect_common(rdp, cmd_buf, 0);
}

static void rdp_cmd_tex_rect_flip(rdp_t *rdp, uint64_t *cmd_buf)
{
    rdp_cmd_tex_rect_common(rdp, cmd_buf, 1);
}
static void rdp_cmd_sync_load(rdp_t *rdp, uint64_t *cmd_buf)
{
    (void)rdp;
    (void)cmd_buf;
}
static void rdp_cmd_sync_pipe(rdp_t *rdp, uint64_t *cmd_buf)
{
    (void)rdp;
    (void)cmd_buf;
}
static void rdp_cmd_sync_tile(rdp_t *rdp, uint64_t *cmd_buf)
{
    (void)rdp;
    (void)cmd_buf;
}
static void rdp_cmd_sync_full(rdp_t *rdp, uint64_t *cmd_buf)
{
    (void)cmd_buf;
    /* Sync Full is the architectural completion point: the queue
     * drains here. The aux buffer cursor resets with it. */
    rdp_pipeline_drain(rdp);

    /* The host raises the DP interrupt when this command retires. */
}
static void rdp_cmd_set_key_gb(rdp_t *rdp, uint64_t *cmd_buf)
{
    rgbaint_set_b(&rdp->m_key_scale, (uint32_t)(cmd_buf[0] >>  0) & 0xff);
    rgbaint_set_g(&rdp->m_key_scale, (uint32_t)(cmd_buf[0] >> 16) & 0xff);
    rgbaint_set_b(&rdp->m_key_center, (uint32_t)(cmd_buf[0] >>  8) & 0xff);
    rgbaint_set_g(&rdp->m_key_center, (uint32_t)(cmd_buf[0] >> 24) & 0xff);
    rgbaint_set_b(&rdp->m_key_width, (uint32_t)(cmd_buf[0] >> 32) & 0xfff);
    rgbaint_set_g(&rdp->m_key_width, (uint32_t)(cmd_buf[0] >> 44) & 0xfff);
}
static void rdp_cmd_set_key_r(rdp_t *rdp, uint64_t *cmd_buf)
{
    rgbaint_set_r(&rdp->m_key_scale, (uint32_t)(cmd_buf[0] & 0xff));
    rgbaint_set_r(&rdp->m_key_center, (uint32_t)(cmd_buf[0] >> 8) & 0xff);
    rgbaint_set_r(&rdp->m_key_width, (uint32_t)(cmd_buf[0] >> 16) & 0xfff);
}
static void rdp_cmd_set_fill_color32(rdp_t *rdp, uint64_t *cmd_buf)
{
    rdp->m_fill_color = (uint32_t)cmd_buf[0];
}
static void rdp_cmd_set_convert(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];

    if(!rdp->m_pipe_clean) { rdp->m_pipe_clean = true; poly_manager_wait(&rdp->m_pool); }
    int32_t k0 = (int32_t)(w1 >> 45) & 0x1ff;
    int32_t k1 = (int32_t)(w1 >> 36) & 0x1ff;
    int32_t k2 = (int32_t)(w1 >> 27) & 0x1ff;
    int32_t k3 = (int32_t)(w1 >> 18) & 0x1ff;
    int32_t k4 = (int32_t)(w1 >>  9) & 0x1ff;
    int32_t k5 = (int32_t)(w1 >>  0) & 0x1ff;

    k0 = (SIGN9(k0) << 1) + 1;
    k1 = (SIGN9(k1) << 1) + 1;
    k2 = (SIGN9(k2) << 1) + 1;
    k3 = (SIGN9(k3) << 1) + 1;

    rdp_set_yuv_factors(rdp, rgbaint_make(0, k0, k2, 0), rgbaint_make(0, 0, k1, k3), rgbaint_make(k4, k4, k4, k4), rgbaint_make(k5, k5, k5, k5));
}
static void rdp_cmd_set_scissor(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];

    rdp->m_scissor.m_xh = ((w1 >> 44) & 0xfff) >> 2;
    rdp->m_scissor.m_xh_clip = (((w1 >> 44) & 0xfff) + 3) >> 2;
    rdp->m_scissor.m_xh_raw = (w1 >> 44) & 0xfff;
    rdp->m_scissor.m_yh = ((w1 >> 32) & 0xfff) >> 2;
    rdp->m_scissor.m_yh_clip = (((w1 >> 32) & 0xfff) + 3) >> 2;
    rdp->m_scissor.m_xl = ((w1 >> 12) & 0xfff) >> 2;
    rdp->m_scissor.m_xl_clip = (((w1 >> 12) & 0xfff) + 3) >> 2;
    rdp->m_scissor.m_xl_raw = (w1 >> 12) & 0xfff;
    rdp->m_scissor.m_yl = ((w1 >>  0) & 0xfff) >> 2;
    rdp->m_scissor.m_yl_clip = (((w1 >>  0) & 0xfff) + 3) >> 2;
    rdp->m_scissor.m_yh_raw = (w1 >> 32) & 0xfff;
    rdp->m_scissor.m_yl_raw = (w1 >>  0) & 0xfff;

    /* bit 25 = field (interlaced rendering): only scanlines whose parity
     * matches bit 24 (odd) are rasterized -- the walker invalidates the
     * others, like ParaLLEl-RDP span setup's interlace valid_line check.
     * Under interlace the dither matrix is also indexed by y bits [2:1]
     * rather than [1:0] (n64brew; ParaLLEl passes y >> interlace_en to
     * dither_coefficients). */
    rdp->m_scissor.m_field = (uint8_t)((w1 >> 25) & 1);
    rdp->m_scissor.m_keep_odd = (uint8_t)((w1 >> 24) & 1);
}
static void rdp_cmd_set_prim_depth(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_misc_state.m_primitive_z = (uint16_t)(w1 >> 16) & 0x7fff;
    /* Set Primitive Depth (0x2e) packs z in bits [31:16] and dz in bits
     * [15:0]; bits [47:32] are unused and always zero (n64brew, Reality
     * Display Processor/Commands).
     *
     * The blender applies a memory-alpha shift derived from log2(dz).
     * n64brew notes that dz should be a power of two, because the
     * hardware's cheap integer log2 is only guaranteed correct for such
     * inputs -- with 0xFFFF a documented exception that also works. A
     * full dz therefore yields log2 == 15 and no shift, which is how
     * OoT's pause PreRender disables the shift while it reads
     * framebuffer coverage back through the CPU; decoding dz as 0
     * instead would give the maximal shift of 4 and collapse memory
     * coverage. */
    rdp->m_misc_state.m_primitive_dz = (uint16_t)w1;
}
static void rdp_cmd_set_other_modes(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_other_modes.atomic_prim      = (w1 >> 55) & 1;
    rdp->m_other_modes.cycle_type       = (w1 >> 52) & 0x3; // 01
    rdp->m_other_modes.persp_tex_en     = (w1 >> 51) & 1; // 1
    rdp->m_other_modes.detail_tex_en    = (w1 >> 50) & 1; // 0
    rdp->m_other_modes.sharpen_tex_en   = (w1 >> 49) & 1; // 0
    rdp->m_other_modes.tex_lod_en       = (w1 >> 48) & 1; // 0
    rdp->m_other_modes.en_tlut          = (w1 >> 47) & 1; // 0
    rdp->m_other_modes.tlut_type        = (w1 >> 46) & 1; // 0
    rdp->m_other_modes.sample_type      = (w1 >> 45) & 1; // 1
    rdp->m_other_modes.mid_texel        = (w1 >> 44) & 1; // 0
    rdp->m_other_modes.bi_lerp0         = (w1 >> 43) & 1; // 1
    rdp->m_other_modes.bi_lerp1         = (w1 >> 42) & 1; // 1
    rdp->m_other_modes.convert_one      = (w1 >> 41) & 1; // 0
    rdp->m_other_modes.key_en           = (w1 >> 40) & 1; // 0
    rdp->m_other_modes.rgb_dither_sel   = (w1 >> 38) & 0x3; // 00
    rdp->m_other_modes.alpha_dither_sel = (w1 >> 36) & 0x3; // 01
    rdp->m_other_modes.blend_m1a_0      = (w1 >> 30) & 0x3; // 11
    rdp->m_other_modes.blend_m1a_1      = (w1 >> 28) & 0x3; // 00
    rdp->m_other_modes.blend_m1b_0      = (w1 >> 26) & 0x3; // 10
    rdp->m_other_modes.blend_m1b_1      = (w1 >> 24) & 0x3; // 00
    rdp->m_other_modes.blend_m2a_0      = (w1 >> 22) & 0x3; // 00
    rdp->m_other_modes.blend_m2a_1      = (w1 >> 20) & 0x3; // 01
    rdp->m_other_modes.blend_m2b_0      = (w1 >> 18) & 0x3; // 00
    rdp->m_other_modes.blend_m2b_1      = (w1 >> 16) & 0x3; // 01
    rdp->m_other_modes.force_blend      = (w1 >> 14) & 1; // 0
    rdp->m_other_modes.blend_shift      = rdp->m_other_modes.force_blend ? 5 : 2;
    rdp->m_other_modes.alpha_cvg_select = (w1 >> 13) & 1; // 1
    rdp->m_other_modes.cvg_times_alpha  = (w1 >> 12) & 1; // 0
    rdp->m_other_modes.z_mode           = (w1 >> 10) & 0x3; // 00
    rdp->m_other_modes.cvg_dest         = (w1 >> 8) & 0x3; // 00
    rdp->m_other_modes.color_on_cvg     = (w1 >> 7) & 1; // 0
    rdp->m_other_modes.image_read_en    = (w1 >> 6) & 1; // 1
    rdp->m_other_modes.z_update_en      = (w1 >> 5) & 1; // 1
    rdp->m_other_modes.z_compare_en     = (w1 >> 4) & 1; // 1
    rdp->m_other_modes.antialias_en     = (w1 >> 3) & 1; // 1
    rdp->m_other_modes.z_source_sel     = (w1 >> 2) & 1; // 0
    rdp->m_other_modes.dither_alpha_en  = (w1 >> 1) & 1; // 0
    rdp->m_other_modes.alpha_compare_en = (w1 >> 0) & 1; // 0
    rdp->m_other_modes.alpha_dither_mode = (rdp->m_other_modes.alpha_compare_en << 1) | rdp->m_other_modes.dither_alpha_en;
}
static void rdp_cmd_load_tlut(rdp_t *rdp, uint64_t *cmd_buf)
{
    rdp_tile_t* tile = rdp->m_tiles;
    const uint64_t w1 = cmd_buf[0];

    const int32_t tilenum = (w1 >> 24) & 0x7;
    const int32_t sl = tile[tilenum].sl = (int32_t)(w1 >> 44) & 0xfff;
    const int32_t tl = tile[tilenum].tl = (int32_t)(w1 >> 32) & 0xfff;
    const int32_t sh = tile[tilenum].sh = (int32_t)(w1 >> 12) & 0xfff;
    tile[tilenum].th = (int32_t)(w1 >>  0) & 0xfff;

    const int32_t count = ((sh >> 2) - (sl >> 2) + 1) << 2;

    rdp_tmem_load_gate(rdp);

    // A load whose s-range is inverted (sl > sh) transfers no texels.
    // Donkey Kong 64 issues exactly such a degenerate load, with a
    // multi-row t-range on top (cmd f0ce595cdc7b3d88, sl=3301 sh=1971
    // tl=2396 th=3464); the game runs on real hardware, so a no-texel
    // load must not be treated as a pipeline halt whatever its row
    // span. Tile registers still update, TMEM is untouched.
    if (count <= 0)
    {
        rdp->m_tiles[tilenum].sth = rgbaint_make(rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].th, rdp->m_tiles[tilenum].th);
        rdp->m_tiles[tilenum].stl = rgbaint_make(rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].tl, rdp->m_tiles[tilenum].tl);
        return;
    }

    // A Load_TLUT whose t-range spans multiple texel rows (th row above
    // tl row) is "generally undesirable for rendering" but is NOT an RDP
    // pipeline halt. n64brew documents the Load_TLUT hazards as tile
    // texel-size/format configuration and TMEM base alignment only; there
    // is no multi-row halt, and a differing t-range merely updates the
    // tile size registers. The prior code set m_pipeline_crashed here,
    // which aborts the command list before its Sync_Full -> no MI_INTR_DP
    // -> the game hangs in its RDP-done wait (Banjo-Kazooie issues such a
    // load, e.g. cmd f0c2b19e41d0fe65 sl=3115 tl=414 sh=3343 th=3685, and
    // runs on real hardware). Load from the upper-left (tl) row like any
    // other TLUT load and let the list run to Sync_Full; the tile size
    // registers are updated at the end of this function.

    // Load_TLUT reads fixed-function 16-bit palette entries and quadruples
    // each across the four TMEM banks, whatever the texture image's texel
    // size is (n64brew RDP/Commands, Load TLUT: "every texel loaded from
    // RDRAM is quadrupled and placed adjacently in TMEM"). ti_size therefore
    // selects the SOURCE ADDRESSING only, and does so through the same
    // address generator every load command uses: row stride
    // (ti_width << size) >> 1 bytes, s byte offset (s << size) >> 3 with the
    // two coordinate fraction bits folded in. All four sizes take this one
    // path.
    //
    // The documented correct usage is a 16-bit texture image (Load TLUT
    // hazards), but games do issue TLUT loads against other sizes and
    // hardware executes them: Jet Force Gemini stages palettes from a
    // 32-bit image, and Banjo-Kazooie issues a 4-bit one after the intro.
    // The 4-bit "load hazard" that does exist applies to TEXEL loads
    // (Load_Block/Load_Tile, whose address generator cannot address 4-bit
    // data); Load_TLUT does not go through it, so a 4-bit ti_size here is
    // not a pipeline crash and must not abort the command list -- an
    // abort would drop the list's Sync_Full and with it the DP interrupt.
    //
    // (sl << sz) >> 3 generalizes the validated 16-bit expression
    // (sl >> 1) exactly, fraction bits included; sz == 1 reduces to it.
    //
    // HYPOTHESIS pending hardware adjudication (snapper: Load TLUT with
    // ti_size 0/1/3, dump high TMEM): the entry count is taken from the
    // s-range exactly as for 16-bit. If hardware instead derives it from
    // the byte extent, count scales with size and this under/over-loads.
    //
    // Hardware places no restriction on the TMEM destination; TLUT loads
    // into the low half are unusual but not a fault. The dststart bound
    // below is what keeps the write inside TMEM.
    {
        const uint32_t sz = rdp->m_misc_state.m_ti_size;
        const uint32_t rowbytes =
            ((uint32_t)rdp->m_misc_state.m_ti_width << sz) >> 1;
        const uint32_t sbytes = ((uint32_t)sl << sz) >> 3;
        int32_t srcstart = (int32_t)((rdp->m_misc_state.m_ti_address +
            (uint32_t)(tl >> 2) * rowbytes + sbytes) >> 1);
        int32_t dststart = tile[tilenum].tmem << 2;
        uint16_t* dst = ((uint16_t*)rdp->m_tmem);

        for (int32_t i = 0; i < count; i += 4)
        {
            if (dststart < 2048)
            {
                dst[dststart] = RREADIDX16(srcstart);
                dst[dststart + 1] = dst[dststart];
                dst[dststart + 2] = dst[dststart];
                dst[dststart + 3] = dst[dststart];
                dststart += 4;
                srcstart += 1;
            }
        }
    }

    rdp->m_tiles[tilenum].sth = rgbaint_make(rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].th, rdp->m_tiles[tilenum].th);
    rdp->m_tiles[tilenum].stl = rgbaint_make(rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].tl, rdp->m_tiles[tilenum].tl);
}
static void rdp_cmd_set_tile_size(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    const int32_t tilenum = (int32_t)(w1 >> 24) & 0x7;

    rdp->m_tiles[tilenum].sl = (int32_t)(w1 >> 44) & 0xfff;
    rdp->m_tiles[tilenum].tl = (int32_t)(w1 >> 32) & 0xfff;
    rdp->m_tiles[tilenum].sh = (int32_t)(w1 >> 12) & 0xfff;
    rdp->m_tiles[tilenum].th = (int32_t)(w1 >>  0) & 0xfff;

    rdp->m_tiles[tilenum].sth = rgbaint_make(rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].th, rdp->m_tiles[tilenum].th);
    rdp->m_tiles[tilenum].stl = rgbaint_make(rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].tl, rdp->m_tiles[tilenum].tl);
}
static void rdp_cmd_load_block(rdp_t *rdp, uint64_t *cmd_buf)
{
    rdp_tile_t* tile = rdp->m_tiles;
    const uint64_t w1 = cmd_buf[0];

    const unsigned tilenum = (unsigned)(w1 >> 24) & 0x7;
    uint16_t* tc;

    int32_t sl, tl, sh, dxt;
    tile[tilenum].sl =  sl = (int32_t)((w1 >> 44) & 0xfff);
    tile[tilenum].tl =  tl = (int32_t)((w1 >> 32) & 0xfff);
    tile[tilenum].sh =  sh = (int32_t)((w1 >> 12) & 0xfff);
    tile[tilenum].th = dxt = (int32_t)((w1 >>  0) & 0xfff);

    rdp_tmem_load_gate(rdp);

    tc = ((uint16_t*)rdp->m_tmem);

    /*uint16_t tl_masked = tl & 0x3ff;

    int32_t load_edge_walker_data[10] = {
        ((cmd_buf[0] >> 32) & 0xff000000) | (0x10 << 19) | (tilenum << 16) | ((tl_masked << 2) | 3),
        (((tl_masked << 2) | 3) << 16) | (tl_masked << 2),
        sh << 16,
        sl << 16,
        sh << 16,
        ((sl << 3) << 16) | (tl << 3),
        (dxt & 0xff) << 8,
        ((0x80 >> wstate->ti_size) << 16) | (dxt >> 8),
        0x20,
        0x20
    };

    do_load_edge_walker(load_edge_walker_data);*/

    int32_t width = (sh - sl) + 1;
    if (width > 2048)
        return;

    width = (width << rdp->m_misc_state.m_ti_size) >> 1;
    if (width & 7)
    {
        width = (width & ~7) + 8;
    }
    width >>= 3;

    const int32_t tb = tile[tilenum].tmem << 2;

    const int32_t tiwinwords = (rdp->m_misc_state.m_ti_width << rdp->m_misc_state.m_ti_size) >> 2;
    const int32_t slinwords = (sl << rdp->m_misc_state.m_ti_size) >> 2;

    const unsigned src = (rdp->m_misc_state.m_ti_address >> 1) + (tl * tiwinwords) + slinwords;

    if (dxt != 0)
    {
        int32_t j = 0;
        int32_t t = 0;
        int32_t oldt = 0;

        if (tile[tilenum].size != PIXEL_SIZE_32BIT && tile[tilenum].format != FORMAT_YUV)
        {
            for (int32_t i = 0; i < width; i ++)
            {
                oldt = t;
                t = ((j >> 11) & 1) ? WORD_XOR_DWORD_SWAP : HWORD_IN_WORD_XOR;
                if (t != oldt)
                {
                    i += tile[tilenum].line;
                }

                int32_t ptr = tb + (i << 2);
                int32_t srcptr = src + (i << 2);

                tc[(ptr ^ t) & 0x7ff] = RREADIDX16(srcptr);
                tc[((ptr + 1) ^ t) & 0x7ff] = RREADIDX16(srcptr + 1);
                tc[((ptr + 2) ^ t) & 0x7ff] = RREADIDX16(srcptr + 2);
                tc[((ptr + 3) ^ t) & 0x7ff] = RREADIDX16(srcptr + 3);

                j += dxt;
            }
        }
        else if (tile[tilenum].format == FORMAT_YUV)
        {
            for (int32_t i = 0; i < width; i ++)
            {
                oldt = t;
                t = ((j >> 11) & 1) ? WORD_XOR_DWORD_SWAP : HWORD_IN_WORD_XOR;
                if (t != oldt)
                {
                    i += tile[tilenum].line;
                }

                int32_t ptr = ((tb + (i << 1)) ^ t) & 0x3ff;
                int32_t srcptr = src + (i << 2);

                int32_t first = RREADIDX16(srcptr);
                int32_t sec = RREADIDX16(srcptr + 1);
                tc[ptr] = ((first >> 8) << 8) | (sec >> 8);
                tc[ptr | 0x400] = ((first & 0xff) << 8) | (sec & 0xff);

                ptr = ((tb + (i << 1) + 1) ^ t) & 0x3ff;
                first = RREADIDX16(srcptr + 2);
                sec = RREADIDX16(srcptr + 3);
                tc[ptr] = ((first >> 8) << 8) | (sec >> 8);
                tc[ptr | 0x400] = ((first & 0xff) << 8) | (sec & 0xff);

                j += dxt;
            }
        }
        else
        {
            for (int32_t i = 0; i < width; i ++)
            {
                oldt = t;
                t = ((j >> 11) & 1) ? WORD_XOR_DWORD_SWAP : HWORD_IN_WORD_XOR;
                if (t != oldt)
                    i += tile[tilenum].line;

                int32_t ptr = ((tb + (i << 1)) ^ t) & 0x3ff;
                int32_t srcptr = src + (i << 2);
                tc[ptr] = RREADIDX16(srcptr);
                tc[ptr | 0x400] = RREADIDX16(srcptr + 1);

                ptr = ((tb + (i << 1) + 1) ^ t) & 0x3ff;
                tc[ptr] = RREADIDX16(srcptr + 2);
                tc[ptr | 0x400] = RREADIDX16(srcptr + 3);

                j += dxt;
            }
        }
        tile[tilenum].th = tl + (j >> 11);
    }
    else
    {
        if (tile[tilenum].size != PIXEL_SIZE_32BIT && tile[tilenum].format != FORMAT_YUV)
        {
            for (int32_t i = 0; i < width; i ++)
            {
                int32_t ptr = tb + (i << 2);
                int32_t srcptr = src + (i << 2);
                tc[(ptr ^ HWORD_IN_WORD_XOR) & 0x7ff] = RREADIDX16(srcptr);
                tc[((ptr + 1) ^ HWORD_IN_WORD_XOR) & 0x7ff] = RREADIDX16(srcptr + 1);
                tc[((ptr + 2) ^ HWORD_IN_WORD_XOR) & 0x7ff] = RREADIDX16(srcptr + 2);
                tc[((ptr + 3) ^ HWORD_IN_WORD_XOR) & 0x7ff] = RREADIDX16(srcptr + 3);

            }
        }
        else if (tile[tilenum].format == FORMAT_YUV)
        {
            for (int32_t i = 0; i < width; i ++)
            {
                int32_t ptr = ((tb + (i << 1)) ^ HWORD_IN_WORD_XOR) & 0x3ff;
                int32_t srcptr = src + (i << 2);
                int32_t first = RREADIDX16(srcptr);
                int32_t sec = RREADIDX16(srcptr + 1);
                tc[ptr] = ((first >> 8) << 8) | (sec >> 8);//UV pair
                tc[ptr | 0x400] = ((first & 0xff) << 8) | (sec & 0xff);

                ptr = ((tb + (i << 1) + 1) ^ HWORD_IN_WORD_XOR) & 0x3ff;
                first = RREADIDX16(srcptr + 2);
                sec = RREADIDX16(srcptr + 3);
                tc[ptr] = ((first >> 8) << 8) | (sec >> 8);
                tc[ptr | 0x400] = ((first & 0xff) << 8) | (sec & 0xff);

            }
        }
        else
        {
            for (int32_t i = 0; i < width; i ++)
            {
                int32_t ptr = ((tb + (i << 1)) ^ HWORD_IN_WORD_XOR) & 0x3ff;
                int32_t srcptr = src + (i << 2);
                tc[ptr] = RREADIDX16(srcptr);
                tc[ptr | 0x400] = RREADIDX16(srcptr + 1);

                ptr = ((tb + (i << 1) + 1) ^ HWORD_IN_WORD_XOR) & 0x3ff;
                tc[ptr] = RREADIDX16(srcptr + 2);
                tc[ptr | 0x400] = RREADIDX16(srcptr + 3);

            }
        }
        tile[tilenum].th = tl;
    }

    rdp->m_tiles[tilenum].sth = rgbaint_make(rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].th, rdp->m_tiles[tilenum].th);
    rdp->m_tiles[tilenum].stl = rgbaint_make(rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].tl, rdp->m_tiles[tilenum].tl);
}
static void rdp_cmd_load_tile(rdp_t *rdp, uint64_t *cmd_buf)
{
    rdp_tile_t* tile = rdp->m_tiles;
    const uint64_t w1 = cmd_buf[0];
    const int32_t tilenum = (int32_t)(w1 >> 24) & 0x7;

    tile[tilenum].sl    = (int32_t)(w1 >> 44) & 0xfff;
    tile[tilenum].tl    = (int32_t)(w1 >> 32) & 0xfff;
    tile[tilenum].sh    = (int32_t)(w1 >> 12) & 0xfff;
    tile[tilenum].th    = (int32_t)(w1 >>  0) & 0xfff;

    const int32_t sl = tile[tilenum].sl >> 2;
    const int32_t tl = tile[tilenum].tl >> 2;
    const int32_t sh = tile[tilenum].sh >> 2;
    const int32_t th = tile[tilenum].th >> 2;

    int32_t width = (sh - sl) + 1;
    const int32_t height = (th - tl) + 1;

    /* The loading pipeline moves 64 bits per cycle, so a row is loaded
     * as whole TMEM words: the row's texel count rounds up to the word
     * (8 at 8 bpp, 4 at 16, 2 at 32), and the texels past sh that pad
     * the last word are fetched from RDRAM and written to TMEM along
     * with it (n64brew RDP/Commands, Set Tile: Load Tile performs the
     * row padding to a new TMEM word transparently; ParaLLEl-RDP
     * load_tile_iteration rounds the upload width the same way). A tile
     * sampled one texel past sh -- Killer Instinct Gold's fighter strips
     * load 15 CI8 texels and filter up to the 16th -- reads that padding
     * texel, not whatever the word held before the load. */
    switch (rdp->m_misc_state.m_ti_size)
    {
        case PIXEL_SIZE_8BIT:  width = (width + 7) & ~7; break;
        case PIXEL_SIZE_16BIT: width = (width + 3) & ~3; break;
        case PIXEL_SIZE_32BIT: width = (width + 1) & ~1; break;
        default: break;
    }

    rdp_tmem_load_gate(rdp);
/*
    int32_t topad;
    if (m_misc_state.m_ti_size < 3)
    {
        topad = (width * m_misc_state.m_ti_size) & 0x7;
    }
    else
    {
        topad = (width << 2) & 0x7;
    }
    topad = 0; // ????
*/

    switch (rdp->m_misc_state.m_ti_size)
    {
        case PIXEL_SIZE_8BIT:
        {
            const unsigned src = rdp->m_misc_state.m_ti_address;
            const int32_t tb = tile[tilenum].tmem << 3;
            uint8_t* tc = rdp->m_tmem;

            for (int32_t j = 0; j < height; j++)
            {
                const int32_t tline = tb + ((tile[tilenum].line << 3) * j);
                const int32_t s = ((j + tl) * rdp->m_misc_state.m_ti_width) + sl;
                const int32_t xorval8 = ((j & 1) ? BYTE_XOR_DWORD_SWAP : BYTE_IN_WORD_XOR);

                for (int32_t i = 0; i < width; i++)
                {
                    const unsigned data = RREADADDR8(src + s + i);
                    tc[((tline + i) ^ xorval8) & 0xfff] = data;
                }
            }
            break;
        }
        case PIXEL_SIZE_16BIT:
        {
            const unsigned src = rdp->m_misc_state.m_ti_address >> 1;
            uint16_t* tc = ((uint16_t*)rdp->m_tmem);

            if (tile[tilenum].format != FORMAT_YUV)
            {
                for (int32_t j = 0; j < height; j++)
                {
                    const int32_t tb = tile[tilenum].tmem << 2;
                    const int32_t tline = tb + ((tile[tilenum].line << 2) * j);
                    const int32_t s = ((j + tl) * rdp->m_misc_state.m_ti_width) + sl;
                    const int32_t xorval16 = (j & 1) ? WORD_XOR_DWORD_SWAP : HWORD_IN_WORD_XOR;

                    for (int32_t i = 0; i < width; i++)
                    {
                        const unsigned taddr = (tline + i) ^ xorval16;
                        const unsigned data = RREADIDX16(src + s + i);
                        tc[taddr & 0x7ff] = data;
                    }
                }
            }
            else
            {
                for (int32_t j = 0; j < height; j++)
                {
                    const int32_t tb = tile[tilenum].tmem << 3;
                    const int32_t tline = tb + ((tile[tilenum].line << 3) * j);
                    const int32_t s = ((j + tl) * rdp->m_misc_state.m_ti_width) + sl;
                    const int32_t xorval8 = (j & 1) ? BYTE_XOR_DWORD_SWAP : BYTE_IN_WORD_XOR;

                    for (int32_t i = 0; i < width; i++)
                    {
                        unsigned taddr = ((tline + i) ^ xorval8) & 0x7ff;
                        unsigned yuvword = RREADIDX16(src + s + i);
                        rdp->m_tmem[taddr] = yuvword >> 8;
                        rdp->m_tmem[taddr | 0x800] = yuvword & 0xff;
                    }
                }
            }
            break;
        }
        case PIXEL_SIZE_32BIT:
        {
            const unsigned src = rdp->m_misc_state.m_ti_address >> 2;
            const int32_t tb = (tile[tilenum].tmem << 2);
            uint16_t* tc16 = ((uint16_t*)rdp->m_tmem);

            for (int32_t j = 0; j < height; j++)
            {
                const int32_t tline = tb + ((tile[tilenum].line << 2) * j);

                const int32_t s = ((j + tl) * rdp->m_misc_state.m_ti_width) + sl;
                const int32_t xorval32cur = (j & 1) ? WORD_XOR_DWORD_SWAP : HWORD_IN_WORD_XOR;
                for (int32_t i = 0; i < width; i++)
                {
                    unsigned c = RREADIDX32(src + s + i);
                    unsigned ptr = ((tline + i) ^ xorval32cur) & 0x3ff;
                    tc16[ptr] = c >> 16;
                    tc16[ptr | 0x400] = c & 0xffff;
                }
            }
            break;
        }

        default:
            // Only 4-bit remains (2-bit field); 4-bit texture image
            // loads crash the RDP loading pipeline on hardware
            // (n64brew: 4-bit load hazards).
            cen64_log(CEN64_LOG_WRN, "rdp: pipeline crash: 4-bit tile load\n");
            rdp->m_pipeline_crashed = true;
            break;
    }

    rdp->m_tiles[tilenum].sth = rgbaint_make(rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].sh, rdp->m_tiles[tilenum].th, rdp->m_tiles[tilenum].th);
    rdp->m_tiles[tilenum].stl = rgbaint_make(rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].sl, rdp->m_tiles[tilenum].tl, rdp->m_tiles[tilenum].tl);
}
static void rdp_cmd_set_tile(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    const int32_t tilenum = (int32_t)(w1 >> 24) & 0x7;
    rdp_tile_t* tex_tile = &rdp->m_tiles[tilenum];

    tex_tile->format    = (int32_t)(w1 >> 53) & 0x7;
    tex_tile->size      = (int32_t)(w1 >> 51) & 0x3;
    tex_tile->line      = (int32_t)(w1 >> 41) & 0x1ff;
    tex_tile->tmem      = (int32_t)(w1 >> 32) & 0x1ff;
    tex_tile->palette   = (int32_t)(w1 >> 20) & 0xf;
    tex_tile->ct        = (int32_t)(w1 >> 19) & 0x1;
    tex_tile->mt        = (int32_t)(w1 >> 18) & 0x1;
    tex_tile->mask_t    = (int32_t)(w1 >> 14) & 0xf;
    tex_tile->shift_t   = (int32_t)(w1 >> 10) & 0xf;
    tex_tile->cs        = (int32_t)(w1 >>  9) & 0x1;
    tex_tile->ms        = (int32_t)(w1 >>  8) & 0x1;
    tex_tile->mask_s    = (int32_t)(w1 >>  4) & 0xf;
    tex_tile->shift_s   = (int32_t)(w1 >>  0) & 0xf;

    tex_tile->lshift_s  = (tex_tile->shift_s >= 11) ? (16 - tex_tile->shift_s) : 0;
    tex_tile->rshift_s  = (tex_tile->shift_s < 11) ? tex_tile->shift_s : 0;
    tex_tile->lshift_t  = (tex_tile->shift_t >= 11) ? (16 - tex_tile->shift_t) : 0;
    tex_tile->rshift_t  = (tex_tile->shift_t < 11) ? tex_tile->shift_t : 0;
    tex_tile->wrapped_mask_s = (tex_tile->mask_s > 10 ? 10 : tex_tile->mask_s);
    tex_tile->wrapped_mask_t = (tex_tile->mask_t > 10 ? 10 : tex_tile->mask_t);
    tex_tile->wrapped_mask = rgbaint_make(tex_tile->wrapped_mask_s, tex_tile->wrapped_mask_s, tex_tile->wrapped_mask_t, tex_tile->wrapped_mask_t);
    tex_tile->clamp_s = tex_tile->cs || !tex_tile->mask_s;
    tex_tile->clamp_t = tex_tile->ct || !tex_tile->mask_t;
    tex_tile->mm = rgbaint_make(tex_tile->ms ? ~0 : 0, tex_tile->ms ? ~0 : 0, tex_tile->mt ? ~0 : 0, tex_tile->mt ? ~0 : 0);
    tex_tile->invmm = rgbaint_make(tex_tile->ms ? 0 : ~0, tex_tile->ms ? 0 : ~0, tex_tile->mt ? 0 : ~0, tex_tile->mt ? 0 : ~0);
    tex_tile->mask = rgbaint_make(tex_tile->mask_s ? ~0 : 0, tex_tile->mask_s ? ~0 : 0, tex_tile->mask_t ? ~0 : 0, tex_tile->mask_t ? ~0 : 0);
    tex_tile->invmask = rgbaint_make(tex_tile->mask_s ? 0 : ~0, tex_tile->mask_s ? 0 : ~0, tex_tile->mask_t ? 0 : ~0, tex_tile->mask_t ? 0 : ~0);
    tex_tile->lshift = rgbaint_make(tex_tile->lshift_s, tex_tile->lshift_s, tex_tile->lshift_t, tex_tile->lshift_t);
    tex_tile->rshift = rgbaint_make(tex_tile->rshift_s, tex_tile->rshift_s, tex_tile->rshift_t, tex_tile->rshift_t);
    tex_tile->clamp_st = rgbaint_make(tex_tile->clamp_s ? ~0 : 0, tex_tile->clamp_s ? ~0 : 0, tex_tile->clamp_t ? ~0 : 0, tex_tile->clamp_t ? ~0 : 0);

    if (tex_tile->format == FORMAT_I && tex_tile->size > PIXEL_SIZE_8BIT)
    {
        tex_tile->format = FORMAT_RGBA; // Used by Supercross 2000 (in-game)
    }
    if (tex_tile->format == FORMAT_CI && tex_tile->size > PIXEL_SIZE_8BIT)
    {
        tex_tile->format = FORMAT_RGBA; // Used by Clay Fighter - Sculptor's Cut
    }

    if (tex_tile->format == FORMAT_RGBA && tex_tile->size < PIXEL_SIZE_16BIT)
    {
        tex_tile->format = FORMAT_CI; // Used by Exterem-G2, Madden Football 64, and Rat Attack
    }
}
static void rdp_cmd_fill_rect(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    const uint64_t xh = (w1 >> 12) & 0xfff;
    const uint64_t xl = (w1 >> 44) & 0xfff;
    const uint64_t yh = (w1 >>  0) & 0xfff;
    uint64_t yl       = (w1 >> 32) & 0xfff;

    if (rdp->m_other_modes.cycle_type == CYCLE_TYPE_FILL || rdp->m_other_modes.cycle_type == CYCLE_TYPE_COPY)
    {
        yl |= 3;
    }

    const uint64_t xlint = (xl >> 2) & 0x3ff;
    const uint64_t xhint = (xh >> 2) & 0x3ff;

    uint64_t* ewdata = rdp->m_temp_rect_data;
    ewdata[0] = ((uint64_t)0x3680 << 48) | (yl << 32) | (yl << 16) | yh; // command, flipped, tile, yl, ym, yh
    ewdata[1] = (xlint << 48) | ((xl & 3) << 46); // xl, xl frac, dxldy (0), dxldy frac (0)
    ewdata[2] = (xhint << 48) | ((xh & 3) << 46); // xh, xh frac, dxhdy (0), dxhdy frac (0)
    ewdata[3] = (xlint << 48) | ((xl & 3) << 46); // xm, xm frac, dxmdy (0), dxmdy frac (0)
    memset(&ewdata[4], 0, 18 * sizeof(uint64_t));//shade, texture, depth

    rdp_draw_triangle(rdp, cmd_buf, false, false, false, true);
}
static void rdp_cmd_set_fog_color(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rgbaint_set_rgba(&rdp->m_fog_color, (uint8_t)(w1), (uint8_t)(w1 >> 24), (uint8_t)(w1 >> 16), (uint8_t)(w1 >> 8));
}
static void rdp_cmd_set_blend_color(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rgbaint_set_rgba(&rdp->m_blend_color, (uint8_t)(w1), (uint8_t)(w1 >> 24), (uint8_t)(w1 >> 16), (uint8_t)(w1 >> 8));
}
static void rdp_cmd_set_prim_color(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_misc_state.m_min_level = (uint32_t)(w1 >> 40) & 0x1f;
    const uint8_t prim_lod_fraction = (w1 >> 32);
    rgbaint_set_rgba(&rdp->m_prim_lod_fraction, prim_lod_fraction, prim_lod_fraction, prim_lod_fraction, prim_lod_fraction);

    const uint8_t alpha = (w1);
    rgbaint_set_rgba(&rdp->m_prim_color, alpha, (uint8_t)(w1 >> 24), (uint8_t)(w1 >> 16), (uint8_t)(w1 >> 8));
    rgbaint_set_rgba(&rdp->m_prim_alpha, alpha, alpha, alpha, alpha);
}
static void rdp_cmd_set_env_color(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    const uint8_t alpha = (w1);
    rgbaint_set_rgba(&rdp->m_env_color, alpha, (uint8_t)(w1 >> 24), (uint8_t)(w1 >> 16), (uint8_t)(w1 >> 8));
    rgbaint_set_rgba(&rdp->m_env_alpha, alpha, alpha, alpha, alpha);
}
static void rdp_cmd_set_combine(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_combine.sub_a_rgb0    = (uint32_t)(w1 >> 52) & 0xf;
    rdp->m_combine.mul_rgb0      = (uint32_t)(w1 >> 47) & 0x1f;
    rdp->m_combine.sub_a_a0      = (uint32_t)(w1 >> 44) & 0x7;
    rdp->m_combine.mul_a0        = (uint32_t)(w1 >> 41) & 0x7;
    rdp->m_combine.sub_a_rgb1    = (uint32_t)(w1 >> 37) & 0xf;
    rdp->m_combine.mul_rgb1      = (uint32_t)(w1 >> 32) & 0x1f;

    rdp->m_combine.sub_b_rgb0    = (uint32_t)(w1 >> 28) & 0xf;
    rdp->m_combine.sub_b_rgb1    = (uint32_t)(w1 >> 24) & 0xf;
    rdp->m_combine.sub_a_a1      = (uint32_t)(w1 >> 21) & 0x7;
    rdp->m_combine.mul_a1        = (uint32_t)(w1 >> 18) & 0x7;
    rdp->m_combine.add_rgb0      = (uint32_t)(w1 >> 15) & 0x7;
    rdp->m_combine.sub_b_a0      = (uint32_t)(w1 >> 12) & 0x7;
    rdp->m_combine.add_a0        = (uint32_t)(w1 >>  9) & 0x7;
    rdp->m_combine.add_rgb1      = (uint32_t)(w1 >>  6) & 0x7;
    rdp->m_combine.sub_b_a1      = (uint32_t)(w1 >>  3) & 0x7;
    rdp->m_combine.add_a1        = (uint32_t)(w1 >>  0) & 0x7;

}
static void rdp_cmd_set_texture_image(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_misc_state.m_ti_format  = (uint32_t)(w1 >> 53) & 0x7;
    rdp->m_misc_state.m_ti_size    = (uint32_t)(w1 >> 51) & 0x3;
    rdp->m_misc_state.m_ti_width   = ((uint32_t)(w1 >> 32) & 0x3ff) + 1;
    rdp->m_misc_state.m_ti_address = (uint32_t)(w1) & 0x01ffffff;
}
static void rdp_cmd_set_mask_image(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_misc_state.m_zb_address = (uint32_t)(w1) & 0x01ffffff;
}
static void rdp_cmd_set_color_image(rdp_t *rdp, uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    rdp->m_misc_state.m_fb_format  = (uint32_t)(w1 >> 53) & 0x7;
    rdp->m_misc_state.m_fb_size    = (uint32_t)(w1 >> 51) & 0x3;
    rdp->m_misc_state.m_fb_width   = ((uint32_t)(w1 >> 32) & 0x3ff) + 1;
    rdp->m_misc_state.m_fb_address = (uint32_t)(w1) & 0x01ffffff;
}

/*****************************************************************************/
static void rdp_cmd_noop(rdp_t *rdp, uint64_t *cmd_buf)
{
    (void)rdp;
    (void)cmd_buf;
    // Do nothing
}

static void rdp_dispatch_one(rdp_t *rdp, uint64_t *curr_cmd_buf,
    uint8_t cmd);

/* ---- Timed DPC engine entry points -------------------------------------
 *
 * The host's DPC front end (ares rdp/timed.cpp) fetches command words as
 * emulated time passes and dispatches them one at a time, timing each
 * from the work it reports. The host owns DPC_CURRENT and DPC_STATUS;
 * nothing here touches them. Words wait in the accumulator
 * (m_cmd_data/m_cmd_ptr/m_cmd_cur), whose live part is the host's command
 * FIFO. */

/* Words still required before the next buffered command is complete.
 * 0 means a command is ready to step; when the buffer is empty, 1 word
 * (the opcode word) is needed first. */
unsigned rdp_engine_need(rdp_t *rdp)
{
    const unsigned buffered = rdp->m_cmd_ptr - rdp->m_cmd_cur;
    unsigned cmd_words;
    uint8_t cmd;

    if (buffered == 0)
        return 1;

    cmd = (rdp->m_cmd_data[rdp->m_cmd_cur] >> 56) & 0x3f;
    cmd_words = s_rdp_command_length[cmd] >> 3;

    return (buffered >= cmd_words) ? 0 : (cmd_words - buffered);
}

int rdp_crashed(rdp_t *rdp)
{
    return rdp->m_pipeline_crashed;
}

/* Appends nwords 64-bit command words the host's command DMA delivered
 * (an RI grant, or the X bus from DMEM). Compacts the accumulator exactly
 * as the legacy walk does when nearing capacity. */
void rdp_engine_feed(rdp_t *rdp, const uint64_t *words, unsigned nwords)
{
    unsigned i;

    if (rdp->m_cmd_ptr + nwords > CMD_DATA_WORDS) {
        const unsigned pending = rdp->m_cmd_ptr - rdp->m_cmd_cur;
        memmove(&rdp->m_cmd_data[0], &rdp->m_cmd_data[rdp->m_cmd_cur],
            pending * sizeof(uint64_t));
        rdp->m_cmd_cur = 0;
        rdp->m_cmd_ptr = pending;
    }

    for (i = 0; i < nwords; i++)
        rdp->m_cmd_data[rdp->m_cmd_ptr++] = words[i];
}

/* Bytes a TMEM load moves (texel count by the texture image size; 4bpp
 * packs two texels per byte, TLUT entries are 16-bit); 0 for any other
 * command. */
static uint32_t rdp_engine_load_bytes(rdp_t *rdp, uint8_t cmd,
    const uint64_t *cmd_buf)
{
    const uint64_t w1 = cmd_buf[0];
    const int32_t sl = (int32_t)((w1 >> 44) & 0xfff);
    const int32_t tl = (int32_t)((w1 >> 32) & 0xfff);
    const int32_t sh = (int32_t)((w1 >> 12) & 0xfff);
    const int32_t th = (int32_t)((w1 >>  0) & 0xfff);
    int64_t texels;

    if (cmd != 0x30 && cmd != 0x33 && cmd != 0x34)
        return 0;

    if (cmd == 0x33)    /* Load Block: th is dxt, one texel run */
        texels = (int64_t)(sh - sl) + 1;
    else
        texels = ((int64_t)((sh >> 2) - (sl >> 2)) + 1) *
                 ((int64_t)((th >> 2) - (tl >> 2)) + 1);

    if (texels < 0)
        texels = 0;

    return (uint32_t)((cmd == 0x30)
        ? (uint64_t)texels * 2
        : ((uint64_t)texels << rdp->m_misc_state.m_ti_size) >> 1);
}

/* Executes one complete buffered command. Returns 1 and fills *work on
 * dispatch; returns 0 if no complete command is buffered; returns -1
 * if the pipeline is crashed (buffered words are discarded). */
int rdp_engine_step(rdp_t *rdp, rdp_engine_work *work)
{
    uint64_t *curr_cmd_buf;
    unsigned cmd_words;
    uint8_t cmd;

    if (rdp->m_pipeline_crashed) {
        rdp->m_cmd_ptr = 0;
        rdp->m_cmd_cur = 0;
        rdp_fill_haz_publish(rdp);
        return -1;
    }

    if (rdp_engine_need(rdp) != 0)
        return 0;

    curr_cmd_buf = &rdp->m_cmd_data[rdp->m_cmd_cur];
    cmd = (curr_cmd_buf[0] >> 56) & 0x3f;
    cmd_words = s_rdp_command_length[cmd] >> 3;

    memset(&rdp->m_work, 0, sizeof(rdp->m_work));
    rdp->m_work.word = curr_cmd_buf[0];
    rdp->m_work.command = cmd;
    rdp->m_work.cycle_type = rdp->m_other_modes.cycle_type;
    rdp_dispatch_one(rdp, curr_cmd_buf, cmd);
    rdp->m_work.load_bytes = rdp_engine_load_bytes(rdp, cmd, curr_cmd_buf);
    rdp->m_cmd_cur += cmd_words;

    if (rdp->m_cmd_cur == rdp->m_cmd_ptr || rdp->m_pipeline_crashed) {
        rdp->m_cmd_ptr = 0;
        rdp->m_cmd_cur = 0;
        /* Nothing buffered: the pixel pipeline drains, so the window closes
         * here as it does at the end of a list. */
        rdp_fill_haz_publish(rdp);
    }

    *work = rdp->m_work;

    return 1;
}

/* Whether a held hazard primitive's window is still open for the next
 * buffered command: a 1-/2-cycle hold collects the writes rdp_haz_collects
 * names, a FILL hold the commands rdp_fill_haz_cost does not fence on. False when
 * nothing is held or the next command is not buffered whole. */
int rdp_engine_hold_open(rdp_t *rdp)
{
    uint8_t cmd;

    if (rdp_engine_need(rdp) != 0)
        return 0;

    cmd = (rdp->m_cmd_data[rdp->m_cmd_cur] >> 56) & 0x3f;
    if (rdp->m_haz.active)
        return rdp_haz_collects(cmd);
    if (rdp->m_fill_haz.active)
        return rdp_fill_haz_cost(cmd) >= 0;
    return 0;
}

/* Publishes any held hazard primitive into the span queue. Its spans then
 * wait for the host like any other (plan T13). */
void rdp_engine_publish(rdp_t *rdp)
{
    rdp_haz_publish(rdp);
    rdp_fill_haz_publish(rdp);
}

/* Whether the next buffered command would run queued spans to completion
 * inside its handler (loads, Sync Full, Set Convert after a primitive, a
 * primitive under span-aux pool pressure). The host dispatches such a
 * command only once it has run every queued span itself. */
int rdp_engine_drains(rdp_t *rdp)
{
    uint8_t cmd;

    if (rdp_engine_need(rdp) != 0)
        return 0;
    cmd = (rdp->m_cmd_data[rdp->m_cmd_cur] >> 56) & 0x3f;
    switch (cmd)
    {
    case 0x29: case 0x30: case 0x33: case 0x34:
        return 1;
    case 0x2c:
        return !rdp->m_pipe_clean;
    case 0x08: case 0x09: case 0x0a: case 0x0b: case 0x0c: case 0x0d: case 0x0e: case 0x0f:
    case 0x24: case 0x25: case 0x36:
        return rdp->m_aux_buf_ptr + 4096u * sizeof(rdp_span_aux) > EXTENT_AUX_COUNT;
    }
    return 0;
}

int rdp_engine_next(rdp_t *rdp)
{
    if (rdp_engine_need(rdp) != 0)
        return -1;
    return (int)((rdp->m_cmd_data[rdp->m_cmd_cur] >> 56) & 0x3f);
}

void rdp_mem_record(rdp_t *rdp, uint32_t a, uint32_t n)
{
    rdp_memrange *r;
    if (a > MEM8_LIMIT)
        return;
    if (rdp->m_nrec > 0)
    {
        r = &rdp->m_rec[rdp->m_nrec - 1];
        if (a + n + 8u >= r->lo && a <= r->hi + 8u)
        {
            if (a < r->lo) r->lo = a;
            if (a + n > r->hi) r->hi = a + n;
            return;
        }
        if (rdp->m_nrec == RDP_MEMREC_MAX)
        {
            if (a < r->lo) r->lo = a;
            if (a + n > r->hi) r->hi = a + n;
            return;
        }
    }
    r = &rdp->m_rec[rdp->m_nrec++];
    r->lo = a;
    r->hi = a + n;
}

/* The RDRAM byte ranges the next buffered command (a TMEM load) reads, in
 * read order, octbyte-aligned and merged where they touch. Runs the load
 * against a scratch TMEM with reads recorded instead of performed, then
 * restores the tile registers it set; nothing else in a load handler
 * depends on the texel values. */
unsigned rdp_engine_load_plan(rdp_t *rdp, rdp_memrange *out, unsigned max)
{
    static uint8_t scratch[0x1000];
    rdp_tile_t tiles[8];
    uint8_t *tmem = rdp->m_tmem;
    uint64_t *cmd_buf;
    unsigned i, n = 0;
    uint8_t cmd;

    if (rdp_engine_need(rdp) != 0)
        return 0;
    cmd_buf = &rdp->m_cmd_data[rdp->m_cmd_cur];
    cmd = (cmd_buf[0] >> 56) & 0x3f;
    if (cmd != 0x30 && cmd != 0x33 && cmd != 0x34)
        return 0;

    memcpy(tiles, rdp->m_tiles, sizeof(tiles));
    memcpy(scratch, tmem, sizeof(scratch));
    rdp->m_tmem = scratch;
    rdp->m_rec = out;
    rdp->m_nrec = 0;
    rdp->m_mem_record = 1;
    if (cmd == 0x30) rdp_cmd_load_tlut(rdp, cmd_buf);
    if (cmd == 0x33) rdp_cmd_load_block(rdp, cmd_buf);
    if (cmd == 0x34) rdp_cmd_load_tile(rdp, cmd_buf);
    rdp->m_mem_record = 0;
    rdp->m_tmem = tmem;
    memcpy(rdp->m_tiles, tiles, sizeof(tiles));
    if (rdp->m_nrec > max)
        rdp->m_nrec = max;

    for (i = 0; i < rdp->m_nrec; i++)
    {
        uint32_t lo = out[i].lo & ~7u, hi = (out[i].hi + 7u) & ~7u;
        if (hi > MEM8_LIMIT + 1u) hi = MEM8_LIMIT + 1u;
        if (n > 0 && lo <= out[n - 1].hi && hi >= out[n - 1].lo)
        {
            if (lo < out[n - 1].lo) out[n - 1].lo = lo;
            if (hi > out[n - 1].hi) out[n - 1].hi = hi;
            continue;
        }
        out[n].lo = lo;
        out[n].hi = hi;
        n++;
    }
    rdp->m_rec = NULL;
    rdp->m_nrec = 0;
    return n;
}

/* Executes exactly one complete command already sitting in curr_cmd_buf,
 * with the pre/post hazard hooks (rdp_engine_step). */
static void rdp_dispatch_one(rdp_t *rdp, uint64_t *curr_cmd_buf, uint8_t cmd)
{
    rdp_haz_pre(rdp, (int32_t)cmd);

    // execute the command
    switch(cmd)
    {
            case 0x00:  rdp_cmd_noop(rdp, curr_cmd_buf);           break;

            case 0x08:  rdp_triangle(rdp, curr_cmd_buf, false, false, false); break;
            case 0x09:  rdp_triangle(rdp, curr_cmd_buf, false, false,  true); break;
            case 0x0a:  rdp_triangle(rdp, curr_cmd_buf, false,  true, false); break;
            case 0x0b:  rdp_triangle(rdp, curr_cmd_buf, false,  true,  true); break;
            case 0x0c:  rdp_triangle(rdp, curr_cmd_buf,  true, false, false); break;
            case 0x0d:  rdp_triangle(rdp, curr_cmd_buf,  true, false,  true); break;
            case 0x0e:  rdp_triangle(rdp, curr_cmd_buf,  true,  true, false); break;
            case 0x0f:  rdp_triangle(rdp, curr_cmd_buf,  true,  true,  true); break;

            case 0x24:  rdp_cmd_tex_rect(rdp, curr_cmd_buf);       break;
            case 0x25:  rdp_cmd_tex_rect_flip(rdp, curr_cmd_buf);  break;

            case 0x26:  rdp_cmd_sync_load(rdp, curr_cmd_buf);      break;
            case 0x27:  rdp_cmd_sync_pipe(rdp, curr_cmd_buf);      break;
            case 0x28:  rdp_cmd_sync_tile(rdp, curr_cmd_buf);      break;
            case 0x29:  rdp_cmd_sync_full(rdp, curr_cmd_buf);      break;

            case 0x2a:  rdp_cmd_set_key_gb(rdp, curr_cmd_buf);     break;
            case 0x2b:  rdp_cmd_set_key_r(rdp, curr_cmd_buf);      break;

            case 0x2c:  rdp_cmd_set_convert(rdp, curr_cmd_buf);    break;
            case 0x3c:  rdp_cmd_set_combine(rdp, curr_cmd_buf);    break;
            case 0x2d:  rdp_cmd_set_scissor(rdp, curr_cmd_buf);    break;
            case 0x2e:  rdp_cmd_set_prim_depth(rdp, curr_cmd_buf); break;
            case 0x2f:  rdp_cmd_set_other_modes(rdp, curr_cmd_buf);break;

            case 0x30:  rdp_cmd_load_tlut(rdp, curr_cmd_buf);      break;
            case 0x33:  rdp_cmd_load_block(rdp, curr_cmd_buf);     break;
            case 0x34:  rdp_cmd_load_tile(rdp, curr_cmd_buf);      break;

            case 0x32:  rdp_cmd_set_tile_size(rdp, curr_cmd_buf);  break;
            case 0x35:  rdp_cmd_set_tile(rdp, curr_cmd_buf);       break;

            case 0x36:  rdp_cmd_fill_rect(rdp, curr_cmd_buf);      break;

            case 0x37:  rdp_cmd_set_fill_color32(rdp, curr_cmd_buf); break;
            case 0x38:  rdp_cmd_set_fog_color(rdp, curr_cmd_buf);  break;
            case 0x39:  rdp_cmd_set_blend_color(rdp, curr_cmd_buf);break;
            case 0x3a:  rdp_cmd_set_prim_color(rdp, curr_cmd_buf); break;
            case 0x3b:  rdp_cmd_set_env_color(rdp, curr_cmd_buf);  break;

            case 0x3d:  rdp_cmd_set_texture_image(rdp, curr_cmd_buf); break;
            case 0x3e:  rdp_cmd_set_mask_image(rdp, curr_cmd_buf);  break;
            case 0x3f:  rdp_cmd_set_color_image(rdp, curr_cmd_buf); break;
    }

    rdp_haz_post_all(rdp, (int32_t)cmd, curr_cmd_buf);
}

/*****************************************************************************/

int rdp_construct(rdp_t *rdp, uint32_t rdram_size)
{
    memset(rdp, 0, sizeof(*rdp));
    if (poly_manager_init(&rdp->m_pool, rdp))
        return 1;

    rdp->m_mem8_limit = rdram_size - 1u;
    rdp->m_pixels = 0;

    rdp->m_aux_buf_ptr = 0;
    rdp->m_aux_buf = NULL;
    rdp->m_pipe_clean = true;

    memset(&rdp->m_work, 0, sizeof(rdp->m_work));

    rdp->m_start = 0;
    rdp->m_end = 0;
    rdp->m_current = 0;
    rdp->m_status = 0x88;

    rgbaint_set_rgba(&rdp->m_one, 0xff, 0xff, 0xff, 0xff);
    rgbaint_set_rgba(&rdp->m_onecc, 0x100, 0x100, 0x100, 0x100);
    rgbaint_set_rgba(&rdp->m_zero, 0, 0, 0, 0);

    rdp->m_tmem = NULL;
    rdp->m_tmem_pool = NULL;
    rdp->m_tmem_cows = 0;

    rgbaint_set_rgba(&rdp->m_prim_lod_fraction, 0, 0, 0, 0);
    rdp_z_build_com_table(rdp);

    memset(rdp->m_temp_rect_data, 0, sizeof(uint32_t) * 0x1000);

    for (int32_t i = 0; i < 0x4000; i++)
    {
        unsigned exponent = (i >> 11) & 7;
        unsigned mantissa = i & 0x7ff;
        rdp->m_z_complete_dec_table[i] = ((mantissa << m_z_dec_table[exponent].shift) + m_z_dec_table[exponent].add) & 0x3fffff;
    }

    rdp_precalc_cvmask_derivatives(rdp);

    for(int32_t i = 0; i < 0x10000; i++)
    {
        rdp->m_dzpix_normalize[i] = (uint16_t)rdp_normalize_dzpix(i & 0xffff);
    }

    rdp->m_write_pixel[0] = rdp_write_pixel4;
    rdp->m_write_pixel[1] = rdp_write_pixel8;
    rdp->m_write_pixel[2] = rdp_write_pixel16;
    rdp->m_write_pixel[3] = rdp_write_pixel32;

    rdp->m_read_pixel[0] = rdp_read_pixel4;
    rdp->m_read_pixel[1] = rdp_read_pixel8;
    rdp->m_read_pixel[2] = rdp_read_pixel16;
    rdp->m_read_pixel[3] = rdp_read_pixel32;

    rdp->m_copy_pixel[0] = rdp_copy_pixel4;
    rdp->m_copy_pixel[1] = rdp_copy_pixel8;
    rdp->m_copy_pixel[2] = rdp_copy_pixel16;
    rdp->m_copy_pixel[3] = rdp_copy_pixel32;

    return 0;
}
/* The work a primitive asks of the pipeline: its clipped spans, their pixel
 * widths and, in fill and copy mode, the 64-bit words they cover (16/8/4/2
 * pixels per word at 4/8/16/32bpp). The pixel set mirrors the clipping
 * poly_manager_render_extents applies, so the count matches what is
 * actually enqueued. The host's timing model turns the work into clocks
 * (ares rdp/timed.hpp). */
static void rdp_occ_accumulate(rdp_t *rdp, const poly_rect *clip,
    int32_t startscan, int32_t numlines, const extent_t *spans, bool flip)
{
    const int32_t v1 = rdp_max32(startscan, clip->min_y);
    const int32_t v3 = rdp_min32(startscan + numlines, clip->max_y + 1);
    const int32_t cyc_type = rdp->m_other_modes.cycle_type;
    const int32_t px_per_qword = 16 >> (rdp->m_misc_state.m_fb_size & 3);
    int32_t scan;

    for (scan = v1; scan < v3; scan++) {
        const extent_t *e = &spans[scan - startscan];
        int32_t sx = e->startx, ex = e->stopx, w;

        /* Mirror the span callbacks' width semantics EXACTLY
         * (rdp_span_draw_*): both edges are clamped independently
         * (poly_manager_render_extents) and the drawn length is the
         * SIGNED, flip-directional difference of the clamped edges --
         * a negative length draws nothing. This is how the renderer
         * silently rejects the phantom slot past a primitive's last
         * real span, whatever it happens to contain; the previous
         * direction-blind swap here converted any wrong-orientation
         * slot into a full clip-width span, charging every span-walked
         * primitive one phantom span (+~334 cycles at 320-wide clip:
         * the exact per-primitive excess between the dpc_probe
         * emulator and hardware tables, RECTN 2357 vs 2021). By
         * mirroring the drawing rule, occ rejects precisely what the
         * renderer rejects, independent of slot contents. Explicit
         * sentinel skip retained as belt-and-braces (a flip-oriented
         * primitive followed by the (0xfff,0) sentinel would otherwise
         * pass the sign test). */
        if (e->startx == 0xfff && e->stopx == 0)
            continue;

        sx = rdp_max32(rdp_min32(sx, clip->max_x + 1), clip->min_x);
        ex = rdp_max32(rdp_min32(ex, clip->max_x + 1), clip->min_x);
        w = flip ? (sx - ex) : (ex - sx);
        if (w < 0)
            continue;

        rdp->m_pixels += (uint64_t)w;
        rdp->m_work.pixels += (uint32_t)w;
        if (cyc_type == CYCLE_TYPE_COPY || cyc_type == CYCLE_TYPE_FILL)
            rdp->m_work.words += ((uint32_t)w + px_per_qword - 1) / px_per_qword;
        rdp->m_work.lines += 1;
    }

}

static void rdp_render_spans(rdp_t *rdp, int32_t start, int32_t end, int32_t tilenum, bool flip, extent_t* spans, bool rect, rdp_poly_state* object)
{
    /* Hardware-bug crash classes at the primitive choke point.
     * n64brew RDP/Commands: "Rendering any primitive in FILL mode to a
     * 4-bit color image will crash the RDP"; "COPY mode is unavailable
     * when a 32-bit color image is configured". The three fill-mode
     * flag combinations follow ParaLLEl-RDP's hardware validation
     * (Fill + depth test / image read / per-pixel depth write --
     * primitive-sourced depth write is legal), mirrored by ares. A
     * crashed pipe stops responding: see the crashed-DPC status
     * contract in rdp/interface.c. */
    if (rdp->m_other_modes.cycle_type == CYCLE_TYPE_FILL)
    {
        const char *reason = NULL;
        if (rdp->m_misc_state.m_fb_size == 0)
            reason = "fill to 4bpp color image";
        else if (rdp->m_other_modes.z_compare_en)
            reason = "fill with depth test";
        else if (rdp->m_other_modes.image_read_en)
            reason = "fill with image read enable";
        else if (rdp->m_other_modes.z_update_en &&
                 !rdp->m_other_modes.z_source_sel)
            reason = "fill with per-pixel depth write";
        if (reason)
        {
            cen64_log(CEN64_LOG_WRN, "rdp: pipeline crash: %s\n", reason);
            rdp->m_pipeline_crashed = true;
            return;
        }
    }
    else if (rdp->m_other_modes.cycle_type == CYCLE_TYPE_COPY &&
             rdp->m_misc_state.m_fb_size == 3)
    {
        cen64_log(CEN64_LOG_WRN, "rdp: pipeline crash: copy to 32bpp color image\n");
        rdp->m_pipeline_crashed = true;
        return;
    }

    /* RH#001 plumbing: give every span its successor's start S/T/W so
     * the end-of-span pipelined TEXEL1 fetch can peek the next
     * scanline's first pixel (n64brew RDP Hazards RH#001; exact
     * conditions ported from ParaLLEl-RDP shading.h). Walk-thread
     * only, before queueing. */
    for (int32_t l = start; l <= end; l++) {
        extent_t *e = &spans[l - start];
        /* The peek must target the next scanline only when that line is
         * actually rasterized. A span that collapsed to the empty marker
         * (startx=0xfff, stopx=0) is ParaLLEl-RDP's invalid_line (span setup:
         * xleft>xright or fully clipped, which forces xleft=0xffff/xright=0
         * and valid_line=0); peeking its degenerate start anchor makes the
         * previous line's last pixel sample a stale, far-off texel. Gate the
         * peek (SPAN_NS.dpdx, which doubles as the validity flag) on the
         * successor being a valid, non-empty line. */
        if (l < end && spans[l - start + 1].stopx > spans[l - start + 1].startx) {
            const extent_t *n = &spans[l - start + 1];
            e->param[SPAN_NS].start = n->param[SPAN_S].start;
            e->param[SPAN_NT].start = n->param[SPAN_T].start;
            e->param[SPAN_NW].start = n->param[SPAN_W].start;
            e->param[SPAN_NS].dpdx = 1;
        } else {
            e->param[SPAN_NS].dpdx = 0;
        }
    }

    /* The scissor's sub-pixel precision in 1-/2-cycle is per-SUBLINE, not
     * per-row: a fractional top edge renders its boundary row with the
     * quarter lines above the edge invalidated (yh_eff/yl_eff in the edge
     * walker), so the row window here is the floor'd top row in every
     * mode. Copy/fill ignore the fractional bits entirely (n64brew
     * SET_SCISSOR). PRDP 10:9. */
    const int32_t clipy1 = rdp->m_scissor.m_yh;
    const int32_t clipy2 = rdp->m_scissor.m_yl_clip;
    const poly_rect clip = { rdp->m_scissor.m_xh, rdp->m_scissor.m_xl, rdp->m_scissor.m_yh, rdp->m_scissor.m_yl };

    int32_t offset = 0;

    if (clipy2 <= 0)
    {
        return;
    }

    if (start < clipy1)
    {
        offset = clipy1 - start;
        start = clipy1;
    }
    if (start >= clipy2)
    {
        offset = start - (clipy2 - 1);
        start = clipy2 - 1;
    }
    if (end < clipy1)
    {
        end = clipy1;
    }
    /* The pixel pipeline's depth is set by the primitive's own row count, not
     * by how much of it survives the scissor: rows past the lower edge are
     * rejected without being rasterized, but the box the unsynced-attribute
     * hazard measures back from still ends where the command said it did.
     * Kept unscissored for that model alone (see rdp_haz_post); the render
     * range below stays clipped. */
    const int32_t end_box = end;
    if (end >= clipy2)
    {
        end = clipy2 - 1;
    }

    memcpy(&object->m_misc_state, &rdp->m_misc_state, sizeof(misc_state_t));
    memcpy(&object->m_other_modes, &rdp->m_other_modes, sizeof(other_modes_t));
    memcpy(&object->m_span_base, &rdp->m_span_base, sizeof(span_base_t));
    memcpy(&object->m_scissor, &rdp->m_scissor, sizeof(rectangle_t));
    memcpy(&object->m_tiles, &rdp->m_tiles, 8 * sizeof(rdp_tile_t));
    object->tilenum = tilenum;
    /* Producer-offload snapshot: source data for the worker-side span aux
     * initialization (rdp_span_aux_init). Captured here with the
     * other per-primitive snapshots, before any work is queued. */
    memcpy(&object->m_combine, &rdp->m_combine, sizeof(combine_modes_t));
    object->m_blend_color = rdp->m_blend_color;
    object->m_prim_color = rdp->m_prim_color;
    object->m_prim_alpha = rdp->m_prim_alpha;
    object->m_env_color = rdp->m_env_color;
    object->m_env_alpha = rdp->m_env_alpha;
    object->m_fog_color = rdp->m_fog_color;
    object->m_key_scale = rdp->m_key_scale;
    object->m_key_center = rdp->m_key_center;
    object->m_key_width = rdp->m_key_width;
    object->m_lod_fraction = rdp->m_lod_fraction;
    object->m_prim_lod_fraction = rdp->m_prim_lod_fraction;
    object->m_k4 = rdp->m_k4;
    object->m_k5 = rdp->m_k5;
    object->m_tmem_src = rdp->m_tmem;
    object->flip = flip;
    object->m_fill_color = rdp->m_fill_color;
    object->rect = rect;

    rdp_occ_accumulate(rdp, &clip, start, (end - start) + 1, spans + offset, flip);

    {
        const int32_t haz_cyc = (rdp->m_other_modes.cycle_type == CYCLE_TYPE_1) ? 1 :
                                (rdp->m_other_modes.cycle_type == CYCLE_TYPE_2) ? 2 : 0;
        if (rect && haz_cyc != 0)
        {
            const extent_t *e0 = &spans[offset];
            const int32_t a = e0->startx, b = e0->stopx;
            const int32_t nl = (end - start) + 1;
            int32_t slo = (a < b) ? a : b;
            int32_t shi = (a < b) ? b : a;
            int32_t sw;
            if (slo < clip.min_x)     slo = clip.min_x;
            if (shi > clip.max_x + 1) shi = clip.max_x + 1;
            sw = shi - slo + 1;
            /* sw / nl are the command box, inclusive: the dead final column
             * and row are inside them, so both must exceed one for the
             * primitive to commit anything at all. */
            if (sw > 1 && nl > 1)
            {
                const int32_t sp = rdp_max32(haz_cyc * sw + haz_cyc - 1, 4);
                const int32_t off =
                    (haz_cyc == 2 &&
                     !rdp_haz_env_in_cycle(&rdp->m_combine, 0) &&
                      rdp_haz_env_in_cycle(&rdp->m_combine, 1)) ? 1 : 0;

                rdp_haz_state *const h = &rdp->m_haz;
                h->active = 1;
                h->object = object;
                h->clip   = clip;
                h->start  = start;
                h->end    = end;
                h->offset = offset;
                h->lo     = slo;
                h->w      = sw;
                h->h      = (end_box - start) + 1;
                h->n      = sw * h->h;
                h->cyc    = haz_cyc;
                h->clock  = 0;
                h->nseg   = 0;
                h->span   = sp;
                h->lead_max = 0;
                for (int32_t st = 0; st < HAZ_STAGES; st++)
                {
                    const int32_t c = haz_cyc - 1;
                    const int32_t depth = rdp->m_pipeline_depth +
                        rdp_haz_stage_offset[st][c] - rdp_haz_stage_offset[HAZ_COMBINE][c];
                    h->lead[st] = rdp_min32(3 * sp - 2, depth) + (st == HAZ_ENV ? off : 0);
                    if (h->lead[st] > h->lead_max)
                        h->lead_max = h->lead[st];
                }
                return;
            }
        }
    }

    switch(rdp->m_other_modes.cycle_type)
    {
        case CYCLE_TYPE_1:
            poly_manager_render_extents(&rdp->m_pool, &clip, rdp_span_draw_1cycle, start, (end - start) + 1, spans + offset);
            break;

        case CYCLE_TYPE_2:
            poly_manager_render_extents(&rdp->m_pool, &clip, rdp_span_draw_2cycle, start, (end - start) + 1, spans + offset);
            break;

        case CYCLE_TYPE_COPY:
            poly_manager_render_extents(&rdp->m_pool, &clip, rdp_span_draw_copy, start, (end - start) + 1, spans + offset);
            break;

        case CYCLE_TYPE_FILL:
            if (rect)
            {
                /* Held unqueued while the unsynced Set Fill Color window is
                 * open (see rdp_fill_haz_rows). The model keys on the row's
                 * byte extent, so the bounds are the ones rdp_span_draw_fill
                 * writes: same flip selection, same scissor clamp, inclusive
                 * right edge. */
                const extent_t *e0 = &spans[offset];
                int32_t slo = flip ? e0->stopx : e0->startx;
                int32_t shi = flip ? e0->startx : e0->stopx;
                rdp_fill_haz_state *const f = &rdp->m_fill_haz;

                if (slo < object->m_scissor.m_xh)
                    slo = object->m_scissor.m_xh;
                if (shi > object->m_scissor.m_xl)
                    shi = object->m_scissor.m_xl;

                if (shi >= slo)
                {
                    f->active = 1;
                    f->object = object;
                    f->clip   = clip;
                    f->start  = start;
                    f->end    = end;
                    f->offset = offset;
                    f->h      = (end - start) + 1;
                    f->x0     = slo;
                    f->x1     = shi;
                    f->fbsize = (int32_t)object->m_misc_state.m_fb_size;
                    f->clock  = 0;
                    f->nseg   = 0;
                    return;
                }
            }
            poly_manager_render_extents(&rdp->m_pool, &clip, rdp_span_draw_fill, start, (end - start) + 1, spans + offset);
            break;
    }
    /* Queued; drained lazily at the next hazard (rdp_pipeline_drain). */
}
static void rdp_rgbaz_clip(rdp_t *rdp, int32_t sr, int32_t sg, int32_t sb, int32_t sa, int32_t* sz, rdp_span_aux* userdata)
{
    (void)rdp;
    rgbaint_set_rgba(&userdata->m_shade_color, sa, sr, sg, sb);
    rgbaint_clamp9(&userdata->m_shade_color);
    unsigned a = rgbaint_get_a(&userdata->m_shade_color);
    rgbaint_set_rgba(&userdata->m_shade_alpha, a, a, a, a);

    /* Bits 18:17 of the corrected Z select the clip action: 00/01 in
     * range, 10 positive overflow clamping to the far plane, 11 the sign
     * window -- negative Z clamps to zero (near), not far, so a pixel
     * just below zero stores z16 0x0000 (PRDP 7:1/7:2). */
    int32_t zanded = (*sz) & 0x60000;

    zanded >>= 17;
    switch(zanded)
    {
        case 0: *sz &= 0x3ffff;                                         break;
        case 1: *sz &= 0x3ffff;                                         break;
        case 2: *sz = 0x3ffff;                                          break;
        case 3: *sz = 0;                                                break;
    }
}
static void rdp_rgbaz_correct_triangle(rdp_t *rdp, int32_t offx, int32_t offy, int32_t* r, int32_t* g, int32_t* b, int32_t* a, int32_t* z, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    (void)rdp;
    if (userdata->m_current_pix_cvg == 8)
    {
        *r >>= 2;
        *g >>= 2;
        *b >>= 2;
        *a >>= 2;
        *z = (*z >> 3) & 0x7ffff;
    }
    else
    {
        int32_t summand_xr = rdp_smul(offx, SIGN16(object->m_span_base.m_span_dr >> 14));
        int32_t summand_yr = rdp_smul(offy, SIGN16(object->m_span_base.m_span_drdy >> 14));
        int32_t summand_xb = rdp_smul(offx, SIGN16(object->m_span_base.m_span_db >> 14));
        int32_t summand_yb = rdp_smul(offy, SIGN16(object->m_span_base.m_span_dbdy >> 14));
        int32_t summand_xg = rdp_smul(offx, SIGN16(object->m_span_base.m_span_dg >> 14));
        int32_t summand_yg = rdp_smul(offy, SIGN16(object->m_span_base.m_span_dgdy >> 14));
        int32_t summand_xa = rdp_smul(offx, SIGN16(object->m_span_base.m_span_da >> 14));
        int32_t summand_ya = rdp_smul(offy, SIGN16(object->m_span_base.m_span_dady >> 14));

        int32_t summand_xz = rdp_smul(offx, SIGN22(object->m_span_base.m_span_dz >> 10));
        int32_t summand_yz = rdp_smul(offy, SIGN22(object->m_span_base.m_span_dzdy >> 10));

        *r = rdp_pix_correct(*r, summand_xr, summand_yr) >> 4;
        *g = rdp_pix_correct(*g, summand_xg, summand_yg) >> 4;
        *b = rdp_pix_correct(*b, summand_xb, summand_yb) >> 4;
        *a = rdp_pix_correct(*a, summand_xa, summand_ya) >> 4;
        *z = (rdp_pix_correct(*z, summand_xz, summand_yz) >> 5) & 0x7ffff;
    }
}
static void rdp_write_pixel4(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    (void)color;
    (void)userdata;
    /* 4-bit color image: "4-bit modes only write 0s as bytes" (n64brew RDP
     * Commands, Set Color Image). The address generator does NOT pack two
     * pixels per byte -- it steps ONE BYTE PER PIXEL, identically to an
     * 8-bit color image, and the store data is fixed at zero. Confirmed by
     * the ParaLLEl-RDP reference, where FB_FMT_I4 and FB_FMT_I8 share the
     * unshifted byte base (rdp_renderer.cpp: addr_index = fb.addr for both,
     * >>1 only from RGBA5551 up) and store_vram_color's I4 case writes
     * mem_u8(0) at that byte.
     *
     * The hidden bits are left alone. ParaLLEl's I4 store does write the
     * hidden pair on an odd byte index, but with current_color.a, and its
     * write_color() deliberately withholds alpha for I4 alone
     * (`if (FB_FMT == FB_FMT_I4) current_color.rgb = col.rgb;`), so alpha
     * still holds what load_vram_color read out of the hidden RAM: the
     * store is a read-modify-write that puts back what was there. Skipping
     * it entirely is the same net effect and does not fabricate a read. */
    RWRITEADDR8(object->m_misc_state.m_fb_address + curpixel, 0);
}
static void rdp_write_pixel8(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    (void)userdata;
    /* 8-bit color image: the pixel index is a byte address. The RDP's
     * internal 16-bit memory word carries two color bytes -- R on the
     * even byte, G on the odd byte -- and each 16-bit word owns one
     * hidden 9th-bit pair, written together with the odd byte from
     * that byte's low bit. Writes are unconditional -- skipping
     * zero-valued bytes has no hardware basis. Semantics per the
     * n64brew RDP Commands color-image-format notes and the
     * ParaLLEl-RDP reference (memory_interfacing.h store_vram_color,
     * FB_FMT_I8 case). This is what OoT's pause PreRender
     * coverage-to-I8 pass exercises: without the odd-byte hidden
     * write, the extracted coverage image keeps stale full coverage
     * and the VI stops AA-filtering the paused frame. */
    const uint32_t index = object->m_misc_state.m_fb_address + curpixel;
    const unsigned c = (index & 1) ? (rgbaint_get_g(color) & 0xff)
                                   : (rgbaint_get_r(color) & 0xff);

    RWRITEADDR8(index, c);
    if (index & 1)
        HWRITEADDR8(index >> 1, (c & 1) * 3);
}
static void rdp_write_pixel16(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    const unsigned fb = (object->m_misc_state.m_fb_address >> 1) + curpixel;

    /* color_on_cvg substitution happens at the blender output (pre-dither)
     * in rdp_blend.c; by the time the color reaches here it is final. */
    unsigned finalcvg;
    switch (object->m_other_modes.cvg_dest)
    {
        default:
        case 0:
            if (userdata->m_blend_enable)
            {
                finalcvg = userdata->m_current_pix_cvg + userdata->m_current_mem_cvg;
                /* Branchless: if the sum overflowed 3 bits (>=8), clamp to 7. */
                finalcvg ^= (finalcvg ^ 7u) & (uint32_t)(-(int32_t)((finalcvg >> 3) & 1));
            }
            else
                finalcvg = (userdata->m_current_pix_cvg - 1) & 7;
            break;
        case 1:
            finalcvg = (userdata->m_current_pix_cvg + userdata->m_current_mem_cvg) & 7;
            break;
        case 2:
            finalcvg = 7;
            break;
        case 3:
            finalcvg = userdata->m_current_mem_cvg;
            break;
    }

    if (object->m_misc_state.m_fb_format == 3)
    {
        /* IA color image at 16 bits: high byte is the full 8-bit blended
         * red channel, low byte is alpha = coverage << 5, so the hidden
         * pair (alpha bit 0 replicated) lands as zero. ParaLLEl
         * memory_interfacing.h store_vram_color, FB_FMT_IA88. */
        RWRITEIDX16(fb, ((rgbaint_get_r(color) & 0xff) << 8) | (finalcvg << 5));
        HWRITEADDR8(fb, 0);
        return;
    }

    rgbaint_shr_imm(color, 3);
    const uint16_t finalcolor = (rgbaint_get_r(color) << 11) | (rgbaint_get_g(color) << 6) | (rgbaint_get_b(color) << 1);
    RWRITEIDX16(fb, finalcolor | (finalcvg >> 2));
    HWRITEADDR8(fb, finalcvg & 3);
}
static void rdp_write_pixel32(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    const unsigned fb = (object->m_misc_state.m_fb_address >> 2) + curpixel;

    /* color_on_cvg substitution happens at the blender output (pre-dither)
     * in rdp_blend.c; by the time the color reaches here it is final. */
    const uint32_t finalcolor = (rgbaint_get_r(color) << 24) | (rgbaint_get_g(color) << 16) | (rgbaint_get_b(color) << 8);

    switch (object->m_other_modes.cvg_dest)
    {
        case 0:
            if (userdata->m_blend_enable)
            {
                unsigned finalcvg = userdata->m_current_pix_cvg + userdata->m_current_mem_cvg;
                if (finalcvg & 8)
                {
                    finalcvg = 7;
                }

                RWRITEIDX32(fb, finalcolor | (finalcvg << 5));
            }
            else
            {
                RWRITEIDX32(fb, finalcolor | (((userdata->m_current_pix_cvg - 1) & 7) << 5));
            }
            break;
        case 1:
            RWRITEIDX32(fb, finalcolor | (((userdata->m_current_pix_cvg + userdata->m_current_mem_cvg) & 7) << 5));
            break;
        case 2:
            RWRITEIDX32(fb, finalcolor | 0xE0);
            break;
        case 3:
            RWRITEIDX32(fb, finalcolor | (userdata->m_current_mem_cvg << 5));
            break;
    }
}
static void rdp_read_pixel4(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    (void)rdp;
    (void)curpixel;
    (void)object;
    /* 4-bit color image: memory color is zero and memory coverage is
     * always full (7), so the blender's memory-coverage input (memory-
     * color alpha) is the full-coverage encoding 0xe0 (= 7 << 5), same
     * as read_pixel8 and the 16-bit reader's image_read-disabled path.
     * Per the ParaLLEl-RDP reference (memory_interfacing.h
     * decode_memory_color, FB_FMT_I4: color = 0, memory_coverage = 0xe0)
     * and the n64brew RDP Pipeline "Image Read" notes. */
    rgbaint_set_rgba(&userdata->m_memory_color, 0xe0, 0, 0, 0);
    userdata->m_current_mem_cvg = 7;
}
static void rdp_read_pixel8(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    /* 8-bit color image: the memory color presented to the blender is
     * the raw framebuffer byte replicated across R/G/B (no RGBA5551
     * bit-splice reconstruction), and memory coverage is forced to
     * full (7; alpha 0xE0) regardless of image_read_en -- the hidden
     * pair under an I8 color image is only consumed when the buffer is
     * read back as a depth image, which is a separate path here.
     * Semantics per the ParaLLEl-RDP reference (memory_interfacing.h:
     * load_vram_color FB_FMT_I8 and decode_memory_color). */
    const unsigned fbyte = RREADADDR8(object->m_misc_state.m_fb_address + curpixel);
    rgbaint_set_rgba(&userdata->m_memory_color, 0xe0, fbyte, fbyte, fbyte);
    userdata->m_current_mem_cvg = 7;
}
static void rdp_read_pixel16(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    const unsigned fword = RREADIDX16((object->m_misc_state.m_fb_address >> 1) + curpixel);

    if (object->m_misc_state.m_fb_format == 3)
    {
        /* IA color image at 16 bits: high byte is an intensity replicated
         * across R/G/B, low byte is alpha whose top three bits carry the
         * memory coverage. The hidden pair is not consumed here. ParaLLEl
         * memory_interfacing.h load_vram_color, FB_FMT_IA88. */
        const unsigned ibyte = (fword >> 8) & 0xff;
        rgbaint_set_rgba(&userdata->m_memory_color, 0, ibyte, ibyte, ibyte);
        if (object->m_other_modes.image_read_en)
        {
            rgbaint_set_a(&userdata->m_memory_color, fword & 0xe0);
            userdata->m_current_mem_cvg = (fword >> 5) & 7;
        }
        else
        {
            rgbaint_set_a(&userdata->m_memory_color, 0xe0);
            userdata->m_current_mem_cvg = 7;
        }
        return;
    }

    rgbaint_set_rgba(&userdata->m_memory_color, 0, GETHICOL(fword), GETMEDCOL(fword), GETLOWCOL(fword));
    if (object->m_other_modes.image_read_en)
    {
        unsigned hbyte = HREADADDR8((object->m_misc_state.m_fb_address >> 1) + curpixel);
        userdata->m_current_mem_cvg = ((fword & 1) << 2) | (hbyte & 3);
        rgbaint_set_a(&userdata->m_memory_color, userdata->m_current_mem_cvg << 5);
    }
    else
    {
        /* No framebuffer read: full memory coverage is 7<<5 = 0xe0, not 0xff
         * (ParaLLEl memory_interfacing.h memory_coverage = 0xe0). */
        rgbaint_set_a(&userdata->m_memory_color, 0xe0);
        userdata->m_current_mem_cvg = 7;
    }
}
static void rdp_read_pixel32(rdp_t *rdp, uint32_t curpixel, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    const unsigned mem = RREADIDX32((object->m_misc_state.m_fb_address >> 2) + curpixel);
    rgbaint_set_rgba(&userdata->m_memory_color, 0, (mem >> 24) & 0xff, (mem >> 16) & 0xff, (mem >> 8) & 0xff);
    if (object->m_other_modes.image_read_en)
    {
        rgbaint_set_a(&userdata->m_memory_color, mem & 0xff);
        userdata->m_current_mem_cvg = (mem >> 5) & 7;
    }
    else
    {
        rgbaint_set_a(&userdata->m_memory_color, 0xff);
        userdata->m_current_mem_cvg = 7;
    }
}
static void rdp_copy_pixel4(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object)
{
    (void)color;
    /* 4-bit color image, copy pipe: same zero byte at the same one-byte-per-
     * pixel stride as write_pixel4, but the hidden pair IS clobbered here.
     * The copy pipe does not run its store through the alpha-withholding
     * path the 1-/2-cycle blender uses -- ParaLLEl-RDP's copy_pipeline sets
     * the whole quad to zero for FB_FMT_I4 (`current_color = uint8_tx4(0)`,
     * bypassing write_color), so the subsequent store writes zero into the
     * hidden bits on an odd byte index instead of restoring the loaded
     * value. That asymmetry between the two pipes is deliberate in the
     * reference, so it is reproduced rather than smoothed over. */
    const uint32_t index = object->m_misc_state.m_fb_address + curpixel;
    RWRITEADDR8(index, 0);
    if (index & 1)
        HWRITEADDR8(index >> 1, 0);
}
static void rdp_copy_pixel8(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object)
{
    const unsigned c = (rgbaint_get_r(color) & 0xf8) | ((rgbaint_get_g(color) & 0xf8) >> 5);
    if (c != 0)
        RWRITEADDR8(object->m_misc_state.m_fb_address + curpixel, c);
}
static void rdp_copy_pixel16(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object)
{
    const unsigned current_pix_cvg = rgbaint_get_a(color) ? 7 : 0;
    const unsigned r = rgbaint_get_r(color); /* unsigned: keeps r<<24 out of the sign bit */
    const unsigned g = rgbaint_get_g(color);
    const unsigned b = rgbaint_get_b(color);
    RWRITEIDX16((object->m_misc_state.m_fb_address >> 1) + curpixel, ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | ((current_pix_cvg >> 2) & 1));
    HWRITEADDR8((object->m_misc_state.m_fb_address >> 1) + curpixel, current_pix_cvg & 3);
}
static void rdp_copy_pixel32(rdp_t *rdp, uint32_t curpixel, rgbaint_t *color, const rdp_poly_state *object)
{
    const unsigned current_pix_cvg = rgbaint_get_a(color) ? 7 : 0;
    const unsigned r = rgbaint_get_r(color); /* unsigned: keeps r<<24 out of the sign bit */
    const unsigned g = rgbaint_get_g(color);
    const unsigned b = rgbaint_get_b(color);
    RWRITEIDX32((object->m_misc_state.m_fb_address >> 2) + curpixel, (r << 24) | (g << 16) | (b << 8) | (current_pix_cvg << 5));
}
/* Combiner equation up to the output shift; chroma-key alpha samples the
 * value here, so the shift/clamp tail is rdp_combiner_clamp. a/b/d expand
 * at 0x180 but the MULTIPLIER sign-extends at 9 bits (ParaLLEl
 * combiner.h), which is why ONE multiplies as -1.0. cyc is a literal at
 * every call site, so the mux loads stay where the caller put them. */
static inline rgbaint_t rdp_combiner_mix(const color_inputs_t *ci,
    unsigned cyc)
{
    rgbaint_t sub_a = rgbaint_load_merged(ci->combiner_rgbsub_a[cyc], ci->combiner_alphasub_a[cyc]);
    rgbaint_t sub_b = rgbaint_load_merged(ci->combiner_rgbsub_b[cyc], ci->combiner_alphasub_b[cyc]);
    rgbaint_t mul   = rgbaint_load_merged(ci->combiner_rgbmul[cyc],   ci->combiner_alphamul[cyc]);
    rgbaint_t add   = rgbaint_load_merged(ci->combiner_rgbadd[cyc],   ci->combiner_alphaadd[cyc]);

    rgbaint_sign_extend(&sub_a, 0x180, 0xfffffe00);
    rgbaint_sign_extend(&sub_b, 0x180, 0xfffffe00);
    rgbaint_sign_extend(&add,   0x180, 0xfffffe00);
    rgbaint_sign_extend(&mul,   0x100, 0xfffffe00);

    rgbaint_shl_imm(&add, 8);
    rgbaint_sub(&sub_a, &sub_b);
    rgbaint_mul(&sub_a, &mul);
    rgbaint_add(&sub_a, &add);
    rgbaint_add_imm(&sub_a, 0x0080);
    return sub_a;
}

/* Output stage. 9-bit WRAP clamp, not saturating (ParaLLEl
 * clamp_9bit_notrunc): saturating maps [0x180,0x1ff] to 0xff where
 * hardware wraps to 0, which under cvg_x_alpha decides whether the pixel
 * is written at all. */
static inline void rdp_combiner_clamp(rgbaint_t *v)
{
    rgbaint_sra_imm(v, 8);
    rgbaint_clamp_9bit(v);
}

/* First-cycle output stage of 2-cycle mode. No clamping occurs between
 * combiner cycles, so the second cycle receives the raw 9-bit result:
 * 0x100-0x17f expands to 256-383 in the A/B/D inputs, and the whole
 * 0x100-0x1ff range sign-extends negative in the MULTIPLIER input.
 * Clamping here would collapse those to 0xff/0x00 and erase both. */
static inline void rdp_combiner_cycle0(rgbaint_t *v)
{
    rgbaint_sra_imm(v, 8);
    rgbaint_and_imm(v, 0x1ff);
}

/* Keying: pixel color comes from the combiner's SUB_A input directly,
 * keeping only the combiner output's alpha. */
static inline void rdp_chroma_bypass(rgbaint_t *pixel, rgbaint_t sub_a)
{
    rgbaint_sign_extend(&sub_a, 0x180, 0xfffffe00);
    rgbaint_clamp_and_clear(&sub_a, 0xfffffe00);
    rgbaint_set_a(&sub_a, rgbaint_get_a(pixel));
    *pixel = sub_a;
}

/* Worker-side span aux initialization (producer offload): the per-span
 * setup -- combiner and blender input resolution, color constants, the
 * TMEM pointer -- sourced from the per-primitive snapshot in
 * rdp_poly_state. Each extent is processed exactly once, so this runs
 * once per span. The field set written here is exact: the aux pool is
 * never cleared, so fields outside this set must remain unwritten to
 * keep bit-exactness, and every field inside it must be written before
 * the span body reads it. The set_* input helpers
 * only store pointers to aux-internal fields or to the immutable rdp-level
 * constants (m_one/m_zero/m_onecc), so worker-side resolution is race-free and
 * deterministic. */
static void rdp_span_aux_init(rdp_t *rdp, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    memcpy(&userdata->m_combine, &object->m_combine, sizeof(combine_modes_t));
    userdata->m_tmem = object->m_tmem_src;

    userdata->m_blend_color = object->m_blend_color;
    userdata->m_prim_color = object->m_prim_color;
    userdata->m_env_color = object->m_env_color;
    userdata->m_fog_color = object->m_fog_color;
    userdata->m_prim_alpha = object->m_prim_alpha;
    userdata->m_env_alpha = object->m_env_alpha;
    userdata->m_key_scale = object->m_key_scale;
    userdata->m_key_center = object->m_key_center;
    userdata->m_key_width = object->m_key_width;
    userdata->m_lod_fraction = object->m_lod_fraction;
    userdata->m_prim_lod_fraction = object->m_prim_lod_fraction;
    userdata->m_k4 = object->m_k4;
    userdata->m_k5 = object->m_k5;

    rdp_set_blender_input(rdp, 0, 0, &userdata->m_color_inputs.blender1a_rgb[0], &userdata->m_color_inputs.blender1b_a[0], object->m_other_modes.blend_m1a_0, object->m_other_modes.blend_m1b_0, userdata);
    rdp_set_blender_input(rdp, 0, 1, &userdata->m_color_inputs.blender2a_rgb[0], &userdata->m_color_inputs.blender2b_a[0], object->m_other_modes.blend_m2a_0, object->m_other_modes.blend_m2b_0, userdata);
    rdp_set_blender_input(rdp, 1, 0, &userdata->m_color_inputs.blender1a_rgb[1], &userdata->m_color_inputs.blender1b_a[1], object->m_other_modes.blend_m1a_1, object->m_other_modes.blend_m1b_1, userdata);
    rdp_set_blender_input(rdp, 1, 1, &userdata->m_color_inputs.blender2a_rgb[1], &userdata->m_color_inputs.blender2b_a[1], object->m_other_modes.blend_m2a_1, object->m_other_modes.blend_m2b_1, userdata);

    rdp_set_suba_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbsub_a[0], object->m_combine.sub_a_rgb0, userdata);
    rdp_set_subb_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbsub_b[0], object->m_combine.sub_b_rgb0, userdata);
    rdp_set_mul_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbmul[0], object->m_combine.mul_rgb0, userdata);
    rdp_set_add_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbadd[0], object->m_combine.add_rgb0, userdata);
    rdp_set_sub_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphasub_a[0], object->m_combine.sub_a_a0, userdata);
    rdp_set_sub_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphasub_b[0], object->m_combine.sub_b_a0, userdata);
    rdp_set_mul_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphamul[0], object->m_combine.mul_a0, userdata);
    rdp_set_sub_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphaadd[0], object->m_combine.add_a0, userdata);

    rdp_set_suba_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbsub_a[1], object->m_combine.sub_a_rgb1, userdata);
    rdp_set_subb_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbsub_b[1], object->m_combine.sub_b_rgb1, userdata);
    rdp_set_mul_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbmul[1], object->m_combine.mul_rgb1, userdata);
    rdp_set_add_input_rgb(rdp, &userdata->m_color_inputs.combiner_rgbadd[1], object->m_combine.add_rgb1, userdata);
    rdp_set_sub_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphasub_a[1], object->m_combine.sub_a_a1, userdata);
    rdp_set_sub_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphasub_b[1], object->m_combine.sub_b_a1, userdata);
    rdp_set_mul_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphamul[1], object->m_combine.mul_a1, userdata);
    rdp_set_sub_input_alpha(rdp, &userdata->m_color_inputs.combiner_alphaadd[1], object->m_combine.add_a1, userdata);
}

/* Shared 1-/2-cycle span walk: the eight interpolated attributes, their
 * per-pixel increments and walk direction, and the Z source. A
 * non-escaping local in both kernels, so it decomposes back into the
 * registers the open-coded version used. */
typedef struct
{
    span_param_t r, g, b, a, z, s, t, w;
    int32_t drinc, dginc, dbinc, dainc;
    int32_t dsinc, dtinc, dwinc, dzinc;
    int32_t x, xinc, length, dzpix;
    int32_t xend_scissored;
    int32_t fb_index;
    unsigned zb, zhb;
} rdp_span_walk;

static inline void rdp_span_walk_init(rdp_span_walk *sw, int32_t scanline,
    const extent_t *extent, const rdp_poly_state *object,
    const rdp_span_aux *userdata)
{
    const span_base_t *const sb = &object->m_span_base;
    const bool flip = object->flip;

    sw->r.w = extent->param[SPAN_R].start;
    sw->g.w = extent->param[SPAN_G].start;
    sw->b.w = extent->param[SPAN_B].start;
    sw->a.w = extent->param[SPAN_A].start;
    sw->z.w = extent->param[SPAN_Z].start;
    sw->s.w = extent->param[SPAN_S].start;
    sw->t.w = extent->param[SPAN_T].start;
    sw->w.w = extent->param[SPAN_W].start;

    sw->zb  = object->m_misc_state.m_zb_address >> 1;
    /* ares port, plan T13: the dz bits are the Z halfword's own ninth bits,
     * halfword index (address >> 1) + pixel like the color plane; MAME's
     * byte-address base put them in another image's bits. */
    sw->zhb = object->m_misc_state.m_zb_address >> 1;
    sw->fb_index = object->m_misc_state.m_fb_width * scanline;

    /* Right-major spans walk screen-right to screen-left, so every
     * gradient runs backwards and x counts down. */
    if (!flip)
    {
        sw->drinc = rdp_sneg(sb->m_span_dr);
        sw->dginc = rdp_sneg(sb->m_span_dg);
        sw->dbinc = rdp_sneg(sb->m_span_db);
        sw->dainc = rdp_sneg(sb->m_span_da);
        sw->dzinc = rdp_sneg(sb->m_span_dz);
        sw->dsinc = rdp_sneg(sb->m_span_ds);
        sw->dtinc = rdp_sneg(sb->m_span_dt);
        sw->dwinc = rdp_sneg(sb->m_span_dw);
        sw->xinc = -1;
    }
    else
    {
        sw->drinc = sb->m_span_dr;
        sw->dginc = sb->m_span_dg;
        sw->dbinc = sb->m_span_db;
        sw->dainc = sb->m_span_da;
        sw->dzinc = sb->m_span_dz;
        sw->dsinc = sb->m_span_ds;
        sw->dtinc = sb->m_span_dt;
        sw->dwinc = sb->m_span_dw;
        sw->xinc = 1;
    }

    sw->xend_scissored = extent->stopx;
    sw->x = (int32_t)userdata->m_unscissored_rx;

    /* Step the attributes from the anchor to the scissored start, so the
     * texture pipeline is primed at the first pixel hardware processes;
     * priming at a far-away anchor is the F-Zero X garbage column. SIGNED:
     * a mid-walk wrap can leave the anchor on either side of the span, and
     * hardware shades positionally from it regardless. */
    const int32_t skip = flip ? (sw->xend_scissored - sw->x)
                              : (sw->x - sw->xend_scissored);
    if (skip != 0)
    {
        sw->r.w += (uint32_t)skip * (uint32_t)sw->drinc;
        sw->g.w += (uint32_t)skip * (uint32_t)sw->dginc;
        sw->b.w += (uint32_t)skip * (uint32_t)sw->dbinc;
        sw->a.w += (uint32_t)skip * (uint32_t)sw->dainc;
        sw->z.w += (uint32_t)skip * (uint32_t)sw->dzinc;
        sw->s.w += (uint32_t)skip * (uint32_t)sw->dsinc;
        sw->t.w += (uint32_t)skip * (uint32_t)sw->dtinc;
        sw->w.w += (uint32_t)skip * (uint32_t)sw->dwinc;
        sw->x = sw->xend_scissored;
    }

    sw->length = flip ? (extent->startx - sw->x) : (sw->x - extent->startx);

    if (object->m_other_modes.z_source_sel)
    {
        sw->z.w = (uint32_t)object->m_misc_state.m_primitive_z << 16;
        sw->dzpix = object->m_misc_state.m_primitive_dz;
        sw->dzinc = 0;
    }
    else
    {
        sw->dzpix = sb->m_span_dzpix;
    }
}

static inline void rdp_span_walk_step(rdp_span_walk *sw)
{
    sw->r.w += sw->drinc;
    sw->g.w += sw->dginc;
    sw->b.w += sw->dbinc;
    sw->a.w += sw->dainc;
    sw->s.w += sw->dsinc;
    sw->t.w += sw->dtinc;
    sw->w.w += sw->dwinc;
    sw->z.w += sw->dzinc;
    sw->x   += sw->xinc;
}

static cen64_flatten void rdp_span_draw_1cycle(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid)
{
    (void)threadid;

    /* Floor'd left scissor column: a fractional left edge renders its
     * boundary column with partial coverage from the clamped (10.2) edge
     * positions the walker stored, so the write clip admits the floor'd
     * column rather than ceiling past it. Copy/fill keep their own
     * floor'd bounds (fraction ignored). PRDP 10:9. */
    const int32_t clipx1 = object->m_scissor.m_xh;
    const int32_t clipx2 = object->m_scissor.m_xl_clip;
    const int32_t tilenum = object->tilenum;
    const bool flip = object->flip;

    rdp_span_aux* userdata = (rdp_span_aux*)extent->userdata;
    /* Worker-side span entry: initialize this span's aux from the
     * primitive snapshot, then replay coverage from the stored edge
     * data (see rdp_span_aux_init). */
    rdp_span_aux_init(rdp, userdata, object);
    rdp_compute_cvg(rdp, userdata,
        flip ? userdata->m_cvg_majorx    : userdata->m_cvg_minorx,
        flip ? userdata->m_cvg_minorx    : userdata->m_cvg_majorx,
        flip ? userdata->m_cvg_majorxint : userdata->m_cvg_minorxint,
        flip ? userdata->m_cvg_minorxint : userdata->m_cvg_majorxint,
        scanline, object->m_cvg_yh, object->m_cvg_yl);

    rdp_span_walk sw;
    rdp_span_walk_init(&sw, scanline, extent, object, userdata);

    /* Span-end LOD footprint (see TEXPIPE_LOD_1CYCLE_SPANEND): applies
     * only when all four sublines are valid, by compute_cvg's own
     * per-subline predicate (y window and non-inverted int extents). */
    bool span_lodend = true;
    {
        const int32_t scanlinespx = scanline << 2;
        const int32_t *lxi = flip ? userdata->m_cvg_majorxint : userdata->m_cvg_minorxint;
        const int32_t *rxi = flip ? userdata->m_cvg_minorxint : userdata->m_cvg_majorxint;
        for (int32_t i = 0; i < 4; i++)
        {
            const bool vy = (scanlinespx + i) >= object->m_cvg_yh
                         && (scanlinespx + i) <  object->m_cvg_yl;
            if (!vy || rxi[i] - lxi[i] < 0)
                span_lodend = false;
        }
    }

    const bool partialreject = (userdata->m_color_inputs.blender2b_a[0] == &userdata->m_inv_pixel_color && userdata->m_color_inputs.blender1b_a[0] == &userdata->m_pixel_color);
    const int32_t sel0 = (userdata->m_color_inputs.blender2b_a[0] == &userdata->m_memory_color) ? 1 : 0;

    const int32_t cycle0 = ((object->m_other_modes.sample_type & 1) << 1) | (object->m_other_modes.bi_lerp0 & 1);

    int32_t sss = 0;
    int32_t sst = 0;

    /* LOD footprint gate: the per-pixel LOD machinery in lod_1cycle (a
     * second perspective divide for the Y leg plus the step/clamp math)
     * only has observable outputs through the promoted tile (tex_lod_en)
     * and the LOD_FRACTION combiner input (the only two muxes that can
     * reference m_lod_fraction are RGB mul code 13 and Alpha mul code 0;
     * 1-cycle mode evaluates only the cycle-1 equation). Computed once per
     * span, mirroring the cc1_uses_texel1 gate below. */
    const bool span_needs_lod = object->m_other_modes.tex_lod_en
        || userdata->m_color_inputs.combiner_rgbmul[1]   == &userdata->m_lod_fraction
        || userdata->m_color_inputs.combiner_alphamul[1] == &userdata->m_lod_fraction;

    /* 1-cycle TEXEL1 is a hardware pipeline artifact: when the (cycle-1)
     * combiner reads TEXEL1 in 1-cycle mode it samples the NEXT pixel's
     * texel, not the current one (n64brew RDP pipeline; ParaLLEl-RDP
     * combiner_uses_pipelined_texel1). Detect it here so the per-pixel
     * next-pixel fetch below is only paid for when TEXEL1 is actually
     * referenced -- an ungated version doubles texture-fetch cost. Gate
     * mirrors ParaLLEl's combiner_accesses_texel1 over the cycle-1 mux. */
    const bool cc1_uses_texel1 =
        userdata->m_color_inputs.combiner_rgbsub_a[1]   == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_rgbsub_b[1]   == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_rgbmul[1]     == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_rgbmul[1]     == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_rgbadd[1]     == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_alphasub_a[1] == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_alphasub_b[1] == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_alphamul[1]   == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_alphaadd[1]   == &userdata->m_texel1_alpha;

    /* Texture pipeline gate: when the cycle-1 combiner reads no texel
     * register (TEX0/TEX0_ALPHA via any mux slot; TEX1/TEX1_ALPHA already
     * detected by cc1_uses_texel1) and the LOD footprint gate is idle,
     * every output of the texture pipeline is unobservable for this span:
     * the perspective divides prime coordinates only the fetch reads, the
     * fetched texels feed only combiner slots that are not selected, and
     * and the precomputed pipeline coordinates have no other consumers.
     * Untextured spans -- shaded/blended
     * geometry, which real scenes carry plenty of -- then skip both
     * per-pixel perspective divides, the LOD pipeline, the tile clamp
     * setup, and all texel fetches outright. One well-predicted per-span
     * bool; no code duplication. */
    const bool span_textured = span_needs_lod || cc1_uses_texel1
        || userdata->m_color_inputs.combiner_rgbsub_a[1]   == &userdata->m_texel0_color
        || userdata->m_color_inputs.combiner_rgbsub_b[1]   == &userdata->m_texel0_color
        || userdata->m_color_inputs.combiner_rgbmul[1]     == &userdata->m_texel0_color
        || userdata->m_color_inputs.combiner_rgbmul[1]     == &userdata->m_texel0_alpha
        || userdata->m_color_inputs.combiner_rgbadd[1]     == &userdata->m_texel0_color
        || userdata->m_color_inputs.combiner_alphasub_a[1] == &userdata->m_texel0_alpha
        || userdata->m_color_inputs.combiner_alphasub_b[1] == &userdata->m_texel0_alpha
        || userdata->m_color_inputs.combiner_alphamul[1]   == &userdata->m_texel0_alpha
        || userdata->m_color_inputs.combiner_alphaadd[1]   == &userdata->m_texel0_alpha;

    if (span_textured)
    {
        rdp_texpipe_calculate_clamp_diffs(tilenum, userdata, object);
        if (object->m_other_modes.persp_tex_en)
        {
            rdp_tc_div(rdp, sw.s.w >> 16, sw.t.w >> 16, sw.w.w >> 16, &sss, &sst);
        }
        else
        {
            rdp_tc_div_no_perspective(sw.s.w >> 16, sw.t.w >> 16, sw.w.w >> 16, &sss, &sst);
        }
    }

    /* NOISE combiner input (mux code 7) only resolves to sub_a_rgb, either
     * cycle. */
    const bool cc_uses_noise =
        userdata->m_color_inputs.combiner_rgbsub_a[0] == &userdata->m_noise_color ||
        userdata->m_color_inputs.combiner_rgbsub_a[1] == &userdata->m_noise_color;

    /* Span-invariant hoists. The loop writes through userdata and the
     * framebuffer, so without these the optimizer reloads each one every
     * pixel; all are fixed by othermodes for the whole span. */
    const color_inputs_t *const ci = &userdata->m_color_inputs;
    const texel_cycler_t texel_cycle = rdp->m_tex_pipe.m_cycle[cycle0];
    const texel_cycle_ctx_t texel_ctx0 =
        { &rdp->m_tex_pipe, userdata, object, 0 };
    const read_pixel_t read_pixel_fn = rdp->m_read_pixel[object->m_misc_state.m_fb_size];
    const write_pixel_t write_pixel_fn = rdp->m_write_pixel[object->m_misc_state.m_fb_size];
    /* See rdp_blend_ctx_t. blended_pixel is the output slot, read only
     * when the blender accepts; span scope for a stable address. */
    rgbaint_t blended_pixel;
    const rdp_blend_ctx_t blend_ctx = {
        .b = &rdp->m_blender, .userdata = userdata, .object = object,
        .out = &blended_pixel, .partialreject = partialreject,
        .sel0 = sel0, .sel1 = 0 };
    const bool key_en = object->m_other_modes.key_en;
    const bool alpha_dither_noise = (object->m_other_modes.alpha_dither_mode == 3);
    const bool z_update_en = object->m_other_modes.z_update_en;

    /* RH#001 end-of-span: on the last scanned pixel the pipeline peeks
     * the NEXT scanline's first pixel -- when the span is long enough
     * to fill the pipe (>= 8 pixels) and a next line exists in this
     * primitive (ParaLLEl shading.h conditions). Otherwise the fetch
     * falls through to the one-step extrapolation m_precomp already
     * provides. Span-invariant: computed once. */
    int32_t t1s_end = -1, t1t_end = -1;
    if (cc1_uses_texel1 && extent->param[SPAN_NS].dpdx != 0 && sw.length + 1 >= 8)
    {
        int32_t ns, nt;
        if (object->m_other_modes.persp_tex_en)
            rdp_tc_div(rdp, extent->param[SPAN_NS].start >> 16,
                extent->param[SPAN_NT].start >> 16,
                extent->param[SPAN_NW].start >> 16, &ns, &nt);
        else
            rdp_tc_div_no_perspective(extent->param[SPAN_NS].start >> 16,
                extent->param[SPAN_NT].start >> 16,
                extent->param[SPAN_NW].start >> 16, &ns, &nt);
        t1s_end = rdp_lod_lookup[ns & 0x7ffff];
        t1t_end = rdp_lod_lookup[nt & 0x7ffff];
    }

    /* See rdp_lod_ctx_t. tile1p is the promoted-tile output, reset per
     * pixel below; it lives at span scope for a stable address. */
    int32_t tile1p = tilenum;
    const rdp_lod_ctx_t lod_ctx = {
        .tp = &rdp->m_tex_pipe, .object = object, .userdata = userdata,
        .stash = NULL, .sss = &sss, .sst = &sst,
        .t1 = &tile1p, .t2 = NULL,
        .dsinc = sw.dsinc, .dtinc = sw.dtinc, .dwinc = sw.dwinc,
        .prim_tile = tilenum, .need_lod = span_needs_lod };

    for (int32_t j = 0; j <= sw.length; j++)
    {
        /* Signed 9.2 shade snapping; see the matching comment in the
         * 2-cycle span function. */
        int32_t sr = (int32_t)sw.r.w >> 14;
        int32_t sg = (int32_t)sw.g.w >> 14;
        int32_t sb = (int32_t)sw.b.w >> 14;
        int32_t sa = (int32_t)sw.a.w >> 14;
        int32_t sz = (sw.z.w >> 10) & 0x3fffff;
        const bool valid_x = (flip) ? (sw.x >= sw.xend_scissored) : (sw.x <= sw.xend_scissored);

        /* The texture coordinate pipeline is one pixel deep: each pixel
         * samples the coordinates left by its predecessor's pipeline step and
         * computes its successor's. Hardware runs this step for every span
         * pixel and scissors only the framebuffer write, so it advances here
         * (together with the sss/sst reload below) even for pixels the write
         * scissor rejects, e.g. the span pixel sitting exactly on the right
         * scissor bound -- otherwise the first visible pixel samples its
         * scissored neighbor's coordinates: one wrong-texel column at the
         * boundary on the scanlines where S/T cross a texel edge between the
         * two positions. After the positional span start above, at most one
         * span pixel per end lies outside the write scissor. */
        tile1p = tilenum;
        if (span_textured)
            rdp_texpipe_lod(&lod_ctx, sw.s.w, sw.t.w, sw.w.w,
                (span_lodend && j == sw.length - 1)
                    ? TEXPIPE_LOD_1CYCLE_SPANEND : TEXPIPE_LOD_1CYCLE);

        if (sw.x >= clipx1 && sw.x < clipx2 && valid_x)
        {
            uint8_t offx, offy;
            rdp_lookup_cvmask_derivatives(rdp, userdata->m_cvg[sw.x], &offx, &offy, userdata);

            rdp_rgbaz_correct_triangle(rdp, offx, offy, &sr, &sg, &sb, &sa, &sz, userdata, object);
            rdp_rgbaz_clip(rdp, sr, sg, sb, sa, &sz, userdata);

            if (span_textured)
            {
            texel_cycle(&texel_ctx0, &userdata->m_texel0_color, &userdata->m_texel0_color, sss, sst, tile1p);
            unsigned t0a = rgbaint_get_a(&userdata->m_texel0_color);
            rgbaint_set_rgba(&userdata->m_texel0_alpha, t0a, t0a, t0a, t0a);
            if (cc1_uses_texel1)
            {
                /* TEXEL1 = the next pixel's texel. m_precomp_s/t are the next
                 * pixel's perspective-divided coordinates (set by lod_1cycle
                 * above); apply the same lod_lookup clamp the current pixel's
                 * coordinates receive, then sample with the current tile. */
                int32_t t1s, t1t;
                if (j == sw.length && t1s_end >= 0) {
                    /* Last scanned pixel: next scanline's first pixel
                     * (RH#001 edge case). */
                    t1s = t1s_end;
                    t1t = t1t_end;
                } else {
                    t1s = rdp_lod_lookup[userdata->m_precomp_s & 0x7ffff];
                    t1t = rdp_lod_lookup[userdata->m_precomp_t & 0x7ffff];
                }
                texel_cycle(&texel_ctx0, &userdata->m_texel1_color, &userdata->m_texel0_color, t1s, t1t, tile1p);
                unsigned t1a = rgbaint_get_a(&userdata->m_texel1_color);
                rgbaint_set_rgba(&userdata->m_texel1_alpha, t1a, t1a, t1a, t1a);
            }
            /* When cc1_uses_texel1 is false, no combiner input
             * pointer targets m_texel1_color or m_texel1_alpha (the gate
             * enumerates all nine cycle-1 mux slots), no other stage of
             * the 1-cycle span reads them, and any later span that DOES
             * read TEXEL1 has its own gate true and rewrites both before
             * its combiner runs -- pool aux residue cannot leak into an
             * observable path. No TEXEL1=TEXEL0 mirroring copy is needed
             * here, saving 32 bytes of stores per textured pixel. */
            }

            if (cc_uses_noise)
            {
                const unsigned noise = rdp_noise_combiner(rdp_pixel_noise(rdp, j));
                rgbaint_set_rgba(&userdata->m_noise_color, 0, (int32_t)noise, (int32_t)noise, (int32_t)noise);
            }

            // With chroma keying, the pixel color bypasses the combiner
            // and comes from the SUB_A input directly (pre-merge value).
            const rgbaint_t chroma_bypass = *ci->combiner_rgbsub_a[1];
            rgbaint_t comb = rdp_combiner_mix(ci, 1);

            if (key_en)
                userdata->m_keyalpha = rdp_chroma_key_alpha(rdp, &comb, userdata);

            rdp_combiner_clamp(&comb);
            userdata->m_pixel_color = comb;

            if (key_en)
                rdp_chroma_bypass(&userdata->m_pixel_color, chroma_bypass);

            //Alpha coverage combiner
            rgbaint_set_a(&userdata->m_pixel_color, rdp_get_alpha_cvg(rdp, rgbaint_get_a(&userdata->m_pixel_color), userdata, object));

            /* DPS capture, upstream of the z/blend/coverage write
             * gates like the hardware buffer. */
            if (userdata->m_dps_cap)
                rdp_dps_span_capture(rdp, userdata, sw.x,
                                     (int32_t)object->m_misc_state.m_fb_size);

            const unsigned curpixel = sw.fb_index + sw.x;
            const unsigned zbcur = sw.zb + curpixel;
            const unsigned zhbcur = sw.zhb + curpixel;

            read_pixel_fn(rdp, curpixel, userdata, object);

            if (rdp_z_compare(rdp, zbcur, zhbcur, sz, sw.dzpix, userdata, object))
            {
                int32_t cdith = 0;
                int32_t adith = 0;
                rdp_get_dither_values(rdp, sw.x, scanline, j, &cdith, &adith, object);
                if (alpha_dither_noise)
                    userdata->m_blend_noise_threshold = (int32_t)rdp_noise_threshold(rdp_pixel_noise(rdp, j));

                bool rendered = rdp_blender_cycle1(&blend_ctx, cdith, adith);

                if (rendered)
                {
                    write_pixel_fn(rdp, curpixel, &blended_pixel, userdata, object);
                    if (z_update_en)
                    {
                        rdp_z_store(rdp, object, zbcur, zhbcur, sz, userdata->m_dzpix_enc);
                    }
                }
            }
        }

        if (span_textured)
        {
            sss = userdata->m_precomp_s;
            sst = userdata->m_precomp_t;
        }

        rdp_span_walk_step(&sw);
    }
}
static cen64_flatten void rdp_span_draw_2cycle(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid)
{
    (void)threadid;

    /* Floor'd left scissor column, as in rdp_span_draw_1cycle. */
    const int32_t clipx1 = object->m_scissor.m_xh;
    const int32_t clipx2 = object->m_scissor.m_xl_clip;
    const int32_t tilenum = object->tilenum;
    const bool flip = object->flip;

    int32_t tile2 = (tilenum + 1) & 7;
    int32_t tile1 = tilenum;
    const unsigned prim_tile = tilenum;

    int32_t newtile1 = tile1;
    int32_t newtile2 = tile2;
    int32_t news = 0;
    int32_t newt = 0;
    rdp_lod_stash lodstash;
    int32_t stash_valid = 0;

    rdp_span_aux* userdata = (rdp_span_aux*)extent->userdata;
    /* Worker-side span entry: initialize this span's aux from the
     * primitive snapshot, then replay coverage from the stored edge
     * data (see rdp_span_aux_init). */
    rdp_span_aux_init(rdp, userdata, object);
    rdp_compute_cvg(rdp, userdata,
        flip ? userdata->m_cvg_majorx    : userdata->m_cvg_minorx,
        flip ? userdata->m_cvg_minorx    : userdata->m_cvg_majorx,
        flip ? userdata->m_cvg_majorxint : userdata->m_cvg_minorxint,
        flip ? userdata->m_cvg_minorxint : userdata->m_cvg_majorxint,
        scanline, object->m_cvg_yh, object->m_cvg_yl);

    rdp_span_walk sw;
    rdp_span_walk_init(&sw, scanline, extent, object, userdata);

    /* 2-cycle port of the untextured gate. In 2-cycle mode the
     * texture pipeline's outputs -- m_texel0/1_color, m_texel0/1_alpha and
     * m_lod_fraction -- are observable ONLY through the combiner input
     * pointers (both cycles evaluate, so both cycles' nine mux slots are
     * enumerated); m_next_texel_color and m_precomp_s/t are internal pipeline
     * state consumed only by the texture stages themselves, and the
     * blender reads no texel register. When no slot targets any of the
     * five fields and texture LOD is off (conservative, mirroring the
     * 1-cycle gate), the whole per-pixel texture block is dead work:
     * both perspective divides, lod_2cycle, the prefetch divide, both
     * texel cycles, the alpha-compare next-pixel texel evaluations, and
     * the cycle-1 texel rotation swap. Untextured 2-cycle content --
     * fogged/blended shaded geometry -- then pays none of it. */
    /* RH#002: in the SECOND cycle of 2-cycle mode, TEX1 is the NEXT
     * pixel of the first texture (n64brew RDP Hazards; Monster Truck
     * Madness menu is the documented affected title). The rotation
     * swap below correctly promotes TEX0 <- second texture, but the
     * stale swapped value for TEX1 (current pixel's first texture)
     * diverges from hardware. Gate on the cycle-1 mux actually
     * referencing TEXEL1 so non-consumers pay nothing. End-of-span
     * uses the next scanline's first pixel via the SPAN_NS/NT/NW
     * plumbing, mirroring RH#001. */
    const bool cc2_uses_texel1 =
        userdata->m_color_inputs.combiner_rgbsub_a[1]   == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_rgbsub_b[1]   == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_rgbmul[1]     == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_rgbadd[1]     == &userdata->m_texel1_color ||
        userdata->m_color_inputs.combiner_alphasub_a[1] == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_alphasub_b[1] == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_alphamul[1]   == &userdata->m_texel1_alpha ||
        userdata->m_color_inputs.combiner_alphaadd[1]   == &userdata->m_texel1_alpha;

    #define TEXPTR2(p) ((p) == &userdata->m_texel0_color || (p) == &userdata->m_texel1_color \
        || (p) == &userdata->m_texel0_alpha || (p) == &userdata->m_texel1_alpha \
        || (p) == &userdata->m_lod_fraction)
    bool span_textured = object->m_other_modes.tex_lod_en;
    for (int cyc2 = 0; cyc2 < 2 && !span_textured; cyc2++)
    {
        span_textured =
            TEXPTR2(userdata->m_color_inputs.combiner_rgbsub_a[cyc2]) ||
            TEXPTR2(userdata->m_color_inputs.combiner_rgbsub_b[cyc2]) ||
            TEXPTR2(userdata->m_color_inputs.combiner_rgbmul[cyc2])   ||
            TEXPTR2(userdata->m_color_inputs.combiner_rgbadd[cyc2])   ||
            TEXPTR2(userdata->m_color_inputs.combiner_alphasub_a[cyc2]) ||
            TEXPTR2(userdata->m_color_inputs.combiner_alphasub_b[cyc2]) ||
            TEXPTR2(userdata->m_color_inputs.combiner_alphamul[cyc2])   ||
            TEXPTR2(userdata->m_color_inputs.combiner_alphaadd[cyc2]);
    }
    #undef TEXPTR2

    if (span_textured)
        rdp_texpipe_calculate_clamp_diffs(tile1, userdata, object);

    bool partialreject = (userdata->m_color_inputs.blender2b_a[1] == &userdata->m_inv_pixel_color && userdata->m_color_inputs.blender1b_a[1] == &userdata->m_pixel_color);
    int32_t sel0 = (userdata->m_color_inputs.blender2b_a[0] == &userdata->m_memory_color) ? 1 : 0;
    int32_t sel1 = (userdata->m_color_inputs.blender2b_a[1] == &userdata->m_memory_color) ? 1 : 0;

    /* See rdp_blend_ctx_t. */
    rgbaint_t blended_pixel;
    const rdp_blend_ctx_t blend_ctx = {
        .b = &rdp->m_blender, .userdata = userdata, .object = object,
        .out = &blended_pixel, .partialreject = partialreject,
        .sel0 = sel0, .sel1 = sel1 };

    int32_t cdith = 0;
    int32_t adith = 0;

    const int32_t cycle0 = ((object->m_other_modes.sample_type & 1) << 1) | (object->m_other_modes.bi_lerp0 & 1);
    const int32_t cycle1 = ((object->m_other_modes.sample_type & 1) << 1) | (object->m_other_modes.bi_lerp1 & 1);
    const texel_cycle_ctx_t texel_ctx0 =
        { &rdp->m_tex_pipe, userdata, object, 0 };
    const texel_cycle_ctx_t texel_ctx1 =
        { &rdp->m_tex_pipe, userdata, object, 1 };

    /* Span-invariant dispatch hoists, mirroring the 1-cycle kernel. Both
     * texel cycler selectors and the framebuffer size are fixed for the
     * whole span, but the loads sit behind rdp-> and object-> and the loop
     * writes through userdata and the framebuffer, so the optimizer cannot
     * prove non-aliasing and reloads each function pointer on every pixel.
     * Reading them once costs nothing and removes seven dependent loads
     * from the per-pixel chain. */
    const texel_cycler_t texel_cycle0 = rdp->m_tex_pipe.m_cycle[cycle0];
    const texel_cycler_t texel_cycle1 = rdp->m_tex_pipe.m_cycle[cycle1];
    const read_pixel_t  read_pixel_fn  = rdp->m_read_pixel[object->m_misc_state.m_fb_size];
    const write_pixel_t write_pixel_fn = rdp->m_write_pixel[object->m_misc_state.m_fb_size];

    int32_t sss = 0;
    int32_t sst = 0;

    if (span_textured)
    {
        if (object->m_other_modes.persp_tex_en)
        {
            rdp_tc_div(rdp, sw.s.w >> 16, sw.t.w >> 16, sw.w.w >> 16, &sss, &sst);
        }
        else
        {
            rdp_tc_div_no_perspective(sw.s.w >> 16, sw.t.w >> 16, sw.w.w >> 16, &sss, &sst);
        }
    }

    /* See rdp_lod_ctx_t. The peek form drives the same pipeline one pixel
     * ahead, into its own outputs and the stash. */
    const rdp_lod_ctx_t lod_ctx = {
        .tp = &rdp->m_tex_pipe, .object = object, .userdata = userdata,
        .stash = NULL, .sss = &sss, .sst = &sst,
        .t1 = &tile1, .t2 = &tile2,
        .dsinc = sw.dsinc, .dtinc = sw.dtinc, .dwinc = sw.dwinc,
        .prim_tile = prim_tile, .need_lod = true };
    const rdp_lod_ctx_t peek_ctx = {
        .tp = &rdp->m_tex_pipe, .object = object, .userdata = NULL,
        .stash = &lodstash, .sss = &news, .sst = &newt,
        .t1 = &newtile1, .t2 = &newtile2,
        .dsinc = sw.dsinc, .dtinc = sw.dtinc, .dwinc = sw.dwinc,
        .prim_tile = prim_tile, .need_lod = true };

    /* NOISE combiner input (mux code 7) only resolves to sub_a_rgb. */
    const bool cc_uses_noise =
        userdata->m_color_inputs.combiner_rgbsub_a[0] == &userdata->m_noise_color ||
        userdata->m_color_inputs.combiner_rgbsub_a[1] == &userdata->m_noise_color;
    for (int32_t j = 0; j <= sw.length; j++)
    {
        /* Shade snapping is SIGNED 9.2: a slightly-negative interpolated
         * value must survive to the centroid correction, which can rescue
         * it into positive range at partial-coverage edge pixels; hardware
         * does not pre-clamp here. (Matches ParaLLEl-RDP shading.h
         * interpolate_rgba's signed i16 snapping; see also the n64brew RDP
         * combiner overflow notes on 9-bit input ranges. Behavior visible
         * at AA edge pixels where raw shade dips just below zero and the
         * centroid offset restores a small positive value.) */
        int32_t sr = (int32_t)sw.r.w >> 14;
        int32_t sg = (int32_t)sw.g.w >> 14;
        int32_t sb = (int32_t)sw.b.w >> 14;
        int32_t sa = (int32_t)sw.a.w >> 14;
        int32_t sz = (sw.z.w >> 10) & 0x3fffff;

        const bool valid_x = (flip) ? (sw.x >= sw.xend_scissored) : (sw.x <= sw.xend_scissored);

        /* Texture coordinate pipeline advances for every span pixel (with the
         * sss/sst reload below); the write scissor gates only the visible
         * work. See the 1-cycle span for the full rationale. */
        if (span_textured)
        {
            if (stash_valid)
            {
                /* LOD pipeline dedup: the previous pixel's PEEK evaluated
                 * this pixel's entire LOD from identical inputs -- the loop
                 * bottom reloads sss/sst from the same m_precomp the peek
                 * consumed, and the base coordinates have since stepped by
                 * exactly one increment. Its outputs are still live:
                 * news/newt are this pixel's clamped fetch coordinates,
                 * newtile1/newtile2 its promoted tiles, and the stash holds
                 * the raw next divide (this pixel's precomp write) and the
                 * LOD fraction. Applying them replaces two perspective
                 * divides and a full LOD footprint per pixel. */
                sss = news;
                sst = newt;
                tile1 = newtile1;
                tile2 = newtile2;
                userdata->m_lod_fraction = lodstash.lod_fraction;
                userdata->m_precomp_s = lodstash.raw_next_s;
                userdata->m_precomp_t = lodstash.raw_next_t;
                stash_valid = 0;
            }
            else
            {
                rdp_texpipe_lod(&lod_ctx, sw.s.w, sw.t.w, sw.w.w, TEXPIPE_LOD_2CYCLE);
            }
        }

        if (sw.x >= clipx1 && sw.x < clipx2 && valid_x)
        {
            const unsigned compidx = rdp->m_compressed_cvmasks[userdata->m_cvg[sw.x]];
            userdata->m_current_pix_cvg = rdp->cvarray[compidx].cvg;
            userdata->m_current_cvg_bit = rdp->cvarray[compidx].cvbit;
            const unsigned offx = rdp->cvarray[compidx].xoff;
            const unsigned offy = rdp->cvarray[compidx].yoff;

            rdp_rgbaz_correct_triangle(rdp, offx, offy, &sr, &sg, &sb, &sa, &sz, userdata, object);
            rdp_rgbaz_clip(rdp, sr, sg, sb, sa, &sz, userdata);

            if (span_textured)
            {
            news = userdata->m_precomp_s;
            newt = userdata->m_precomp_t;
            rdp_texpipe_lod(&peek_ctx, sw.s.w + sw.dsinc, sw.t.w + sw.dtinc, sw.w.w + sw.dwinc, TEXPIPE_LOD_PEEK);
            stash_valid = 1;

            texel_cycle0(&texel_ctx0, &userdata->m_texel0_color, &userdata->m_texel0_color, sss, sst, tile1);
            texel_cycle1(&texel_ctx1, &userdata->m_texel1_color, &userdata->m_texel0_color, sss, sst, tile2);
            unsigned t0a = rgbaint_get_a(&userdata->m_texel0_color);
            unsigned t1a = rgbaint_get_a(&userdata->m_texel1_color);
            rgbaint_set_rgba(&userdata->m_texel0_alpha, t0a, t0a, t0a, t0a);
            rgbaint_set_rgba(&userdata->m_texel1_alpha, t1a, t1a, t1a, t1a);
            }

            if (cc_uses_noise)
            {
                const unsigned noise = rdp_noise_combiner(rdp_pixel_noise(rdp, j));
                rgbaint_set_rgba(&userdata->m_noise_color, 0, (int32_t)noise, (int32_t)noise, (int32_t)noise);
            }

            /* Alpha-compare reference is the NEXT pixel's cycle-0 combiner
             * alpha (n64brew Set Other Modes hazards: "2-Cycle mode pipeline
             * bug: Alpha compare uses the output of the first combiner cycle
             * of the next pixel as the value to compare to the threshold").
             * Evaluate cycle 0 once with next-pixel inputs: texel0/texel1
             * through the prefetch divide and per-pixel promoted tiles
             * (news/newt/newtile1/newtile2), shade alpha stepped by dadx.
             * Approximations, recorded: LOD_FRACTION and noise inputs use the
             * current pixel's values; next shade alpha skips the coverage
             * centroid; at the last span pixel the prefetch walks one step
             * beyond the span (hardware reads "garbage" there per RH#002's
             * scanline-edge caveat). ParaLLEl models the CURRENT pixel's
             * reference (combiner.h alpha_test_reference), so par-side gates
             * are expected to diverge on alpha-compare 2-cycle content; n64brew
             * documentation confirms. */
            int32_t next_c0_alpha = -1;
            if (object->m_other_modes.alpha_compare_en)
            {
                rgbaint_t save_t0 = rgbaint_make(0, 0, 0, 0);
                rgbaint_t save_t1 = save_t0;
                rgbaint_t save_t0a = save_t0;
                rgbaint_t save_t1a = save_t0;
                rgbaint_t save_sh = userdata->m_shade_color;
                rgbaint_t save_sha = userdata->m_shade_alpha;

                /* With the gate false the texel registers are never
                 * modified this span, so the next-pixel texel evaluations
                 * (and their save/restore) are dead; only the shade
                 * stepping and the cycle-0 combiner evaluation remain
                 * observable through next_c0_alpha. */
                if (span_textured)
                {
                save_t0 = userdata->m_texel0_color;
                save_t1 = userdata->m_texel1_color;
                /* the ALPHA combiner selects read the broadcast alpha
                 * registers, not the color registers */
                save_t0a = userdata->m_texel0_alpha;
                save_t1a = userdata->m_texel1_alpha;

                texel_cycle0(&texel_ctx0, &userdata->m_next_texel_color, &userdata->m_next_texel_color, news, newt, newtile1);
                userdata->m_texel0_color = userdata->m_next_texel_color;
                texel_cycle1(&texel_ctx1, &userdata->m_texel1_color, &userdata->m_texel0_color, news, newt, newtile2);
                {
                    const unsigned nt0a = rgbaint_get_a(&userdata->m_texel0_color);
                    const unsigned nt1a = rgbaint_get_a(&userdata->m_texel1_color);
                    rgbaint_set_rgba(&userdata->m_texel0_alpha, nt0a, nt0a, nt0a, nt0a);
                    rgbaint_set_rgba(&userdata->m_texel1_alpha, nt1a, nt1a, nt1a, nt1a);
                }
                }

                int32_t next_sa = (int32_t)((sw.a.w + sw.dainc) >> 16);
                if (next_sa & 0xfffffe00) next_sa = 0;
                if (next_sa > 0xff) next_sa = 0xff;
                rgbaint_set_a(&userdata->m_shade_color, next_sa);
                rgbaint_set_rgba(&userdata->m_shade_alpha, next_sa, next_sa, next_sa, next_sa);

                rgbaint_t ncomb = rdp_combiner_mix(&userdata->m_color_inputs, 0);
                rdp_combiner_clamp(&ncomb);
                next_c0_alpha = (int32_t)rgbaint_get_a(&ncomb);

                if (span_textured)
                {
                    userdata->m_texel0_color = save_t0;
                    userdata->m_texel1_color = save_t1;
                    userdata->m_texel0_alpha = save_t0a;
                    userdata->m_texel1_alpha = save_t1a;
                }
                userdata->m_shade_color = save_sh;
                userdata->m_shade_alpha = save_sha;
            }

            rgbaint_t comb = rdp_combiner_mix(&userdata->m_color_inputs, 0);
            rdp_combiner_cycle0(&comb);
            rgbaint_copy(&userdata->m_combined_color, &comb);

            /* Cycle-1 texel rotation as a SWAP, matching ParaLLEl-RDP
             * shading.h's promotion (cycle-1 TEXEL0 = tile2 sample, TEXEL1
             * approximated by the current tile1 sample). A true pipeline
             * advance (TEXEL1 = next pixel's texel0 via the prefetch divide
             * and promoted tile) is a recorded negative: without the
             * span-signal end-of-span coordinates it diverges from both
             * oracles while fixing nothing. Do not reintroduce it without
             * the full span-signal machinery. */
            if (span_textured)
            {
                rgbaint_t temp_color = userdata->m_texel0_color;
                userdata->m_texel0_color = userdata->m_texel1_color;
                userdata->m_texel1_color = temp_color;
            }

            /* 9 bits wide, like the color lanes: COMBINED_ALPHA reaches
             * the second cycle's multiplier, where bit 8 is the sign. */
            const int32_t ca = rgbaint_get_a32(&userdata->m_combined_color);
            rgbaint_set_rgba(&userdata->m_combined_alpha, ca, ca, ca, ca);
            /* Texel alpha rotation mirrors the color swap (see note above on
             * the reverted true-advance experiment). With no texel-register
             * consumers the swap of stale values is dead. */
            if (span_textured)
            {
                rgbaint_t temp_alpha = userdata->m_texel0_alpha;
                userdata->m_texel0_alpha = userdata->m_texel1_alpha;
                userdata->m_texel1_alpha = temp_alpha;

                if (cc2_uses_texel1)
                {
                    /* RH#002: cycle-1 TEX1 = next pixel of the FIRST
                     * texture (or the next scanline's first pixel at
                     * end of span). news/newt are the next pixel's
                     * coordinates, newtile1 its promoted first tile.
                     * Interior pixels advance (next pixel of the first
                     * texture). The END pixel keeps the swapped stale
                     * value: the end-pixel "garbage" is closest to the
                     * stale latch, not a clamped over-fetch, and not the
                     * next scanline's start. Residual rule (bilinear
                     * t-frac rows) still under characterization. */
                    if (j != sw.length) {
                        texel_cycle0(&texel_ctx0, &userdata->m_texel1_color, &userdata->m_texel1_color, news, newt, newtile1);
                        const unsigned r2a = rgbaint_get_a(&userdata->m_texel1_color);
                        rgbaint_set_rgba(&userdata->m_texel1_alpha, r2a, r2a, r2a, r2a);
                    }
                }
            }

            // Chroma key bypass captures the second-cycle SUB_A input before
            // the combine mutates it (pre-merge value).
            const rgbaint_t chroma_bypass = *userdata->m_color_inputs.combiner_rgbsub_a[1];
            comb = rdp_combiner_mix(&userdata->m_color_inputs, 1);

            if (object->m_other_modes.key_en)
                userdata->m_keyalpha = rdp_chroma_key_alpha(rdp, &comb, userdata);

            rdp_combiner_clamp(&comb);
            rgbaint_copy(&userdata->m_pixel_color, &comb);

            if (object->m_other_modes.key_en)
                rdp_chroma_bypass(&userdata->m_pixel_color, chroma_bypass);

            //Alpha coverage combiner
            /* Alpha-compare reference: in 2-cycle mode the hardware tests the
             * CYCLE-0 combiner alpha (ParaLLEl-RDP combiner.h: the
             * alpha_test_reference comes out of combiner_cycle0), while the
             * blend math and coverage modulation below use the final cycle-1
             * alpha. Evaluated against the PRE-modulation coverage
             * (m_current_pix_cvg is mutated by get_alpha_cvg just below).
             *
             * key_en is a cycle-1 term and does not reach cycle 0, so the
             * keyed alpha never sources this reference and does not displace
             * the dither seed here: both legs below are cycle-0 quantities.
             * The keyed alpha reaches the blender as the pixel alpha instead,
             * which is where get_alpha_cvg muxes it in. */
            if (object->m_other_modes.alpha_compare_en)
            {
                int32_t ref = next_c0_alpha; /* NEXT pixel cycle-0 alpha, see above */
                ref += (ref + 1) >> 8;
                if (object->m_other_modes.alpha_cvg_select)
                {
                    ref = object->m_other_modes.cvg_times_alpha
                        ? (((ref * (int32_t)userdata->m_current_pix_cvg) + 4) >> 3)
                        : ((int32_t)userdata->m_current_pix_cvg << 5);
                }
                else
                {
                    int32_t refcd = 0, refad = 0;
                    rdp_get_dither_values(rdp, sw.x, scanline, j, &refcd, &refad, object);
                    ref += refad;
                }
                if (ref > 0xff) ref = 0xff;
                userdata->m_alpha_test_ref = ref;
            }
            rgbaint_set_a(&userdata->m_pixel_color, rdp_get_alpha_cvg(rdp, rgbaint_get_a(&userdata->m_pixel_color), userdata, object));

            const unsigned curpixel = sw.fb_index + sw.x;
            const unsigned zbcur = sw.zb + curpixel;
            const unsigned zhbcur = sw.zhb + curpixel;

            read_pixel_fn(rdp, curpixel, userdata, object);

            if(rdp_z_compare(rdp, zbcur, zhbcur, sz, sw.dzpix, userdata, object))
            {
                rdp_get_dither_values(rdp, sw.x, scanline, j, &cdith, &adith, object);
                if (object->m_other_modes.alpha_dither_mode == 3)
                    userdata->m_blend_noise_threshold = (int32_t)rdp_noise_threshold(rdp_pixel_noise(rdp, j));

                bool rendered = rdp_blender_cycle2(&blend_ctx, cdith, adith);

                if (rendered)
                {
                    write_pixel_fn(rdp, curpixel, &blended_pixel, userdata, object);
                    if (object->m_other_modes.z_update_en)
                    {
                        rdp_z_store(rdp, object, zbcur, zhbcur, sz, userdata->m_dzpix_enc);
                    }
                }
            }
        }

        sss = userdata->m_precomp_s;
        sst = userdata->m_precomp_t;

        rdp_span_walk_step(&sw);
    }
}
static cen64_flatten void rdp_span_draw_copy(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid)
{
    (void)threadid;
    const int32_t clipx1 = object->m_scissor.m_xh;
    const int32_t clipx2 = object->m_scissor.m_xl;
    const int32_t tilenum = object->tilenum;
    const bool flip = object->flip;

    /* Copy-pipe alpha compare is defined by the COLOR IMAGE format, not the
     * render tile's (n64brew RDP/Pipeline, Alpha Compare). For a 4-bit color
     * image the test "always fails if enabled", so the whole span writes
     * nothing; the texture fetch below has no side effects outside
     * m_texel0_color, so the span can be abandoned outright.
     *
     * The other sizes: 16-bit tests the texel's alpha bit (the RGBA5551 LSB,
     * which the copy fetch has already expanded, so the a != 0 test below
     * covers it); 32-bit cannot reach here at all, since COPY to a 32-bit
     * color image crashes the pipe in render_spans; and 8-bit is documented
     * to compare the texel against the blend color's alpha or a noise
     * threshold per dither_alpha_en, which is deliberately NOT modelled --
     * ParaLLEl-RDP gates the entire test on a 16-bit color image and so
     * treats 8-bit as always-pass, cen64 has always agreed with it, and
     * wiki prose alone is not enough to move a path this many titles touch.
     * Recorded in FINDINGS instead.
     *
     * That same ParaLLEl gate also makes the 4-bit case an always-pass,
     * which is where this diverges from it: n64brew is the primary hardware
     * reference and the gate demonstrably does not model the 8-bit rule
     * either, so it is not an exhaustive account of this hazard. */
    if (object->m_other_modes.alpha_compare_en &&
        object->m_misc_state.m_fb_size == 0)
        return;

    rdp_span_aux* userdata = (rdp_span_aux*)extent->userdata;
    /* Producer offload: copy spans read only the TMEM pointer and the
     * producer-written m_unscissored_rx from aux; no other init needed
     * (m_texel0_color is written by the texture pipe before any read).
     * Fill spans read no aux at all and get no init. */
    userdata->m_tmem = object->m_tmem_src;

    const int32_t xstart = extent->startx;
    const int32_t xend = userdata->m_unscissored_rx;
    const int32_t xend_scissored = extent->stopx;
    const int32_t xinc = flip ? 1 : -1;
    const int32_t length = flip ? (xstart - xend) : (xend - xstart);

    /* The copy pipe fetches 64 bits of texels per cycle (4 pixels for a
     * 16-bit color image, 8 for 8-bit; n64brew RDP Pipeline). S/T are
     * interpolated ONCE PER GROUP -- the full DsDx step per group, from the
     * span start -- and each pixel within the group selects its texel with
     * an integer in-group offset applied AFTER the tile shift, in texel
     * space (ParaLLEl-RDP interpolate_st_copy / sample_texture_copy).
     * Stepping S per pixel by DsDx/4 and shifting each pixel's own
     * coordinate is wrong whenever shift_s != 0 (the in-group advance
     * collapses under the shift) or a group straddles a mask or mirror
     * boundary. */
    const int32_t s_start = extent->param[SPAN_S].start;
    const int32_t t_start = extent->param[SPAN_T].start;
    const int32_t w_start = extent->param[SPAN_W].start;
    const int32_t ds_group = object->m_span_base.m_span_ds; /* already & ~0x1f */
    const int32_t dt_group = object->m_span_base.m_span_dt;
    const int32_t dw_group = object->m_span_base.m_span_dw;
    const bool persp = object->m_other_modes.persp_tex_en;
    const int32_t gshift = (object->m_misc_state.m_fb_size == 2) ? 2 : 3;
    const int32_t gmask = (1 << gshift) - 1;

    const int32_t fb_index = object->m_misc_state.m_fb_width * scanline;

    /* See rdp_copy_ctx_t. */
    rdp_copy_ctx_t copy_ctx;
    rdp_texpipe_copy_ctx_init(&copy_ctx, &rdp->m_tex_pipe, object, userdata,
        &userdata->m_texel0_color, (uint32_t)tilenum);

    int32_t x = xend;

    for (int32_t j = 0; j <= length; j++)
    {
        const bool valid_x = (flip) ? (x >= xend_scissored) : (x <= xend_scissored);

        /* Copy-mode scissor right edge is INCLUSIVE: x == XL is written.
         * The scissored rect at XL=80 writes x=80, and the fill span at
         * XL=320 writes x=320 -- which with fb_index + x arithmetic lands
         * at column 0 of the NEXT scanline, as measured. 1/2-cycle spans
         * keep their exclusive edge (n64brew SET_SCISSOR XH <= x < XL
         * holds there; copy/fill are the documented inclusive exception).
         * Adjudicated by the 9:17 full-window framebuffer dump. */
        if (x >= clipx1 && x <= clipx2 && valid_x)
        {
            const int32_t dx = flip ? (x - xend_scissored) : (xend_scissored - x);
            const int32_t group = dx >> gshift;
            const int32_t s_offset = dx & gmask;
            const int32_t lerp = flip ? group : -group;
            int32_t sss = (int32_t)(s_start + ds_group * lerp) >> 16;
            int32_t sst = (int32_t)(t_start + dt_group * lerp) >> 16;
            /* The copy pipe honors persp_tex_en: per-group S/T/W go
             * through the same tc_div as the 1/2-cycle pipe, but copy has
             * no clamp stage, so the divide's saturation folds into the
             * value here -- the w<=0 carry and positive overflow saturate
             * a coordinate to +0x7fff, negative overflow to -0x8000.
             * Adjudicated by 9:17 for the w-carry case (a fill's zeroed
             * (s,t,w) yields texel (1023,1023) and the wrapped TMEM window
             * across seven tile configs). The negative leg is unadjudicated
             * and follows the divide's structural rule (ParaLLEl-RDP
             * perspective_divide). */
            if (persp)
            {
                const int32_t ssw = (int32_t)(w_start + dw_group * lerp) >> 16;
                rdp_tc_div(rdp, sss, sst, ssw, &sss, &sst);
                if (sss & (1 << 18))      sss = 0x7fff;
                else if (sss & (1 << 17)) sss = -0x8000;
                else                      sss = (sss & 0x1ffff);
                if (sst & (1 << 18))      sst = 0x7fff;
                else if (sst & (1 << 17)) sst = -0x8000;
                else                      sst = (sst & 0x1ffff);
            }
            rdp_texpipe_copy(&copy_ctx, sss, sst, s_offset);

            unsigned curpixel = fb_index + x;
            /* 16-bit: alpha bit set. 8-bit: always passes (see the
             * alpha-compare note at the top of this function). 4-bit and
             * 32-bit never reach here. */
            if (rgbaint_get_a(&userdata->m_texel0_color) != 0 || !object->m_other_modes.alpha_compare_en || object->m_misc_state.m_fb_size == 1)
            {
                rdp->m_copy_pixel[object->m_misc_state.m_fb_size](rdp, curpixel, &userdata->m_texel0_color, object);
            }
        }

        x += xinc;
    }
}
/* Execute one 64-bit word of a fill burst plan: write the enabled bytes of
 * the fill value (bit 7 of the enable mask is byte 0), mirroring the
 * byte-granular store shape of the single-burst path below. */
static void fill_write_word(rdp_t *rdp, uint32_t rowb, uint32_t fba,
                                  int32_t w, uint8_t be, uint32_t fval,
                                  uint8_t h0, uint8_t h1)
{
    for (uint32_t b = 0; b < 8u; b++)
    {
        if (!(be & (0x80u >> b)))
            continue;

        const uint32_t addr = rowb + ((uint32_t)w << 3) + b;
        if (addr < fba)
            continue;

        const uint32_t bp = (addr - fba) & 3u;      /* byte within pixel */
        RWRITEADDR8(addr, (uint8_t)(fval >> ((3u - bp) << 3)));
        HWRITEADDR8(addr >> 1, (bp < 2u) ? h0 : h1);
    }
}


/*****************************************************************************/
/* FILL-mode TRIANGLE write law.
 *
 * A triangle's span endpoints are not constrained to the 64-bit write
 * granularity and the fill unit does not mask them coherently. The unit
 * commits 64 bits per clock and has no view of the pixel format beyond
 * which bytes of the fill color land where, so the law is byte geometry
 * and pixel depth enters only through the addresses.
 *
 * Only spans that walk right-to-left (lmajor clear) take it. With lmajor
 * set the span is written naively, exactly as a rectangle is -- 398/398
 * rows against hardware -- and keeps the plain per-pixel path.
 *
 * Writing a0 and a1 for the span's first and last BYTE, W0 = a0 >> 3 and
 * W1 = a1 >> 3 for the words holding them, and
 *
 *     p0 = a0 & 7               first byte within its word
 *     p1 = a1 & 7               last byte within its word
 *     q  = end pixel's index within its word
 *     B  = ceil(p0 / 4)         0, 1, 1, 2 for p0 = 0, 2, 4, 6
 *
 * the row is the single run [ W0 + (q < B) .. W1 ], every word fully
 * enabled except its two ends: the last carries only bytes at or after
 * p1, and the first only bytes at or before p0 -- unless q - B >= 2,
 * where it is fully enabled instead.
 *
 * The trims are complemented with respect to the span -- the run's first
 * word keeps its LOW bytes and its last word its HIGH bytes, an
 * end-of-span comparator resolving the wrong way -- which is why no
 * naive span fill reproduces these rows at any width. Where the two
 * enables of a single write do not intersect the span commits nothing.
 *
 * B is what makes the head selection parameter-free. Fitting it as
 * q < (lo & 3) is right for p0 = 0 and 2 and wrong for 4 and 6, and is
 * equivalent to counting one write per 8 span bytes and anchoring at the
 * tail: 32 bits per pixel reaches only p0 in {0,4}, where the two agree,
 * so RGBA32 captures cannot tell them apart and RGBA16 ones reject the
 * count form.
 *
 * Addresses are absolute. fill_unit alignment follows the framebuffer
 * base and the row pitch, not the row alone, so a base or pitch that is
 * not 8-byte aligned shifts every p0/p1/q with it.
 *
 * At p0 == 0 the head trim is suppressed here and the whole word is
 * written. Hardware does BOTH: over 121 aligned-head rows of general
 * (all-slopes-moving) fill triangles captured on the rig, 61 wrote byte
 * 0 alone and 60 wrote the full word, alternating down the triangle in
 * step with the right edge's word crossings. The two earlier corpora
 * each sampled one phase of that state, which is why they disagreed.
 * The full-word form kept here is the steady one; the byte-0 rows are
 * burst-transient state this path does not model, the same class as
 * the blank and fragment rows of the gated families. The same capture
 * shows the close trim suppressed on 60 rows -- the phenomenon the
 * family-A kz clause carries at 47/50 -- so both trims are state, not
 * constants, and belong to the transient model when it exists. */
static void fill_write_span(rdp_t *rdp, const rdp_poly_state *object,
                            int32_t fb_index, int32_t lo, int32_t hi,
                            uint32_t bpp)
{
    if (hi < lo)
        return;

    const uint32_t fval = object->m_fill_color;
    const uint32_t fba  = object->m_misc_state.m_fb_address;
    const uint8_t  h0 = (fval & 0x10000) ? 3 : 0;
    const uint8_t  h1 = (fval & 0x1) ? 3 : 0;

    const uint32_t a0 = fba + ((uint32_t)fb_index + (uint32_t)lo) * bpp;
    const uint32_t a1 = fba + ((uint32_t)fb_index + (uint32_t)hi) * bpp
                        + bpp - 1u;
    const uint32_t W1 = a1 >> 3;
    const int32_t  p0 = (int32_t)(a0 & 7u);
    const int32_t  p1 = (int32_t)(a1 & 7u);

    /* Right-major spans write the exact byte range [a0 .. a1]: plain
     * head and tail masks, no complement trims, no head-word selection.
     * Hardware-adjudicated at 32bpp: 2,479 of 2,479 non-blank rows
     * across 43 right-major captures -- two scissor slices, the sweep's
     * full my range -- are contiguous [a0 .. a1] byte runs, and no row
     * of either handedness matches the other side's mask form. The
     * complement-trim structure below, and every burst transient ever
     * captured, is left-major-only. A separate one-pixel endpoint
     * residual on 96 of those rows is a span-boundary rounding-or-state
     * question upstream of this function (subline selection is
     * falsified) and is unchanged by the mask form. 16bpp is adjudicated
     * by the repeater64 fill-triangle references: all three right-major
     * captures -- 19,123 triangle pixels -- are byte-exact under this
     * mask and mismatch under the trim law, with zero one-pixel
     * endpoint deviations across their rows. Rectangles remain
     * uncaptured, so they keep the old path. */
    if (!object->rect && object->flip)
    {
        const uint32_t W0 = a0 >> 3;
        for (uint32_t w = W0; w <= W1; w++)
        {
            uint8_t be = 0xffu;                 /* bit 7 == byte 0 */
            if (w == W0)
                be &= (uint8_t)(0xffu >> p0);
            if (w == W1)
                be &= (uint8_t)((0xffu << (7 - p1)) & 0xffu);
            fill_write_word(rdp, 0u, fba, (int32_t)w, be, fval, h0, h1);
        }
        return;
    }

    /* Pixels per 64-bit word, the end pixel's index inside its own word,
     * and the head-selection threshold. */
    const uint32_t ppw = 8u / bpp;
    const int32_t  q = (int32_t)(((uint32_t)fb_index + (uint32_t)hi)
                                 & (ppw - 1u));
    const int32_t  B = (p0 + 3) >> 2;

    const uint32_t S = (a0 >> 3) + ((q < B) ? 1u : 0u);
    if (S > W1)
        return;

    for (uint32_t w = S; w <= W1; w++)
    {
        uint8_t be = 0xffu;                     /* bit 7 == byte 0 */

        if (w == S && (q - B) < 2 && p0 != 0)
            be &= (uint8_t)((0xffu << (7 - p0)) & 0xffu);
        if (w == W1)
            be &= (uint8_t)(0xffu >> p1);
        if (be != 0u)
            fill_write_word(rdp, 0u, fba, (int32_t)w, be, fval, h0, h1);
    }
}

static cen64_flatten void rdp_span_draw_fill(rdp_t *rdp, int32_t scanline, const extent_t *extent, const rdp_poly_state *object, int32_t threadid)
{
    (void)threadid;

    const bool flip = object->flip;

    const int32_t clipx1 = object->m_scissor.m_xh;
    const int32_t clipx2 = object->m_scissor.m_xl;

    const int32_t fb_index = object->m_misc_state.m_fb_width * scanline;

    const int32_t xstart = extent->startx;
    const int32_t xend_scissored = extent->stopx;

    /* FILL-mode triangle burst plan: when the producer attached one
     * (fill_burst_row), execute it verbatim and skip the generic path --
     * including its scissor clamp, which the plan already accounts for
     * (span extents were scissored during edge walking, and the burst
     * geometry is defined over those extents). */
    if (!object->rect && object->m_misc_state.m_fb_size == 3)
    {
        const rdp_span_aux *plan_ud = (const rdp_span_aux *)extent->userdata;
        if (plan_ud != NULL && plan_ud->m_fill_plan)
        {
            const uint32_t fval = object->m_fill_color;
            const uint8_t  h0 = (fval & 0x10000) ? 3 : 0;
            const uint8_t  h1 = (fval & 0x1) ? 3 : 0;
            const uint32_t fba = object->m_misc_state.m_fb_address;
            const uint32_t rowb = fba + ((uint32_t)fb_index << 2);

            for (int32_t w = plan_ud->m_fill_b1lo; w <= plan_ud->m_fill_b1hi; w++)
            {
                uint8_t be = 0xffu;
                if (w == plan_ud->m_fill_b1lo) be &= plan_ud->m_fill_open;
                if (w == plan_ud->m_fill_b1hi) be &= plan_ud->m_fill_close;
                if (be != 0u)
                    fill_write_word(rdp, rowb, fba, w, be, fval, h0, h1);
            }
            if (plan_ud->m_fill_pw >= 0 && plan_ud->m_fill_pm != 0u)
                fill_write_word(rdp, rowb, fba, plan_ud->m_fill_pw,
                                      plan_ud->m_fill_pm, fval, h0, h1);
            for (int32_t w = plan_ud->m_fill_t2lo; w <= plan_ud->m_fill_t2hi; w++)
            {
                uint8_t be = 0xffu;
                if (w == plan_ud->m_fill_t2hi) be &= plan_ud->m_fill_t2close;
                if (be != 0u)
                    fill_write_word(rdp, rowb, fba, w, be, fval, h0, h1);
            }
            return;
        }
    }

    /* Batched fill, and the sole fill implementation. Every value a fill
     * writes is a pure function of pixel POSITION (curpixel parity for
     * 16-bit lane select and its hidden bit; curpixel&3 for the 8-bit byte
     * lane; constants for 32-bit), so the span is order-independent:
     * intersect it with the scissor ONCE and store straight through
     * instead of paying an indirect call, a scissor test and a parity
     * branch per pixel. This is also the hardware's own shape -- FILL
     * commits 64 bits per clock, not per-pixel read-modify-write. The
     * same addresses receive the same values a per-pixel loop would;
     * only the (unobservable) store order differs. */
    int32_t lo = flip ? xend_scissored : xstart;
    int32_t hi = flip ? xstart : xend_scissored;
    if (lo < clipx1) lo = clipx1;
    /* The scissor's right edge is INCLUSIVE in FILL mode -- the column named
     * by SET_SCISSOR XL is rasterized, one further than the 1-/2-cycle rule
     * (n64brew SET_SCISSOR hazards: inclusive on the right and exclusive on
     * the lower edge in FILL and COPY, exclusive on both in 1-/2-cycle).
     * The edge walker has already clamped the span to that column, so an
     * exclusive compare here retracts it by one and leaves the whole right
     * column of every FILL primitive that meets the scissor unwritten. */
    if (hi > clipx2) hi = clipx2;
    if (lo > hi)
        return;

    switch (object->m_misc_state.m_fb_size)
    {
    case 0:
        /* 4-bit color image: unreachable. "Rendering any primitive in FILL
         * mode to a 4-bit color image will crash the RDP" (n64brew RDP
         * Commands, Set Color Image hazards), and render_spans latches
         * m_pipeline_crashed and returns before any span is queued. There
         * is no defined fill-to-4bpp pixel behaviour to model -- unlike the
         * 1-/2-cycle and copy pipes, which do write zero bytes. */
        break;

    case 1:
    {
        /* 8-bit: one byte store per pixel. RDRAM holds N64 byte order, so
         * pixel k of each four takes fill color byte k counting from the
         * top -- a guest byte position, not a host one. BYTE_IN_WORD_XOR
         * is the host-endian swizzle HWRITEADDR8 applies to the hidden
         * array and coincides with (3 - k) only on little-endian hosts;
         * using it here reverses each four-pixel group on big-endian
         * ones. Hoisted to a 4-entry lane table. */
        uint8_t lane[4];
        for (unsigned k = 0; k < 4; k++)
            lane[k] = (uint8_t)(object->m_fill_color >> ((3u - (k & 3u)) << 3));
        const uint32_t fba = object->m_misc_state.m_fb_address;
        for (int32_t x = lo; x <= hi; x++)
        {
            const uint32_t curpixel = (uint32_t)(fb_index + x);
            RWRITEADDR8(fba + curpixel, lane[curpixel & 3]);
        }
        break;
    }

    case 2:
    {
        /* 16-bit: even pixels take the fill word's high half, odd pixels
         * the low half; hidden byte derives from the written value's LSB.
         * Stores are pre-swapped once. */
        const uint16_t v_even = (uint16_t)((object->m_fill_color >> 16) & 0xffff);
        const uint16_t v_odd  = (uint16_t)(object->m_fill_color & 0xffff);
        const uint8_t  h_even = (uint8_t)(((v_even & 1) << 1) | (v_even & 1));
        const uint8_t  h_odd  = (uint8_t)(((v_odd  & 1) << 1) | (v_odd  & 1));
        const uint32_t base = (object->m_misc_state.m_fb_address >> 1) + (uint32_t)fb_index;

        /* A triangle whose spans walk right-to-left (lmajor clear) does
         * not write a plain pixel run in FILL mode: the write stream is
         * 64-bit words with byte enables and a start word that can be
         * displaced past the span head (fill_write_span). Rectangles --
         * internally lmajor-set triangles with all three slopes zero
         * (n64brew RDP Commands, Fill Rectangle) -- and lmajor-set
         * triangles keep the plain run below. */
        if (!object->rect && !flip)
        {
            fill_write_span(rdp, object, fb_index, lo, hi, 2u);
            break;
        }

        for (int32_t x = lo; x <= hi; x++)
        {
            const uint32_t curpixel = (uint32_t)(fb_index + x);
            const uint32_t idx = base + (uint32_t)x;
            if (curpixel & 1)
            {
                RWRITEIDX16(idx, v_odd);
                HWRITEADDR8(idx, h_odd);
            }
            else
            {
                RWRITEIDX16(idx, v_even);
                HWRITEADDR8(idx, h_even);
            }
        }
        break;
    }

    case 3:
    {
        /* 32-bit: constant word store plus two constant hidden bytes per
         * pixel. */
        const uint32_t fval = object->m_fill_color;
        const uint8_t  h0 = (fval & 0x10000) ? 3 : 0;
        const uint8_t  h1 = (fval & 0x1) ? 3 : 0;
        const uint32_t base32 = (object->m_misc_state.m_fb_address >> 2) + (uint32_t)fb_index;
        const uint32_t baseh  = (object->m_misc_state.m_fb_address >> 1) + ((uint32_t)fb_index << 1);

        /* Rectangles are pixel-exact against hardware, and a rectangle
         * is internally an lmajor-set triangle with all three slopes
         * zero (n64brew RDP Commands, Fill Rectangle), so lmajor-set
         * triangles take the same path -- as they do at 16 bits per
         * pixel, where 398/398 rows put them on it. Only lmajor-clear
         * spans take the byte-enabled write law. */
        if (object->rect || flip)
        {
            for (int32_t x = lo; x <= hi; x++)
            {
                RWRITEIDX32(base32 + (uint32_t)x, fval);
                const uint32_t hidx = baseh + ((uint32_t)x << 1);
                HWRITEADDR8(hidx, h0);
                HWRITEADDR8(hidx + 1, h1);
            }
            break;
        }

        fill_write_span(rdp, object, fb_index, lo, hi, 4u);
        break;
    }
    }
}

/*****************************************************************************/

// Texture perspective division ROMs (normpoint/normslope).
static const int32_t s_norm_point_rom[64] =
{
    0x4000, 0x3f04, 0x3e10, 0x3d22, 0x3c3c, 0x3b5d, 0x3a83, 0x39b1,
    0x38e4, 0x381c, 0x375a, 0x369d, 0x35e5, 0x3532, 0x3483, 0x33d9,
    0x3333, 0x3291, 0x31f4, 0x3159, 0x30c3, 0x3030, 0x2fa1, 0x2f15,
    0x2e8c, 0x2e06, 0x2d83, 0x2d03, 0x2c86, 0x2c0b, 0x2b93, 0x2b1e,
    0x2aab, 0x2a3a, 0x29cc, 0x2960, 0x28f6, 0x288e, 0x2828, 0x27c4,
    0x2762, 0x2702, 0x26a4, 0x2648, 0x25ed, 0x2594, 0x253d, 0x24e7,
    0x2492, 0x243f, 0x23ee, 0x239e, 0x234f, 0x2302, 0x22b6, 0x226c,
    0x2222, 0x21da, 0x2193, 0x214d, 0x2108, 0x20c5, 0x2082, 0x2041,
};
static const int32_t s_norm_slope_rom[64] =
{
    0xfc, 0xf4, 0xee, 0xe6, 0xdf, 0xda, 0xd2, 0xcd,
    0xc8, 0xc2, 0xbd, 0xb8, 0xb3, 0xaf, 0xaa, 0xa6,
    0xa2, 0x9d, 0x9b, 0x96, 0x93, 0x8f, 0x8c, 0x89,
    0x86, 0x83, 0x80, 0x7d, 0x7b, 0x78, 0x75, 0x73,
    0x71, 0x6e, 0x6c, 0x6a, 0x68, 0x66, 0x64, 0x62,
    0x60, 0x5e, 0x5c, 0x5b, 0x59, 0x57, 0x56, 0x55,
    0x53, 0x51, 0x50, 0x4f, 0x4d, 0x4c, 0x4a, 0x4a,
    0x48, 0x47, 0x46, 0x45, 0x43, 0x43, 0x41, 0x41,
};

//
// Returns nonzero on failure, having released anything it had already taken,
// so the rdp is left exactly as rdp_construct() produced it and the caller can
// simply free() it. The two acquisitions are ordered lock-then-pool for that
// reason: rdp_destroy() unconditionally destroys m_wait_lock, so it must
// never see a struct where the pool exists but the lock does not.
int rdp_init_internal_state(rdp_t *rdp)
{
    if (pthread_mutex_init(&rdp->m_wait_lock, NULL)) {
        cen64_log(CEN64_LOG_ERR, "rdp: wait lock init failed\n");
        return 1;
    }

    rdp->m_tmem_pool = (uint8_t *)calloc(TMEM_POOL_SLOTS, 0x1000);
    if (rdp->m_tmem_pool == NULL) {
        cen64_log(CEN64_LOG_ERR, "rdp: TMEM pool allocation failed (%u bytes)\n",
            (unsigned)TMEM_POOL_SLOTS * 0x1000u);
        pthread_mutex_destroy(&rdp->m_wait_lock);
        return 1;
    }
    rdp->m_tmem = rdp->m_tmem_pool;
    rdp->m_tmem_cows = 0;

    rdp_tcdiv_lut_init();

    memset(rdp->m_tiles, 0, 8 * sizeof(rdp_tile_t));
    memset(rdp->m_cmd_data, 0, sizeof(rdp->m_cmd_data));

    for (int32_t i = 0; i < 8; i++)
    {
        rdp->m_tiles[i].num = i;
        rdp->m_tiles[i].invmm = rgbaint_make(~0, ~0, ~0, ~0);
        rdp->m_tiles[i].invmask = rgbaint_make(~0, ~0, ~0, ~0);
    }

    return 0;
}

// Precondition: rdp_construct() AND rdp_init_internal_state() have both
// succeeded on this rdp. m_wait_lock is destroyed unconditionally, so this
// must not be called on a struct that never got one; the failure paths in
// rdp_render_init() free such a struct directly instead.
void rdp_destroy(rdp_t *rdp)
{
    pthread_mutex_destroy(&rdp->m_wait_lock);
    poly_manager_destroy(&rdp->m_pool);
    free(rdp->m_tmem_pool);
    rdp->m_tmem_pool = NULL;
    rdp->m_tmem = NULL;
    free(rdp->m_aux_buf);
    rdp->m_aux_buf = NULL;
}

/* ares port: the span callbacks a queued primitive can name, for save states. */
poly_render_cb const *rdp_span_callbacks(uint32_t *count)
{
    static poly_render_cb const table[4] = {
        rdp_span_draw_1cycle, rdp_span_draw_2cycle, rdp_span_draw_copy, rdp_span_draw_fill };
    *count = 4;
    return table;
}
