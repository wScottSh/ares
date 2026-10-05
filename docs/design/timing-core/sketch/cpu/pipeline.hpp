//VR4300 timing as a timestamped in-order pipeline.
//
//The VR4300 is single-issue and in-order, and every interlock, slip and
//memory stall freezes the whole pipeline (NEC UM ch. 4). So the stage times
//of instruction i are fixed offsets from one number, its EX time:
//
//    IC = ex - 2   RF = ex - 1   EX = ex   DC = ex + 1   WB = ex + 2   (pclk)
//
//and ex(i) = ex(i-1) + 1 + stall(i). A stage-by-stage simulator and this
//model produce the same stage times for an in-order, whole-pipe-stall
//machine; this one does it with one addition per instruction instead of five
//stage updates per cycle. The things that need stage identity are encoded as
//offsets from ex: memory at DC, fetch at IC (FetchWindow), exception detection
//stage (Fault), CP0 write visibility (Cp0Writes).
//
//This is the only cost model for the CPU. The interpreter calls it; the
//recompiler is removed from the timing build (rationale "CPU timing seam"). If
//a block executor returns, it must call these same functions in the same
//order, and the lockstep checker (plan U-L) compares their Clock traces.

namespace ares::Nintendo64 {

using Timing::Clock;

//Per-opcode timing, one table, filled from the decoder's existing OpInfo
//(register use/def masks) plus Timing::Behavior latencies. Indexed by the
//decoded op id both the interpreter and the disassembler already use.
struct OpTiming {
  enum class Unit : u8 { Integer, Load, Store, MulDiv, Fpu, Cp0, Branch, Cache };
  Unit unit;
  u8   latency;     //pclk until the result can be forwarded; Load/MFC0 = 2
  u8   repeat;      //pclk the unit stays busy (MCI): MULT/DIV/FPU
  u8   trivialLatency;  //FPU ops: latency when an operand is 0, -0, Inf or qNaN
  u32  gprUse, gprDef;  //register-field masks, including fields the VR4300
  u32  fprUse, fprDef;  //interlocks on without using (n64brew LDI rule)
  u1   readsHiLo, writesHiLo;
  u8   cp0WriteDelay;   //instructions until an MTC0 to this target is visible
};

extern const OpTiming opTiming[];

enum class FaultStage : u8 { RF, EX, FPU };

struct Pipeline {
  Clock ex;  //EX time of the instruction currently executing

  //Scoreboard: the earliest EX time at which a consumer may read each value.
  Clock gprReady[32];
  Clock fprReady[32];
  Clock hiloReady;
  Clock mulDivFree;
  Clock fpuFree;
  u1    lastWasFpuProducer;  //for the FPU->FPU forwarding bubble
  u1    lastWasStore;        //for DCB

  //Starts instruction i: computes ex(i) from ex(i-1) and every interlock the
  //operands and units impose. Pure arithmetic on the scoreboard; no I/O.
  //
  //  ex = ex + pclk(1)
  //  ex = max(ex, gprReady[s] for s in t.gprUse)       //LDI, MFC0, MCI reads
  //  ex = max(ex, fprReady[s] + fwd for s in t.fprUse) //fwd = CpuFpuForward
  //                                                     //  when the producer was FPU
  //  if t.readsHiLo: ex = max(ex, hiloReady)
  //  if t.unit is MulDiv: ex = max(ex, mulDivFree)
  //  if t.unit is Fpu:    ex = max(ex, fpuFree)
  //  if lastWasStore and t.unit in {Load, Store, Cache}: ex += CpuDcb
  auto issue(const OpTiming& t) -> void;

  //Retires instruction i's results into the scoreboard. `latency` is the
  //table value, or trivialLatency when the FPU operands hit the fast path,
  //which only the executing op can know (nemu64-test C3).
  auto retire(const OpTiming& t, u8 latency) -> void;

  auto dc() const -> Clock { return ex + Timing::pclk(1); }

  //A memory or fetch stall freezes the whole pipe: every later stage time
  //moves by the same amount. Scoreboard times are absolute and do not move,
  //on the reading that MULT/DIV and FPU iterate independently of the pipe
  //freeze (unverified; open question in the rationale).
  auto freezeUntil(Clock dcComplete) -> void;

  //Exception: the handler's first instruction gets EX at
  //  ex(i) + {CpuExcRf, CpuExcEx, CpuExcFpuUnimpl}[stage]
  //and an FPU arithmetic exception first pays the op's own latency
  //(nemu64-test C1). ERET and the nullified likely-branch slot are bubbles
  //with their own table rows.
  auto fault(FaultStage) -> void;
  auto bubble() -> void;
};

//Instruction words are fetched at IC, three issue slots ahead of the DC stage
//of the instruction that might be storing to them. Keeping that window
//explicit is what makes self-modifying code within ~3 instructions execute
//the old word (nemu64-test cycle set, 7 SMC cases).
struct FetchWindow {
  struct Slot {
    u64 pc;
    u32 word;
    Clock ic;
  };
  Slot slots[3];
  u8   count = 0;

  auto refill(u64 pc) -> void;  //branch taken, exception, ERET
  auto next() -> Slot;
};

//MTC0/DMTC0 effects land late and differently per register (nemu64-test
//cop0hazard: COUNT write, Cause/Status interrupt sampling one instruction
//late, Wired). Reads apply every pending write whose instruction index has
//been reached.
struct Cp0Writes {
  struct Pending {
    u8  reg;
    u64 value;
    u64 visibleAtInstruction;
  };
  Pending pending[4];
  u8      count = 0;
};

//Registers that are functions of time, evaluated on read instead of stepped.
//  COUNT(t)  = countBase + (t - countEpoch) / UnitsPerCount
//  Random(t) = derived from cycles since the last Wired write, decrementing
//              from 31 to Wired and wrapping (nemu64-test RandomDecrement)
//  COMPARE match -> one timeline event at the exact crossing time, not a
//              check in synchronize()
struct TimedCp0 {
  Clock countEpoch;
  u32   countBase;
  Clock wiredEpoch;
  auto count(Clock) const -> u32;
  auto random(Clock, u8 wired) const -> u8;
  auto compareCrossing(u32 compare) const -> Clock;
};

}
