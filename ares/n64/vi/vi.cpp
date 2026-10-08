#include <n64/n64.hpp>

namespace ares::Nintendo64 {

VI vi;
#include "io.cpp"
#include "debugger.cpp"
#include "serialization.cpp"

auto VI::step(u32 vclks) -> void {
  Thread::clock = vclk.advance(vclks);
  timeline.schedule({Thread::clock, (u32)EventKind::VI_Line});
}

auto VI::load(Node::Object parent) -> void {
  node = parent->append<Node::Object>("VI");

  screen = node->append<Node::Video::Screen>("Screen", 640, 576);
  screen->setRefresh(std::bind_front(&VI::refresh, this));
  screen->refreshRateHint(Region::PAL() ? 50 : 60); // TODO: More accurate refresh rate hint
  screen->colors((1 << 24) + (1 << 15), [&](n32 color) -> n64 {
    if(color < (1 << 24)) {
      u64 a = 65535;
      u64 r = image::normalize(color >> 16 & 255, 8, 16);
      u64 g = image::normalize(color >>  8 & 255, 8, 16);
      u64 b = image::normalize(color >>  0 & 255, 8, 16);
      return a << 48 | r << 32 | g << 16 | b << 0;
    } else {
      u64 a = 65535;
      u64 r = image::normalize(color >> 10 & 31, 5, 16);
      u64 g = image::normalize(color >>  5 & 31, 5, 16);
      u64 b = image::normalize(color >>  0 & 31, 5, 16);
      return a << 48 | r << 32 | g << 16 | b << 0;
    }
  });
  
  int videoHeight = Region::PAL() ? 576 : 480;

  screen->setSize(640, videoHeight);

  // Pedantic N64 NTSC aspect ratio is 120:119, but let's keep 120:120 to avoid slight scaling.
  // Pedantic N64 PAL aspect ratio is 5900000:4965653, but let's use 12:10 to achieve the
  // same aspect ratio as NTSC.
  Region::PAL() ? screen->setAspect(12, 10) : screen->setAspect(120, 120);

  debugger.load(node);
}

auto VI::unload() -> void {
  debugger = {};
  node->remove(screen);
  screen.reset();
  node.reset();
}

auto VI::line() -> void {
  if(active()) {
    //HSYNC triggers the RDRAM refresh while the VI is active. rdram-bus-arbitration.md B11 says
    //refresh also runs before VI init, but nemu64-test's VI-off uncached loads (n64brew
    //Video_Interface: type 0 sends no sync) average 32.54 pclk, which a 52-rclk holdoff every
    //line would raise by about 2; the model follows nemu64 (behaviors.tsv ri.refresh-trigger).
    ri.refresh(Thread::clock);
    ++io.vcounter;
    int halfline = io.vcounter << 1 | io.field;
    if(halfline >= io.halfLinesPerField+1) {
      io.vcounter = 0;
      io.field += !io.halfLinesPerField.bit(0);
      if(++io.leapCounter == 5) io.leapCounter = 0;
    }

    if(io.vcounter == io.vstart >> 1) {
      refreshed = true;
      screen->frame();
      ri.checkRefresh();
    }

    if(io.halfLinesPerField.bit(0)) { // progressive
      if(io.vcounter == io.coincidence >> 1) {
        mi.raise(MI::IRQ::VI);
      }
    } else { // interlaced
      if(io.coincidence.bit(0)) {
        if(io.vcounter == io.coincidence >> 1)
          mi.raise(MI::IRQ::VI);
      }
      if(!io.coincidence.bit(0)) {
        int halfline = io.vcounter << 1 | io.field;
        if(!io.field && halfline == io.coincidence)
          mi.raise(MI::IRQ::VI);
        if(io.field && halfline+1 == io.coincidence)
          mi.raise(MI::IRQ::VI);
        if(!io.field && halfline == io.halfLinesPerField && io.coincidence == 0)
          mi.raise(MI::IRQ::VI);
      }
    }

    startFetch();

    u32 lineDuration = io.quarterLineDuration+1;
    if(io.vcounter == 1)
      lineDuration = io.hsyncLeap[io.leapPattern.bit(io.leapCounter)];      
    step(lineDuration);
  } else {
    // Arbitrarily call screen->frame() every once in a while to keep the UI responsive.
    // We do that every 200 simulated lines of 0x800 quarter-clocks. This is just arbitrary,
    // the real VI is not clocking at all when inactive; the period is host liveness, not a cost.
    io.vcounter = 0;
    if(++inactiveCounter >= 200) {
      inactiveCounter = 0;
      refreshed = true;
    }
    step(0x800);
  }
}

auto VI::window() const -> Window {
  Window w;
  w.hscanStart = Region::NTSC() ? 108 : 128;
  w.vscanStart = Region::NTSC() ?  34 :  44;
  w.hscanLen   = 640;
  w.vscanLen   = Region::NTSC() ? 480 : 576;
  s32 hscanStop = w.hscanStart + w.hscanLen;
  s32 vscanStop = w.vscanStart + w.vscanLen;

  w.dy0 = io.vstart;
  w.dy1 = io.vend;   if(w.dy1 < w.dy0) w.dy1 = vscanStop;
  w.dx0 = io.hstart;
  w.dx1 = io.hend;

  w.dy0 = max((s32)w.vscanStart, w.dy0);
  w.dy1 = min(vscanStop, w.dy1);
  w.dx0 = max((s32)w.hscanStart, w.dx0);
  w.dx1 = min(hscanStop, w.dx1);

  // Undocumented VI guard-band "hardware bug" (match parallel-RDP)
  if(w.dx0 >= (s32)w.hscanStart) w.dx0 += 8;
  if(w.dx1 <  hscanStop)         w.dx1 -= 7;
  return w;
}

auto VI::drawn(const Window& w, s32 dy) const -> bool {
  return dy >= w.dy0 && dy < w.dy1 && (!io.serrate || (dy & 1) == !io.field);
}

//Output line l covers screen rows 2l and 2l+1 (V_VIDEO counts half-lines).
//Each row samples framebuffer line (y >> 11) of the three fetched at HSYNC.
auto VI::compose() -> void {
  auto w = window();
  const u32 bpp = io.colorDepth == 2 ? 2 : 4;
  const u32 fetched = Fetch::Lines * fetch.pitch;
  for(s32 dy = 2 * fetch.output; dy < 2 * fetch.output + 2; dy++) {
    if(!drawn(w, dy)) continue;
    u32 y = io.ysubpixel + io.yscale * (dy - io.vstart);
    u32 base = ((y >> 11) - fetch.line) * fetch.pitch;
    auto row = screen->pixels(0).data() + (dy - w.vscanStart) * w.hscanLen;
    auto raw = scanned + (dy - w.vscanStart) * w.hscanLen;
    u32 x = io.xsubpixel + io.xscale * (w.dx0 - io.hstart);
    for(s32 dx = w.dx0; dx < w.dx1; dx++, x += io.xscale) {
      u32 at = base + (x >> 10) * bpp;
      //the VI reads only the fetched lines; a sample past them has no bytes
      u32 pixel = 0;
      if(at + bpp <= fetched) {
        const u8* p = fetch.bytes + at;
        pixel = bpp == 2 ? p[0] << 8 | p[1] : p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
      }
      raw[dx - w.hscanStart] = pixel;
      row[dx - w.hscanStart] = bpp == 2 ? 1 << 24 | pixel >> 1 : pixel >> 8;
    }
  }
}

//A line still fetching at the next HSYNC (only a VI programmed with a line
//shorter than its H_VIDEO window) keeps fetching; the new line fetches nothing.
auto VI::startFetch() -> void {
  if(io.colorDepth < 2 || !io.width) return;
  if(fetch.next < fetch.count || fetch.inFlight) return;
  auto w = window();
  s32 dy = 2 * io.vcounter;
  if(!drawn(w, dy)) dy++;
  if(!drawn(w, dy)) return;
  fetch.hsync  = vclk;
  fetch.hstart = io.hstart;
  fetch.hend   = io.hend;
  fetch.output = io.vcounter;
  if(dy == w.dy0 || dy == w.dy0 + 1) scannedOrigin = io.dramAddress;
  fetch.line   = io.ysubpixel + io.yscale * (dy - io.vstart) >> 11;
  const u32 pitch = io.width * (io.colorDepth == 2 ? 2 : 4);
  fetch.start(io.dramAddress + fetch.line * pitch, pitch);
  fetch.next = 0;
  timeline.schedule({fetch.dueAt(0), (u32)EventKind::VI_Fetch});
}

auto VI::refresh() -> void {
  if(io.serrate == 0) screen->setProgressive(0);
  if(io.serrate == 1) screen->setInterlace(!io.field);
  auto w = window();
  screen->setViewport(0, 0, w.hscanLen, w.vscanLen);
  if(Model::Aleck64()) aleck64.vdp.render(screen);
}

//At HSYNC: latch the line's geometry and build its burst list. Segment j of
//lines n, n+1, n+2 in turn (US 6,166,748: a block of line n, then of n+1 and
//n+2), each split where it crosses a 2 KiB row (ri.row-of).
auto VI::Fetch::start(u32 origin_, u32 pitch_) -> void {
  origin = origin_;
  pitch = pitch_;
  count = 0;
  for(u32 j = 0; j < pitch; j += Timing::Behavior::ViBurst) {
    for(u32 k = 0; k < Lines; k++) {
      u32 offset = k * pitch + j;
      u32 left = min((u32)Timing::Behavior::ViBurst, pitch - j);
      while(left) {
        u32 address = origin + offset & 0xffffff;
        u32 n = RiBus::split(address, left);
        slots[count++] = {address, offset, (u8)n};
        offset += n;
        left -= n;
      }
    }
  }
}

//Slot k of N is due at H_START + k (H_END - H_START) / N pixels into the line
//(vi.fetch-window); H_VIDEO counts pixels of vi.vclk-per-pixel VCLKs.
auto VI::Fetch::dueAt(u32 slot) const -> Clock {
  u32 width = hend > hstart ? hend - hstart : 0;
  auto t = hsync;
  return t.advance((u64)(hstart + (u64)slot * width / count) * Timing::Behavior::ViVclkPerPixel);
}

auto VI::Fetch::post(Clock at) -> void {
  const auto& s = slots[next];
  ri.post({s.address, s.bytes, RiBus::Direction::Read, RiBus::Requester::ViFetch, (u16)next}, at);
  inFlight = true;
  due = false;
  if(++next < count) {
    Clock t = dueAt(next);
    timeline.schedule({t > at ? t : at, (u32)EventKind::VI_Fetch});
  }
}

auto VI::fetchDue() -> void {
  if(fetch.inFlight) { fetch.due = true; return; }
  fetch.post(timeline.now(Thread::clock));
}

auto VI::Fetch::buffer(const RiBus::Burst& b) -> void* {
  return bytes + slots[b.tag].offset;
}

auto VI::Fetch::granted(const RiBus::Grant& g) -> void {
  inFlight = false;
  if(next == count) return vi.compose();
  if(due) post(g.dataEnd);
}

auto VI::power(bool reset) -> void {
  Thread::reset();
  screen->power();
  io = {};
  refreshed = false;
  vclk = {system.vclkPeriod()};
  fetch.count = fetch.next = 0;
  fetch.inFlight = fetch.due = false;
  ri.attach(RiBus::Requester::ViFetch, &fetch);
  timeline.schedule({Thread::clock, (u32)EventKind::VI_Line});
}

}
