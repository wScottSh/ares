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

  //timed.cpp: a timeline actor; command fetch, dispatch, the span pipeline
  //and its RDRAM traffic, SYNC_FULL retire
  auto readiness() const -> Timing::Readiness override;
  auto run(Clock limit) -> void override;
  auto kick(Clock at) -> void;
  auto step(Clock at) -> void;
  auto startFetch(Clock at) -> void;
  auto dispatch(Clock at) -> void;
  auto dispatchable() const -> bool;
  auto retire() -> void;
  auto land(Clock at) -> void;
  auto pipeline(Clock at) -> void;
  auto prefetch(Clock at) -> void;
  auto startSpan(Clock at) -> bool;
  auto beginChunk(Clock at) -> bool;
  auto endChunk(Clock at) -> void;
  auto writeBack(u32 image, u32 firstPixel, u32 endPixel, Clock at) -> void;
  auto startLoad(Clock at) -> void;
  auto wakeAt(Clock at) -> void;
  auto busy() const -> bool;

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

  //The X-bus command fetch in flight; its words land at `arrival`.
  struct Fetch {
    u32   dwords = 0;
    Clock arrival;
  } fetch;

  //The command processor: busy with one dispatch until `until`, or idle and
  //free to dispatch from `until` on. A SYNC_FULL also waits for every write-back.
  struct Executor {
    bool  busy = false;
    bool  load = false;
    bool  syncFull = false;
    Clock until;
  } executor;

  //The memory interface (ADR 0001 Decision 3, plan T13). Every byte the
  //renderer reads or writes moves in an RI burst: command words
  //(DpCommand), span snapshots and write-back runs (DpColor, DpDepth),
  //TMEM load sources (DpTexture), fill writes (DpFill).
  enum Image : u8 { Color, Depth, Texture, Command };
  static constexpr u32 SpanBytes = 4096 + 16;   //a 1024-pixel 32-bpp row, octbyte-aligned
  static constexpr u32 Slots = 4;               //spans between prefetch and their last write grant
  static constexpr u32 LoadBytes = 64 * 1024;   //TMEM load staging (rows of a load, octbyte-aligned)

  //One span row of one image as the RI delivered it and as the pipeline wrote it.
  struct Window {
    u32 lo = 0, hi = 0;
    u8  data[SpanBytes];
    u8  hidden[SpanBytes / 2];
    u8  written[SpanBytes];
  };

  struct Slot {
    rdp_span_info info;
    Window color, depth;
    u32   reads = 0;    //snapshot bursts not yet landed
    u32   writes = 0;   //write-back bursts not yet landed
    Clock ready;        //the last snapshot burst landed
    bool  shaded = false;
  };

  //One burst a port has yet to post or has in flight.
  struct Pending {
    u32 address;
    u8  bytes;
    u8  write;
    u8  slot;
    u8  image;
    u8  half;
  };

  //The RDP's memory interface toward the RI. It posts one burst at a time
  //and holds the RI request until the burst's data has moved plus the
  //RDP's per-burst overhead (rdp.mem-overhead-read/-write). A read's data
  //is usable rdp.span-read-latency after its last beat, and an image has
  //one read outstanding at a time. Bursts post in the order queued, so a
  //span's snapshot read and an earlier span's write-back keep their order
  //(SDK 12.2.3). The command DMA and fill writes have ports of their own.
  struct Port : RI::Client {
    Port(RDP* self, RiBus::Requester requester) : self(self), requester(requester) {}
    RDP* self;
    RiBus::Requester requester;
    std::deque<Pending> queue;  //not yet posted
    bool  posted = false;       //queue.front() is in the RI
    Clock freeAt;               //takes its next post from here
    struct Flight { Pending p; Clock landAt; };
    std::deque<Flight> flights; //granted, data not yet landed
    u8    words[128];           //DpCommand data, bus order

    auto buffer(const RiBus::Burst&) -> void* override { return words; }
    auto native(const RiBus::Burst&, Native&) -> bool override;
    auto granted(const RiBus::Grant&) -> void override;
    auto post(Clock at) -> void;
    auto next() const -> Clock;
    auto eligible() const -> s32;
    auto reset() -> void { queue.clear(); flights.clear(); posted = false; freeAt = {}; }
  };

  //A span-RAM half (span-ram.md rows 3-6): it fills along the stream and
  //writes back when full or at the end of a span; a TMEM load waits for the
  //Z halves' write-backs (it stages through them).
  struct Half {
    u32 outstanding = 0;
  };

  struct Stream {
    u32  position = 0;  //stream position of the next pixel (span-ram.md row 3)
    u32  halfStart = 0; //first pixel of the current span in the current half
    Half halves[2];
  };

  struct Pipe {
    Clock time;          //the pipeline takes its next chunk from here
    Clock wake = Clock::never();
    s32   current = -1;  //slot being shaded
    u32   pixel = 0;     //pixels of the current span done
    bool  chunk = false; //a chunk runs until `chunkEnd`
    Clock chunkEnd;
    u32   chunkPixels = 0;
    Stream color, depth;
    u32   head = 0, count = 0;   //slots in use, oldest first
    s32   prefetched = -1;       //slot holding the next unrun span
    u32   lastPrimitive = ~0u;
    Clock lastWrite;             //last write-back landing
    u32   writes = 0;            //write-back bursts not yet landed, every slot
  } pipe;

  struct Load {
    static constexpr u32 Ranges = 4096;
    bool  active = false;
    u32   reads = 0;
    Clock ready;
    u32   count = 0;
    rdp_memrange ranges[Ranges];
    rdp_memwin   windows[Ranges];
    u8    data[LoadBytes], hidden[LoadBytes / 2], written[LoadBytes];
  };

  Slot  slots[Slots];
  Load  tmemLoad;
  //Measurement only: RCP time the RDP was busy, and the part of it a pixel
  //chunk ran; the rest is the pipeline's GCLK off (waiting on memory or on
  //the command processor).
  struct Stat {
    u64   busy = 0, pipe = 0;
    Clock since;
    bool  on = false;
  } stat;

  Port  memory{this, RiBus::Requester::DpColor};
  Port  command{this, RiBus::Requester::DpCommand};
  Port  fillPort{this, RiBus::Requester::DpFill};

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
