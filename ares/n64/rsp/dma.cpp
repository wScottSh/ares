//SP DMA as an RI bus client (ADR 0001 RSP seam, sketch rsp/actor.hpp SpDma).
//A transfer is LEN+1 bytes per row, COUNT+1 rows, SKIP between rows. Each row
//goes out as bursts of at most sp.dma-burst bytes that never cross a 2 KiB
//RDRAM row, one in flight at a time; the next is posted when the previous one's
//data has moved, so the rate is the RI's (wire time plus the fitted
//ri.overhead-*). The RI moves each burst's bytes at its grant and the
//registers advance with it, independent of where the RSP's issue pairs fall.

auto RSP::dmaTransferStart(Thread& thread) -> void {
  if(dma.busy.any() || !dma.full.any()) return;
  dma.begin(thread.clock);
}

auto RSP::DMA::begin(Clock at) -> void {
  current = pending;
  busy    = full;
  full    = {0,0};
  rowLeft = current.length + 8;  //LEN counts 8-byte units, low bits ignored
  post(at);
}

auto RSP::DMA::post(Clock at) -> void {
  u32 bytes = RiBus::split(current.dramAddress, rowLeft);
  if(bytes > Timing::Behavior::SpDmaBurst) bytes = Timing::Behavior::SpDmaBurst;
  auto direction = busy.read ? RiBus::Direction::Read : RiBus::Direction::Write;
  ri.post({(u32)current.dramAddress, (u8)bytes, direction, RiBus::Requester::SpDma, 0}, at);
}

//Busy until the last burst of the transfer has landed.
auto RSP::DMA::busyAt(Clock at) const -> bool {
  return busy.any() || at < done;
}

//IMEM and DMEM store words differently; both go through their own Word accessors.
template<typename Memory> static auto spCopy(Memory& mem, u32 pbus, u8* bytes, u32 count, bool toMemory) -> void {
  for(u32 i = 0; i < count; i += 4) {
    u32 address = (pbus + i) & 0xffc;
    if(toMemory) {
      mem.template write<Word>(address, bytes[i + 0] << 24 | bytes[i + 1] << 16 | bytes[i + 2] << 8 | bytes[i + 3]);
    } else {
      u32 w = mem.template read<Word>(address);
      bytes[i + 0] = w >> 24; bytes[i + 1] = w >> 16; bytes[i + 2] = w >> 8; bytes[i + 3] = w;
    }
  }
}

auto RSP::DMA::copy(u32 bytes, bool toMemory) -> void {
  if(current.pbusRegion) spCopy(rsp.imem, current.pbusAddress, staging, bytes, toMemory);
  else                   spCopy(rsp.dmem, current.pbusAddress, staging, bytes, toMemory);
}

auto RSP::DMA::buffer(const RiBus::Burst& b) -> void* {
  if(b.direction == RiBus::Direction::Write) copy(b.bytes, false);
  return staging;
}

auto RSP::DMA::granted(const RiBus::Grant& g) -> void {
  const u32 bytes = g.burst.bytes;
  if(g.burst.direction == RiBus::Direction::Read) {
    copy(bytes, true);
    if(system.homebrewMode) {
      for(u32 i = 0; i < bytes; i += 8) {
        rsp.debugger.dmaReadWord(current.dramAddress + i, current.pbusRegion, current.pbusAddress + i);
      }
    }
  }
  current.dramAddress += bytes;
  current.pbusAddress += bytes;
  rowLeft -= bytes;
  done = g.dataEnd;
  if(rowLeft) return post(g.dataEnd);
  if(current.count) {
    current.count -= 1;
    current.dramAddress += current.skip;
    rowLeft = current.length + 8;
    return post(g.dataEnd);
  }
  busy = {0,0};
  current.length = 0xFF8;
  //DMA_FULL clears a few clocks before the previous transfer ends (n64brew RSP Interface)
  if(full.any()) begin(g.dataEnd);
}
