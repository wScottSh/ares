//Peripheral Interface

struct PI : Memory::RCP<PI> {
  Node::Object node;

  struct Debugger {
    //debugger.cpp
    auto load(Node::Object) -> void;
    auto io(bool mode, u32 address, u32 data) -> void;

    struct Tracer {
      Node::Debugger::Tracer::Notification io;
    } tracer;
  } debugger;

  struct IO {
    n1  dmaBusy;
    n1  ioBusy;
    n1  error;
    n1  interrupt;
    n32 dramAddress;
    n32 pbusAddress;
    n32 readLength;
    n32 writeLength;
    n32 busLatch;
    u64 originPc;
  } io;

  struct BSD {
    n8 latency;
    n8 pulseWidth;
    n4 pageSize;
    n2 releaseDuration;
  } bsd1, bsd2;

  struct DeviceEntry {
    u32 priority;
    PIDevice* device;
  };
  std::vector<DeviceEntry> devices;

  s32 busDevice = -1;
  PIDeviceTiming busTiming;

  //pi.cpp
  auto load(Node::Object) -> void;
  auto unload() -> void;
  auto power(bool reset) -> void;

  //dma.cpp
  struct DMA : RiBus::Client {
    enum class Phase : u8 { Idle, Filling, Posted, Settling };
    Phase phase = Phase::Idle;
    n1  toRdram;          //PI_WR_LEN: cart to RDRAM
    n1  firstBlock;
    n1  addressSelected;
    i32 length = 0;       //bytes still to fill (to RDRAM) or to read (to cart)
    u32 maxBlockSize = 0;
    u32 offset = 0;       //to cart: bytes already moved
    u32 address = 0;      //the block's RDRAM address
    u32 bytes = 0;        //the block's burst size
    i32 lastLen = 0;      //to RDRAM: the block's cart bytes, for PI_WR_LEN
    i32 misalign = 0;
    u8  block[128];

    auto buffer(const RiBus::Burst&) -> void* override;
    auto granted(const RiBus::Grant&) -> void override;
  } dma;

  auto pageSetup(u32 address) -> Clock;
  auto halfwordTime(u32 address) -> Clock;
  auto dmaStart(bool toRdram, Clock at) -> void;
  auto dmaFill(Clock at) -> void;
  auto dmaPostRead(Clock at) -> void;
  auto dmaStep() -> void;
  auto dmaLanded(Clock at) -> void;
  auto dmaFinished() -> void;

  //io.cpp
  auto ioRead(u32 address, Thread& thread) -> u32;
  auto ioWrite(u32 address, u32 data, Thread& thread) -> void;

  //bus.hpp
  auto attach(PIDevice& device, u32 priority) -> void;
  auto detach(PIDevice& device) -> void;
  auto bsdForAddress(u32 address) -> BSD&;
  auto busAddress(u32 address) -> void;
  auto busReadHalf() -> u16;
  auto busWriteHalf(u16 data) -> void;
  auto readWord(u32 address, Thread& thread) -> u32;
  auto writeWord(u32 address, u32 data, Thread& thread) -> void;
  auto writeFinished() -> void;
  auto writeForceFinish(Clock now) -> Clock;

  //serialization.cpp
  auto serialize(serializer&) -> void;
};

extern PI pi;
