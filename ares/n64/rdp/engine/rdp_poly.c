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

    rdp_poly.c (from MAME devices/video/poly.h)

    Polygon helper routines, ISO C11 translation. See rdp_poly.h.

***************************************************************************/

#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#include "common/debug.h"
#include "rdp_poly.h"

/***************************************************************************
    POLY POOL (poly_array)
***************************************************************************/

static size_t poly_pool_round_item(size_t size)
{
    return ((size + POLY_CACHE_LINE_SIZE - 1) / POLY_CACHE_LINE_SIZE) * POLY_CACHE_LINE_SIZE;
}

// Allocates a chunk holding at least `count` items (rounded up to the
// chunk granularity), zero-filled.
static poly_pool_chunk *poly_pool_chunk_alloc(const poly_pool *pool, uint32_t count)
{
    poly_pool_chunk *chunk;
    size_t bytes;

    count = ((count + pool->items_per_chunk - 1) / pool->items_per_chunk) * pool->items_per_chunk;
    bytes = pool->item_size * count + POLY_CACHE_LINE_SIZE;

    chunk = (poly_pool_chunk *)malloc(sizeof(*chunk));
    if (chunk == NULL)
        return NULL;

    chunk->alloc = (uint8_t *)calloc(1, bytes);
    if (chunk->alloc == NULL) {
        free(chunk);
        return NULL;
    }

    chunk->base = (uint8_t *)(((uintptr_t)chunk->alloc + POLY_CACHE_LINE_SIZE - 1) &
        (~(uintptr_t)0 << POLY_CACHE_LINE_SHIFT));
    chunk->count = count;
    atomic_store_explicit(&chunk->next, NULL, memory_order_relaxed);
    return chunk;
}

static int poly_pool_init(poly_pool *pool, size_t item_size, bool track_last)
{
    memset(pool, 0, sizeof(*pool));
    pool->item_size = poly_pool_round_item(item_size);
    pool->items_per_chunk = (uint32_t)(POLY_CHUNK_GRANULARITY / pool->item_size);
    if (pool->items_per_chunk == 0)
        pool->items_per_chunk = 1;
    pool->track_last = track_last;

    pool->chunks = poly_pool_chunk_alloc(pool, pool->items_per_chunk);
    return (pool->chunks == NULL) ? 1 : 0;
}

static void poly_pool_destroy(poly_pool *pool)
{
    poly_pool_chunk *chunk = pool->chunks;
    while (chunk != NULL) {
        poly_pool_chunk *next = atomic_load_explicit(&chunk->next, memory_order_acquire);
        free(chunk->alloc);
        free(chunk);
        chunk = next;
    }
    pool->chunks = NULL;
}

// Allocates and returns the next item. The item is zero-initialized on
// first use of its slot (fresh chunks are calloc'd) and retains stale
// contents on reuse; every field the RDP reads is written before use.
static void *poly_pool_next(poly_pool *pool)
{
    poly_pool_chunk *chunk = pool->chunks;
    uint32_t index = atomic_load_explicit(&pool->next, memory_order_relaxed);
    void *item;

    if (atomic_load_explicit(&pool->next, memory_order_relaxed) > pool->max)
        pool->max = atomic_load_explicit(&pool->next, memory_order_relaxed);

    // walk chunks to the one containing `index`, growing as needed
    while (index >= chunk->count) {
        index -= chunk->count;
        if (atomic_load_explicit(&chunk->next, memory_order_acquire) == NULL) {
            poly_pool_chunk *grown = poly_pool_chunk_alloc(pool, pool->items_per_chunk);
            /* Only ever publish a real chunk: storing a null here would
             * put it into the chain every worker walks. There is nothing
             * to hand back but a null the caller would write through, so
             * report and stop -- CEN64_LOG_ERR is the frontend's cue to
             * exit. */
            if (grown == NULL) {
                cen64_log(CEN64_LOG_ERR, "rdp: poly pool chunk allocation failed\n");
                return NULL;
            }
            /* base/count fully initialized before publication */
            atomic_store_explicit(&chunk->next, grown, memory_order_release);
        }
        chunk = atomic_load_explicit(&chunk->next, memory_order_acquire);
    }

    item = chunk->base + (size_t)index * pool->item_size;
    atomic_store_explicit(&pool->next, atomic_load_explicit(&pool->next, memory_order_relaxed) + 1, memory_order_relaxed);
    if (pool->track_last)
        pool->last = item;
    return item;
}

