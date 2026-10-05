auto RI::attach(RiBus::Requester requester, Client* client) -> void {
  clients[(u32)requester] = client;
}

auto RI::post(const RiBus::Burst& burst, Clock at) -> void {
  channel.post(burst, at);
  timeline.wake(Timing::ActorId::Bus);
}

//One broadcast SetRR per VI HSYNC while RI_REFRESH.En is set (n64brew RDRAM_Interface, B11).
auto RI::refresh(Clock at) -> void {
  if(!io.refresh.bit(17)) return;
  //One request latch, sampled only while no refresh is waiting or running: an HSYNC
  //during one adds none. Only a VI line shorter than a refresh (H_SYNC still 0 while
  //a ROM programs the VI) can hit this; at any real line rate refreshes never overlap.
  if(channel.pendingFor(RiBus::Requester::Refresh) || at < channel.refreshEnd) return;
  post({0, 0, RiBus::Direction::Write, RiBus::Requester::Refresh, 0}, at);
}

auto RI::readiness() const -> Timing::Readiness {
  if(channel.empty()) return Timing::Readiness::parked();
  return Timing::Readiness::runnable(channel.next());
}

//A DMA burst's bytes, in bus order, between RDRAM and the client's buffer.
//Whole aligned words skip the byte path; the result is the same.
auto RI::move(const RiBus::Burst& b, u8* data) -> void {
  RBusDevice device = RBusDevice::SP_DMA;
  if(b.requester == RiBus::Requester::PiDma) device = RBusDevice::PI_DMA;
  if(b.requester == RiBus::Requester::SiDma) device = RBusDevice::SI_DMA;
  if(b.requester == RiBus::Requester::AiDma) device = RBusDevice::AI_DMA;
  const bool words = (b.address & 3) == 0 && (b.bytes & 3) == 0;
  if(b.direction == RiBus::Direction::Read) {
    if(words) {
      for(u32 i = 0; i < b.bytes; i += 4) {
        u32 w = rdram.ram.read<Word>(b.address + i, device);
        data[i + 0] = w >> 24; data[i + 1] = w >> 16; data[i + 2] = w >> 8; data[i + 3] = w;
      }
    } else {
      for(u32 i = 0; i < b.bytes; i++) data[i] = rdram.ram.read<Byte>(b.address + i, device);
    }
  } else {
    if(words) {
      for(u32 i = 0; i < b.bytes; i += 4) {
        u32 w = data[i + 0] << 24 | data[i + 1] << 16 | data[i + 2] << 8 | data[i + 3];
        rdram.ram.write<Word>(b.address + i, w, device);
      }
    } else {
      for(u32 i = 0; i < b.bytes; i++) rdram.ram.write<Byte>(b.address + i, data[i], device);
    }
  }
}

auto RI::run(Clock limit) -> void {
  auto g = channel.decide();
  if(g.burst.requester == RiBus::Requester::Refresh) return;
  auto client = clients[(u32)g.burst.requester];
  void* data = client->buffer(g.burst);
  if(g.burst.requester != RiBus::Requester::CpuSysAD) {
    move(g.burst, (u8*)data);
    return client->granted(g);
  }
  const u32 address = g.burst.address;
  const auto device = RBusDevice::VR4300_UNCACHED;
  if(g.burst.direction == RiBus::Direction::Read) {
    switch(g.burst.bytes) {
    case Byte:   *(u64*)data = rdram.ram.read<Byte>(address, device); break;
    case Half:   *(u64*)data = rdram.ram.read<Half>(address, device); break;
    case Word:   *(u64*)data = rdram.ram.read<Word>(address, device); break;
    case Dual:   *(u64*)data = rdram.ram.read<Dual>(address, device); break;
    case DCache: rdram.ram.readBurst<DCache>(address, (u32*)data, RBusDevice::VR4300_DCACHE); break;
    case ICache: rdram.ram.readBurst<ICache>(address, (u32*)data, RBusDevice::VR4300_ICACHE); break;
    }
  } else {
    switch(g.burst.bytes) {
    case Byte:   rdram.ram.write<Byte>(address, *(u64*)data, device); break;
    case Half:   rdram.ram.write<Half>(address, *(u64*)data, device); break;
    case Word:   rdram.ram.write<Word>(address, *(u64*)data, device); break;
    case Dual:   rdram.ram.write<Dual>(address, *(u64*)data, device); break;
    case DCache: rdram.ram.writeBurst<DCache>(address, (u32*)data, RBusDevice::VR4300_DCACHE); break;
    case ICache: rdram.ram.writeBurst<ICache>(address, (u32*)data, RBusDevice::VR4300_ICACHE); break;
    }
  }
  client->granted(g);
}

auto RI::postAndDecide(const RiBus::Burst& burst, Clock at) -> bool {
  channel.post(burst, at);
  if(channel.count != 1 || channel.next() > timeline.horizon()) {
    timeline.wake(Timing::ActorId::Bus);
    return false;
  }
  timeline.record(channel.next(), Timing::ActorId::Bus);
  run(channel.next());
  return true;
}
