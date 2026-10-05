//RDRAM Interface

#include <n64/ri/bus.hpp>

//The RI registers, and the RDRAM channel as the timeline's Bus actor: the one
//owner of RDRAM bytes and RDRAM time among hardware clients (ADR 0001 Decision 2).
//Clients post bursts; at each grant the RI moves the burst's bytes between
//rdram.ram and the client's buffer, in grant order, so RDRAM content and RDRAM
//timing cannot disagree.
struct RI : Memory::RCP<RI>, Timing::Actor {
  Node::Object node;

  struct Client {
    //The buffer for burst `tag`, asked for at grant time. Reads fill it, writes drain it.
    virtual auto buffer(const RiBus::Burst&) -> void* = 0;
    //The bytes have moved. A client may post its next burst from here.
    virtual auto granted(const RiBus::Grant&) -> void = 0;
  };

  struct Debugger {
    //debugger.cpp
    auto load(Node::Object) -> void;
    auto io(bool mode, u32 address, u32 data) -> void;

    struct Tracer {
      Node::Debugger::Tracer::Notification io;
    } tracer;
  } debugger;

  //ri.cpp
  auto load(Node::Object) -> void;
  auto unload() -> void;
  auto power(bool reset) -> void;
  auto active() const -> bool { return io.currentLoaded && io.select == 0x14; }
  auto ackError() -> void { io.error.bit(0) = 1; }
  auto checkRefresh() -> void;

  //io.cpp
  auto readWord(u32 address, Thread& thread) -> u32;
  auto writeWord(u32 address, u32 data, Thread& thread) -> void;

  //bus.cpp
  auto attach(RiBus::Requester, Client*) -> void;
  auto post(const RiBus::Burst&, Clock at) -> void;
  auto refresh(Clock at) -> void;
  //Posts the burst and, when horizon() proves no other actor can act before
  //its decision, grants it at once. Else the timeline grants it later.
  auto postAndDecide(const RiBus::Burst&, Clock at) -> bool;
  auto readiness() const -> Timing::Readiness override;
  auto run(Clock limit) -> void override;

  //serialization.cpp
  auto serialize(serializer&) -> void;

  RiBus::Channel channel;
  Client* clients[(u32)RiBus::Requester::Count] = {};

  struct IO {
    n32 mode;
    n32 config;
    n32 currentLoad;
    n32 select;
    n32 refresh;
    n32 latency;
    n32 error;
    n32 bankStatus;
    n1  currentLoaded;
  } io;

  n1 refreshWarned;
};

extern RI ri;
