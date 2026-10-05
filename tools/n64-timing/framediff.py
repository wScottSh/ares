#!/usr/bin/env python3
"""Compare two n64-run --dump-frame PPMs and attribute the differences.

Usage: framediff.py A.ppm B.ppm [--tile N] [--threshold T] [--out DIFF.png]

Prints the number of differing pixels, the largest absolute channel
difference, and the differing tiles (default 32 px) with their bounding
box, differing-pixel count and mean absolute channel difference, so a
region can be matched to a draw call or a renderer behavior. A pixel
differs when any channel differs by more than --threshold (default 0,
so the 5-bit expansion in both dumps cancels). --out writes a PNG that
marks differing pixels red over A, when Pillow is installed.
"""
import argparse
import sys


def read_ppm(path):
    with open(path, 'rb') as fp:
        data = fp.read()
    fields = []
    pos = 0
    while len(fields) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b'#':
            while data[pos:pos + 1] not in (b'\n', b''):
                pos += 1
            continue
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    pos += 1
    if fields[0] != b'P6' or fields[3] != b'255':
        sys.exit(f'{path}: not an 8-bit P6 PPM')
    width, height = int(fields[1]), int(fields[2])
    pixels = data[pos:pos + width * height * 3]
    if len(pixels) != width * height * 3:
        sys.exit(f'{path}: truncated')
    return width, height, pixels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('a')
    parser.add_argument('b')
    parser.add_argument('--tile', type=int, default=32)
    parser.add_argument('--threshold', type=int, default=0)
    parser.add_argument('--out')
    args = parser.parse_args()

    wa, ha, pa = read_ppm(args.a)
    wb, hb, pb = read_ppm(args.b)
    if (wa, ha) != (wb, hb):
        sys.exit(f'size mismatch: {wa}x{ha} vs {wb}x{hb}')

    tiles = {}
    differing = 0
    maxdiff = 0
    mask = bytearray(wa * ha)
    for y in range(ha):
        row = y * wa * 3
        for x in range(wa):
            i = row + x * 3
            d = max(abs(pa[i] - pb[i]), abs(pa[i + 1] - pb[i + 1]), abs(pa[i + 2] - pb[i + 2]))
            if d <= args.threshold:
                continue
            differing += 1
            maxdiff = max(maxdiff, d)
            mask[y * wa + x] = 1
            key = (y // args.tile, x // args.tile)
            t = tiles.setdefault(key, [x, y, x, y, 0, 0])
            t[0] = min(t[0], x)
            t[1] = min(t[1], y)
            t[2] = max(t[2], x)
            t[3] = max(t[3], y)
            t[4] += 1
            t[5] += d

    print(f'{args.a} vs {args.b}: {differing} of {wa * ha} pixels differ '
          f'({100.0 * differing / (wa * ha):.2f}%), max channel diff {maxdiff}, '
          f'{len(tiles)} tiles of {args.tile} px')
    for (ty, tx), (x0, y0, x1, y1, count, total) in sorted(tiles.items()):
        print(f'  tile ({tx},{ty}) box x{x0}-{x1} y{y0}-{y1}: {count} px, mean diff {total / count:.1f}')

    if args.out:
        try:
            from PIL import Image
        except ImportError:
            sys.exit('--out needs Pillow')
        marked = bytearray(pa)
        for n in range(wa * ha):
            if mask[n]:
                marked[n * 3:n * 3 + 3] = b'\xff\x00\x00'
        Image.frombytes('RGB', (wa, ha), bytes(marked)).save(args.out)
    return 0 if differing == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
