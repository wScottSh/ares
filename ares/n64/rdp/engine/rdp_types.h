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

#ifndef RDP_TYPES_H
#define RDP_TYPES_H

#include <stdbool.h>
#include <stdint.h>

#include "rdp_rgba.h"

// Min/max. Typed rather than macros so arguments are evaluated once and
// the comparison's signedness is stated at the call site rather than
// falling out of the usual arithmetic conversions.
static inline int32_t rdp_min32(int32_t a, int32_t b) { return a < b ? a : b; }
static inline int32_t rdp_max32(int32_t a, int32_t b) { return a > b ? a : b; }
static inline uint32_t rdp_umin32(uint32_t a, uint32_t b) { return a < b ? a : b; }

/* The renderer state (defined in rdp_core.h). Declared here so the tag is
 * at file scope before rdp_poly.h and rdp_texpipe.h name it in prototypes;
 * a first mention inside a parameter list would scope a distinct type. */
struct rdp_t;

typedef struct misc_state_t
{
    int32_t m_fb_format;          // Framebuffer pixel format index (0 - RGBA, 1 - YUV, 2 - CI, 3 - IA, 4 - I)
    int32_t m_fb_size;            // Framebuffer pixel size index (0 - 4bpp, 1 - 8bpp, 2 - 16bpp, 3 - 32bpp)
    int32_t m_fb_width;           // Framebuffer width, in pixels
    uint32_t m_fb_address;        // Framebuffer source address offset (in bytes) from start of RDRAM

    uint32_t m_zb_address;        // Z-buffer source address offset (in bytes) from start of RDRAM

    int32_t m_ti_format;          // Format for Texture Interface (TI) transfers
    int32_t m_ti_size;            // Size (in bytes) of TI transfers
    int32_t m_ti_width;           // Width (in pixels) of TI transfers
    uint32_t m_ti_address;        // Destination address for TI transfers

    uint32_t m_max_level;         // Maximum LOD level for texture filtering
    uint32_t m_min_level;         // Minimum LOD level for texture filtering

    uint16_t m_primitive_z;       // Forced Z value for current primitive, if applicable
    uint16_t m_primitive_dz;      // Forced Delta-Z value for current primitive, if applicable
} misc_state_t;

typedef struct rdp_tile_t
{
    int32_t format; // Image data format: RGBA, YUV, CI, IA, I
    int32_t size; // Size of texel element: 4b, 8b, 16b, 32b
    int32_t line; // Size of tile line in bytes
    int32_t tmem; // Starting tmem address for this tile in bytes
    int32_t palette; // Palette number for 4b CI texels
    int32_t ct, mt, cs, ms; // Clamp / mirror enable bits for S / T direction
    int32_t mask_t, shift_t, mask_s, shift_s; // Mask values / LOD shifts
    int32_t lshift_s, rshift_s, lshift_t, rshift_t;
    int32_t wrapped_mask_s, wrapped_mask_t;
    bool clamp_s, clamp_t;
    rgbaint_t mm, invmm;
    rgbaint_t wrapped_mask;
    rgbaint_t mask;
    rgbaint_t invmask;
    rgbaint_t lshift;
    rgbaint_t rshift;
    rgbaint_t sth;
    rgbaint_t stl;
    rgbaint_t clamp_st;
    uint16_t sl, tl, sh, th;      // 10.2 fixed-point, starting and ending texel row / column
    int32_t num;
} rdp_tile_t;

typedef struct span_base_t
{
    int32_t m_span_dr;
    int32_t m_span_dg;
    int32_t m_span_db;
    int32_t m_span_da;
    int32_t m_span_ds;
    int32_t m_span_dt;
    int32_t m_span_dw;
    int32_t m_span_dsdy;
    int32_t m_span_dtdy;
    int32_t m_span_dwdy;
    int32_t m_span_dz;
    int32_t m_span_dymax;
    int32_t m_span_dzpix;
    int32_t m_span_drdy;
    int32_t m_span_dgdy;
    int32_t m_span_dbdy;
    int32_t m_span_dady;
    int32_t m_span_dzdy;
} span_base_t;

