//The RDRAM channel as the RI drives it: one in-order master, atomic bursts of
//1-16 octbytes, eight banks with one open 2 KiB row each, and a refresh per
//VI HSYNC (rdram-bus-arbitration.md B1-B12, ADR 0001 Decision 2).
//
//This is the pure timing half of the RI: who wins the channel, when, and what
//it costs on the wire. It moves no bytes and knows no device, so the host unit
//test (tools/n64-timing/tests/ri.cpp) runs it without the core. ri/bus.cpp
//wraps it as the timeline's Bus actor and moves the bytes at each grant.
//
//Stands alone on clock.hpp, behaviors.hpp and the nall integer types.

namespace RiBus {

using Timing::Clock;

//One row per hardware client of the RI. Declaration order is the last
//arbitration tie-break (ri.arbitration).
enum class Requester : u8 {
  Refresh,    //RI-internal, posted at each VI HSYNC
  ViFetch,
  CpuSysAD,   //uncached reads and writes, D/I fills, D writebacks, in SysAD order
  SpDma,
  DpCommand,
  DpColor,
  DpDepth,
  DpTexture,
  DpFill,
  PiDma,
  SiDma,
  AiDma,
  Count,
};

enum class Direction : u8 { Read, Write };

//A burst never crosses a 2 KiB row and never exceeds 128 B. `tag` is the
//client's own: the client hands the RI its buffer for that tag at grant time,
//so a pending burst holds no host pointer and survives a save state.
struct Burst {
  u32       address;
  u8        bytes;      //1..128; 0 for Refresh
  Direction direction;
  Requester requester;
  u16       tag;
};

//What a client learns when its burst wins. The bytes have already moved.
struct Grant {
  Burst burst;
  Clock start;      //rclk edge the RI sent the request packet
  Clock dataStart;  //first data beat, after the hit latency or the row-miss retry
  Clock dataEnd;    //last data beat
  bool  rowMiss;
};

//A hardware client of the RI. ri/bus.cpp calls it at each grant; the channel
//model here never does.
struct Client {
  //The buffer for `burst`, asked for at grant time. Reads fill it, writes drain
  //it. CPU SysAD bursts use the VR4300 word layout; a DMA burst is `bytes`
  //bytes in bus order (byte i is RDRAM address + i).
  virtual auto buffer(const Burst&) -> void* = 0;
  //The bytes have moved. A client may post its next burst from here.
  virtual auto granted(const Grant&) -> void = 0;
};

//Bytes in the first burst of a transfer of `bytes` at `address`: at most
//ri.max-burst, and never across a 2 KiB row (B2, B6).
constexpr auto split(u32 address, u32 bytes) -> u32 {
  u32 row = 0x800 - (address & 0x7ff);
  u32 n = bytes < row ? bytes : row;
  return n < (u32)Timing::Behavior::RiMaxBurst ? n : (u32)Timing::Behavior::RiMaxBurst;
}

struct Bank {
  u16  row;
  bool valid;
  bool dirty;
};

//Per requester, for the bench readout, the debugger and the research bands
//(VI 6.5-9% of channel time, refresh 1.3-1.4%; vi-fetch.md).
struct Counters {
  u64   bursts;
  u64   bytesRead;
  u64   bytesWritten;
  u64   rowMisses;
  Clock busy;  //channel time this requester held
  Clock wait;  //arrival to grant, summed
};

constexpr auto rank(Requester r) -> s64 {
  if(r == Requester::Refresh) return Timing::Behavior::RiRankRefresh;
  if(r == Requester::ViFetch) return Timing::Behavior::RiRankVi;
  return Timing::Behavior::RiRankOther;
}

//ri.bank-of, ri.row-of: 8 banks of 1 MiB, rows of 2 KiB.
constexpr auto bankOf(u32 address) -> u32 { return address >> 20 & 7; }
constexpr auto rowOf (u32 address) -> u32 { return address >> 11 & 511; }

//Octbytes on the wire: the RI computes Count from the length and Adr[2:0] (B2).
constexpr auto octbytes(u32 address, u32 bytes) -> u32 { return ((address & 7) + bytes + 7) >> 3; }

enum class Row : u8 { Hit, CleanMiss, DirtyMiss };

//NEC uPD488170L, request start to last data beat (B8): hit latency, then the
//retry wait on a row miss, then 4 tc per octbyte.
constexpr auto wire(Direction direction, u32 octs, Row row) -> Clock {
  Clock access = direction == Direction::Read ? Timing::Behavior::RiReadHit : Timing::Behavior::RiWriteHit;
  if(row == Row::CleanMiss) access += Timing::Behavior::RiRetryClean;
  if(row == Row::DirtyMiss) access += Timing::Behavior::RiRetryDirty;
  return {access.units + octs * Timing::Behavior::RiOctbyte.units};
}

//Channel time a burst holds beyond its wire time before the next request
//packet: the per-direction RI overhead fitted from SP DMA throughput, then the
//NEC post-transaction gap.
constexpr auto trailer(Requester requester, Direction direction) -> Clock {
  bool dp = requester >= Requester::DpCommand && requester <= Requester::DpFill;
  if(direction == Direction::Read)
    return (dp ? Timing::Behavior::RiOverheadRdp : Timing::Behavior::RiOverheadRead) + Timing::Behavior::RiPostReadGap;
  return (dp ? Timing::Behavior::RiOverheadRdp : Timing::Behavior::RiOverheadWrite) + Timing::Behavior::RiPostWriteGap;
}

struct Channel {
  //every client keeps at most one burst in flight (refresh, SysAD, each DMA engine)
  static constexpr u32 Capacity = 16;

