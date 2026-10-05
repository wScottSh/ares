#include <n64/n64.hpp>
#include <mia/mia.hpp>
#include <nall/main.hpp>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#if defined(PLATFORM_WINDOWS)
  #include <fcntl.h>
  #include <io.h>
  #define dup _dup
  #define dup2 _dup2
  #define fdopen _fdopen
#else
  #include <unistd.h>
#endif

namespace N64 = ares::Nintendo64;

#include "script.hpp"

namespace {

struct FrameDump {
  u64 frame;
  string path;
};

enum class StopReason { EmuxExit, ScriptStop, FrameLimit, EmulatedTimeLimit, WallTimeLimit };

struct StopInfo {
  const char* name;
  int exitCode;
};

constexpr auto stopInfo(StopReason reason) -> StopInfo {
  switch(reason) {
  case StopReason::EmuxExit:          return {"emux-exit", 0};
  case StopReason::ScriptStop:        return {"script-stop", 0};
  case StopReason::FrameLimit:        return {"frame-limit", 0};
  case StopReason::EmulatedTimeLimit: return {"emulated-time-limit", 2};
  case StopReason::WallTimeLimit:     return {"wall-time-limit", 3};
  }
  return {"unknown", 1};
}

struct Options {
  string rom;
  u64 frames = 0;
  double emulatedSeconds = 0;
  double wallSeconds = 0;
  string statsPath;
  u32 controllers = 1;
  std::vector<FrameDump> dumps;
  string scriptPath;
};

//cpu.profile.cpuCycles counts VR4300 PClock cycles (93.75 MHz on NTSC).
constexpr double CpuCyclesPerSecond = 93'750'000.0;
//rsp_busy_clocks stays in the core's pre-T4 unit, 187.5 MHz ticks (2 per PClock), so stats files
//compare across the 750 MHz rebase; the RSP profile counts Timing::Clock units.
constexpr s64 UnitsPerStatsTick = N64::Timing::UnitsPerPclk / 2;

struct FrameStats {
  u64 frame;
  u32 origin;
  u32 width;
  u32 depth;
  u64 fbHash;
  s64 cpuCycles;
  s64 rspBusyClocks;
  u32 dpcStart;
  u32 dpcEnd;
  u32 colorImage;
  u32 depthImage;
  u64 rdpPixels;
  u64 traceHash;
};

auto usage() -> void {
  std::fprintf(stderr,
    "usage: n64-run ROM [options]\n"
    "  --frames N          stop after N VI fields (0 = no limit)\n"
    "  --emulated-seconds S  stop after S seconds of emulated CPU time (0 = no limit)\n"
    "  --wall-seconds S    stop after S seconds of host wall time (0 = no limit)\n"
    "  --stats FILE        write one TSV line per VI field to FILE\n"
    "  --dump-frame N FILE write the RDRAM image the VI samples at field N as a P6 PPM\n"
    "                      (640x480; repeatable)\n"
    "  --controllers N     gamepads connected at power-on (0-4, default 1)\n"
    "  --script FILE       run an input script (controller 1 input, memory peeks and pokes)\n"
    "stdout carries ISViewer and emux output only. The stop line goes to stderr.\n"
    "exit: 0 emux exit, script stop, or frame limit, 2 emulated-time limit, 3 wall-time limit, 1 error\n");
}

auto parse(const Arguments& arguments) -> maybe<Options> {
  Options options;
  for(u32 i = 0; i < arguments.size(); i++) {
    string arg = arguments[i];
    auto value = [&]() -> string {
      if(i + 1 >= arguments.size()) return {};
      return arguments[++i];
    };
    if(arg == "--frames") options.frames = value().natural();
    else if(arg == "--emulated-seconds") options.emulatedSeconds = value().real();
    else if(arg == "--wall-seconds") options.wallSeconds = value().real();
    else if(arg == "--stats") options.statsPath = value();
    else if(arg == "--script") options.scriptPath = value();
    else if(arg == "--controllers") options.controllers = min(4u, (u32)value().natural());
    else if(arg == "--dump-frame") {
      FrameDump dump;
      dump.frame = value().natural();
      dump.path = value();
      if(!dump.path) return nothing;
      options.dumps.push_back(dump);
    }
    else if(arg.beginsWith("--")) return nothing;
    else if(!options.rom) options.rom = arg;
    else return nothing;
  }
  if(!options.rom) return nothing;
  return options;
}

struct Fnv1a {
  u64 hash = 0xcbf29ce484222325ull;
  auto mix(u32 value) -> void {
    for(u32 byte : range(4)) {
      hash ^= (value >> byte * 8) & 0xff;
      hash *= 0x100000001b3ull;
    }
  }
};

//Walks the RDRAM pixels the VI scans out this field, sampling them the way VI::refresh does.
//The callback receives the output position and the raw 16- or 32-bit pixel.
template<typename F> auto walkFramebuffer(F&& pixelAt) -> void {
  auto& io = N64::vi.io;
  if(io.colorDepth < 2) return;

  const u32 hscanStart = N64::Region::NTSC() ? 108 : 128;
  const u32 vscanStart = N64::Region::NTSC() ?  34 :  44;
  const u32 hscanStop  = hscanStart + 640;
  const u32 vscanStop  = vscanStart + (N64::Region::NTSC() ? 480 : 576);

  s32 dy0 = io.vstart;
  s32 dy1 = io.vend; if(dy1 < dy0) dy1 = vscanStop;
  s32 dx0 = io.hstart;
  s32 dx1 = io.hend;
  dy0 = max((s32)vscanStart, dy0);
  dy1 = min((s32)vscanStop,  dy1);
  dx0 = max((s32)hscanStart, dx0);
  dx1 = min((s32)hscanStop,  dx1);
  if(dx0 >= (s32)hscanStart) dx0 += 8;
  if(dx1 <  (s32)hscanStop)  dx1 -= 7;

  auto& ram = N64::rdram.ram;
  const u32 bytesPerPixel = io.colorDepth == 2 ? 2 : 4;
  const u32 pitch = io.width;
  u32 y0 = io.ysubpixel + io.yscale * (dy0 - io.vstart);
  for(s32 dy = dy0; dy < dy1; dy++) {
    if(!io.serrate || (dy & 1) == !io.field) {
      u32 line = io.dramAddress + (y0 >> 11) * pitch * bytesPerPixel;
      u32 x0 = io.xsubpixel + io.xscale * (dx0 - io.hstart);
      for(s32 dx = dx0; dx < dx1; dx++) {
        u32 address = line + (x0 >> 10) * bytesPerPixel;
        u32 pixel = 0;
        if(address < ram.size) {
          pixel = bytesPerPixel == 2
            ? (u32)ram.N64::Memory::Writable::read<N64::Half>(address)
            : (u32)ram.N64::Memory::Writable::read<N64::Word>(address);
        }
        pixelAt(dx - hscanStart, dy - vscanStart, pixel);
        x0 += io.xscale;
      }
    }
    y0 += io.yscale;
  }
}

auto rdramFramebufferHash() -> u64 {
  Fnv1a fnv;
  walkFramebuffer([&](u32, u32, u32 pixel) { fnv.mix(pixel); });
  return N64::vi.io.colorDepth < 2 ? 0 : fnv.hash;
}

//Writes the sampled image as a 640x480 binary PPM. Unsampled positions stay black.
//5-bit channels are expanded by shifting, so a 15-bit and a 24-bit source of the same
//color differ in the low bits.
auto dumpFramebuffer(const string& path) -> bool {
  constexpr u32 width = 640, height = 480;
  std::vector<u8> rgb(width * height * 3, 0);
  const bool depth16 = N64::vi.io.colorDepth == 2;
  walkFramebuffer([&](u32 x, u32 y, u32 pixel) {
    if(x >= width || y >= height) return;
    u8* out = &rgb[(y * width + x) * 3];
    if(depth16) {
      out[0] = (pixel >> 11 & 31) << 3;
      out[1] = (pixel >>  6 & 31) << 3;
      out[2] = (pixel >>  1 & 31) << 3;
    } else {
      out[0] = pixel >> 24;
      out[1] = pixel >> 16;
      out[2] = pixel >>  8;
    }
  });
  file_buffer fp;
  if(!fp.open(path, file::mode::write)) return false;
  fp.print("P6\n", width, " ", height, "\n255\n");
  fp.write({rgb.data(), rgb.size()});
  return true;
}

auto sample(u64 frame, u64 fbHash) -> FrameStats {
  return {
    frame,
    (u32)N64::vi.io.dramAddress,
    (u32)N64::vi.io.width,
    (u32)N64::vi.io.colorDepth,
    fbHash,
    N64::cpu.profile.cpuCycles,
    (N64::rsp.profile.cycles - N64::rsp.profile.haltedCycles) / UnitsPerStatsTick,
    (u32)N64::rdp.command.start,
    (u32)N64::rdp.command.end,
    N64::rdp.engine.colorImage(),
    N64::rdp.engine.maskImage(),
    N64::rdp.engine.pixels(),
    N64::traceHash.fieldBoundary(),
  };
}

//Guest memory as a CPU load or store to a KSEG0/KSEG1 RDRAM address sees it: a dirty data
//cache line holds newer data than RDRAM. Unlike CPU::readDebug, a miss reads RDRAM directly
//instead of going through the bus, so script accesses never touch bus or cache timing state.
struct GuestMemory {
  static auto physical(u32 address) -> maybe<u32> {
    if(address < 0x8000'0000 || address >= 0xc000'0000) return nothing;
    u32 paddr = address & 0x1fff'ffff;
    if(paddr >= N64::rdram.ram.size) return nothing;
    return paddr;
  }

