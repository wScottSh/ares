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

    rdp_blender_cycle1/cycle2 are the two entry points; they recover the
    per-variant behaviour from span-constant mode bits. Everything else
    is static in rdp_blend.c.

******************************************************************************/

#ifndef RDP_BLEND_H
#define RDP_BLEND_H

#include "rdp_types.h"

typedef struct rdp_blender_t rdp_blender_t;

struct rdp_blender_t
{
        uint8_t             m_color_dither[256 * 8];
        uint8_t             m_alpha_dither[256 * 8];
};

void rdp_blender_init(rdp_blender_t *b);

/* Per-span invariant operands, as rdp_lod_ctx_t does for the LOD pipeline:
 * at eight and nine parameters two and three went on the stack, once per
 * blended pixel. Leaves the two dither draws: three arguments. */
typedef struct
{
    rdp_blender_t        *b;
    rdp_span_aux         *userdata;
    const rdp_poly_state *object;
    rgbaint_t            *out;           /* blended pixel destination */
    int                   partialreject;
    int                   sel0;          /* cycle-0 m2b MEMORY_ALPHA select */
    int                   sel1;          /* cycle-1 select; 2-cycle only */
} rdp_blend_ctx_t;

bool rdp_blender_cycle1(const rdp_blend_ctx_t *ctx, int dith, int adseed);
bool rdp_blender_cycle2(const rdp_blend_ctx_t *ctx, int dith, int adseed);

#endif