  struct Pending {
    Burst burst;
    Clock arrival;
    u32   sequence;
  };

  auto reset() -> void {
    count = 0;
    for(auto& p : pending) p = {};
    for(auto& n : sequences) n = 0;
    free = {};
    refreshEnd = {};
    for(auto& bank : banks) bank = {};
    for(auto& c : counters) c = {};
    cachedNext = Clock::never();
  }

  //`at` is the poster's own time; the request reaches the arbiter one request
  //latency later, so a decision never races an equal-time post.
  auto post(const Burst& burst, Clock at) -> void {
    if(count == Capacity) abort();
    Clock arrival = at + Timing::Behavior::RiRequestLatency;
    pending[count++] = {burst, arrival, sequences[(u32)burst.requester]++};
    Clock d = Timing::nextRclkEdge(arrival > free ? arrival : free);
    if(d < cachedNext) cachedNext = d;
  }

  //The rclk edge of the next decision, or never when nothing is pending.
  auto next() const -> Clock { return cachedNext; }

  auto empty() const -> bool { return count == 0; }

  auto pendingFor(Requester r) const -> bool {
    for(u32 i = 0; i < count; i++) if(pending[i].burst.requester == r) return true;
    return false;
  }

  //Makes the decision at next(): picks the winner among the arrived requests
  //by (rank, arrival, requester, sequence), charges its wire time for the
  //bank's row state, and updates the bank.
  auto decide() -> Grant {
    const Clock d = cachedNext;
    u32 w = count;
    for(u32 i = 0; i < count; i++) {
      if(pending[i].arrival > d) continue;
      if(w == count || before(pending[i], pending[w])) w = i;
    }
    //removing in place keeps the array a pure function of the live requests,
    //so a save state does not depend on the order the host posted them in
    const Pending p = pending[w];
    for(u32 i = w + 1; i < count; i++) pending[i - 1] = pending[i];
    pending[--count] = {};

    const Burst& b = p.burst;
    Grant g{b, d, d, d, false};
    auto& c = counters[(u32)b.requester];
    if(b.requester == Requester::Refresh) {
      //a broadcast SetRR holds the whole channel and restores each dirty open row (NEC s.8.2.2, B12)
      bool dirty = false;
      for(auto& bank : banks) dirty |= bank.dirty, bank.dirty = false;
      g.dataEnd = d + (dirty ? Timing::Behavior::RiRefreshDirty : Timing::Behavior::RiRefreshClean);
      free = g.dataEnd;
      refreshEnd = g.dataEnd;
    } else {
      auto& bank = banks[bankOf(b.address)];
      const u16 row = rowOf(b.address);
      const bool write = b.direction == Direction::Write;
      Row state = Row::Hit;
      if(!bank.valid || bank.row != row) state = bank.valid && bank.dirty ? Row::DirtyMiss : Row::CleanMiss;
      const u32 octs = octbytes(b.address, b.bytes);
      g.dataEnd   = d + wire(b.direction, octs, state);
      g.dataStart = g.dataEnd - Clock{octs * Timing::Behavior::RiOctbyte.units};
      g.rowMiss   = state != Row::Hit;
      bank.dirty  = state == Row::Hit ? bank.dirty || write : write;
      bank.valid  = true;
      bank.row    = row;
      free = g.dataEnd + trailer(b.requester, b.direction);
      if(write) c.bytesWritten += b.bytes; else c.bytesRead += b.bytes;
      c.rowMisses += g.rowMiss;
    }
    c.bursts++;
    c.busy += free - d;
    c.wait += d - p.arrival;
    recompute();
    return g;
  }

