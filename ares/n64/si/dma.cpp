//SI DMA as an RI bus client (sketch devices/events.hpp SiDma). The RDRAM side
//is 64 bytes, one burst unless it crosses a 2 KiB row (MiSTer SI.vhd moves
//64 B; US 6,166,748 "64-byte"). READ64B runs the PIF's joybus phase
//(pif.estimateTiming), then writes the PIF RAM to RDRAM; the interrupt follows
//the last burst. WRITE64B reads RDRAM at its start and hands the bytes to the
//PIF when si.write64 (n64-systembench's measured total) has elapsed, or when
//the read lands if contention made it later.

auto SI::dmaPost(Clock at) -> void {
  u32 address = io.dramAddress + dma.offset;
  u32 bytes = RiBus::split(address, 64 - dma.offset);
  auto direction = dma.toRdram ? RiBus::Direction::Write : RiBus::Direction::Read;
  dma.phase = DMA::Phase::Posted;
  ri.post({address, (u8)bytes, direction, RiBus::Requester::SiDma, 0}, at);
}

auto SI::DMA::buffer(const RiBus::Burst&) -> void* {
  return block + offset;
}

auto SI::DMA::granted(const RiBus::Grant& g) -> void {
  if(phase != Phase::Posted && phase != Phase::Due) return;
  offset += g.burst.bytes;
  if(offset < 64) {
    bool due = phase == Phase::Due;
    si.dmaPost(g.dataEnd);
    if(due) phase = Phase::Due;
    return;
  }
  if(toRdram || phase == Phase::Due) {
    phase = Phase::Landed;
    return timeline.schedule({g.dataEnd, (u32)(toRdram ? EventKind::SI_DMA_Read : EventKind::SI_DMA_Write)});
  }
  phase = Phase::Landed;
}

//The SI_DMA_Read and SI_DMA_Write events.
auto SI::dmaStep() -> void {
  Clock now = timeline.now(Clock{});
  if(dma.phase == DMA::Phase::Joybus) {
    pif.dmaRead(io.readAddress, dma.block);
    dma.offset = 0;
    return dmaPost(now);
  }
  if(dma.phase == DMA::Phase::Posted) {
    dma.phase = DMA::Phase::Due;
    return;
  }
  if(dma.phase != DMA::Phase::Landed) return;
  if(!dma.toRdram) pif.dmaWrite(io.writeAddress, dma.block);
  dmaFinish();
}

auto SI::dmaFinish() -> void {
  dma.phase = DMA::Phase::Idle;
  io.dmaBusy = 0;
  io.pchState = 0;
  io.dmaState = 0;
  io.interrupt = 1;
  mi.raise(MI::IRQ::SI);
}
