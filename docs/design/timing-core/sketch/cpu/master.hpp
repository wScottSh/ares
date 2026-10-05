//The CPU master loop and the one memory path. Replaces CPU::main,
//CPU::synchronize, jitClockTarget, forceSynchronize and the 55 scattered
//step() calls (ares-timing-architecture.md s.2, obstacle 3).

namespace ares::Nintendo64 {

using Timing::Clock;

//  auto CPU::main() -> void {           //one VI field per host frame, as now
//    while(!vi.refreshed) instruction();
//    vi.refreshed = false;
//  }
//
//  auto CPU::instruction() -> void {
//    auto slot = fetchWindow.next();     //word fetched at its IC time
//    auto& t = opTiming[decode(slot.word)];
//    pipeline.issue(t);                  //ex for this instruction
//    if(pipeline.ex >= timeline.horizon()) timeline.catchUp(pipeline.ex, ActorId::CPU);
//    if(interruptTaken(pipeline.ex)) return pipeline.fault(FaultStage::RF), exception.interrupt();
//    execute(slot.word);                 //may call load()/store() below, may fault
//    pipeline.retire(t, latencyFor(t)); //trivial-operand FPU latency decided here
//  }
//
//Interrupt sampling uses CP0 state after Cp0Writes visibility and MI lines as
//of pipeline.ex; catchUp guarantees every raise before ex has happened.

struct CpuMemory {
  //The interpreter's loads and stores call these and nothing else.
  //  cached hit:   no time beyond the pipeline (CpuDcacheHit is the issue cycle)
  //  cached miss:  pipeline.freezeUntil(sysad.fill(..., pipeline.dc()));
  //                dirty victim -> sysad.writeback(...) after the fill
  //  uncached:     pipeline.freezeUntil(sysad.read(..., pipeline.dc()))
  //  store:        pipeline.freezeUntil(sysad.store(..., pipeline.dc()))
  template<u32 Size> auto load(u64 vaddr, u64& data) -> bool;
  template<u32 Size> auto store(u64 vaddr, u64 data) -> bool;
  auto fetch(u64 vaddr) -> maybe<u32>;  //I-cache hit, or fill through sysad
};

}
