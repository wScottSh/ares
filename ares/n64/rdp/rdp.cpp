#include <n64/n64.hpp>
#include <chrono>
#include <cstdarg>

namespace ares::Nintendo64 {

RDP rdp;
#include "engine.cpp"
#include "timed.cpp"
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
  dpc.crashed = 1;
}

auto RDP::power(bool reset) -> void {
  Thread::reset();
  engine.unload();
  engine.load();
  dpc = {};
  fetch = {};
  executor = {};
  pipe = {};
  tmemLoad.active = false;
  tmemLoad.count = tmemLoad.reads = 0;
  for(auto& port : ports) port.queue.clear(), port.posted = port.landed = false;
  fillPort.queue.clear(), fillPort.posted = fillPort.landed = false;
  for(auto& slot : slots) slot.reads = slot.writes = 0, slot.shaded = false;
  for(auto& port : ports) ri.attach(port.requester, &port);
  ri.attach(fillPort.requester, &fillPort);
  io.bist = {};
  io.test = {};
  if(!reset) mapIdentityWarned = 0;
  timeline.attach(Timing::ActorId::RDP, this);
}

}
