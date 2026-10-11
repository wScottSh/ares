"""The VI line buffer read back through the test registers (kit-vilb; prehw-plan.md U-VI-LINEBUF).

n64brew Video_Interface (rev 5791): VI_CTRL bit 7 TEST_MODE "enables usage of the line buffer test
registers VI_TEST_ADDR/VI_STAGED_DATA. KILL_WE should also be set to avoid access races between the VI
and CPU"; bit 11 KILL_WE "possibly kills VI DMA writes to line buffers"; VI_TEST_ADDR (0x0440 0038)
holds a 7-bit word address and VI_STAGED_DATA (0x0440 003C) reads "32 bits of line buffer data" there.
No source gives the order the VI fills the buffer in, so these points are a report with no question:
the console run records the fill order, and the fork, which decodes VI words 0-13 only, reads 0.

Each point fills a 16 bpp framebuffer whose every word names its line and its index in the line, shows
it with AA_MODE replicate and Y_SCALE 0x800 (two framebuffer lines per output line, progressive), and at
a polled V_CURRENT sets TEST_MODE and KILL_WE and reads all 128 words. X_SCALE 0x201 is n64brew's
X_SCALE erratum workaround for 0x200 (replicate, 16 bpp, H_START 108 under 128); 0xE01 is past the 0xE00
where 16 bpp "renders incorrect pixels". A ROM of its own, because the test-mode writes could disturb the
VI state that later points in another kit ROM read (inferred).
"""
from ..bench.benches import COLOR_IMAGE, KSEG1, Rom
from .bus import BUS_POLLS, VI_INIT, VI_CTRL, VI_X_SCALE, VI_Y_SCALE

FB = COLOR_IMAGE              # bank 7; nothing else in this ROM uses it
FB_WIDTH = 320
FB_LINES = 512                # Y_SCALE 2.0 over V_VIDEO 0x25..0x1FF reaches line 474, X_SCALE 0xE01 7 lines past it
WORDS = 128                   # VI_TEST_ADDR[6:0]
TEST_MODE, KILL_WE = 1 << 7, 1 << 11
AA_REPLICATE = 3 << 8
CTRL = VI_INIT[VI_CTRL] & ~(3 << 8) | AA_REPLICATE
Y_SCALE = 0x800
TARGET = 0x64                 # V_CURRENT half-line 100: output line 31 of V_VIDEO's 0x25 start
X_SCALES = [0x201, 0xE01]
EXTRA = [f"w{i}" for i in range(WORDS)] + ["timeout", "v_before", "v_after"]

ASM = f"""
# args = {{framebuffer (KSEG1), lines, X_SCALE, target V_CURRENT}}. Fills the framebuffer (word i of line y
# reads (0x8000 | y) << 16 | 0x8000 | i), shows it at {CTRL:#x} with Y_SCALE {Y_SCALE:#x}, waits for a vsync
# and then for the target line in the VI's field, sets TEST_MODE and KILL_WE, and reads VI_STAGED_DATA at
# each VI_TEST_ADDR 0..{WORDS - 1} into RES[2..{WORDS + 1}]. RES[{WORDS + 2}] = 1 when a wait gave up (no read),
# RES[{WORDS + 3}] / RES[{WORDS + 4}] = V_CURRENT before and after the reads. Then writes vi_init's values back.
# v0 = COUNT ticks of the reads.
k_vilb:
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    move $t2, $zero
kvl_line:
    ori $t3, $t2, 0x8000
    sll $t3, $t3, 16
    move $t4, $zero
kvl_word:
    ori $t5, $t4, 0x8000
    or $t5, $t5, $t3
    sw $t5, 0($t0)
    addiu $t4, $t4, 1
    sltiu $t6, $t4, {FB_WIDTH // 2}
    bnez $t6, kvl_word
    addiu $t0, $t0, 4
    addiu $t2, $t2, 1
    bne $t2, $t1, kvl_line
    nop
    sw $zero, {WORDS * 4}($a1)
    sw $zero, {(WORDS + 1) * 4}($a1)
    sw $zero, {(WORDS + 2) * 4}($a1)
    li $t7, 0xA4400000
    lw $t0, 0($a0)
    li $t1, 0x1FFFFFFF
    and $t0, $t0, $t1
    sw $t0, 0x04($t7)
    lw $t0, 8($a0)
    sw $t0, 0x30($t7)
    li $t0, {Y_SCALE:#x}
    sw $t0, 0x34($t7)
    li $t0, {CTRL:#x}
    sw $t0, 0x00($t7)
    li $t1, {BUS_POLLS}
kvl_leave:
    lw $t0, 0x10($t7)
    sltiu $t0, $t0, 0x20
    beqz $t0, kvl_vsync
    addiu $t1, $t1, -1
    bnez $t1, kvl_leave
    nop
    b kvl_timeout
    nop
kvl_vsync:
    li $t1, {BUS_POLLS}
kvl_vsync_loop:
    lw $t0, 0x10($t7)
    sltiu $t0, $t0, 0x10
    bnez $t0, kvl_field
    addiu $t1, $t1, -1
    bnez $t1, kvl_vsync_loop
    nop
    b kvl_timeout
    nop
kvl_field:
    lw $t0, 0x10($t7)
    andi $t0, $t0, 1
    lw $t2, 12($a0)
    or $t2, $t2, $t0
    li $t1, {BUS_POLLS}
kvl_target:
    lw $t0, 0x10($t7)
    beq $t0, $t2, kvl_read
    addiu $t1, $t1, -1
    bnez $t1, kvl_target
    nop
    b kvl_timeout
    nop
kvl_read:
    li $t1, {CTRL | TEST_MODE | KILL_WE:#x}
    sw $t1, 0x00($t7)
    sw $t0, {(WORDS + 1) * 4}($a1)
    move $t3, $a1
    move $t4, $zero
    mfc0 $t8, $count
kvl_read_loop:
    sw $t4, 0x38($t7)
    lw $t5, 0x3C($t7)
    sw $t5, 0($t3)
    addiu $t4, $t4, 1
    sltiu $t6, $t4, {WORDS}
    bnez $t6, kvl_read_loop
    addiu $t3, $t3, 4
    mfc0 $t9, $count
    lw $t0, 0x10($t7)
    sw $t0, {(WORDS + 2) * 4}($a1)
    b kvl_restore
    subu $v0, $t9, $t8
kvl_timeout:
    addiu $t0, $zero, 1
    sw $t0, {WORDS * 4}($a1)
    move $v0, $zero
kvl_restore:
    li $t0, {VI_INIT[VI_CTRL]:#x}
    sw $t0, 0x00($t7)
    li $t0, FB0 & 0x1FFFFFFF | 0xA0000000
    sw $t0, 0x04($t7)
    li $t0, {VI_INIT[VI_X_SCALE]:#x}
    sw $t0, 0x30($t7)
    li $t0, {VI_INIT[VI_Y_SCALE]:#x}
    jr $ra
    sw $t0, 0x34($t7)
"""


def vi_linebuf(suite):
    rom = Rom(suite, "vi-linebuf")
    for x in X_SCALES:
        rom.point(f"x{x:03x}", "k_vilb", [KSEG1 | FB, FB_LINES, x, TARGET],
                  [("x_scale", x), ("y_scale", Y_SCALE), ("aa_mode", 3), ("target", TARGET)], reps=1, extra=EXTRA)


BUILDERS = [vi_linebuf]
