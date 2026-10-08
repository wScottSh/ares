//The VR4300's external port: its 4-entry write (flush) buffer and the SysAD
//bus to the RCP, as one in-order queue (R4300i datasheet p.9: the flush
//buffer carries reads too, one read at a time; NEC VR4300 UM s.12.6.2).
//
//Every CPU access that leaves the caches goes through here, so three rules
//hold by construction (vr4300-wb.md):
//  - a read waits until every older buffered write has drained;
//  - a dirty D-miss reads its fill first and queues the victim after it
//    (NEC s.12.5.2-12.5.3);
//  - a posted register write takes effect when it drains, not when the
//    store executes.
//
//RDRAM traffic goes to the RI as CpuSysAD bursts, so it waits behind refresh
//and, once they post, every other client. The CPU-visible totals are hardware
//measurements; each fixed SysAD/MI path below is that total minus the modeled
//uncontended RI time, so the uncontended case reproduces the measurement and
//contention adds on top (ADR 0001 Decision 2).

//The wire time of an aligned `bytes` burst at row hit.
constexpr auto hitWire(RiBus::Direction direction, u32 bytes) -> Clock {
  return RiBus::wire(direction, RiBus::octbytes(0, bytes), RiBus::Row::Hit);
}

struct SysAD : Timing::Actor, RI::Client {
  //CPU side. Each call runs at cpu.clock (the load or store's execute time)
  //and leaves cpu.clock at the time the pipeline restarts.
  template<u32 Size> auto read(u32 address) -> u64;
  template<u32 Size> auto store(u32 address, u64 data) -> void;
  //Size is DCache or ICache. False when the line is not in RDRAM (the CPU froze).
  template<u32 Size> auto fill(u32 address, u32* words) -> bool;
  //A line leaving a cache: queued behind every older write, drained later.
  template<u32 Size> auto writeback(u32 address, const u32* words) -> void;
  //The debugger's view of RDRAM: `value` with every queued write to it applied.
  template<u32 Size> auto forward(u32 address, u64 value) const -> u64;

  auto power() -> void;
  auto readiness() const -> Timing::Readiness override;
  auto run(Clock limit) -> void override;
  auto buffer(const RiBus::Burst&) -> void* override;
  auto granted(const RiBus::Grant&) -> void override;
  auto serialize(serializer&) -> void;

  //The RI decides on rclk edges and the CPU restarts on pclk edges. From a
  //pclk-aligned request the wait for the deciding edge averages this many
  //units over the three pclk phases of an rclk pair.
  static constexpr Clock MeanEdgeWait = {(
      (Timing::nextRclkEdge(Clock{ 0} + Timing::Behavior::RiRequestLatency).units -  0) +
      (Timing::nextRclkEdge(Clock{ 8} + Timing::Behavior::RiRequestLatency).units -  8) +
      (Timing::nextRclkEdge(Clock{16} + Timing::Behavior::RiRequestLatency).units - 16)) / 3};

  //A measured total counts the load's own issue cycle, which is a D-cache hit's whole cost.
  static constexpr Clock Issue = Timing::Behavior::CpuDcacheHit;

  //Last data beat to pipeline restart: the measured total less the modeled RI time for
  //the measurement's row state and the mean edge wait (ADR 0001 Decision 2).
  static constexpr Clock ReadPath  = Timing::Behavior::CpuUncachedReadTotal - Issue - MeanEdgeWait - hitWire(RiBus::Direction::Read, 8);
  //nemu64-test's miss loop evicts with a line 8 KiB away, a clean row miss in the same bank.
  static constexpr Clock DfillPath = Timing::Behavior::CpuDfillTotal - Issue - MeanEdgeWait
      - RiBus::wire(RiBus::Direction::Read, 2, RiBus::Row::CleanMiss);
  //cpu.ifill-stall takes M from the D-fill, so it holds at the D-fill's clean row miss.
  static constexpr Clock IfillPath = Timing::Behavior::CpuIfillStall - MeanEdgeWait
      - RiBus::wire(RiBus::Direction::Read, 4, RiBus::Row::CleanMiss);
  //Last data beat to EOK, from the steady-state drain period per entry.
  static constexpr Clock WritePath = Timing::Behavior::SysadRdramWritePeriod
      - Timing::Behavior::RiRequestLatency - hitWire(RiBus::Direction::Write, 8);
  static constexpr Clock BlockWritePath = Timing::Behavior::SysadRdramBlockWritePeriod
      - Timing::Behavior::RiRequestLatency - hitWire(RiBus::Direction::Write, 16);

  struct Entry {
    enum class Phase : u8 { Ready, Posted, Applying, Done };
    Phase phase;
    u8    size;      //Byte..Dual for a store, DCache or ICache for a line
    u8    slots;     //write-buffer entries it occupies (R4300i datasheet p.9)
    u32   address;
    Clock enqueued;
    Clock done;      //EOK: the entry's slot frees and the next transaction may start
    u64   value;
    u32   words[8];
  };

  static constexpr u32 ReadTag = 0xff;

private:
  template<typename F> auto await(F&& done) -> void;
  auto resume(Clock t) -> void;
  auto retire(Clock now) -> void;
  auto reserve(u32 slots) -> void;
  auto drain() -> void;
  auto enqueue(const Entry&) -> void;
  auto update() -> void;
  auto pending() -> Entry*;
  auto apply(Entry&) -> void;
  template<u32 Size> auto readRdram(u32 address, void* data, Clock path) -> void;

  Entry entries[4];
  u8    head = 0;
  u8    count = 0;
  u8    slotsUsed = 0;
  Clock free;  //the SysAD bus is idle from here: the last transaction's end

  //the one read in flight (NEC s.12.6.2)
  bool  readGranted = false;
  Clock readEnd;
  union { u64 value; u32 words[8]; } readData;

  Timing::Readiness cached;
  Thread drainer;  //the clock a drained register write runs at
};

extern SysAD sysad;
