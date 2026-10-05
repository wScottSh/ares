//Fully scheduled devices. Their future is known from their registers, so
//they are timeline events plus bus clients, never stepped actors.

namespace ares::Nintendo64 {

using Timing::Clock;

enum class EventKind : u32 {
  //order = tie-break among events at the same time
  ViHsync,         //posts the Refresh request; schedules the line's fetches
  ViFetch,         //one 128 B burst of the current output line
  ViLineEnd,       //composes the output line from its fetched bytes
  ViInterrupt,     //V_CURRENT == V_INTR
  AiSample,        //DAC needs the next 8 B
  CountCompare,    //COUNT reaches COMPARE (TimedCp0::compareCrossing)
  PiBlock,         //PI buffer filled from the cart bus; post its RDRAM write
  SiTransfer,      //PIF joybus phase done
  Count,
};

//VI (vi-fetch.md). Per active output line, from H_START:
//  ViLinesPerOutputLine lines x ceil(width * bpp / ViBurstBytes) bursts,
//  spaced evenly across the active window, addresses ORIGIN + (y+k)*stride.
//At HSYNC one Refresh request (rank 0). Line timing uses VclkAccumulator.
//Each burst names its slot in `lines`; the RI fills it at grant time, so the
//displayed image is RDRAM as the VI read it (tearing included). The filter is
//ares's existing software VI path, fed from these line buffers. An underrun
//(a line composed before its last burst was granted) increments a counter
//that the stats report; it never changes emulated state.
struct ViFetch : RI::Client {
  u8  lines[3][1152 * 4];  //widest MM mode is the 576-px notebook
  u8  hidden[3][1152];
  u64 underruns = 0;
  auto granted(const RI::Grant&) -> void override;
};

//AI: no sample RAM; an 8 B read per two stereo samples at VCLK/(DACRATE+1),
//through VclkAccumulator (fixes the +33 ppm truncation, clocks.md).
struct AiDma : RI::Client {
  u8 sample[8];
  auto granted(const RI::Grant&) -> void override;
};

//PI DMA (dma-timing.md): block by block. Each <= 128 B block, clipped at the
//2 KiB RDRAM row, fills from the cart bus at BSD timing
//(page 14+LAT+1, halfword PWD+1+RLS+1), then posts one RDRAM write burst
//naming the block buffer; its bytes land at grant time. PI_DRAM_ADDR and
//PI_CART_ADDR advance per block. The IRQ fires after the last block's grant
//completes.
struct PiDma : RI::Client {
  u8 block[128];
  auto granted(const RI::Grant&) -> void override;
};

//SI DMA: PIF timing from the existing estimate (si/io.cpp, pif/hle.cpp),
//RDRAM side as one 64 B burst (US 6,166,748 "64-byte").
struct SiDma : RI::Client {
  u8 block[64];
  auto granted(const RI::Grant&) -> void override;
};

}
