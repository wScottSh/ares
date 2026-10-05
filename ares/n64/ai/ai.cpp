#include <n64/n64.hpp>

namespace ares::Nintendo64 {

AI ai;
#include "io.cpp"
#include "debugger.cpp"
#include "serialization.cpp"

auto AI::load(Node::Object parent) -> void {
  node = parent->append<Node::Object>("AI");

  stream = node->append<Node::Audio::Stream>("AI");
  stream->setChannels(2);
  stream->setFrequency(44100.0);

  debugger.load(node);
}

auto AI::unload() -> void {
  debugger = {};
  node->remove(stream);
  stream.reset();
  node.reset();
}

auto AI::sampleEvent() -> void {
  if(!sample()) stream->frame(dac.left, dac.right);
  Thread::clock = dac.vclk.advance(dac.vclksPerSample);
  timeline.schedule({Thread::clock, (u32)EventKind::AI_Sample});
}

//The DAC has no sample RAM: the AI reads ai.fetch-bytes (two stereo samples)
//from RDRAM per request (n64brew Audio_Interface; US 6,166,748), as an RI bus
//client. The registers advance at the sample times as before; the pair's two
//output frames go to the host stream when its read lands.
//Returns whether the sample came from DMA (its frame is emitted at the grant).
auto AI::sample() -> bool {
  bool active = false;

  if(io.dmaCount && io.dmaLength[0] && io.dmaEnable) {
    io.dmaAddress[0].bit(13,23) += io.dmaAddressCarry;
    if(io.dmaLength[0] % Timing::Behavior::AiFetchBytes == 0) {
      ri.post({(u32)io.dmaAddress[0], (u8)Timing::Behavior::AiFetchBytes, RiBus::Direction::Read, RiBus::Requester::AiDma, 0}, Thread::clock);
    }

    io.dmaAddress[0].bit(0,12) += 4;
    io.dmaAddressCarry = io.dmaAddress[0].bit(0,12) == 0;
    io.dmaLength[0] -= 4;
    active = true;
  }

  if(io.dmaCount && io.dmaLength[0] == 0) {
    if(--io.dmaCount) {
      io.dmaAddress[0]  = io.dmaAddress[1];
      io.dmaLength[0]   = io.dmaLength[1];
      io.dmaOriginPc[0] = io.dmaOriginPc[1];
      mi.raise(MI::IRQ::AI);
    }
  }

  if(!active) {
    dac.left  *= dac.decayFactor;
    dac.right *= dac.decayFactor;
    if(fabs(dac.left)  < 1e-7) dac.left  = 0.0;
    if(fabs(dac.right) < 1e-7) dac.right = 0.0;
  }
  return active;
}

auto AI::Fetch::buffer(const RiBus::Burst&) -> void* {
  return bytes;
}

auto AI::Fetch::granted(const RiBus::Grant& g) -> void {
  for(u32 i = 0; i < g.burst.bytes; i += 4) {
    ai.dac.left  = (s16)(bytes[i + 0] << 8 | bytes[i + 1]) / 32768.0;
    ai.dac.right = (s16)(bytes[i + 2] << 8 | bytes[i + 3]) / 32768.0;
    ai.stream->frame(ai.dac.left, ai.dac.right);
  }
}

auto AI::updateDecay() -> void {
  dac.decayFactor = exp(-1.0 / (dac.frequency * 0.003));
}

auto AI::power(bool reset) -> void {
  Thread::reset();
  io = {};
  dac.left  = 0.0;
  dac.right = 0.0;
  dac.frequency = 44100;
  dac.precision = 16;
  //The power-on rate is a whole VCLK divider too: the one nearest above 44100 Hz.
  dac.vclksPerSample = system.videoFrequency() / dac.frequency;
  dac.vclk = {system.vclkPeriod()};
  updateDecay();
  ri.attach(RiBus::Requester::AiDma, &fetch);
  timeline.schedule({Thread::clock, (u32)EventKind::AI_Sample});
}

}
