auto SI::serialize(serializer& s) -> void {
  s(io.dramAddress);
  s(io.readAddress);
  s(io.writeAddress);
  s(io.busLatch);
  s(io.dmaBusy);
  s(io.ioBusy);
  s(io.readPending);
  s(io.pchState);
  s(io.dmaState);
  s(io.dmaError);
  s(io.interrupt);

  s((u8&)dma.phase);
  s(dma.toRdram);
  s(dma.offset);
  s(dma.block);
}
