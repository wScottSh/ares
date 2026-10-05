//cen64-jgemu pixel engine (engine/), synchronous on the emulation thread.
//RDP::dispatch (timed.cpp) feeds it one command at a time; each dispatch
//leaves its pixels in rdram.ram and rdram.hidden before returning.

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
  if(rdp_render_init((u32*)rdram.ram.data, rdram.ram.size, rdram.hidden.data, (u32*)rsp.dmem.data)) {
    debug(unusual, "[RDP engine] init failed; no pixels will be drawn");
    return;
  }
  rdp_render_set_log(engineLog);
  loaded = true;
}

auto RDP::Engine::unload() -> void {
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