typedef struct combine_modes_t
{
    int32_t sub_a_rgb0;
    int32_t sub_b_rgb0;
    int32_t mul_rgb0;
    int32_t add_rgb0;
    int32_t sub_a_a0;
    int32_t sub_b_a0;
    int32_t mul_a0;
    int32_t add_a0;

    int32_t sub_a_rgb1;
    int32_t sub_b_rgb1;
    int32_t mul_rgb1;
    int32_t add_rgb1;
    int32_t sub_a_a1;
    int32_t sub_b_a1;
    int32_t mul_a1;
    int32_t add_a1;
} combine_modes_t;

typedef struct color_inputs_t
{
    // combiner inputs
    rgbaint_t* combiner_rgbsub_a[2];
    rgbaint_t* combiner_rgbsub_b[2];
    rgbaint_t* combiner_rgbmul[2];
    rgbaint_t* combiner_rgbadd[2];

    rgbaint_t* combiner_alphasub_a[2];
    rgbaint_t* combiner_alphasub_b[2];
    rgbaint_t* combiner_alphamul[2];
    rgbaint_t* combiner_alphaadd[2];

    // blender input
    rgbaint_t* blender1a_rgb[2];
    rgbaint_t* blender1b_a[2];
    rgbaint_t* blender2a_rgb[2];
    rgbaint_t* blender2b_a[2];
} color_inputs_t;

typedef struct other_modes_t
{
    int32_t cycle_type;
    bool atomic_prim;
    bool persp_tex_en;
    bool detail_tex_en;
    bool sharpen_tex_en;
    bool tex_lod_en;
    bool en_tlut;
    bool tlut_type;
    bool sample_type;
    bool mid_texel;
    bool bi_lerp0;
    bool bi_lerp1;
    bool convert_one;
    bool key_en;
    int32_t rgb_dither_sel;
    int32_t alpha_dither_sel;
    int32_t blend_m1a_0;
    int32_t blend_m1a_1;
    int32_t blend_m1b_0;
    int32_t blend_m1b_1;
    int32_t blend_m2a_0;
    int32_t blend_m2a_1;
    int32_t blend_m2b_0;
    int32_t blend_m2b_1;
    int32_t force_blend;
    int32_t blend_shift;
    bool alpha_cvg_select;
    bool cvg_times_alpha;
    int32_t z_mode;
    int32_t cvg_dest;
    bool color_on_cvg;
    uint8_t image_read_en;
    bool z_update_en;
    bool z_compare_en;
    bool antialias_en;
    bool z_source_sel;
    int32_t dither_alpha_en;
    int32_t alpha_compare_en;
    int32_t alpha_dither_mode;
} other_modes_t;

typedef struct rectangle_t
{
    uint16_t m_xl;    // 10.2 fixed-point
    uint16_t m_yl;    // 10.2 fixed-point
    uint16_t m_xh;    // 10.2 fixed-point
    uint16_t m_yh;    // 10.2 fixed-point
    /* Whole-pixel scissor bounds honoring the sub-pixel (10.2) fractional
     * bits: ceil of the raw value, i.e. (raw + 3) >> 2. The plain fields
     * above are the floor ((raw) >> 2), which copy/fill modes use because
     * they ignore the fractional scissor bits (n64brew: SET_SCISSOR). */
    uint16_t m_xl_clip;
    uint16_t m_yl_clip;
    uint16_t m_xh_clip;
    uint16_t m_yh_clip;
    /* Raw 10.2 scissor X bounds as delivered by SET_SCISSOR, fractional bits
     * intact. The edge walker clamps each scanline's walked edge X against
     * these at sub-pixel precision before the span bounds and coverage masks
     * are derived from it (ParaLLEl-RDP span_setup.comp clamps the quantized
     * per-subpixel X to the scissor range the same way). */
    uint16_t m_xh_raw;
    uint16_t m_xl_raw;
    /* Raw (10.2) y bounds for per-subline scissor masking in 1-/2-cycle.
     * Not serialized: the loader backfills them from the integer rows,
     * losing the fraction until the next SET_SCISSOR. */
    uint16_t m_yh_raw;
    uint16_t m_yl_raw;
    uint8_t  m_field; // SET_SCISSOR interlace field bit (bit 25); shifts dither Y
    uint8_t  m_keep_odd; // SET_SCISSOR bit 24: which line parity is kept when m_field is set
} rectangle_t;

