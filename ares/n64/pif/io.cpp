auto PIF::readInt(u32 address) -> u32 {
  address &= 0x7ff;
  if(address <= 0x7bf) {
    if(io.romLockout) return 0;
    return rom.read<Word>(address);
  }
  return ram.read<Word>(address);
}

auto PIF::writeInt(u32 address, u32 data) -> void {
  address &= 0x7ff;
  if(address <= 0x7bf) {
    if(io.romLockout) return;
    return rom.write<Word>(address, data);
  }
  return ram.write<Word>(address, data);
}

auto PIF::readWord(u32 address) -> u32 {
  intA(Read, Size4);
  return readInt(address);
}

auto PIF::writeWord(u32 address, u32 data) -> void {
  writeInt(address, data);  
  intA(Write, Size4);
  mainHLE();
}

//SI DMA's PIF side; the SI moves the 64 bytes through the RI (si/dma.cpp).
auto PIF::dmaRead(u32 address, u8* bytes) -> void {
  intA(Read, Size64);
  for(u32 offset = 0; offset < 64; offset += 4) {
    u32 data = readInt(address + offset);
    bytes[offset + 0] = data >> 24; bytes[offset + 1] = data >> 16; bytes[offset + 2] = data >> 8; bytes[offset + 3] = data;
  }
}

auto PIF::dmaWrite(u32 address, const u8* bytes) -> void {
  for(u32 offset = 0; offset < 64; offset += 4) {
    u32 data = bytes[offset + 0] << 24 | bytes[offset + 1] << 16 | bytes[offset + 2] << 8 | bytes[offset + 3];
    writeInt(address + offset, data);
  }
  intA(Write, Size64);
  mainHLE();
}
