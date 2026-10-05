auto PI::serialize(serializer& s) -> void {
  s(io.dmaBusy);
  s(io.ioBusy);
  s(io.error);
  s(io.interrupt);
  s(io.dramAddress);
  s(io.pbusAddress);
  s(io.readLength);
  s(io.writeLength);
  s(io.busLatch);
  s(io.originPc);

  s(bsd1.latency);
  s(bsd1.pulseWidth);
  s(bsd1.pageSize);
  s(bsd1.releaseDuration);

  s(bsd2.latency);
  s(bsd2.pulseWidth);
  s(bsd2.pageSize);
  s(bsd2.releaseDuration);

  s(busDevice);
  s(busTiming.latency);
  s(busTiming.pulseWidth);
  s(busTiming.releaseDuration);

  s((u8&)dma.phase);
  s(dma.toRdram);
  s(dma.firstBlock);
  s(dma.addressSelected);
  s(dma.length);
  s(dma.maxBlockSize);
  s(dma.offset);
  s(dma.address);
  s(dma.bytes);
  s(dma.lastLen);
  s(dma.misalign);
  s(dma.block);
}