  static auto cachedLine(u32 address, u32 paddr) -> N64::CPU::DataCache::Line* {
    if(address >= 0xa000'0000) return nullptr;
    auto& line = N64::cpu.dcache.line(address);
    return line.hit(paddr) ? &line : nullptr;
  }

  static auto read(u32 address, script::Width width) -> maybe<u32> {
    auto paddr = physical(address);
    if(!paddr) return nothing;
    auto& ram = N64::rdram.ram;
    auto line = cachedLine(address, *paddr);
    switch(width) {
    case script::Width::Byte: return line ? line->bytes[*paddr & 15 ^ 3] : (u32)ram.N64::Memory::Writable::read<N64::Byte>(*paddr);
    case script::Width::Half: return line ? line->halfs[*paddr >> 1 & 7 ^ 1] : (u32)ram.N64::Memory::Writable::read<N64::Half>(*paddr);
    case script::Width::Word: return line ? line->words[*paddr >> 2 & 3] : (u32)ram.N64::Memory::Writable::read<N64::Word>(*paddr);
    }
    return nothing;
  }

  static auto write(u32 address, script::Width width, u32 value) -> bool {
    auto paddr = physical(address);
    if(!paddr) return false;
    auto& ram = N64::rdram.ram;
    if(auto line = cachedLine(address, *paddr)) {
      switch(width) {
      case script::Width::Byte: line->bytes[*paddr & 15 ^ 3] = value; break;
      case script::Width::Half: line->halfs[*paddr >> 1 & 7 ^ 1] = value; break;
      case script::Width::Word: line->words[*paddr >> 2 & 3] = value; break;
      }
      line->dirty |= ((1 << (u32)width) - 1) << (*paddr & 15);
      return true;
    }
    switch(width) {
    case script::Width::Byte: ram.N64::Memory::Writable::write<N64::Byte>(*paddr, value); break;
    case script::Width::Half: ram.N64::Memory::Writable::write<N64::Half>(*paddr, value); break;
    case script::Width::Word: ram.N64::Memory::Writable::write<N64::Word>(*paddr, value); break;
    }
    return true;
  }

  static auto evaluate(const script::Expr& expr) -> maybe<u32> {
    u32 value = 0;
    for(auto& term : expr.terms) {
      switch(term.op) {
      case script::Expr::Op::Push: value = term.value; break;
      case script::Expr::Op::Add: value += term.value; break;
      case script::Expr::Op::Load: {
        auto loaded = read(value, script::Width::Word);
        if(!loaded) return nothing;
        value = *loaded;
      } break;
      }
    }
    return value;
  }
};

//Runs script steps between VI fields until one has to wait for a later field.
struct ScriptRunner {
  std::vector<script::Step> steps;
  u32 next = 0;
  u64 waitUntil = 0;
  bool waiting = false;
  script::Pad pad;
  string shotPath;
  bool stopRequested = false;
  ares::Node::System* root = nullptr;

