//The shared timeline: one deterministic, conservative discrete-event
//scheduler over every timed thing in the console (ADR 0001, Decision 1).
//
//Invariant (the only one callers rely on):
//  When an actor performs an interaction at time t (a bus request, a read or
//  write of another device's state, an interrupt), every other actor has
//  already performed every interaction it has before t, and none after t.
//
//Ordering comes from timestamps alone, with a fixed tie-break rank. How often
//the host switches between actors cannot change any result. The stepCap run
//mode (n64-run --step-cap) proves it: with the CPU's horizon skip disabled,
//the per-field stats and trace hash must equal the normal run.
//
//No cothreads. The CPU is the master loop and always the outermost frame.
//Every other actor is a resumable state machine that returns when it reaches
//its limit. Nested catch-ups recurse with non-increasing floors, so depth is
//bounded by the actor count.
//
//This header stands alone on clock.hpp and the nall integer types, so the
//host unit test (tools/n64-timing/tests) compiles it without the core.

namespace Timing {

//Declaration order is the tie-break rank at equal timestamps. It is a
//convention, not a hardware fact (behaviors.tsv: scheduler.tie-rank).
enum class ActorId : u8 {
  Bus,     //RI arbitration decisions (plan T6)
  Events,  //VI, AI, PI, SI, PIF, COMPARE, cartridge timers: the event heap below
  SysAD,   //VR4300 write buffer drain and the SysAD read port (plan T6)
  RDP,     //rdp/timed.hpp (plan T12)
  RSP,     //rsp/rsp.hpp
  CPU,     //the master loop; never stepped by the timeline
  Count,
};

//What an actor tells the timeline about itself. A pure function of the
//actor's own state, recomputed after each of its steps.
struct Readiness {
  enum class Kind : u8 {
    Runnable,  //next step starts at `at`
    Blocked,   //waiting for a bus decision; the bus will wake it
    Parked,    //cannot act until another actor acts on it (halted RSP, idle RDP)
  } kind = Kind::Parked;
  Clock at = Clock::never();

  static constexpr auto runnable(Clock at) -> Readiness { return {Kind::Runnable, at}; }
  static constexpr auto blocked() -> Readiness { return {Kind::Blocked, Clock::never()}; }
  static constexpr auto parked() -> Readiness { return {}; }
};

//The contract every stepped actor implements. run(limit) performs one
//indivisible step (an RSP issue pair, one DMA landing), then may keep going
//while its next step starts before `limit`. A step's interactions are stamped
//with its start time, which is the `at` the actor reported. `limit` was the
//next contender when run() began, so a run that schedules an event or wakes an
//actor earlier than `limit` must return after that step: it compares its next
//step with timeline.limit(limit), not with `limit`.
//Each step after the first is folded with timeline.record().
struct Actor {
  virtual auto readiness() const -> Readiness = 0;
  virtual auto run(Clock limit) -> void = 0;
};

struct Timeline {
  //Fully scheduled devices post their future work here instead of being
  //stepped. Absolute times replace nall's relative-delay queue and its
  //"fires relative to the last sync" skew (ares-timing-architecture.md s.1).
  //Equal times fire in `kind` order, then in posting order.
  struct Event {
    Clock at;
    u32   kind;
  };
  using Handler = void (*)(const Event&);
  static constexpr u32 EventCapacity = 64;

  //Power-on. Actors stay attached; events and the trace restart.
  auto reset(Handler handler) -> void {
    fire = handler;
    count = 0;
    onStack = 0;
    depth = 0;
    maxDepth = 0;
    trace = 0;
    firing = false;
    refreshHorizon();
  }

  auto attach(ActorId id, Actor* actor) -> void {
    if(!actors[(u8)id]) enlist(id);
    actors[(u8)id] = actor;
    refreshHorizon();
  }

  //The CPU calls this before each instruction whose start time has reached
  //horizon(), and any actor calls it before interacting at `t`. Advances every
  //actor that is not already on the call stack until it is past `t`, in
  //(time, rank) order.
  auto catchUp(Clock t, ActorId caller) -> void {
    if(t < cachedHorizon) return;
    advance(t, caller);
  }

  //The earliest time any actor other than the CPU could act. Under stepCap it
  //is Clock{0}, so the CPU calls catchUp before every instruction.
  auto horizon() const -> Clock { return cachedHorizon; }

