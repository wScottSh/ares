#!/usr/bin/env python3
"""Build timing-test.z64: borrow header+IPL3 (CIC 6105) from any retail-format ROM, load code at 0x80000400.

    mips-linux-gnu-as -march=vr4300 -mabi=32 -EB -o t.o timing-test.s
    mips-linux-gnu-ld -EB -Ttext=0x80000400 -e _start -o t.elf t.o
    mips-linux-gnu-objcopy -O binary -j .text t.elf t.bin
    python build-rom.py <donor.z64> t.bin timing-test.z64     # needs `pip install ipl3checksum`

Run: ares --setting Developer/HomebrewMode=true timing-test.z64  (IS-Viewer prints "Tn <Count delta hex>")
"""
import struct, sys, ipl3checksum
donor, code, out = sys.argv[1:4]
rom = bytearray(open(donor, "rb").read()[:0x1000])
rom[8:12] = struct.pack(">I", 0x80000400)
rom += open(code, "rb").read()
rom += b"\0" * (0x200000 - len(rom))
cic = ipl3checksum.detectCIC(bytes(rom[:0x101000]))
c1, c2 = ipl3checksum.calculateChecksum(bytes(rom), cic)
rom[0x10:0x18] = struct.pack(">II", c1, c2)
open(out, "wb").write(rom)
