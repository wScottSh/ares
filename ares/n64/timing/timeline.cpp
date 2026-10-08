#include <n64/n64.hpp>

namespace ares::Nintendo64 {

Timing::Timeline timeline;

auto fireEvent(const Timing::Timeline::Event& event) -> void {
  switch((EventKind)event.kind) {
  case EventKind::VI_Line:           return vi.line();
  case EventKind::VI_Fetch:          return vi.fetchDue();
  case EventKind::AI_Sample:         return ai.sampleEvent();
  case EventKind::CPU_Compare:       return cpu.compareMatch();
  case EventKind::PIF_Poll:          return pif.mainHLE();
  case EventKind::PI_DMA_Read:       return pi.dmaStep();
  case EventKind::PI_DMA_Write:      return pi.dmaStep();
  case EventKind::PI_BUS_Write:      return pi.writeFinished();
  case EventKind::SI_DMA_Read:       return si.dmaStep();
  case EventKind::SI_DMA_Write:      return si.dmaStep();
  case EventKind::SI_BUS_Write:      return si.writeFinished();
  case EventKind::RTC_Tick:          return cartridge.rtc.tick();
  case EventKind::EEPROM_Write:      return cartridge.eepromFinish();
  case EventKind::Flash_Complete:    return cartridge.flash.finish();
  case EventKind::DD_Clock_Tick:     return dd.rtc.tickClock();
  case EventKind::DD_MECHA_Response: return dd.mechaResponse();
  case EventKind::DD_BM_Request:     return dd.bmRequest();
  case EventKind::DD_Motor_Mode:     return dd.motorChange();
  case EventKind::GDB_Poll:          return cpu.gdbPoll();
  }
}

auto scheduleAfter(EventKind kind, Clock delay) -> void {
  timeline.schedule({timeline.now(cpu.clock) + delay, (u32)kind});
}

auto cancelEvent(EventKind kind) -> Clock {
  return timeline.cancel((u32)kind);
}

}