// Returns the item at `index` (must be < pool->next).
static void *poly_pool_byindex(const poly_pool *pool, uint32_t index)
{
    const poly_pool_chunk *chunk = pool->chunks;

    while (index >= chunk->count) {
        index -= chunk->count;
        chunk = atomic_load_explicit(&chunk->next, memory_order_acquire);
    }
    return chunk->base + (size_t)index * pool->item_size;
}

// Returns the index of an item obtained from this pool.
static uint32_t poly_pool_indexof(const poly_pool *pool, const void *item)
{
    const poly_pool_chunk *chunk;
    uint32_t base_index = 0;

    for (chunk = pool->chunks; chunk != NULL; chunk = atomic_load_explicit(&chunk->next, memory_order_acquire)) {
        const uint8_t *p = (const uint8_t *)item;
        if (p >= chunk->base && p < chunk->base + (size_t)chunk->count * pool->item_size)
            return base_index + (uint32_t)((size_t)(p - chunk->base) / pool->item_size);
        base_index += chunk->count;
    }

    /* Every caller passes an item this pool handed out, so this is an
     * invariant violation, not a runtime condition. There is no index that
     * could be returned instead: a wrong one silently aliases another work
     * unit. CEN64_LOG_ERR is the frontend's cue to exit; the 0 below exists
     * only so the function is total. */
    cen64_log(CEN64_LOG_ERR, "rdp: poly pool index lookup: item not in pool\n");
    return 0;
}

// reset(): rewind allocation; if growth chained extra chunks, coalesce
// into a single chunk sized to the high-water mark. Tracked pools
// repopulate the last item into slot 0 so last() survives the reset.
static void poly_pool_reset(poly_pool *pool)
{
    // Capture the tracked last item before anything moves:
    // poly_pool_next() below retargets pool->last to the slot it
    // returns, and the coalesce path frees the chunk holding the old
    // bytes.
    void *old_last = pool->track_last ? pool->last : NULL;

    if (pool->chunks->next != NULL) {
        poly_pool_chunk *fresh = poly_pool_chunk_alloc(pool, pool->max);

        if (fresh != NULL) {
            // Stage the carry into the fresh chunk while the old chain
            // (and old_last) are still alive, then swap chains.
            if (old_last != NULL) {
                memcpy(fresh->base, old_last, pool->item_size);
                old_last = fresh->base;
            }

            poly_pool_destroy(pool);
            pool->chunks = fresh;
        }
        // On allocation failure keep the chain; correctness is
        // unaffected, only locality.
    }

    atomic_store_explicit(&pool->next, 0, memory_order_relaxed);

    if (old_last != NULL) {
        void *slot0 = poly_pool_next(pool);
        if (slot0 != old_last)
            memmove(slot0, old_last, pool->item_size);
        pool->last = slot0;
    }
}

// Returns a contiguous run of items starting at `index`, capped at
// `count`; the actual run length is stored in *chunklen.
static void *poly_pool_contiguous(const poly_pool *pool, uint32_t index, uint32_t count, uint32_t *chunklen)
{
    const poly_pool_chunk *chunk = pool->chunks;

    while (index >= chunk->count) {
        index -= chunk->count;
        chunk = atomic_load_explicit(&chunk->next, memory_order_acquire);
    }

    *chunklen = rdp_umin32(count, chunk->count - index);
    return chunk->base + (size_t)index * pool->item_size;
}

/***************************************************************************
    POLY MANAGER
***************************************************************************/

//-------------------------------------------------
//  poly_manager_init - constructor
//-------------------------------------------------

int poly_manager_init(poly_manager *poly, struct rdp_t *cbarg)
{
    int i;

    memset(poly, 0, sizeof(*poly));
    poly->m_cbarg = cbarg;

    // create the work queue
    poly->m_queue = rdp_wq_alloc();
    if (poly->m_queue == NULL)
        return 1;

    // initialize the buckets to empty
    for (i = 0; i < TOTAL_BUCKETS; i++)
        poly->m_unit_bucket[i] = 0xffffffff;

    if (poly_pool_init(&poly->m_primitive, sizeof(primitive_info), false) ||
        poly_pool_init(&poly->m_object, sizeof(rdp_poly_state), true) ||
        poly_pool_init(&poly->m_unit, sizeof(work_unit), false)) {
        poly_manager_destroy(poly);
        return 1;
    }

    return 0;
}

