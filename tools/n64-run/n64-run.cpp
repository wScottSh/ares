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

namespace {

enum class CpuMode { Interpreter, Recompiler };

//None: no RDP rasterizer runs; RDRAM holds only what the CPU and RSP write.
//Vulkan: paraLLEl-RDP on the host GPU, the same renderer the desktop build uses.
//Soft: the cen64-jgemu pixel engine on the emulation thread (ares/n64/rdp/engine).
enum class RdpMode { None, Vulkan, Soft };

constexpr auto rdpModeName(RdpMode mode) -> const char* {
  switch(mode) {
  case RdpMode::None:   return "none";
  case RdpMode::Vulkan: return "vulkan";
  case RdpMode::Soft:   return "soft";
  }
  return "unknown";
}

struct FrameDump {
  u64 frame;
  string path;
};

enum class StopReason { EmuxExit, FrameLimit, EmulatedTimeLimit, WallTimeLimit };

struct StopInfo {
  const char* name;
  int exitCode;
};

constexpr auto stopInfo(StopReason reason) -> StopInfo {
  switch(reason) {
  case StopReason::EmuxExit:          return {"emux-exit", 0};
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
  CpuMode cpu = CpuMode::Interpreter;
  RdpMode rdp = RdpMode::None;
  string statsPath;
  u32 controllers = 1;
  std::vector<FrameDump> dumps;
};

//cpu.profile.cpuCycles counts VR4300 PClock cycles (93.75 MHz on NTSC).
constexpr double CpuCyclesPerSecond = 93'750'000.0;

struct FrameStats {
  u64 frame;
  u32 origin;
  u32 width;
  u32 depth;
  u64 fbHash;
  s64 cpuCycles;
  s64 rspBusyClocks;
};

auto usage() -> void {
  std::fprintf(stderr,
    "usage: n64-run ROM [options]\n"
    "  --frames N          stop after N VI fields (0 = no limit)\n"
    "  --emulated-seconds S  stop after S seconds of emulated CPU time (0 = no limit)\n"
    "  --wall-seconds S    stop after S seconds of host wall time (0 = no limit)\n"
    "  --cpu interpreter|recompiler  CPU and RSP execution mode (default interpreter)\n"
    "  --rdp none|vulkan|soft  RDP rasterizer: none, paraLLEl-RDP on the host GPU, or the\n"
    "                      cen64-jgemu engine on the emulation thread (default none)\n"
    "  --stats FILE        write one TSV line per VI field to FILE\n"
    "  --dump-frame N FILE write the RDRAM image the VI samples at field N as a P6 PPM\n"
    "                      (640x480; repeatable)\n"
    "  --controllers N     gamepads connected at power-on (0-4, default 1)\n"
    "stdout carries ISViewer and emux output only. The stop line goes to stderr.\n"
    "exit: 0 emux exit or frame limit, 2 emulated-time limit, 3 wall-time limit, 1 error\n");
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
    else if(arg == "--controllers") options.controllers = min(4u, (u32)value().natural());
    else if(arg == "--cpu") {
      auto mode = value();
      if(mode == "interpreter") options.cpu = CpuMode::Interpreter;
      else if(mode == "recompiler") options.cpu = CpuMode::Recompiler;
      else return nothing;
    }
    else if(arg == "--rdp") {
      auto mode = value();
      if(mode == "none") options.rdp = RdpMode::None;
      else if(mode == "vulkan") options.rdp = RdpMode::Vulkan;
      else if(mode == "soft") options.rdp = RdpMode::Soft;
      else return nothing;
    }
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

//Hashes paraLLEl-RDP's VI scanout for this field and releases the readback buffer.
//VI::refresh normally does the release on the screen thread, which run-ahead disables;
//without it the next field's scanout waits forever.
auto vulkanScanoutHash() -> u64 {
  if(!N64::vi.gpuOutputValid) return 0;
  N64::vi.gpuOutputValid = false;
  const u8* rgba = nullptr;
  u32 width = 0, height = 0;
  N64::vulkan.mapScanoutRead(rgba, width, height);
  Fnv1a fnv;
  fnv.mix(width);
  fnv.mix(height);
  if(rgba) {
    for(u32 i : range(width * height)) fnv.mix(memory::readl<4>(rgba + i * 4) & 0xffffff);
  }
  N64::vulkan.unmapScanoutRead();
  N64::vulkan.endScanout();
  return fnv.hash;
}

auto sample(u64 frame, u64 fbHash) -> FrameStats {
  return {
    frame,
    (u32)N64::vi.io.dramAddress,
    (u32)N64::vi.io.width,
    (u32)N64::vi.io.colorDepth,
    fbHash,
    N64::cpu.profile.cpuCycles,
    N64::rsp.profile.cycles - N64::rsp.profile.haltedCycles,
  };
}

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

  Headless platform;
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

  N64::option("Enable GPU acceleration", options.rdp == RdpMode::Vulkan ? "true" : "false");
  N64::option("Software RDP", options.rdp == RdpMode::Soft ? "true" : "false");
  N64::option("Quality", "SD");
  N64::option("Supersampling", "false");
  N64::option("Homebrew Mode", "true");
  N64::option("Deterministic Entropy", "true");
  N64::option("Recompiler", options.cpu == CpuMode::Recompiler ? "true" : "false");
  N64::option("Expansion Pak", "true");

  ares::Node::System root;
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
    stats.print("frame\torigin\twidth\tdepth\tfb_hash\tcpu_cycles\trsp_busy_clocks\n");
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
    if(N64::vulkan.enable) fbHash = vulkanScanoutHash();
    else if(stats && N64::vi.active()) fbHash = rdramFramebufferHash();
    if(N64::vi.active()) {
      if(stats) {
        auto s = sample(frames, fbHash);
        stats.print(s.frame, "\t", hex(s.origin, 6L), "\t", s.width, "\t", s.depth, "\t",
                    hex(s.fbHash, 16L), "\t", s.cpuCycles, "\t", s.rspBusyClocks, "\n");
      }
      for(auto& dump : options.dumps) {
        if(dump.frame != frames) continue;
        if(!dumpFramebuffer(dump.path)) std::fprintf(stderr, "n64-run: cannot write %s\n", dump.path.data());
      }
      frames++;
    }
    if(platform.exitRequested) { reason = StopReason::EmuxExit; break; }
    if(options.frames && frames >= options.frames) { reason = StopReason::FrameLimit; break; }
    if(options.emulatedSeconds && emulatedElapsed() >= options.emulatedSeconds) { reason = StopReason::EmulatedTimeLimit; break; }
    if(options.wallSeconds && wallElapsed() >= options.wallSeconds) { reason = StopReason::WallTimeLimit; break; }
  }

  auto info = stopInfo(reason);
  stats.close();
  std::fflush(platform.output);
  std::fflush(stdout);
  std::fprintf(stderr, "n64-run: stop=%s frames=%llu emulated_s=%.6f wall_s=%.3f rdp=%s\n",
    info.name, (unsigned long long)frames, emulatedElapsed(), wallElapsed(), rdpModeName(options.rdp));
  if(options.rdp == RdpMode::Soft) {
    //host time inside the engine's render calls and the pixels it rasterized (ADR 0001 risk 1)
    auto& engine = N64::rdp.engine;
    std::fprintf(stderr, "n64-run: rdp_soft render_calls=%llu render_ms=%.3f pixels=%llu ns_per_pixel=%.2f\n",
      (unsigned long long)engine.renderCalls, engine.renderNanoseconds / 1e6,
      (unsigned long long)engine.pixels(),
      engine.pixels() ? (double)engine.renderNanoseconds / engine.pixels() : 0.0);
  }
  std::fflush(stderr);
  //Skip core teardown: the result is already written, and unloading joins host threads for no benefit.
  std::_Exit(info.exitCode);
}
