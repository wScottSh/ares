//Determinism made checkable by a script (ADR 0001, Determinism): two runs of the same ROM
//must produce identical trace hashes at every VI field.

namespace Timing {

enum class ActorId : u8 {
  Bus,
  Events,
  SysAD,
  RDP,
  RSP,
  CPU,
};

struct TraceHash {
  //Folds one action into the rolling hash. The device event queue is the only caller until
  //the timeline (plan T5) folds every actor step and bus grant.
  auto fold(u64 pclock, ActorId actor, u8 kind, u64 payload) -> void;

  //Folds a hash of the whole serialized machine state into the rolling hash and returns the
  //result. A divergence therefore shows in every later field, and the first differing field
  //is where it began.
  auto fieldBoundary() -> u64;

  u64 rolling = 0;
  serializer state;  //reused across fields so its multi-MiB buffer is allocated once
};

}

extern Timing::TraceHash traceHash;