  template<typename S> auto serialize(S& s) -> void {
    if(s.writing()) canonicalize();
    s(count);
    for(auto& p : pending) {
      s(p.burst.address);
      s(p.burst.bytes);
      s((u8&)p.burst.direction);
      s((u8&)p.burst.requester);
      s(p.burst.tag);
      s(p.arrival.units);
      s(p.sequence);
    }
    for(auto& bank : banks) {
      s(bank.row);
      s(bank.valid);
      s(bank.dirty);
    }
    s(free.units);
    s(refreshEnd.units);
    for(auto& n : sequences) s(n);
    for(auto& c : counters) {
      s(c.bursts);
      s(c.bytesRead);
      s(c.bytesWritten);
      s(c.rowMisses);
      s(c.busy.units);
      s(c.wait.units);
    }
    recompute();
  }

  Pending  pending[Capacity] = {};
  u32      count = 0;
  Bank     banks[8] = {};
  Clock    free;  //the channel takes its next request packet from here
  Clock    refreshEnd;  //the last granted refresh releases the channel here
  u32      sequences[(u32)Requester::Count] = {};  //per requester: its posts arrive in its own order
  Counters counters[(u32)Requester::Count] = {};

private:
  static auto before(const Pending& a, const Pending& b) -> bool {
    s64 ra = rank(a.burst.requester), rb = rank(b.burst.requester);
    if(ra != rb) return ra < rb;
    if(a.arrival != b.arrival) return a.arrival < b.arrival;
    if(a.burst.requester != b.burst.requester) return a.burst.requester < b.burst.requester;
    return a.sequence < b.sequence;
  }

  //Live requests in (arrival, requester, sequence) order: the order two
  //requesters' posts reached the host never shows in the state.
  auto canonicalize() -> void {
    for(u32 i = 1; i < count; i++) {
      Pending p = pending[i];
      u32 j = i;
      for(; j > 0 && later(pending[j - 1], p); j--) pending[j] = pending[j - 1];
      pending[j] = p;
    }
  }

  static auto later(const Pending& a, const Pending& b) -> bool {
    if(a.arrival != b.arrival) return a.arrival > b.arrival;
    if(a.burst.requester != b.burst.requester) return a.burst.requester > b.burst.requester;
    return a.sequence > b.sequence;
  }

  auto recompute() -> void {
    if(!count) { cachedNext = Clock::never(); return; }
    Clock first = pending[0].arrival;
    for(u32 i = 1; i < count; i++) if(pending[i].arrival < first) first = pending[i].arrival;
    cachedNext = Timing::nextRclkEdge(first > free ? first : free);
  }

  Clock cachedNext = Clock::never();
};

}