  auto log(const char* verb, const string& name, u64 frame, const string& detail = "") -> void {
    std::fprintf(stderr, "n64-run: %s %.*s frame=%llu%s%.*s\n", verb, (int)name.size(), name.data(),
      (unsigned long long)frame, detail.size() ? " " : "", (int)detail.size(), detail.data());
  }

  //frame is the number of VI fields completed so far.
  auto advance(u64 frame) -> void {
    while(next < steps.size() && !stopRequested) {
      bool done = std::visit([&](auto& step) { return execute(step, frame); }, steps[next]);
      if(!done) return;
      next++;
      waiting = false;
    }
  }

  auto execute(const script::Wait& step, u64 frame) -> bool {
    if(!waiting) { waiting = true; waitUntil = frame + step.fields; }
    return frame >= waitUntil;
  }

  auto execute(const script::Until& step, u64) -> bool {
    auto address = GuestMemory::evaluate(step.address);
    if(!address) return false;
    auto value = GuestMemory::read(*address, step.width);
    if(!value) return false;
    switch(step.compare) {
    case script::Compare::Equal:    return *value == step.value;
    case script::Compare::NotEqual: return *value != step.value;
    case script::Compare::AtLeast:  return *value >= step.value;
    case script::Compare::Below:    return *value <  step.value;
    }
    return false;
  }