//-------------------------------------------------
//  poly_manager_destroy - destructor
//-------------------------------------------------

void poly_manager_destroy(poly_manager *poly)
{
    // free the work queue
    if (poly->m_queue != NULL) {
        rdp_wq_free(poly->m_queue);
        poly->m_queue = NULL;
    }

    poly_pool_destroy(&poly->m_primitive);
    poly_pool_destroy(&poly->m_object);
    poly_pool_destroy(&poly->m_unit);
}

//-------------------------------------------------
//  poly_work_callback - process a work item
//-------------------------------------------------

static void *poly_work_callback(void *param, int threadid)
{
    while (1)
    {
        work_unit *unit = (work_unit *)param;
        primitive_info *primitive = unit->primitive;
        int count = atomic_load(&unit->count_next) & 0xff;
        uint32_t orig_count_next;
        int curscan;

        // if our previous item isn't done yet, enqueue this item to the end and proceed
        if (unit->previtem != 0xffffffff)
        {
            work_unit *prevunit = (work_unit *)poly_pool_byindex(&primitive->m_owner->m_unit, unit->previtem);
            if (atomic_load(&prevunit->count_next) != 0)
            {
                uint32_t unitnum = poly_pool_indexof(&primitive->m_owner->m_unit, unit);
                uint32_t new_count_next;

                // attempt to atomically swap in this new value
                do
                {
                    orig_count_next = atomic_load(&prevunit->count_next);
                    new_count_next = orig_count_next | (unitnum << 8);
                } while (!atomic_compare_exchange_weak_explicit(&prevunit->count_next,
                    &orig_count_next, new_count_next,
                    memory_order_release, memory_order_relaxed));

                // if we succeeded, skip out early so we can do other work
                if (orig_count_next != 0)
                    break;
            }
        }

        // iterate over extents
        for (curscan = 0; curscan < count; curscan++)
            (*primitive->m_callback)(primitive->m_cbarg, unit->scanline + curscan,
                &unit->extent[curscan], primitive->m_object, threadid);

        // set our count to 0 and re-fetch the original count value
        do
        {
            orig_count_next = atomic_load(&unit->count_next);
        } while (!atomic_compare_exchange_weak_explicit(&unit->count_next,
            &orig_count_next, 0, memory_order_release, memory_order_relaxed));

        // if we have no more work to do, do nothing
        orig_count_next >>= 8;
        if (orig_count_next == 0)
            break;
        param = poly_pool_byindex(&primitive->m_owner->m_unit, orig_count_next);
    }
    return NULL;
}

//-------------------------------------------------
//  queue_items - enqueue work items in
//  contiguous chunks
//-------------------------------------------------

static void queue_items(poly_manager *poly, uint32_t start)
{
    // do nothing if no queue; items will be processed on the next wait
    if (poly->m_queue == NULL)
        return;

    // enqueue the items in contiguous chunks
    while (start < poly->m_unit.next)
    {
        uint32_t chunk;
        work_unit *base = (work_unit *)poly_pool_contiguous(&poly->m_unit, start,
            poly->m_unit.next - start, &chunk);
        rdp_wq_submit(poly->m_queue, poly_work_callback,
            (int32_t)chunk, base, (int32_t)poly->m_unit.item_size);
        start += chunk;
    }
}

//-------------------------------------------------
//  poly_manager_wait - stall until all work is
//  complete
//-------------------------------------------------

void poly_manager_wait(poly_manager *poly)
{
    uint32_t unitnum;
    int i;

    // early out if no units outstanding
    if (poly->m_unit.next == 0)
        return;

    // wait for all pending work items to complete
    if (poly->m_queue != NULL)
        rdp_wq_wait(poly->m_queue);

    // if we don't have a queue, just run the whole list now
    else
        for (unitnum = 0; unitnum < poly->m_unit.next; unitnum++)
            poly_work_callback(poly_pool_byindex(&poly->m_unit, unitnum), 0);

    // clear the buckets
    for (i = 0; i < TOTAL_BUCKETS; i++)
        poly->m_unit_bucket[i] = 0xffffffff;

    // reset all the poly arrays
    poly_pool_reset(&poly->m_primitive);
    poly_pool_reset(&poly->m_object);
    poly_pool_reset(&poly->m_unit);
}

