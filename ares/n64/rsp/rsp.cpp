#include <n64/n64.hpp>

namespace ares::Nintendo64 {

RSP rsp;
#include "decoder.cpp"
#include "dma.cpp"
#include "io.cpp"
#include "interpreter.cpp"
#include "interpreter-ipu.cpp"
#include "interpreter-scc.cpp"
#include "interpreter-vpu.cpp"
#include "debugger.cpp"
#include "serialization.cpp"
#include "disassembler.cpp"
#include "emux.cpp"

auto RSP::load(Node::Object parent) -> void {
  node = parent->append<Node::Object>("RSP");
  dmem.allocate(4_KiB);
  imem.allocate(4_KiB);
  debugger.load(node);
}

auto RSP::unload() -> void {
  debugger.unload();
  dmem.reset();
  imem.reset();
  node.reset();
}

auto RSP::readiness() const -> Timing::Readiness {
  if(dma.busy.any()) {
    if(status.halted || dma.landing < Thread::clock) return Timing::Readiness::runnable(dma.landing);
    return Timing::Readiness::runnable(Thread::clock);
  }
  if(!status.halted) return Timing::Readiness::runnable(Thread::clock);
  return Timing::Readiness::parked();
}

auto RSP::run(Clock limit) -> void {
  while(true) {
    if(dma.busy.any() && (status.halted || dma.landing <= Thread::clock)) {
      if(Thread::clock < dma.landing) Thread::clock = dma.landing;
      dmaTransferStep();
    } else {
      instruction();
    }
    auto next = readiness();
    if(next.kind != Timing::Readiness::Kind::Runnable || timeline.ends(next.at, limit)) return;
    timeline.record(next.at, Timing::ActorId::RSP);  //one trace record per step, however the steps are batched
  }
}

auto RSP::instruction() -> void {
  pipeline.dblIssueCount = 0;
  u32 instruction = imem.read<Word>(ipu.pc);
  instructionPrologue(instruction);
  branch.begin();
  pipeline.begin();
  OpInfo op0 = decoderEXECUTE(instruction);
  pipeline.issue(op0);
  interpreterEXECUTE();

  if(!pipeline.singleIssue && !op0.branch()) {
    u32 instruction = imem.read<Word>(ipu.pc + 4);
    OpInfo op1 = decoderEXECUTE(instruction);

    if(canDualIssue(op0, op1)) {
      pipeline.dblIssueCount = 1;
      instructionEpilogue();
      instructionPrologue(instruction);
      branch.begin();
      pipeline.issue(op1);
      interpreterEXECUTE();
    }
  }

  pipeline.end();
  instructionEpilogue();

  step(pipeline.clocks);
  profile.cycles += pipeline.clocks.units;
  pipeline.clocksTotal += pipeline.clocks.units;
}

auto RSP::instructionPrologue(u32 instruction) -> void {
  pipeline.address = ipu.pc;
  pipeline.instruction = instruction;
  debugger.instruction();
}

auto RSP::instructionEpilogue() -> void {
  ipu.r[0].u32 = 0;
  if(branch.inDelaySlot()) {
    pipeline.stall();
    if(branch.pc & 4) pipeline.singleIssue = 1;
  }

  branch.end();
  ipu.pc = branch.pc;
}

auto RSP::power(bool reset) -> void {
  Thread::reset();
  timeline.attach(Timing::ActorId::RSP, this);
  dmem.fill();
  imem.fill();

  pipeline = {};
  profile = {};
  dma = {};
  status.semaphore = 0;
  status.halted = 1;
  status.broken = 0;
  status.full = 0;
  status.singleStep = 0;
  status.interruptOnBreak = 0;
  for(auto& signal : status.signal) signal = 0;
  for(auto& r : ipu.r) r.u32 = 0;
  ipu.pc = 0;
  branch.setPc(ipu.pc);
  for(auto& r : vpu.r) r = zero;
  vpu.acch = zero;
  vpu.accm = zero;
  vpu.accl = zero;
  vpu.vcoh = zero;
  vpu.vcol = zero;
  vpu.vcch = zero;
  vpu.vccl = zero;
  vpu.vce = zero;
  vpu.divin = 0;
  vpu.divout = 0;
  vpu.divdp = 0;

  reciprocals[0] = u16(~0);
  for(u16 index : range(1, 512)) {
    u64 a = index + 512;
    u64 b = (u64(1) << 34) / a;
    reciprocals[index] = u16(b + 1 >> 8);
  }

  for(u16 index : range(0, 512)) {
    u64 a = index + 512 >> (index % 2 == 1);
    u64 b = 1 << 17;
    //find the largest b where b < 1.0 / sqrt(a)
    while(a * (b + 1) * (b + 1) < (u64(1) << 44)) b++;
    inverseSquareRoots[index] = u16(b >> 1);
  }

  if constexpr(Accuracy::RSP::SISD) {
    platform->status("RSP vectorization disabled (no SSE 4.1 support)");
  }
}

}
