"""Kit points for the tex kit ROM (sets.py KITS["kit-tex"]): builders follow the bench convention
(suites/bench/benches.py Rom.point), kernels the bench kernel convention (asm.py).

Texture command encodings follow n64brew Reality_Display_Processor/Commands (Set Texture Image,
Set Tile, Set Tile Size, Load Block, Load Tile, Texture Rectangle) and agree with the fork's decoders
(ares/n64/rdp/engine/rdp_core.c rdp_cmd_set_tile, rdp_cmd_load_block, rdp_cmd_tex_rect_common).
"""
from ... import rcp
from ...suite import Step, Value
from ..bench.benches import KSEG1, LIST_BUF, COLOR_IMAGE, VI_OFF, RDP_EXTRA, Rom, emit_step, rdp_point

TEX_SRC = 0x00780000     # bank 7, past a 320x240 32 bpp COLOR_IMAGE; load sources (contents unused)
PAT_BUF = 0x00788000     # bank 7, the texel patterns of PATTERNS
Z_BUF = 0x00790000       # bank 7

FMT_RGBA, SIZ_16, SIZ_32 = 0, 2, 3
LOAD_TILE = 7
S10_ONE = 1 << 10        # s5.10 1.0 (Texture Rectangle DsDx/DtDy)
CD_BAYER = 1 << 6
ZMODE_DEC = 3 << 10
BL_P_BLEND = (2 << 30) | (2 << 28)   # blender m1a, cycles 0 and 1 = blend color
TEXEL0, COMBINED, PRIM = 1, 0, 3


def set_texture_image(addr, width, siz=SIZ_16, fmt=FMT_RGBA):
    return rcp._op(0x3D, rcp._f(fmt, 3, 21) | rcp._f(siz, 2, 19) | rcp._f(width - 1, 10, 0), addr)


def set_tile(tile, line, tmem, siz=SIZ_16, fmt=FMT_RGBA, mask_s=0):
    return rcp._op(0x35, rcp._f(fmt, 3, 21) | rcp._f(siz, 2, 19) | rcp._f(line, 9, 9) | rcp._f(tmem, 9, 0),
                   rcp._f(tile, 3, 24) | rcp._f(mask_s, 4, 4))


def _tile_rect(code, tile, sl, tl, sh, th):
    return rcp._op(code, rcp._f(sl, 12, 12) | rcp._f(tl, 12, 0),
                   rcp._f(tile, 3, 24) | rcp._f(sh, 12, 12) | rcp._f(th, 12, 0))


def set_tile_size(tile, sl, tl, sh, th):
    """10.2 texel coordinates."""
    return _tile_rect(0x32, tile, sl, tl, sh, th)


def load_block(tile, texels, dxt=0):
    """sh is the last texel index (integer); dxt (1.11) only places odd lines, not the load's length."""
    return _tile_rect(0x33, tile, 0, 0, texels - 1, dxt)


def load_tile(tile, width, height):
    return _tile_rect(0x34, tile, 0, 0, (width - 1) * 4, (height - 1) * 4)


def texture_rectangle_frac(tile, xh, yh, xl, yl, dsdx, dtdy, s=0, t=0):
    """Two command words: the rectangle (10.2 screen coordinates), then S, T (s10.5) and DsDx, DtDy (s5.10)."""
    return [rcp._op(0x24, rcp._f(xl, 12, 12) | rcp._f(yl, 12, 0),
                    rcp._f(tile, 3, 24) | rcp._f(xh, 12, 12) | rcp._f(yh, 12, 0)),
            rcp._f(s, 16, 48) | rcp._f(t, 16, 32) | rcp._f(dsdx, 16, 16) | rcp._f(dtdy, 16, 0)]


def combine_d(d0, ad0, d1, ad1):
    """(A - B) * C + D with A, B, C zero in both cycles: the output is D."""
    hi = (15 << 20) | (31 << 15) | (7 << 12) | (7 << 9) | (15 << 5) | 31
    lo = ((15 << 28) | (15 << 24) | (7 << 21) | (7 << 18) | (d0 << 15) | (7 << 12) | (ad0 << 9)
          | (d1 << 6) | (7 << 3) | ad1)
    return rcp.set_combine_raw(hi << 32 | lo)


