#include <n64/n64.hpp>
#include <nall/gdb/server.hpp>

namespace ares::Nintendo64 {

CPU cpu;
#include "context.cpp"
#include "sysad.cpp"
#include "dcache.cpp"
#include "tlb.cpp"
#include "memory.cpp"
#include "exceptions.cpp"
#include "algorithms.cpp"
#include "interpreter.cpp"
#include "decoder.cpp"
#include "interpreter-ipu.cpp"
#include "interpreter-scc.cpp"
#include "interpreter-fpu.cpp"
#include "interpreter-cop2.cpp"
#include "pipeline.cpp"
#include "debugger.cpp"
#include "serialization.cpp"
#include "disassembler.cpp"
#include "emux.cpp"

auto CPU::load(Node::Object parent) -> void {
  node = parent->append<Node::Object>("CPU");
  debugger.load(node);
}

auto CPU::unload() -> void {
  debugger.unload();
  node.reset();
}

auto CPU::main() -> void {
  while(GDB::server.reportPC(ipu.pc & 0xFFFFFFFF)) {
    //every other actor is past this instruction's start before it samples interrupts or executes
    timeline.catchUp(Thread::clock, Timing::ActorId::CPU);
    if(vi.refreshed) break;
    instruction();
  }

  flushCount();
  vi.refreshed = false;
  cancelEvent(EventKind::GDB_Poll);
  if(GDB::server.hasClient()) {
    scheduleAfter(EventKind::GDB_Poll, Clock{Timing::UnitsPerSecond / 60 / 240});
  }
}

auto CPU::gdbPoll() -> void {
  if(GDB::server.hasClient()) {
    GDB::server.updateLoop();
    scheduleAfter(EventKind::GDB_Poll, Clock{Timing::UnitsPerSecond / 60 / 240});
  }
}

auto CPU::stepCount(u64 clocks) -> void {
  if(!clocks) return;
  scc.count += clocks;
  profile.cpuCycles += clocks;
  if(scc.status.exceptionLevel) profile.cpuCyclesExc += clocks;
}

auto CPU::flushCount() -> void {
  auto clocks = pendingCount();
  countClock += pclk(clocks);
  stepCount(clocks);
}

//COUNT reaches COMPARE at one exact time, so the match is one timeline event
//instead of a check per sync. Rescheduled by every write to COUNT or COMPARE
//and by the match itself (the next match is one full COUNT wrap later).
auto CPU::scheduleCompare() -> void {
  cancelEvent(EventKind::CPU_Compare);
  u64 remaining = (u64)(scc.compare - scc.count) & CountMask;
  if(!remaining) remaining = CountMask + 1;
  timeline.schedule({countClock + pclk(remaining), (u32)EventKind::CPU_Compare});
}

auto CPU::compareMatch() -> void {
  flushCount();
  setInterruptPending(Interrupt::Timer, 1);
  scheduleCompare();
}

auto CPU::setInterruptPending(u32 bit, bool value) -> void {
  scc.cause.interruptPending.bit(bit) = value;
}


auto CPU::instruction() -> void {
  if(auto interrupts = scc.cause.interruptPending & scc.status.interruptMask) {
    if(scc.status.interruptEnable && !scc.status.exceptionLevel && !scc.status.errorLevel) {
      debugger.interrupt(scc.cause.interruptPending);
      step(pclk(1));
      exception.interrupt();
      return;
    }
  }

  if (scc.nmiPending) {
    debugger.nmi();
    step(pclk(1));
    exception.nmi();
    return;
  }
  if (scc.sysadFrozen) {
    step(pclk(1));
    return;
  }

  auto access = devirtualize<Read, Word>(ipu.pc);
  if(!access) return;

  auto data = fetch(access);
  if (!data) return;
  instructionIndex++;
  pipeline.begin();
  auto issued = pipeline.issue(*data);
  instructionPrologue(ipu.pc, *data);
  decoderEXECUTE(*data);
  instructionEpilogue();
  pipeline.retire(issued);
  pipeline.end();
}

auto CPU::instructionPrologue(u64 address, u32 instruction) -> void {
  debugger.instruction(address, instruction);
}

auto CPU::instructionEpilogue() -> void {
  ipu.r[0].u64 = 0;
}

auto CPU::power(bool reset) -> void {
  Thread::reset();
  countClock = {};

  context.endian = Context::Endian::Big;
  context.mode = Context::Mode::Kernel;
  context.bits = 64;
  for(auto& segment : context.segment) segment = Context::Segment::Unused;
  icache.power(reset);
  dcache.power(reset);
  for(auto& entry : tlb.entry) entry = {}, entry.synchronize();
  tlb.physicalAddress = 0;
  for(auto& r : ipu.r) r.u64 = 0;
  ipu.lo.u64 = 0;
  ipu.hi.u64 = 0;
  ipu.r[29].u64 = 0xffff'ffff'a400'1ff0ull;  //stack pointer
  pipeline.power();
  pipeline.setPc(0xffff'ffff'bfc0'0000ull);
  scc = {};
  scc.wired.randomEpoch = instructionIndex;
  for(auto& r : fpu.r) r.u64 = 0;
  fpu.csr = {};
  cop2 = {};
  emuxState = {};
  fenv.setRound(float_env::toNearest);
  context.setMode();
  scheduleCompare();
  sysad.power();
}

}
