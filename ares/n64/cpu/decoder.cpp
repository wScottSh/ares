//Timing facts the decoder can read from the instruction word alone. Costs are
//nemu64-test measurements (behaviors.tsv rows); the register fields follow
//nemu64-test CPURegisterDependency.
auto CPU::opTiming(u32 instruction) -> OpTiming {
  using namespace Timing::Behavior;
  using Late = OpTiming::Late;
  OpTiming t{CpuIssue, OpTiming::RS | OpTiming::RT};

  switch(instruction >> 26) {
  case 0x00:  //SPECIAL
    switch(instruction & 0x3f) {
    case 0x18: case 0x19: t.cost = CpuMult; break;
    case 0x1a: case 0x1b: t.cost = CpuDiv; break;
    case 0x1c: case 0x1d: t.cost = CpuDmult; break;
    case 0x1e: case 0x1f: t.cost = CpuDdiv; break;
    }
    return t;
  case 0x02: case 0x03:  //J, JAL: no register fields ("LD $RA; JAL" does not stall)
    t.gprFields = 0;
    return t;
  case 0x10:  //COP0
    switch(instruction >> 21 & 31) {
    case 0x00: case 0x01: t.late = Late::Cp0Rt; break;  //MFC0, DMFC0
    case 0x10:  //CO
      if((instruction & 0x3f) == 0x18) t.cost = CpuEret;  //ERET
      break;
    case 0x04: case 0x05:  //MTC0, DMTC0
      switch(instruction >> 11 & 31) {
      case 1: case 2: case 3: case 7: case 10: t.cost = CpuMtc0SlowRegs; break;
      }
      break;
    }
    return t;
  case 0x11:
    return fpuTiming(instruction);
  case 0x12:  //COP2: inferred from COP1, whose moves check rt and not rs
    t.gprFields = OpTiming::RT;
    return t;
  case 0x1a: case 0x1b: case 0x20: case 0x21: case 0x22: case 0x23:
  case 0x24: case 0x25: case 0x26: case 0x27: case 0x30: case 0x34: case 0x37:
    t.late = Late::LoadRt;
    return t;
  case 0x2f:  //CACHE: only D-cache Index Load Tag has a measured cost
    if((instruction >> 16 & 31) == 0x05) t.cost = CpuCacheIndexLoadTag;
    return t;
  case 0x31: case 0x35:  //LWC1, LDC1: the base only ("LD $T3; LWC1 $F11" does not stall)
    t.gprFields = OpTiming::RS;
    t.late = Late::LoadFt;
    return t;
  case 0x39: case 0x3d:  //SWC1, SDC1
    t.gprFields = OpTiming::RS;
    return t;
  }
  return t;
}

//COP1 checks rt and never rs: "LB $A0; MTC1 $A3" does not stall although rs = 4.
//The arithmetic formats also check fs and ft as FPU operands, the destination
//never ("ADD.S doesn't create a dependency on its destination register").
auto CPU::fpuTiming(u32 instruction) -> OpTiming {
  using namespace Timing::Behavior;
  using Fast = OpTiming::Fast;
  OpTiming t{CpuIssue, OpTiming::RT};
  u32 format = instruction >> 21 & 31;
  if(format < 16) return t;  //moves and BC1: no FPU dependency in either direction
  t.fprFields = true;
  u32 function = instruction & 0x3f;
  if(function < 0x30) t.late = OpTiming::Late::FpuFd;  //C.cond writes only the condition bit

  bool d = format == 17;
  //A W or L format op that has an S form raises unimplemented operation after
  //the S form's latency (behaviors.tsv cpu.exc-fpu-detect).
  bool sForm = format == 16 || d || ((format == 20 || format == 21) && function != 0x20 && function != 0x21);
  if(sForm) switch(function) {
  case 0x00: case 0x01: t.cost = CpuFpuAdd; t.fast = Fast::AddSub; break;
  case 0x02: t.cost = d ? CpuFpuMulD : CpuFpuMulS; t.fast = Fast::Mul; break;
  case 0x03: t.cost = d ? CpuFpuDivD : CpuFpuDivS; t.fast = Fast::Div; break;
  case 0x04: t.cost = d ? CpuFpuSqrtD : CpuFpuSqrtS; t.fast = Fast::Sqrt; break;
  case 0x08: case 0x09: case 0x0a: case 0x0b:  //ROUND, TRUNC, CEIL, FLOOR .L
  case 0x0c: case 0x0d: case 0x0e: case 0x0f:  //ROUND, TRUNC, CEIL, FLOOR .W
  case 0x24: case 0x25:                        //CVT.W, CVT.L
    t.cost = CpuFpuConvert;
    break;
  case 0x20: if(d) t.cost = CpuFpuCvtSD; break;  //CVT.S.S is unimplemented
  }
  if(format == 20 || format == 21) switch(function) {
  case 0x20: case 0x21: t.cost = CpuFpuConvert; t.fast = Fast::FromInt; break;  //CVT.S, CVT.D
  }
  return t;
}
