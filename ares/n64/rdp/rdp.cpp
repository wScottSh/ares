#include <n64/n64.hpp>
#include <chrono>
#include <cstdarg>
extern "C" {
  #include "engine/rdp.h"
}

namespace ares::Nintendo64 {

RDP rdp;
#include "engine.cpp"
#include "io.cpp"
#include "debugger.cpp"
#include "serialization.cpp"

auto RDP::load(Node::Object parent) -> void {
  node = parent->append<Node::Object>("RDP");
  debugger.load(node);
}

auto RDP::unload() -> void {
  engine.unload();
  debugger = {};
  node.reset();
}

auto RDP::crash(const char *reason) -> void {
  debug(unusual, "[RDP] software triggered a hardware bug; RDP crashed and will stop responding. Reason: ", reason);
  command.crashed = 1;
  //guard against asynchronous reporting of crash state. We want the RDP to report that it's busy forever
  command.pipeBusy = 1;
  command.bufferBusy = 1;
}

auto RDP::main() -> void {
  constexpr Clock quantum = Timing::seconds(1);
  while(Thread::clock < cpu.clock) {
    step(quantum);
    command.clock += quantum.units / Timing::UnitsPerRclk;
  }
}

auto RDP::power(bool reset) -> void {
  Thread::reset();
  engine.unload();
  engine.load();
  command = {};
  io.bist = {};
  io.test = {};
  if(!reset) mapIdentityWarned = 0;
}

}
