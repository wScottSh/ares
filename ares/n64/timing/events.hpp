//The console's scheduled events and the one timeline they live on.
//Declaration order is the tie-break among events at equal times.

enum class EventKind : u32 {
  VI_Line,        //one VI half-line: counters, VI interrupt, field boundary
  VI_Fetch,       //the next scanout burst of the output line is due
  AI_Sample,      //one DAC sample
  CPU_Compare,    //COP0 COUNT reaches COMPARE
  PIF_Poll,       //PIF HLE boot handshake poll
  PI_DMA_Read,
  PI_DMA_Write,
  PI_BUS_Write,
  SI_DMA_Read,
  SI_DMA_Write,
  SI_BUS_Write,
  RTC_Tick,
  EEPROM_Write,
  Flash_Complete,
  DD_Clock_Tick,
  DD_MECHA_Response,
  DD_BM_Request,
  DD_Motor_Mode,
  GDB_Poll,
};

extern Timing::Timeline timeline;

//timeline.cpp
auto fireEvent(const Timing::Timeline::Event&) -> void;
//Posts `kind` `delay` after now: the running event's time inside a handler,
//the CPU's time otherwise (every other poster is the CPU executing a store).
auto scheduleAfter(EventKind kind, Clock delay) -> void;
//Removes every pending event of `kind`; returns the latest of their times or Clock::never().
auto cancelEvent(EventKind kind) -> Clock;
