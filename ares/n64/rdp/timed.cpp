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

//span-ram.md rows 3-6: a half holds rdp.span-ram-half bytes. Whether a 16 bpp
//color half holds that many bytes or 16 positions is open (question 1).
static auto halfPixels(u32 image, u32 bpp) -> u32 {
  if(image == RDP::Color && bpp == 2) return Timing::Behavior::RdpColorHalfPixels16bpp;
  return bpp ? (u32)Timing::Behavior::RdpSpanRamHalf / bpp : ~0u;
}

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
  n = p.write ? Native{w.out, w.outHidden, w.lo} : Native{w.data, w.hidden, w.lo};
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
  self->changed();
  timeline.wake(Timing::ActorId::RDP);
}

//The queue entry to post next: the oldest of the first rdp.port-lookahead
//whose image has nothing older waiting, and, for a read, no read of its image
//in flight (one read per image). Writes and reads of one image keep their order.
auto RDP::Port::eligible() const -> s32 {
  u32 seen = 0;
  for(u32 i : range(min((u32)queue.size(), (u32)Timing::Behavior::RdpPortLookahead))) {
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
  //a span the pipeline has not entered: admitted, or not yet admitted (the
  //slot past a primitive's last span draws nothing and enters nothing)
  rdp_span_info info;
  bool unrun = pipe.admitted > 0;
  for(u32 i = pipe.queued; !unrun && rdp_render_span_peek(i, &info); i++) unrun = !info.phantom;
  //a primitive dispatches once the previous one's last span has entered the pipe
  if(isPrimitive(command) && unrun) return false;
  //Sync Load/Pipe/Tile stall the pipeline a fixed number of GCLK (n64brew
  //Commands), after the spans ahead of them
  if(isSync(command) && (unrun || pipe.current >= 0)) return false;
  if(rdp_render_engine_drains()) {
    if(unrun || pipe.current >= 0 || rdp_render_span_peek(0, &info)) return false;
    if(isLoad(command)) return tmemLoad.active && tmemLoad.reads == 0;
  }
  return true;
}

auto RDP::readiness() const -> Timing::Readiness {
  if(!cachedReadiness) cachedReadiness = nextStep();
  return *cachedReadiness;
}

auto RDP::nextStep() const -> Timing::Readiness {
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
  changed();
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
  changed();
}

//Frees finished slots, oldest first.
auto RDP::retire() -> void {
  while(pipe.count - pipe.admitted) {
    auto& slot = slots[pipe.head];
    if(!slot.shaded || slot.writes) break;
    slot.shaded = false;
    pipe.head = (pipe.head + 1) % Slots;
    pipe.count--;
  }
}

//Granted bursts whose data has arrived: segments become ready, halves and
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
    auto& stream = p.image == Color ? pipe.color : pipe.depth;
    if(!p.write) {
      auto& g = stream.segments[p.segment];
      g.reads--;
      if(t > g.ready) g.ready = t;
      return;
    }
    auto& slot = slots[p.slot];
    slot.writes--;
    pipe.writes--;
    if(t > pipe.lastWrite) pipe.lastWrite = t;
    if(p.half != 0xff) {
      stream.halves[p.half].outstanding--;
      drain(p.image, t);
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

//Half instances drain in order: an instance has drained once no later span
//can put pixels in it, the pipeline has shaded every segment in it, and its
//write-backs have landed. Its half then holds instance n + 2.
auto RDP::drain(u32 image, Clock at) -> void {
  auto& s = image == Color ? pipe.color : pipe.depth;
  while(s.drained < s.instance) {
    if(s.count && s.segment(0).instance <= s.drained) return;
    auto& half = s.halves[s.drained & 1];
    if(half.outstanding) return;
    half.drained = at;
    s.drained++;
  }
}

//Admits the next queued spans in stream order: each image's pixels take
//consecutive stream positions in the image's halves (span-ram.md rows 3-6),
//each span from its segment phase, cut into one segment per half instance.
//A span is admitted once the half its first pixels go into is usable. A
//1-primitive span waits for every earlier write-back to land and for
//rdp.atomic-dead clocks after the previous span was rendered (SDK 12.2.3:
//"30 to 40 null cycles after the last span of a primitive is rendered";
//1prim-cost.md).
auto RDP::admit(Clock at) -> void {
  while(true) {
    retire();
    if(pipe.count == Slots) return;
    rdp_span_info info;
    if(!rdp_render_span_peek(pipe.queued, &info)) return;
    //the slot past a primitive's last real span draws nothing and never enters the pipe
    if(info.phantom) {
      if(pipe.queued) pipe.queued++;
      else rdp_render_span_run();
      continue;
    }
    if(info.atomic && info.primitive != pipe.lastPrimitive) {
      if(pipe.count || pipe.current >= 0) return;
      Clock barrier = max(pipe.lastWrite, pipe.lastSpanEnd + Timing::Behavior::RdpAtomicDead);
      if(barrier > at) return wakeAt(barrier);
    }

    const bool rmw = info.cycle_type <= 1;
    const bool z = rmw && (info.z_compare || info.z_update);
    const u32 bpps[2] = {bytesPerPixel(info.fb_size), z ? 2u : 0u};
    const bool reads[2] = {rmw && info.image_read, rmw && info.z_compare};
    const u32 bases[2] = {info.fb_address & 0xffffff, info.zb_address & 0xffffff};
    const bool empty = info.x1 < info.x0;
    const u32 pixels = spanPixels(info);

    //where each image's stream puts the span: phase-aligned (4 positions of
    //4 B as measured at 32 bpp; the same 4 positions at 16 bpp, where nothing
    //measures them), in a new instance when the half size changes
    struct Place { u32 instance, offset, size, segments; } place[2];
    for(u32 image : {(u32)Color, (u32)Depth}) {
      auto& s = image == Color ? pipe.color : pipe.depth;
      auto& p = place[image];
      p = {s.instance, s.offset, s.size, 0};
      const bool used = rmw && bpps[image] && !empty;
      if(used) {
        u32 size = halfPixels(image, bpps[image]);
        if(size != p.size && p.offset) p.instance++, p.offset = 0;
        p.size = size;
      }
      if(!p.size) continue;
      p.offset += ((u32)info.x0 - p.offset) & (u32)(Timing::Behavior::RdpSpanRamSegment / 4 - 1);
      if(p.offset >= p.size) p.instance++, p.offset -= p.size;
      if(!used) continue;
      if(!s.usable(p.instance)) return;
      p.segments = pixels ? (p.offset + pixels + p.size - 1) / p.size : 1;
      if(s.count + p.segments + 1 > Segments) return;
    }

    u32 index = (pipe.head + pipe.count) % Slots;
    auto& slot = slots[index];
    slot.info = info;
    slot.writes = 0;
    slot.shaded = false;
    slot.queued = true;
    slot.drawn = 0;
    pipe.count++;
    pipe.admitted++;
    pipe.queued++;
    pipe.lastPrimitive = info.primitive;

    for(u32 image : {(u32)Color, (u32)Depth}) {
      auto& s = image == Color ? pipe.color : pipe.depth;
      auto& w = image == Color ? slot.color : slot.depth;
      auto& p = place[image];
      const u32 bpp = bpps[image];
      w.lo = w.hi = 0;
      if(bpp && !empty) {
        u32 row = bases[image] + ((u32)info.y * info.fb_width + (u32)info.x0) * bpp;
        u32 end = bases[image] + ((u32)info.y * info.fb_width + (u32)info.x1 + 1) * bpp;
        w.lo = row & ~7;
        w.hi = (end + 7) & ~7;
        if(w.hi - w.lo > SpanBytes) w.hi = w.lo + SpanBytes;
        memory::fill<u8>(w.data, w.hi - w.lo, 0);
        memory::fill<u8>(w.hidden, (w.hi - w.lo) / 2, 0);
      }
      s.instance = p.instance, s.offset = p.offset, s.size = p.size;
      if(!rmw || !bpp || empty) continue;
      //one segment per half instance the span's pixels reach; the first
      //starts at the window's start, the last ends at its end (the walk can
      //touch one position past the drawn width)
      const u32 row = bases[image] + ((u32)info.y * info.fb_width + (u32)info.x0) * bpp;
      u32 first = 0;
      do {
        u32 n = min(pixels - first, s.size - s.offset);
        auto& g = s.segments[(s.head + s.count) % Segments];
        g = {};
        g.slot = index;
        g.read = reads[image];
        g.instance = s.instance;
        g.first = first;
        g.end = first + n;
        g.lo = first ? max(w.lo, (row + first * bpp) & ~7) : w.lo;
        g.hi = g.end < pixels ? min(w.hi, (row + g.end * bpp + 7) & ~7) : w.hi;
        if(g.hi < g.lo) g.hi = g.lo;
        s.count++;
        first += n;
        s.offset += n;
        if(s.offset == s.size) s.instance++, s.offset = 0;
      } while(first < pixels);
    }
  }
}

//Queues each image's segment reads in stream order, as their halves become usable.
auto RDP::postReads() -> void {
  for(u32 image : {(u32)Color, (u32)Depth}) {
    auto& s = image == Color ? pipe.color : pipe.depth;
    while(s.posted < s.count) {
      auto& g = s.segment(s.posted);
      if(!s.usable(g.instance)) break;
      if(g.read) splitBursts(g.lo, g.hi, Timing::Behavior::RiMaxBurst, [&](u32 a, u32 n) {
        memory.queue.push_back({a, (u8)n, 0, g.slot, (u8)image, 0xff, (u8)((s.head + s.posted) % Segments)});
        g.reads++;
      });
      g.posted = 1;
      s.posted++;
    }
  }
}

//The pipeline takes the oldest admitted span; it enters the pipe with its
//first chunk.
auto RDP::startSpan(Clock at) -> bool {
  if(!pipe.admitted) return false;
  pipe.current = (pipe.head + pipe.count - pipe.admitted) % Slots;
  pipe.pixel = 0;
  pipe.stalls = 0;
  pipe.spanStart = Clock::never();
  return true;
}

//Draws the current span from the bytes its reads delivered so far, into
//`out`; pixels whose halves have not landed draw from zeros and are drawn
//again later. Each pixel samples the noise at its own pipeline clock, plus
//the open rdp.noise-pixel-offset; a 2-cycle pixel at its first clock. The
//final draw leaves the engine's span queue.
auto RDP::draw(bool final) -> void {
  auto& slot = slots[pipe.current];
  rdp_memwin windows[2];
  u32 n = 0;
  for(auto* w : {&slot.color, &slot.depth}) {
    if(w->hi == w->lo) continue;
    const u32 bytes = w->hi - w->lo;
    memory::copy<u8>(w->out, w->data, bytes);
    memory::copy<u8>(w->outHidden, w->hidden, bytes / 2);
    memory::fill<u8>(w->written, bytes, 0);
    windows[n++] = {w->lo, w->hi, w->data, w->hidden, w->written, w->out, w->outHidden};
  }
  rdp_render_set_windows(windows, n);
  const u64 first = (Timing::nextRclkEdge(pipe.spanStart) + Timing::Behavior::RdpNoisePixelOffset).units / Timing::UnitsPerRclk;
  rdp_render_set_span_clock(first, RDPTimed::pixelClocks(slot.info.cycle_type, 1).units / Timing::UnitsPerRclk);
  rdp_render_set_span_stalls(pipe.stallPixel, pipe.stallClocks, pipe.stalls);
  auto host = std::chrono::steady_clock::now();
  if(final) rdp_render_span_run();
  else rdp_render_span_draw();
  engine.renderNanoseconds += std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - host).count();
  rdp_render_set_windows(nullptr, 0);
  rdp_render_set_span_stalls(nullptr, nullptr, 0);
  if(!final) return;
  slot.queued = false;
  pipe.queued--;
  //the slot past a primitive's last span, queued behind this one
  rdp_span_info info;
  while(pipe.queued && rdp_render_span_peek(0, &info) && info.phantom) rdp_render_span_run(), pipe.queued--;
}

//Runs the next chunk of the current span: the pixels up to the end of the
//segment it is in, in each image. A chunk starts once each image's half is
//usable and, where the span reads the image, the segment's read has landed.
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
      auto& g = s.segment(0);
      if(!s.usable(g.instance)) return false;
      if(g.instance >= 2) start = max(start, s.halves[g.instance & 1].drained);
      if(g.read) {
        if(!g.posted || g.reads) return false;
        start = max(start, g.ready);
      }
      k = min(k, g.end - pipe.pixel);
    }
    clocks = RDPTimed::pixelClocks(info.cycle_type, k);
    if(pipe.pixel + k == pixels) clocks += RDPTimed::spanTail(info.cycle_type);
  } else {
    //fill and copy bypass the span buffers ("committed straight to RDRAM",
    //span-ram.md row 13): a span runs once the previous one's writes are in the RI
    auto& port = info.cycle_type == 3 ? fillPort : memory;
    for(auto& p : port.queue) if(p.write) return false;
    const u32 bpp = bytesPerPixel(info.fb_size);
    u64 words = bpp && pixels ? ((u64)(info.x0 + pixels) * bpp + 7) / 8 - (u64)info.x0 * bpp / 8 : 0;
    clocks = RDPTimed::wordClocks(words);
  }
  if(start > at) return wakeAt(start), false;
  if(pipe.spanStart == Clock::never()) {
    pipe.spanStart = start;
    pipe.admitted--;
    //a span with no halves (fill, copy, or nothing to touch) draws at once
    bool halves = false;
    if(info.cycle_type <= 1) for(auto* w : {&slot.color, &slot.depth}) halves |= w->hi > w->lo;
    if(!halves) draw(true);
  } else {
    const s64 late = (Timing::nextRclkEdge(start) - Timing::nextRclkEdge(pipe.spanStart)).units / Timing::UnitsPerRclk
                   - (s64)pipe.pixel * (RDPTimed::pixelClocks(info.cycle_type, 1).units / Timing::UnitsPerRclk);
    if(late > (pipe.stalls ? (s64)pipe.stallClocks[pipe.stalls - 1] : 0)) {
      pipe.stallPixel[pipe.stalls] = pipe.pixel;
      pipe.stallClocks[pipe.stalls++] = (u32)late;
    }
  }
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
      auto& g = s.segment(0);
      if(pipe.pixel < g.end) continue;
      //a segment's end, at a half boundary or the span's end, writes back (span-ram.md row 6)
      writeBack(image, g.first, pipe.pixel, at);
      s.head = (s.head + 1) % Segments;
      s.count--;
      s.posted--;
      drain(image, at);
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
//range posts nothing (rdp-write-granularity.md). The span is drawn first if
//its last draw predates bytes these pixels need.
auto RDP::writeBack(u32 image, u32 firstPixel, u32 endPixel, Clock at) -> void {
  auto& slot = slots[pipe.current];
  auto& info = slot.info;
  auto& w = image == Color ? slot.color : slot.depth;
  const bool direct = info.cycle_type >= 2;
  if(slot.queued && (slot.drawn < endPixel || endPixel >= spanPixels(info))) {
    //pixels drawn from landed bytes: up to the first segment still reading,
    //and, if noise is used, up to the last pixel whose clock is known
    u32 drawn = spanPixels(info);
    for(auto* s : {&pipe.color, &pipe.depth})
      for(u32 i = 0; i < s->count && s->segment(i).slot == pipe.current; i++) {
        auto& g = s->segment(i);
        if(g.read && (!g.posted || g.reads)) { drawn = min(drawn, g.first); break; }
      }
    if(info.noise) drawn = min(drawn, pipe.pixel);
    draw(drawn >= spanPixels(info));
    slot.drawn = drawn;
  }
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
    half = s.segment(0).instance & 1;
    h = &s.halves[half];
  }
  u32 bursts = 0;
  for(u32 a = lo; a < hi;) {
    if(!w.written[a - w.lo]) { a++; continue; }
    u32 end = a;
    while(end < hi && w.written[end - w.lo]) end++;
    splitBursts(a, end, Timing::Behavior::RiMaxBurst, [&](u32 b, u32 n) {
      port.queue.push_back({b, (u8)n, 1, (u8)pipe.current, (u8)image, half, 0});
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
    admit(at);
    //an admitted span can move a stream past an instance that has otherwise drained
    drain(Color, at), drain(Depth, at);
    postReads();
    if(pipe.chunk) {
      if(pipe.chunkEnd > at) return;
      endChunk(pipe.chunkEnd);
      continue;
    }
    if(pipe.current < 0 && !startSpan(at)) return;
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

  Clock busy, setup;
  for(u32 n : range(count)) {
    auto& w = works[n];
    auto c = RDPTimed::cost({w.command, w.cycle_type, w.pixels, w.words, w.lines, w.load_bytes});
    if(n == 0) setup = c.busy;
    busy += c.busy;
    executor.load |= c.load;
    executor.syncFull |= c.syncFull;
    debugger.command(w.word);
  }
  executor.busy = true;
  if(isSync(command) && pipe.time > at) at = pipe.time;
  executor.until = at + busy;
  if(isSync(command)) pipe.time = executor.until;
  //a primitive's spans enter the pipeline after its own setup; the unsynced
  //writes its hazard window collected run in the command processor meanwhile
  if(isPrimitive(command) && pipe.time < at + setup) pipe.time = at + setup;
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
  changed();
  timeline.wake(Timing::ActorId::RDP);
}
