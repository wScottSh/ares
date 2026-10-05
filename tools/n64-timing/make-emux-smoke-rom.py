#!/usr/bin/env python3
"""Builds a tiny ROM that prints one line through emux XLOG, then requests exit through
emux XIOCTL. It proves n64-run's guest-output and emux-exit paths without a toolchain.

Boot code comes from libdragon's ipl3_compat.z64 (public domain), which loads a flat
binary from ROM 0x1000 to the entry point in header word 0x8.

usage: make-emux-smoke-rom.py IPL3_COMPAT_Z64 OUT_Z64
"""
import struct
import sys

ENTRY = 0x80000400
MESSAGE = b"emux smoke: hello\n\0"


def cop0_co(rd, rt, code, funct):
    # Encoding from nemu64-test src/emux.rs (encode_xlog / encode_xioctl).
    return (0x10 << 26) | (0x10 << 21) | ((rd & 0x1F) << 20) | ((rt & 0x1F) << 15) | ((code & 0x1FF) << 6) | funct


def main():
    ipl3_path, out_path = sys.argv[1:3]
    ipl3 = bytearray(open(ipl3_path, "rb").read())
    if len(ipl3) != 0x1000 or ipl3[:4] != b"\x80\x37\x12\x40":
        sys.exit(f"{ipl3_path}: expected a 4 KiB big-endian ipl3_compat.z64")

    message_addr = ENTRY + 4 * 7
    code = [
        0x3C080000 | (message_addr >> 16),       # lui   $t0, hi(message)
        0x35080000 | (message_addr & 0xFFFF),    # ori   $t0, $t0, lo(message)
        cop0_co(8, 0, 0x0, 0x25),                # XLOG  $t0 (NUL-terminated string)
        cop0_co(0, 0, 0x1, 0x2C),                # XIOCTL exit
        0x08000000 | ((ENTRY + 4 * 4) >> 2 & 0x3FFFFFF),  # j . (spin until the host stops)
        0x00000000,                              # nop
        0x00000000,
    ]
    payload = b"".join(struct.pack(">I", word) for word in code) + MESSAGE
    payload += b"\0" * (-len(payload) % 0x1000)

    struct.pack_into(">I", ipl3, 0x8, ENTRY)
    struct.pack_into(">I", ipl3, 0x10, len(payload))
    with open(out_path, "wb") as out:
        out.write(bytes(ipl3) + payload)


if __name__ == "__main__":
    main()
