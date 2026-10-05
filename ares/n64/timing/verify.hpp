//Determinism made checkable by a script (ADR 0001, Determinism): two runs of the same ROM
//must produce identical trace hashes at every VI field.

namespace Timing {

struct TraceHash {
  //Folds a hash of the whole serialized machine state, which carries the timeline's rolling
  //hash of every step and event, into the rolling hash and returns the result. A divergence
  //therefore shows in every later field, and the first differing field is where it began.
  auto fieldBoundary() -> u64;

  u64 rolling = 0;
  serializer state;  //reused across fields so its multi-MiB buffer is allocated once
};

}

extern Timing::TraceHash traceHash;
