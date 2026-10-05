//Verification hooks that make determinism and sync independence checkable by
//a script instead of by argument. Always compiled in; a rolling hash costs
//about 1 ns per event. Output only when n64-run asks for the stats column.

namespace ares::Nintendo64::Timing {

//Every actor step and every RI grant folds (time, actor, kind, payload) into
//a 64-bit FNV-style hash. At each VI field boundary the rolling hash and a
//hash of {CPU regs, RDRAM, DMEM/IMEM, TMEM, span RAM halves, device regs}
//are written as the `trace_hash` stats column. Two runs of the same ROM must
//produce identical files.
struct TraceHash {
  u64 events;     //rolling over every action
  u64 state;      //computed at the field boundary
  auto fold(Clock, ActorId, u8 kind, u64 payload) -> void;
  auto fieldBoundary(u64 field) -> void;
};

//The harness exercises these on purpose (tools/n64-timing/determinism.sh):
//  det      two consecutive runs, same options: stats and trace_hash equal
//  stepcap  n64-run --step-cap (Timeline::stepCap = true, catchUp before
//           every instruction) against the normal run: equal. This is the
//           #14 sync-independence requirement as a test.
//  tie      for pairs of events the model declares independent (Vi and Ai at
//           an equal time), a build with their EventKind order swapped must
//           hash equal; if it does not, the pair was not independent.
//  entropy  the pinned seed changed: no field differs once T2 lands.
//The script fails with the first differing field and column.

}
