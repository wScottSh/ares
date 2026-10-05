struct Accuracy {
  //enable all accuracy flags
  static constexpr bool Reference = 0;

  struct CPU {
    //exceptions when the CPU accesses unaligned memory addresses
    static constexpr bool AddressErrors = 1 | Reference;
  };

  struct RSP {
    //VU instructions
    static constexpr bool SISD = 0 | Reference | !ARCHITECTURE_SUPPORTS_SSE4_1;
    static constexpr bool SIMD = !SISD;
  };

  struct PIF {
    // Emulate a region-locked console
    static constexpr bool RegionLock = false;
    // Emulate the PIF's checksum security check
    static constexpr bool IPL2Checksum = true;
  };
};
