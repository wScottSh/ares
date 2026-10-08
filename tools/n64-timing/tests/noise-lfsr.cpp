//Host unit test for the RDP noise LFSRs (checks.tsv: unit:noise-lfsr,
//noise:a, noise:b, noise:c). Drives RDPTimed::NoiseLfsr without a timeline
//against Thar0/RDP-Noise console dumps (noise-datasets.hpp). Exits nonzero
//on any failure.

#include <nall/nall.hpp>
#include <nall/main.hpp>
#include <cstdio>
#include <cstring>

namespace test {
  using namespace nall;
  using n1 = nall::Natural<1>;
  using n24 = nall::Natural<24>;
  #include <n64/timing/clock.hpp>
  #include <n64/timing/behaviors.hpp>
  #include <n64/rdp/timed.hpp>
}

#include "noise-datasets.hpp"

using namespace test;
using test::RDPTimed::NoiseLfsr;

static u32 failures = 0;

#define CHECK(cond, ...) do { if(!(cond)) { failures++; std::printf("FAIL %s:%d: ", __FILE__, __LINE__); std::printf(__VA_ARGS__); std::printf("\n"); } } while(0)

//rdp-noise.md: from all ones, a and b reach dataset A and B's first pixel after
//256,586,636 steps.
static constexpr u64 AbFirstPixel = 256'586'636;
//The four c captures' first pixels, found by locating each capture's a bits
//(a = 1 exactly where c is hidden) in a's sequence from all ones; 1787 steps
//apart, as rdp-noise.md reports.
static constexpr u64 CFirstPixel[4] = {161'308'259, 161'306'472, 161'304'685, 161'302'898};

static auto outputBit(u32 outputs, char lfsr) -> u32 { return outputs >> ('c' - lfsr) & 1; }

//Counts pixels whose `lfsr` output differs from `data`, stepping one RDP
//clock per pixel (1-cycle) through at(); skips hidden bits.
static auto mismatches(const char* data, u64 first, char lfsr) -> u32 {
  NoiseLfsr noise;
  u32 bad = 0;
  for(u32 i = 0; data[i]; i++) {
    if(data[i] == 'x') continue;
    bad += outputBit(NoiseLfsr::outputs(noise.at(first + i)), lfsr) != (u32)(data[i] - '0');
  }
  return bad;
}

static auto datasetA() -> void {
  CHECK(std::strlen(NoiseA) == 1016, "dataset A has %zu pixels", std::strlen(NoiseA));
  CHECK(mismatches(NoiseA, AbFirstPixel, 'a') == 0, "a from reset: %u/1016 pixels differ from dataset A", mismatches(NoiseA, AbFirstPixel, 'a'));
  //a defect that drops or repeats one step anywhere in the run shows here
  CHECK(mismatches(NoiseA, AbFirstPixel + 1, 'a') > 300, "dataset A also matches one clock later");
}

static auto datasetB() -> void {
  CHECK(mismatches(NoiseB, AbFirstPixel, 'b') == 0, "b from reset: %u/1016 pixels differ from dataset B", mismatches(NoiseB, AbFirstPixel, 'b'));
  //a and b run in lockstep from the same reset: a b that started one clock off fails
  CHECK(mismatches(NoiseB, AbFirstPixel - 1, 'b') > 300, "dataset B also matches one clock earlier");
}

static auto datasetC() -> void {
  const char* sets[4] = {NoiseC0, NoiseC1, NoiseC2, NoiseC3};
  for(u32 s : range(4)) {
    u32 hidden = 0;
    NoiseLfsr noise;
    for(u32 i = 0; sets[s][i]; i++) {
      u32 a = outputBit(NoiseLfsr::outputs(noise.at(CFirstPixel[s] + i)), 'a');
      hidden += a != (sets[s][i] == 'x');
    }
    CHECK(hidden == 0, "set C%u: a disagrees with the hidden c bits at %u pixels", s, hidden);
    //c runs one step ahead of a and b from reset; jump() carries that step
    u32 bad = mismatches(sets[s], CFirstPixel[s], 'c');
    CHECK(bad == 0, "set C%u: c from reset: %u known pixels differ", s, bad);
  }
}

//Stepping and jumping agree everywhere, the registers are maximal-length,
//and at() is a pure function of the clock whatever it was asked before.
static auto structure() -> void {
  const u64 clocks[] = {0, 1, 2, 63, 64, 65, 1000, 123'456'789, (1ull << 29) - 2, 1ull << 40};
  for(u64 n : clocks) {
    auto j = NoiseLfsr::jump(n);
    NoiseLfsr s;
    s.clock = n > 200 ? n - 200 : 0;
    s.registers = NoiseLfsr::jump(s.clock);
    for(; s.clock < n;) s.at(s.clock + 1);
    CHECK(j.a == s.registers.a && j.b == s.registers.b && j.c == s.registers.c, "jump(%llu) differs from stepping", (unsigned long long)n);
  }
  auto r0 = NoiseLfsr::jump(0);
  CHECK(r0.a == (1u << 29) - 1 && r0.b == (1u << 28) - 1, "a and b are not all ones at power-on");
  CHECK(r0.c == NoiseLfsr::c().shift((1u << 27) - 1), "c is not one step past all ones at power-on");
  CHECK(NoiseLfsr::a().advance(r0.a, (1ull << 29) - 1) == r0.a, "a's period is not 2^29 - 1");
  CHECK(NoiseLfsr::b().advance(r0.b, (1ull << 28) - 1) == r0.b, "b's period is not 2^28 - 1");
  CHECK(NoiseLfsr::c().advance(r0.c, (1ull << 27) - 1) == r0.c, "c's period is not 2^27 - 1");
  CHECK(NoiseLfsr::a().advance(r0.a, (1ull << 29) - 1 - 29) != r0.a, "a repeats early");

  NoiseLfsr n;
  n.at(5'000'000);
  auto back = n.at(17);
  auto direct = NoiseLfsr::jump(17);
  CHECK(back.a == direct.a && back.b == direct.b && back.c == direct.c, "at() going back in time keeps the later state");
  n.at(17 + 65);
  auto far = NoiseLfsr::jump(17 + 65);
  CHECK(n.registers.a == far.a, "at() across a gap past the step window");
}

auto nall::main(Arguments arguments) -> void {
  string which = arguments.take();
  if(which == "noise-lfsr") structure();
  else if(which == "dataset-a") datasetA();
  else if(which == "dataset-b") datasetB();
  else if(which == "dataset-c") datasetC();
  else { std::printf("usage: n64-timing-noise noise-lfsr|dataset-a|dataset-b|dataset-c\n"); exit(2); }
  std::printf("%s: %u failures\n", (const char*)which, failures);
  exit(failures ? 1 : 0);
}
