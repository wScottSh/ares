SysAD sysad;

static constexpr auto ceilPclk(Clock t) -> Clock {
  return {(t.units + Timing::UnitsPerPclk - 1) / Timing::UnitsPerPclk * Timing::UnitsPerPclk};
}

//RDRAM data the RI moves. MI repeat and EBus test modes, the RDRAM register
//space and everything else keep their device paths.
static auto throughRi(u32 address) -> bool {
  return address <= 0x03ef'ffff && !mi.repeating() && !mi.ebusTest();
}

auto SysAD::power() -> void {
  head = count = slotsUsed = 0;
  free = {};
  readGranted = false;
  readEnd = {};
  drainer.reset();
  drainer.actor = Timing::ActorId::SysAD;
  update();
  ri.attach(RiBus::Requester::CpuSysAD, this);
  timeline.attach(Timing::ActorId::SysAD, this);
}

//The CPU is the only actor that blocks inside a call, and only here, for its
//own transaction (ADR 0001 Decision 1). Its clock runs on through the stall,
//so COUNT and every event it sees stay in time order.
template<typename F> auto SysAD::await(F&& done) -> void {
  while(!done()) {
    Clock t = timeline.earliest();
    if(t == Clock::never()) abort();  //nothing left that could grant it
    if(cpu.clock < t) cpu.clock = t;
    timeline.catchUp(t, Timing::ActorId::CPU);
  }
}

auto SysAD::resume(Clock t) -> void {
  if(cpu.clock < t) cpu.clock = t;
  cpu.clock = ceilPclk(cpu.clock);
}

auto SysAD::retire(Clock now) -> void {
  while(count) {
    auto& e = entries[head];
    if(e.phase != Entry::Phase::Done || e.done > now) break;
    slotsUsed -= e.slots;
    head = (head + 1) & 3;
    count--;
  }
}

//"has a space" (NEC s.4.9): a store that finds the buffer full stalls until
//the oldest entries' EOK frees enough slots (cpu.wb-release).
auto SysAD::reserve(u32 slots) -> void {
  retire(cpu.clock);
  while(slotsUsed + slots > Timing::Behavior::CpuWbEntries) {
    auto& e = entries[head];
    if(e.phase == Entry::Phase::Done) resume(e.done);
    else await([&] { return e.phase == Entry::Phase::Done; });
    retire(cpu.clock);
  }
}

//Reads go out behind every older write (vr4300-wb.md, read after write).
auto SysAD::drain() -> void {
  await([&] { return !pending(); });
  retire(cpu.clock);
}

auto SysAD::enqueue(const Entry& entry) -> void {
  const bool idle = !pending();
  entries[(head + count) & 3] = entry;
  count++;
  slotsUsed += entry.slots;
  if(!idle) return;
  update();
  timeline.wake(Timing::ActorId::SysAD);
}

auto SysAD::pending() -> Entry* {
  for(u32 i = 0; i < count; i++) {
    auto& e = entries[(head + i) & 3];
    if(e.phase != Entry::Phase::Done) return &e;
  }
  return nullptr;
}

auto SysAD::update() -> void {
  auto e = pending();
  if(!e) cached = Timing::Readiness::parked();
  else if(e->phase == Entry::Phase::Ready) cached = Timing::Readiness::runnable(e->enqueued > free ? e->enqueued : free);
  else if(e->phase == Entry::Phase::Applying) cached = Timing::Readiness::runnable(e->done);
  else cached = Timing::Readiness::blocked();
}

auto SysAD::readiness() const -> Timing::Readiness {
  return cached;
}

//One entry per step: post it to the RI, or perform a register write.
auto SysAD::run(Clock limit) -> void {
  auto& e = *pending();
  if(e.phase == Entry::Phase::Applying) {
    apply(e);
    e.phase = Entry::Phase::Done;
    free = e.done;
    update();
    return;
  }
  const Clock start = cached.at;
  if(throughRi(e.address)) {
    e.phase = Entry::Phase::Posted;
    update();
    ri.post({e.address, e.size, RiBus::Direction::Write, RiBus::Requester::CpuSysAD, (u16)(&e - entries)}, start);
    return;
  }
  //No measurement exists for a register write's drain (vr4300-wb.md); sysad.register-write.
  e.phase = Entry::Phase::Applying;
  e.done = start + Timing::Behavior::SysadRegisterWrite;
  update();
}

//A posted write whose target is not RDRAM data runs its device path now, at the drain's time.
auto SysAD::apply(Entry& e) -> void {
  drainer.clock = e.done;
  timeline.actingAt(e.done, [&] {
    switch(e.size) {
    case Byte:   bus.write<Byte>(e.address, e.value, drainer, RBusDevice::VR4300_UNCACHED); break;
    case Half:   bus.write<Half>(e.address, e.value, drainer, RBusDevice::VR4300_UNCACHED); break;
    case Word:   bus.write<Word>(e.address, e.value, drainer, RBusDevice::VR4300_UNCACHED); break;
    case Dual:   bus.write<Dual>(e.address, e.value, drainer, RBusDevice::VR4300_UNCACHED); break;
    case DCache: bus.writeBurst<DCache>(e.address, e.words, drainer); break;
    case ICache: bus.writeBurst<ICache>(e.address, e.words, drainer); break;
    }
  });
}

