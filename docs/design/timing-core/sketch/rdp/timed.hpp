//The RDP as a time-stepped device whose memory traffic is its pixel data.
//
//One engine produces both pixels and timing. Pixel arithmetic is a C++ port
//of the cen64-jgemu RDP (src/rdp at 2f8d7bc, BSD-3-Clause, MAME lineage,
//fitted to snapper64 console captures); it never touches rdram.ram. Every
//byte it reads or writes moves through an RI grant:
//
//  command fetch   DpCommand burst  -> CommandFifo      (DPC_CURRENT advances)
//  span prefetch   DpColor/DpDepth  -> SpanSnapshot     (filled at grant time)
//  shading         SpanSnapshot + TMEM -> SpanRam half  (at pipeline time)
//  write-back      SpanRam half     -> DpColor/DpDepth bursts, one per
//                                      contiguous written run
//  TMEM load       DpTexture burst  -> Z half staging   -> TMEM
//  fill            DpFill bursts, direct from a fill-word buffer
//
//Consequences that fall out of the structure instead of being special-cased:
//  - write traffic depends on per-pixel results through the run count
//    (rdp-write-granularity.md), because runs are cut from the written mask;
//  - span-buffer coherency hazards (SDK 12.2.3) appear when a prefetch is
//    granted before an overlapping write-back, and G_PM_1PRIMITIVE removes
//    them by ordering, as on hardware (1prim-cost.md);
//  - a CPU or RSP read of the framebuffer sees exactly the runs granted
//    before it; no GPU thread, no SyncFull wait, no host timing.
//
//paraLLEl-RDP and the Vulkan path are removed from the N64 core (T10).

namespace ares::Nintendo64::RDPTimed {

using Timing::Clock;

//---- front end (rsp-rdp-fifo.md rows 9-13) -------------------------------

//Pure transition functions on a value type, unit-tested without a timeline
//(tools/n64-timing/tests/dpc-regs.cpp against n64-systemtest tests/rdp).
struct Dpc {
  n24 start, end, current;
  n24 endNext;
  n1  startValid;   //START written, not yet consumed
  n1  endPending;   //END written while a transfer was active (END_VALID)
  n1  xbus, freeze, flush;
  n1  transferActive;
  //Counters are functions of time, settled on read or on a state change.
  Clock clockEpoch;
  Clock cmdBusySince, pipeBusySince, tmemBusyAccum;
  //  DPC_START write: latch iff !startValid; startValid = 1
  //  DPC_END write:
  //    !startValid               -> end = v (extend), fetch may resume
  //    startValid && !active     -> current = start, end = v, startValid = 0
  //    startValid && active      -> endNext = v, endPending = 1; swap when
  //                                 current reaches end
  //  STATUS read: DMA_BUSY = a fetch burst pending; CMD_BUSY = fifo or
  //    executor busy; PIPE_BUSY = first DMA since reset until SYNC_FULL
  //    retires; TMEM_BUSY = a load in progress and GCLK on; START_GCLK = pipe
  //    started and not yet synced; END_VALID = endPending.
  auto write(u32 reg, u32 value, Clock at) -> void;
  auto read(u32 reg, Clock at) const -> u32;
};

struct CommandFifo {
  u64 words[Timing::Behavior::RdpCmdFifoDwords];
  u8  head = 0, count = 0;
  auto room() const -> u32;
};

//Posts DpCommand bursts (naming a slot in the fifo) while room > 0 and
//current < end; XBUS mode reads DMEM over the private X bus instead (no RI
//traffic), after timeline.catchUp(t, RDP) so DMEM is current.
struct CommandFetch : RI::Client {
  auto granted(const RI::Grant&) -> void override;  //count += words, current += bytes
};

//---- geometry -------------------------------------------------------------

//Everything about a primitive that is fixed when the command processor
//dispatches it. Attribute changes after dispatch do not reach it; the
//unsynced-attribute stage offsets (rdp-command-timing.md s.3.7) are T15,
//which replaces this snapshot with per-stage sampling.
struct Primitive {
  u8  cycleType;      //1-cycle, 2-cycle, copy, fill
  u1  imageRead, zCompare, zUpdate, atomic;
  u8  colorBpp;
  u32 colorBase, depthBase;
  u16 colorWidth;
  u16 firstSpan, spanCount;
};

//One scanline of one primitive, from the edge walker. Extents depend only on
//the command and scissor (rdp-pixel-timing-coupling.md), so all spans of a
//primitive are computed at dispatch; pixels are not.
struct Span {
  s16 y;
  s16 xStart, xEnd;     //inclusive pixel range after scissor
  u16 streamStart;      //position S of the first pixel (span-ram.md row 3)
};

//The pipeline's unit of work: the stream positions of one span that fall in
//one span-RAM half. Stalls (GCLK off) can occur only between segments.
struct Segment {
  u16 span;
  u16 firstPosition;
  u8  positions;
  u1  half;
};

//---- memory interface -------------------------------------------------------

//Bytes of one span row as the RI delivered them at grant time, color or Z,
//including hidden bits. The Burst names `bytes`/`hidden` as its data.
struct SpanSnapshot {
  u8   bytes[640 * 4];
  u8   hidden[640];
  u16  span;
  RI::Ticket ticket;
  Clock ready;  //Grant::complete
};

//Two halves per image, alternating every N stream positions
//(span-ram.md rows 3-6). A half is Free, Filling (pipeline writing pixels),
//or Draining (write-back bursts outstanding). The pipeline stalls when the
//next segment's half is not Free or its span's snapshot is not ready.
struct SpanRamHalf {
  enum class State : u8 { Free, Filling, Draining } state;
  u8    pixels[64];
  u8    hidden[64];
  u64   writtenMask;   //one bit per byte, from the pixel engine
  u16   span;
  u8    outstanding;   //write-back bursts not yet granted
  Clock freeAt;
};

//Contiguous written byte ranges of a half, split at 128 B and 2 KiB rows,
//become one Wseq burst each (data pointing into `pixels`, trims from the mask
//edges); a fully rejected half posts nothing.
auto writeRuns(const SpanRamHalf&, u32 rowAddress, auto&& post) -> void;

//---- pixels -----------------------------------------------------------------

//Hardware noise: three LFSRs (deg 29/28/27) from all-ones at reset, one step
//per RDP clock including stalls, c one step ahead (rdp-noise.md). State is a
//function of the RDP clock count; advancing a gap uses GF(2) jump tables so
//idle time costs nothing. This replaces the port's seeded hash
//(cen64-jgemu rdp_core.c:58-89, which is paraLLEl's noise.h), T14.
struct NoiseLfsr {
  u32 a, b, c;
  u64 atClock;
  auto at(u64 rdpClock) -> u32;  //9-bit combiner NOISE value
};

struct SegmentResult {
  u64 colorWritten;  //byte mask within the half
  u64 depthWritten;
  u32 pipelineClocks;
};

//The ported renderer. Every site that touches m_rdram in the source is
//rewritten to read snapshots or staging and write halves: rdp_read_pixel*,
//rdp_write_pixel*, rdp_z_compare, rdp_z_store (rdp_core.c:1127-1300,
//5723-5940), the TMEM load source reads (about 4069-4410), read_rdram_pair
//(1392) and the rect pre-state restore (4638). T9 lists every site; T13
//redirects every one; the compile-time private accessor catches a miss.
//Nothing else in it knows about time. Edge walking is its rdp_render_spans
//extent computation, unchanged.
struct PixelEngine {
  auto dispatch(const u64* command, u32 words, Primitive&, vector<Span>&) -> void;
  auto shade(const Primitive&, const Span&, const Segment&,
             const SpanSnapshot* color, const SpanSnapshot* depth,
             SpanRamHalf* colorOut, SpanRamHalf* depthOut,
             NoiseLfsr&, u64 firstPixelClock) -> SegmentResult;
  //TMEM loads: plan the RDRAM rows (DpTexture bursts into the Z half), then
  //apply the staged bytes into tmem at the load's TMEM clocks.
  auto planLoad(const u64* command, auto&& post) -> u32;   //returns TMEM clocks
  auto applyLoad(const u8* staged, u32 bytes) -> void;
  u8 tmem[4096];
};

//---- the actor --------------------------------------------------------------

struct RDP : Timing::Actor, RI::Client {
  Clock time;   //RDP clock position of the pipeline (GCLK-gated work + stalls)

