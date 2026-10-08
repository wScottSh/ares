auto VI::serialize(serializer& s) -> void {
  Thread::serialize(s);

  s(io.colorDepth);
  s(io.gammaDither);
  s(io.gamma);
  s(io.divot);
  s(io.serrate);
  s(io.antialias);
  s(io.dedither);
  s(io.reserved);
  s(io.dramAddress);
  s(io.width);
  s(io.coincidence);
  s(io.hsyncWidth);
  s(io.colorBurstWidth);
  s(io.vsyncWidth);
  s(io.colorBurstHsync);
  s(io.halfLinesPerField);
  s(io.quarterLineDuration);
  s(io.leapPattern);
  s(io.hsyncLeap);
  s(io.hend);
  s(io.hstart);
  s(io.vend);
  s(io.vstart);
  s(io.colorBurstEnd);
  s(io.colorBurstStart);
  s(io.xscale);
  s(io.xsubpixel);
  s(io.yscale);
  s(io.ysubpixel);
  s(io.vcounter);
  s(io.field);
  s(io.leapCounter);

  s(vclk.origin.units);
  s(vclk.vclks);
  s(inactiveCounter);

  s(fetch.hsync.origin.units);
  s(fetch.hsync.vclks);
  s(fetch.origin);
  s(fetch.pitch);
  s(fetch.line);
  s(fetch.hstart);
  s(fetch.hend);
  s(fetch.output);
  s(fetch.next);
  s(fetch.inFlight);
  s(fetch.due);
  s(fetch.bytes);
  if(s.reading()) {
    fetch.hsync.period = system.vclkPeriod();
    fetch.start(fetch.origin, fetch.pitch);
  }
}
