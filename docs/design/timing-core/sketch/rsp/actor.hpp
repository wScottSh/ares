//The RSP as a timeline actor. Additions to the existing struct RSP; the
//interpreter and its Pipeline (rsp.hpp:163-260, GPR/VR read-after-write and
//load-store stalls) are kept as they are and remain the RSP cost model.
//
//The RSP recompiler is removed from the build (T1). Its blocks run past any
//sync target and step DMA once per block (recompiler-parity.md row E, the
//+1.7% of #28); making it exact would mean exits at every interaction op and
//at the SP DMA landing horizon, which is the interpreter's step size anyway.

namespace ares::Nintendo64 {

using Timing::Clock;

struct RSPActor : Timing::Actor {
  Clock time;  //start of the next issue pair

  //Parked while halted: a halted RSP costs nothing and steps nothing (today
  //it steps every 128 ticks, ares-timing-architecture.md s.1). The SP_STATUS
  //write that clears HALT (from SysAD drain or a CPU-side path) sets
  //time = max(time, writeTime) and makes it Runnable.
  //
  //Runnable only while time < ri.earliestLanding(SpDma): an instruction may
  //not read DMEM/IMEM past a DMA write that has not been decided yet. At the
  //horizon it reports Blocked; the bus decision wakes it.
  auto readiness() const -> Timing::Readiness override;

  //One issue pair (rsp.cpp:49-86), then time += pipeline.clocks converted to
  //units. Interactions inside the pair use `time` (the pair's start):
  //  MFC0 SP_DMA_*        -> DMA state as of `time` (bus already decided
  //                          up to the horizon, see readiness)
  //  MFC0/MTC0 DPC_*      -> timeline.catchUp(time, RSP), then rdp.read/write
  //  MTC0 SP DMA length   -> spDma.start(time)
  //  BREAK / SP_STATUS    -> mi.raise(SP) at `time`
  //  SP_PC read (CPU)     -> the live PC, never random()
  auto step(Clock limit) -> void override;
};

//SP DMA as a bus client with no time of its own. A start posts the first
//burst, naming the DMEM/IMEM bytes it moves; the RI copies them at grant time
//and granted() posts the next burst at that grant's completion. Rows (LEN+1,
//SKIP) split at 128 B and at 2 KiB RDRAM rows. Busy/full flags are functions
//of the pending and granted bursts, so a read at time t needs no stepping.
struct SpDma : RI::Client {
  auto start(Clock at) -> void;
  auto busy(Clock at) const -> bool;
  auto full(Clock at) const -> bool;
  auto granted(const RI::Grant&) -> void override;
};

}