  auto execute(const script::Input& step, u64) -> bool {
    pad = {step.buttons, step.x, step.y};
    return true;
  }

  auto execute(const script::Poke& step, u64 frame) -> bool {
    auto address = GuestMemory::evaluate(step.address);
    if(!address || !GuestMemory::write(*address, step.width, step.value)) log("poke-failed", "-", frame);
    return true;
  }

  auto execute(const script::Copy& step, u64 frame) -> bool {
    auto source = GuestMemory::evaluate(step.source);
    auto target = GuestMemory::evaluate(step.target);
    for(u32 offset = 0; source && target && offset < step.length; offset++) {
      auto byte = GuestMemory::read(*source + offset, script::Width::Byte);
      if(!byte || !GuestMemory::write(*target + offset, script::Width::Byte, *byte)) { log("copy-failed", "-", frame); break; }
    }
    if(!source || !target) log("copy-failed", "-", frame);
    return true;
  }

  auto execute(const script::Peek& step, u64 frame) -> bool {
    auto address = GuestMemory::evaluate(step.address);
    auto value = address ? GuestMemory::read(*address, step.width) : maybe<u32>{};
    log("peek", step.name, frame, value ? string{"0x", hex(*value, 2 * (u32)step.width)} : string{"unreadable"});
    return true;
  }

  auto execute(const script::Mark& step, u64 frame) -> bool {
    log("mark", step.name, frame);
    return true;
  }

  auto execute(const script::Shot& step, u64) -> bool {
    shotPath = step.path;
    return true;
  }

  auto execute(const script::SaveState& step, u64 frame) -> bool {
    auto state = (*root)->serialize(true);
    if(!file::write(step.path, {state.data(), state.size()})) log("save-state-failed", "-", frame);
    return true;
  }

  //The trace hash chain and the RSP profile belong to the run, not to the machine (the load
  //powers the core, which resets the profile), so they carry across the load: a
  //save-then-load round trip then compares column for column with a plain run.
  auto execute(const script::LoadState& step, u64 frame) -> bool {
    auto data = file::read(step.path);
    serializer state{data.data(), (u32)data.size()};
    auto rolling = N64::traceHash.rolling;
    auto rspProfile = N64::rsp.profile;
    if(data.empty() || !(*root)->unserialize(state)) log("load-state-failed", "-", frame);
    N64::traceHash.rolling = rolling;
    N64::rsp.profile = rspProfile;
    return true;
  }

  auto execute(const script::PokeTmem& step, u64) -> bool {
    N64::rdp.engine.tmem()[step.offset] = step.value;
    return true;
  }

