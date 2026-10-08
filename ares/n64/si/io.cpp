auto SI::readWord(u32 address, Thread& thread) -> u32 {
  if(address <= 0x048f'ffff) return ioRead(address);

  if (unlikely(io.ioBusy)) {
    writeForceFinish(); //technically, we should wait until EventKind::SI_BUS_Write
    return io.busLatch;
  }
  //RCP::read charged a register read; a PIF RAM read costs cpu.pif-ram-read in all (n64-systembench SI I/O R)
  if((address & 0x7ff) >= 0x7c0) thread.step(Timing::Behavior::CpuPifRamRead - Timing::Behavior::CpuRcpRegisterRead);
  return pif.read<Word>(address);
}

auto SI::ioRead(u32 address) -> u32 {
  address = (address & 0x1f) >> 2;
  n32 data;

  if(address == 0) {
    //SI_DRAM_ADDRESS
    data.bit(0,23) = io.dramAddress;
  }

  if(address == 1) {
    //SI_PIF_ADDRESS_READ64B
    data.bit(0,31) = io.readAddress;
  }

  if(address == 2) {
    //SI_INT_ADDRESS_WRITE64B
  }

  if(address == 3) {
    //SI_RESERVED
  }

  if(address == 4) {
    //SI_PIF_ADDRESS_WRITE64B
    data.bit(0,31) = io.writeAddress;
  }

  if(address == 5) {
    //SI_INT_ADDRESS_READ64B
  }

  if(address == 6) {
    //SI_STATUS
    data.bit( 0)    = io.dmaBusy;
    data.bit( 1)    = io.ioBusy;
    data.bit( 2)    = io.readPending;
    data.bit( 3)    = io.dmaError;
    data.bit( 4, 7) = io.pchState;
    data.bit( 8,11) = io.dmaState;
    data.bit(12)    = io.interrupt;
  }

  debugger.io(Read, address, data);
  return data;
}

auto SI::writeWord(u32 address, u32 data, Thread& thread) -> void {
  if(address <= 0x048f'ffff) return ioWrite(address, data, thread);

  if(io.ioBusy) return;
  io.ioBusy = 1;
  io.dmaBusy = 1;
  io.pchState = 0xb;
  io.dmaState = 0x9;
  io.busLatch = data;
  //si.io-busy: n64-systembench SI I/O W, the write to SI_STATUS idle
  scheduleAfter(EventKind::SI_BUS_Write, Timing::Behavior::SiIoBusy);
  return pif.write<Word>(address, data);
}

auto SI::ioWrite(u32 address, u32 data_, Thread& thread) -> void {
  address = (address & 0x1f) >> 2;
  n32 data = data_;

  if(address == 0) {
    //SI_DRAM_ADDRESS
    io.dramAddress = data.bit(0,23) & ~7;
  }

  if(address == 1) {
    //SI_PIF_ADDRESS_READ64B
    io.readAddress = data.bit(0,31) & ~1;
    io.dmaBusy = 1;
    io.dmaState = 1;
    io.pchState = 4;
    int cycles = pif.estimateTiming();
    dma.toRdram = 1;
    dma.phase = DMA::Phase::Joybus;
    scheduleAfter(EventKind::SI_DMA_Read, rclk(cycles));
  }

  if(address == 2) {
    //SI_INT_ADDRESS_WRITE4B
  }

  if(address == 3) {
    //SI_RESERVED
  }

  if(address == 4) {
    //SI_PIF_ADDRESS_WRITE64B
    io.writeAddress = data.bit(0,31) & ~1;
    io.dmaBusy = 1;
    io.dmaState = 4;
    io.pchState = 1;
    dma.toRdram = 0;
    dma.offset = 0;
    dmaPost(thread.clock);
    //the PIF ROM range (below PIF RAM's 0x7c0) ends sooner: n64-systembench SI DMA W ROM
    bool rom = (io.writeAddress & 0x7ff) < 0x7c0;
    scheduleAfter(EventKind::SI_DMA_Write, rom ? Timing::Behavior::SiWrite64Rom : Timing::Behavior::SiWrite64);
  }

  if(address == 5) {
    //SI_INT_ADDRESS_READ4B
  }

  if(address == 6) {
    //SI_STATUS
    io.interrupt = 0;
    mi.lower(MI::IRQ::SI);
  }

  debugger.io(Write, address, data);
}

auto SI::writeFinished() -> void {
  io.ioBusy = 0;
  io.dmaBusy = 0;
  io.pchState = 0;
  io.dmaState = 0;
  io.interrupt = 1;
  mi.raise(MI::IRQ::SI);
}

auto SI::writeForceFinish() -> void {
  io.ioBusy = 0;
  cancelEvent(EventKind::SI_BUS_Write);
}
