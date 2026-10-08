//The RDP as a timeline actor (ADR 0001 Decision 3, plans T12 and T13).
//
//One step handles everything due at one time, in hardware order: the command
//processor retires what it was running, granted bursts land, the pixel
//pipeline advances, the next command dispatches, and the ports and the
//command DMA post what they can. The renderer never touches RDRAM: a span
//shades from the snapshot its read bursts landed, into windows that its
//write-back bursts drain; a TMEM load reads the rows its DpTexture bursts
//staged. So content and time come from the same grants.

//ARES_DPLOG=<file> logs DPC register traffic and the DP interrupt, one line
//each, for checking the RSP's back-pressure loops (rsp-rdp-fifo.md). Host-side
//only; it never changes emulation.
static FILE* dpLog = [] { auto path = getenv("ARES_DPLOG"); return path ? fopen(path, "w") : (FILE*)nullptr; }();

static auto dpLogActor(Timing::ActorId id) -> const char* {
  return id == Timing::ActorId::CPU ? "cpu" : id == Timing::ActorId::RSP ? "rsp" : "dbg";
}

static auto bytesPerPixel(u32 size) -> u32 { return size == 0 ? 0 : 1 << (size - 1); }

//span-ram.md rows 3-6: a half holds rdp.span-ram-half bytes, i.e. 32 pixels
//at 16 bpp (rdp.color-half-pixels-16bpp).
static auto halfPixels(u32 bpp) -> u32 { return bpp ? (u32)Timing::Behavior::RdpSpanRamHalf / bpp : ~0u; }

static auto isLoad(int command) -> bool { return command == 0x30 || command == 0x33 || command == 0x34; }
static auto isSync(int command) -> bool { return command >= 0x26 && command <= 0x28; }
static auto isPrimitive(int command) -> bool {
  return (command >= 0x08 && command <= 0x0f) || command == 0x24 || command == 0x25 || command == 0x36;
}

static auto spanPixels(const rdp_span_info& info) -> u32 { return (u32)info.pixels; }

//Cuts [lo, hi) into bursts the RI accepts (at most ri.max-burst, never across a 2 KiB row).
template<typename F> static auto splitBursts(u32 lo, u32 hi, u32 unit, F&& emit) -> void {
  while(lo < hi) {
    u32 n = min(RiBus::split(lo, hi - lo), unit - (lo & (unit - 1)));
    emit(lo, n);
    lo += n;
  }
}

//---- ports ----------------------------------------------------------------

auto RDP::Port::native(const RiBus::Burst& b, Native& n) -> bool {
  if(requester == RiBus::Requester::DpCommand) return false;
  auto& p = queue.front();
  if(p.image == Texture) {
    auto& load = self->tmemLoad;
    for(u32 i : range(load.count)) {
      auto& w = load.windows[i];
      if(b.address >= w.lo && b.address < w.hi) { n = {w.data, w.hidden, w.lo}; return true; }
    }
    abort();
  }
  auto& w = p.image == Color ? self->slots[p.slot].color : self->slots[p.slot].depth;
  n = {w.data, w.hidden, w.lo};
  return true;
}

auto RDP::Port::granted(const RiBus::Grant& g) -> void {
  Pending p = queue.front();
  queue.pop_front();
  posted = false;
  freeAt = g.dataEnd;
  Clock landAt = g.dataEnd;
  if(this == &self->memory) {
    //the interface's own cost scales with the burst's bytes, fit per 64 B half
    using namespace Timing::Behavior;
    auto scaled = [&](Clock perHalf) -> Clock { return {perHalf.units * p.bytes / RdpSpanRamHalf}; };
    if(p.write) freeAt = freeAt + scaled(RdpMemOverheadWrite);
    else freeAt = freeAt + scaled(RdpMemOverheadRead), landAt = freeAt + RdpSpanReadLatency;
  }
  flights.push_back({p, landAt});
  timeline.wake(Timing::ActorId::RDP);
}

//The queue entry to post next: the oldest whose image has nothing older
//waiting, and, for a read, no read of its image in flight (one read per image).
//Writes and reads of one image keep their order.
auto RDP::Port::eligible() const -> s32 {
  u32 seen = 0;
  for(u32 i : range(min((u32)queue.size(), 8u))) {
    auto& p = queue[i];
    u32 bit = 1 << p.image;
    if(seen & bit) continue;
    seen |= bit;
    bool blocked = false;
    if(!p.write) for(auto& f : flights) if(!f.p.write && f.p.image == p.image) blocked = true;
    if(!blocked) return i;
  }
  return -1;
}

