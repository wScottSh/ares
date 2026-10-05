#include <n64/n64.hpp>

#define XXH_INLINE_ALL
#include <xxhash.h>

namespace ares::Nintendo64 {

Timing::TraceHash traceHash;

namespace Timing {

auto TraceHash::fold(u64 pclock, ActorId actor, u8 kind, u64 payload) -> void {
  const u64 record[3] = {pclock, (u64)actor << 8 | kind, payload};
  rolling = XXH3_64bits_withSeed(record, sizeof(record), rolling);
}

auto TraceHash::fieldBoundary() -> u64 {
  auto state = system.serialize(false);
  rolling = XXH3_64bits_withSeed(state.data(), state.size(), rolling);
  return rolling;
}

}

}
