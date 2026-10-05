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
// rdp/rdp_wqueue.c: Render work queue.
//
// CEN64: Cycle-Accurate Nintendo 64 Emulator.
//

#include <pthread.h>
#include <stdlib.h>

#ifndef RDP_WQ_THREADS
#if defined(_WIN32)
#include <windows.h>
#elif defined(__APPLE__)
#define _DARWIN_C_SOURCE
#include <sys/types.h>
#include <sys/sysctl.h>
#else
#include <unistd.h>
#endif
#endif

#ifdef CEN64_DEVPROF
#include "device/devprof.h"
#endif
#include "rdp_wqueue.h"

// One pending work item.
typedef struct rdp_wq_item {
    rdp_wq_fn callback;
    void *param;
} rdp_wq_item;

struct rdp_wq_t {
    pthread_mutex_t lock;
    pthread_cond_t  items_avail;    // signalled when items are enqueued
    pthread_cond_t  all_done;       // signalled when outstanding hits zero

    rdp_wq_item *ring;                // FIFO ring buffer of pending items
    uint32_t ring_cap;              // capacity (power of two)
    uint32_t head;                  // dequeue position
    uint32_t tail;                  // enqueue position

    uint32_t outstanding;           // items enqueued but not yet completed
    int exiting;                    // workers should terminate

    pthread_t threads[RDP_WQ_MAX_THREADS];
    int numthreads;
};

// Worker count, capped at RDP_WQ_MAX_THREADS. See RDP_WQ_THREADS.
static int rdp_wq_num_processors(void)
{
    long n;

#ifdef RDP_WQ_THREADS
    n = RDP_WQ_THREADS;
#elif defined(_WIN32)
    SYSTEM_INFO info;
    GetSystemInfo(&info);
    n = (long)info.dwNumberOfProcessors;
#elif defined(__APPLE__)
    int count = 0;
    size_t size = sizeof(count);
    if (sysctlbyname("hw.logicalcpu", &count, &size, NULL, 0) != 0)
        count = 0;
    n = count;
#else
    n = sysconf(_SC_NPROCESSORS_ONLN);
#endif

    if (n < 1)
        n = 1;
    if (n > RDP_WQ_MAX_THREADS)
        n = RDP_WQ_MAX_THREADS;
    return (int)n;
}

// Dequeues and runs one item with the queue lock held on entry and
// exit; returns 0 if the ring was empty. Completion of the final
// outstanding item broadcasts all_done.
static int rdp_wq_run_one(rdp_wq_t *queue, int threadid)
{
    rdp_wq_item item;

    if (queue->head == queue->tail)
        return 0;

    item = queue->ring[queue->head & (queue->ring_cap - 1)];
    queue->head++;

    pthread_mutex_unlock(&queue->lock);
    (*item.callback)(item.param, threadid);
    pthread_mutex_lock(&queue->lock);

    if (--queue->outstanding == 0)
        pthread_cond_broadcast(&queue->all_done);

    return 1;
}

static void *rdp_wq_worker(void *opaque_pair)
{
    // opaque_pair packs {queue, threadid} allocated by alloc().
    void **pair = (void **)opaque_pair;
    rdp_wq_t *queue = (rdp_wq_t *)pair[0];
    int threadid = (int)(intptr_t)pair[1];
    free(pair);

    pthread_mutex_lock(&queue->lock);
    for (;;) {
        if (rdp_wq_run_one(queue, threadid))
            continue;
        if (queue->exiting)
            break;
        pthread_cond_wait(&queue->items_avail, &queue->lock);
    }
    pthread_mutex_unlock(&queue->lock);
    return NULL;
}

rdp_wq_t *rdp_wq_alloc(void)
{
    rdp_wq_t *queue;
    int numprocs, i;

    queue = (rdp_wq_t *)calloc(1, sizeof(*queue));
    if (queue == NULL)
        return NULL;

    queue->ring_cap = 1024;
    queue->ring = (rdp_wq_item *)malloc(queue->ring_cap * sizeof(rdp_wq_item));
    if (queue->ring == NULL) {
        free(queue);
        return NULL;
    }

    if (pthread_mutex_init(&queue->lock, NULL) ||
        pthread_cond_init(&queue->items_avail, NULL) ||
        pthread_cond_init(&queue->all_done, NULL)) {
        free(queue->ring);
        free(queue);
        return NULL;
    }

    // numprocs - 1 workers; the waiting thread is threadid 0.
    numprocs = rdp_wq_num_processors();
    queue->numthreads = numprocs - 1;
    if (queue->numthreads > RDP_WQ_MAX_THREADS - 1)
        queue->numthreads = RDP_WQ_MAX_THREADS - 1;

    for (i = 0; i < queue->numthreads; i++) {
        void **pair = (void **)malloc(2 * sizeof(void *));
        if (pair == NULL || (pair[0] = queue, pair[1] = (void *)(intptr_t)(i + 1),
            pthread_create(&queue->threads[i], NULL, rdp_wq_worker, pair))) {
            free(pair);
            queue->numthreads = i;
            break;
        }
    }

    return queue;
}