auto RDP::Port::post(Clock at) -> void {
  if(posted || queue.empty() || at < freeAt) return;
  s32 i = eligible();
  if(i < 0) return;
  if(i) {  //the posted burst stays at the front until its grant
    Pending p = queue[i];
    queue.erase(queue.begin() + i);
    queue.push_front(p);
  }
  auto& p = queue.front();
  posted = true;
  auto r = requester;
  if(this == &self->memory)
    r = p.image == Color ? RiBus::Requester::DpColor : p.image == Depth ? RiBus::Requester::DpDepth : RiBus::Requester::DpTexture;
  ri.post({p.address, p.bytes, p.write ? RiBus::Direction::Write : RiBus::Direction::Read, r, 0}, at);
}

//When this port next has something to do: a landing, or a post it waits to make.
auto RDP::Port::next() const -> Clock {
  Clock t = Clock::never();
  for(auto& f : flights) if(f.landAt < t) t = f.landAt;
  if(!posted && !queue.empty() && freeAt < t && eligible() >= 0) t = freeAt;
  return t;
}

//---- the actor ------------------------------------------------------------

auto RDP::busy() const -> bool {
  if(executor.busy || rdp_render_engine_buffered() > 0) return true;
  if(pipe.count || pipe.current >= 0 || tmemLoad.active) return true;
  rdp_span_info info;
  return rdp_render_span_peek(0, &info);
}

auto RDP::wakeAt(Clock at) -> void {
  if(at < pipe.wake) pipe.wake = at;
}

auto RDP::dispatchable() const -> bool {
  if(executor.busy || dpc.freeze || dpc.crashed || rdp_render_engine_need() != 0) return false;
  int command = rdp_render_engine_next();
  rdp_span_info info;
  bool unrun = rdp_render_span_peek(0, &info);
  //a primitive dispatches once the previous one's last span has entered the pipe
  if(isPrimitive(command) && unrun) return false;
  //Sync Load/Pipe/Tile stall the pipeline a fixed number of GCLK (n64brew
  //Commands), after the spans ahead of them
  if(isSync(command) && (unrun || pipe.current >= 0)) return false;
  if(rdp_render_engine_drains()) {
    if(unrun || pipe.current >= 0) return false;
    if(isLoad(command)) return tmemLoad.active && tmemLoad.reads == 0;
  }
  return true;
}

auto RDP::readiness() const -> Timing::Readiness {
  Clock next = pipe.wake;
  if(fetch.dwords && fetch.arrival < next) next = fetch.arrival;
  if(executor.busy && executor.until < next) next = executor.until;
  for(auto* port : {&memory, &command, &fillPort}) next = min(next, port->next());
  if(pipe.chunk && pipe.chunkEnd < next) next = pipe.chunkEnd;
  if(!executor.busy && dispatchable()) next = min(next, max(executor.until, Thread::clock));
  if(next == Clock::never()) return Timing::Readiness::parked();
  return Timing::Readiness::runnable(next);
}

auto RDP::run(Clock limit) -> void {
  while(true) {
    auto next = readiness();
    if(next.kind != Timing::Readiness::Kind::Runnable) return;
    Thread::clock = next.at;
    step(next.at);
    next = readiness();
    if(next.kind != Timing::Readiness::Kind::Runnable || next.at >= timeline.limit(limit)) return;
    timeline.record(next.at, Timing::ActorId::RDP);  //one trace record per step, however the steps are batched
  }
}