PASS, FAIL = 0xF801, 0xF800     # RGBA5551 red; the copy pipe's 16 bpp alpha compare tests bit 0
PAT_TEXELS = 64
PAT_LINE = 2 * PAT_TEXELS // 8
PATTERNS = {
    "pass": [PASS] * PAT_TEXELS,
    "fail": [FAIL] * PAT_TEXELS,
    "word": ([PASS] * 4 + [FAIL] * 4) * (PAT_TEXELS // 8),
    "texel": [PASS, FAIL] * (PAT_TEXELS // 2),
    "blue": [0x003F] * PAT_TEXELS,
}
PAT_ADDR = {name: PAT_BUF + i * 2 * PAT_TEXELS for i, name in enumerate(PATTERNS)}


def pattern_write(suite):
    texels = [t for pat in PATTERNS.values() for t in pat]
    words = [(a << 16) | b for a, b in zip(texels[0::2], texels[1::2])]
    return Step("bench_list_step", [suite.blob(words), len(words), 0, 0, 0, 0, 0, KSEG1 | PAT_BUF], 0)


def load_pattern(name, tile, tmem):
    """A 64-texel RGBA16 row into TMEM at `tmem` words, and `tile` reading it with S wrapping at 64."""
    return [set_texture_image(PAT_ADDR[name], PAT_TEXELS), set_tile(LOAD_TILE, 0, tmem),
            load_block(LOAD_TILE, PAT_TEXELS), set_tile(tile, PAT_LINE, tmem, mask_s=6),
            set_tile_size(tile, 0, 0, (PAT_TEXELS - 1) * 4, 0)]


HASH_EXTRA = RDP_EXTRA + ["hash", "changed", "tail"]


def hash_point(rom, point, cmds, consts, surf_bytes, cmp_bytes, z_bytes=0, pre=(), reps=4):
    """An RDP list run as rdp_point does, from a cleared surface at COLOR_IMAGE (and Z_BUF cleared to the
    far plane), then hashed: hash = FNV-1a over the surface's words; of the surface's first cmp_bytes,
    changed = the halfwords unlike its first, tail = the halfwords from the first of those to the end
    (tex_k_hash)."""
    suite = rom.suite
    words = rcp.words(cmds + [rcp.full_sync()])
    build = Step("bench_list_step", [suite.blob(words), len(words), 0, 0, 0, 0, 0, KSEG1 | LIST_BUF], 0)
    steps = list(pre) + [
        build,
        Step("bench_run", ["tex_k_hash", reps, VI_OFF, LIST_BUF, 4 * len(words), KSEG1 | COLOR_IMAGE, surf_bytes,
                           cmp_bytes, KSEG1 | Z_BUF, z_bytes], 0),
        emit_step(suite, rom.name, point, list(consts) + [("vi", "off"), ("reps", reps)],
                  [("min", 0), ("max", 1)] + [(k, 2 + i) for i, k in enumerate(HASH_EXTRA)]),
    ]
    rom.test.values.append(Value(point, steps, []))


LOAD_BYTES = [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
LOAD_COUNTS = (1, 4)
TILE_MAX_TEXELS = 1024


def tmem_load_rate(suite):
    """Load Block and Load Tile of RGBA16 against size, each list one load or four back to back:
    (clock at n=4 - clock at n=1) / 3 is one load with the list's fixed cost removed, and its fit over
    bytes gives slope and intercept. 8 B/rclk (MiSTer RDP_raster.vhd) puts 4096 B at 512 clocks, the
    jgemu dpc_probe law (15 + 0.418/B) at 1727. Load Tile is one row up to 1024 texels (2048 B), two
    rows at 4096 B."""
    rom = Rom(suite, "tex-load")
    for nbytes in LOAD_BYTES:
        texels = nbytes // 2
        block = [set_texture_image(TEX_SRC, TILE_MAX_TEXELS), set_tile(LOAD_TILE, 0, 0)]
        for n in LOAD_COUNTS:
            rdp_point(rom, f"block-{nbytes}-n{n}", [load_block(LOAD_TILE, texels)], n,
                      [("op", "block"), ("bytes", nbytes), ("rows", 1)], prologue=block)
        width = min(texels, TILE_MAX_TEXELS)
        rows = texels // width
        tile = [set_texture_image(TEX_SRC, width), set_tile(LOAD_TILE, 2 * width // 8, 0)]
        for n in LOAD_COUNTS:
            rdp_point(rom, f"tile-{nbytes}-n{n}", [load_tile(LOAD_TILE, width, rows)], n,
                      [("op", "tile"), ("bytes", nbytes), ("rows", rows)], prologue=tile)


ROW_TOTAL = 2048
ROW_COUNTS = [1, 2, 4, 8, 16, 32, 64, 128, 256]


def load_tile_rows(suite):
    """2048 B by Load Tile as 1 to 256 rows (row 2048 to 8 B); tex-load block-2048-n1 is the same bytes
    as one Load Block. A per-row cost shows as clock rising with rows at fixed bytes."""
    rom = Rom(suite, "tex-rows")
    for rows in ROW_COUNTS:
        width = ROW_TOTAL // 2 // rows
        pro = [set_texture_image(TEX_SRC, width), set_tile(LOAD_TILE, 2 * width // 8, 0)]
        rdp_point(rom, f"rows-{rows}", [load_tile(LOAD_TILE, width, rows)], 1,
                  [("op", "tile"), ("bytes", ROW_TOTAL), ("rows", rows), ("row_bytes", 2 * width)], prologue=pro)


FC_WIDTHS = [8, 16, 32, 64, 128, 256, 320]
FC_H = 8


def fill_copy_rate(suite):
    """Fill rectangles at 16 and 32 bpp and copy-mode texture rectangles at 16 bpp against width, FC_H lines.
    SDK 12.1.4/12.1.5 give 64 bits per clock in both, so the clock steps by FC_H per 8 B of line.
    Fill and copy rectangles include their right and bottom edges, hence the w - 1 and h - 1."""
    rom = Rom(suite, "tex-fillcopy")
    for bpp, siz, color in ((16, SIZ_16, 0xF801F801), (32, SIZ_32, 0xFF0000FF)):
        pro = [rcp.set_color_image(FMT_RGBA, siz, 320, COLOR_IMAGE), rcp.set_scissor(0, 0, 320, 240),
               rcp.set_other_mode(rcp.CYC_FILL, 0), rcp.set_fill_color(color)]
        for w in FC_WIDTHS:
            rdp_point(rom, f"fill-b{bpp}-w{w}", [rcp.fill_rectangle_frac(0, 0, (w - 1) * 4, (FC_H - 1) * 4)], 1,
                      [("mode", "fill"), ("bpp", bpp), ("w", w), ("h", FC_H)], prologue=pro)
    pro = [rcp.set_color_image(FMT_RGBA, SIZ_16, 320, COLOR_IMAGE), rcp.set_scissor(0, 0, 320, 240),
           *load_pattern("pass", 0, 0), rcp.set_other_mode(rcp.CYC_COPY, 0)]
    for w in FC_WIDTHS:
        rect = texture_rectangle_frac(0, 0, 0, (w - 1) * 4, (FC_H - 1) * 4, 4 * S10_ONE, 0)
        rdp_point(rom, f"copy-b16-w{w}", rect, 1, [("mode", "copy"), ("bpp", 16), ("w", w), ("h", FC_H)],
                  prologue=pro)
    copy_first = next(v for v in rom.test.values if v.desc == f"copy-b16-w{FC_WIDTHS[0]}")
    copy_first.steps.insert(0, pattern_write(suite))


AC_W, AC_H = 256, 8
AC_CASES = [("pass", 1), ("fail", 1), ("word", 1), ("texel", 1), ("pass", 0), ("fail", 0)]


def copy_alpha(suite):
    """Copy-mode texture rectangles, 256x8 at 16 bpp, with alpha compare on: texels all pass, all fail,
    alternating per 64-bit word (4 texels), alternating per texel; and all pass and all fail with it off.
    A rejected word that skips its write makes fail cheaper than pass and word in between (#17); a masked
    write makes them equal. The hash shows which texels were written."""
    rom = Rom(suite, "tex-copyac")
    for i, (pat, ac) in enumerate(AC_CASES):
        cmds = [rcp.set_color_image(FMT_RGBA, SIZ_16, AC_W, COLOR_IMAGE), rcp.set_scissor(0, 0, AC_W, AC_H),
                *load_pattern(pat, 0, 0), rcp.set_other_mode(rcp.CYC_COPY, ac),
                *texture_rectangle_frac(0, 0, 0, (AC_W - 1) * 4, (AC_H - 1) * 4, 4 * S10_ONE, 0)]
        hash_point(rom, f"{pat}-ac{ac}", cmds, [("pat", pat), ("ac", ac), ("w", AC_W), ("h", AC_H)],
                   2 * AC_W * AC_H, 2 * AC_W * AC_H, pre=[pattern_write(suite)] if i == 0 else [])


AT_W, AT_H = 64, 4
BASE0 = rcp.CD_DISABLE | rcp.AD_DISABLE | rcp.TC_FILT
ZCMP = rcp.Z_CMP | rcp.ZS_PRIM


def _fill_rects(cyc, setup, mode_a, mode_b):
    return (setup + [rcp.set_other_mode(cyc | mode_a[0], mode_a[1]), rcp.fill_rectangle(0, 0, AT_W, AT_H)],
            [rcp.set_other_mode(cyc | mode_b[0], mode_b[1]), rcp.fill_rectangle(0, AT_H, AT_W, 2 * AT_H)])


def attribute_case(name, cyc):
    """(head, tail): the list through rect1, then the attribute change and rect2."""
    prim = [combine_d(PRIM, PRIM, PRIM, PRIM), rcp.set_prim_color(0xFF0000FF)]
    if name == "none":
        return _fill_rects(cyc, prim, (BASE0, 0), (BASE0, 0))
    if name == "blender":
        return _fill_rects(cyc, prim + [rcp.set_blend_color(0x00FF00FF)], (BASE0, 0), (BASE0, BL_P_BLEND))
    if name == "zmode":
        return _fill_rects(cyc, prim + [rcp.set_depth_image(Z_BUF), rcp.set_prim_depth(0, 0)],
                           (BASE0, ZCMP), (BASE0, ZCMP | ZMODE_DEC))
    if name == "zmode-rev":
        return _fill_rects(cyc, prim + [rcp.set_depth_image(Z_BUF), rcp.set_prim_depth(0, 0)],
                           (BASE0, ZCMP | ZMODE_DEC), (BASE0, ZCMP))
    if name == "dither":
        # 0x87 has low bits 7, so a Bayer threshold below 7 rounds the 5-bit channel up
        return _fill_rects(cyc, [combine_d(PRIM, PRIM, PRIM, PRIM), rcp.set_prim_color(0x878787FF)],
                           (BASE0, 0), (CD_BAYER | rcp.AD_DISABLE | rcp.TC_FILT, 0))
    second = TEXEL0 if cyc == rcp.CYC_1CYCLE else COMBINED
    setup = (load_pattern("pass", 0, 0) + [rcp.tile_sync()] + load_pattern("blue", 1, 0x100)
             + [set_tile(1, PAT_LINE, 0, mask_s=6), combine_d(TEXEL0, TEXEL0, second, second),
                rcp.set_other_mode(cyc | BASE0, 0)])

    def rect(y):
        return texture_rectangle_frac(0, 0, y * 4, AT_W * 4, (y + AT_H) * 4, S10_ONE, 0)
    return setup + rect(0), [set_tile(0, PAT_LINE, 0x100, mask_s=6), *rect(AT_H)]


AT_SYNCS = {"none": [], "pipe": [rcp.pipe_sync()], "tile": [rcp.tile_sync()]}
AT_CASES = [("none", ["none"]), ("tile", ["none", "pipe", "tile"]), ("blender", ["none", "pipe"]),
            ("zmode", ["none", "pipe"]), ("zmode-rev", ["none", "pipe"]), ("dither", ["none", "pipe"])]


def attribute_stage(suite):
    """Two 64x4 rectangles at 16 bpp with one attribute changed between them, unsynced or synced, in 1- and
    2-cycle mode. n64brew Pipeline 'Effect of unsynced attribute changes' has the change land that row's
    cycles (tile 13/10, blender 26/24, z_mode 27/26, rgb_dither_sel 29/28) before rect1 ends, so unsynced,
    rect1's last pixels take rect2's attribute: tail counts rect1's pixels from the first unlike its first
    to its end (the window in pixels; dither leaves some of them unchanged, so changed <= tail), hash
    covers the whole 64x8 surface. The clock against the no-change list gives each sync's cost. The tile case
    repoints tile 0 from the red row to the blue row. zmode turns rect1's tail from pass (opaque, prim Z 0
    over a far-plane Z buffer) to fail (decal), zmode-rev the other way: a model that redraws the tail
    over the finished primitive can show only the second."""
    rom = Rom(suite, "tex-attr")
    for cyc_name, cyc in (("c1", rcp.CYC_1CYCLE), ("c2", rcp.CYC_2CYCLE)):
        for name, syncs in AT_CASES:
            head, tail = attribute_case(name, cyc)
            for sync in syncs:
                cmds = [rcp.set_color_image(FMT_RGBA, SIZ_16, AT_W, COLOR_IMAGE),
                        rcp.set_scissor(0, 0, AT_W, 2 * AT_H), *head, *AT_SYNCS[sync], *tail]
                hash_point(rom, f"{name}-{cyc_name}-{sync}", cmds,
                           [("attr", name), ("cycle", cyc_name[1]), ("sync", sync)], 2 * AT_W * 2 * AT_H,
                           2 * AT_W * AT_H, z_bytes=2 * AT_W * 2 * AT_H if name.startswith("zmode") else 0,
                           pre=[pattern_write(suite)] if not rom.test.values else [])


BUILDERS = [tmem_load_rate, load_tile_rows, fill_copy_rate, copy_alpha, attribute_stage]

ASM = r"""
# Kernel. args = {list, bytes, surface (KSEG1), surface bytes, compare bytes (> 0), zbuf (KSEG1), zbuf bytes}.
# Clears the surface to 0 and the Z buffer to the far plane (z 0x3FFF, dz 0), runs k_rdp, then sets
# RES extras 4 = FNV-1a over the surface's words; over its first compare bytes, 5 = halfwords unlike the
# first, 6 = halfwords from the first unlike it to the end (0 if none).
tex_k_hash:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $a0, 8($sp)
    sd $a1, 16($sp)
    lw $t0, 8($a0)
    lw $t1, 12($a0)
    addu $t1, $t0, $t1
tex_kh_clr:
    sw $zero, 0($t0)
    addiu $t0, $t0, 4
    bne $t0, $t1, tex_kh_clr
    nop
    lw $t0, 20($a0)
    lw $t1, 24($a0)
    addu $t1, $t0, $t1
    li $t2, 0xFFFCFFFC
    beq $t0, $t1, tex_kh_run
    nop
tex_kh_zclr:
    sw $t2, 0($t0)
    addiu $t0, $t0, 4
    bne $t0, $t1, tex_kh_zclr
    nop
tex_kh_run:
    jal k_rdp
    nop
    move $v1, $v0
    ld $a0, 8($sp)
    ld $a1, 16($sp)
    lw $t0, 8($a0)
    lw $t1, 12($a0)
    addu $t1, $t0, $t1
    li $t2, 0x811C9DC5
    li $t3, 0x01000193
tex_kh_fnv:
    lw $t4, 0($t0)
    xor $t2, $t2, $t4
    multu $t2, $t3
    mflo $t2
    addiu $t0, $t0, 4
    bne $t0, $t1, tex_kh_fnv
    nop
    sw $t2, 16($a1)
    lw $t0, 8($a0)
    lw $t1, 16($a0)
    addu $t1, $t0, $t1
    lhu $t5, 0($t0)
    move $t6, $zero
    move $t7, $t1
tex_kh_cnt:
    lhu $t4, 0($t0)
    addiu $t0, $t0, 2
    beq $t4, $t5, tex_kh_same
    nop
    bnez $t6, tex_kh_same
    addiu $t6, $t6, 1
    addiu $t7, $t0, -2
tex_kh_same:
    bne $t0, $t1, tex_kh_cnt
    nop
    sw $t6, 20($a1)
    subu $t7, $t1, $t7
    srl $t7, $t7, 1
    sw $t7, 24($a1)
    move $v0, $v1
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 32
"""
