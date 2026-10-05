/* Stands in for cen64's common/common.h, common/debug.h and
   common/endian.h in the ares port of the cen64-jgemu RDP. ares only
   builds on little-endian hosts, so the host byte order is fixed here.

   The sub-word XORs keep cen64's little-endian values because the TMEM
   image the texture pipe indexes with them is internal to the renderer
   (loads and fetches use the same constants). RDRAM access does not go
   through these: see the RREAD and RWRITE macros in rdp_core.h, which
   address ares' word-swizzled RDRAM layout directly. */

#ifndef RDP_ENGINE_CEN64_COMPAT_H
#define RDP_ENGINE_CEN64_COMPAT_H

#include <stdint.h>

#include "rdp.h"

#define CEN64_LITTLE_ENDIAN 1

#define BYTE_IN_HWORD_XOR  1
#define BYTE_IN_WORD_XOR   3
#define HWORD_IN_WORD_XOR  1
#define WORD_IN_DWORD_XOR  4

static inline uint16_t byteswap_16(uint16_t hword) { return __builtin_bswap16(hword); }
static inline uint32_t byteswap_32(uint32_t word)  { return __builtin_bswap32(word); }
static inline uint64_t byteswap_64(uint64_t dword) { return __builtin_bswap64(dword); }

#define cen64_flatten __attribute__((flatten))
#define likely(expr)   __builtin_expect(!!(expr), 1)
#define unlikely(expr) __builtin_expect(!!(expr), 0)

/* Levels in rdp.h (enum cen64_loglevel). Defined in rdp.c; defaults to
   stderr until the host installs its own sink with rdp_render_set_log. */
extern void (*cen64_log)(int, const char *, ...);

#endif
