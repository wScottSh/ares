/*
Copyright (c) 2011-2023 Vas Crabb, Ryan Holtz
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
/***************************************************************************

    rdp_rgba.h (from MAME rgbgen.h / rgbgen.cpp)

    General RGB utilities, ISO C11 translation.

    rgbaint_t is a plain struct; every operation is a static inline
    taking an explicit object pointer, with the argument form spelled out
    in the name (rgbaint_set_rgba / rgbaint_copy / rgbaint_make). There
    is one portable path; no SIMD backends.

***************************************************************************/

#ifndef RDP_RGBA_H
#define RDP_RGBA_H

/***************************************************************************
    TYPE DEFINITIONS
***************************************************************************/

typedef struct rgbaint_t
{
    int32_t m_a;
    int32_t m_r;
    int32_t m_g;
    int32_t m_b;
} rgbaint_t;

static inline void rgbaint_set_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a = a;
    c->m_r = r;
    c->m_g = g;
    c->m_b = b;
}

static inline void rgbaint_copy(rgbaint_t *c, const rgbaint_t *other)
{
    *c = *other;
}

static inline rgbaint_t rgbaint_make(int32_t a, int32_t r, int32_t g, int32_t b)
{
    rgbaint_t c;
    rgbaint_set_rgba(&c, a, r, g, b);
    return c;
}

static inline uint8_t rgbaint_get_a(const rgbaint_t *c) { return (uint8_t)(uint32_t)c->m_a; }
static inline uint8_t rgbaint_get_r(const rgbaint_t *c) { return (uint8_t)(uint32_t)c->m_r; }
static inline uint8_t rgbaint_get_g(const rgbaint_t *c) { return (uint8_t)(uint32_t)c->m_g; }
static inline uint8_t rgbaint_get_b(const rgbaint_t *c) { return (uint8_t)(uint32_t)c->m_b; }

static inline int32_t rgbaint_get_a32(const rgbaint_t *c) { return c->m_a; }
static inline int32_t rgbaint_get_r32(const rgbaint_t *c) { return c->m_r; }
static inline int32_t rgbaint_get_g32(const rgbaint_t *c) { return c->m_g; }
static inline int32_t rgbaint_get_b32(const rgbaint_t *c) { return c->m_b; }

static inline void rgbaint_set_a(rgbaint_t *c, int32_t value) { c->m_a = value; }
static inline void rgbaint_set_r(rgbaint_t *c, int32_t value) { c->m_r = value; }
static inline void rgbaint_set_g(rgbaint_t *c, int32_t value) { c->m_g = value; }
static inline void rgbaint_set_b(rgbaint_t *c, int32_t value) { c->m_b = value; }

static inline void rgbaint_add_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a += a;
    c->m_r += r;
    c->m_g += g;
    c->m_b += b;
}

static inline void rgbaint_add(rgbaint_t *c, const rgbaint_t *color)
{
    rgbaint_add_imm_rgba(c, color->m_a, color->m_r, color->m_g, color->m_b);
}

static inline void rgbaint_add_imm(rgbaint_t *c, int32_t imm)
{
    rgbaint_add_imm_rgba(c, imm, imm, imm, imm);
}

static inline void rgbaint_sub_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a -= a;
    c->m_r -= r;
    c->m_g -= g;
    c->m_b -= b;
}

static inline void rgbaint_sub(rgbaint_t *c, const rgbaint_t *color)
{
    rgbaint_sub_imm_rgba(c, color->m_a, color->m_r, color->m_g, color->m_b);
}

static inline void rgbaint_subr_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a = a - c->m_a;
    c->m_r = r - c->m_r;
    c->m_g = g - c->m_g;
    c->m_b = b - c->m_b;
}

static inline void rgbaint_subr_imm(rgbaint_t *c, int32_t imm)
{
    rgbaint_subr_imm_rgba(c, imm, imm, imm, imm);
}

static inline void rgbaint_mul_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a *= a;
    c->m_r *= r;
    c->m_g *= g;
    c->m_b *= b;
}

