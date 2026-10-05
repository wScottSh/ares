auto RDP::readWord(u32 address, Thread& thread) -> u32 {
  address = (address & 0x1f) >> 2;
  u32 data = dpc.read(address, thread.clock);
  if(dpLog && (address == RDPTimed::Current || address == RDPTimed::Status)) {
    fprintf(dpLog, "R %lld %s %s %06x\n", (long long)thread.clock.units, dpLogActor(thread.actor),
      address == RDPTimed::Current ? "CURRENT" : "STATUS", data);
  }
  debugger.ioDPC(Read, address, data);
  return data;
}

auto RDP::writeWord(u32 address, u32 data, Thread& thread) -> void {
  address = (address & 0x1f) >> 2;
  if(dpLog && address <= RDPTimed::Status) {
    fprintf(dpLog, "W %lld %s %s %08x sv=%u ev=%u cur=%06x end=%06x\n", (long long)thread.clock.units,
      dpLogActor(thread.actor), address == RDPTimed::Start ? "START" : address == RDPTimed::End ? "END" : "STATUS",
      data, (u32)dpc.startValid, (u32)dpc.endValid, (u32)dpc.current, (u32)dpc.end);
  }
  dpc.write(address, data, thread.clock);
  if(address == RDPTimed::End || address == RDPTimed::Status) kick(thread.clock);
  debugger.ioDPC(Write, address, data);
}

auto RDP::IO::readWord(u32 address, Thread& thread) -> u32 {
  address = (address & 0xfffff) >> 2;
  n32 data;

  if(address == 0) {
    //DPS_TBIST
    data.bit(0)    = bist.check;
    data.bit(1)    = bist.go;
    data.bit(2)    = bist.done;
    data.bit(3,10) = bist.fail;
  }

  if(address == 1) {
    //DPS_TEST_MODE
    data.bit(0) = test.enable;
  }

  if(address == 2) {
    //DPS_BUFTEST_ADDR
    data.bit(0,6) = test.address;
  }

  if(address == 3) {
    //DPS_BUFTEST_DATA
    //A drawn span-buffer image lands in words 0-31 and zeroes 32-127 (engine/rdp.h)
    if(self.engine.dpsTake(&test.data[0])) {
      for(u32 n : range(32, 128)) test.data[n] = 0;
    }
    data.bit(0,31) = test.data[test.address];
  }

  self.debugger.ioDPS(Read, address, data);
  return data;
}

auto RDP::IO::writeWord(u32 address, u32 data_, Thread& thread) -> void {
  address = (address & 0xfffff) >> 2;
  n32 data = data_;
  self.engine.dpsArm();

  if(address == 0) {
    //DPS_TBIST
    bist.check = data.bit(0);
    bist.go    = data.bit(1);
    if(data.bit(2)) bist.done = 0;
  }

  if(address == 1) {
    //DPS_TEST_MODE
    test.enable = data.bit(0);
  }

  if(address == 2) {
    //DPS_BUFTEST_ADDR
    test.address = data.bit(0,6);
  }

  if(address == 3) {
    //DPS_BUFTEST_DATA
    u32 value = data.bit(0,31);
    u32 column = test.address % 4;
    
    if(column == 2) {
      value &= 0xFF;
    } else if(column == 3) {
      value = 0;
    }

    test.data[test.address] = value;
  }

  self.debugger.ioDPS(Write, address, data);
}
