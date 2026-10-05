//The RDP as a timeline actor (ADR 0001 Decision 3, plan T12).
//
//One step handles everything due at one RCP clock edge, in hardware order:
//the command processor retires what it was running, the command DMA's words
//land in the FIFO, the next command dispatches, and the DMA asks for more.
//The pixel engine renders a command whole at its dispatch; its time is the
//compute cost in timed.hpp.

//ARES_DPLOG=<file> logs DPC register traffic and the DP interrupt, one line
//each, for checking the RSP's back-pressure loops (rsp-rdp-fifo.md). Host-side
//only; it never changes emulation.
static FILE* dpLog = [] { auto path = getenv("ARES_DPLOG"); return path ? fopen(path, "w") : (FILE*)nullptr; }();

static auto dpLogActor(Timing::ActorId id) -> const char* {
  return id == Timing::ActorId::CPU ? "cpu" : id == Timing::ActorId::RSP ? "rsp" : "dbg";
}

auto RDP::dispatchable() const -> bool {
  return !executor.busy && !dpc.freeze && !dpc.crashed && rdp_render_engine_need() == 0;
}

auto RDP::readiness() const -> Timing::Readiness {
  Clock next = Clock::never();
  if(fetch.dwords) next = fetch.arrival;
  if((executor.busy || dispatchable()) && executor.until < next) next = executor.until;
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
  }
}

auto RDP::step(Clock at) -> void {
  if(executor.busy && executor.until <= at) {
    executor.busy = false;
    if(executor.load) dpc.tmem.set(false, at), executor.load = false;
    if(executor.syncFull) {
      executor.syncFull = false;
      dpc.syncFullRetired(at);
      mi.raise(MI::IRQ::DP);
      if(dpLog) fprintf(dpLog, "I %lld rsp_halted=%u\n", (long long)at.units, (u32)rsp.status.halted);
    }
  }
  if(fetch.dwords && fetch.arrival <= at) {
    rdp_render_engine_feed(dpc.current, fetch.dwords, dpc.xbus);
    dpc.fetched(fetch.dwords * sizeof(u64));
    fetch.dwords = 0;
  }
  if(dispatchable()) dispatch(at);
  startFetch(at);
  dpc.cmd.set(executor.busy || rdp_render_engine_buffered() > 0, at);
}

auto RDP::dispatch(Clock at) -> void {
  rdp_engine_work works[Timing::Behavior::RdpCmdFifoDwords];
  auto start = std::chrono::steady_clock::now();
  int count = rdp_render_engine_step(works, Timing::Behavior::RdpCmdFifoDwords);
  engine.renderNanoseconds += std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start).count();
  engine.renderCalls++;
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
  executor.until = at + busy;
  if(executor.load) dpc.tmem.set(true, at);
  if(rdp_render_crashed()) crash("pixel engine pipeline crash");
}

auto RDP::startFetch(Clock at) -> void {
  if(fetch.dwords) return;
  u32 dwords = RDPTimed::fetchDwords(dpc, rdp_render_engine_buffered());
  if(!dwords) return;
  if(!mapIdentityWarned && !rdram.mapIdentity && !dpc.xbus) {
    debug(unusual, "[RDP] started while RDRAM DeviceId map is non-identity");
    mapIdentityWarned = 1;
  }
  fetch.dwords = dwords;
  fetch.arrival = Timing::nextRclkEdge(Timing::nextRclkEdge(at) + RDPTimed::fetchLatency(dwords, dpc.xbus));
}

//Another actor changed the DPC registers at `at`: the DMA may start and the
//command processor may resume.
auto RDP::kick(Clock at) -> void {
  if(!executor.busy && executor.until < Timing::nextRclkEdge(at)) executor.until = Timing::nextRclkEdge(at);
  startFetch(at);
  timeline.wake(Timing::ActorId::RDP);
}
