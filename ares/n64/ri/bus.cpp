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
  post({0, 0, RiBus::Direction::Write, RiBus::Requester::Refresh, 0}, at);
}

auto RI::readiness() const -> Timing::Readiness {
  if(channel.empty()) return Timing::Readiness::parked();
  return Timing::Readiness::runnable(channel.next());
}

auto RI::run(Clock limit) -> void {
  auto g = channel.decide();
  if(g.burst.requester == RiBus::Requester::Refresh) return;
  auto client = clients[(u32)g.burst.requester];
  void* data = client->buffer(g.burst);
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
