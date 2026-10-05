//Reality Display Processor

struct RDP : Thread, Memory::RCP<RDP> {
  Node::Object node;

  struct Debugger {
    //debugger.cpp
    auto load(Node::Object) -> void;
    auto commands() -> void;
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
  auto flushCommands() -> void;

  //serialization.cpp
  auto serialize(serializer&) -> void;

  //engine.cpp
  auto syncFull() -> void;

  //cen64-jgemu pixel engine (engine/): the RDP's rasterizer and its state
  struct Engine {
    auto load() -> void;
    auto unload() -> void;
    auto render() -> void;
    auto serialize(serializer&) -> void;
    auto dpsArm() -> void;
    auto dpsTake(u32 words[32]) -> bool;
    auto pixels() -> u64;
    auto colorImage() -> u32;
    auto maskImage() -> u32;
    auto tmem() -> u8*;

    bool loaded = false;
    u32  regs[8] = {};
    //host time spent inside render(); measurement only, never fed back into emulation
    u64  renderNanoseconds = 0;
    u64  renderCalls = 0;
  } engine;

  struct Command {
    n24 start;
    n24 end;
    n24 current;
    Clock clockOrigin;  //DPC_CLOCK counts RCP clocks since this time
    n24 bufferBusy;
    n24 pipeBusy;
    n24 tmemBusy;
    n1  source;  //0 = RDRAM, 1 = DMEM
    n1  freeze;
    n1  crashed;
    n1  flush;
    n1  startValid;
    n1  endValid;
    n1  startGclk;
    n1  ready = 1;
  } command;

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
