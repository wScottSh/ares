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

    No angrylion source was consulted here. In this project angrylion is a
    black-box oracle only: run, observed and compared against, never read.
    None of its identifiers appear anywhere in this tree.

******************************************************************************/

#include "cen64_compat.h"
#include "rdp_texpipe.h"
#include "rdp_core.h"

_Static_assert(sizeof(unsigned) == 4, "rdp assumes 32-bit unsigned int");

/* RGBA16 -> rgbaint expansion table, and the ONLY way a 16-bit TMEM word
 * becomes an rgbaint.
 *
 * Contents depend only on the constant 5->8 bit replication ((i<<3)|(i>>2)),
 * never on renderer instance state, so it lives at file scope: this drops
 * the rdp_texpipe_t* parameter from every texel fetcher, letting all
 * six remaining arguments travel in registers through the per-pixel
 * function-pointer calls, and removes 64KB of per-instance struct
 * footprint. */
static rgbaint_t s_expand_16to32_table[0x10000];

/* Further instance-independent constants, moved to file scope for the same
 * reasons (pure functions of their index / fixed values; see init). */
static int32_t  s_maskbits_table[16];
uint16_t rdp_lod_lookup[0x80000]; /* shared with rdp_core.c */
/* Field order is a, r, g, b (see rgbaint_t). */
static const rgbaint_t s_st2_add = { 1, 0, 1, 0 };
static const rgbaint_t s_v1 = { 1, 1, 1, 1 };

/* The constant 5-bit -> 8-bit replication (v<<3)|(v>>2), duplicated from the
 * renderer instance table so the RGBA16 decode macros need no instance
 * pointer. Kept in sync by construction: both are the same pure function. */
static const uint8_t s_replicated_5to8[32] = {
    0x00,0x08,0x10,0x18,0x21,0x29,0x31,0x39,0x42,0x4a,0x52,0x5a,0x63,0x6b,0x73,0x7b,
    0x84,0x8c,0x94,0x9c,0xa5,0xad,0xb5,0xbd,0xc6,0xce,0xd6,0xde,0xe7,0xef,0xf7,0xff
};