static inline void rgbaint_mul(rgbaint_t *c, const rgbaint_t *color)
{
    rgbaint_mul_imm_rgba(c, color->m_a, color->m_r, color->m_g, color->m_b);
}

static inline void rgbaint_mul_imm(rgbaint_t *c, int32_t imm)
{
    rgbaint_mul_imm_rgba(c, imm, imm, imm, imm);
}

static inline void rgbaint_shl(rgbaint_t *c, const rgbaint_t *shift)
{
    /* The masked count only matters in the branch where it is <= 31; it
     * makes the shift ISO-defined for any lane value so the compiler is
     * free to if-convert the ternary. */
    c->m_a = ((uint32_t)shift->m_a > 31) ? 0 : (int32_t)((uint32_t)c->m_a << ((uint32_t)shift->m_a & 31u));
    c->m_r = ((uint32_t)shift->m_r > 31) ? 0 : (int32_t)((uint32_t)c->m_r << ((uint32_t)shift->m_r & 31u));
    c->m_g = ((uint32_t)shift->m_g > 31) ? 0 : (int32_t)((uint32_t)c->m_g << ((uint32_t)shift->m_g & 31u));
    c->m_b = ((uint32_t)shift->m_b > 31) ? 0 : (int32_t)((uint32_t)c->m_b << ((uint32_t)shift->m_b & 31u));
}

static inline void rgbaint_shl_imm(rgbaint_t *c, uint8_t shift)
{
    /* Branchless: shift > 31 zeroes every lane (the keep mask), otherwise a
     * plain shift. Shifting the lanes as unsigned is ISO-defined for any
     * lane value and produces the same bit pattern as the previous signed
     * shift. Uniform straight-line lane code so the compiler's SLP
     * vectorizer can pack the four lanes. */
    const uint32_t s = (uint32_t)shift & 31u;
    const uint32_t keep = (shift > 31) ? 0u : 0xffffffffu;
    c->m_a = (int32_t)(((uint32_t)c->m_a << s) & keep);
    c->m_r = (int32_t)(((uint32_t)c->m_r << s) & keep);
    c->m_g = (int32_t)(((uint32_t)c->m_g << s) & keep);
    c->m_b = (int32_t)(((uint32_t)c->m_b << s) & keep);
}

static inline void rgbaint_shr_imm(rgbaint_t *c, uint8_t shift)
{
    /* Branchless; see rgbaint_shl_imm. */
    const uint32_t s = (uint32_t)shift & 31u;
    const uint32_t keep = (shift > 31) ? 0u : 0xffffffffu;
    c->m_a = (int32_t)(((uint32_t)c->m_a >> s) & keep);
    c->m_r = (int32_t)(((uint32_t)c->m_r >> s) & keep);
    c->m_g = (int32_t)(((uint32_t)c->m_g >> s) & keep);
    c->m_b = (int32_t)(((uint32_t)c->m_b >> s) & keep);
}

static inline void rgbaint_sra(rgbaint_t *c, const rgbaint_t *shift)
{
    c->m_a >>= ((uint32_t)shift->m_a > 31) ? 31 : shift->m_a;
    c->m_r >>= ((uint32_t)shift->m_r > 31) ? 31 : shift->m_r;
    c->m_g >>= ((uint32_t)shift->m_g > 31) ? 31 : shift->m_g;
    c->m_b >>= ((uint32_t)shift->m_b > 31) ? 31 : shift->m_b;
}

static inline void rgbaint_sra_imm(rgbaint_t *c, uint8_t shift)
{
    const uint8_t s = (shift < 31) ? shift : 31;
    c->m_a >>= s;
    c->m_r >>= s;
    c->m_g >>= s;
    c->m_b >>= s;
}

static inline void rgbaint_or_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a |= a;
    c->m_r |= r;
    c->m_g |= g;
    c->m_b |= b;
}

static inline void rgbaint_and_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a &= a;
    c->m_r &= r;
    c->m_g &= g;
    c->m_b &= b;
}

static inline void rgbaint_xor_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a ^= a;
    c->m_r ^= r;
    c->m_g ^= g;
    c->m_b ^= b;
}