typedef struct rdp_poly_state
{
    misc_state_t        m_misc_state;           /* miscellaneous rasterizer bits */
    other_modes_t       m_other_modes;          /* miscellaneous rasterizer bits (2) */
    span_base_t         m_span_base;            /* span initial values for triangle rasterization */
    rectangle_t         m_scissor;              /* screen-space scissor bounds */
    uint32_t              m_fill_color;           /* poly fill color */
    rdp_tile_t          m_tiles[8];             /* texture tile state */
    uint8_t               m_tmem[0x1000];         /* texture cache */
    int32_t               tilenum;                /* texture tile index */
    uint32_t              m_primitive_offset;     /* per-primitive index for the noise hash */
    /* Producer-offload snapshot: everything the worker-side span aux
     * initialization (rdp_span_aux_init) needs, captured once per
     * primitive alongside the other snapshots above so the producer's
     * per-span work shrinks to carving the slot and storing edge data. */
    combine_modes_t     m_combine;              /* combiner mux selects */
    rgbaint_t           m_blend_color;
    rgbaint_t           m_prim_color;
    rgbaint_t           m_prim_alpha;
    rgbaint_t           m_env_color;
    rgbaint_t           m_env_alpha;
    rgbaint_t           m_fog_color;
    rgbaint_t           m_key_scale;
    rgbaint_t           m_key_center;
    rgbaint_t           m_key_width;
    rgbaint_t           m_lod_fraction;
    rgbaint_t           m_prim_lod_fraction;
    rgbaint_t           m_k4;
    rgbaint_t           m_k5;
    uint8_t*            m_tmem_src;             /* this primitive's TMEM */
    int32_t             m_cvg_yh;               /* triangle subpixel Y bounds */
    int32_t             m_cvg_yl;               /*   for coverage replay */
    bool                flip;                   /* left-major / right-major flip */
    bool                rect;                   /* primitive is rectangle (vs. triangle) */
} rdp_poly_state;

#define RDP_CVG_SPAN_MAX            (1024)