// forward declarations (file-internal)
static void rdp_texpipe_fetch_nop(rgbaint_t* out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_mask(rgbaint_t *sstt, const rdp_tile_t *tile);
static rgbaint_t rdp_texpipe_shift_cycle(rgbaint_t *st, const rdp_tile_t *tile);
static void rdp_texpipe_shift_copy(rgbaint_t *st, const rdp_tile_t *tile);
static void rdp_texpipe_clamp_cycle(rgbaint_t *st, rgbaint_t *stfrac, rgbaint_t *maxst, const int32_t tilenum, const rdp_tile_t *tile, rdp_span_aux* userdata);
static void rdp_texpipe_clamp_cycle_light(rgbaint_t *st, rgbaint_t *maxst, const int32_t tilenum, const rdp_tile_t *tile, rdp_span_aux* userdata);
static void rdp_texpipe_cycle_nearest(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum);
static void rdp_texpipe_cycle_nearest_lerp(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum);
static void rdp_texpipe_cycle_linear_lerp(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum);
static void rdp_texpipe_fetch_rgba16_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_rgba16_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_rgba16_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_rgba32_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_rgba32_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_rgba32_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_yuv(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_yuv_cs(rgbaint_t *out, int32_t s, int32_t cs, int32_t t, int32_t tbase, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_yuv32(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci4_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci4_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci4_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci8_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci8_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci8_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia4_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia4_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia4_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia8_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia8_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia8_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia16_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia16_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ia16_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_ci32_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_i4_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_i4_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_i4_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_i8_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_i8_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);
static void rdp_texpipe_fetch_i8_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata);

void rdp_texpipe_init(rdp_texpipe_t *tp, struct rdp_t *rdp)
{
    tp->m_rdp = rdp;

    s_maskbits_table[0] = 0xffff;
    for(int i = 1; i < 16; i++)
    {
        s_maskbits_table[i] = ((uint16_t)(0xffff) >> (16 - i)) & 0x3ff;
    }

    /* ---- Texel fetch dispatch ------------------------------------------
     *
     * index = (tile.format << 4) | (tile.size << 2) | (en_tlut << 1) |
     * tlut_type, built identically at all four call sites. The two
     * en_tlut == 0 slots of a (format, size) pair hold the same direct
     * fetcher, since tlut_type only selects the palette expansion.
     *
     * The console officially supports RGBA16/32, YUV16, CI4/8, IA4/8/16
     * and I4/8 (n64brew RDP/Commands, Set Tile). Every OTHER combination
     * still decodes to something in silicon, and games do reach those
     * slots; leaving them at fetch_nop rendered nothing at all wherever
     * one was hit. They are filled here from the ParaLLEl-RDP reference
     * (MIT, shaders/texture.h sample_texture / sample_texel_*), which
     * enumerates all of them explicitly, and the cen64 fetcher named in
     * each comment is bit-identical to the ParaLLEl one it stands in for.
     *
     * Where a hole is filled with a fetcher belonging to another format,
     * that is not an approximation: the decode really is shared. TLUT
     * mode in particular ignores the tile format outright ("If tlut_en is
     * set the final texel will be sourced from a palette and the tile
     * format is ignored"), which is why the existing IA/I TLUT fetchers
     * are already byte-for-byte copies of the CI ones.
     */
    for (int32_t i = 0; i < 16*8; i++)
    {
        tp->m_texel_fetch[i] = rdp_texpipe_fetch_nop;
    }

    /* Format 0 (RGBA). Sizes 0 and 1 are not officially supported and
     * decode as plain intensity: ParaLLEl's sample_texel_rgba4 is a nibble
     * broadcast across all four lanes (== fetch_i4_raw) and its
     * sample_texel_rgba8 is a byte broadcast (== fetch_i8_raw). */
    tp->m_texel_fetch[ 0] = rdp_texpipe_fetch_i4_raw;
    tp->m_texel_fetch[ 1] = rdp_texpipe_fetch_i4_raw;
    tp->m_texel_fetch[ 2] = rdp_texpipe_fetch_ci4_tlut0;
    tp->m_texel_fetch[ 3] = rdp_texpipe_fetch_ci4_tlut1;
    tp->m_texel_fetch[ 4] = rdp_texpipe_fetch_i8_raw;
    tp->m_texel_fetch[ 5] = rdp_texpipe_fetch_i8_raw;
    tp->m_texel_fetch[ 6] = rdp_texpipe_fetch_ci8_tlut0;
    tp->m_texel_fetch[ 7] = rdp_texpipe_fetch_ci8_tlut1;
    tp->m_texel_fetch[ 8] = rdp_texpipe_fetch_rgba16_raw;
    tp->m_texel_fetch[ 9] = rdp_texpipe_fetch_rgba16_raw;
    tp->m_texel_fetch[10] = rdp_texpipe_fetch_rgba16_tlut0;
    tp->m_texel_fetch[11] = rdp_texpipe_fetch_rgba16_tlut1;
    tp->m_texel_fetch[12] = rdp_texpipe_fetch_rgba32_raw;
    tp->m_texel_fetch[13] = rdp_texpipe_fetch_rgba32_raw;
    tp->m_texel_fetch[14] = rdp_texpipe_fetch_rgba32_tlut0;
    tp->m_texel_fetch[15] = rdp_texpipe_fetch_rgba32_tlut1;

    /* Format 1 (YUV). The YUV fetcher addresses luma bytewise out of high
     * TMEM and chroma as 16-bit words out of low TMEM. Sizes 0-2 share
     * the 16-bit-rate fetcher (the TLUT path has no YUV case; ParaLLEl
     * reaches sample_texel_yuv16 for every size). Size 3 is the illegal
     * YUV/32bpp combination, addressed at 32bpp texel rate -- see
     * rdp_texpipe_fetch_yuv32. */
    for (int32_t i = 16; i < 28; i++)
        tp->m_texel_fetch[i] = rdp_texpipe_fetch_yuv;
    for (int32_t i = 28; i < 32; i++)
        tp->m_texel_fetch[i] = rdp_texpipe_fetch_yuv32;

    /* Format 2 (CI). Sizes 0 and 1 are the supported pair. Direct CI8 is a
     * byte broadcast, the same decode ParaLLEl reaches through
     * sample_texel_rgba8. Sizes 2 and 3 are unsupported and fall to the
     * split-byte fetcher; their TLUT slots take the 16-bit index form. */
    tp->m_texel_fetch[32] = rdp_texpipe_fetch_ci4_raw;
    tp->m_texel_fetch[33] = rdp_texpipe_fetch_ci4_raw;
    tp->m_texel_fetch[34] = rdp_texpipe_fetch_ci4_tlut0;
    tp->m_texel_fetch[35] = rdp_texpipe_fetch_ci4_tlut1;
    tp->m_texel_fetch[36] = rdp_texpipe_fetch_ci8_raw;
    tp->m_texel_fetch[37] = rdp_texpipe_fetch_ci8_raw;
    tp->m_texel_fetch[38] = rdp_texpipe_fetch_ci8_tlut0;
    tp->m_texel_fetch[39] = rdp_texpipe_fetch_ci8_tlut1;
    tp->m_texel_fetch[40] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[41] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[42] = rdp_texpipe_fetch_ia16_tlut0;
    tp->m_texel_fetch[43] = rdp_texpipe_fetch_ia16_tlut1;
    tp->m_texel_fetch[44] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[45] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[46] = rdp_texpipe_fetch_ia16_tlut0;
    tp->m_texel_fetch[47] = rdp_texpipe_fetch_ia16_tlut1;

    /* Format 3 (IA). Sizes 0-2 are supported; size 3 is not and takes the
     * split-byte fetcher. */
    tp->m_texel_fetch[48] = rdp_texpipe_fetch_ia4_raw;
    tp->m_texel_fetch[49] = rdp_texpipe_fetch_ia4_raw;
    tp->m_texel_fetch[50] = rdp_texpipe_fetch_ia4_tlut0;
    tp->m_texel_fetch[51] = rdp_texpipe_fetch_ia4_tlut1;
    tp->m_texel_fetch[52] = rdp_texpipe_fetch_ia8_raw;
    tp->m_texel_fetch[53] = rdp_texpipe_fetch_ia8_raw;
    tp->m_texel_fetch[54] = rdp_texpipe_fetch_ia8_tlut0;
    tp->m_texel_fetch[55] = rdp_texpipe_fetch_ia8_tlut1;
    tp->m_texel_fetch[56] = rdp_texpipe_fetch_ia16_raw;
    tp->m_texel_fetch[57] = rdp_texpipe_fetch_ia16_raw;
    tp->m_texel_fetch[58] = rdp_texpipe_fetch_ia16_tlut0;
    tp->m_texel_fetch[59] = rdp_texpipe_fetch_ia16_tlut1;
    tp->m_texel_fetch[60] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[61] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[62] = rdp_texpipe_fetch_ia16_tlut0;
    tp->m_texel_fetch[63] = rdp_texpipe_fetch_ia16_tlut1;

    /* Format 4 (I). Sizes 0 and 1 are supported; 2 and 3 are not and take
     * the split-byte fetcher. */
    tp->m_texel_fetch[64] = rdp_texpipe_fetch_i4_raw;
    tp->m_texel_fetch[65] = rdp_texpipe_fetch_i4_raw;
    tp->m_texel_fetch[66] = rdp_texpipe_fetch_i4_tlut0;
    tp->m_texel_fetch[67] = rdp_texpipe_fetch_i4_tlut1;
    tp->m_texel_fetch[68] = rdp_texpipe_fetch_i8_raw;
    tp->m_texel_fetch[69] = rdp_texpipe_fetch_i8_raw;
    tp->m_texel_fetch[70] = rdp_texpipe_fetch_i8_tlut0;
    tp->m_texel_fetch[71] = rdp_texpipe_fetch_i8_tlut1;
    tp->m_texel_fetch[72] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[73] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[74] = rdp_texpipe_fetch_ia16_tlut0;
    tp->m_texel_fetch[75] = rdp_texpipe_fetch_ia16_tlut1;
    tp->m_texel_fetch[76] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[77] = rdp_texpipe_fetch_ci32_raw;
    tp->m_texel_fetch[78] = rdp_texpipe_fetch_ia16_tlut0;
    tp->m_texel_fetch[79] = rdp_texpipe_fetch_ia16_tlut1;

    /* Formats 5-7 ARE Intensity. n64brew documents the tile and texture
     * image format field as RGBA 0, YUV 1, CI 2, IA 3, "Intensity (I) 4+"
     * -- the decoder tests the field's upper bit rather than matching an
     * exact value, so 4, 5, 6 and 7 all select the same decode. They are
     * not reserved encodings with no behaviour, and games do set them,
     * which is why the table is sized 16*8 rather than 16*5. Alias the
     * whole format-4 block rather than leaving sixteen silent holes. */
    for (int32_t i = 0; i < 16; i++)
    {
        tp->m_texel_fetch[(5 << 4) | i] = tp->m_texel_fetch[(4 << 4) | i];
        tp->m_texel_fetch[(6 << 4) | i] = tp->m_texel_fetch[(4 << 4) | i];
        tp->m_texel_fetch[(7 << 4) | i] = tp->m_texel_fetch[(4 << 4) | i];
    }

    tp->m_cycle[0] = rdp_texpipe_cycle_nearest;
    tp->m_cycle[1] = rdp_texpipe_cycle_nearest_lerp;
    /* The bi_lerp=0 (YUV convert) cycle is sample-type independent, so
     * one function serves both dispatch slots. */
    tp->m_cycle[2] = rdp_texpipe_cycle_nearest;
    tp->m_cycle[3] = rdp_texpipe_cycle_linear_lerp;

    for(int32_t i = 0; i < 0x10000; i++)
    {
        s_expand_16to32_table[i] = rgbaint_make((i & 1) ? 0xff : 0x00, s_replicated_5to8[(i >> 11) & 0x1f], s_replicated_5to8[(i >>  6) & 0x1f], s_replicated_5to8[(i >>  1) & 0x1f]);
    }

    for(uint32_t i = 0; i < 0x80000; i++)
    {
        if (i & 0x40000)
        {
            rdp_lod_lookup[i] = 0x7fff;
        }
        else if (i & 0x20000)
        {
            rdp_lod_lookup[i] = 0x8000;
        }
        else
        {
            if ((i & 0x18000) == 0x8000)
            {
                rdp_lod_lookup[i] = 0x7fff;
            }
            else if ((i & 0x18000) == 0x10000)
            {
                rdp_lod_lookup[i] = 0x8000;
            }
            else
            {
                rdp_lod_lookup[i] = i & 0xffff;
            }
        }
    }
}
static void rdp_texpipe_mask(rgbaint_t *sstt, const rdp_tile_t *tile)
{
    unsigned s_mask_bits = s_maskbits_table[tile->mask_s];
    unsigned t_mask_bits = s_maskbits_table[tile->mask_t];
    rgbaint_t maskbits = rgbaint_make(s_mask_bits, s_mask_bits, t_mask_bits, t_mask_bits);

    rgbaint_t do_wrap = *sstt;
    rgbaint_sra(&do_wrap, &tile->wrapped_mask);
    rgbaint_and_reg(&do_wrap, &s_v1);
    rgbaint_cmpeq(&do_wrap, &s_v1);
    rgbaint_and_reg(&do_wrap, &tile->mm);

    rgbaint_t wrapped = *sstt;
    rgbaint_xor_reg(&wrapped, &do_wrap);
    rgbaint_and_reg(&wrapped, &maskbits);
    rgbaint_and_reg(&wrapped, &tile->mask);
    rgbaint_and_reg(sstt, &tile->invmask);
    rgbaint_or_reg(sstt, &wrapped);
}
static rgbaint_t rdp_texpipe_shift_cycle(rgbaint_t *st, const rdp_tile_t *tile)
{
    /* HW tile-shift is two-path: shift 0-10 sign-extends then arithmetic
     * right-shifts; shift 11-15 left-shifts then treats result as 16-bit
     * signed. With lshift/rshift precomputed (one is zero per path) the
     * unified order is: left-shift, truncate to 16 bits, sign-extend at
     * bit 15, arithmetic right-shift. (rgbaint_sign_extend only ORs the
     * sign bits, so the explicit & 0xffff truncation is required.) */
    rgbaint_shl(st, &tile->lshift);
    rgbaint_and_imm(st, 0xffff);
    rgbaint_sign_extend(st, 0x00008000, 0xffff8000);
    rgbaint_sra(st, &tile->rshift);

    rgbaint_t maxst = *st;
    rgbaint_sra_imm(&maxst, 3);
    rgbaint_t maxst_eq = maxst;
    rgbaint_cmpgt(&maxst, &tile->sth);
    rgbaint_cmpeq(&maxst_eq, &tile->sth);
    rgbaint_or_reg(&maxst, &maxst_eq);

    rgbaint_t stlsb = *st;
    rgbaint_and_imm(&stlsb, 7);

    rgbaint_sra_imm(st, 3);
    rgbaint_sub(st, &tile->stl);
    rgbaint_shl_imm(st, 3);
    rgbaint_or_reg(st, &stlsb);

    return maxst;
}
static void rdp_texpipe_shift_copy(rgbaint_t *st, const rdp_tile_t *tile)
{
    /* Copy mode uses the same two-path hardware shifter as the cycle path
     * (ParaLLEl-RDP texture.h shift_coord: shift 0-10 arithmetic-right-
     * shifts the signed coordinate; shift 11-15 left-shifts and re-signs
     * at 16 bits). The previous logical shr/shl pair destroyed the sign of
     * negative coordinates, decoding huge positive texel indices for any
     * copy walk left/above the tile origin or any large tile shift. */
    rgbaint_shl(st, &tile->lshift);
    rgbaint_and_imm(st, 0xffff);
    rgbaint_sign_extend(st, 0x00008000, 0xffff8000);
    rgbaint_sra(st, &tile->rshift);
}
/* Tile clamp. stfrac is NULL on the paths with no fractional coordinate
 * (nearest sampling and copy); the two wrappers below pass it as a
 * constant so the branch folds away. */
static inline void rdp_texpipe_clamp(rgbaint_t *st, rgbaint_t *stfrac, rgbaint_t *maxst, const int32_t tilenum, const rdp_tile_t *tile, rdp_span_aux* userdata)
{
    rgbaint_t not_clamp = tile->clamp_st;
    rgbaint_xor_imm(&not_clamp, 0xffffffff);

    rgbaint_t highbit_mask = rgbaint_make(0x10000, 0x10000, 0x10000, 0x10000);
    rgbaint_t highbit = *st;
    rgbaint_and_reg(&highbit, &highbit_mask);
    rgbaint_cmpeq(&highbit, &highbit_mask);

    rgbaint_t not_highbit = highbit;
    rgbaint_xor_imm(&not_highbit, 0xffffffff);

    rgbaint_t not_maxst = *maxst;
    rgbaint_xor_imm(&not_maxst, 0xffffffff);
    rgbaint_and_reg(&not_maxst, &not_highbit);
    rgbaint_or_reg(&not_maxst, &not_clamp);

    rgbaint_t shifted_st = *st;
    rgbaint_sign_extend(&shifted_st, 0x00010000, 0xffff0000);
    rgbaint_shr_imm(&shifted_st, 5);
    rgbaint_and_imm(&shifted_st, 0x1fff);
    rgbaint_and_reg(&shifted_st, &not_maxst);
    if (stfrac != NULL)
        rgbaint_and_reg(stfrac, &not_maxst);

    rgbaint_t clamp_diff = userdata->m_clamp_diff[tilenum];
    rgbaint_and_reg(&clamp_diff, &tile->clamp_st);
    rgbaint_and_reg(&clamp_diff, maxst);

    rgbaint_copy(st, &shifted_st);
    rgbaint_or_reg(st, &clamp_diff);
}
static void rdp_texpipe_clamp_cycle(rgbaint_t *st, rgbaint_t *stfrac, rgbaint_t *maxst, const int32_t tilenum, const rdp_tile_t *tile, rdp_span_aux* userdata)
{
    rdp_texpipe_clamp(st, stfrac, maxst, tilenum, tile, userdata);
}
static void rdp_texpipe_clamp_cycle_light(rgbaint_t *st, rgbaint_t *maxst, const int32_t tilenum, const rdp_tile_t *tile, rdp_span_aux* userdata)
{
    rdp_texpipe_clamp(st, NULL, maxst, tilenum, tile, userdata);
}
/* One nearest-sampled texel: the tile and its fetcher, and the coordinate
 * after shift -> clamp -> mask with the TMEM row base it lands on. */
typedef struct
{
    const rdp_tile_t *tile;
    texel_fetcher_t   fetch;
    int32_t           s;
    int32_t           t;
    unsigned          tbase;
} rdp_nearest_sample_t;

static inline rdp_nearest_sample_t rdp_texpipe_nearest_sample(const texel_cycle_ctx_t *ctx, int32_t SSS, int32_t SST, uint32_t tilenum)
{
    const rdp_poly_state *const object = ctx->object;
    const rdp_tile_t* tile = &object->m_tiles[tilenum];
    const unsigned index = (tile->format << 4) | (tile->size << 2) | ((uint32_t) object->m_other_modes.en_tlut << 1) | (uint32_t) object->m_other_modes.tlut_type;

    rgbaint_t st = rgbaint_make(0, SSS, 0, SST);
    rgbaint_t maxst = rdp_texpipe_shift_cycle(&st, tile);
    rdp_texpipe_clamp_cycle_light(&st, &maxst, tilenum, tile, ctx->userdata);
    rdp_texpipe_mask(&st, tile);

    const rdp_nearest_sample_t smp = {
        .tile  = tile,
        .fetch = ctx->tp->m_texel_fetch[index],
        .s     = rgbaint_get_r32(&st),
        .t     = rgbaint_get_b32(&st),
        .tbase = tile->tmem + ((tile->line * rgbaint_get_b32(&st)) & 0x1ff),
    };
    return smp;
}
static cen64_flatten void rdp_texpipe_cycle_nearest(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum)
{
    rdp_texpipe_t *const tp = ctx->tp;
    const rdp_nearest_sample_t smp = rdp_texpipe_nearest_sample(ctx, SSS, SST, tilenum);

    rgbaint_t t0;
    smp.fetch(&t0, smp.s, smp.t, smp.tbase, smp.tile->palette, ctx->userdata);
    if (ctx->object->m_other_modes.convert_one && ctx->cycle)
    {
        rgbaint_copy(&t0, prev);
    }

    rgbaint_sign_extend(&t0, 0x00000100, 0xffffff00);

    rgbaint_t k13r = tp->m_rdp->m_k13;
    rgbaint_mul_imm(&k13r, rgbaint_get_r32(&t0));

    rgbaint_copy(TEX, &tp->m_rdp->m_k02);
    rgbaint_mul_imm(TEX, rgbaint_get_g32(&t0));
    rgbaint_add(TEX, &k13r);
    rgbaint_add_imm(TEX, 0x80);
    rgbaint_shr_imm(TEX, 8);
    rgbaint_add_imm(TEX, rgbaint_get_b32(&t0));
    rgbaint_and_imm(TEX, 0x1ff);
}
static cen64_flatten void rdp_texpipe_cycle_nearest_lerp(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum)
{
    (void)prev;
    const rdp_nearest_sample_t smp = rdp_texpipe_nearest_sample(ctx, SSS, SST, tilenum);

    smp.fetch(TEX, smp.s, smp.t, smp.tbase, smp.tile->palette, ctx->userdata);
}
// TMEM address swizzle, indexed by the odd/even line bit.
static const int32_t s_tex_addr_swap16[2] = { HWORD_IN_WORD_XOR, WORD_XOR_DWORD_SWAP };
static const int32_t s_tex_addr_swap8[2] = { BYTE_IN_WORD_XOR, BYTE_XOR_DWORD_SWAP };

/* --- scalar bilinear sampler: class selection and shared lerp ------
 *
 * The scalar path implements 3-point (triangular) filtering only, so
 * mid_texel (average mode) always falls through to the generic body.
 * Everything else is a property of the tile's (format, size) and the
 * TLUT mode, exactly as it is for the m_texel_fetch[] table index. */
enum {
    RDP_SCAL_NONE = 0,      /* no scalar fetcher; use generic body */
    RDP_SCAL_RGBA16,        /* fetch table rows 8/9:  rgba16_raw   */
    RDP_SCAL_CI4_T0,        /* fetch table row 34:    ci4_tlut0    */
    RDP_SCAL_CI4_T1,        /* fetch table row 35:    ci4_tlut1    */
    RDP_SCAL_CI8_T0,        /* fetch table row 38:    ci8_tlut0    */
    RDP_SCAL_CI8_T1,        /* fetch table row 39:    ci8_tlut1    */
    RDP_SCAL_CI4_RAW,       /* fetch table rows 32/33: ci4_raw     */
    RDP_SCAL_CI8_RAW,       /* rows 36/37: ci8_raw, == i8_raw      */
    RDP_SCAL_I4_RAW,        /* rows 64/65 (and 0/1, 80+): i4_raw   */
    RDP_SCAL_I8_RAW         /* rows 68/69 (and 4/5, 84+): i8_raw   */
};

static inline unsigned rdp_scal_class(const rdp_tile_t *tile,
    const other_modes_t *om)
{
    if (om->mid_texel)
        return RDP_SCAL_NONE;

    if (tile->format == 0 && tile->size == 2 && !om->en_tlut)
        return RDP_SCAL_RGBA16;   /* RGBA 16-bit, direct */

    /* Colour-indexed with TLUT. The palette lookup yields exactly the
     * 16-bit TMEM word the direct fetchers produce, so both share the
     * expansion and the lerp; only the index fetch differs. tlut_type
     * picks the expansion, matching the _tlut0 / _tlut1 split of the
     * fetch table. */
    if (tile->format == 2 && om->en_tlut) {
        if (tile->size == 0)
            return om->tlut_type ? RDP_SCAL_CI4_T1 : RDP_SCAL_CI4_T0;
        if (tile->size == 1)
            return om->tlut_type ? RDP_SCAL_CI8_T1 : RDP_SCAL_CI8_T0;
    }

    /* Broadcast formats: the fetcher yields one 8-bit value replicated
     * across all four lanes, so the lerp collapses to a single channel
     * broadcast. TLUT off; the _tlut0/_tlut1 rows of these formats keep
     * using the generic body. Note these index the FULL 4 KB TMEM
     * (mask 0xfff), unlike the TLUT paths' low 2 KB (0x7ff).
     *
     * format >= 4 rather than == 4 because 5, 6 and 7 are Intensity too
     * (n64brew: "Intensity (I) 4+"); they resolve to the same fetchers in
     * m_texel_fetch[], so this only keeps them on the fast path instead of
     * dropping them to the generic body for an identical result. */
    if (!om->en_tlut) {
        if (tile->format == 2 && tile->size == 0) return RDP_SCAL_CI4_RAW;
        if (tile->format == 2 && tile->size == 1) return RDP_SCAL_CI8_RAW;
        if (tile->format >= 4 && tile->size == 0) return RDP_SCAL_I4_RAW;
        if (tile->format >= 4 && tile->size == 1) return RDP_SCAL_I8_RAW;
    }

    return RDP_SCAL_NONE;
}

/* Triangle select shared by the three corner expansions below: up_ picks
 * the upper triangle (base T11, inverse fractions) or the lower (base
 * T00, direct fractions); k1_/k2_ are the 8.3 weights and cb_ the base
 * corner. Declares up_/k1_/k2_/cb_ in the caller's scope. */
#define RDP_SCAL_LERP_SETUP(c11_, c00_, fs_, ft_)                          \
    const int32_t up_ = -(int32_t)(((fs_) + (ft_)) >= 0x20);               \
    const int32_t k1_ = ((((0x20 - (ft_)) << 3) & up_)                     \
                      | (((fs_) << 3) & ~up_));                            \
    const int32_t k2_ = ((((0x20 - (fs_)) << 3) & up_)                     \
                      | (((ft_) << 3) & ~up_));                            \
    const int32_t cb_ = ((int32_t)(c11_) & up_)                            \
                      | ((int32_t)(c00_) & ~up_)

/* Per-channel triangular lerp:
 * ((T10 - base) * k1 + (T01 - base) * k2 + 0x80) >> 8 + base. */
#define RDP_SCAL_CH(v10_, v01_, vb_, k1_, k2_) \
    (((((v10_) - (vb_)) * (k1_) + ((v01_) - (vb_)) * (k2_) + 0x80) >> 8) + (vb_))

/* Branchless triangle select and per-channel triangular lerp, shared by
 * every scalar fetcher whose corners are RGBA5551 TMEM words. Upper
 * triangle uses base T11 with inverse fractions, lower uses base T00
 * with direct fractions; the selected values are identical to the
 * branchy form. Channels expand through the 32-byte 5-to-8 table. */
#define RDP_SCAL_LERP_RGBA16(TEX_, c10_, c01_, c11_, c00_, fs_, ft_)   \
    do {                                                                   \
        RDP_SCAL_LERP_SETUP((c11_), (c00_), (fs_), (ft_));                 \
        const int32_t ab_ = -(int32_t)(cb_ & 1) & 0xff;                    \
        const int32_t rb_ = s_replicated_5to8[(cb_ >> 11) & 0x1f];         \
        const int32_t gb_ = s_replicated_5to8[(cb_ >>  6) & 0x1f];         \
        const int32_t bb_ = s_replicated_5to8[(cb_ >>  1) & 0x1f];         \
        (TEX_)->m_a = RDP_SCAL_CH(-(int32_t)((c10_) & 1) & 0xff,       \
            -(int32_t)((c01_) & 1) & 0xff, ab_, k1_, k2_);                 \
        (TEX_)->m_r = RDP_SCAL_CH(                                     \
            s_replicated_5to8[((c10_) >> 11) & 0x1f],                      \
            s_replicated_5to8[((c01_) >> 11) & 0x1f], rb_, k1_, k2_);      \
        (TEX_)->m_g = RDP_SCAL_CH(                                     \
            s_replicated_5to8[((c10_) >>  6) & 0x1f],                      \
            s_replicated_5to8[((c01_) >>  6) & 0x1f], gb_, k1_, k2_);      \
        (TEX_)->m_b = RDP_SCAL_CH(                                     \
            s_replicated_5to8[((c10_) >>  1) & 0x1f],                      \
            s_replicated_5to8[((c01_) >>  1) & 0x1f], bb_, k1_, k2_);      \
    } while (0)

/* Single-channel corners replicated across all four lanes: the untabled
 * CI4/CI8/I4/I8 fetchers, each of which does rgbaint_set_rgba(c,c,c,c).
 * The lerp is evaluated once and broadcast. */
#define RDP_SCAL_LERP_REPL(TEX_, c10_, c01_, c11_, c00_, fs_, ft_)     \
    do {                                                                   \
        RDP_SCAL_LERP_SETUP((c11_), (c00_), (fs_), (ft_));                 \
        const int32_t v_ = RDP_SCAL_CH((c10_), (c01_), cb_, k1_, k2_); \
        (TEX_)->m_a = v_;                                                  \
        (TEX_)->m_r = v_;                                                  \
        (TEX_)->m_g = v_;                                                  \
        (TEX_)->m_b = v_;                                                  \
    } while (0)

/* IA16 expansion of the same corners, for tlut_type 1: alpha is the low
 * byte and intensity the high byte replicated across RGB (the _tlut1
 * fetchers). The three colour lanes carry identical values, so the
 * channel lerp is evaluated once and broadcast. */
#define RDP_SCAL_LERP_IA16(TEX_, c10_, c01_, c11_, c00_, fs_, ft_)     \
    do {                                                                   \
        RDP_SCAL_LERP_SETUP((c11_), (c00_), (fs_), (ft_));                 \
        const int32_t iv_ = RDP_SCAL_CH(((c10_) >> 8) & 0xff,          \
            ((c01_) >> 8) & 0xff, (cb_ >> 8) & 0xff, k1_, k2_);            \
        (TEX_)->m_a = RDP_SCAL_CH((c10_) & 0xff, (c01_) & 0xff,        \
            cb_ & 0xff, k1_, k2_);                                         \
        (TEX_)->m_r = iv_;                                                 \
        (TEX_)->m_g = iv_;                                                 \
        (TEX_)->m_b = iv_;                                                 \
    } while (0)

static cen64_flatten void rdp_texpipe_cycle_linear_lerp(const texel_cycle_ctx_t *ctx, rgbaint_t* TEX, rgbaint_t* prev, int32_t SSS, int32_t SST, uint32_t tilenum)
{
    (void)prev;
    rdp_texpipe_t *const tp = ctx->tp;
    rdp_span_aux *const userdata = ctx->userdata;
    const rdp_poly_state *const object = ctx->object;
    const rdp_tile_t* tile = &object->m_tiles[tilenum];

    /* Scalar bilinear sampler classes. The guarded path below is a
     * transplant of the generic body's pipeline (shift_cycle ->
     * clamp_cycle -> +s_st2_add -> mask -> fetch x4 -> triangular lerp)
     * with the rgbaint helpers replaced by per-axis scalar arithmetic
     * mirroring their exact lane semantics on the (a,r)=S / (g,b)=T
     * packing set_tile builds.
     *
     * Only the four-corner FETCH is format specific. The coordinate
     * skeleton and the triangular lerp are not, and every fetcher that
     * yields a 16-bit TMEM word shares one of two expansions. Class
     * selection is loop-invariant per tile; it is written as a switch
     * so that adding a fetcher does not touch the skeleton.
     *
     * prev/cycle are not consumed by either body (no convert path at
     * bi_lerp=1), so the scalar path is valid for every caller, both
     * cycle modes included. */
    const unsigned scal = rdp_scal_class(tile, &object->m_other_modes);
    if (scal != RDP_SCAL_NONE)
    {
        /* Coordinate skeleton: format independent. */
        const uint32_t lsh_s = (uint32_t)tile->lshift.m_r & 31u, lsh_t = (uint32_t)tile->lshift.m_b & 31u;
        const int32_t  rsh_s = ((uint32_t)tile->rshift.m_r > 31) ? 31 : tile->rshift.m_r;
        const int32_t  rsh_t = ((uint32_t)tile->rshift.m_b > 31) ? 31 : tile->rshift.m_b;
        const int32_t  cl_s  = tile->clamp_st.m_r, cl_t = tile->clamp_st.m_b;    /* ~0 / 0 */
        const int32_t  mm_s  = tile->mm.m_r,       mm_t = tile->mm.m_b;          /* mirror ~0 / 0 */
        const int32_t  wm_s  = tile->wrapped_mask.m_r, wm_t = tile->wrapped_mask.m_b;
        const int32_t  mb_s  = s_maskbits_table[tile->mask_s];
        const int32_t  mb_t  = s_maskbits_table[tile->mask_t];
        const int32_t  km_s  = tile->mask.m_r,     km_t = tile->mask.m_b;        /* ~0 / 0 */
        const int32_t  im_s  = tile->invmask.m_r,  im_t = tile->invmask.m_b;     /* ~0 / 0 */

        /* shift_cycle: <<lshift, truncate to 16 bits, sign-extend at
         * bit 15, arithmetic >>rshift; footprint max flag; tile-origin
         * rebase keeping the 3 subtexel LSBs. */
        int32_t s = (int32_t)(int16_t)(uint16_t)((uint32_t)SSS << lsh_s);
        int32_t t = (int32_t)(int16_t)(uint16_t)((uint32_t)SST << lsh_t);
        s >>= rsh_s;
        t >>= rsh_t;
        const int32_t max_s = -(int32_t)((s >> 3) >= tile->sth.m_r);
        const int32_t max_t = -(int32_t)((t >> 3) >= tile->sth.m_b);
        const int32_t lsb_s = s & 7, lsb_t = t & 7;
        s = (int32_t)(((uint32_t)((s >> 3) - tile->stl.m_r)) << 3) | lsb_s;
        t = (int32_t)(((uint32_t)((t >> 3) - tile->stl.m_b)) << 3) | lsb_t;

        /* 5-bit bilinear fraction, taken before the clamp */
        int32_t f_s = s & 0x1f, f_t = t & 0x1f;

        /* clamp_cycle */
        const int32_t hb_s = -(int32_t)((s & 0x10000) != 0);
        const int32_t hb_t = -(int32_t)((t & 0x10000) != 0);
        const int32_t nm_s = (~max_s & ~hb_s) | ~cl_s;
        const int32_t nm_t = (~max_t & ~hb_t) | ~cl_t;
        const int32_t sc_s = (int32_t)((((uint32_t)s | (0xffff0000u & (uint32_t)hb_s)) >> 5) & 0x1fff);
        const int32_t sc_t = (int32_t)((((uint32_t)t | (0xffff0000u & (uint32_t)hb_t)) >> 5) & 0x1fff);
        const int32_t cs0 = (sc_s & nm_s) | (userdata->m_clamp_diff[tilenum].m_r & cl_s & max_s);
        const int32_t ct0 = (sc_t & nm_t) | (userdata->m_clamp_diff[tilenum].m_b & cl_t & max_t);
        f_s &= nm_s;
        f_t &= nm_t;

        /* corner coordinates (s_st2_add) then per-value mask/mirror */
        int32_t ms0 = cs0, ms1 = cs0 + 1, mt0 = ct0, mt1 = ct0 + 1;
#define RDP_MASKV(v, wm, mmv, mbits, kmask, iv) do {                     \
            const int32_t dw_ = (-(int32_t)(((v) >> (wm)) & 1)) & (mmv); \
            const int32_t wr_ = (((v) ^ dw_) & (mbits)) & (kmask);       \
            (v) = ((v) & (iv)) | wr_;                                    \
        } while (0)
        RDP_MASKV(ms0, wm_s, mm_s, mb_s, km_s, im_s);
        RDP_MASKV(ms1, wm_s, mm_s, mb_s, km_s, im_s);
        RDP_MASKV(mt0, wm_t, mm_t, mb_t, km_t, im_t);
        RDP_MASKV(mt1, wm_t, mm_t, mb_t, km_t, im_t);
#undef RDP_MASKV

        const int32_t tb1 = tile->tmem + ((tile->line * mt0) & 0x1ff);
        const int32_t tb2 = tile->tmem + ((tile->line * mt1) & 0x1ff);

        /* Byte-swap selectors: a property of the T parity, shared by
         * every fetcher. */
        const uint32_t sw0 = (uint32_t)s_tex_addr_swap16[mt0 & 1];
        const uint32_t sw1 = (uint32_t)s_tex_addr_swap16[mt1 & 1];

        /* Corner fetch (T10, T01, T11, T00): the only format-specific
         * step. Each arm yields the same four 16-bit TMEM words the
         * corresponding m_texel_fetch[] entry would produce. */
        uint16_t c10, c01, c11, c00;

        switch (scal)
        {
        case RDP_SCAL_RGBA16:
        default:
        {
            const uint16_t *const tm16 = (const uint16_t *)userdata->m_tmem;
            c10 = tm16[((((uint32_t)tb1 << 2) + (uint32_t)ms1) ^ sw0) & 0x7ff];
            c01 = tm16[((((uint32_t)tb2 << 2) + (uint32_t)ms0) ^ sw1) & 0x7ff];
            c11 = tm16[((((uint32_t)tb2 << 2) + (uint32_t)ms1) ^ sw1) & 0x7ff];
            c00 = tm16[((((uint32_t)tb1 << 2) + (uint32_t)ms0) ^ sw0) & 0x7ff];
            break;
        }

        case RDP_SCAL_CI4_T0:
        case RDP_SCAL_CI4_T1:
        {
            /* fetch_ci4_tlut0/1: nibble index out of low TMEM at the
             * 4bpp stride, palette lookup into high TMEM at 0x800 with
             * the quadrupled TLUT stride. */
            const uint8_t *const tc = userdata->m_tmem;
            const uint16_t *const tl = (const uint16_t *)(userdata->m_tmem + 0x800);
            const int32_t p8_0 = s_tex_addr_swap8[mt0 & 1];
            const int32_t p8_1 = s_tex_addr_swap8[mt1 & 1];
            const uint32_t pal = (uint32_t)tile->palette;
/* The >> 1 is an ARITHMETIC shift in the reference fetcher: taddr is
 * built from int32_t operands there. Keep the operand signed -- a
 * uint32_t cast would make it logical and diverge for any negative
 * intermediate. */
#define RDP_SCAL_CI4A(tb_, s_, sw_) \
    ((uint32_t)(((((tb_) << 4) + (s_)) >> 1) ^ (int32_t)(sw_)) & 0x7ffu)
#define RDP_SCAL_CI4(tb_, s_, sw_, k_) (tl[(((pal << 4) | (((s_) & 1)  \
    ? (tc[RDP_SCAL_CI4A(tb_, s_, sw_)] & 0xf)                          \
    : (tc[RDP_SCAL_CI4A(tb_, s_, sw_)] >> 4))) << 2) ^ (k_)])
            /* TLUT accessor banks: see the CI8 arm below. */
            { const unsigned ax = ((f_s + f_t) >= 0x20) ? 2u : 1u;
            c10 = RDP_SCAL_CI4(tb1, ms1, p8_0, 1u ^ ax);
            c01 = RDP_SCAL_CI4(tb2, ms0, p8_1, 2u ^ ax);
            c11 = RDP_SCAL_CI4(tb2, ms1, p8_1, 3u ^ ax);
            c00 = RDP_SCAL_CI4(tb1, ms0, p8_0, 0u ^ ax); }
