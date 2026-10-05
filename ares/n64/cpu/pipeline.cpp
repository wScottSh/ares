auto CPU::Pipeline::issue(u32 word) -> Issued {
  using Late = OpTiming::Late;
  auto t = opTiming(word);
  u8 rs = word >> 21 & 31, rt = word >> 16 & 31, fs = word >> 11 & 31, fd = word >> 6 & 31;

  Clock ready = self.clock;
  if(t.gprFields & OpTiming::RS && gprReady[rs] > ready) ready = gprReady[rs];
  if(t.gprFields & OpTiming::RT && gprReady[rt] > ready) ready = gprReady[rt];
  if(t.fprFields) {
    if(fprReady[fs] > ready) ready = fprReady[fs];
    if(fprReady[rt] > ready) ready = fprReady[rt];
  }
  self.step(ready - self.clock);

  Clock cost = t.fast != OpTiming::Fast::None && fastOperands(t.fast, word) ? Timing::Behavior::CpuFpuTrivial : t.cost;
  u8 dest = t.late == Late::FpuFd ? fd : rt;
  return {cost - Timing::Behavior::CpuIssue, t.late, dest};
}

auto CPU::Pipeline::retire(const Issued& issued) -> void {
  using namespace Timing::Behavior;
  using Late = OpTiming::Late;
  if(faulted) return;
  self.step(issued.extra);
  Clock next = self.clock + CpuIssue;
  switch(issued.late) {
  case Late::None: break;
  case Late::LoadRt: if(issued.dest) gprReady[issued.dest] = next + CpuLdi; break;
  case Late::Cp0Rt:  if(issued.dest) gprReady[issued.dest] = next + CpuMci; break;
  case Late::LoadFt: fprReady[issued.dest] = next + CpuLdi; break;
  case Late::FpuFd:  fprReady[issued.dest] = next + CpuFpuForward; break;
  }
}

//cen64 vr4300/pipeline.c:430-448 orders it the same way: a miss goes to DCM, and
//only a hit waits for the store before it. Only the next instruction waits: the
//nemu64-test Data cache Size loop (SW, then a cached SW six slots later) costs 6.
auto CPU::Pipeline::dataCacheAccess(bool store, bool hit) -> void {
  bool busy = storeInstruction == self.instructionIndex;
  if(store) storeInstruction = self.instructionIndex + 1;
  if(busy && hit) self.step(Timing::Behavior::CpuDcb);
}

//Operands on which an FPU operation finishes in Behavior::CpuFpuTrivial
//(nemu64-test COP1Instructions32/64, measured):
//  ADD/SUB, DIV: either operand 0, Inf or NaN;
//  MUL: either operand with a zero mantissa (0, Inf, any power of two) or NaN;
//  SQRT: 0, Inf, NaN or negative;
//  CVT.S/CVT.D from W or L: the integer 0.
auto CPU::Pipeline::fastOperands(OpTiming::Fast fast, u32 word) -> bool {
  using Fast = OpTiming::Fast;
  u32 format = word >> 21 & 31;
  u8 fs = word >> 11 & 31, ft = word >> 16 & 31;
  if(fast == Fast::FromInt) {
    if(format == 20) return self.fgr_s<s32>(fs) == 0;
    return self.fgr_s<s64>(fs) == 0;
  }

  struct Operand {
    u64 exponent, mantissa, maxExponent;
    bool sign;
    auto special() const -> bool { return exponent == maxExponent || (exponent == 0 && mantissa == 0); }
  };
  auto operand = [&](u64 bits) -> Operand {
    if(format == 17) return {bits >> 52 & 0x7ff, bits & (1ull << 52) - 1, 0x7ff, bool(bits >> 63)};
    return {bits >> 23 & 0xff, bits & 0x7fffff, 0xff, bool(bits >> 31 & 1)};
  };
  Operand a, b;
  if(format == 17) {
    a = operand(std::bit_cast<u64>(self.fgr_s<f64>(fs)));
    b = operand(std::bit_cast<u64>(self.fgr_t<f64>(ft)));
  } else {
    a = operand(std::bit_cast<u32>(self.fgr_s<f32>(fs)));
    b = operand(std::bit_cast<u32>(self.fgr_t<f32>(ft)));
  }

  switch(fast) {
  case Fast::AddSub:
  case Fast::Div:  return a.special() || b.special();
  case Fast::Mul:  return a.mantissa == 0 || b.mantissa == 0 || a.exponent == a.maxExponent || b.exponent == b.maxExponent;
  case Fast::Sqrt: return a.special() || a.sign;
  default: return false;
  }
}

auto CPU::Pipeline::power() -> void {
  for(auto& ready : gprReady) ready = {};
  for(auto& ready : fprReady) ready = {};
  storeInstruction = 0;
  faulted = false;
}

auto CPU::Pipeline::serialize(serializer& s) -> void {
  s(pc);
  s(nextpc);
  s(state);
  s(nstate);
  for(auto& ready : gprReady) s(ready.units);
  for(auto& ready : fprReady) s(ready.units);
  s(storeInstruction);
}
