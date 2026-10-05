//The VR4300's external port: the 4-entry write (flush) buffer and the SysAD
//bus to the RCP, as one in-order queue (R4300i datasheet p.9: the flush
//buffer carries reads too; one read pending at a time, NEC s.12.6.2).
//
//Every CPU access that leaves the caches goes through here, so the three
//rules below hold by construction instead of by convention at 55 step()
//call sites (ares-timing-architecture.md obstacle 3):
//  - a read waits behind every older buffered write (vr4300-wb.md),
//  - a dirty D-miss reads its fill first and writes the victim after
//    (NEC s.12.5.2-12.5.3),
//  - a posted register write takes effect when it drains, not when the
//    store executes. A write to SP_STATUS halts the RSP at drain time.

namespace ares::Nintendo64 {

using Timing::Clock;

enum class SysADTarget : u8 { Rdram, RcpRegister, PiBus, PifRam };

struct SysAD : Timing::Actor, RI::Client {
  struct Entry {
    enum class Kind : u8 { Write, BlockWrite, Read, Fill } kind;
    SysADTarget target;
    u32 address;
    u8  bytes;
    u8  data[16];         //BlockWrite carries a 16 B line; the RI reads from here
    u8* destination;      //Read/Fill: where the CPU wants the data; the RI writes here
    Clock enqueued;
  };

  //CPU side. Every call takes the pipeline's DC time and returns the time the
  //pipeline may continue; the pipeline freezes until then.

  //Posted store. Returns `at` when a slot is free; otherwise the time a slot
  //frees. Release rule ("has a space", NEC s.4.9, vs "emptied", R4300i p.9)
  //is behavior `cpu.wb-release`; both give the same throughput.
  auto store(u32 address, u8 bytes, u64 data, Clock at) -> Clock;

  //Uncached load or fill. Enqueues behind older writes, then waits for the
  //data through timeline.await(). The CPU is the only actor that blocks in a
  //call, and only here.
  auto read(u32 address, u8 bytes, u8* destination, Clock at) -> Clock;
  auto fill(u32 address, u8* line, u8 bytes, Clock at) -> Clock;

  //Dirty victim of the miss just filled: two entries, queued after the fill.
  auto writeback(u32 address, const u8 line[16], Clock at) -> void;

  //Timing::Actor: drains the head entry when its issue time is reached.
  //  Rdram:        post a CpuSysAD burst naming the entry's bytes; Blocked
  //                until granted
  //  RcpRegister:  timeline.catchUp(t, SysAD); device.readWord/writeWord at t;
  //                done at t + sysad.rcp-register-path
  //  PiBus/PifRam: hand to the PI/SI bus model, which owns BSD/PIF timing
  auto readiness() const -> Timing::Readiness override;
  auto step(Clock limit) -> void override;

  //RI::Client: the bytes have moved; record completion and pop the entry.
  auto granted(const RI::Grant&) -> void override;

private:
  Entry queue[6];  //4 write entries + 1 read + the fill's victim pair
  u8    head = 0, count = 0;
  u8    writeEntriesUsed = 0;
};

extern SysAD sysad;

}
