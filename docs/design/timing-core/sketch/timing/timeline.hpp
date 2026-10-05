//The shared timeline: one deterministic, conservative discrete-event
//scheduler over every timed thing in the console.
//
//Invariant (the only one callers rely on):
//  When an actor performs an interaction at time t (a bus request, a read or
//  write of another device's state, an interrupt), every other actor has
//  already performed every interaction it has before t, and none after t.
//
//Ordering comes from timestamps alone, with a fixed tie-break rank. How often
//the host switches between actors cannot change any result, so the
//interpreter-per-instruction loop and any future block executor see the same
//timeline (recompiler-parity.md, "sync-granularity independence"). The
//`stepCap` run mode (n64-run --step-cap) proves it: with the CPU's horizon
//skip disabled, the per-field stats and TraceHash must equal the normal run.
//
//No cothreads. Only the CPU ever waits inside a call (for its own bus
//grant), and it is always the outermost frame. Every other actor is a
//resumable state machine that returns when it reaches its limit or its
//horizon. Nested catch-up (the RSP reading DPC_CURRENT, a SysAD drain writing
//DPC_END) recurses with strictly decreasing targets, so depth <= actor count.

namespace ares::Nintendo64::Timing {

//Declaration order is the tie-break rank at equal timestamps. It is a
//convention, not a hardware fact; it is recorded as behavior
//`scheduler.tie-rank` so the spec states it.
enum class ActorId : u8 {
  Bus,     //RI arbitration decisions (ri/bus.hpp)
  Events,  //VI, AI, PI, SI, refresh, COUNT/COMPARE: fully scheduled devices
  SysAD,   //VR4300 write buffer drain and the SysAD read port (cpu/sysad.hpp)
  RDP,     //rdp/timed.hpp
  RSP,     //rsp/actor.hpp
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
};

//The contract every stepped actor implements. step() advances by at least one
//indivisible step that starts before `limit`, and may end after it (an RSP
//issue pair, one RDP segment). A step's interactions are stamped with times
//at or after the step's start.
struct Actor {
  virtual auto readiness() const -> Readiness = 0;
  virtual auto step(Clock limit) -> void = 0;
};

struct Timeline {
  //Registration happens once at power-on; the set of actors is fixed.
  auto attach(ActorId, Actor&) -> void;

  //Called by the CPU before each instruction when `cpuTime >= horizon()`, and
  //by any actor about to interact at `t`. Advances every actor that is not
  //already on the call stack until it is past `t`, in timestamp order, firing
  //bus decisions as they become safe.
  //
  //  push caller with its current time onto the stack
  //  loop:
  //    floor = min(t, times of actors on the stack)
  //    a = argmin over Runnable actors not on the stack of (at, rank)
  //    if a.at > floor, or a.at == floor and rank(a) >= rank(caller): break
  //    a.step(floor)
  //    trace.fold(a.at, id(a), ...)       //verify.hpp
  //    refresh cached horizon
  //  pop
  auto catchUp(Clock t, ActorId caller) -> void;

  //The CPU's blocking wait for its own transaction. The CPU is Blocked, so it
  //is not a floor; everything else runs in timestamp order until the bus
  //marks the ticket complete.
  //
  //  while(!bus.complete(ticket)):
  //    a = argmin over Runnable actors other than CPU of (at, rank)
  //    a.step(Clock::never())
  template<typename Ticket> auto await(Ticket ticket) -> Clock;

  //The earliest time any actor other than the CPU could interact. The CPU
  //interpreter runs instructions without calling catchUp while its time is
  //below this. With the RSP halted, the RDP idle and the bus empty, this is
  //the next VI/AI/PI/SI/timer event, so the CPU runs long stretches alone.
  //Under stepCap it returns Clock{0}, so the CPU calls catchUp every
  //instruction; the result must not change (checks.tsv: stepcap).
  auto horizon() const -> Clock { return stepCap ? Clock{0} : cachedHorizon; }

  //Fully scheduled devices post their future work here instead of being
  //stepped. Replaces nall's relative-delay priority_queue and its
  //"fires relative to the last sync" skew (ares-timing-architecture.md s.1).
  struct Event {
    Clock at;
    u32   kind;   //EventKind from devices/events.hpp
    u32   arg;
  };
  auto schedule(Event) -> void;
  auto cancel(u32 kind) -> void;

  bool stepCap = false;   //set once by n64-run --step-cap; never a toggle in the core's behavior

private:
  Actor* actors[(u32)ActorId::Count] = {};
  u8     onStack = 0;  //bitmask of ActorId
  Clock  stackTime[(u32)ActorId::Count];
  Clock  cachedHorizon;
  //binary heap ordered by (at, kind); kind order is the tie-break among events
  vector<Event> events;
};

extern Timeline timeline;

}