auto RDP::step(Clock at) -> void {
  if(pipe.wake <= at) pipe.wake = Clock::never();
  if(executor.busy && executor.until <= at) {
    if(executor.syncFull && pipe.writes) {
      executor.until = Clock::never();  //retires when the last write-back lands (land)
    } else {
      executor.busy = false;
      if(executor.load) dpc.tmem.set(false, at), executor.load = false;
      if(executor.syncFull) {
        executor.syncFull = false;
        dpc.syncFullRetired(at);
        mi.raise(MI::IRQ::DP);
        if(dpLog) fprintf(dpLog, "I %lld rsp_halted=%u\n", (long long)at.units, (u32)rsp.status.halted);
      }
    }
  }
  if(fetch.dwords && fetch.arrival <= at) {
    u64 words[16];
    for(u32 n : range(fetch.dwords)) {
      u32 address = (dpc.current + n * 8) & 0xfff;
      words[n] = (u64)rsp.dmem.read<Word>(address) << 32 | rsp.dmem.read<Word>((address + 4) & 0xfff);
    }
    rdp_render_engine_feed(words, fetch.dwords);
    dpc.fetched(fetch.dwords * sizeof(u64));
    fetch.dwords = 0;
  }
  land(at);
  pipeline(at);
  if(dispatchable()) dispatch(at);
  startLoad(at);
  pipeline(at);
  startFetch(at);
  for(auto* port : {&memory, &command, &fillPort}) port->post(at);
  const bool b = busy();
  if(b != stat.on) {
    if(stat.on) stat.busy += (at - stat.since).units;
    stat.on = b;
    stat.since = at;
  }
  dpc.cmd.set(b, at);
}

//Frees finished slots, oldest first.
auto RDP::retire() -> void {
  while(pipe.count) {
    auto& slot = slots[pipe.head];
    if(!slot.shaded || slot.writes) break;
    slot.shaded = false;
    pipe.head = (pipe.head + 1) % Slots;
    pipe.count--;
  }
}

//Granted bursts whose data has arrived: snapshots become ready, halves and
//slots drain, command words reach the FIFO, staged load rows count down.
auto RDP::land(Clock at) -> void {
  auto landOne = [&](Port& port, const Port::Flight& f) {
    const Pending& p = f.p;
    const Clock t = f.landAt;
    if(p.image == Command) {
      u64 words[16];
      for(u32 n : range(p.bytes / 8)) {
        u64 w = 0;
        for(u32 b : range(8)) w = w << 8 | port.words[n * 8 + b];
        words[n] = w;
      }
      rdp_render_engine_feed(words, p.bytes / 8);
      dpc.fetched(p.bytes);
      return;
    }
    if(p.image == Texture) {
      tmemLoad.reads--;
      if(t > tmemLoad.ready) tmemLoad.ready = t;
      return;
    }
    auto& slot = slots[p.slot];
    if(!p.write) {
      slot.reads--;
      if(t > slot.ready) slot.ready = t;
      return;
    }
    slot.writes--;
    pipe.writes--;
    if(t > pipe.lastWrite) pipe.lastWrite = t;
    if(p.half != 0xff) {
      auto& half = (p.image == Color ? pipe.color : pipe.depth).halves[p.half];
      half.outstanding--;
    }
    if(executor.syncFull && !pipe.writes && executor.until == Clock::never()) executor.until = max(t, at);
  };
  for(auto* port : {&memory, &command, &fillPort}) {
    //in landing order; a port's flights are few
    while(true) {
      auto best = port->flights.end();
      for(auto f = port->flights.begin(); f != port->flights.end(); f++)
        if(f->landAt <= at && (best == port->flights.end() || f->landAt < best->landAt)) best = f;
      if(best == port->flights.end()) break;
      auto f = *best;
      port->flights.erase(best);
      landOne(*port, f);
    }
  }
  retire();
}

