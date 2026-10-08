//cen64-jgemu pixel engine (engine/), on the emulation thread. RDP::dispatch
//(timed.cpp) feeds it one command at a time; its spans and loads run when the
//memory interface has their bytes (plan T13). It holds no view of RDRAM.

static auto engineLog(int level, const char* format, ...) -> void {
  char buffer[512];
  va_list arguments;
  va_start(arguments, format);
  vsnprintf(buffer, sizeof buffer, format, arguments);
  va_end(arguments);
  if(auto length = strlen(buffer); length && buffer[length - 1] == '\n') buffer[length - 1] = 0;
  if(level >= CEN64_LOG_WRN) debug(unusual, "[RDP engine] ", buffer);
}

auto RDP::Engine::load() -> void {
  if(rdp_render_init(rdram.installed(), Timing::Behavior::RdpPipelineDepth.units / Timing::UnitsPerRclk)) {
    debug(unusual, "[RDP engine] init failed; no pixels will be drawn");
    return;
  }
  rdp_render_set_log(engineLog);
  loaded = true;
}

auto RDP::Engine::unload() -> void {
  if(loaded && rdp_render_mem_misses()) debug(unusual, "[RDP engine] ", rdp_render_mem_misses(), " accesses outside the memory windows");
  if(loaded) rdp_render_destroy();
  loaded = false;
}

auto RDP::Engine::serialize(serializer& s) -> void {
  auto io = [](void* context, void* data, size_t size) {
    (*(serializer*)context)(std::span<u8>{(u8*)data, size});
  };
  rdp_render_serialize(io, &s, s.reading());
}

auto RDP::Engine::dpsArm() -> void {
  rdp_render_dps_arm();
}

auto RDP::Engine::dpsTake(u32 words[32]) -> bool {
  return rdp_render_dps_take(words) != 0;
}

auto RDP::Engine::pixels() -> u64 {
  return rdp_render_pixel_count();
}

auto RDP::Engine::colorImage() -> u32 {
  return rdp_render_color_image();
}

auto RDP::Engine::maskImage() -> u32 {
  return rdp_render_mask_image();
}

auto RDP::Engine::tmem() -> u8* {
  return rdp_render_tmem();
}
