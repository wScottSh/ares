//The RDP's DPC front end as a function of time (ADR 0001 Decision 3, plan T12).
//
//The register block, the command DMA's progress and the busy counters are
//pure transitions on a value type, so tools/n64-timing/tests/dpc-regs.cpp
//drives them without a timeline. RDP::run (timed.cpp) moves them through
//time: command fetch, one dispatch at a time, SYNC_FULL retire.
//
//This header stands alone on clock.hpp, behaviors.hpp and the nall integer
//types.

namespace RDPTimed {

using Timing::Clock;

inline auto divideRoundingUp(u64 n, u64 d) -> u64 { return (n + d - 1) / d; }

//DPC register index: address bits 4:2 (n64brew Reality_Display_Processor/Interface).
enum Reg : u32 { Start, End, Current, Status, ClockCounter, BufBusy, PipeBusy, TmemBusy };

namespace StatusBit {
  enum : u32 {
    Xbus       = 1 <<  0,
    Freeze     = 1 <<  1,
    Flush      = 1 <<  2,
    StartGclk  = 1 <<  3,
    TmemBusy   = 1 <<  4,
    PipeBusy   = 1 <<  5,
    CmdBusy    = 1 <<  6,
    CbufReady  = 1 <<  7,
    DmaBusy    = 1 <<  8,
    EndValid   = 1 <<  9,
    StartValid = 1 << 10,
  };
}

//A 24-bit DPC counter of RCP clocks. It changes state only on rclk edges, so
//a read between edges sees the count at the last edge.
struct Counter {
  Clock since;     //rclk edge of the last turn-on or clear
  s64   units = 0; //accumulated before `since`
  bool  on = false;

  static auto edge(Clock at) -> Clock { return Timing::nextRclkEdge(at); }
  static auto floorEdge(Clock at) -> Clock { return {at.units - at.units % Timing::UnitsPerRclk}; }

  auto set(bool value, Clock at) -> void {
    if(value == on) return;
    at = edge(at);
    if(on && at > since) units += (at - since).units;
    on = value;
    since = at;
  }
  auto clear(Clock at) -> void {
    units = 0;
    since = edge(at);
  }
  auto read(Clock at) const -> u32 {
    s64 total = units;
    auto now = floorEdge(at);
    if(on && now > since) total += (now - since).units;
    return (u32)(total / Timing::UnitsPerRclk) & 0xff'ffff;
  }
};

//The register block and the command DMA pointers (rsp-rdp-fifo.md rows 9-13).
struct Dpc {
  n24 start;       //START as last latched
  n24 end;         //the end of the transfer the DMA is running
  n24 current;     //the fetch pointer: advances as command words reach the FIFO
  n24 endNext;     //END written while a transfer was active, queued behind it
  n1  startValid;  //START written and not yet consumed by an END write
  n1  endValid;    //END_PENDING: endNext is queued
  n1  xbus, freeze, flush;
  n1  pipeBusy;    //from an END write until SYNC_FULL retires
  n1  startGclk;
  n1  crashed;     //the pipeline crashed; the RDP reports busy forever
  Clock clockOrigin;
  Counter cmd;     //BUFBUSY: the command FIFO is non-empty or a command executes
  Counter pipe;    //PIPEBUSY: PIPE_BUSY is set
  Counter tmem;    //TMEM: a TMEM load executes

  //The DMA has words left to fetch.
  auto dmaBusy() const -> bool { return current < end; }

  //What a DPC_END read returns: the last value written.
  auto endRegister() const -> u32 { return endValid ? (u32)endNext : (u32)end; }

  auto write(u32 reg, u32 value, Clock at) -> void {
    const u32 address = value & 0xff'fff8;
    switch(reg) {
    case Start:
      if(!startValid) start = address;
      startValid = 1;
      return;
    case End:
      if(!startValid) {
        end = address;
      } else if(!dmaBusy()) {
        current = start;
        end = address;
        startValid = 0;
      } else {
        endNext = address;
        endValid = 1;
      }
      if(!freeze && !crashed) busy(at);
      return;
    case Status:
      if(value & 1 <<  0) xbus = 0;
      if(value & 1 <<  1) xbus = 1;
      if(value & 1 <<  2) {
        freeze = 0;
        if(!crashed) busy(at);
      }
      if(value & 1 <<  3) freeze = 1;
      if(value & 1 <<  4) flush = 0;
      if(value & 1 <<  5) flush = 1;
      if(value & 1 <<  6) tmem.clear(at);
      if(value & 1 <<  7) pipe.clear(at);
      if(value & 1 <<  8) cmd.clear(at);
      if(value & 1 <<  9) clockOrigin = at;
      return;
    }
  }

  auto read(u32 reg, Clock at) const -> u32 {
    switch(reg) {
    case Start:   return start;
    case End:     return endRegister();
    case Current: return current;
    case Status:  return status();
    case ClockCounter: return (u32)((at - clockOrigin).units / Timing::UnitsPerRclk) & 0xff'ffff;
    case BufBusy:  return cmd.read(at);
    case PipeBusy: return pipe.read(at);
    case TmemBusy: return tmem.read(at);
    }
    return 0;
  }