  auto execute(const script::Stop&, u64) -> bool {
    stopRequested = true;
    return true;
  }
};

struct Headless : ares::Platform {
  std::shared_ptr<mia::Pak> system;
  std::shared_ptr<mia::Pak> game;
  bool exitRequested = false;
  FILE* output = stdout;

  auto pak(ares::Node::Object node) -> std::shared_ptr<vfs::directory> override {
    if(node->name() == "Nintendo 64") return system->pak;
    if(node->name() == "Nintendo 64 Cartridge") return game->pak;
    return {};
  }

  auto event(ares::Event event) -> void override {
    if(event == ares::Event::Shutdown) exitRequested = true;
  }

  //Every connected gamepad reads the script's pad; with no script, nothing is pressed.
  const script::Pad* pad = nullptr;

  auto input(ares::Node::Input::Input node) -> void override {
    if(!pad) return;
    if(auto button = node->cast<ares::Node::Input::Button>()) {
      auto& held = pad->buttons;
      button->setValue(std::find(held.begin(), held.end(), node->name()) != held.end());
    } else if(auto axis = node->cast<ares::Node::Input::Axis>()) {
      if(node->name() == "X-Axis") axis->setValue(pad->x);
      if(node->name() == "Y-Axis") axis->setValue(pad->y);
    }
  }

  auto log(ares::Node::Debugger::Tracer::Tracer node, string_view message) -> void override {
    if(!node->terminal()) return;
    std::fwrite(message.data(), 1, message.size(), output);
    if(node->autoLineBreak()) std::fputc('\n', output);
  }
};

}

auto nall::main(Arguments arguments) -> void {
  auto parsed = parse(arguments);
  if(!parsed) { usage(); std::_Exit(1); }
  auto options = *parsed;

  ScriptRunner runner;
  ares::Node::System root;
  runner.root = &root;
  if(options.scriptPath) {
    if(!file::exists(options.scriptPath)) {
      std::fprintf(stderr, "n64-run: cannot read script %s\n", options.scriptPath.data());
      std::_Exit(1);
    }
    auto parsedScript = script::parse(string::read(options.scriptPath));
    if(auto line = std::get_if<u32>(&parsedScript)) {
      std::fprintf(stderr, "n64-run: %s:%u: invalid script step\n", options.scriptPath.data(), *line);
      std::_Exit(1);
    }
    runner.steps = std::get<std::vector<script::Step>>(parsedScript);
  }

  Headless platform;
  platform.pad = &runner.pad;
  //The core prints debug notices with print() to stdout. Move fd 1 to stderr so the
  //real stdout carries only ISViewer and emux guest output.
  std::fflush(stdout);
  platform.output = fdopen(dup(1), "wb");
  dup2(2, 1);
  #if defined(PLATFORM_WINDOWS)
  _setmode(_fileno(platform.output), O_BINARY);
  #endif
  ares::platform = &platform;
  //Screen and audio stream nodes skip all host-side work while run-ahead is set, so no
  //host video/audio path runs and no screen thread reads RDRAM concurrently with the core.
  ares::setRunAhead(true);

  //An unused directory keeps mia from loading host save files that sit next to the ROM.
  mia::setSaveLocation([] { return string{Path::program(), "n64-run-no-saves/"}; });

  platform.system = mia::System::create("Nintendo 64");
  if(platform.system->load() != successful) {
    std::fprintf(stderr, "n64-run: failed to load system pak\n");
    std::_Exit(1);
  }
  platform.game = mia::Medium::create("Nintendo 64");
  if(platform.game->load(options.rom) != successful) {
    std::fprintf(stderr, "n64-run: failed to load ROM %s\n", options.rom.data());
    std::_Exit(1);
  }

  N64::option("Homebrew Mode", "true");
  N64::option("Expansion Pak", "true");

  if(!N64::load(root, "[Nintendo] Nintendo 64 (NTSC)")) {
    std::fprintf(stderr, "n64-run: failed to load N64 system\n");
    std::_Exit(1);
  }
  if(auto port = root->find<ares::Node::Port>("Cartridge Slot")) {
    port->allocate();
    port->connect();
  }
  for(u32 id : range(options.controllers)) {
    if(auto port = root->find<ares::Node::Port>({"Controller Port ", 1 + id})) {
      port->allocate("Gamepad");
      port->connect();
    }
  }
  root->power();

  file_buffer stats;
  if(options.statsPath) {
    if(!stats.open(options.statsPath, file::mode::write)) {
      std::fprintf(stderr, "n64-run: cannot write %s\n", options.statsPath.data());
      std::_Exit(1);
    }
    stats.print("frame\torigin\twidth\tdepth\tfb_hash\tcpu_cycles\trsp_busy_clocks"
                "\tdpc_start\tdpc_end\tcimg\tzimg\trdp_pixels\ttrace_hash\n");
  }

  auto wallStart = std::chrono::steady_clock::now();
  auto wallElapsed = [&] {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - wallStart).count();
  };
  auto emulatedElapsed = [] { return N64::cpu.profile.cpuCycles / CpuCyclesPerSecond; };

