//unit:rdram-private: RDRAM data is private to the RI, MI, the loader and the
//not-yet-converted VI and RDP (ADR 0001 Decision 2). rdram-private.cmake
//compiles this file twice: with RDRAM_PRIVATE_FRIEND the access goes through
//the host Loader and must compile; without it a device-side function reads
//rdram.ram the way the DMA engines did before T8 and must fail to compile on
//the access check, not on anything else.

#include <n64/n64.hpp>

namespace ares::Nintendo64 {

auto rdramPrivateProbe() -> u64 {
#if defined(RDRAM_PRIVATE_FRIEND)
  return Loader::ram().read<Word>(0, RBusDevice::PI_DMA);
#else
  return rdram.ram.read<Word>(0, RBusDevice::PI_DMA);
#endif
}

}