#undef RDP_SCAL_CI4
#undef RDP_SCAL_CI4A
            break;
        }

        case RDP_SCAL_CI8_T0:
        case RDP_SCAL_CI8_T1:
        {
            /* fetch_ci8_tlut0/1: byte index, same palette lookup. */
            const uint8_t *const tc = userdata->m_tmem;
            const uint16_t *const tl = (const uint16_t *)(userdata->m_tmem + 0x800);
            const int32_t p8_0 = s_tex_addr_swap8[mt0 & 1];
            const int32_t p8_1 = s_tex_addr_swap8[mt1 & 1];
#define RDP_SCAL_CI8(tb_, s_, sw_, k_) (tl[((uint32_t)tc[          \
    (uint32_t)((((tb_) << 3) + (s_)) ^ (int32_t)(sw_)) & 0x7ffu] << 2) ^ (k_)])
            /* TLUT accessor banks: the four bilinear corners read the
             * quadruplicated palette entry from distinct 16-bit slots,
             * (entry << 2) + role with role c00/c10/c01/c11 = 0/1/2/3,
             * all XORed with 2 on the upper bilinear triangle and 1 on
             * the lower. This 16-bit view's element indices already carry
             * the halfword byte-order XOR, which cancels the physical-slot
             * conversion and leaves role ^ diagonal directly. A
             * Load-Tlut-replicated palette makes every slot equal, so the
             * selection is invisible in ordinary content; PRDP 3:5
             * adjudicates it against an unreplicated one. */
            { const unsigned ax = ((f_s + f_t) >= 0x20) ? 2u : 1u;
            c10 = RDP_SCAL_CI8(tb1, ms1, p8_0, 1u ^ ax);
            c01 = RDP_SCAL_CI8(tb2, ms0, p8_1, 2u ^ ax);
            c11 = RDP_SCAL_CI8(tb2, ms1, p8_1, 3u ^ ax);
            c00 = RDP_SCAL_CI8(tb1, ms0, p8_0, 0u ^ ax); }