//Posts the snapshot reads of the next queued span: color if IM_RD, Z if
//Z_CMP (rdp.read-gate), one span ahead of the pipeline (SDK 12.2.3: the next
//span is prefetched into another span buffer). A 1-primitive span waits for
//every earlier write-back to land and for rdp.atomic-dead clocks after the
//previous span was rendered (SDK 12.2.3: "30 to 40 null cycles after the
//last span of a primitive is rendered"; 1prim-cost.md).
auto RDP::prefetch(Clock at) -> void {
  retire();
  if(pipe.prefetched >= 0 || pipe.count == Slots) return;
  rdp_span_info info;
  //the slot past a primitive's last real span draws nothing and never enters the pipe
  while(rdp_render_span_peek(0, &info) && info.phantom) rdp_render_span_run();
  if(!rdp_render_span_peek(0, &info)) return;
  if(info.atomic && info.primitive != pipe.lastPrimitive) {
    if(pipe.count || pipe.current >= 0) return;
    Clock barrier = max(pipe.lastWrite, pipe.lastSpanEnd + Timing::Behavior::RdpAtomicDead);
    if(barrier > at) return wakeAt(barrier);
  }
  u32 index = (pipe.head + pipe.count) % Slots;
  auto& slot = slots[index];
  slot.info = info;
  slot.reads = slot.writes = 0;
  slot.ready = at;
  slot.shaded = false;
  pipe.count++;
  pipe.prefetched = index;
  pipe.lastPrimitive = info.primitive;

  auto setup = [&](Window& w, u32 base, u32 bpp, bool read, Image image) {
    w.lo = w.hi = 0;
    if(!bpp || info.x1 < info.x0) return;
    u32 row = base + ((u32)info.y * info.fb_width + (u32)info.x0) * bpp;
    u32 end = base + ((u32)info.y * info.fb_width + (u32)info.x1 + 1) * bpp;
    w.lo = row & ~7;
    w.hi = (end + 7) & ~7;
    if(w.hi - w.lo > SpanBytes) w.hi = w.lo + SpanBytes;
    memory::fill<u8>(w.data, w.hi - w.lo, 0);
    memory::fill<u8>(w.hidden, (w.hi - w.lo) / 2, 0);
    memory::fill<u8>(w.written, w.hi - w.lo, 0);
    if(!read) return;
    splitBursts(w.lo, w.hi, Timing::Behavior::RdpSpanRamHalf, [&](u32 a, u32 n) {
      memory.queue.push_back({a, (u8)n, 0, (u8)index, (u8)image, 0xff});
      slot.reads++;
    });
  };
  const bool rmw = info.cycle_type <= 1;
  setup(slot.color, info.fb_address & 0xffffff, bytesPerPixel(info.fb_size), rmw && info.image_read, Color);
  const bool z = rmw && (info.z_compare || info.z_update);
  setup(slot.depth, info.zb_address & 0xffffff, z ? 2 : 0, rmw && info.z_compare, Depth);
}

//Shades the prefetched span once its snapshot has landed and the pipeline
//is free: pixels are computed now, from the bytes the RI delivered.
auto RDP::startSpan(Clock at) -> bool {
  if(pipe.prefetched < 0) return false;
  auto& slot = slots[pipe.prefetched];
  if(slot.reads) return false;
  Clock start = max(pipe.time, slot.ready);
  if(start > at) return wakeAt(start), false;
  rdp_memwin windows[2];
  u32 n = 0;
  for(auto* w : {&slot.color, &slot.depth})
    if(w->hi > w->lo) windows[n++] = {w->lo, w->hi, w->data, w->hidden, w->written};
  rdp_render_set_windows(windows, n);
  auto host = std::chrono::steady_clock::now();
  rdp_render_span_run();
  engine.renderNanoseconds += std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - host).count();
  rdp_render_set_windows(nullptr, 0);
  pipe.current = pipe.prefetched;
  pipe.prefetched = -1;
  pipe.pixel = 0;
  pipe.time = start;
  for(auto* s : {&pipe.color, &pipe.depth}) {
    //each span starts at its 4-pixel phase (span-ram.md row 3)
    s->position += ((u32)slot.info.x0 - s->position) & 3;
    s->halfStart = 0;
  }
  return true;
}

//Runs the next chunk of the current span: the pixels up to the next half
//boundary of either image. A half's write-back queues at the memory
//interface without stalling the pipeline; the interface's occupancy and the
//span slots bound how far shading runs ahead of memory (fit to Thar0: 2-cycle
//IM_RD lines take as long as 1-cycle ones, 675 vs 681 rclk per 320 px).
auto RDP::beginChunk(Clock at) -> bool {
  auto& slot = slots[pipe.current];
  auto& info = slot.info;
  const u32 pixels = spanPixels(info);
  Clock start = pipe.time, clocks;
  u32 k = pixels - pipe.pixel;
  if(info.cycle_type <= 1) {
    for(u32 image : {(u32)Color, (u32)Depth}) {
      auto& s = image == Color ? pipe.color : pipe.depth;
      auto& w = image == Color ? slot.color : slot.depth;
      if(w.hi == w.lo) continue;
      u32 h = halfPixels(image == Color ? bytesPerPixel(info.fb_size) : 2);
      k = min(k, h - s.position % h);
    }
    clocks = RDPTimed::pixelClocks(info.cycle_type, k);
    if(pipe.pixel + k == pixels) clocks += RDPTimed::spanTail(info.cycle_type);
  } else {
    const u32 bpp = bytesPerPixel(info.fb_size);
    u64 words = bpp && pixels ? ((u64)(info.x0 + pixels) * bpp + 7) / 8 - (u64)info.x0 * bpp / 8 : 0;
    clocks = RDPTimed::wordClocks(words);
  }
  if(start > at) return wakeAt(start), false;
  stat.pipe += clocks.units;
  pipe.chunk = true;
  pipe.chunkPixels = k;
  pipe.chunkEnd = start + clocks;
  pipe.time = pipe.chunkEnd;
  return true;
}