  u64 frames = 0;
  StopReason reason;
  while(true) {
    root->run();
    u64 fbHash = 0;
    if(N64::vi.active()) {
      if(stats) fbHash = rdramFramebufferHash();
      if(runner.shotPath && !dumpFramebuffer(runner.shotPath)) std::fprintf(stderr, "n64-run: cannot write %s\n", runner.shotPath.data());
      runner.shotPath = {};
    }
    if(N64::vi.active()) {
      if(stats) {
        auto s = sample(frames, fbHash);
        stats.print(s.frame, "\t", hex(s.origin, 6L), "\t", s.width, "\t", s.depth, "\t",
                    hex(s.fbHash, 16L), "\t", s.cpuCycles, "\t", s.rspBusyClocks, "\t",
                    hex(s.dpcStart, 6L), "\t", hex(s.dpcEnd, 6L), "\t", hex(s.colorImage, 7L), "\t",
                    hex(s.depthImage, 7L), "\t", s.rdpPixels, "\t", hex(s.traceHash, 16L), "\n");
      }
      for(auto& dump : options.dumps) {
        if(dump.frame != frames) continue;
        if(!dumpFramebuffer(dump.path)) std::fprintf(stderr, "n64-run: cannot write %s\n", dump.path.data());
      }
      frames++;
      runner.advance(frames);
    }
    if(platform.exitRequested) { reason = StopReason::EmuxExit; break; }
    if(runner.stopRequested) { reason = StopReason::ScriptStop; break; }
    if(options.frames && frames >= options.frames) { reason = StopReason::FrameLimit; break; }
    if(options.emulatedSeconds && emulatedElapsed() >= options.emulatedSeconds) { reason = StopReason::EmulatedTimeLimit; break; }
    if(options.wallSeconds && wallElapsed() >= options.wallSeconds) { reason = StopReason::WallTimeLimit; break; }
  }

  auto info = stopInfo(reason);
  stats.close();
  std::fflush(platform.output);
  std::fflush(stdout);
  std::fprintf(stderr, "n64-run: stop=%s frames=%llu emulated_s=%.6f wall_s=%.3f\n",
    info.name, (unsigned long long)frames, emulatedElapsed(), wallElapsed());
  //host cost per interpreted CPU instruction: the scheduler's own overhead shows here (plan T5)
  std::fprintf(stderr, "n64-run: cpu_instructions=%llu ns_per_instruction=%.2f\n",
    (unsigned long long)N64::cpu.instructionIndex,
    N64::cpu.instructionIndex ? wallElapsed() * 1e9 / N64::cpu.instructionIndex : 0.0);
  //host time inside the engine's render calls and the pixels it rasterized (ADR 0001 risk 1)
  auto& engine = N64::rdp.engine;
  std::fprintf(stderr, "n64-run: rdp_engine render_calls=%llu render_ms=%.3f pixels=%llu ns_per_pixel=%.2f\n",
    (unsigned long long)engine.renderCalls, engine.renderNanoseconds / 1e6,
    (unsigned long long)engine.pixels(),
    engine.pixels() ? (double)engine.renderNanoseconds / engine.pixels() : 0.0);
  std::fflush(stderr);
  //Skip core teardown: the result is already written, and unloading joins host threads for no benefit.
  std::_Exit(info.exitCode);
}
