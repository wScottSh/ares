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
  return {word, cost - Timing::Behavior::CpuIssue, t.late, dest};
}

auto CPU::Pipeline::retire(const Issued& issued) -> void {
  using namespace Timing::Behavior;
  using Late = OpTiming::Late;
  if(!inFlight) return;
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

auto CPU::Pipeline::fpuOperand(u32 format, u8 index, bool target) -> FpuOperand {
  if(format == 17) {
    u64 bits = std::bit_cast<u64>(target ? self.fgr_t<f64>(index) : self.fgr_s<f64>(index));
    return {bits >> 52 & 0x7ff, bits & (1ull << 52) - 1, 0x7ff, bool(bits >> 63)};
  }
  u32 bits = std::bit_cast<u32>(target ? self.fgr_t<f32>(index) : self.fgr_s<f32>(index));
  return {bits >> 23 & 0xff, bits & 0x7fffff, 0xff, bool(bits >> 31)};
}

//The nemu64-test JustFire count runs from the faulting instruction's issue slot
//through the handler's first, and fetch charges both slots.
auto CPU::Pipeline::fault(FaultStage stage) -> void {
  using namespace Timing::Behavior;
  if(!inFlight) return;
  auto& issued = *inFlight;
  inFlight = nullptr;
  Clock slots = CpuIssue + CpuIssue;
  switch(stage) {
  case FaultStage::None: return;
  case FaultStage::RF:  self.step(CpuExcRf - slots); return;
  case FaultStage::EX:  self.step(CpuExcEx - slots); return;
  case FaultStage::FPU:
    if((issued.word >> 21 & 31) < 16) return;  //a CTC1-raised FPE has no reference
    self.step(fpuDetection(issued) + CpuExcFpu - slots);
    return;
  }
}

//The time the FPU takes to raise an exception (nemu64-test COP1Instructions32/64
//JustFire, measured: the count is this plus CpuExcFpu). An exception raised from
//the result (inexact, overflow, underflow, a W conversion of 2^31 <= |x| < 2^32)
//takes the operation's latency, trivial operands included. One raised from the
//operands takes at most CpuFpuTrivial: a denormal or NaN operand; a conversion
//to W of |x| >= 2^32 or Inf, to L of |x| >= 2^53, or from L of |x| >= 2^55; a
//W or L format op that has an S form (fpuTiming gives it the S form's latency).
auto CPU::Pipeline::fpuDetection(const Issued& issued) -> Clock {
  using namespace Timing::Behavior;
  u32 word = issued.word;
  Clock latency = issued.extra + CpuIssue;
  u32 format = word >> 21 & 31, function = word & 0x3f;
  u8 fs = word >> 11 & 31, ft = word >> 16 & 31;
  bool operands = false;

  if(format == 20 || format == 21) {
    if(function == 0x20 || function == 0x21) {  //CVT.S, CVT.D
      s64 x = self.fgr_s<s64>(fs);
      operands = format == 21 && (x >= 1ll << 55 || x < -(1ll << 55));
    } else {
      operands = true;
    }
  } else if(format == 16 || format == 17) {
    auto a = fpuOperand(format, fs, false);
    bool twoOperands = function < 0x04 || function >= 0x30;
    operands = a.denormal() || a.nan();
    if(twoOperands) {
      auto b = fpuOperand(format, ft, true);
      operands |= b.denormal() || b.nan();
    }
    //Unbiased exponent at or above which a conversion to an integer is refused.
    s64 limit = (function >= 0x0c && function <= 0x0f) || function == 0x24 ? 32
              : (function >= 0x08 && function <= 0x0b) || function == 0x25 ? 53 : 0;
    if(limit && s64(a.exponent) - s64(a.bias()) >= limit) operands = true;
  }

  if(operands && latency > CpuFpuTrivial) latency = CpuFpuTrivial;
  return latency;
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

  auto a = fpuOperand(format, fs, false);
  auto b = fpuOperand(format, ft, true);

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
  inFlight = nullptr;
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
