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

  s(io.bist.check);
  s(io.bist.go);
  s(io.bist.done);
  s(io.bist.fail);

  s(io.test.enable);
  s(io.test.address);
  for(auto& d : io.test.data) s(d);
}
