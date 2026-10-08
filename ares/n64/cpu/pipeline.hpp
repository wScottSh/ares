//VR4300 issue timing (ADR 0001, CPU timing seam).
//
//The VR4300 issues one instruction per PClock, in order, and every interlock
//stalls the whole pipeline (NEC VR4300 UM ch. 4). MULT/DIV and the FPU hold
//EX for their full latency with nothing executing in their shadow (nemu64-test
//HiLoInterlockTiming: "the total is always latency + nops + 1"), so each
//instruction's own cost is one number. The interlocks that depend on another
//instruction are a late result read in the next issue slot:
//  - LDI: a load or MFC0/DMFC0 result (UM s.4.6.5);
//  - FPU forwarding: an FPU result read by the next FPU operation;
//  - DCB: a cached access right after a cached store (UM s.4.6.7).
//The scoreboard holds, for each register, the earliest issue time at which a
//reader does not stall, so LDI and forwarding are one max() at issue.

//What the decoder knows about an instruction's timing before it executes.
struct OpTiming {
  //The VR4300 compares raw instruction fields against a pending load, whether
  //or not the instruction reads them (n64brew VR4300 load delay interlock;
  //nemu64-test CPURegisterDependency: ADDI $A2,$T0 stalls on $A2, MTC0 on rs=4).
  enum Field : u8 { RS = 1, RT = 2 };
  //Which result arrives late, and in which register field.
  enum class Late : u8 { None, LoadRt, Cp0Rt, LoadFt, FpuFd };
  //Operand classes on which an FPU operation finishes in Behavior::CpuFpuTrivial.
  enum class Fast : u8 { None, AddSub, Mul, Div, Sqrt, FromInt };

  Clock cost;              //time the instruction holds EX, its issue slot included
  u8    gprFields = 0;     //Field bits checked against pending GPR results
  bool  fprFields = false; //fs and ft checked against pending FPR results
  Late  late = Late::None;
  Fast  fast = Fast::None;
};

//Where an exception is detected, which sets how long the refill from the
//vector takes (nemu64-test Exceptions and COP1 JustFire, plan C1). None: no
//hardware reference, the exception costs nothing beyond its issue slot.
enum class FaultStage : u8 { None, RF, EX, FPU };

struct Pipeline {
  CPU& self;
  u64 pc     = 0;  //pc after current instruction
  u64 nextpc = 0;  //pc after next instruction
  u32 state  = 0;  //current branch state
  u32 nstate = 0;  //next branch state

  enum : u32 {
    DelaySlot = 1 << 1,
  };

  auto inDelaySlot() const -> bool { return state & DelaySlot; }
  auto setPc(u64 address) -> void { self.ipu.pc = pc = address; nextpc = address + 4; state = nstate = 0; flush(); }
  auto branch(u64 address) -> void { nextpc = address; nstate |= DelaySlot; }
  auto noBranch() -> void { nstate |= DelaySlot; }
  //A not-taken likely branch turns its delay slot into a bubble (nemu64-test LikelyBranchCycleCount).
  auto skip() -> void { pc += 4; nextpc = pc + 4; self.step(Timing::Behavior::CpuLikelyNullified); }
  auto begin() -> void {
    nstate = 0;
    pc = nextpc;
    nextpc += 4;
  }
  auto end() -> void {
    inFlight = nullptr;
    state = nstate;
    self.ipu.pc = pc;
  }

  //What retire() and fault() need from issue(): the cost beyond the issue slot and the late result.
  struct Issued {
    u32 word;
    Clock extra;
    OpTiming::Late late;
    u8 dest;
  };

  //pipeline.cpp
  //Stalls until every field the instruction checks is ready. Runs after the fetch
  //has charged the issue slot, before the instruction executes.
  auto issue(u32 word) -> Issued;
  //Charges the instruction's cost beyond its issue slot and records its late result.
  //An instruction that raised an exception does neither: fault() charged it.
  auto retire(const Issued&) -> void;
  //Charges the refill from the exception vector. An exception raised outside an
  //instruction (interrupt, instruction fetch) charges nothing here.
  auto fault(FaultStage) -> void;
  auto fpuDetection(const Issued&) -> Clock;
  //DCB: called on every cached D-cache access, before a hit is served.
  auto dataCacheAccess(bool store, bool hit) -> void;
  auto fastOperands(OpTiming::Fast, u32 word) -> bool;
  //An S or D format operand's fields; maxExponent marks Inf and NaN.
  struct FpuOperand {
    u64 exponent, mantissa, maxExponent;
    bool sign;
    auto bias() const -> u64 { return maxExponent >> 1; }
    auto special() const -> bool { return exponent == maxExponent || (exponent == 0 && mantissa == 0); }
    auto denormal() const -> bool { return exponent == 0 && mantissa != 0; }
    auto nan() const -> bool { return exponent == maxExponent && mantissa != 0; }
  };
  auto fpuOperand(u32 format, u8 index, bool target) -> FpuOperand;
  auto power() -> void;
  auto serialize(serializer&) -> void;

  //The word of instruction n is read in n-2's slot (cpu.fetch-ahead-slots): after
  //n-2 has executed, so a branch's target is known and a load has been served, and
  //before n-2's store lands, at WB (NEC VR4300 UM s.4.6.7 DCB). An older store has
  //landed and is seen. The window holds the next two instructions in program order.
  struct Fetched {
    u64 vaddr;
    u32 word;
    u32 translated;  //0: the fetch faults, raised when the instruction issues
  };
  //Reads the word at nextpc, and the one at pc if a branch or a skip has moved it.
  auto fetchAhead() -> void;
  //The word at pc. The reference holds until the next fetchAhead().
  auto take() -> const Fetched&;
  //The word of the instruction after the executing one.
  auto next() const -> const Fetched* { return window[head].vaddr == pc ? &window[head] : nullptr; }
  auto read(Fetched& slot, u64 vaddr) -> void;
  //An exception or ERET: no vaddr is all ones, so nothing in the window matches.
  auto flush() -> void { for(auto& slot : window) slot.vaddr = ~0ull; }
  Fetched window[Timing::Behavior::CpuFetchAheadSlots];
  u8 head = 0;  //the slot of the instruction at pc

  Clock gprReady[32];
  Clock fprReady[32];
  u64 storeInstruction = 0;  //instructionIndex + 1 of the last cached store; 0 for none
  //The instruction between issue() and end(), until an exception ends it. It lives
  //on CPU::instruction()'s stack: an Issued member here cost 10% of MM wall time.
  const Issued* inFlight = nullptr;
};