#undef RDP_SCAL_CI8
            break;
        }

        case RDP_SCAL_CI4_RAW:
        case RDP_SCAL_CI8_RAW:
        case RDP_SCAL_I4_RAW:
        case RDP_SCAL_I8_RAW:
        {
            /* fetch_ci4_raw / ci8_raw / i4_raw / i8_raw. The >> 1 in the
             * 4bpp address is arithmetic in the reference fetchers, so
             * the operand stays signed. */
            const uint8_t *const tc = userdata->m_tmem;
            const int32_t p8_0 = s_tex_addr_swap8[mt0 & 1];
            const int32_t p8_1 = s_tex_addr_swap8[mt1 & 1];
            const uint32_t pal4 = ((uint32_t)tile->palette & 0xfu) << 4;
            const int nib = (scal == RDP_SCAL_CI4_RAW
                          || scal == RDP_SCAL_I4_RAW);
            const int isi4 = (scal == RDP_SCAL_I4_RAW);
#define RDP_SCAL_RAWA4(tb_, s_, sw_) \
    ((uint32_t)(((((tb_) << 4) + (s_)) >> 1) ^ (int32_t)(sw_)) & 0xfffu)
#define RDP_SCAL_RAWA8(tb_, s_, sw_) \
    ((uint32_t)((((tb_) << 3) + (s_)) ^ (int32_t)(sw_)) & 0xfffu)
#define RDP_SCAL_RAW(tb_, s_, sw_) (nib                                \
    ? (isi4                                                                \
        ? (((((s_) & 1) ? (tc[RDP_SCAL_RAWA4(tb_, s_, sw_)] & 0xfu)    \
                        : ((tc[RDP_SCAL_RAWA4(tb_, s_, sw_)] >> 4)     \
                           & 0xfu)))                                       \
           | ((((s_) & 1) ? (tc[RDP_SCAL_RAWA4(tb_, s_, sw_)] & 0xfu)  \
                          : ((tc[RDP_SCAL_RAWA4(tb_, s_, sw_)] >> 4)   \
                             & 0xfu)) << 4))                               \
        : (pal4 | (((s_) & 1) ? (tc[RDP_SCAL_RAWA4(tb_, s_, sw_)] & 0xfu) \
                              : (tc[RDP_SCAL_RAWA4(tb_, s_, sw_)] >> 4))))  \
    : (uint32_t)tc[RDP_SCAL_RAWA8(tb_, s_, sw_)])
            c10 = (uint16_t)RDP_SCAL_RAW(tb1, ms1, p8_0);
            c01 = (uint16_t)RDP_SCAL_RAW(tb2, ms0, p8_1);
            c11 = (uint16_t)RDP_SCAL_RAW(tb2, ms1, p8_1);
            c00 = (uint16_t)RDP_SCAL_RAW(tb1, ms0, p8_0);
