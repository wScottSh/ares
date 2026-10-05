//PI DMA as an RI bus client, block by block (dma-timing.md; n64brew Parallel
//Interface, DMA Transfers). A transfer moves through the PI's 128 B buffer,
//each block clipped at the 2 KiB RDRAM row. Cart to RDRAM: a block fills from
//the cart bus at its domain's BSD timing (14 + LAT + 1 per page address,
//PWD + 1 + RLS + 1 per halfword), then goes to RDRAM as one write burst, and the
//next block starts once that burst has landed and the PI has finished its
//writeback. PI_CART_ADDR advances as a block fills, PI_DRAM_ADDR when it lands
//("PI_CART_ADDR moving forward, and then PI_DRAM_ADDR catching up with a leap").
//RDRAM to cart is the mirror: a read burst, then the block drains to the cart
//bus. The interrupt follows the last block.

//pi.block-writeback is a whole block's writeback (fit to n64-systembench); the
//RI supplies its wire part, so the PI's own share is the rest. A block ends on
//the cart bus's RCP clock, so the deciding rclk edge is on average half a clock away.
static constexpr Clock PiEdgeWait = {Timing::UnitsPerRclk / 2};
static constexpr auto piBlockPath(RiBus::Direction direction) -> Clock {
  auto octs = Timing::Behavior::PiBlockBytes / 8;
  return Timing::Behavior::PiBlockWriteback - Timing::Behavior::RiRequestLatency - PiEdgeWait
       - RiBus::wire(direction, octs, RiBus::Row::Hit);
}

auto PI::pageSetup(u32 address) -> Clock {
  busAddress(address);
  return Timing::Behavior::PiPageSetup + rclk(bsdForAddress(address).latency);
}

auto PI::halfwordTime(u32 address) -> Clock {
  auto& bsd = bsdForAddress(address);
  return rclk(bsd.pulseWidth + bsd.releaseDuration) + Timing::Behavior::PiHalfwordBias;
}

auto PI::dmaStart(bool toRdram, Clock at) -> void {
  io.dmaBusy = 1;
  dma.toRdram = toRdram;
  dma.firstBlock = 1;
  dma.addressSelected = 0;
  dma.maxBlockSize = Timing::Behavior::PiBlockBytes;
  dma.offset = 0;
  if(toRdram) {
    dma.length = io.writeLength + 1;
    return dmaFill(at);
  }
  io.readLength = (io.readLength | 1) + 1;
  dma.length = io.readLength;
  dmaPostRead(at);
}

//Cart to RDRAM: one block from the cart bus into the buffer. The block, byte
//count and register quirks are n64_pi_dma_test's hardware results as ares
//models them (misaligned and short first blocks, the 8-byte realign).
auto PI::dmaFill(Clock at) -> void {
  auto& bsd = bsdForAddress(io.pbusAddress);
  u32 pageMask = (1 << (bsd.pageSize + 2)) - 1;
  i32 misalign = io.dramAddress & 7;
  i32 distEndOfRow = 0x800 - (io.dramAddress & 0x7ff);
  i32 curLen = min(dma.length, min((i32)dma.maxBlockSize - misalign, distEndOfRow));

  Clock fill;
  for(i32 i = 0; i < curLen; i += 2) {
    if(!dma.addressSelected || (io.pbusAddress & pageMask) == 0) {
      fill += pageSetup(io.pbusAddress);
      dma.addressSelected = 1;
    }
    fill += halfwordTime(io.pbusAddress);
    u16 data = busReadHalf();
    dma.block[i + 0] = data >> 8;
    dma.block[i + 1] = data >> 0;
    io.pbusAddress += 2;
    dma.length -= 2;
  }

  i32 bytes = curLen - misalign;
  if(!(dma.firstBlock && curLen < 127 - misalign)) bytes = (bytes + 1) & ~1;
  dma.address = io.dramAddress;
  dma.bytes = max(bytes, 0);
  dma.lastLen = curLen;
  dma.misalign = misalign;
  dma.maxBlockSize = distEndOfRow < 8 ? 128 - misalign : 128;
  dma.firstBlock = 0;
  dma.phase = DMA::Phase::Filling;
  timeline.schedule({at + fill, (u32)EventKind::PI_DMA_Write});
}

//RDRAM to cart: one block's read burst.
auto PI::dmaPostRead(Clock at) -> void {
  dma.address = io.dramAddress + dma.offset;
  dma.bytes = RiBus::split(dma.address, dma.length);
  dma.phase = DMA::Phase::Posted;
  ri.post({dma.address, (u8)dma.bytes, RiBus::Direction::Read, RiBus::Requester::PiDma, 0}, at);
}

//The PI_DMA_Read and PI_DMA_Write events: a block finished filling, or the PI
//finished with a block and starts the next one or ends the transfer.
auto PI::dmaStep() -> void {
  Clock now = timeline.now(Clock{});
  if(dma.phase == DMA::Phase::Filling) {
    dma.phase = DMA::Phase::Posted;
    if(dma.bytes) return ri.post({dma.address, (u8)dma.bytes, RiBus::Direction::Write, RiBus::Requester::PiDma, 0}, now);
    return dmaLanded(now);
  }
  if(dma.phase != DMA::Phase::Settling) return;
  if(dma.length > 0) return dma.toRdram ? dmaFill(now) : dmaPostRead(now);
  dma.phase = DMA::Phase::Idle;
  dmaFinished();
}

//Cart to RDRAM: the block is in RDRAM; PI_DRAM_ADDR leaps to the next octbyte.
auto PI::dmaLanded(Clock at) -> void {
  io.dramAddress = (dma.address + dma.bytes + 7) & ~7;
  io.writeLength = dma.lastLen <= 8 ? 127 - dma.misalign : 127;
  dma.phase = DMA::Phase::Settling;
  timeline.schedule({at + piBlockPath(RiBus::Direction::Write), (u32)EventKind::PI_DMA_Write});
}

auto PI::DMA::buffer(const RiBus::Burst&) -> void* {
  return block;
}

auto PI::DMA::granted(const RiBus::Grant& g) -> void {
  if(phase != Phase::Posted) return;  //PI_STATUS reset the DMA while this burst waited
  if(toRdram) return pi.dmaLanded(g.dataEnd);

  //RDRAM to cart: the block drains to the cart bus, a page address at the
  //transfer's start and at each page boundary.
  auto& bsd = pi.bsdForAddress(pi.io.pbusAddress);
  u32 pageMask = (1 << (bsd.pageSize + 2)) - 1;
  Clock drain;
  for(u32 i = 0; i < bytes; i += 2) {
    u32 cursor = pi.io.pbusAddress + offset + i;
    if(offset + i == 0 || (cursor & pageMask) == 0) drain += pi.pageSetup(cursor);
    drain += pi.halfwordTime(cursor);
    pi.busWriteHalf(block[i] << 8 | block[i + 1]);
  }
  offset += bytes;
  length -= bytes;
  phase = Phase::Settling;
  timeline.schedule({g.dataEnd + piBlockPath(RiBus::Direction::Read) + drain, (u32)EventKind::PI_DMA_Read});
}

auto PI::dmaFinished() -> void {
  io.dmaBusy = 0;
  io.interrupt = 1;
  mi.raise(MI::IRQ::PI);
}