auto RDP::endChunk(Clock at) -> void {
  auto& slot = slots[pipe.current];
  auto& info = slot.info;
  const u32 pixels = spanPixels(info);
  const u32 k = pipe.chunkPixels;
  pipe.chunk = false;
  pipe.pixel += k;
  const bool last = pipe.pixel >= pixels;
  if(info.cycle_type <= 1) {
    for(u32 image : {(u32)Color, (u32)Depth}) {
      auto& s = image == Color ? pipe.color : pipe.depth;
      auto& w = image == Color ? slot.color : slot.depth;
      if(w.hi == w.lo) continue;
      u32 h = halfPixels(image == Color ? bytesPerPixel(info.fb_size) : 2);
      s.position += k;
      if(s.position % h == 0 || last) {
        //a full half, or the end of the span, writes back (span-ram.md row 6)
        writeBack(image, s.halfStart, pipe.pixel, at);
        s.halfStart = pipe.pixel;
      }
    }
  } else {
    writeBack(Color, 0, pixels, at);
  }
  if(last) {
    slot.shaded = true;
    pipe.lastSpanEnd = at;
    pipe.current = -1;
    retire();
  }
}

//One write burst per contiguous written run of [firstPixel, endPixel) of
//the current span, split at ri.max-burst and 2 KiB rows; a fully rejected
//range posts nothing (rdp-write-granularity.md).
auto RDP::writeBack(u32 image, u32 firstPixel, u32 endPixel, Clock at) -> void {
  auto& slot = slots[pipe.current];
  auto& info = slot.info;
  auto& w = image == Color ? slot.color : slot.depth;
  const bool direct = info.cycle_type >= 2;
  auto& port = info.cycle_type == 3 ? fillPort : memory;
  const u32 bpp = image == Color ? bytesPerPixel(info.fb_size) : 2;
  const u32 base = (image == Color ? info.fb_address : info.zb_address) & 0xffffff;
  const u32 row = base + ((u32)info.y * info.fb_width + (u32)info.x0) * bpp;
  //the span's end flushes the whole window: the walk can touch one position
  //past the drawn width (the clipped end pixel)
  const bool end = endPixel >= spanPixels(info);
  u32 lo = direct ? w.lo : max(w.lo, row + firstPixel * bpp);
  u32 hi = direct || end ? w.hi : min(w.hi, row + endPixel * bpp);
  u8 half = 0xff;
  Half* h = nullptr;
  if(!direct) {
    auto& s = image == Color ? pipe.color : pipe.depth;
    half = ((s.position - 1) / halfPixels(bpp)) & 1;
    h = &s.halves[half];
  }
  u32 bursts = 0;
  for(u32 a = lo; a < hi;) {
    if(!w.written[a - w.lo]) { a++; continue; }
    u32 end = a;
    while(end < hi && w.written[end - w.lo]) end++;
    splitBursts(a, end, Timing::Behavior::RiMaxBurst, [&](u32 b, u32 n) {
      port.queue.push_back({b, (u8)n, 1, (u8)pipe.current, (u8)image, half});
      bursts++;
    });
    a = end;
  }
  slot.writes += bursts;
  pipe.writes += bursts;
  if(h) h->outstanding += bursts;
}

auto RDP::pipeline(Clock at) -> void {
  while(true) {
    prefetch(at);
    if(pipe.chunk) {
      if(pipe.chunkEnd > at) return;
      endChunk(pipe.chunkEnd);
      continue;
    }
    if(pipe.current < 0) {
      prefetch(at);
      if(!startSpan(at)) return;
      prefetch(at);
    }
    if(!beginChunk(at)) return;
  }
}