#undef RDP_SCAL_RAW
#undef RDP_SCAL_RAWA8
#undef RDP_SCAL_RAWA4
            break;
        }
        }

        if (scal >= RDP_SCAL_CI4_RAW)
            RDP_SCAL_LERP_REPL(TEX, c10, c01, c11, c00, f_s, f_t);
        else if (scal == RDP_SCAL_CI4_T1 || scal == RDP_SCAL_CI8_T1)
            RDP_SCAL_LERP_IA16(TEX, c10, c01, c11, c00, f_s, f_t);
        else
            RDP_SCAL_LERP_RGBA16(TEX, c10, c01, c11, c00, f_s, f_t);
        return;
    }

    unsigned tpal = tile->palette;
    unsigned index = (tile->format << 4) | (tile->size << 2) | ((uint32_t) object->m_other_modes.en_tlut << 1) | (uint32_t) object->m_other_modes.tlut_type;
    const texel_fetcher_t texel_fetch = tp->m_texel_fetch[index];

    rgbaint_t sstt = rgbaint_make(SSS, SSS, SST, SST);
    rgbaint_t maxst = rdp_texpipe_shift_cycle(&sstt, tile);
    rgbaint_t stfrac = sstt;
    rgbaint_and_imm(&stfrac, 0x1f);

    rdp_texpipe_clamp_cycle(&sstt, &stfrac, &maxst, tilenum, tile, userdata);

    rgbaint_add(&sstt, &s_st2_add);

    rdp_texpipe_mask(&sstt, tile);

    const unsigned tbase1 = tile->tmem + ((tile->line * rgbaint_get_b32(&sstt)) & 0x1ff);
    const unsigned tbase2 = tile->tmem + ((tile->line * rgbaint_get_g32(&sstt)) & 0x1ff);

    bool upper = ((rgbaint_get_r32(&stfrac) + rgbaint_get_b32(&stfrac)) >= 0x20);

    rgbaint_t invstf = stfrac;
    if (upper)
    {
        rgbaint_subr_imm(&invstf, 0x20);
        rgbaint_shl_imm(&invstf, 3);
    }

    rgbaint_shl_imm(&stfrac, 3);

    /* stfrac was shifted left by 3 above to form the 8-bit bilinear lerp
     * weight (raw 5-bit fraction x 8). The mid-texel center is the exact
     * texel centre, raw fraction 0x10 (0.5); in this shifted representation
     * that is 0x10 << 3 = 0x80 (cf. ParaLLEl-RDP texture.h, which tests the
     * raw fraction == 0x10 before the >>5). The previous 0x10 compared the
     * shifted weight and so fired at raw fraction 2, missing the true centre
     * -- only observable when perspective division lands S and T exactly on
     * 0.5 together (linear interpolation effectively never does).
     */
    bool center = (rgbaint_get_r32(&stfrac) == 0x80) && (rgbaint_get_b32(&stfrac) == 0x80) && object->m_other_modes.mid_texel;

    /* YUV (format 1): chroma (U,V) and luma (Y) are filtered as two
     * independent 3-tap triangular planes. Luma uses the ordinary
     * (f_s, f_t) pair; chroma's S fraction runs at half rate with the
     * base column's S parity folded in as its top bit, f_c =
     * ((s0 & 1) << 4) | (f_s >> 1), and picks its own diagonal by
     * f_c + f_t. The far column's chroma pair is addressed one step
     * ahead of the base pair, cs1 = 2*s1 - s0. Mid-texel averaging
     * applies per plane on its own fraction pair, and taps are widened
     * to signed before the plane arithmetic. ParaLLEl-RDP texture.h
     * sample_texture / bilinear_3tap; PRDP 11:45 adjudicates the
     * 2-cycle bilinear convert_one configuration. */
    if (tile->format == 1u)
    {
        const int32_t s0 = rgbaint_get_r32(&sstt), s1 = rgbaint_get_a32(&sstt);
        const int32_t yt0 = rgbaint_get_b32(&sstt), yt1 = rgbaint_get_g32(&sstt);
        const int32_t f_s = rgbaint_get_r32(&stfrac) >> 3;   /* raw 5-bit */
        const int32_t f_t = rgbaint_get_b32(&stfrac) >> 3;
        const int32_t f_c = ((s0 & 1) << 4) | (f_s >> 1);
        const int32_t cs1 = 2 * s1 - s0;

        rgbaint_t q00, q10, q01, q11;
        if (tile->size == 3u)
        {
            /* 32bpp-rate addressing binds chroma to the texel pair, so
             * the extrapolated chroma column (cs1) has no meaning here:
             * each tap applies the size-3 law at its own s. The point
             * path is adjudicated (PRDP 5:0); this bilinear arrangement
             * is the consistent extension, with no hardware capture yet. */
            rdp_texpipe_fetch_yuv32(&q00, s0, yt0, (int32_t)tbase1, 0, userdata);
            rdp_texpipe_fetch_yuv32(&q10, s1, yt0, (int32_t)tbase1, 0, userdata);
            rdp_texpipe_fetch_yuv32(&q01, s0, yt1, (int32_t)tbase2, 0, userdata);
            rdp_texpipe_fetch_yuv32(&q11, s1, yt1, (int32_t)tbase2, 0, userdata);
        }
        else
        {
            rdp_texpipe_fetch_yuv_cs(&q00, s0, s0,  yt0, (int32_t)tbase1, userdata);
            rdp_texpipe_fetch_yuv_cs(&q10, s1, cs1, yt0, (int32_t)tbase1, userdata);
            rdp_texpipe_fetch_yuv_cs(&q01, s0, s0,  yt1, (int32_t)tbase2, userdata);
            rdp_texpipe_fetch_yuv_cs(&q11, s1, cs1, yt1, (int32_t)tbase2, userdata);
        }

#define RDP_YUV_SX9(x) ((int32_t)((uint32_t)(x) << 23) >> 23)
        const int32_t u00 = RDP_YUV_SX9(rgbaint_get_r32(&q00)), v00 = RDP_YUV_SX9(rgbaint_get_g32(&q00)), y00 = rgbaint_get_b32(&q00);
        const int32_t u10 = RDP_YUV_SX9(rgbaint_get_r32(&q10)), v10 = RDP_YUV_SX9(rgbaint_get_g32(&q10)), y10 = rgbaint_get_b32(&q10);
        const int32_t u01 = RDP_YUV_SX9(rgbaint_get_r32(&q01)), v01 = RDP_YUV_SX9(rgbaint_get_g32(&q01)), y01 = rgbaint_get_b32(&q01);
        const int32_t u11 = RDP_YUV_SX9(rgbaint_get_r32(&q11)), v11 = RDP_YUV_SX9(rgbaint_get_g32(&q11)), y11 = rgbaint_get_b32(&q11);
#undef RDP_YUV_SX9

        int32_t uo, vo, yo;
        const bool mid_l = object->m_other_modes.mid_texel && f_s == 0x10 && f_t == 0x10;
        const bool mid_c = object->m_other_modes.mid_texel && f_c == 0x10 && f_t == 0x10;

        if (mid_l)
            yo = (y00 + y10 + y01 + y11 + 2) >> 2;
        else if (f_s + f_t >= 0x20)
            yo = (((y10 - y11) * ((0x20 - f_t) << 3) + (y01 - y11) * ((0x20 - f_s) << 3) + 0x80) >> 8) + y11;
        else
            yo = (((y10 - y00) * (f_s << 3) + (y01 - y00) * (f_t << 3) + 0x80) >> 8) + y00;

        if (mid_c)
        {
            uo = (u00 + u10 + u01 + u11 + 2) >> 2;
            vo = (v00 + v10 + v01 + v11 + 2) >> 2;
        }
        else if (f_c + f_t >= 0x20)
        {
            uo = (((u10 - u11) * ((0x20 - f_t) << 3) + (u01 - u11) * ((0x20 - f_c) << 3) + 0x80) >> 8) + u11;
            vo = (((v10 - v11) * ((0x20 - f_t) << 3) + (v01 - v11) * ((0x20 - f_c) << 3) + 0x80) >> 8) + v11;
        }
        else
        {
            uo = (((u10 - u00) * (f_c << 3) + (u01 - u00) * (f_t << 3) + 0x80) >> 8) + u00;
            vo = (((v10 - v00) * (f_c << 3) + (v01 - v00) * (f_t << 3) + 0x80) >> 8) + v00;
        }

        rgbaint_set_rgba(TEX, yo, uo, vo, yo);
        return;
    }

    rgbaint_t t2;
    texel_fetch(TEX, rgbaint_get_a32(&sstt), rgbaint_get_b32(&sstt), tbase1, tpal, userdata);
    texel_fetch(&t2, rgbaint_get_r32(&sstt), rgbaint_get_g32(&sstt), tbase2, tpal, userdata);

    if (!center)
    {
        if (upper)
        {
            rgbaint_t t3;
            texel_fetch(&t3, rgbaint_get_a32(&sstt), rgbaint_get_g32(&sstt), tbase2, tpal, userdata);

            rgbaint_sub(TEX, &t3);
            rgbaint_sub(&t2, &t3);

            rgbaint_mul_imm(TEX, rgbaint_get_b32(&invstf));
            rgbaint_mul_imm(&t2, rgbaint_get_r32(&invstf));

            rgbaint_add(TEX, &t2);
            rgbaint_add_imm(TEX, 0x0080);
            rgbaint_sra_imm(TEX, 8);
            rgbaint_add(TEX, &t3);
        }
        else
        {
            rgbaint_t t0;
            texel_fetch(&t0, rgbaint_get_r32(&sstt), rgbaint_get_b32(&sstt), tbase1, tpal, userdata);

            rgbaint_sub(TEX, &t0);
            rgbaint_sub(&t2, &t0);

            rgbaint_mul_imm(TEX, rgbaint_get_r32(&stfrac));
            rgbaint_mul_imm(&t2, rgbaint_get_b32(&stfrac));

            rgbaint_add(TEX, &t2);
            rgbaint_add_imm(TEX, 0x80);
            rgbaint_sra_imm(TEX, 8);
            rgbaint_add(TEX, &t0);
        }
    }
    else
    {
        rgbaint_t t0, t3;
        texel_fetch(&t0, rgbaint_get_r32(&sstt), rgbaint_get_b32(&sstt), tbase1, tpal, userdata);
        texel_fetch(&t3, rgbaint_get_a32(&sstt), rgbaint_get_g32(&sstt), tbase2, tpal, userdata);
        rgbaint_add(TEX, &t0);
        rgbaint_add(TEX, &t2);
        rgbaint_add(TEX, &t3);
        /* Box filter is a rounded 4-tap average: (t00+t10+t01+t11+2)>>2
         * (cf. ParaLLEl-RDP texture.h). The previous truncating >>2 dropped
         * the +2 round-to-nearest term.
         */
        rgbaint_add_imm(TEX, 2);
        rgbaint_sra_imm(TEX, 2);
    }
}
/* Resolve the span's fixed tile and fetcher. Called once per copy span. */
void rdp_texpipe_copy_ctx_init(rdp_copy_ctx_t *ctx, rdp_texpipe_t *tp,
    const rdp_poly_state *object, rdp_span_aux *userdata, rgbaint_t *out,
    uint32_t tilenum)
{
    const rdp_tile_t *const tile = &object->m_tiles[tilenum];
    const unsigned index = (tile->format << 4) | (tile->size << 2)
        | ((uint32_t)object->m_other_modes.en_tlut << 1)
        | (uint32_t)object->m_other_modes.tlut_type;

    ctx->tp       = tp;
    ctx->object   = object;
    ctx->userdata = userdata;
    ctx->tile     = tile;
    ctx->fetch    = tp->m_texel_fetch[index];
    ctx->out      = out;
}