// Per-span scratch. One instance is carved out of m_aux_buf per span, so
// the layout is sized for the span count, not for a single primitive.
typedef struct rdp_span_aux
{
    /* mode-3 alpha-compare threshold for the current pixel: the shared
     * per-pixel seeded noise (ParaLLEl-RDP noise_get_blend_threshold), set
     * by the span loop, consumed by the blender's alpha reject. Replaces the
     * stateful machine LFSR, which carried hidden state across primitives. */
    int32_t m_blend_noise_threshold;
    /* Alpha-compare reference for 2-cycle mode: hardware tests the CYCLE-0
     * combiner alpha (ParaLLEl-RDP combiner.h: combiner_cycle0 produces
     * alpha_test_reference; combiner_cycle1 does not), not the final
     * cycle-1 alpha. Computed by the 2-cycle span, consumed by the
     * blender's alpha reject. Unused in other cycle types. */
    int32_t m_alpha_test_ref;
    /* FILL-mode triangle burst plan: the hardware-adjudicated per-span
     * 64-bit write pattern, computed sequentially by the producer during
     * edge walking (derived from the snapper64 Fill Mode Tri hardware
     * reference captures; see fill_burst_row in rdp_core.c). Word
     * indices are 8-byte words relative to the framebuffer row base; a
     * run with lo > hi is empty. m_fill_plan == 0 selects the default
     * single-burst fill path. */
    /* DPS capture plan (rdp_dps_model_t): the 1-cycle span walk stores
     * the word image of pixels in [m_dps_cap_x0..m_dps_cap_x1] at
     * model val[x + m_dps_voff], plus the listed residual seeds.
     * m_dps_cap == 0 skips everything. */
    uint8_t             m_dps_cap;
    uint8_t             m_dps_seed_n;
    int16_t             m_dps_cap_x0;
    int16_t             m_dps_cap_x1;
    int32_t             m_dps_voff;
    int16_t             m_dps_seed_x[4];
    uint8_t             m_dps_seed_k[4];
    uint8_t             m_fill_plan;
    uint8_t             m_fill_open;    /* run1 first-word byte enables (bit 7 = byte 0) */
    uint8_t             m_fill_close;   /* run1 last-word byte enables */
    uint8_t             m_fill_pm;      /* tail partial-word byte enables (0 = none) */
    uint8_t             m_fill_t2close; /* tail full-run last-word byte enables (0xff = plain) */
    int16_t             m_fill_b1lo;    /* run1 word range */
    int16_t             m_fill_b1hi;
    int16_t             m_fill_pw;      /* tail partial word (< 0 = none) */
    int16_t             m_fill_t2lo;    /* tail full-word range */
    int16_t             m_fill_t2hi;
    uint32_t              m_unscissored_rx;
    /* Subpixel edge X values for this scanline, stored by the producer
     * during edge walking; the worker replays coverage computation from
     * them at span entry (see rdp_span_aux_init and the producer-
     * offload notes in draw_triangle). */
    int32_t             m_cvg_majorx[4];
    int32_t             m_cvg_minorx[4];
    int32_t             m_cvg_majorxint[4];
    int32_t             m_cvg_minorxint[4];
    uint16_t              m_cvg[RDP_CVG_SPAN_MAX];
    rgbaint_t           m_memory_color;
    rgbaint_t           m_pixel_color;
    rgbaint_t           m_inv_pixel_color;
    rgbaint_t           m_blended_pixel_color;

    rgbaint_t           m_combined_color;
    rgbaint_t           m_combined_alpha;
    rgbaint_t           m_texel0_color;
    rgbaint_t           m_texel0_alpha;
    rgbaint_t           m_texel1_color;
    rgbaint_t           m_texel1_alpha;
    rgbaint_t           m_next_texel_color;
    rgbaint_t           m_blend_color;          /* constant blend color */
    rgbaint_t           m_prim_color;           /* flat primitive color */
    rgbaint_t           m_prim_alpha;           /* flat primitive alpha */
    rgbaint_t           m_env_color;            /* generic color constant ('environment') */
    rgbaint_t           m_env_alpha;            /* generic alpha constant ('environment') */
    rgbaint_t           m_fog_color;            /* generic color constant ('fog') */
    rgbaint_t           m_shade_color;          /* gouraud-shaded color */
    rgbaint_t           m_shade_alpha;          /* gouraud-shaded alpha */
    rgbaint_t           m_key_scale;            /* color-keying constant */
    rgbaint_t           m_key_center;           /* color-keying center */
    rgbaint_t           m_key_width;            /* color-keying width */
    int32_t             m_keyalpha;             /* chroma key alpha for this pixel */
    rgbaint_t           m_noise_color;          /* noise */
    rgbaint_t           m_lod_fraction;         /* Z-based LOD fraction for this poly */
    rgbaint_t           m_prim_lod_fraction;    /* fixed LOD fraction for this poly */
    rgbaint_t           m_k4;
    rgbaint_t           m_k5;
    color_inputs_t      m_color_inputs;
    uint32_t              m_current_pix_cvg;
    uint32_t              m_current_mem_cvg;
    uint32_t              m_current_cvg_bit;
    int32_t               m_shift_a;
    int32_t               m_shift_b;
    int32_t               m_precomp_s;
    int32_t               m_precomp_t;
    int32_t               m_blend_enable;
    bool                m_pre_wrap;
    int32_t               m_dzpix_enc;
    uint8_t*              m_tmem;                /* pointer to texture cache for this polygon */
    rgbaint_t           m_clamp_diff[8];
    combine_modes_t     m_combine;
} rdp_span_aux;

typedef struct z_decompress_entry_t
{
    uint32_t shift;
    uint32_t add;
} z_decompress_entry_t;

typedef struct cv_mask_derivative_t
{
    uint8_t cvg;
    uint8_t cvbit;
    uint8_t xoff;
    uint8_t yoff;
} cv_mask_derivative_t;

typedef struct span_param_t
{
    union
    {
        uint32_t w;
#ifdef CEN64_BIG_ENDIAN
        struct { int16_t h; uint16_t l; } h;
#else
        struct { uint16_t l; int16_t h; } h;
#endif
    };
} span_param_t;

#endif
