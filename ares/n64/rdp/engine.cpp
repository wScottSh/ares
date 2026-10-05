//cen64-jgemu pixel engine (engine/), synchronous on the emulation thread.
//Each DPC_END write renders the whole command range into rdram.ram and
//rdram.hidden before returning, and Sync_Full raises the DP interrupt
//through syncFull() the way the paraLLEl path does.

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

//rdram.hidden.data is assigned when the Vulkan module loads on the first
//System::run, after power(), so the engine attaches lazily from render().
auto RDP::Engine::load() -> void {
  if(loaded) return;
  if(rdp_render_init((u32*)rdram.ram.data, rdram.ram.size, rdram.hidden.data,
                     (u32*)rsp.dmem.data, regs, engineInterrupt, nullptr)) {
    debug(unusual, "[RDP engine] init failed; no pixels will be drawn");
    enable = false;
    return;
  }
  rdp_render_set_log(engineLog);
  loaded = true;
}

auto RDP::Engine::unload() -> void {
  if(loaded) rdp_render_destroy();
  loaded = false;
}

auto RDP::Engine::render() -> void {
  auto& command = rdp.command;
  regs[RDP_DPC_START_REG]   = command.start;
  regs[RDP_DPC_END_REG]     = command.end;
  regs[RDP_DPC_CURRENT_REG] = command.current;
  regs[RDP_DPC_STATUS_REG]  = command.source << 0 | command.freeze << 1 | command.flush << 2;

  auto start = std::chrono::steady_clock::now();
  rdp_process_list();
  renderNanoseconds += std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start).count();
  renderCalls++;

  command.current = regs[RDP_DPC_CURRENT_REG];
  if(rdp_render_crashed()) rdp.crash("pixel engine pipeline crash");
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
