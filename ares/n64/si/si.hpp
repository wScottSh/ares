//Serial Interface

struct SI : Memory::RCP<SI> {
  Node::Object node;

  struct Debugger {
    //debugger.cpp
    auto load(Node::Object) -> void;
    auto io(bool mode, u32 address, u32 data) -> void;

    struct Tracer {
      Node::Debugger::Tracer::Notification io;
    } tracer;
  } debugger;

  //si.cpp
  auto load(Node::Object) -> void;
  auto unload() -> void;
  auto power(bool reset) -> void;

  //dma.cpp
  struct DMA : RiBus::Client {
    enum class Phase : u8 { Idle, Joybus, Posted, Landed, Due };
    Phase phase = Phase::Idle;
    n1  toRdram;   //READ64B: PIF RAM to RDRAM
    u32 offset = 0;  //bytes of the 64 already granted
    u8  block[64];

    auto buffer(const RiBus::Burst&) -> void* override;
    auto granted(const RiBus::Grant&) -> void override;
  } dma;

  auto dmaPost(Clock at) -> void;
  auto dmaStep() -> void;
  auto dmaFinish() -> void;

  //io.cpp
  auto ioRead(u32 address) -> u32;
  auto ioWrite(u32 address, u32 data, Thread& thread) -> void;
  auto readWord(u32 address, Thread& thread) -> u32;
  auto writeWord(u32 address, u32 data, Thread& thread) -> void;
  auto writeFinished() -> void;
  auto writeForceFinish() -> void;

  //serialization.cpp
  auto serialize(serializer&) -> void;

  struct IO {
    n24 dramAddress;
    n32 readAddress;
    n32 writeAddress;
    u32 busLatch;
    n1  dmaBusy;
    n1  ioBusy;
    n1  readPending;
    n4  pchState;
    n4  dmaState;
    n1  dmaError;
    n1  interrupt;
  } io;
};

extern SI si;
