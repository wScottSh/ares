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

//What one command costs the command processor. A primitive costs its setup;
//its spans run in the pixel pipeline (spanClocks), where memory stalls them.
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
  case 0x24: case 0x25: case 0x36:
    return {RdpPrimitiveBase};
  }
  return {RdpSetter};
}

//Pipeline clocks for `pixels` of a 1- or 2-cycle span (SDK Table 12-1), and
//the tail every span adds after its last pixel: the dead slots at the same
//rate, then the line gap (rdp.span-dead-pixels, rdp.span-line-gap).
inline auto pixelClocks(u32 cycleType, u64 pixels) -> Clock {
  using namespace Timing::Behavior;
  if(cycleType == 1) return Timing::rclk(pixels * RdpSpan2cycle.denominator / RdpSpan2cycle.numerator);
  return Timing::rclk(pixels / RdpSpan1cycle);
}
inline auto spanTail(u32 cycleType) -> Clock {
  using namespace Timing::Behavior;
  return pixelClocks(cycleType, RdpSpanDeadPixels) + RdpSpanLineGap;
}
//A fill or copy span moves its 64-bit words at the fill/copy rate (SDK 12.1.4/12.1.5).
inline auto wordClocks(u64 words) -> Clock {
  using namespace Timing::Behavior;
  return Timing::rclk(words * sizeof(u64) / RdpFillCopyRate) + RdpSpanLineGap;
}

//The command DMA's next request: up to one burst, no more than the FIFO has
//room for. Waiting for room for a whole burst would deadlock: a FIFO of 30
//dwords can hold a partial 22-dword triangle with less than a burst free.
inline auto fetchDwords(const Dpc& dpc, u32 fifoDwords) -> u32 {
  if(!dpc.dmaBusy() || fifoDwords >= Timing::Behavior::RdpCmdFifoDwords) return 0;
  u32 dwords = (u32)(dpc.end - dpc.current) / sizeof(u64);
  dwords = min(dwords, (u32)(Timing::Behavior::RdpCmdFetchBurst / sizeof(u64)));
  return min(dwords, (u32)(Timing::Behavior::RdpCmdFifoDwords - fifoDwords));
}

//An X-bus command fetch reads DMEM over the RSP-RDP bus, with no RI traffic.
inline auto xbusLatency(u32 dwords) -> Clock {
  return Timing::rclk(divideRoundingUp(dwords * sizeof(u64), Timing::Behavior::RdpXbusFetchRate));
}


//The RDP's noise (rdp-noise.md, from Thar0/RDP-Noise console dumps): three
//Fibonacci LFSRs, a(x) = x^29 + x^2 + 1, b(x) = x^28 + x^3 + 1 and
//c(x) = x^27 + x^5 + x^2 + x + 1. A register holds its next `degree` outputs,
//the current one in its top bit, and shifts in the parity of its taps once
//per RDP clock, stalls included (rdp.noise-step). All three are all ones at
//power-on, c one step ahead (rdp.noise-reset). The state is a function of the
//clock count alone, so a gap is a GF(2) matrix power, not a loop.
struct NoiseLfsr {
  struct Registers { u32 a, b, c; };

  struct Lfsr {
    u32 degree, taps;
    u32 power[64][32];  //power[k][j]: bit j's image after 2^k steps

    Lfsr(u32 degree, u32 taps) : degree(degree), taps(taps) {
      for(u32 j = 0; j < degree; j++) power[0][j] = shift(1u << j);
      for(u32 k = 1; k < 64; k++)
        for(u32 j = 0; j < degree; j++) power[k][j] = apply(power[k - 1], power[k - 1][j]);
    }
    auto ones() const -> u32 { return (1u << degree) - 1; }
    auto shift(u32 r) const -> u32 { return (r << 1 | (u32)__builtin_parity(r & taps)) & ones(); }
    auto apply(const u32* m, u32 r) const -> u32 {
      u32 o = 0;
      for(u32 j = 0; r; j++, r >>= 1) if(r & 1) o ^= m[j];
      return o;
    }
    auto advance(u32 r, u64 steps) const -> u32 {
      for(u32 k = 0; steps; k++, steps >>= 1) if(steps & 1) r = apply(power[k], r);
      return r;
    }
    auto output(u32 r) const -> u32 { return r >> (degree - 1) & 1; }
  };

  //Taps in register order: bit i is the output i + 1 steps back.
  static auto a() -> const Lfsr& { static const Lfsr l{29, 1u << 1 | 1u << 28}; return l; }
  static auto b() -> const Lfsr& { static const Lfsr l{28, 1u << 2 | 1u << 27}; return l; }
  static auto c() -> const Lfsr& { static const Lfsr l{27, 1u << 0 | 1u << 1 | 1u << 4 | 1u << 26}; return l; }

  static auto jump(u64 rdpClock) -> Registers {
    return {a().advance(a().ones(), rdpClock), b().advance(b().ones(), rdpClock), c().advance(c().ones(), rdpClock + 1)};
  }

  //The registers at an RDP clock counted from power-on. Pixels ask in
  //clock order, so a short gap steps; anything else jumps from reset.
  auto at(u64 rdpClock) -> Registers {
    if(rdpClock < clock || rdpClock - clock > 64) {
      registers = jump(rdpClock);
      clock = rdpClock;
    }
    for(; clock < rdpClock; clock++) registers = {a().shift(registers.a), b().shift(registers.b), c().shift(registers.c)};
    return registers;
  }

  //The combiner's NOISE bits a, b, c at that clock (combiner NOISE = abc100000).
  static auto outputs(Registers r) -> u32 {
    return a().output(r.a) << 2 | b().output(r.b) << 1 | c().output(r.c);
  }

  Registers registers = jump(0);
  u64 clock = 0;
};

}
