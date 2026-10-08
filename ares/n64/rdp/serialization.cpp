auto RDP::serialize(serializer& s) -> void {
  Thread::serialize(s);

  s(dpc.start);
  s(dpc.end);
  s(dpc.current);
  s(dpc.endNext);
  s(dpc.startValid);
  s(dpc.endValid);
  s(dpc.xbus);
  s(dpc.freeze);
  s(dpc.flush);
  s(dpc.pipeBusy);
  s(dpc.startGclk);
  s(dpc.crashed);
  s(dpc.clockOrigin.units);
  for(auto counter : {&dpc.cmd, &dpc.pipe, &dpc.tmem}) {
    s(counter->since.units);
    s(counter->units);
    s(counter->on);
  }
  s(fetch.dwords);
  s(fetch.arrival.units);
  s(executor.busy);
  s(executor.load);
  s(executor.syncFull);
  s(executor.until.units);

  engine.serialize(s);

  //the memory interface (plan T13): bursts queued and in flight, the span
  //slots with their window bytes, the pipeline and stream positions, a TMEM load
  auto pending = [&](Pending& p) {
    s(p.address);
    s(p.bytes);
    s(p.write);
    s(p.slot);
    s(p.image);
    s(p.half);
  };
  for(auto* port : {&memory, &command, &fillPort}) {
    u32 queued = port->queue.size(), flying = port->flights.size();
    s(queued);
    s(flying);
    if(s.reading()) port->queue.resize(queued), port->flights.resize(flying);
    for(auto& p : port->queue) pending(p);
    for(auto& f : port->flights) pending(f.p), s(f.landAt.units);
    s(port->posted);
    s(port->freeAt.units);
    s(port->words);
  }
  for(auto& slot : slots) {
    s(std::span<u8>{(u8*)&slot.info, sizeof(slot.info)});
    for(auto* w : {&slot.color, &slot.depth}) {
      s(w->lo);
      s(w->hi);
      u32 bytes = w->hi > w->lo && w->hi - w->lo <= SpanBytes ? w->hi - w->lo : 0;
      s(std::span<u8>{w->data, bytes});
      s(std::span<u8>{w->hidden, bytes / 2});
      s(std::span<u8>{w->written, bytes});
    }
    s(slot.reads);
    s(slot.writes);
    s(slot.ready.units);
    s(slot.shaded);
  }
  s(pipe.time.units);
  s(pipe.wake.units);
  s(pipe.current);
  s(pipe.pixel);
  s(pipe.chunk);
  s(pipe.chunkEnd.units);
  s(pipe.chunkPixels);
  for(auto* st : {&pipe.color, &pipe.depth}) {
    s(st->position);
    s(st->halfStart);
    for(auto& h : st->halves) s(h.outstanding);
  }
  s(pipe.head);
  s(pipe.count);
  s(pipe.prefetched);
  s(pipe.lastPrimitive);
  s(pipe.lastWrite.units);
  s(pipe.lastSpanEnd.units);
  s(pipe.writes);
  s(tmemLoad.active);
  s(tmemLoad.reads);
  s(tmemLoad.ready.units);
  s(tmemLoad.count);
  if(tmemLoad.count > Load::Ranges) tmemLoad.count = 0;
  u32 offset = 0;
  for(u32 i : range(tmemLoad.count)) {
    auto& w = tmemLoad.windows[i];
    s(tmemLoad.ranges[i].lo);
    s(tmemLoad.ranges[i].hi);
    s(w.lo);
    s(w.hi);
    u32 bytes = w.hi - w.lo;
    if(s.reading()) {
      if(offset + bytes > LoadBytes) bytes = 0, w.hi = w.lo;
      w.data = tmemLoad.data + offset, w.hidden = tmemLoad.hidden + offset / 2, w.written = tmemLoad.written + offset;
    }
    s(std::span<u8>{w.data, bytes});
    s(std::span<u8>{w.hidden, bytes / 2});
    offset += bytes;
  }
  s(stat.busy);
  s(stat.pipe);
  s(stat.since.units);
  s(stat.on);

  s(io.bist.check);
  s(io.bist.go);
  s(io.bist.done);
  s(io.bist.fail);

  s(io.test.enable);
  s(io.test.address);
  for(auto& d : io.test.data) s(d);
  changed();
}