//A TMEM load stages its source rows in the Z half (span-ram.md row 12): it
//starts once the pipeline is empty and the Z halves have drained, and its
//rows arrive as DpTexture bursts before the load runs.
auto RDP::startLoad(Clock at) -> void {
  if(tmemLoad.active || executor.busy || dpc.freeze || dpc.crashed) return;
  if(!isLoad(rdp_render_engine_next())) return;
  rdp_span_info info;
  if(rdp_render_span_peek(0, &info) || pipe.current >= 0) return;
  for(auto& half : pipe.depth.halves) if(half.outstanding) return;
  tmemLoad.count = rdp_render_load_plan(tmemLoad.ranges, Load::Ranges);
  tmemLoad.reads = 0;
  tmemLoad.ready = at;
  tmemLoad.active = true;
  u32 offset = 0;
  for(u32 i : range(tmemLoad.count)) {
    auto& r = tmemLoad.ranges[i];
    u32 bytes = min(r.hi - r.lo, LoadBytes - offset);
    tmemLoad.windows[i] = {r.lo, r.lo + bytes, tmemLoad.data + offset, tmemLoad.hidden + offset / 2, tmemLoad.written + offset};
    splitBursts(r.lo, r.lo + bytes, Timing::Behavior::RiMaxBurst, [&](u32 a, u32 n) {
      memory.queue.push_back({a, (u8)n, 0, 0, (u8)Texture, 0xff});
      tmemLoad.reads++;
    });
    offset += bytes;
  }
  dpc.tmem.set(true, at);
}

auto RDP::dispatch(Clock at) -> void {
  const int command = rdp_render_engine_next();
  if(isLoad(command)) rdp_render_set_windows(tmemLoad.windows, tmemLoad.count);
  rdp_engine_work works[Timing::Behavior::RdpCmdFifoDwords];
  auto start = std::chrono::steady_clock::now();
  int count = rdp_render_engine_step(works, Timing::Behavior::RdpCmdFifoDwords);
  engine.renderNanoseconds += std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start).count();
  engine.renderCalls++;
  rdp_render_set_windows(nullptr, 0);
  if(isLoad(command)) tmemLoad.active = false;
  if(count < 0) return crash("pixel engine pipeline crash");
  if(count == 0) return;

  Clock busy;
  for(u32 n : range(count)) {
    auto& w = works[n];
    auto c = RDPTimed::cost({w.command, w.cycle_type, w.pixels, w.words, w.lines, w.load_bytes});
    busy += c.busy;
    executor.load |= c.load;
    executor.syncFull |= c.syncFull;
    debugger.command(w.word);
  }
  executor.busy = true;
  if(isSync(command) && pipe.time > at) at = pipe.time;
  executor.until = at + busy;
  if(isSync(command)) pipe.time = executor.until;
  //a primitive's spans enter the pipeline after its setup
  if(isPrimitive(command) && pipe.time < executor.until) pipe.time = executor.until;
  if(executor.load) dpc.tmem.set(true, at);
  if(rdp_render_crashed()) crash("pixel engine pipeline crash");
}

//The command DMA posts one DpCommand burst at a time, no more than the FIFO
//has room for (RDPTimed::fetchDwords); DPC_CURRENT advances as it lands. The
//X bus reads DMEM directly.
auto RDP::startFetch(Clock at) -> void {
  auto& port = command;
  if(fetch.dwords || !port.queue.empty() || !port.flights.empty()) return;
  u32 dwords = RDPTimed::fetchDwords(dpc, rdp_render_engine_buffered());
  if(!dwords) return;
  if(!mapIdentityWarned && !rdram.mapIdentity && !dpc.xbus) {
    debug(unusual, "[RDP] started while RDRAM DeviceId map is non-identity");
    mapIdentityWarned = 1;
  }
  if(dpc.xbus) {
    fetch.dwords = dwords;
    fetch.arrival = Timing::nextRclkEdge(Timing::nextRclkEdge(at) + RDPTimed::xbusLatency(dwords));
    return;
  }
  u32 address = dpc.current & 0xfffff8;
  u32 bytes = RiBus::split(address, dwords * 8) & ~7;
  port.queue.push_back({address, (u8)bytes, 0, 0, (u8)Command, 0xff});
  port.post(at);
}

//Another actor changed the DPC registers at `at`: the DMA may start and the
//command processor may resume.
auto RDP::kick(Clock at) -> void {
  if(!executor.busy && executor.until < Timing::nextRclkEdge(at)) executor.until = Timing::nextRclkEdge(at);
  startFetch(at);
  timeline.wake(Timing::ActorId::RDP);
}