static inline void rgbaint_or_reg(rgbaint_t *c, const rgbaint_t *color)
{
    rgbaint_or_imm_rgba(c, color->m_a, color->m_r, color->m_g, color->m_b);
}

static inline void rgbaint_and_reg(rgbaint_t *c, const rgbaint_t *color)
{
    rgbaint_and_imm_rgba(c, color->m_a, color->m_r, color->m_g, color->m_b);
}

static inline void rgbaint_xor_reg(rgbaint_t *c, const rgbaint_t *color)
{
    rgbaint_xor_imm_rgba(c, color->m_a, color->m_r, color->m_g, color->m_b);
}

static inline void rgbaint_and_imm(rgbaint_t *c, int32_t imm)
{
    rgbaint_and_imm_rgba(c, imm, imm, imm, imm);
}

static inline void rgbaint_xor_imm(rgbaint_t *c, int32_t imm)
{
    rgbaint_xor_imm_rgba(c, imm, imm, imm, imm);
}

static inline void rgbaint_clamp_to_uint8(rgbaint_t *c)
{
    /* Split max(0)/min(255) passes: each pass is a uniform 4-lane min/max
     * idiom the vectorizer recognizes, unlike the previous nested ternary
     * chain. Identical results. */
    c->m_a = (c->m_a < 0) ? 0 : c->m_a;
    c->m_r = (c->m_r < 0) ? 0 : c->m_r;
    c->m_g = (c->m_g < 0) ? 0 : c->m_g;
    c->m_b = (c->m_b < 0) ? 0 : c->m_b;
    c->m_a = (c->m_a > 255) ? 255 : c->m_a;
    c->m_r = (c->m_r > 255) ? 255 : c->m_r;
    c->m_g = (c->m_g > 255) ? 255 : c->m_g;
    c->m_b = (c->m_b > 255) ? 255 : c->m_b;
}

static inline void rgbaint_clamp_9bit(rgbaint_t *c)
{
    /* Hardware combiner-output clamp (ParaLLEl-RDP clamping.h,
     * clamp_9bit_notrunc): v -= 0x80; sign-extend to 9 bits; v += 0x80;
     * clamp to [0, 0xff]. Unlike a saturating clamp this wraps in bands:
     *   [0x000, 0x0ff] -> identity
     *   [0x100, 0x17f] -> 0xff
     *   [0x180, 0x1ff] -> 0        (saturating clamps wrongly give 0xff)
     *   [0x200, 0x27f] -> v - 0x200
     * and mirrored bands on the negative side. sext9(x) is computed
     * branchlessly as ((x & 0x1ff) ^ 0x100) - 0x100. */
    c->m_a = ((((c->m_a - 0x80) & 0x1ff) ^ 0x100) - 0x100) + 0x80;
    c->m_r = ((((c->m_r - 0x80) & 0x1ff) ^ 0x100) - 0x100) + 0x80;
    c->m_g = ((((c->m_g - 0x80) & 0x1ff) ^ 0x100) - 0x100) + 0x80;
    c->m_b = ((((c->m_b - 0x80) & 0x1ff) ^ 0x100) - 0x100) + 0x80;
    rgbaint_clamp_to_uint8(c);
}

static inline int32_t rgbaint_clear_lane_(int32_t x, uint32_t sign)
{
    /* if (x & sign) x = 0; arithmetically (see rgbaint_sext_lane_). */
    const uint32_t d = (uint32_t)x & sign;
    const uint32_t keep = ((d | (0u - d)) >> 31) - 1u;   /* all-ones iff d == 0 */
    return (int32_t)((uint32_t)x & keep);
}

static inline int32_t rgbaint_clamp9_lane_(int32_t x)
{
    const int32_t v = x & 0x1ff;
    if (v & 0x100)
        return (v & 0x80) ? 0 : 0xff;
    return v;
}

static inline void rgbaint_clamp9(rgbaint_t *c)
{
    c->m_a = rgbaint_clamp9_lane_(c->m_a);
    c->m_r = rgbaint_clamp9_lane_(c->m_r);
    c->m_g = rgbaint_clamp9_lane_(c->m_g);
    c->m_b = rgbaint_clamp9_lane_(c->m_b);
}

