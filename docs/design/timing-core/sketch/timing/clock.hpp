//Emulated time for the whole N64 core.
//
//One unit is 1/750 MHz. 750 MHz is the least common multiple of every
//synchronous NUS-001 clock, so each of them is an exact integer number of
//units (clocks.md: RCLK 250, RCP 62.5, PClock 93.75, COUNT 46.875 MHz, all
//from X2 x17). VCLK comes from the other crystal and is a rational multiple.
//
//Time is absolute since power-on. Nothing subtracts from it at sync points
//(today's Thread::clock does), so a timestamp means the same thing in every
//actor, in the bus, in the event queue and in a save state.

namespace ares::Nintendo64::Timing {

struct Clock {
  s64 units = 0;

  constexpr auto operator<=>(const Clock&) const = default;
  constexpr auto operator+(Clock o) const -> Clock { return {units + o.units}; }
  constexpr auto operator-(Clock o) const -> Clock { return {units - o.units}; }
  constexpr auto operator+=(Clock o) -> Clock& { units += o.units; return *this; }

  static constexpr auto never() -> Clock { return {INT64_MAX}; }
};

//Exact unit counts per hardware clock period.
constexpr s64 UnitsPerTc    =  3;  //RDRAM channel cycle, 4 ns
constexpr s64 UnitsPerPclk  =  8;  //VR4300 PClock
constexpr s64 UnitsPerRclk  = 12;  //RCP / MasterClock / SysAD / DPC_CLOCK
constexpr s64 UnitsPerCount = 16;  //COP0 COUNT = PClock / 2

constexpr auto tc  (s64 n) -> Clock { return {n * UnitsPerTc}; }
constexpr auto pclk(s64 n) -> Clock { return {n * UnitsPerPclk}; }
constexpr auto rclk(s64 n) -> Clock { return {n * UnitsPerRclk}; }

//Rounds up to the next RCP clock edge. The RI and every RCP block change
//state on rclk edges; only the RDRAM wire is finer.
constexpr auto nextRclkEdge(Clock t) -> Clock {
  return {(t.units + UnitsPerRclk - 1) / UnitsPerRclk * UnitsPerRclk};
}

//VCLK = 315/22 MHz * 17/5. One VCLK = 750e6 / VCLK units = 5500/357 units.
//The accumulator keeps the remainder so VI and AI never drift (the AI today
//double-truncates its period, +33 ppm; clocks.md).
struct VclkAccumulator {
  static constexpr s64 Numerator   = 5500;
  static constexpr s64 Denominator =  357;

  Clock origin;     //time of VCLK 0
  u64   vclks = 0;  //VCLKs elapsed since origin

  auto advance(u64 count) -> Clock {
    vclks += count;
    return {origin.units + (s64)(vclks * Numerator / Denominator)};
  }
};

}