cen64_flatten void rdp_texpipe_copy(const rdp_copy_ctx_t *ctx, int32_t sss,
    int32_t sst, int32_t s_offset)
{
    const rdp_tile_t *const tile = ctx->tile;

    rgbaint_t st = rgbaint_make(0, sss, 0, sst);
    rdp_texpipe_shift_copy(&st, tile);
    rgbaint_t stlsb = st;
    rgbaint_and_imm(&stlsb, 7);
    /* The tile-origin subtraction happens in texel space, so this >>3 must
     * be arithmetic to preserve negative coordinates (ParaLLEl shift_coord
     * subtracts lo<<3 on the signed coordinate; (x>>3 - lo)<<3 | (x&7) is
     * only equivalent when >>3 floors). The final >>5 below is shift-type
     * agnostic thanks to the & 0x1fff mask. */
    rgbaint_sra_imm(&st, 3);
    const rgbaint_t st_sl_tl = rgbaint_make(0, tile->sl, 0, tile->tl);
    rgbaint_sub(&st, &st_sl_tl);
    rgbaint_shl_imm(&st, 3);
    rgbaint_add(&st, &stlsb);
    rgbaint_sign_extend(&st, 0x00010000, 0xffff0000);
    rgbaint_shr_imm(&st, 5);
    rgbaint_and_imm(&st, 0x1fff);
    /* the pixel's in-group texel offset applies AFTER the tile shift, in
     * texel space, before masking (ParaLLEl-RDP sample_texture_copy:
     * st.x += s_offset after shift_coord and >>5) */
    {
        rgbaint_t s_off = rgbaint_make(0, s_offset, 0, 0);
        rgbaint_add(&st, &s_off);
    }
    rdp_texpipe_mask(&st, tile);

    const unsigned tbase = tile->tmem + ((tile->line * rgbaint_get_b32(&st)) & 0x1ff);

    ctx->fetch(ctx->out, rgbaint_get_r32(&st), rgbaint_get_b32(&st), tbase,
        tile->palette, ctx->userdata);
}
/* Consolidation of the former lod_1cycle / lod_2cycle /
 * lod_2cycle_limited triplet: an identical coordinate/footprint core
 * with three mode-gated deviations (the 1-cycle need_lod early-out,
 * the per-pixel LOD-fraction/precomp side effects, and whether the
 * second tile is produced). mode is constant at every call site, so
 * the gates are perfectly predicted; one outlined body replaces three.
 * TEXPIPE_LOD_PEEK is the next-pixel probe form: no userdata side
 * effects (ctx->userdata is NULL there). */