auto SysAD::buffer(const RiBus::Burst& burst) -> void* {
  if(burst.tag == ReadTag) return burst.bytes > Dual ? (void*)readData.words : (void*)&readData.value;
  auto& e = entries[burst.tag];
  return e.size > Dual ? (void*)e.words : (void*)&e.value;
}

auto SysAD::granted(const RiBus::Grant& g) -> void {
  if(g.burst.tag == ReadTag) {
    readGranted = true;
    readEnd = g.dataEnd;
    return;
  }
  auto& e = entries[g.burst.tag];
  e.done = g.dataEnd + (e.size > Dual ? BlockWritePath : WritePath);
  e.phase = Entry::Phase::Done;
  free = e.done;
  update();
}

template<u32 Size> auto SysAD::readRdram(u32 address, void* data, Clock path) -> void {
  const Clock start = cpu.clock > free ? cpu.clock : free;
  readGranted = false;
  if(!ri.postAndDecide({address, (u8)Size, RiBus::Direction::Read, RiBus::Requester::CpuSysAD, ReadTag}, start)) {
    await([&] { return readGranted; });
  }
  free = readEnd + path;
  resume(free);
  if constexpr(Size <= Dual) *(u64*)data = readData.value;
  else memory::copy(data, readData.words, Size);
}

template<u32 Size> auto SysAD::read(u32 address) -> u64 {
  drain();
  if(throughRi(address)) {
    u64 value;
    readRdram<Size>(address, &value, ReadPath);
    return value;
  }
  resume(free);
  u64 value = bus.read<Size>(address, cpu, RBusDevice::VR4300_UNCACHED);
  if(free < cpu.clock) free = cpu.clock;
  return value;
}

template<u32 Size> auto SysAD::store(u32 address, u64 data) -> void {
  reserve(1);
  Entry e{};
  e.phase = Entry::Phase::Ready;
  e.size = Size;
  e.slots = 1;
  e.address = address;
  e.enqueued = cpu.clock;
  e.value = data;
  enqueue(e);
}

template<u32 Size> auto SysAD::fill(u32 address, u32* words) -> bool {
  drain();
  if(address <= 0x03ef'ffff && !mi.ebusTest()) {
    readRdram<Size>(address, words, Size == DCache ? DfillPath : IfillPath);
    return true;
  }
  //the RDRAM register space, EBus test mode and non-RDRAM space keep their device paths at the uncontended cost
  resume(free);
  cpu.step(Size == DCache ? Timing::Behavior::CpuDfillTotal - Issue : IfillStall);
  free = cpu.clock;
  return bus.readBurst<Size>(address, words, cpu);
}

template<u32 Size> auto SysAD::writeback(u32 address, const u32* words) -> void {
  const u32 slots = Size == DCache ? Timing::Behavior::CpuWbBlockEntries : Timing::Behavior::CpuWbEntries;
  reserve(slots);
  Entry e{};
  e.phase = Entry::Phase::Ready;
  e.size = Size;
  e.slots = slots;
  e.address = address;
  e.enqueued = cpu.clock;
  memory::copy(e.words, words, Size);
  enqueue(e);
}

template<u32 Size> auto SysAD::forward(u32 address, u64 value) const -> u64 {
  for(u32 i = 0; i < count; i++) {
    auto& e = entries[(head + i) & 3];
    if(e.phase == Entry::Phase::Done) continue;
    for(u32 k = 0; k < Size; k++) {
      u32 a = address + k;
      if(a < e.address || a >= e.address + e.size) continue;
      u32 o = a - e.address;
      u8 byte = e.size > Dual ? e.words[o >> 2] >> (24 - 8 * (o & 3)) : e.value >> (8 * (e.size - 1 - o));
      u32 shift = 8 * (Size - 1 - k);
      value = value & ~((u64)0xff << shift) | (u64)byte << shift;
    }
  }
  return value;
}

auto SysAD::serialize(serializer& s) -> void {
  for(auto& e : entries) {
    s((u8&)e.phase);
    s(e.size);
    s(e.slots);
    s(e.address);
    s(e.enqueued.units);
    s(e.done.units);
    s(e.value);
    s(e.words);
  }
  s(head);
  s(count);
  s(slotsUsed);
  s(free.units);
  update();
}

auto CPU::InstructionCache::Line::fill(u32 paddr, CPU& cpu) -> void {
  const u32 tag = paddr & ~0x0000'0fffu;
  tagKey = tag;
  setValid(true);
  sysad.fill<ICache>(tag | index, words);
}

auto CPU::InstructionCache::Line::writeBack(CPU& cpu) -> void {
  cpu.step(pclk(48));
  const u32 tag = tagKey & ~0x0000'0fffu;
  sysad.writeback<ICache>(tag | index, words);
}
