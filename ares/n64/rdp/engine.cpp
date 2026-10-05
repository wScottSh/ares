//cen64-jgemu pixel engine (engine/), synchronous on the emulation thread.
//Each DPC_END write renders the whole command range into rdram.ram and
//rdram.hidden before returning, and Sync_Full raises the DP interrupt
//through syncFull().

auto RDP::syncFull() -> void {
  if(!command.crashed) {
    mi.raise(MI::IRQ::DP);
    command.bufferBusy = 0;
    command.pipeBusy = 0;
  }
  command.startGclk = 0;
}

static auto engineInterrupt(void*) -> void {
  rdp.syncFull();
}

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
  if(rdp_render_init((u32*)rdram.ram.data, rdram.ram.size, rdram.hidden.data,
                     (u32*)rsp.dmem.data, regs, engineInterrupt, nullptr)) {
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

//DPC_STATUS bits the engine reads and may change (n64brew RDP registers).
namespace EngineStatus {
  enum : u32 { Source = 1 << 0, Freeze = 1 << 1, Flush = 1 << 2, Ready = 1 << 7, StartValid = 1 << 10 };
}

auto RDP::Engine::render() -> void {
  if(!loaded) return;
  auto& command = rdp.command;
  regs[RDP_DPC_START_REG]   = command.start;
  regs[RDP_DPC_END_REG]     = command.end;
  regs[RDP_DPC_CURRENT_REG] = command.current;
  regs[RDP_DPC_STATUS_REG]  = (command.source     ? EngineStatus::Source     : 0)
                            | (command.freeze     ? EngineStatus::Freeze     : 0)
                            | (command.flush      ? EngineStatus::Flush      : 0)
                            | (command.ready      ? EngineStatus::Ready      : 0)
                            | (command.startValid ? EngineStatus::StartValid : 0);

  auto start = std::chrono::steady_clock::now();
  rdp_process_list();
  renderNanoseconds += std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start).count();
  renderCalls++;

  u32 status = regs[RDP_DPC_STATUS_REG];
  command.current    = regs[RDP_DPC_CURRENT_REG];
  command.source     = (bool)(status & EngineStatus::Source);
  command.freeze     = (bool)(status & EngineStatus::Freeze);
  command.flush      = (bool)(status & EngineStatus::Flush);
  command.ready      = (bool)(status & EngineStatus::Ready);
  command.startValid = (bool)(status & EngineStatus::StartValid);
  if(rdp_render_crashed()) rdp.crash("pixel engine pipeline crash");
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