static inline void rgbaint_clamp_and_clear(rgbaint_t *c, uint32_t sign)
{
    c->m_a = rgbaint_clear_lane_(c->m_a, sign);
    c->m_r = rgbaint_clear_lane_(c->m_r, sign);
    c->m_g = rgbaint_clear_lane_(c->m_g, sign);
    c->m_b = rgbaint_clear_lane_(c->m_b, sign);

    rgbaint_clamp_to_uint8(c);
}

static inline int32_t rgbaint_sext_lane_(int32_t x, uint32_t compare, uint32_t sign)
{
    /* if ((x & compare) == compare) x |= sign; in pure arithmetic:
     * d is zero iff every compare bit is set; (d | -d) >> 31 is the
     * standard is-nonzero bit, minus one gives an all-ones mask iff
     * d == 0. No compares or selects, so the four-lane caller is
     * straight dataflow the SLP vectorizer packs. */
    const uint32_t d = ((uint32_t)x & compare) ^ compare;
    const uint32_t m = ((d | (0u - d)) >> 31) - 1u;
    return x | (int32_t)(sign & m);
}

static inline void rgbaint_sign_extend(rgbaint_t *c, uint32_t compare, uint32_t sign)
{
    c->m_a = rgbaint_sext_lane_(c->m_a, compare, sign);
    c->m_r = rgbaint_sext_lane_(c->m_r, compare, sign);
    c->m_g = rgbaint_sext_lane_(c->m_g, compare, sign);
    c->m_b = rgbaint_sext_lane_(c->m_b, compare, sign);
}

static inline void rgbaint_cmpeq_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a = (c->m_a == a) ? 0xffffffff : 0;
    c->m_r = (c->m_r == r) ? 0xffffffff : 0;
    c->m_g = (c->m_g == g) ? 0xffffffff : 0;
    c->m_b = (c->m_b == b) ? 0xffffffff : 0;
}

static inline void rgbaint_cmpgt_imm_rgba(rgbaint_t *c, int32_t a, int32_t r, int32_t g, int32_t b)
{
    c->m_a = (c->m_a > a) ? 0xffffffff : 0;
    c->m_r = (c->m_r > r) ? 0xffffffff : 0;
    c->m_g = (c->m_g > g) ? 0xffffffff : 0;
    c->m_b = (c->m_b > b) ? 0xffffffff : 0;
}

static inline void rgbaint_cmpeq(rgbaint_t *c, const rgbaint_t *value)
{
    rgbaint_cmpeq_imm_rgba(c, value->m_a, value->m_r, value->m_g, value->m_b);
}

static inline void rgbaint_cmpgt(rgbaint_t *c, const rgbaint_t *value)
{
    rgbaint_cmpgt_imm_rgba(c, value->m_a, value->m_r, value->m_g, value->m_b);
}

/* rgb with alpha's A lane substituted, written as a constant-mask
 * four-lane select. A single scalar lane insert builds a mixed-origin
 * vector, which is precisely
 * what stops compilers from SLP-vectorizing the combiner block that
 * follows; the mask form is a uniform lane operation with per-lane
 * constants, which packs. Identical results. */
static inline rgbaint_t rgbaint_load_merged(const rgbaint_t *rgb, const rgbaint_t *alpha)
{
    rgbaint_t o;
    o.m_a = (int32_t)(((uint32_t)rgb->m_a & 0x00000000u) | ((uint32_t)alpha->m_a & 0xffffffffu));
    o.m_r = (int32_t)(((uint32_t)rgb->m_r & 0xffffffffu) | ((uint32_t)alpha->m_r & 0x00000000u));
    o.m_g = (int32_t)(((uint32_t)rgb->m_g & 0xffffffffu) | ((uint32_t)alpha->m_g & 0x00000000u));
    o.m_b = (int32_t)(((uint32_t)rgb->m_b & 0xffffffffu) | ((uint32_t)alpha->m_b & 0x00000000u));
    return o;
}

#endif
