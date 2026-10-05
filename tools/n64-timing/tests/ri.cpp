//Host unit test for RiBus::Channel, the RI's arbitration and wire-cost model
//(checks.tsv: unit:ri-cost-table). Each case names the defect it detects.

#include <nall/nall.hpp>
#include <cstdio>

namespace test {
  using namespace nall;
  #include <n64/timing/clock.hpp>
  #include <n64/timing/behaviors.hpp>
  #include <n64/ri/bus.hpp>
}

using namespace test;
using namespace test::Timing;
using namespace test::RiBus;

static u32 failures = 0;

#define CHECK(cond, ...) do { if(!(cond)) { failures++; std::printf("FAIL %s:%d: ", __FILE__, __LINE__); std::printf(__VA_ARGS__); std::printf("\n"); } } while(0)

static auto burst(u32 address, u8 bytes, Direction direction, Requester requester = Requester::CpuSysAD) -> Burst {
  return {address, bytes, direction, requester, 0};
}

//Grants `b` alone on `c` at time `at`; returns its wire time in tc.
static auto wireTc(Channel& c, Burst b, s64 at) -> s64 {
  c.post(b, Clock{at});
  auto g = c.decide();
  return (g.dataEnd - g.start).units / UnitsPerTc;
}

auto testRi() -> u32 {
  failures = 0;

  //The cost table (rdram-bus-arbitration.md s.2, NEC uPD488170L at the IPL3
  //delays): request start to last data beat for 1/2/4/8/16 octbytes. Defects:
  //a wrong row state (no bank tracking, dirty never set or never cleared), a
  //per-octbyte or retry constant off, or read and write swapped.
  {
    const u32 octs[] = {1, 2, 4, 8, 16};
    const s64 readHit[]   = {14, 18, 26, 42, 74};
    const s64 writeHit[]  = { 8, 12, 20, 36, 68};
    const s64 readClean[] = {36, 40, 48, 64, 96}, readDirty[]  = {44, 48, 56, 72, 104};
    const s64 writeClean[]= {30, 34, 42, 58, 90}, writeDirty[] = {38, 42, 50, 66, 98};
    const u32 a = 0x0030'0000, other = a + 0x800;  //bank 3, two rows
    for(u32 i = 0; i < 5; i++) {
      const u8 n = octs[i] * 8;
      for(auto dir : {Direction::Read, Direction::Write}) {
        bool read = dir == Direction::Read;
        Channel c; c.reset();
        wireTc(c, burst(a, 8, Direction::Read), 0);
        s64 hit = wireTc(c, burst(a, n, dir), 10'000);
        CHECK(hit == (read ? readHit[i] : writeHit[i]), "%s hit %u B: %lld tc", read ? "read" : "write", n, (long long)hit);

        c.reset();
        wireTc(c, burst(other, 8, Direction::Read), 0);
        s64 clean = wireTc(c, burst(a, n, dir), 10'000);
        CHECK(clean == (read ? readClean[i] : writeClean[i]), "%s clean miss %u B: %lld tc", read ? "read" : "write", n, (long long)clean);

        c.reset();
        wireTc(c, burst(other, 8, Direction::Write), 0);
        s64 dirty = wireTc(c, burst(a, n, dir), 10'000);
        CHECK(dirty == (read ? readDirty[i] : writeDirty[i]), "%s dirty miss %u B: %lld tc", read ? "read" : "write", n, (long long)dirty);
      }
    }
    //a write to the open row keeps it dirty; a read of it does not clean it
    Channel c; c.reset();
    wireTc(c, burst(other, 8, Direction::Write), 0);
    wireTc(c, burst(other, 8, Direction::Read), 10'000);
    CHECK(wireTc(c, burst(a, 8, Direction::Read), 20'000) == 44, "a read hit must not clear the dirty bit");
    //banks are independent: another bank's row does not close this one
    c.reset();
    wireTc(c, burst(a, 8, Direction::Read), 0);
    wireTc(c, burst(0x0040'0000, 8, Direction::Write), 10'000);
    CHECK(wireTc(c, burst(a, 8, Direction::Read), 20'000) == 14, "a row in bank 4 must not close bank 3's row");
  }

  //Decisions land on rclk edges, one request latency after the post, and the
  //channel is busy for wire + RI overhead + post gap. Defect: a decision off
  //the RCP clock or before the request arrives.
  {
    Channel c; c.reset();
    c.post(burst(0, 8, Direction::Read), Clock{12});
    CHECK(c.next() == Clock{24}, "a post at an rclk edge is decided at the next edge, got %lld", (long long)c.next().units);
    auto g = c.decide();
    CHECK(c.free == g.dataEnd + Behavior::RiOverheadRead + Behavior::RiPostReadGap, "channel free time after a read");
  }

  //Arbitration: refresh, then VI, then everyone first-come first-served by
  //arrival, then requester order, then posting order. No preemption: a burst
  //in flight finishes before refresh starts. Defects: rank ignored, arrival
  //ignored, a refresh that cuts into a burst.
  {
    Channel c; c.reset();
    c.post(burst(0, 8, Direction::Read, Requester::SpDma), Clock{0});
    c.post(burst(0, 8, Direction::Read, Requester::CpuSysAD), Clock{1});
    c.post({0, 0, Direction::Write, Requester::Refresh, 0}, Clock{2});
    c.post(burst(0, 8, Direction::Read, Requester::ViFetch), Clock{3});
    auto order = [&](Requester r) { auto g = c.decide(); return g.burst.requester == r; };
    CHECK(c.next() == Clock{12}, "first decision at 12");
    CHECK(order(Requester::Refresh), "refresh wins the first decision");
    CHECK(order(Requester::ViFetch), "VI before the rest");
    CHECK(order(Requester::SpDma), "then arrival order: SP DMA posted first");
    CHECK(order(Requester::CpuSysAD), "CPU last");

    c.reset();
    c.post(burst(0, 128, Direction::Write, Requester::SpDma), Clock{0});
    auto g = c.decide();
    c.post({0, 0, Direction::Write, Requester::Refresh, 0}, g.start + Clock{1});
    CHECK(c.next() == nextRclkEdge(c.free), "refresh waits for the burst in flight, got %lld vs %lld",
          (long long)c.next().units, (long long)c.free.units);

    c.reset();
    c.post(burst(0, 8, Direction::Read, Requester::PiDma), Clock{5});
    c.post(burst(0, 8, Direction::Read, Requester::CpuSysAD), Clock{5});
    CHECK(order(Requester::CpuSysAD), "equal arrival and rank fall back to requester order");
    c.reset();
    c.post({0, 0, Direction::Write, Requester::Refresh, 0}, Clock{20});
    c.post(burst(0, 8, Direction::Read, Requester::PiDma), Clock{0});
    CHECK(c.next() == Clock{12} && order(Requester::PiDma), "a refresh that has not arrived by the decision does not win it");
  }

  //Refresh: 52 rclk when no bank is dirty, 54 when one is; it clears every
  //dirty bit and leaves rows open (NEC s.8.2.2, B12). Defects: the dirty
  //delay never chosen, dirty bits kept, rows closed by refresh.
  {
    Channel c; c.reset();
    c.post({0, 0, Direction::Write, Requester::Refresh, 0}, Clock{0});
    auto g = c.decide();
    CHECK(g.dataEnd - g.start == Behavior::RiRefreshClean, "clean refresh 52 rclk");
    wireTc(c, burst(0x0010'0000, 8, Direction::Write), 10'000);
    c.post({0, 0, Direction::Write, Requester::Refresh, 0}, Clock{20'000});
    g = c.decide();
    CHECK(g.dataEnd - g.start == Behavior::RiRefreshDirty, "dirty refresh 54 rclk");
    CHECK(wireTc(c, burst(0x0010'0000, 8, Direction::Read), 30'000) == 14, "refresh leaves the row open");
    CHECK(wireTc(c, burst(0x0010'0800, 8, Direction::Read), 40'000) == 36, "refresh cleans the row: the next miss is clean");
  }

  //Counters: bursts, bytes, row misses, channel time and wait per requester.
  {
    Channel c; c.reset();
    c.post(burst(0, 16, Direction::Read), Clock{0});
    c.post(burst(0x800, 8, Direction::Write), Clock{0});
    c.decide(); c.decide();
    auto& k = c.counters[(u32)Requester::CpuSysAD];
    CHECK(k.bursts == 2 && k.bytesRead == 16 && k.bytesWritten == 8 && k.rowMisses == 2, "counters");
    CHECK(k.wait > Clock{0} && k.busy > Clock{0}, "wait and busy accumulate");
  }

  if(failures) std::printf("ri-cost-table: %u failure(s)\n", failures);
  else std::printf("ri-cost-table: ok\n");
  return failures;
}

//unit:ri-split: a DMA transfer's bursts are at most 128 B and never cross a
//2 KiB row (n64brew RDRAM_Interface Count, B2, B6). Defects: no row clip, no
//size cap, a clip one byte off, a short transfer padded to a full burst.
auto testRiSplit() -> u32 {
  u32 before = failures;
  CHECK(split(0x0000, 4096) == 128, "a long aligned transfer bursts 128 B");
  CHECK(split(0x07c0, 4096) == 64, "a burst stops at the 2 KiB row end");
  CHECK(split(0x07f8, 4096) == 8, "8 B before the row end");
  CHECK(split(0x0800, 4096) == 128, "the next row starts a full burst");
  CHECK(split(0x1234, 40) == 40, "a short transfer is one burst of its own size");
  CHECK(split(0x07ff, 2) == 1, "the last byte of a row");
  u32 n = 0, sum = 0;
  for(u32 address = 0x7f8, left = 4096; left; n++) {
    u32 b = split(address, left);
    sum += b; address += b; left -= b;
  }
  CHECK(sum == 4096 && n == 33, "4 KiB from 8 B before a row end: 8 B then 32 full bursts");
  u32 f = failures - before;
  if(f) std::printf("ri-split: %u failure(s)\n", f);
  else std::printf("ri-split: ok\n");
  return f;
}
