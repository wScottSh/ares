/*
Copyright (c) 2011-2023 Ville Linde, Aaron Giles
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

    rdp_poly.h (from MAME devices/video/poly.h)

    Polygon helper routines, ISO C11 translation.

    The RDP is the only client, so this specializes to eight parameters
    over rdp_poly_state and keeps only the span path. The scheduling
    machinery is unchanged: work units of up to 32 scanlines, 16
    screen-space buckets, and the previtem/count_next atomic chaining
    that serializes overlapping units within a bucket while letting
    disjoint spans run concurrently.

    poly_pool is a chunked pool with runtime item size: items are
    cache-line aligned (avoiding false sharing between worker threads),
    addresses are stable until reset, growth chains new chunks, and
    reset() consolidates to the high-water capacity while preserving the
    tracked last object, which poly_pool_last() relies upon.

****************************************************************************

    Pixel model:

    (0.0,0.0)       (1.0,0.0)       (2.0,0.0)       (3.0,0.0)
        +---------------+---------------+---------------+
        |               |               |               |
        |               |               |               |
        |   (0.5,0.5)   |   (1.5,0.5)   |   (2.5,0.5)   |
        |       *       |       *       |       *       |
        |               |               |               |
        |               |               |               |
    (0.0,1.0)       (1.0,1.0)       (2.0,1.0)       (3.0,1.0)
        +---------------+---------------+---------------+
        |               |               |               |
        |               |               |               |
        |   (0.5,1.5)   |   (1.5,1.5)   |   (2.5,1.5)   |
        |       *       |       *       |       *       |
        |               |               |               |
        |               |               |               |
        |               |               |               |
        +---------------+---------------+---------------+
    (0.0,2.0)       (1.0,2.0)       (2.0,2.0)       (3.0,2.0)

***************************************************************************/

#ifndef RDP_POLY_H
#define RDP_POLY_H

#include "rdp_types.h"
#include "rdp_wqueue.h"

//**************************************************************************
//  CONSTANTS
//**************************************************************************

#define POLY_MAX_PARAMS         11
#define SCANLINES_PER_BUCKET    32
#define TOTAL_BUCKETS           (512 / SCANLINES_PER_BUCKET)

// poly_array cache-line/chunk geometry.
#define POLY_CACHE_LINE_SHIFT   6
#define POLY_CACHE_LINE_SIZE    (1u << POLY_CACHE_LINE_SHIFT)
#define POLY_CHUNK_GRANULARITY  65536u

//**************************************************************************
//  TYPE DEFINITIONS
//**************************************************************************

// each extent param has a starting value and a dp/dx (BaseType = uint32_t)
typedef struct extent_param_t
{
        uint32_t start;                     // parameter value at start
        uint32_t dpdx;                      // dp/dx relative to start
} extent_param_t;

// a single extent describes a span and a list of parameter extents
typedef struct extent_t
{
        int16_t startx, stopx;              // starting (inclusive)/ending (exclusive) endpoints
        extent_param_t param[POLY_MAX_PARAMS]; // array of parameter start/deltas
        void *userdata;                     // custom per-span data
} extent_t;

// clip rectangle for render_extents (inclusive bounds)
typedef struct poly_rect
{
        int32_t min_x, max_x;               // left() / right()
        int32_t min_y, max_y;               // top() / bottom()
} poly_rect;

// Scanline callback. Typed against struct rdp_t (forward-declared via
// rdp_types.h) so
// the RDP's span_draw_* functions match this pointer type exactly --
// calling through a mismatched function-pointer type is undefined
// behavior in C, even between void* and object pointers.
typedef void (*poly_render_cb)(struct rdp_t *cbarg, int32_t scanline,
        const extent_t *extent, const rdp_poly_state *object, int32_t threadid);

// chunked pool with stable item addresses (poly_array)
typedef struct poly_pool_chunk
{
        _Atomic(struct poly_pool_chunk *) next;  /* appended by the producer while
                                                  * workers traverse: release store on
                                                  * publish, acquire loads in walks */
        uint8_t *alloc;                          // raw allocation
        uint8_t *base;                           // cache-line aligned base
        uint32_t count;                          // items in this chunk
} poly_pool_chunk;

typedef struct poly_pool
{
        size_t item_size;                        // sizeof item, rounded up to cache line
        uint32_t items_per_chunk;
        poly_pool_chunk *chunks;                 // singly-linked, first is primary
        _Atomic uint32_t next;                   // total items handed out since reset
                                                 // (relaxed atomics: producer-only writes,
                                                 // worker-side reads are the byindex bound
                                                 // assert; ordering rides the wqueue mutex)
        uint32_t max;                            // high-water mark
        void *last;                              // most recently allocated item (tracked pools)
        bool track_last;
} poly_pool;

// primitive_info describes a single primitive
typedef struct primitive_info
{
        struct poly_manager *m_owner;            // pointer back to the poly manager
        rdp_poly_state *m_object;                // object data pointer
        poly_render_cb m_callback;               // callback to handle a scanline's worth of work
        struct rdp_t *m_cbarg;                 // callback context (the rdp_t)
} primitive_info;

// internal unit of work
typedef struct work_unit
{
        _Atomic uint32_t count_next;             // number of scanlines and index of next item to process
        primitive_info *primitive;               // pointer to primitive
        int32_t scanline;                        // starting scanline
        uint32_t previtem;                       // index of previous item in the same bucket
        extent_t extent[SCANLINES_PER_BUCKET];   // array of scanline extents
} work_unit;

typedef struct poly_manager
{
        // queue management
        rdp_wq_t *m_queue;                 // work queue

        // arrays
        poly_pool m_primitive;                   // array of primitives
        poly_pool m_object;                      // array of object data
        poly_pool m_unit;                        // array of work units

        // buckets
        uint32_t m_unit_bucket[TOTAL_BUCKETS];   // buckets for tracking unit usage

        // callback context for all primitives (the owning rdp_t)
        struct rdp_t *m_cbarg;
} poly_manager;

// construction/destruction
int  poly_manager_init(poly_manager *poly, struct rdp_t *cbarg);
void poly_manager_destroy(poly_manager *poly);

// synchronization: stall until all work is complete, then reset pools
void poly_manager_wait(poly_manager *poly);

// return and default-initialize the next object (object_data().next())
rdp_poly_state *poly_manager_object_next(poly_manager *poly);

// direct custom extents (render_extents<8>)
void poly_manager_render_extents(poly_manager *poly, const poly_rect *cliprect,
        poly_render_cb callback, int startscanline, int numscanlines, const extent_t *extents);

#endif
