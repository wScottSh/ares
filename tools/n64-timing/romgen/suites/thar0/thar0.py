"""Port of Thar0/RDP-Timing-Tests src/test_main.c (exec_timing, rdp_exec, main's print loop).

Each spec is one romgen test with one value whose single step, `thar0_spec`, programs the VI,
runs the setup command list, times a lone FULLSYNC as the baseline, then times RUNS fill
rectangles and prints the original's result block:

    <desc>
    BUF = [
        <buf - baseline_buf - 1>, ...
    ]
    PIPE = [
        <pipe - baseline_pipe - 1>, ...
    ]

The subtraction is in u32 like the C `%lu` print. compare.py turns the blocks into min/avg/max.
"""
from ... import rcp
from ...suite import Step, Test, Value
from .configs import SPECS

WIDTH, HEIGHT = 320, 240
FB_BYTES = WIDTH * HEIGHT * 2

# test_main.c reserves a 1 MiB-aligned static fb_region; libdragon links it into the first free
# 1 MiB bank above the program, which for this payload is bank 1 (inferred, not observed).
FB_REGION = 0x80100000
FB_ADDR = FB_REGION
ZB_ADDR_SAME = FB_REGION + 1 * FB_BYTES
VI_ADDR_SAME = FB_REGION + 2 * FB_BYTES
# test_main.c puts the separate Z-buffer at 0xA0400000. romgen's runtime data and stack live in
# bank 4, so the port uses bank 6, another Expansion Pak bank distinct from the FB's.
ZB_ADDR_DIFF = 0xA0600000
VI_ADDR_DIFF = 0xA0500000

RESULTS = 0x80700000         # RUNS x {BUFBUSY, PIPEBUSY, TMEM}
BASELINE = RESULTS - 16       # the lone-FULLSYNC counters
RUN_DL = 0xA07F0000          # libdragon keeps gfx_run[] on the stack, at the top of RDRAM
PAYLOAD_LIMIT = FB_REGION

VI_CTRL_ON = 0x00002 | 0x00004 | 0x00008 | 0x00010 | 0x00100 | (3 << 12)


def vi_writes(spec):
    vi = lambda off: rcp.VI_BASE + off  # noqa: E731
    if spec.vi_on:
        origin = VI_ADDR_SAME if spec.vi_same_bank else VI_ADDR_DIFF
        return [
            (vi(0x00), VI_CTRL_ON),
            (vi(0x04), origin),
            (vi(0x08), WIDTH),
            (vi(0x0C), 1024 - 1),
            (vi(0x10), 0),
            (vi(0x14), 57 | (34 << 8) | (5 << 16) | (62 << 20)),
            (vi(0x18), 525),
            (vi(0x1C), 3093),
            (vi(0x20), (3093 << 16) | 3093),
            (vi(0x24), (108 << 16) | 748),
            (vi(0x28), (37 << 16) | 511),
            (vi(0x2C), (14 << 16) | 516),
            (vi(0x30), 0x200),   # VI_SCALE(2.0, 0): 1/2 in 2.10
            (vi(0x34), 0x400),   # VI_SCALE(1.0, 0)
        ]
    return [
        (vi(0x00), 0),
        (vi(0x0C), 1024 - 1),
        (vi(0x24), 0),
        (vi(0x28), 0),
        (vi(0x10), 0),
        (vi(0x04), VI_ADDR_DIFF),
    ]


def setup_dl(spec):
    fb = FB_ADDR
    zb = ZB_ADDR_SAME if spec.zb_same_bank else ZB_ADDR_DIFF
    dl = [
        rcp.set_scissor_frac(rcp.SC_NON_INTERLACE, 0, 0, WIDTH * 4, HEIGHT * 4),
        rcp.set_other_mode(rcp.CYC_FILL, 0),
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, WIDTH, fb),
        rcp.set_fill_color((rcp.rgba5551(0, 0, 0, 255) << 16) | rcp.rgba5551(0, 0, 0, 255)),
        rcp.fill_rectangle(0, 0, WIDTH, HEIGHT),
        rcp.pipe_sync(),
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, WIDTH, zb),
        rcp.set_fill_color((rcp.zdz(rcp.MAXFBZ, 0) << 16) | rcp.zdz(rcp.MAXFBZ, 0)),
        rcp.fill_rectangle(0, 0, WIDTH, HEIGHT),
        rcp.pipe_sync(),
        rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, WIDTH, fb),
        rcp.set_depth_image(zb),
        rcp.set_combine_lerp("0", "0", "0", "PRIMITIVE", "0", "0", "0", "PRIMITIVE",
                             "0", "0", "0", "PRIMITIVE", "0", "0", "0", "PRIMITIVE"),
    ]
    om0 = ((rcp.CYC_2CYCLE if spec.two_cycle else rcp.CYC_1CYCLE)
           | rcp.AD_DISABLE | rcp.CD_DISABLE | rcp.CK_NONE
           | rcp.TC_FILT | rcp.TF_POINT | rcp.TT_NONE | rcp.TL_TILE | rcp.TD_CLAMP | rcp.TP_NONE
           | rcp.PM_NPRIMITIVE)
    om1 = ((rcp.AC_THRESHOLD if spec.alpha_compare else rcp.AC_NONE)
           | rcp.ZS_PRIM | rcp.CVG_DST_FULL | rcp.ZMODE_OPA
           | (rcp.IM_RD if spec.color_read else 0)
           | (rcp.Z_CMP if spec.depth_read else 0)
           | (rcp.Z_UPD if spec.depth_write else 0)
           | rcp.RM_NOOP)
    if not spec.depth_pass:
        dl += [
            rcp.set_other_mode(om0, om1 | rcp.Z_UPD),
            rcp.set_prim_color(0, 0, 255, 0, 0, 255),
            rcp.set_prim_depth(0, 0),
            rcp.fill_rectangle(0, 0, WIDTH, HEIGHT),
            rcp.pipe_sync(),
        ]
    dl += [
        rcp.set_other_mode(om0, om1),
        rcp.set_blend_color(0, 0, 0, spec.alpha_compare_threshold),
        rcp.set_prim_color(0, 0, 0, 255, 0, spec.rectangle_alpha),
        rcp.set_prim_depth(0x7FFF, 0),
        rcp.full_sync(),
    ]
    return dl