//-------------------------------------------------
//  poly_manager_object_next - allocate the next
//  object data block (object_data().next())
//-------------------------------------------------

rdp_poly_state *poly_manager_object_next(poly_manager *poly)
{
    return (rdp_poly_state *)poly_pool_next(&poly->m_object);
}

//-------------------------------------------------
//  primitive_alloc - allocate a new primitive
//-------------------------------------------------

static primitive_info *primitive_alloc(poly_manager *poly, poly_render_cb callback)
{
    // return and initialize the next one
    primitive_info *primitive = (primitive_info *)poly_pool_next(&poly->m_primitive);
    primitive->m_owner = poly;
    primitive->m_object = (rdp_poly_state *)poly->m_object.last;
    primitive->m_callback = callback;
    primitive->m_cbarg = poly->m_cbarg;
    return primitive;
}

//-------------------------------------------------
//  poly_manager_render_extents - perform a custom
//  render of an object, given specific extents
//  (render_extents<8>)
//-------------------------------------------------

void poly_manager_render_extents(poly_manager *poly, const poly_rect *cliprect,
    poly_render_cb callback, int startscanline, int numscanlines, const extent_t *extents)
{
    primitive_info *primitive;
    uint32_t startunit;
    int32_t scaninc = 1;
    int32_t v1yclip, v3yclip, curscan;

    // clip coordinates
    v1yclip = rdp_max32(startscanline, cliprect->min_y);
    v3yclip = rdp_min32(startscanline + numscanlines, cliprect->max_y + 1);
    if (v3yclip - v1yclip <= 0)
        return;

    // allocate and populate a new primitive
    primitive = primitive_alloc(poly, callback);

    // compute the X extents for each scanline
    startunit = poly->m_unit.next;
    for (curscan = v1yclip; curscan < v3yclip; curscan += scaninc)
    {
        uint32_t bucketnum = ((uint32_t)curscan / SCANLINES_PER_BUCKET) % TOTAL_BUCKETS;
        uint32_t unit_index = poly->m_unit.next;
        work_unit *unit = (work_unit *)poly_pool_next(&poly->m_unit);
        int32_t count;
        int extnum;

        // determine how much to advance to hit the next bucket
        scaninc = SCANLINES_PER_BUCKET - (uint32_t)curscan % SCANLINES_PER_BUCKET;

        // fill in the work unit basics
        count = rdp_min32(v3yclip - curscan, scaninc);
        unit->primitive = primitive;
        atomic_store(&unit->count_next, (uint32_t)count);
        unit->scanline = curscan;
        unit->previtem = poly->m_unit_bucket[bucketnum];
        poly->m_unit_bucket[bucketnum] = unit_index;

        // iterate over extents
        for (extnum = 0; extnum < count; extnum++)
        {
            const extent_t *srcextent = &extents[(curscan + extnum) - startscanline];
            int32_t istartx = srcextent->startx, istopx = srcextent->stopx;
            extent_t *extent;
            int paramnum;

            // apply left/right clipping
            istartx = rdp_max32(istartx, cliprect->min_x);
            istartx = rdp_min32(istartx, cliprect->max_x + 1);
            istopx = rdp_max32(istopx, cliprect->min_x);
            istopx = rdp_min32(istopx, cliprect->max_x + 1);

            extent = &unit->extent[extnum];
            extent->startx = (int16_t)istartx;
            extent->stopx = (int16_t)istopx;

            // fill in the parameters for the extent
            for (paramnum = 0; paramnum < POLY_MAX_PARAMS; paramnum++)
            {
                extent->param[paramnum].start = srcextent->param[paramnum].start;
                extent->param[paramnum].dpdx = srcextent->param[paramnum].dpdx;
            }
            extent->userdata = srcextent->userdata;
        }
    }

    // enqueue the work items
    queue_items(poly, startunit);
}