void rdp_wq_free(rdp_wq_t *queue)
{
    int i;

    if (queue == NULL)
        return;

    rdp_wq_wait(queue);

    pthread_mutex_lock(&queue->lock);
    queue->exiting = 1;
    pthread_cond_broadcast(&queue->items_avail);
    pthread_mutex_unlock(&queue->lock);

    for (i = 0; i < queue->numthreads; i++)
        pthread_join(queue->threads[i], NULL);

    pthread_mutex_destroy(&queue->lock);
    pthread_cond_destroy(&queue->items_avail);
    pthread_cond_destroy(&queue->all_done);
    free(queue->ring);
    free(queue);
}

int rdp_wq_submit(rdp_wq_t *queue, rdp_wq_fn callback,
    int32_t numitems, void *parambase, int32_t paramstep)
{
    int32_t i;

    if (numitems <= 0)
        return 0;

    pthread_mutex_lock(&queue->lock);

    // Grow the ring if the pending backlog would not fit.
    {
        uint32_t pending = queue->tail - queue->head;
        uint32_t needed = pending + (uint32_t)numitems;
        if (needed > queue->ring_cap) {
            uint32_t newcap = queue->ring_cap;
            rdp_wq_item *newring;
            uint32_t j;
            while (newcap < needed)
                newcap <<= 1;
            newring = (rdp_wq_item *)malloc(newcap * sizeof(rdp_wq_item));
            if (newring == NULL) {
                pthread_mutex_unlock(&queue->lock);
                return 1;
            }
            for (j = 0; j < pending; j++)
                newring[j] = queue->ring[(queue->head + j) & (queue->ring_cap - 1)];
            free(queue->ring);
            queue->ring = newring;
            queue->ring_cap = newcap;
            queue->head = 0;
            queue->tail = pending;
        }
    }

    for (i = 0; i < numitems; i++) {
        rdp_wq_item *item = &queue->ring[queue->tail & (queue->ring_cap - 1)];
        item->callback = callback;
        item->param = (uint8_t *)parambase + (size_t)i * (size_t)paramstep;
        queue->tail++;
    }
    queue->outstanding += (uint32_t)numitems;

    if (queue->numthreads > 0) {
        if (numitems == 1)
            pthread_cond_signal(&queue->items_avail);
        else
            pthread_cond_broadcast(&queue->items_avail);
    }

    pthread_mutex_unlock(&queue->lock);
    return 0;
}

int rdp_wq_busy(rdp_wq_t *queue)
{
    int busy;

    pthread_mutex_lock(&queue->lock);
    busy = queue->outstanding != 0;
    pthread_mutex_unlock(&queue->lock);

    return busy;
}

void rdp_wq_wait(rdp_wq_t *queue)
{
#ifdef CEN64_DEVPROF
    uint64_t dp_d0 = devprof_now();
    uint64_t dp_sleep = 0;
    uint64_t dp_parks = 0;
#endif

    pthread_mutex_lock(&queue->lock);

    // Help drain the ring as threadid 0, then sleep until the last
    // in-flight item (possibly on a worker) completes.
    while (queue->outstanding != 0) {
        if (rdp_wq_run_one(queue, 0))
            continue;
#ifdef CEN64_DEVPROF
        {
            uint64_t dp_s0 = devprof_now();
            dp_parks++;
            pthread_cond_wait(&queue->all_done, &queue->lock);
            dp_sleep += devprof_now() - dp_s0;
        }
#else
        pthread_cond_wait(&queue->all_done, &queue->lock);
#endif
    }

    pthread_mutex_unlock(&queue->lock);

#ifdef CEN64_DEVPROF
    devprof_rdp_drain(devprof_now() - dp_d0, dp_sleep, dp_parks);
#endif
}