# gfx_run[]: the measured rectangle; the prim depth word (index 3) is patched per run.
RUN_TEMPLATE = rcp.words([
    rcp.fill_rectangle(0, 0, WIDTH, HEIGHT),
    rcp.set_prim_depth(0x7FFF, 0),
    rcp.full_sync(),
])

ASM = r"""
# a0 = {vi_writes, setup_dl, setup_bytes}. Runs one spec and prints its result block.
thar0_spec:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    move $s0, $a0
    jal pif_terminate_boot
    nop
    jal io_writes
    lw $a0, 0($s0)
    li $a0, 20 * COUNT_PER_MS
    jal wait_count
    nop
    li $t1, 0x1FFFFFFF
    lw $a0, 4($s0)
    and $a0, $a0, $t1
    lw $t0, 8($s0)
    addu $a1, $a0, $t0
    jal rdp_exec
    move $a2, $zero
    la $a0, thar0_fullsync
    li $t1, 0x1FFFFFFF
    and $a0, $a0, $t1
    addiu $a1, $a0, 8
    li $a2, BASELINE
    jal rdp_exec
    nop
    move $s1, $zero
    li $s2, RESULTS
ts_run:
    la $t0, thar0_run_template
    li $t1, RUN_DL
    li $t2, 6
ts_copy:
    lw $t3, 0($t0)
    sw $t3, 0($t1)
    addiu $t0, $t0, 4
    addiu $t2, $t2, -1
    bnez $t2, ts_copy
    addiu $t1, $t1, 4
    li $t0, 0x7FFF
    subu $t0, $t0, $s1
    sll $t0, $t0, 16
    li $t1, RUN_DL
    sw $t0, 12($t1)
    jal thar0_rand
    nop
    li $t0, COUNT_PER_MS
    multu $v0, $t0
    jal wait_count
    mflo $a0
    li $a0, RUN_DL & 0x1FFFFFFF
    addiu $a1, $a0, 24
    jal rdp_exec
    move $a2, $s2
    addiu $s2, $s2, 12
    addiu $s1, $s1, 1
    li $t0, RUNS
    bne $s1, $t0, ts_run
    nop
    la $t0, DATA_BASE + D_TEST_NAME
    jal pr_str
    lw $a0, 0($t0)
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    la $a0, thar0_str_buf
    jal thar0_print_list
    move $a1, $zero
    la $a0, thar0_str_pipe
    li $a1, 4
    jal thar0_print_list
    nop
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    jr $ra
    addiu $sp, $sp, 48

# a0 = header string, a1 = counter offset in a result record (0 BUFBUSY, 4 PIPEBUSY).
# Prints "<header>v, v, ...\n]\n" with v = run - baseline - 1, one XLOG per value.
thar0_print_list:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    li $s0, RESULTS
    addu $s0, $s0, $a1
    li $s2, BASELINE
    addu $s2, $s2, $a1
    li $s1, RUNS
    jal pr_str
    nop
tp_loop:
    lw $a0, 0($s0)
    lw $t0, 0($s2)
    subu $a0, $a0, $t0
    jal pr_dec
    addiu $a0, $a0, -1
    la $a0, thar0_str_sep
    jal pr_str
    nop
    jal pr_flush
    addiu $s0, $s0, 12
    addiu $s1, $s1, -1
    bnez $s1, tp_loop
    nop
    la $a0, thar0_str_close
    jal pr_str
    nop
    jal pr_flush
    nop
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    jr $ra
    addiu $sp, $sp, 32

# newlib rand(): next = next * 6364136223846793005 + 1, return (next >> 32) & RAND_MAX.
# Returns (rand() >> 28) & 0xF, the original's wait in ms (0-7).
thar0_rand:
    la $t0, thar0_rand_state
    ld $t1, 0($t0)
    ld $t2, 8($t0)
    dmultu $t1, $t2
    mflo $t1
    daddiu $t1, $t1, 1
    sd $t1, 0($t0)
    dsrl32 $v0, $t1, 28
    jr $ra
    andi $v0, $v0, 7

thar0_str_buf: .asciiz "BUF = [\n    "
thar0_str_pipe: .asciiz "PIPE = [\n    "
thar0_str_sep: .asciiz ", "
thar0_str_close: .asciiz "\n]\n"
.align 8
# test_main.c seeds rand() from COUNT at boot; the port uses newlib's unseeded state (1) so the
# ROM's run-to-run phase pattern is deterministic.
thar0_rand_state: .dword 1, 6364136223846793005
thar0_fullsync: .word FULLSYNC_WORDS
thar0_run_template: .word RUN_WORDS
""".replace("FULLSYNC_WORDS", ", ".join(str(w) for w in rcp.words([rcp.full_sync()]))
          ).replace("RUN_WORDS", ", ".join(str(w) for w in RUN_TEMPLATE))


def build(suite):
    for spec in SPECS:
        vi = [len(vi_writes(spec))] + [w for pair in vi_writes(spec) for w in pair]
        dl = rcp.words(setup_dl(spec))
        step = Step("thar0_spec", [suite.blob(vi), suite.blob(dl), 4 * len(dl)])
        suite.tests.append(Test(spec.desc, [Value(spec.id, [step], [])]))
