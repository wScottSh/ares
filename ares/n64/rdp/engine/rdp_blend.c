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

    SGI/Nintendo Reality Display Processor Blend Unit (BL)
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

******************************************************************************/

#include "rdp_blend.h"
#include "rdp_core.h"
#include "rdp_blendlut.h"

// forward declarations (file-internal)
static int32_t rdp_blender_dither_alpha(int32_t alpha, int32_t dither);
static int32_t rdp_blender_dither_color(int32_t color, int32_t dither);
static bool rdp_blender_test_for_reject(rdp_span_aux* userdata, const rdp_poly_state *object);
static bool rdp_blender_alpha_reject(rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_blender_blend_with_partial_reject(rgbaint_t *out, int32_t cycle, int32_t partialreject, int32_t select, rdp_span_aux* userdata, const rdp_poly_state *object);
static void rdp_blender_blend_pipe(const int cycle, const int special, const int final, rgbaint_t *out, rdp_span_aux* userdata, const rdp_poly_state *object);
static int32_t rdp_blender_min(const int32_t x, const int32_t min);

void rdp_blender_init(rdp_blender_t *b)
{
    for (int value = 0; value < 256; value++)
    {
        for (int dither = 0; dither < 8; dither++)
        {
            b->m_color_dither[(value << 3) | dither] = (uint8_t)rdp_blender_dither_color(value, dither);
            b->m_alpha_dither[(value << 3) | dither] = (uint8_t)rdp_blender_dither_alpha(value, dither);
        }
    }
}
static int32_t rdp_blender_dither_alpha(int32_t alpha, int32_t dither)
{
    return rdp_blender_min(alpha + dither, 0xff);
}
static int32_t rdp_blender_dither_color(int32_t color, int32_t dither)
{
    /* Round up to the next multiple of 8 iff (color & 7) > dither, saturating
     * to 255 only when that would overflow past 255 (originals in [248,255]).
     * Branchless, matching ParaLLEl-RDP rgb_dither. The MAME original tested
     * the rounded value (> 247), wrongly saturating [241,247] to 255 instead
     * of 248; only visible in 32-bit color. */
    const int32_t base     = (color & 0xf8) + 8;
    const int32_t overflow = (247 - color) >> 31;        /* ~0 if color > 247        */
    const int32_t rounded  = base + (overflow & (255 - base));
    const int32_t apply    = (dither - (color & 7)) >> 31; /* ~0 if (color & 7) > dither */
    return color + (apply & (rounded - color));
}
static bool rdp_blender_test_for_reject(rdp_span_aux* userdata, const rdp_poly_state *object)
{
    if (rdp_blender_alpha_reject(userdata, object))
    {
        return true;
    }
    if (object->m_other_modes.antialias_en ? !userdata->m_current_pix_cvg : !userdata->m_current_cvg_bit)
    {
        return true;
    }
    return false;
}
static bool rdp_blender_alpha_reject(rdp_span_aux* userdata, const rdp_poly_state *object)
{
    switch (object->m_other_modes.alpha_dither_mode)
    {
        case 0:
        case 1:
            return false;

        case 2:
            /* 2-cycle: test the cycle-0 combiner reference (see
             * m_alpha_test_ref); other cycle types test the pixel alpha
             * (dithered above by the blend cycle functions). */
            return ((object->m_other_modes.cycle_type == CYCLE_TYPE_2)
                        ? userdata->m_alpha_test_ref
                        : rgbaint_get_a(&userdata->m_pixel_color))
                   < rgbaint_get_a(&userdata->m_blend_color);

        case 3:
            /* Threshold = the pixel's noise threshold, set by the span loop
             * (rdp_noise_threshold). */
            return ((object->m_other_modes.cycle_type == CYCLE_TYPE_2)
                        ? userdata->m_alpha_test_ref
                        : rgbaint_get_a(&userdata->m_pixel_color))
                   < userdata->m_blend_noise_threshold;

        default:
            return false;
    }
}
/* One blender covering all sixteen mode combinations. The axes are
 * span-constant mode bits -- alpha_cvg_select and rgb_dither_sel --
 * plus the per-pixel blend enable, all recoverable here, so the paths
 * fold into well-predicted branches and the per-pixel call is direct
 * rather than indirect. The two entry points differ only in which
 * mux column they read and in 2-cycle's extra leading blend, so the
 * prologue and output stage are shared below; cycle is a literal at both
 * call sites. */
static inline bool rdp_blend_prologue(const rdp_blend_ctx_t *ctx, int adseed)
{
    rdp_blender_t *const b = ctx->b;
    rdp_span_aux *const ud = ctx->userdata;

    /* The dither seed is added to the pixel alpha only when that alpha comes
     * from the combiner. Coverage-derived alpha and chroma-keyed alpha both
     * arrive from their own mux leg and are passed on as they stand; the
     * seed is a combiner-path term, not a blender-input term. Shade alpha
     * takes the seed regardless of which leg fed the pixel. */
    if (!ctx->object->m_other_modes.alpha_cvg_select &&
        !ctx->object->m_other_modes.key_en)
        rgbaint_set_a(&ud->m_pixel_color, b->m_alpha_dither[((uint8_t)rgbaint_get_a(&ud->m_pixel_color) << 3) | adseed]);
    rgbaint_set_a(&ud->m_shade_color, b->m_alpha_dither[((uint8_t)rgbaint_get_a(&ud->m_shade_color) << 3) | adseed]);

    return !rdp_blender_test_for_reject(ud, ctx->object);
}

/* Final-cycle output. color_on_cvg without a coverage wrap substitutes the
 * 2A mux input as the blender output UPSTREAM of dither (ParaLLEl
 * blender.h); substituting at write time instead would bypass it. */
static inline void rdp_blend_output(const rdp_blend_ctx_t *ctx, int dith,
    const int cycle, const int select)
{
    rdp_blender_t *const b = ctx->b;
    rdp_span_aux *const ud = ctx->userdata;
    const bool cov_sub = ctx->object->m_other_modes.color_on_cvg && !ud->m_pre_wrap;
    rgbaint_t rgb;

    if (!ud->m_blend_enable)
        rgb = cov_sub
            ? *ud->m_color_inputs.blender2a_rgb[cycle]
            : *ud->m_color_inputs.blender1a_rgb[cycle];
    else if (cov_sub)
        rgb = *ud->m_color_inputs.blender2a_rgb[cycle];  /* color_on_cvg: 2A mux, pre-dither (par blender.h early return) */
    else
        rdp_blender_blend_with_partial_reject(&rgb, cycle, ctx->partialreject, select, ud, ctx->object);

    if (!(ctx->object->m_other_modes.rgb_dither_sel < 3))
    {
        rgbaint_copy(ctx->out, &rgb);
        return;
    }

    rgbaint_shl_imm(&rgb, 3);
    rgbaint_or_imm_rgba(&rgb, 0, dith & 7, (dith >> 3) & 7, (dith >> 6) & 7);  /* per-channel RGB dither (ParaLLEl packed 9-bit) */
    rgbaint_and_imm(&rgb, 0x7ff);
    rgbaint_set_rgba(ctx->out, 0, b->m_color_dither[rgbaint_get_r32(&rgb)], b->m_color_dither[rgbaint_get_g32(&rgb)], b->m_color_dither[rgbaint_get_b32(&rgb)]);
}

bool rdp_blender_cycle1(const rdp_blend_ctx_t *ctx, int dith, int adseed)
{
    if (!rdp_blend_prologue(ctx, adseed))
        return false;

    rdp_blend_output(ctx, dith, 0, ctx->sel0);
    return true;
}

bool rdp_blender_cycle2(const rdp_blend_ctx_t *ctx, int dith, int adseed)
{
    rdp_span_aux *const ud = ctx->userdata;

    if (!rdp_blend_prologue(ctx, adseed))
        return false;

    rgbaint_set_a(&ud->m_inv_pixel_color, 0xff - rgbaint_get_a(ud->m_color_inputs.blender1b_a[0]));
    rdp_blender_blend_pipe(0, ctx->sel0, 0, &ud->m_blended_pixel_color, ud, ctx->object);
    rgbaint_set_a(&ud->m_blended_pixel_color, rgbaint_get_a(&ud->m_pixel_color));

    rdp_blend_output(ctx, dith, 1, ctx->sel1);
    return true;
}
static void rdp_blender_blend_with_partial_reject(rgbaint_t *out, int32_t cycle, int32_t partialreject, int32_t select, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    if (partialreject && rgbaint_get_a(&userdata->m_pixel_color) >= 0xff)
    {
        rgbaint_copy(out, userdata->m_color_inputs.blender1a_rgb[cycle]);
    }
    else
    {
        rgbaint_set_a(&userdata->m_inv_pixel_color, 0xff - rgbaint_get_a(userdata->m_color_inputs.blender1b_a[cycle]));
        rdp_blender_blend_pipe(cycle, select, 1, out, userdata, object);
    }
}
static void rdp_blender_blend_pipe(const int cycle, const int special, const int final, rgbaint_t *out, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    /* Exact hardware blend equation, ported from ParaLLEl-RDP blender.h.
     * The alpha factors are the 8-bit inputs >> 3. When m2b selects
     * MEMORY_ALPHA (`special`), the leading factor is additionally shifted
     * by the dz-derived a-shift and masked to 0x3c, and the trailing factor
     * is shifted by the b-shift and OR'd with 3 (NOT masked -- the low bits
     * are forced on).
     *
     * blended = rgb0*a0 + rgb1*(a1 + 1)
     *
     * A NON-final cycle (the first blend of 2-cycle mode), and any cycle
     * with force_blend, resolves with a plain >>5 -- no divider. Only the
     * final cycle without force_blend applies the weighted-average divider,
     * and that divider is not a straight integer division: hardware behaves
     * like a lookup whose edge-case results follow no simple formula
     * (ParaLLEl ships it as a table; see rdp_blendlut.h). Output wraps
     * mod 256, never saturates. */
    int32_t a0 = rgbaint_get_a(userdata->m_color_inputs.blender1b_a[cycle]) >> 3;
    int32_t a1 = rgbaint_get_a(userdata->m_color_inputs.blender2b_a[cycle]) >> 3;
    if (special)
    {
        a0 = (a0 >> userdata->m_shift_a) & 0x3c;
        a1 = (a1 >> userdata->m_shift_b) | 3;
    }

    rgbaint_t temp = *userdata->m_color_inputs.blender1a_rgb[cycle];
    rgbaint_mul_imm(&temp, a0);

    rgbaint_t other = *userdata->m_color_inputs.blender2a_rgb[cycle];
    rgbaint_mul_imm(&other, a1 + 1);
    rgbaint_add(&temp, &other);

    if (!final || object->m_other_modes.force_blend)
    {
        rgbaint_shr_imm(&temp, 5);
    }
    else
    {
        const int32_t blend_sum = ((a0 >> 2) + (a1 >> 2) + 1) << 11;
        rgbaint_set_r(&temp, rdp_blender_divider_lut[blend_sum | ((rgbaint_get_r32(&temp) >> 2) & 0x7ff)]);
        rgbaint_set_g(&temp, rdp_blender_divider_lut[blend_sum | ((rgbaint_get_g32(&temp) >> 2) & 0x7ff)]);
        rgbaint_set_b(&temp, rdp_blender_divider_lut[blend_sum | ((rgbaint_get_b32(&temp) >> 2) & 0x7ff)]);
    }

    rgbaint_and_imm(&temp, 0xff);
    rgbaint_copy(out, &temp);
}
static int32_t rdp_blender_min(const int32_t x, const int32_t min)
{
    /* Branchless min(x, min): if x<min, (x-min)>>31 is -1 and we add (x-min)
     * back to min to get x; otherwise +0. Inputs are small/bounded (alpha+dither
     * vs 0xff), so x-min cannot overflow. (bithacks IntegerMinOrMax.) */
    const int32_t d = x - min;
    return min + (d & (d >> 31));
}