cen64_flatten void rdp_texpipe_lod(const rdp_lod_ctx_t *ctx, const int32_t s,
    const int32_t t, const int32_t w, const int mode)
{
    rdp_texpipe_t        *const tp        = ctx->tp;
    const rdp_poly_state *const object    = ctx->object;
    rdp_span_aux         *const userdata  = ctx->userdata;
    rdp_lod_stash        *const stash     = ctx->stash;
    int32_t              *const sss       = ctx->sss;
    int32_t              *const sst       = ctx->sst;
    int32_t              *const t1        = ctx->t1;
    int32_t              *const t2        = ctx->t2;
    const int32_t               dsinc     = ctx->dsinc;
    const int32_t               dtinc     = ctx->dtinc;
    const int32_t               dwinc     = ctx->dwinc;
    const int32_t               prim_tile = ctx->prim_tile;
    const bool                  need_lod  = ctx->need_lod;

    const int32_t nextsw = rdp_sadd(w, dwinc) >> 16;
    int32_t nexts = rdp_sadd(s, dsinc) >> 16;
    int32_t nextt = rdp_sadd(t, dtinc) >> 16;

    if (object->m_other_modes.persp_tex_en)
    {
        rdp_tc_div(tp->m_rdp, nexts, nextt, nextsw, &nexts, &nextt);
    }
    else
    {
        rdp_tc_div_no_perspective(nexts, nextt, nextsw, &nexts, &nextt);
    }

    if (mode != TEXPIPE_LOD_PEEK)
    {
        userdata->m_precomp_s = nexts;
        userdata->m_precomp_t = nextt;
    }
    else if (stash)
    {
        /* The raw next-pixel divide IS the next pixel's precomp value:
         * the span loop reloads sss/sst from m_precomp at the loop
         * bottom, so applying this stash reproduces the next main LOD
         * call's inputs exactly. */
        stash->raw_next_s = nexts;
        stash->raw_next_t = nextt;
    }

    /* When neither texture LOD nor the LOD_FRACTION combiner input is live
     * for this span (flag computed once per span in the caller), the entire
     * LOD footprint below is unobservable: lod/lodclamp feed only
     * m_lod_fraction (not selected by any combiner mux this span) and the
     * tile promotion (gated on tex_lod_en, which is off). The pipeline
     * outputs that ARE observable -- the next-pixel divided coordinates
     * (m_precomp_s/t, computed above) and the current pixel's clamped fetch
     * coordinates (below) -- are produced identically. This skips the
     * second (Y-leg) perspective divide and the step/clamp arithmetic on
     * every non-LOD pixel. */
    const int spanend = (mode == TEXPIPE_LOD_1CYCLE_SPANEND);
    const int lmode = spanend ? TEXPIPE_LOD_1CYCLE : mode;

    if (lmode == TEXPIPE_LOD_1CYCLE && !need_lod)
    {
        *sss = rdp_lod_lookup[*sss & 0x7ffff];
        *sst = rdp_lod_lookup[*sst & 0x7ffff];
        return;
    }

    int32_t lod;
    int32_t lodclamp;
    if (lmode == TEXPIPE_LOD_1CYCLE)
    {
        /* Hardware 1-cycle LOD footprint. In 1-cycle mode the LOD unit
         * does not see the current pixel or a scanline-down sample: it
         * measures the pipelined pair -- the NEXT pixel and the one after
         * it in span walk order -- and only along the span (X).
         *
         * At the second-to-last walked pixel of a span whose four
         * sublines are all valid there is no P+2, and hardware measures
         * the CENTERED pair (P-1, P+1) instead. Partial spans (any
         * invalid subline) keep the interior form: their observable
         * pixels showed no promotion, consistent with the hardware
         * walker's extent running past the covered pixels there.
         *
         * Adjudicated at zero residual against the PRDP 11:23 and 11:46
         * checksums (two camera variants of a 6-level mip scene) and a
         * mip-coded replay of the same scenes, in which each pyramid
         * level is a distinct solid color so every pixel reads out its
         * chosen tile. For scale, the current-pixel + scanline footprint
         * the 2-cycle path uses misses by ~4400 pixels per scene and
         * next-pixel X-only by ~100. The P+1 divide computed above is
         * unchanged either way, so its m_precomp TEXEL1 coordinate side
         * effect is intact. */
        const int32_t p2step = spanend ? -1 : 2;
        const int32_t next2sw = rdp_sadd(w, p2step * dwinc) >> 16;
        int32_t next2s = rdp_sadd(s, p2step * dsinc) >> 16;
        int32_t next2t = rdp_sadd(t, p2step * dtinc) >> 16;
        if (object->m_other_modes.persp_tex_en)
        {
            rdp_tc_div(tp->m_rdp, next2s, next2t, next2sw, &next2s, &next2t);
        }
        else
        {
            rdp_tc_div_no_perspective(next2s, next2t, next2sw, &next2s, &next2t);
        }

        lodclamp = (((nextt & 0x60000) > 0) | ((next2t & 0x60000) > 0))
                       || (((nexts & 0x60000) > 0) | ((next2s & 0x60000) > 0));

        int32_t horstep = SIGN17(next2s & 0x1ffff) - SIGN17(nexts & 0x1ffff);
        int32_t vertstep = SIGN17(next2t & 0x1ffff) - SIGN17(nextt & 0x1ffff);
        if (horstep & 0x20000)  { horstep = ~horstep & 0x1ffff; }
        if (vertstep & 0x20000) { vertstep = ~vertstep & 0x1ffff; }

        lod = (horstep >= vertstep) ? horstep : vertstep;
    }
    else
    {
    /* Vertical (Y) texel derivative for the LOD footprint. The RDP LOD is the
     * max texel/pixel ratio over BOTH screen axes; the previous MAME-derived
     * code used only the horizontal (next-pixel) derivatives. ParaLLEl-RDP
     * folds |st_dy - st| in alongside the X term, where st_dy is the
     * perspective-divided coordinate one scanline down: stw + (DsDy & ~0x7fff)
     * (the Y row is not flip-signed). */
    int32_t nexts_y = rdp_sadd(s, object->m_span_base.m_span_dsdy & ~0x7fff) >> 16;
    int32_t nextt_y = rdp_sadd(t, object->m_span_base.m_span_dtdy & ~0x7fff) >> 16;
    const int32_t nextsw_y = rdp_sadd(w, object->m_span_base.m_span_dwdy & ~0x7fff) >> 16;
    if (object->m_other_modes.persp_tex_en)
    {
        rdp_tc_div(tp->m_rdp, nexts_y, nextt_y, nextsw_y, &nexts_y, &nextt_y);
    }
    else
    {
        rdp_tc_div_no_perspective(nexts_y, nextt_y, nextsw_y, &nexts_y, &nextt_y);
    }

    lodclamp = (((*sst & 0x60000) > 0) | ((nextt & 0x60000) > 0))
                          || (((*sss & 0x60000) > 0) | ((nexts & 0x60000) > 0))
                          || (((nextt_y & 0x60000) > 0) | ((nexts_y & 0x60000) > 0));

    int32_t horstep = SIGN17(nexts & 0x1ffff) - SIGN17(*sss & 0x1ffff);
    int32_t vertstep = SIGN17(nextt & 0x1ffff) - SIGN17(*sst & 0x1ffff);
    int32_t horstep_y = SIGN17(nexts_y & 0x1ffff) - SIGN17(*sss & 0x1ffff);
    int32_t vertstep_y = SIGN17(nextt_y & 0x1ffff) - SIGN17(*sst & 0x1ffff);
    if (horstep & 0x20000)    { horstep = ~horstep & 0x1ffff; }
    if (vertstep & 0x20000)   { vertstep = ~vertstep & 0x1ffff; }
    if (horstep_y & 0x20000)  { horstep_y = ~horstep_y & 0x1ffff; }
    if (vertstep_y & 0x20000) { vertstep_y = ~vertstep_y & 0x1ffff; }

    /* A perspective divide whose W is <= 0 (w_carry) saturates its outputs
     * and raises the divide's overflow flag (ParaLLEl-RDP perspective.h:
     * w_carry => temp = 0x7fff, overflow = true); tc_div encodes that flag
     * as the coordinate's bit 18. The LOD overflow clamp is therefore the
     * plain OR of the flag bits across all three legs -- any overflowing
     * leg (magnitude saturation or w_carry) forces lod = 0x7fff = distant
     * (texture.h compute_lod_2cycle: perspective_overflow => distant,
     * lod_frac = 0xff). */

    lod = (horstep >= vertstep) ? horstep : vertstep;
    if (horstep_y > lod)  { lod = horstep_y; }
    if (vertstep_y > lod) { lod = vertstep_y; }
    }

    *sss = rdp_lod_lookup[*sss & 0x7ffff];
    *sst = rdp_lod_lookup[*sst & 0x7ffff];

    if ((lod & 0x4000) || lodclamp)
    {
        lod = 0x7fff;
    }
    else if ((uint32_t)lod < object->m_misc_state.m_min_level)
    {
        lod = object->m_misc_state.m_min_level;
    }

    int32_t l_tile = rdp_get_log2((lod >> 5) & 0xff);
    const bool magnify = (lod < 32);
    const bool distant = ((lod & 0x6000) || ((uint32_t)l_tile >= object->m_misc_state.m_max_level));

    if (mode != TEXPIPE_LOD_PEEK || stash)
    {
        rgbaint_t *const frac_out = (mode != TEXPIPE_LOD_PEEK)
            ? &userdata->m_lod_fraction : &stash->lod_fraction;
        unsigned lod_fraction = ((lod << 3) >> l_tile) & 0xff;

        if(!object->m_other_modes.sharpen_tex_en && !object->m_other_modes.detail_tex_en)
        {
            if (distant)
            {
                lod_fraction = 0xff;
            }
            else if (magnify)
            {
                lod_fraction = 0;
            }
        }

        rgbaint_set_rgba(frac_out, lod_fraction, lod_fraction, lod_fraction, lod_fraction);

        /* Sharpen: while magnifying, the LOD fraction gains the 9-bit sign bit
         * (ParaLLEl-RDP texture.h compute_lod_2cycle: lod_frac =
         * (max(min_lod, max_d) << 3) + (sharpen_tex_en ? -0x100 : 0); the
         * two's-complement 9-bit pattern of that negative value is 0x100|frac).
         * All combiner input paths sign-extend consistently: the multiplier at
         * 0x100, the a/b/d inputs via the 0x180 special expand. */
        if (object->m_other_modes.sharpen_tex_en && magnify)
        {
            rgbaint_or_imm_rgba(frac_out, 0x100, 0x100, 0x100, 0x100);
        }
    }

    /* Tile promotion, shared by all modes: 1-cycle promotes TEXEL0 by the
     * same rules (ParaLLEl-RDP shading.h calls the one compute_lod_2cycle
     * for BOTH cycle modes whenever LOD is in use; texture.h
     * compute_lod_2cycle tail), and the pipelined TEXEL1 samples through
     * the promoted tile (shading.h uses_pipelined_texel1: tile1 = tile0). */
    if (object->m_other_modes.tex_lod_en)
    {
        if (distant)
        {
            l_tile = object->m_misc_state.m_max_level;
        }
        if (!object->m_other_modes.detail_tex_en)
        {
            *t1 = (prim_tile + l_tile) & 7;
            if (lmode != TEXPIPE_LOD_1CYCLE)
            {
                if (!(distant || (!object->m_other_modes.sharpen_tex_en && magnify)))
                {
                    *t2 = (*t1 + 1) & 7;
                }
                else
                {
                    *t2 = *t1; // World Driver Championship, Stunt Race 64, Beetle Adventure Racing
                }
            }
        }
        else // Beetle Adventure Racing, World Driver Championship (ingame_, NFL Blitz 2001, Pilotwings
        {
            if (!magnify)
            {
                *t1 = (prim_tile + l_tile + 1);
            }
            else
            {
                *t1 = (prim_tile + l_tile);
            }
            *t1 &= 7;
            if (lmode != TEXPIPE_LOD_1CYCLE)
            {
                if (!distant && !magnify)
                {
                    *t2 = (prim_tile + l_tile + 2) & 7;
                }
                else
                {
                    *t2 = (prim_tile + l_tile + 1) & 7;
                }
            }
        }
    }
}
void rdp_texpipe_calculate_clamp_diffs(uint32_t prim_tile, rdp_span_aux* userdata, const rdp_poly_state *object)
{
    const rdp_tile_t* tiles = object->m_tiles;
    if (object->m_other_modes.cycle_type == CYCLE_TYPE_2)
    {
        if (object->m_other_modes.tex_lod_en)
        {
            for (int32_t start = 0; start <= 7; start++)
            {
                rgbaint_set_rgba(&userdata->m_clamp_diff[start], (tiles[start].sh >> 2) - (tiles[start].sl >> 2), (tiles[start].sh >> 2) - (tiles[start].sl >> 2), (tiles[start].th >> 2) - (tiles[start].tl >> 2), (tiles[start].th >> 2) - (tiles[start].tl >> 2));
            }
        }
        else
        {
            const int32_t start = prim_tile;
            const int32_t end = (prim_tile + 1) & 7;
            rgbaint_set_rgba(&userdata->m_clamp_diff[start], (tiles[start].sh >> 2) - (tiles[start].sl >> 2), (tiles[start].sh >> 2) - (tiles[start].sl >> 2), (tiles[start].th >> 2) - (tiles[start].tl >> 2), (tiles[start].th >> 2) - (tiles[start].tl >> 2));
            rgbaint_set_rgba(&userdata->m_clamp_diff[end], (tiles[end].sh >> 2) - (tiles[end].sl >> 2), (tiles[end].sh >> 2) - (tiles[end].sl >> 2), (tiles[end].th >> 2) - (tiles[end].tl >> 2), (tiles[end].th >> 2) - (tiles[end].tl >> 2));
        }
    }
    else//1-cycle or copy
    {
        if (object->m_other_modes.cycle_type == CYCLE_TYPE_1 && object->m_other_modes.tex_lod_en)
        {
            /* 1-cycle texture LOD promotes the sampled tile per pixel
             * (prim_tile + l_tile, +1 more under detail), exactly like the
             * 2-cycle promotion above. The clamp parameters are per-tile
             * state and must exist for every tile the promotion can select;
             * populating only prim_tile leaves the promoted tiles clamping
             * against stale pool data. Mirror the 2-cycle lod_en branch. */
            for (int32_t start = 0; start <= 7; start++)
            {
                rgbaint_set_rgba(&userdata->m_clamp_diff[start], (tiles[start].sh >> 2) - (tiles[start].sl >> 2), (tiles[start].sh >> 2) - (tiles[start].sl >> 2), (tiles[start].th >> 2) - (tiles[start].tl >> 2), (tiles[start].th >> 2) - (tiles[start].tl >> 2));
            }
        }
        else
        {
            rgbaint_set_rgba(&userdata->m_clamp_diff[prim_tile], (tiles[prim_tile].sh >> 2) - (tiles[prim_tile].sl >> 2), (tiles[prim_tile].sh >> 2) - (tiles[prim_tile].sl >> 2), (tiles[prim_tile].th >> 2) - (tiles[prim_tile].tl >> 2), (tiles[prim_tile].th >> 2) - (tiles[prim_tile].tl >> 2));
        }
    }
}