  auto status() const -> u32 {
    u32 s = StatusBit::CbufReady;
    if(xbus)              s |= StatusBit::Xbus;
    if(freeze || crashed) s |= StatusBit::Freeze;
    if(flush)             s |= StatusBit::Flush;
    if(startGclk)         s |= StatusBit::StartGclk;
    if(tmem.on)           s |= StatusBit::TmemBusy;
    if(pipeBusy || crashed) s |= StatusBit::PipeBusy;
    if(cmd.on || crashed) s |= StatusBit::CmdBusy;
    if(dmaBusy())         s |= StatusBit::DmaBusy;
    if(endValid)          s |= StatusBit::EndValid;
    if(startValid)        s |= StatusBit::StartValid;
    return s;
  }

  //`bytes` of command words reached the FIFO. At the end of the transfer a
  //queued START/END pair takes over (n64brew; MiSTer RDP.vhd:595-605).
  auto fetched(u32 bytes) -> void {
    current = current + bytes;
    if(endValid && !dmaBusy()) {
      current = start;
      end = endNext;
      startValid = 0;
      endValid = 0;
    }
  }

  //SYNC_FULL retired: the pipeline is idle (n64-systemtest tests/rdp: the
  //status after SYNC_FULL is CBUF_READY alone).
  auto syncFullRetired(Clock at) -> void {
    pipeBusy = 0;
    startGclk = 0;
    pipe.set(false, at);
  }

private:
  auto busy(Clock at) -> void {
    pipeBusy = 1;
    startGclk = 1;
    pipe.set(true, at);
  }
};

//What one dispatched command asks of the pipeline (the engine's
//rdp_engine_work): its opcode, the cycle type it ran in, and for primitives
//the spans it walked.
struct Work {
  u32 command;
  u32 cycleType;   //0 1-cycle, 1 2-cycle, 2 copy, 3 fill
  u32 pixels;      //clipped span widths, summed
  u32 words;       //fill and copy: 64-bit words the spans cover
  u32 lines;       //spans
  u32 loadBytes;   //TMEM loads
};

struct Cost {
  Clock busy;      //command-processor occupancy
  bool  load;      //a TMEM load: the TMEM counter runs for `busy`
  bool  syncFull;  //raises the DP interrupt when it retires
};

//Compute clocks only: memory stalls are plan T13's. A primitive occupies the
//command processor for its whole span time; overlap with the next command
//(rdp-command-timing.md s.3.4) is plan T13/T15's.
inline auto cost(const Work& w) -> Cost {
  using namespace Timing::Behavior;
  switch(w.command) {
  case 0x26: return {RdpSyncLoad};
  case 0x27: return {RdpSyncPipe};
  case 0x28: return {RdpSyncTile};
  case 0x29: return {RdpSyncFull, false, true};
  case 0x30: case 0x33: case 0x34: {
    u64 clocks = divideRoundingUp(w.loadBytes, RdpTmemLoadRate);
    return {RdpSetter + Timing::rclk(clocks), true};
  }
  case 0x08: case 0x09: case 0x0a: case 0x0b: case 0x0c: case 0x0d: case 0x0e: case 0x0f:
  case 0x24: case 0x25: case 0x36: {
    u64 clocks = 0;
    const u64 slots = w.pixels + (u64)w.lines * RdpSpanDeadPixels;
    switch(w.cycleType) {
    case 0: clocks = slots / RdpSpan1cycle; break;
    case 1: clocks = slots * RdpSpan2cycle.denominator / RdpSpan2cycle.numerator; break;
    default: clocks = (u64)w.words * sizeof(u64) / RdpFillCopyRate; break;
    }
    return {RdpPrimitiveBase + Timing::rclk(clocks) + Clock{(s64)w.lines * RdpSpanLineGap.units}};
  }
  }
  return {RdpSetter};
}

//The command DMA's next request: a whole burst once the FIFO has room for
//one, else the rest of the transfer once it fits; 0 while it must wait.
inline auto fetchDwords(const Dpc& dpc, u32 fifoDwords) -> u32 {
  if(!dpc.dmaBusy()) return 0;
  const u32 remaining = (u32)(dpc.end - dpc.current) / sizeof(u64);
  const u32 burst = Timing::Behavior::RdpCmdFetchBurst / sizeof(u64);
  const u32 want = remaining < burst ? remaining : burst;
  const u32 room = Timing::Behavior::RdpCmdFifoDwords - fifoDwords;
  return want <= room ? want : 0;
}

//How long a command fetch of `dwords` takes from request to the words being
//in the FIFO. Until the RI arbiter (plan T6) takes DpCommand requests, an
//RDRAM fetch is one uncontended read burst: the NEC read-hit wire time,
//4 tc per octbyte, and the RDP's per-burst RI overhead. The X bus reads DMEM
//directly. The seam for T6/T13: replace this with an RI post whose grant
//lands the words.
inline auto fetchLatency(u32 dwords, bool xbus) -> Clock {
  using namespace Timing::Behavior;
  if(xbus) return Timing::rclk(divideRoundingUp(dwords * sizeof(u64), RdpXbusFetchRate));
  return RiReadHit + Clock{(s64)dwords * RiOctbyte.units} + RiOverheadRdp;
}

}
