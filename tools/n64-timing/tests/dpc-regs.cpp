//Host unit test for the RDP's DPC front end (checks.tsv: unit:dpc-regs).
//Drives RDPTimed::Dpc and the cost model without a timeline. Register
//expectations come from n64-systemtest src/tests/rdp/mod.rs (MIT, 196f542)
//and the double-buffer rules from n64brew and MiSTer RDP.vhd as cited in
//docs/research/rsp-rdp-fifo.md rows 9-13. Each check names the defect it
//detects. Exits nonzero on any failure.

#include <nall/nall.hpp>
#include <nall/main.hpp>
#include <cstdio>
#include <cstdlib>

namespace test {
  using namespace nall;
  using n1 = nall::Natural<1>;
  using n24 = nall::Natural<24>;
  #include <n64/timing/clock.hpp>
  #include <n64/timing/behaviors.hpp>
  #include <n64/rdp/timed.hpp>
}

using namespace test;
using namespace test::Timing;
using namespace test::RDPTimed;
using namespace test::Timing::Behavior;

static u32 failures = 0;

#define CHECK(cond, ...) do { if(!(cond)) { failures++; std::printf("FAIL %s:%d: ", __FILE__, __LINE__); std::printf(__VA_ARGS__); std::printf("\n"); } } while(0)

static auto status(const Dpc& d, u32 mask) -> u32 { return d.read(Status, {}) & mask; }

