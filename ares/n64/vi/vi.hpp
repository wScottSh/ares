//Video Interface

struct VI : Thread, Memory::RCP<VI> {
  Node::Object node;
  Node::Video::Screen screen;

  struct Debugger {
    //debugger.cpp
    auto load(Node::Object) -> void;
    auto io(bool mode, u32 address, u32 data) -> void;

    struct Tracer {
      Node::Debugger::Tracer::Notification io;
    } tracer;
  } debugger;

  //vi.cpp
  auto load(Node::Object) -> void;
  auto unload() -> void;
  auto step(u32 vclks) -> void;

  auto line() -> void;
  auto startFetch() -> void;
  auto fetchDue() -> void;
  auto refresh() -> void;
  auto power(bool reset) -> void;
  auto active() -> bool { return io.colorDepth != 0; }

  //io.cpp
  auto readWord(u32 address, Thread& thread) -> u32;
  auto writeWord(u32 address, u32 data, Thread& thread) -> void;

  //serialization.cpp
  auto serialize(serializer&) -> void;

  struct IO {
    n2  colorDepth;
    n1  gammaDither;
    n1  gamma;
    n1  divot;
    n1  serrate;  //interlace
    n2  antialias;
    n1  dedither;
    n32 reserved;
    n24 dramAddress;
    n12 width;
    n10 coincidence = 256;
    n8  hsyncWidth;
    n8  colorBurstWidth;
    n4  vsyncWidth;
    n10 colorBurstHsync;
    n10 halfLinesPerField;
    n12 quarterLineDuration;
    n5  leapPattern;
    n12 hsyncLeap[2];
    n10 hend;
    n10 hstart;
    n10 vend;
    n10 vstart;
    n10 colorBurstEnd;
    n10 colorBurstStart;
    n12 xscale;
    n12 xsubpixel;
    n12 yscale;
    n12 ysubpixel;

  //internal:
    n9  vcounter;
    n1  field;
    n3  leapCounter;
  } io;

  Timing::VclkAccumulator vclk;
  u32 inactiveCounter;

  //Scanout as an RI bus client (vi-fetch.md): from H_START of each active
  //output line, vi.lines-per-output-line framebuffer lines (n, n+1, n+2) are
  //read segment by segment in vi.burst pieces, spaced evenly to H_END, one
  //burst in flight. The line is composed from the bytes as the RI moved them,
  //so the image is RDRAM as the VI read it, tearing included.
  struct Fetch : RiBus::Client {
    static constexpr u32 Lines = Timing::Behavior::ViLinesPerOutputLine;
    static constexpr u32 LineBytes = 4095 * 4;  //widest VI_WIDTH at 32 bpp
    struct Slot {
      u32 address;
      u32 offset;  //into bytes: line k of the three at k * pitch
      u8  bytes;
    };

    auto start(u32 origin, u32 pitch) -> void;
    auto post(Clock at) -> void;
    auto dueAt(u32 slot) const -> Clock;
    auto buffer(const RiBus::Burst&) -> void* override;
    auto granted(const RiBus::Grant&) -> void override;

    //latched at the line's HSYNC
    Timing::VclkAccumulator hsync;
    u32 origin = 0;  //RDRAM address of framebuffer line n
    u32 pitch = 0;   //bytes per framebuffer line
    u32 line = 0;    //framebuffer line n
    u32 hstart = 0;
    u32 hend = 0;
    u32 output = 0;  //vcounter of the output line
    //progress
    u32  count = 0;  //slots this line
    u32  next = 0;   //first slot not yet posted
    bool inFlight = false;
    bool due = false;  //slot `next` came due while its predecessor was in flight

    //rebuilt from origin and pitch
    //a segment splits in two where it crosses a 2 KiB row
    Slot slots[Lines * 2 * ((LineBytes + Timing::Behavior::ViBurst - 1) / Timing::Behavior::ViBurst)];
    u8   bytes[Lines * LineBytes];
  } fetch;
  //The screen area the field covers, in screen rows (half-lines) and pixels.
  struct Window {
    s32 dy0, dy1, dx0, dx1;
    u32 hscanStart, vscanStart, hscanLen, vscanLen;
  };
  auto window() const -> Window;
  //Whether screen row dy belongs to this field.
  auto drawn(const Window&, s32 dy) const -> bool;
  auto compose() -> void;

//unserialized:
  bool refreshed;
  //the raw pixels each screen position last composed from, for the runner's
  //tearing count against RDRAM (n64-run vi_tear)
  u32 scanned[640 * 576];
  u32 scannedOrigin = 0;  //VI_ORIGIN at the field's first composed line

};

extern VI vi;
