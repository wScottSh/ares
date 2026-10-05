/*
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
//
// rdp/rdp_wqueue.h: Render work queue.
//
// CEN64: Cycle-Accurate Nintendo 64 Emulator.
//
// The subset of work-queue behaviour the poly manager needs: a
// multi-consumer queue of auto-released items, batch submission, and a
// wait that drains the queue with the calling thread helping. The
// intra-primitive ordering guarantees the RDP relies on come from the
// poly manager's own atomics (work_unit chaining), not the queue, so
// FIFO dispatch with completion counting is sufficient here.
//

#ifndef RDP_WQUEUE_H
#define RDP_WQUEUE_H

#include <stdint.h>

typedef struct rdp_wq_t rdp_wq_t;

// Work item callback: receives the item parameter and the worker's
// thread index (0 = the thread calling rdp_wq_wait; workers are
// numbered from 1). The poly manager uses threadid to select
// per-thread scratch state.
typedef void *(*rdp_wq_fn)(void *param, int threadid);

// Maximum threadid + 1 ever passed to a callback; bounds the
// per-thread arrays indexed by it.
#define RDP_WQ_MAX_THREADS 4

/* Worker count. Left undefined, the queue sizes itself to the host's
   logical processor count, capped at RDP_WQ_MAX_THREADS. Build with
   -DRDP_WQ_THREADS=n to pin it and skip the probe entirely; n is still
   capped. */
#if defined(RDP_WQ_THREADS) && RDP_WQ_THREADS < 1
#error "RDP_WQ_THREADS must be at least 1"
#endif

// Allocates a queue with min(hardware threads, RDP_WQ_MAX_THREADS) - 1
// workers; the submitting thread contributes during wait. The
// RDP_THREADS environment variable, if set, overrides the detected
// processor count. Returns NULL on failure.
rdp_wq_t *rdp_wq_alloc(void);

// Waits for all outstanding items, stops the workers, and frees the
// queue.
void rdp_wq_free(rdp_wq_t *queue);

// Queues numitems work items sharing one callback, with parameters
// parambase, parambase + paramstep, ... Items are released
// automatically on completion. Returns 0 on success.
int rdp_wq_submit(rdp_wq_t *queue, rdp_wq_fn callback,
    int32_t numitems, void *parambase, int32_t paramstep);

// Blocks until every queued item has completed, processing items on
// the calling thread as threadid 0 while any remain unclaimed.
void rdp_wq_wait(rdp_wq_t *queue);

// Nonzero while any queued item has not yet completed. Takes the queue
// lock briefly; intended for the producer thread at command granularity
// (e.g. deciding whether a TMEM snapshot is required before a load).
int rdp_wq_busy(rdp_wq_t *queue);

#endif
