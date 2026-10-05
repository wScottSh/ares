//The RDRAM channel as seen through the RI: one in-order master, atomic bursts
//of 8-128 B, eight banks with one open 2 KiB row each, refresh per HSYNC.
//(rdram-bus-arbitration.md B1-B12.)
//
//Every RDRAM byte that any hardware client reads or writes is moved by the RI
//itself, at grant time, in grant order, between rdram.ram and the buffer the
//client named in its Burst. Rdram::ram's data accessors are private with a
//friend list (RI, Debugger, Loader; T6-T8 shrink the list to that), so a device
//that reads RDRAM directly fails to compile. RDRAM content and RDRAM timing
//therefore cannot disagree: a CPU uncached read sees exactly the RDP writes
//granted before it.

namespace ares::Nintendo64::RI {

using Timing::Clock;

//One row per hardware client of the RI. The table below is the only place a
//requester's arbitration and latency properties live; every value comes from
//Timing::Behavior (behaviors.tsv).
enum class Requester : u8 {
  Refresh,    //RI-internal, triggered by VI HSYNC
  ViFetch,
  CpuSysAD,   //uncached reads/writes, D/I fills, D writebacks (in SysAD order)
  SpDma,
  DpCommand,  //RDP command DMA from RDRAM
  DpColor,    //span prefetch / write-back, color image
  DpDepth,    //span prefetch / write-back, Z image
  DpTexture,  //TMEM loads
  DpFill,     //fill-mode direct writes
  PiDma,
  SiDma,
  AiDma,
  Count,
};

struct RequesterSpec {
  u8    rank;             //lower wins; equal ranks fall back to arrival time
  Clock requestLatency;   //client posts -> request visible to the RI (>= 1 unit)
  Clock responseLatency;  //last data beat on the wire -> client has the data
  u8    maxOutstanding;
};

//constexpr, built from Timing::Behavior::RiRank*, Ri*Latency, ... only.
extern const RequesterSpec requesterSpecs[(u32)Requester::Count];

enum class Direction : u8 { Read, Write };

//A burst never crosses a 2 KiB row or exceeds 128 B; post() asserts it, and
//split() is the only way clients build bursts from larger ranges. `data` and
//`hidden` name the client's bytes; the RI copies at grant (read: rdram ->
//data; write: data -> rdram). `hidden` is the 9th-bit plane, DP and VI only.
//`trimHead`/`trimTail` mask bytes of the first and last octbyte on writes
//(Wseq Adr[2:0] and Count[2:0]; rdp-write-granularity.md).
struct Burst {
  u32       address;    //physical, 8-byte aligned except PI/SI first block
  u8        bytes;      //1..128
  Direction direction;
  Requester requester;
  u8*       data;
  u8*       hidden;     //nullptr for clients without 9th bits
  u8        trimHead = 0, trimTail = 0;
  u16       tag;        //client-private (span index, DMA row, ...)
};

//emit(address, bytes, offsetFromStart) for each legal burst of the range.
auto split(u32 address, u32 bytes, u32 maxBytes, auto&& emit) -> void;

//What a client learns when its burst wins. The bytes have already moved.
struct Grant {
  Burst burst;
  Clock start;      //rclk edge the RI issued the request packet
  Clock dataStart;  //first data beat (after hit latency or row-miss retry)
  Clock dataEnd;    //last data beat
  Clock complete;   //dataEnd + responseLatency: the client may use the data
  bool  rowMiss;
};

//Clients learn of the grant here; they may post follow-up bursts in it.
struct Client {
  virtual auto granted(const Grant&) -> void = 0;
};

struct Ticket {
  u32 sequence;
  auto operator<=>(const Ticket&) const = default;
};

struct BankState {
  n9 row;
  n1 valid;
  n1 dirty;
};

//Per requester, for the bench readout (emux), the debugger and the research
//bands (VI 6.5-9% of channel time, refresh 1.3-1.4%, vi-fetch.md).
struct Counters {
  u64 bursts, bytesRead, bytesWritten, rowMisses;
  Clock busy;   //channel time this requester held
  Clock wait;   //arrival -> start, summed
};

struct Ri : Timing::Actor {
  auto attach(Requester, Client&) -> void;

  //`at` is the client's current time; the request reaches the arbiter at
  //at + requestLatency. Posting in the future is allowed (DMA engines post
  //the next row at the previous grant's completion).
  auto post(const Burst&, Clock at) -> Ticket;
  auto complete(Ticket) const -> maybe<Clock>;

  //The earliest data-landing time any still-pending burst of `requester`
  //could have. The RSP uses it as its horizon so DMEM reads never pass an
  //SP DMA write that has not been decided (rsp/actor.hpp).
  auto earliestLanding(Requester) const -> Clock;

  //Timing::Actor. readiness() is Runnable at the next decision time when any
  //burst is pending, else Parked. step() makes exactly one decision.
  //
  //  d = nextRclkEdge(max(channelFree, min arrival of pending))
  //  candidates = pending with arrival <= d
  //  w = argmin over candidates of (spec.rank, arrival, requester, sequence)
  //  b = banks[bankOf(w.address)]
  //  hit = b.valid && b.row == rowOf(w.address)
  //  retry = hit ? 0 : (b.dirty ? RiRetryDirty : RiRetryClean)
  //  access = (w.direction == Read ? RiReadHit : RiWriteHit) + retry
  //  wire = access + octbytes(w) * RiOctbyte
  //  channelFree = d + wire + overhead(direction) + postGap(direction)
  //  b = {row, valid: 1, dirty: hit ? b.dirty | write : write}
  //  move bytes: Read  -> copy rdram[address..+bytes] (and hidden) into w.data
  //              Write -> copy w.data into rdram, honoring trimHead/trimTail
  //  counters[w.requester] += ...
  //  client(w).granted({w, d, d + access, d + wire, d + wire + responseLatency, !hit})
  //
  //A Refresh request occupies RiRefreshDirty if any bank is dirty, else
  //RiRefreshClean, then clears every dirty bit and leaves rows open
  //(NEC s.8.2.2, B12).
  auto readiness() const -> Timing::Readiness override;
  auto step(Clock limit) -> void override;

  //RI_REFRESH, RI_LATENCY etc. stay functional registers in ri/io.cpp; the
  //arbiter reads RI_REFRESH.En only. RI_BANK_STATUS reads `banks`.
  auto bankStatus() const -> const BankState*;
  auto counters() const -> const Counters*;
  auto serialize(serializer&) -> void;

private:
  struct Pending {
    Burst  burst;
    Clock  arrival;
    Ticket ticket;
  };
  static constexpr u32 MaxPending = 32;
  Pending   pending[MaxPending];
  u32       pendingCount = 0;
  BankState banks[8];
  Clock     channelFree;
  u32       nextSequence = 0;
  Client*   clients[(u32)Requester::Count] = {};
  Counters  counts[(u32)Requester::Count] = {};
  //completed tickets awaited by the CPU: at most one at a time (one read
  //pending on SysAD, NEC s.12.6.2)
  maybe<Clock> cpuCompletion;
};

extern Ri ri;

}

//rdram/rdram.hpp (the change this design makes there):
//
//  struct RDRAM {
//    ...
//  private:
//    Memory::Writable ram;   //data accessors reachable only by the friends below
//    friend struct RI::Ri;
//    friend struct Debugger;
//    friend struct Loader;   //power-on image, save states
//  };
//
//A device including rdram.hpp and calling rdram.ram.read() fails to compile.
//tools/n64-timing/tests/rdram-private.cpp is a negative compile test.