  //An actor whose readiness another actor just changed (the CPU unhalting the
  //RSP, a DMA start) lowers the horizon here. A step never needs this: the
  //loop refreshes after every step.
  auto wake(ActorId id) -> void {
    if(auto actor = actors[(u8)id]) {
      auto r = actor->readiness();
      if(r.kind != Readiness::Kind::Runnable) return;
      if(r.at < cachedHorizon) cachedHorizon = r.at;
      if(r.at < woken) woken = r.at;
    }
  }

  //The limit a running actor or the event loop must stop at: its own, or
  //earlier if something it did woke an actor that must run first.
  auto limit(Clock limit) const -> Clock { return woken < limit ? woken : limit; }

  //The earliest time any actor or event other than the CPU acts, ignoring
  //stepCap. The CPU blocked on its own SysAD transaction advances to it.
  auto earliest() const -> Clock {
    Clock h = count ? events[0].at : Clock::never();
    for(u8 i = 0; i < listedCount; i++) {
      auto id = listed[i];
      if(id == ActorId::Events) continue;
      auto r = actors[(u8)id]->readiness();
      if(r.kind == Readiness::Kind::Runnable && r.at < h) h = r.at;
    }
    return h;
  }

  //Folds a step advance() did not start: the second and later steps of one
  //run(), and the CPU deciding its own bus grant when horizon() proves no
  //other actor can act first. The trace then holds one record per step, the
  //same however the steps were batched.
  auto record(Clock at, ActorId id) -> void { fold(at, id, 0); }

  //Runs `f` as if an event handler were running at `t`, so now() is `t`: a
  //SysAD drain performs the CPU's posted register write at the drain's time.
  template<typename F> auto actingAt(Clock t, F&& f) -> void {
    const bool wasFiring = firing;
    const Clock wasFiringAt = firingAt;
    firing = true;
    firingAt = t;
    f();
    firing = wasFiring;
    firingAt = wasFiringAt;
  }

  auto schedule(Event event) -> void {
    //every kind has one pending event in practice; a full heap means a device reposts without cancelling
    if(count == EventCapacity) abort();
    u32 i = count;
    while(i > 0 && later(events[i - 1], event)) {
      events[i] = events[i - 1];
      i--;
    }
    events[i] = event;
    count++;
    if(event.at < cachedHorizon) cachedHorizon = event.at;
    if(event.at < woken) woken = event.at;
  }

  //Removes every pending event of `kind` and returns the latest of their
  //times, or Clock::never() when none was pending.
  auto cancel(u32 kind) -> Clock {
    Clock latest = Clock::never();
    u32 kept = 0;
    for(u32 i = 0; i < count; i++) {
      if(events[i].kind == kind) {
        latest = latest == Clock::never() ? events[i].at : (events[i].at > latest ? events[i].at : latest);
      } else {
        events[kept++] = events[i];
      }
    }
    count = kept;
    return latest;
  }

  auto pending(u32 kind) const -> bool {
    for(u32 i = 0; i < count; i++) if(events[i].kind == kind) return true;
    return false;
  }

  //The time an event handler is running at, so a handler that reposts itself
  //(RTC tick, GDB poll) counts from its own time. Outside a handler the caller
  //supplies its own clock.
  auto now(Clock fallback) const -> Clock { return firing ? firingAt : fallback; }

  auto setStepCap(bool on) -> void {
    stepCap = on;
    refreshHorizon();
  }

  //Recomputes the horizon from every actor. Called after a load, when every
  //actor's state is in place.
  auto refreshHorizon() -> void {
    if(stepCap) { cachedHorizon = {}; return; }
    Clock h = count ? events[0].at : Clock::never();
    for(u8 i = 0; i < listedCount; i++) {
      auto id = listed[i];
      if(id == ActorId::Events) continue;
      auto r = actors[(u8)id]->readiness();
      if(r.kind == Readiness::Kind::Runnable && r.at < h) h = r.at;
    }
    cachedHorizon = h;
  }

  template<typename S> auto serialize(S& s) -> void {
    s(count);
    for(u32 i = 0; i < EventCapacity; i++) {
      s(events[i].at.units);
      s(events[i].kind);
    }
    s(trace);
  }

  bool stepCap = false;  //set once by n64-run --step-cap; never a toggle in the core's behavior
  u64  trace = 0;        //rolling hash of every step and event; TraceHash folds it per field
  u32  maxDepth = 0;     //deepest nesting seen; the unit test bounds it by the actor count

private:
  static auto later(const Event& a, const Event& b) -> bool {
    return a.at > b.at || (a.at == b.at && a.kind > b.kind);
  }