static void rdp_texpipe_fetch_rgba16_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x7ff;

    unsigned c = ((uint16_t*)userdata->m_tmem)[taddr];
    c = ((uint16_t*)(userdata->m_tmem + 0x800))[(c >> 8) << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_rgba16_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x7ff;

    unsigned c = ((uint16_t*)userdata->m_tmem)[taddr];
    c = ((uint16_t*)(userdata->m_tmem + 0x800))[(c >> 8) << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_rgba16_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x7ff;

    const unsigned c = ((uint16_t*)userdata->m_tmem)[taddr];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_rgba32_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint32_t *tc = ((uint32_t*)userdata->m_tmem);
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x3ff;

    unsigned c = tc[taddr];
    c = ((uint16_t*)(userdata->m_tmem + 0x800))[(c >> 24) << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_rgba32_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint32_t *tc = ((uint32_t*)userdata->m_tmem);
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x3ff;

    unsigned c = tc[taddr];
    c = ((uint16_t*)(userdata->m_tmem + 0x800))[(c >> 24) << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_rgba32_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x3ff;

    const unsigned cl = ((uint16_t*)userdata->m_tmem)[taddr];
    const unsigned ch = ((uint16_t*)userdata->m_tmem)[taddr | 0x400];

    rgbaint_set_rgba(out, ch & 0xff, cl >> 8, cl & 0xff, ch >> 8);
}

static void rdp_texpipe_fetch_nop(rgbaint_t* out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)out; (void)s; (void)t; (void)tbase; (void)tpal; (void)userdata;
}

/* YUV texel fetch with an explicit chroma S source. Luma is addressed by
 * s; the chroma (U,V) pair by cs, which the bilinear quad sets per
 * column: cs = s0 for the T00/T01 column and cs = 2*s1 - s0 for T10/T11,
 * the chroma pair one step ahead of the base pair (ParaLLEl-RDP
 * texture.h sample_texture). For a point fetch cs == s, and with
 * arithmetic shifts ((tbase << 3) + s) >> 1 == (tbase << 2) + (s >> 1),
 * so the single-texel behavior is unchanged. */
static void rdp_texpipe_fetch_yuv_cs(rgbaint_t *out, int32_t s, int32_t cs, int32_t t, int32_t tbase, rdp_span_aux* userdata)
{
    const uint16_t *tc = ((uint16_t*)userdata->m_tmem);

    const int32_t taddr = (tbase << 3) + s;  /* unmasked; may be negative -- must stay signed */
    const int32_t caddr = (tbase << 3) + cs; /* likewise; arithmetic >>1 below */
    const unsigned taddrhi = (taddr ^ s_tex_addr_swap8[t & 1]) & 0x7ff;
    const unsigned taddrlow = ((caddr >> 1) ^ s_tex_addr_swap16[t & 1]) & 0x3ff;

    const unsigned c = tc[taddrlow];

    int32_t y = userdata->m_tmem[taddrhi | 0x800];
    int32_t u = c >> 8;
    int32_t v = c & 0xff;

    v ^= 0x80; u ^= 0x80;
    u |= ((u & 0x80) << 1);
    v |= ((v & 0x80) << 1);

    rgbaint_set_rgba(out, y, u, v, y);
}
static void rdp_texpipe_fetch_yuv(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    rdp_texpipe_fetch_yuv_cs(out, s, s, t, tbase, userdata);
}

/* YUV with tile size 3 (32bpp): an illegal format/size combination the
 * RDP resolves by addressing the tile at 32bpp texel rate. One 32-bit
 * unit holds a UYVY texel pair, so the pair index is s >> 1; the tile
 * line counts double (tbase scales by 8 into 16-bit words, not 4); the
 * odd-line swap applies to the pair index (the far half of the 64-bit
 * doubleword at texel granularity); and address bit 1 of the in-row word
 * is the OR of the 16-bit-rate and 32bpp-rate drivers, a wired mux
 * artifact of the undefined combination. Chroma is the addressed
 * low-bank word, luma byte (s & 1) of the same word in the high bank.
 * Adjudicated by the PRDP 5:0 coded-texture replay at 204/204 decoded
 * texels and zero golden-sum residual, which also covers the pair
 * indices beyond the coded rows' direct reach. tile.tmem scaling rides
 * the same << 3 as the line term, but the probe ran with tmem == 0, so a
 * nonzero-tmem YUV32 tile is unadjudicated. */
static void rdp_texpipe_fetch_yuv32(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint16_t *tc = ((uint16_t*)userdata->m_tmem);

    const unsigned m = ((unsigned)(s >> 1) ^ (((unsigned)t & 1u) << 1)) & 0x1ffu;
    const unsigned inrow = ((m >> 1) << 2) | (((m | (m >> 1)) & 1u) << 1) | (m & 1u);
    const unsigned wlog = (((unsigned)tbase << 3) + inrow) & 0x3ffu;

    const unsigned c = tc[wlog ^ HWORD_IN_WORD_XOR];
    int32_t y = userdata->m_tmem[((((wlog << 1) | ((unsigned)s & 1u)) ^ BYTE_IN_WORD_XOR) & 0x7ffu) | 0x800u];
    int32_t u = c >> 8;
    int32_t v = c & 0xff;

    v ^= 0x80; u ^= 0x80;
    u |= ((u & 0x80) << 1);
    v |= ((v & 0x80) << 1);

    rgbaint_set_rgba(out, y, u, v, y);
}
static void rdp_texpipe_fetch_ci4_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = (s & 1) ? (tc[taddr] & 0xf) : (tc[taddr] >> 4);
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[((tpal << 4) | p) << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_ci4_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    int32_t taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = (s & 1) ? (tc[taddr] & 0xf) : (tc[taddr] >> 4);
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[((tpal << 4) | p) << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_ci4_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0xfff;

    unsigned p = (s & 1) ? (tc[taddr] & 0xf) : (tc[taddr] >> 4);
    p = (((unsigned)tpal & 0xf) << 4) | p; /* mask preserves the old uint8_t truncation */

    rgbaint_set_rgba(out, p, p, p, p);
}
static void rdp_texpipe_fetch_ci8_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = tc[taddr];
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[p << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_ci8_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = tc[taddr];
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[p << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_ci8_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0xfff;

    const unsigned p = tc[taddr];
    rgbaint_set_rgba(out, p, p, p, p);
}
static void rdp_texpipe_fetch_ia4_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = ((s) & 1) ? (tc[taddr] & 0xf) : (tc[taddr] >> 4);
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[((tpal << 4) | p) << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_ia4_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = ((s) & 1) ? (tc[taddr] & 0xf) : (tc[taddr] >> 4);
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[((tpal << 4) | p) << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_ia4_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0xfff;

    const unsigned p = ((s) & 1) ? (tc[taddr] & 0xf) : (tc[taddr] >> 4);
    unsigned i = p & 0xe;
    i = (i << 4) | (i << 1) | (i >> 2);

    rgbaint_set_rgba(out, (p & 1) * 0xff, i, i, i);
}
static void rdp_texpipe_fetch_ia8_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = tc[taddr];
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[p << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_ia8_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned p = tc[taddr];
    const unsigned c = ((uint16_t*)(userdata->m_tmem + 0x800))[p << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_ia8_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0xfff;

    const unsigned p = tc[taddr];
    unsigned i = p & 0xf0;
    i |= (i >> 4);

    rgbaint_set_rgba(out, ((p << 4) | (p & 0xf)) & 0xff, i, i, i);
}
static void rdp_texpipe_fetch_ia16_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint16_t *tc = ((uint16_t*)userdata->m_tmem);
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x3ff;

    unsigned c = tc[taddr];
    c = ((uint16_t*)(userdata->m_tmem + 0x800))[(c >> 8) << 2];

    rgbaint_copy(out, &s_expand_16to32_table[c]);
}
static void rdp_texpipe_fetch_ia16_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint16_t *tc = ((uint16_t*)userdata->m_tmem);
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x3ff;

    unsigned c = tc[taddr];
    c = ((uint16_t*)(userdata->m_tmem + 0x800))[(c >> 8) << 2];

    const unsigned k = (c >> 8) & 0xff;
    rgbaint_set_rgba(out, c & 0xff, k, k, k);
}
static void rdp_texpipe_fetch_ia16_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint16_t *tc = ((uint16_t*)userdata->m_tmem);
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x7ff;

    const unsigned c = tc[taddr];
    const unsigned i = (c >> 8);
    rgbaint_set_rgba(out, c & 0xff, i, i, i);
}
static void rdp_texpipe_fetch_ci32_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    /* The decode every unsupported >=16-bit direct (non-TLUT) format/size
     * combination lands on: CI16, CI32, IA32, I16 and I32. Addressing is
     * the plain 16-bit-word form shared with ia16_raw; the word is then
     * split into its two bytes and interleaved across the lanes as
     * (r,g,b,a) = (hi, lo, hi, lo) rather than expanded as a colour.
     *
     * Named for ParaLLEl-RDP's sample_texel_ci32 (texture.h), which is the
     * reference for this and which every one of those combinations
     * dispatches to there; the name is kept identical so the two can be
     * diffed. It is not specific to 32-bit tiles. */
    const uint16_t *tc = ((uint16_t*)userdata->m_tmem);
    const unsigned taddr = (((tbase << 2) + s) ^ s_tex_addr_swap16[t & 1]) & 0x7ff;

    const unsigned c = tc[taddr];
    const unsigned hi = c >> 8;
    const unsigned lo = c & 0xff;

    rgbaint_set_rgba(out, lo, hi, lo, hi);
}
static void rdp_texpipe_fetch_i4_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned byteval = tc[taddr];
    const unsigned c = ((s & 1)) ? (byteval & 0xf) : ((byteval >> 4) & 0xf);

    const unsigned k = ((uint16_t*)(userdata->m_tmem + 0x800))[((tpal << 4) | c) << 2];
    rgbaint_copy(out, &s_expand_16to32_table[k]);
}
static void rdp_texpipe_fetch_i4_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned byteval = tc[taddr];
    const unsigned c = ((s & 1)) ? (byteval & 0xf) : ((byteval >> 4) & 0xf);
    const unsigned k = ((uint16_t*)(userdata->m_tmem + 0x800))[((tpal << 4) | c) << 2];

    const unsigned i = (k >> 8) & 0xff;
    rgbaint_set_rgba(out, k & 0xff, i, i, i);
}
static void rdp_texpipe_fetch_i4_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = ((((tbase << 4) + s) >> 1) ^ s_tex_addr_swap8[t & 1]) & 0xfff;

    const unsigned byteval = tc[taddr];
    unsigned c = ((s & 1)) ? (byteval & 0xf) : ((byteval >> 4) & 0xf);
    c |= (c << 4);

    rgbaint_set_rgba(out, c, c, c, c);
}
static void rdp_texpipe_fetch_i8_tlut0(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned c = tc[taddr];

    const unsigned k = ((uint16_t*)(userdata->m_tmem + 0x800))[c << 2];
    rgbaint_copy(out, &s_expand_16to32_table[k]);
}
static void rdp_texpipe_fetch_i8_tlut1(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0x7ff;

    const unsigned c = tc[taddr];
    const unsigned k = ((uint16_t*)(userdata->m_tmem + 0x800))[c << 2];

    const unsigned i = (k >> 8) & 0xff;
    rgbaint_set_rgba(out, k & 0xff, i, i, i);
}
static void rdp_texpipe_fetch_i8_raw(rgbaint_t *out, int32_t s, int32_t t, int32_t tbase, int32_t tpal, rdp_span_aux* userdata)
{
    (void)tpal;
    const uint8_t *tc = userdata->m_tmem;
    const unsigned taddr = (((tbase << 3) + s) ^ s_tex_addr_swap8[t & 1]) & 0xfff;

    const unsigned c = tc[taddr];

    rgbaint_set_rgba(out, c, c, c, c);
}