auto nall::main(Arguments) -> void {
  const u32 valid = StatusBit::StartValid | StatusBit::EndValid;

  //n64-systemtest StartAndEndMasking: both registers keep bits 23:3
  for(u32 v : {0xfffu, 0xff'ffffu, 0x12ff'ffffu, 0x1280'0000u, 0xffff'ffffu, 0u}) {
    Dpc d;
    d.write(Status, 1 << 3, {});  //freeze, as the test does
    d.write(Start, v, {});
    d.write(End, v, {});
    u32 m = v & 0xff'fff8;
    CHECK(d.read(Start, {}) == m && d.read(Current, {}) == m && d.read(End, {}) == m,
      "START/CURRENT/END not masked for %08x: %06x %06x %06x", v, d.read(Start, {}), d.read(Current, {}), d.read(End, {}));
  }

  //n64-systemtest StartIsValidFlag: START latches only while START_VALID is clear
  {
    Dpc d;
    d.write(Status, 1 << 3, {});
    CHECK(status(d, valid) == 0, "start-valid or end-valid set at power-on");
    d.write(Start, 0x1238, {});
    CHECK(status(d, valid) == StatusBit::StartValid, "START write should set START_VALID only, got %03x", status(d, valid));
    CHECK(d.read(Start, {}) == 0x1238, "START reads back the latched value");
    d.write(Start, 0x12'3450, {});
    CHECK(d.read(Start, {}) == 0x1238, "a second START while START_VALID must be ignored, got %06x", d.read(Start, {}));
    CHECK(d.read(Current, {}) == 0, "START must not move CURRENT");
    d.write(End, 0x1238, {});
    CHECK(status(d, valid) == 0, "END on an idle DMA consumes START: valid bits %03x", status(d, valid));
    CHECK(d.read(Current, {}) == 0x1238 && d.read(End, {}) == 0x1238, "END on an idle DMA loads CURRENT from START");
  }

  //n64brew / MiSTer RDP.vhd:545-605: START/END double buffer while the DMA is busy
  {
    Dpc d;
    d.write(Start, 0x1000, {});
    d.write(End, 0x1400, {});
    CHECK(status(d, StatusBit::DmaBusy), "DMA_BUSY should be set while CURRENT is short of END");
    d.write(Start, 0x2000, {});
    CHECK(status(d, valid) == StatusBit::StartValid, "START while busy sets START_VALID only, got %03x", status(d, valid));
    d.write(End, 0x2100, {});
    CHECK(status(d, valid) == valid, "END while START_VALID and busy must set END_VALID, got %03x", status(d, valid));
    CHECK(d.read(End, {}) == 0x2100, "END reads back the last written value, got %06x", d.read(End, {}));
    CHECK(d.read(Current, {}) == 0x1000, "a queued END must not move CURRENT, got %06x", d.read(Current, {}));
    d.fetched(0x200);
    CHECK(d.read(Current, {}) == 0x1200 && status(d, valid) == valid, "the first transfer keeps running to its own END");
    d.fetched(0x200);
    CHECK(d.read(Current, {}) == 0x2000 && d.end == 0x2000 + 0x100, "reaching END swaps in the queued pair: CURRENT %06x END %06x",
      d.read(Current, {}), (u32)d.end);
    CHECK(status(d, valid) == 0, "the swap clears START_VALID and END_VALID, got %03x", status(d, valid));
    d.fetched(0x100);
    CHECK(!status(d, StatusBit::DmaBusy), "DMA_BUSY must clear when CURRENT reaches END");
  }

  //F3DZEX2 appends within a lap: END with START_VALID clear extends the transfer
  {
    Dpc d;
    d.write(Start, 0x100, {});
    d.write(End, 0x180, {});
    d.fetched(0x40);
    d.write(End, 0x300, {});
    CHECK(d.read(Current, {}) == 0x140 && d.read(End, {}) == 0x300, "END without START_VALID extends; CURRENT %06x END %06x",
      d.read(Current, {}), d.read(End, {}));
  }

  //n64-systemtest StatusFlagsDuringRun: idle but unsynced, then synced
  {
    Dpc d;
    d.write(Start, 0x100, {});
    d.write(End, 0x100, {});
    const u32 idleBusy = StatusBit::CbufReady | StatusBit::PipeBusy | StatusBit::StartGclk;
    CHECK(d.status() == idleBusy, "after END the idle status is CBUF_READY|PIPE_BUSY|START_GCLK, got %03x", d.status());
    d.syncFullRetired(rclk(10));
    CHECK(d.status() == StatusBit::CbufReady, "after SYNC_FULL the status is CBUF_READY, got %03x", d.status());
  }

  //Frozen: END does not start the pipe; unfreezing does
  {
    Dpc d;
    d.write(Status, 1 << 3, {});
    d.write(End, 0x80, {});
    CHECK(!status(d, StatusBit::PipeBusy), "END while frozen must not set PIPE_BUSY");
    d.write(Status, 1 << 2, {});
    CHECK(status(d, StatusBit::PipeBusy | StatusBit::Freeze) == StatusBit::PipeBusy, "unfreezing starts the pipe");
  }

  //Counters count RCP clocks while on; DPC_TMEM_BUSY reads its counter (ares read it only when data == 7)
  {
    Dpc d;
    d.tmem.set(true, rclk(5));
    d.cmd.set(true, rclk(5));
    CHECK(d.read(TmemBusy, rclk(105)) == 100, "TMEM counter should read 100, got %u", d.read(TmemBusy, rclk(105)));
    CHECK(status(d, StatusBit::TmemBusy | StatusBit::CmdBusy) == (StatusBit::TmemBusy | StatusBit::CmdBusy), "TMEM_BUSY and CMD_BUSY follow the counters");
    d.tmem.set(false, rclk(105));
    CHECK(d.read(TmemBusy, rclk(500)) == 100, "a stopped counter holds its count");
    CHECK(d.read(BufBusy, Clock{rclk(205).units + 7}) == 200, "a read between edges sees the last edge, got %u", d.read(BufBusy, Clock{rclk(205).units + 7}));
    d.write(Status, 1 << 8, rclk(205));
    CHECK(d.read(BufBusy, rclk(215)) == 10, "STATUS bit 8 clears BUFBUSY, got %u", d.read(BufBusy, rclk(215)));
    d.write(Status, 1 << 9, rclk(300));
    CHECK(d.read(ClockCounter, rclk(350)) == 50, "STATUS bit 9 restarts DPC_CLOCK, got %u", d.read(ClockCounter, rclk(350)));
    d.write(Start, 0, rclk(400));
    d.write(End, 8, Clock{rclk(400).units + 5});
    CHECK(d.read(PipeBusy, rclk(410)) == 9, "PIPEBUSY starts at the rclk edge after END, got %u", d.read(PipeBusy, rclk(410)));
  }

  //Compute costs: Thar0 alpha all-fail 320x240 rectangle (hardware-corpora.md), setters, syncs, loads
  {
    auto clocks = [](Work w) { return cost(w).busy.units / UnitsPerRclk; };
    auto units = [](Clock c) { return c.units / UnitsPerRclk; };
    //a primitive's command-processor cost is its setup; its spans run in the pipeline
    CHECK(clocks({0x36, 0, 320 * 240, 0, 240, 0}) == 13, "a rectangle's setup costs 13");
    //Thar0 prints BUFBUSY - baseline - 1; the run's trailing setter overlaps the spans
    auto line1 = units(pixelClocks(0, 320) + spanTail(0)), line2 = units(pixelClocks(1, 320) + spanTail(1));
    CHECK(13 + 240 * line1 - 1 == 77772, "1-cycle 320x240 should read 77772, got %lld", (long long)(13 + 240 * line1 - 1));
    CHECK(13 + 240 * line2 - 1 == 155052, "2-cycle 320x240 should read 155052, got %lld", (long long)(13 + 240 * line2 - 1));
    CHECK(units(wordClocks(80)) == 80 + 2, "fill 320 px 16bpp: 80 words and the line gap");
    CHECK(clocks({0x2f}) == 1 && clocks({0x00}) == 1, "setters and NOP cost 1");
    CHECK(clocks({0x26}) == 25 && clocks({0x28}) == 33 && clocks({0x27}) == 50, "Sync Load/Tile/Pipe cost 25/33/50");
    CHECK(cost({0x29}).syncFull && !cost({0x27}).syncFull, "only Sync Full raises the DP interrupt");
    CHECK(clocks({0x33, 0, 0, 0, 0, 4096}) == 1 + 512 && cost({0x33}).load, "a 4 KiB load moves 8 B per clock");
  }

  //Command DMA requests: one burst at most, never past the FIFO (a full-burst wait deadlocks on a partial triangle)
  {
    Dpc d;
    d.write(Start, 0, {});
    d.write(End, 0x1000, {});
    CHECK(fetchDwords(d, 0) == 16, "an empty FIFO fetches one 128 B burst");
    CHECK(fetchDwords(d, 20) == 10, "20 dwords buffered leaves room for 10, got %u", fetchDwords(d, 20));
    CHECK(fetchDwords(d, 30) == 0, "a full FIFO fetches nothing");
    d.fetched(0x1000 - 32);
    CHECK(fetchDwords(d, 0) == 4, "the tail of a transfer is fetched whole");
    CHECK(xbusLatency(16) == rclk(16), "the X bus moves 8 B per clock");
  }

  if(failures) { std::printf("dpc-regs: %u failure(s)\n", failures); std::exit(1); }
  std::printf("dpc-regs: ok\n");
}