  auto fold(Clock at, ActorId id, u32 kind) -> void {
    //splitmix64 finalizer over the step record; cheap enough for one call per step
    u64 x = trace ^ (u64)at.units ^ ((u64)id << 56) ^ ((u64)kind << 40);
    x ^= x >> 30; x *= 0xbf58476d1ce4e5b9ull;
    x ^= x >> 27; x *= 0x94d049bb133111ebull;
    x ^= x >> 31;
    trace = x;
  }

  auto advance(Clock t, ActorId caller) -> void {
    const u8 callerBit = 1u << (u8)caller;
    const bool nested = onStack & callerBit;
    const Clock saved = stackTime[(u8)caller];
    Clock floor = t;
    if(onStack) {
      for(u8 id = 0; id < (u8)ActorId::Count; id++) {
        if((onStack & (1u << id)) && stackTime[id] < floor) floor = stackTime[id];
      }
    }
    onStack |= callerBit;
    stackTime[(u8)caller] = t;
    if(++depth > maxDepth) maxDepth = depth;

    Clock at;
    while(true) {
      //argmin over runnable actors not on the stack of (at, rank); `listed` is in
      //rank order, so a strict compare keeps the lower rank on ties
      ActorId best = ActorId::Count;
      at = Clock::never();
      Clock second = Clock::never();
      auto consider = [&](ActorId id, Clock c) {
        if(c < at) { second = at; at = c; best = id; }
        else if(c < second) second = c;
      };
      for(u8 i = 0; i < listedCount; i++) {
        auto id = listed[i];
        if(onStack & (1u << (u8)id)) continue;
        if(id == ActorId::Events) {
          if(count) consider(ActorId::Events, events[0].at);
        } else {
          auto r = actors[(u8)id]->readiness();
          if(r.kind == Readiness::Kind::Runnable) consider(id, r.at);
        }
      }
      if(best == ActorId::Count || at > floor || (at == floor && best >= caller)) break;

      //the actor may keep stepping while it stays strictly before the next
      //contender and the floor; ties come back through this loop and its rank rule
      const Clock limit = second < floor ? second : floor;
      onStack |= 1u << (u8)best;
      stackTime[(u8)best] = at;
      if(best != ActorId::Events) fold(at, best, 0);
      const Clock wokenOutside = woken;
      woken = Clock::never();
      if(best == ActorId::Events) fireEvents(limit);
      else actors[(u8)best]->run(limit);
      if(wokenOutside < woken) woken = wokenOutside;
      onStack &= ~(1u << (u8)best);
    }

    depth--;
    if(!nested) onStack &= ~callerBit;
    stackTime[(u8)caller] = saved;
    if(depth > 0) return;
    woken = Clock::never();
    //the CPU is never attached, so with only the CPU on the stack the last scan saw every actor
    if(caller == ActorId::CPU && !stepCap) cachedHorizon = at;
    else refreshHorizon();
  }

  //keeps `listed` in rank order; the scans walk only the event heap and attached actors
  auto enlist(ActorId id) -> void {
    u8 i = listedCount++;
    while(i > 0 && listed[i - 1] > id) listed[i] = listed[i - 1], i--;
    listed[i] = id;
  }

  //A handler that wakes an actor (a VI HSYNC posting a refresh to the bus)
  //ends the batch, so the woken actor's earlier step is not passed over.
  auto fireEvents(Clock limit) -> void {
    const bool wasFiring = firing;
    const Clock wasFiringAt = firingAt;
    do {
      Event event = events[0];
      for(u32 i = 1; i < count; i++) events[i - 1] = events[i];
      count--;
      firing = true;
      firingAt = event.at;
      fold(event.at, ActorId::Events, event.kind);  //one record per event, so batching never shows in the trace
      fire(event);
    } while(count && events[0].at < this->limit(limit));
    firing = wasFiring;
    firingAt = wasFiringAt;
  }

  Handler fire = nullptr;
  Actor*  actors[(u8)ActorId::Count] = {};
  ActorId listed[(u8)ActorId::Count] = {ActorId::Events};
  u8      listedCount = 1;
  u8      onStack = 0;  //bitmask of ActorId
  u32     depth = 0;
  Clock   stackTime[(u8)ActorId::Count] = {};
  Clock   cachedHorizon;
  Event   events[EventCapacity] = {};  //sorted by (at, kind, posting order)
  u32     count = 0;
  bool    firing = false;
  Clock   firingAt;
  Clock   woken = Clock::never();  //earliest wake inside the current step
};

}
