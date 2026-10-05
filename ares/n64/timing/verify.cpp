#include <n64/n64.hpp>

#define XXH_INLINE_ALL
#include <xxhash.h>

namespace ares::Nintendo64 {

Timing::TraceHash traceHash;

namespace Timing {

auto TraceHash::fieldBoundary() -> u64 {
  state.setWriting();
  system.serialize(state, false);
  rolling = XXH3_64bits_withSeed(state.data(), state.size(), rolling);
  return rolling;
}

}

}