  //DpColor/DpDepth reads: the snapshot is already filled; mark it ready.
  //Writes: one fewer outstanding on the half; free it after the last.
  //DpTexture: staged bytes arrived; apply when all rows are in.
  //DpFill: nothing to do beyond accounting.
  auto granted(const RI::Grant&) -> void override;

  //Parked when idle (fifo empty, no transfer, nothing in flight); Blocked
  //when the next segment waits for a snapshot or a half; else Runnable.
  auto readiness() const -> Timing::Readiness override;

  //Processes the earliest internal event:
  //  command processor: decode the fifo head; setters cost RdpSetter, syncs
  //    RdpSync*, primitives RdpPrimitiveBase then dispatch spans; a primitive
  //    may dispatch once the previous one's last segment entered the pipe
  //    (no drain), unless the previous one was atomic (barrier + RdpAtomicDead
  //    after its last write-back);
  //  prefetch: post color/Z reads for spans up to `prefetchLead` ahead of the
  //    pipe (SDK 12.2.3: the next span is prefetched into another buffer);
  //  pipe: run the next Segment through PixelEngine::shade at `time`, advance
  //    time by its pipelineClocks, then write back a half that is full or
  //    whose span or primitive ended;
  //  SYNC_FULL: retires when every half is Free and every write-back granted;
  //    raises MI DP at that time and stops PIPE_BUSY.
  auto step(Clock limit) -> void override;

  Dpc          dpc;
  CommandFifo  fifo;
  CommandFetch fetch;
  PixelEngine  pixels;
  NoiseLfsr    noise;
  SpanRamHalf  color[2], depth[2];
  vector<SpanSnapshot> snapshots;  //ring, prefetchLead + 1 deep per image
  vector<Span> spans;              //current and next primitive
  u64          fillWords[16];      //DpFill burst source
};

}
