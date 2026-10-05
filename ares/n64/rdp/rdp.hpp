//Reality Display Processor

#include <n64/rdp/timed.hpp>

struct RDP : Thread, Memory::RCP<RDP>, Timing::Actor {
  Node::Object node;

  RDP() { Thread::actor = Timing::ActorId::RDP; }

  struct Debugger {
    //debugger.cpp
    auto load(Node::Object) -> void;
    auto command(u64 word) -> void;
    auto ioDPC(bool mode, u32 address, u32 data) -> void;
    auto ioDPS(bool mode, u32 address, u32 data) -> void;

    struct Tracer {
      Node::Debugger::Tracer::Notification command;
      Node::Debugger::Tracer::Notification io;
    } tracer;
  } debugger;

  //rdp.cpp
  auto load(Node::Object) -> void;
  auto unload() -> void;

  auto power(bool reset) -> void;
  auto crash(const char *reason) -> void;

  //io.cpp
  auto readWord(u32 address, Thread& thread) -> u32;
  auto writeWord(u32 address, u32 data, Thread& thread) -> void;

  //timed.cpp: a timeline actor; command fetch, dispatch and SYNC_FULL retire
  auto readiness() const -> Timing::Readiness override;
  auto run(Clock limit) -> void override;
  auto kick(Clock at) -> void;
  auto step(Clock at) -> void;
  auto startFetch(Clock at) -> void;
  auto dispatch(Clock at) -> void;
  auto dispatchable() const -> bool;

  //serialization.cpp
  auto serialize(serializer&) -> void;

  //cen64-jgemu pixel engine (engine/): the RDP's rasterizer and its state
  struct Engine {
    auto load() -> void;
    auto unload() -> void;
    auto serialize(serializer&) -> void;
    auto dpsArm() -> void;
    auto dpsTake(u32 words[32]) -> bool;
    auto pixels() -> u64;
    auto colorImage() -> u32;
    auto maskImage() -> u32;
    auto tmem() -> u8*;

    bool loaded = false;
    //host time spent inside dispatch; measurement only, never fed back into emulation
    u64  renderNanoseconds = 0;
    u64  renderCalls = 0;
  } engine;

  RDPTimed::Dpc dpc;

  //The command DMA request in flight; its words land at `arrival`.
  struct Fetch {
    u32   dwords = 0;
    Clock arrival;
  } fetch;

  //The command processor: busy with one dispatch until `until`, or idle and
  //free to dispatch from `until` on.
  struct Executor {
    bool  busy = false;
    bool  load = false;
    bool  syncFull = false;
    Clock until;
  } executor;

  struct IO : Memory::RCP<IO> {
    RDP& self;
    IO(RDP& self) : self(self) {}

    //io.cpp
    auto readWord(u32 address, Thread& thread) -> u32;
    auto writeWord(u32 address, u32 data, Thread& thread) -> void;

    struct BIST {
      n1 check;
      n1 go;
      n1 done;
      n8 fail;
    } bist;
    struct Test {
      n1  enable;
      n7  address;
      array<u32[128]> data;
    } test;

  } io{*this};

  n1 mapIdentityWarned;
};

extern RDP rdp;
