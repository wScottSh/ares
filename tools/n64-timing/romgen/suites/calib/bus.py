"""Kit points for the bus kit ROM (sets.py KITS["kit-bus"]): builders follow the bench convention
(suites/bench/benches.py Rom.point), kernels the bench kernel convention (asm.py).

RDRAM client priority and reordering (rdram-bus-arbitration.md section 8 questions 1-2), the AI
sample clock (ai.cpp power-on rate, AI_LEN granularity), the VI fetch against its registers
(vi-fetch.md), the refresh holdoff per bank (issue #16) and the VI interrupt and line phase (#24).
RDRAM written: BUS_SAMPLES and AI_BUF (bank 6, this module's), and the bench's LIST_BUF, PI_DMA_BUF
and COLOR_IMAGE (benches.py). The SP DMA reads RDRAM into DMEM.
"""
from ...suite import Step, Value
from ... import rcp
from ..bench.benches import (KSEG0, KSEG1, LIST_BUF, COLOR_IMAGE, SP_DMA_BUF, PI_DMA_BUF, MIB, VI_OFF,
                             TICK_FIELDS, Rom, emit_step, rdp_prologue)

BUS_SAMPLES = 0x006A0000      # bank 6, 6 KiB of packed samples (fits the 8 KiB D-cache, as bench_hpos)
BUS_MAX_SAMPLES = 1536
AI_BUF = 0x006B0000           # bank 6, inside one 8 KiB block (the AI DMA address carry, ai.cpp)
LOAD_BANK5 = 0x005E0000       # a bank no client and no VI touches
LOAD_BANK6 = 0x006C0000       # SP DMA and PI DMA's bank, another row
LOAD_BANK7 = 0x007C0000       # the RDP color image's bank, another row
BUS_POLLS = 0x100000          # poll bound: over 2 VI fields at one RCP register read per poll

SP_REGS, DPC_REGS, MI_REGS, PI_REGS, VI_REGS = 0xA4040000, 0xA4100000, 0xA4300000, 0xA4600000, 0xA4400000
MI_INTR = MI_REGS + 0x8
VI_CTRL, VI_H_VIDEO, VI_V_VIDEO, VI_X_SCALE, VI_Y_SCALE = (VI_REGS + o for o in (0x00, 0x24, 0x28, 0x30, 0x34))

# runtime.py vi_init's values of the registers these points change; k_bus_vline writes them back.
VI_INIT = {VI_CTRL: 0x324E, VI_H_VIDEO: 0x006C02EC, VI_V_VIDEO: 0x002501FF, VI_X_SCALE: 0x200, VI_Y_SCALE: 0x400}
VI_INIT_V_INTR = 2
AA_SHIFT = 8


def ctrl(aa=2, kind=2):
    return VI_INIT[VI_CTRL] & ~(3 << AA_SHIFT) & ~3 | aa << AA_SHIFT | kind


def vi_boot_phase(suite):
    """The ROM's first point: COUNT at the first V_CURRENT change it sees, a report value (the VI and
    the CPU run from separate crystals, #24, so on a console it moves with each power-on)."""
    rom = Rom(suite, "bus-vi-phase")
    rom.point("boot", "k_bus_vboot", [], reps=1, extra=["count_at", "v_before", "v_after"])


AI_BYTES = 1024
AI_EXTRA = ["len_first", "changes", "step_min", "step_max", "first_change", "last_change", "busy_clear",
            "timeout"]
AI_RATES = [1102, 1103]       # 1103 and 1104 VCLK per sample: ai.cpp power()'s truncation question
AI_BITRATE = 15


def ai_rate(suite):
    """Two AI buffers queued back to back; the second plays from AI_STATUS full clearing to AI_LEN
    reading 0. The power-on point runs before any AI_DACRATE write in this ROM."""
    rom = Rom(suite, "bus-ai")
    zero = Step("bench_list_step", [suite.blob([0] * (AI_BYTES // 4)), AI_BYTES // 4, 0, 0, 0, 0, 0,
                                    KSEG1 | AI_BUF], 0)
    rom.point("power-on", "k_bus_ai", [0xFFFFFFFF, 0, AI_BUF, AI_BYTES], [("dacrate", "unset"), ("bytes", AI_BYTES)],
              reps=2, extra=AI_EXTRA, pre=[zero])
    for rate in AI_RATES:
        rom.point(f"dacrate-{rate}", "k_bus_ai", [rate, AI_BITRATE, AI_BUF, AI_BYTES],
                  [("dacrate", rate), ("bytes", AI_BYTES)], reps=2, extra=AI_EXTRA)


LOADS = 32
CLIENT_EXTRA = ["load_max", "busy_after", "client_ticks", "timeout"]
SP_LEN_16K = 3 << 12 | 0xFFF       # four 4 KiB rows into DMEM, its address wrapping (SP_RD_LEN COUNT field)
PI_BYTES = 8192
PI_CART = 0x10001000
FILL_LIST = [rcp.set_color_image(rcp.IM_FMT_RGBA, rcp.IM_SIZ_16b, 320, COLOR_IMAGE), rcp.set_scissor(0, 0, 320, 240),
             rcp.set_other_mode(rcp.CYC_FILL, 0), rcp.set_fill_color(0), rcp.fill_rectangle(0, 0, 320, 64),
             rcp.full_sync()]
IMRD_LIST = rdp_prologue()[:-1] + [rcp.set_other_mode(rcp.CYC_1CYCLE, rcp.IM_RD), rcp.fill_rectangle(0, 0, 320, 16),
                                   rcp.full_sync()]


def client_args(setups, trigger, done, ack=(0, 0)):
    """k_bus_client's register program: up to two setup writes, the trigger write, the
    (register, mask, value) that means done, and one acknowledge write."""
    setups = list(setups) + [(0, 0)] * (2 - len(setups))
    return [*setups[0], *setups[1], *trigger, *done, *ack]


def rdp_client(suite, dl):
    words = rcp.words(dl)
    build = Step("bench_list_step", [suite.blob(words), len(words), 0, 0, 0, 0, 0, KSEG1 | LIST_BUF], 0)
    args = client_args([(DPC_REGS + 0xC, 0x3C1), (DPC_REGS + 0x0, LIST_BUF)], (DPC_REGS + 0x4, LIST_BUF + 4 * len(words)),
                       (MI_INTR, 0x20, 0x20), (MI_REGS, 0x800))
    return args, [build], LOAD_BANK7


def clients(suite):
    """name -> (k_bus_client program, pre steps, a load address in the client's bank)."""
    suite.blob([0x5A5A5A5A] * (PI_BYTES // 4))
    return {
        "idle": (client_args([], (SP_REGS + 0x1C, 0), (MI_INTR, 0, 0)), [], LOAD_BANK6),
        "sp-rd-16k": (client_args([(SP_REGS + 0x0, 0), (SP_REGS + 0x4, SP_DMA_BUF)], (SP_REGS + 0x8, SP_LEN_16K),
                                  (SP_REGS + 0x18, 1, 0)), [], LOAD_BANK6),
        "pi-8k": (client_args([(PI_REGS + 0x0, PI_DMA_BUF), (PI_REGS + 0x4, PI_CART)], (PI_REGS + 0xC, PI_BYTES - 1),
                              (PI_REGS + 0x10, 3, 0), (PI_REGS + 0x10, 2)), [], LOAD_BANK6),
        "rdp-fill": rdp_client(suite, FILL_LIST),
        "rdp-imrd": rdp_client(suite, IMRD_LIST),
    }


def ri_priority(suite):
    """LOADS uncached loads while one client saturates the channel, in the client's bank (another row)
    and in bank 5; v0 sums their latencies. sp-rd-16k-alone is the DMA with no loads (serial), so the
    SP rows' client_ticks answer ri-reorder."""
    rom = Rom(suite, "bus-ri")
    progs = clients(suite)
    for name, (prog, pre, own) in progs.items():
        for where, addr in (("own", own), ("bank5", LOAD_BANK5)):
            rom.point(f"{name}-{where}", "k_bus_client", prog + [KSEG1 | addr, LOADS],
                      [("client", name), ("bank", addr >> 20), ("loads", LOADS)], reps=4, flags=VI_OFF,
                      extra=CLIENT_EXTRA, pre=pre)
    rom.point("sp-rd-16k-alone", "k_bus_client", progs["sp-rd-16k"][0] + [KSEG1 | LOAD_BANK5, 0],
              [("client", "sp-rd-16k"), ("bank", 5), ("loads", 0)], reps=4, flags=VI_OFF, extra=CLIENT_EXTRA)


VLINE_EXTRA = (["n", "sum", "slow", "lat_min", "lat_max", "line_ticks"] + [f"s{i}" for i in range(8)]
               + [f"c{i}" for i in range(8)] + ["timeout"])
V_TARGET = 0x100
V_LINES = 10
LINE_TICKS = 2979   # NTSC: (H_SYNC 0xC15 + 1) VCLK at 48.681812 MHz in 46.875 MHz COUNT ticks
SLOW_TICKS = 30
V_VIDEO_EARLY_OFF = 0x00250080   # the active lines end before V_TARGET
VI_BANK_LOAD = 0x00280000        # bank 2, the VI front buffer's bank (FB0), another row

VI_CASES = [
    # name, register writes, late (written once V_CURRENT reads the target, one line before the window)
    ("base", [], 0),
    ("vi-blank", [(VI_CTRL, ctrl(kind=0))], 0),
    ("aa0", [(VI_CTRL, ctrl(aa=0))], 0),
    ("aa1", [(VI_CTRL, ctrl(aa=1))], 0),
    ("aa3", [(VI_CTRL, ctrl(aa=3))], 0),
    ("x-0.25", [(VI_X_SCALE, 0x100)], 0),
    ("x-1.0", [(VI_X_SCALE, 0x400)], 0),
    ("x-2.0", [(VI_X_SCALE, 0x800)], 0),
    ("y-0.5", [(VI_Y_SCALE, 0x200)], 0),
    ("y-2.0", [(VI_Y_SCALE, 0x800)], 0),
    ("aa3-y-2.0", [(VI_CTRL, ctrl(aa=3)), (VI_Y_SCALE, 0x800)], 0),
    ("hvideo-half", [(VI_H_VIDEO, 0x006C01AC)], 0),
    ("vvideo-outside", [(VI_V_VIDEO, V_VIDEO_EARLY_OFF)], 0),
    ("x-2.0-late", [(VI_X_SCALE, 0x800)], 1),
    ("vi-blank-late", [(VI_CTRL, ctrl(kind=0))], 1),
    ("vvideo-outside-late", [(VI_V_VIDEO, V_VIDEO_EARLY_OFF)], 1),
]
# V_VIDEO opened from V 8: the window (V 12 to 32, half-lines) lies inside it but above ares's display
# window, which starts at half-line 34 on NTSC (vi.cpp window(), vi.display-window).
VVIDEO_EARLY = ("vvideo-early", [(VI_V_VIDEO, 0x000801FF)], 0, 0x0A)


def vline_point(rom, point, addr, writes, late, consts, target=V_TARGET):
    regs = [w for pair in writes for w in pair]
    rom.point(point, "k_bus_vline", [KSEG1 | addr, target, V_LINES, SLOW_TICKS, late, len(writes), *regs],
              list(consts) + [("bank", addr >> 20), ("v", target), ("lines", V_LINES), ("late", late)], reps=1,
              extra=VLINE_EXTRA)


def vi_fetch_modes(suite):
    """Back-to-back uncached loads in the VI's bank for V_LINES lines after V_TARGET, per VI register
    case; s<i> and c<i> sum and count the latencies by eighth of the line."""
    rom = Rom(suite, "bus-vi")
    for name, writes, late in VI_CASES:
        vline_point(rom, name, VI_BANK_LOAD, writes, late, [("case", name)])
    name, writes, late, target = VVIDEO_EARLY
    vline_point(rom, name, VI_BANK_LOAD, writes, late, [("case", name)], target)
    vline_point(rom, "base-bank5", LOAD_BANK5, [], 0, [("case", "base")])


def refresh_banks(suite):
    """The same sampling in every bank, V_VIDEO ending before the window so that the per-HSYNC
    refresh is the only channel holdoff left in it."""
    rom = Rom(suite, "bus-refresh")
    for bank in range(8):
        vline_point(rom, f"bank{bank}", bank * MIB + 0xF0000, [(VI_V_VIDEO, V_VIDEO_EARLY_OFF)], 0,
                    [("case", "vvideo-outside")])


VINTR_BIAS = 4096
VINTR_REPS = 16
VINTR_STEP = 2


def vi_intr(suite):
    """V_INTR = V_TARGET; v0 = COUNT at the first MI_INTR VI bit minus COUNT at the first V_CURRENT ==
    V_INTR, plus VINTR_BIAS. Each rep spins VINTR_STEP more iterations, walking the poll's phase."""
    rom = Rom(suite, "bus-vintr")
    steps = [Step("bench_multi", ["k_bus_vintr", VINTR_REPS, 0, V_TARGET, VINTR_STEP], 0),
             emit_step(suite, rom.name, "v-intr", [("v_intr", V_TARGET), ("bias", VINTR_BIAS), ("reps", VINTR_REPS)],
                       TICK_FIELDS + [("sum", 2), ("max2", 3), ("v_at_intr", 4), ("iter_ticks", 5), ("timeout", 6)])]
    rom.test.values.append(Value("v-intr", steps, []))


BUILDERS = [vi_boot_phase, ai_rate, ri_priority, vi_fetch_modes, refresh_banks, vi_intr]

VI_RESTORE = "\n".join(f"    .word 0x{reg:08X}, 0x{val:08X}" for reg, val in VI_INIT.items())

ASM = f"""
# args = {{}}. RES[2] = COUNT at the first V_CURRENT change, RES[3] / RES[4] = V_CURRENT before / after.
# v0 = ticks waited.
k_bus_vboot:
    li $t0, 0xA4400010
    mfc0 $t8, $count
    lw $t1, 0($t0)
    li $t3, {BUS_POLLS}
bus_vb_loop:
    lw $t2, 0($t0)
    bne $t2, $t1, bus_vb_hit
    addiu $t3, $t3, -1
    bnez $t3, bus_vb_loop
    nop
bus_vb_hit:
    mfc0 $t9, $count
    sw $t9, 0($a1)
    sw $t1, 4($a1)
    sw $t2, 8($a1)
    jr $ra
    subu $v0, $t9, $t8

# a0 = previous V_CURRENT. v0 = the next value (a0 on timeout), v1 = COUNT at the change. Uses t0, t1.
bus_vchg:
    li $t0, 0xA4400010
    li $t1, {BUS_POLLS}
bus_vc_loop:
    lw $v0, 0($t0)
    bne $v0, $a0, bus_vc_hit
    addiu $t1, $t1, -1
    bnez $t1, bus_vc_loop
    nop
    jr $ra
    move $v0, $a0
bus_vc_hit:
    mfc0 $v1, $count
    jr $ra
    nop

# a0 = a V_CURRENT value. Waits until V_CURRENT reads it: v0 = 1, or 0 on timeout. Uses t0, t1.
bus_vwait_eq:
    li $t0, 0xA4400010
    li $t1, {BUS_POLLS}
bus_ve_loop:
    lw $v0, 0($t0)
    beq $v0, $a0, bus_ve_hit
    addiu $t1, $t1, -1
    bnez $t1, bus_ve_loop
    nop
    jr $ra
    move $v0, $zero
bus_ve_hit:
    jr $ra
    addiu $v0, $zero, 1

# a0 = &{{..., n at 20, (register, value) x n at 24}}. Uses t0-t3.
bus_vi_writes:
    lw $t0, 20($a0)
    addiu $t1, $a0, 24
bus_vw_loop:
    beqz $t0, bus_vw_done
    nop
    lw $t2, 0($t1)
    lw $t3, 4($t1)
    sw $t3, 0($t2)
    addiu $t1, $t1, 8
    b bus_vw_loop
    addiu $t0, $t0, -1
bus_vw_done:
    jr $ra
    nop

# args = {{setup reg, value, setup reg, value (reg 0 = none), trigger reg, value, done reg, mask, done
# value, ack reg (0 = none), value, load addr, loads}}. The setup writes, a read of the done register
# (it drains the write buffer), COUNT, the trigger write, then `loads` timed uncached LWs. RES[2] = the
# longest load, RES[3] = 1 if the client was not done after the loads, RES[4] = ticks from the trigger to
# (done reg & mask) == done value, RES[5] = 1 on a poll timeout. v0 = the loads' summed ticks.
k_bus_client:
    lw $t0, 0($a0)
    beqz $t0, bus_cl_setup2
    lw $t1, 4($a0)
    sw $t1, 0($t0)
bus_cl_setup2:
    lw $t0, 8($a0)
    beqz $t0, bus_cl_go
    lw $t1, 12($a0)
    sw $t1, 0($t0)
bus_cl_go:
    lw $t0, 16($a0)
    lw $t1, 20($a0)
    lw $t2, 44($a0)
    lw $t3, 48($a0)
    lw $t4, 24($a0)
    lw $t5, 28($a0)
    lw $t6, 32($a0)
    move $v0, $zero
    move $v1, $zero
    lw $t7, 0($t4)
    mfc0 $a2, $count
    sw $t1, 0($t0)
bus_cl_load:
    beqz $t3, bus_cl_after
    nop
    mfc0 $t8, $count
    lw $t7, 0($t2)
    addu $t7, $t7, $zero
    mfc0 $t9, $count
    subu $t9, $t9, $t8
    addu $v0, $v0, $t9
    sltu $t8, $v1, $t9
    beqz $t8, bus_cl_load
    addiu $t3, $t3, -1
    b bus_cl_load
    move $v1, $t9
bus_cl_after:
    lw $t8, 0($t4)
    and $t8, $t8, $t5
    xor $t8, $t8, $t6
    sltu $t8, $zero, $t8
    sw $v1, 0($a1)
    sw $t8, 4($a1)
    li $a3, {BUS_POLLS}
bus_cl_done:
    lw $t8, 0($t4)
    and $t8, $t8, $t5
    beq $t8, $t6, bus_cl_fin
    nop
    addiu $a3, $a3, -1
    bnez $a3, bus_cl_done
    nop
bus_cl_fin:
    mfc0 $t9, $count
    subu $t9, $t9, $a2
    sw $t9, 8($a1)
    sltiu $t8, $a3, 1
    sw $t8, 12($a1)
    lw $t0, 36($a0)
    beqz $t0, bus_cl_ret
    lw $t1, 40($a0)
    sw $t1, 0($t0)
bus_cl_ret:
    jr $ra
    nop

# args = {{dacrate (negative = leave it), bitrate, dram addr, bytes}}. Queues two AI buffers, waits for
# AI_STATUS full to clear (the second buffer starts), then polls AI_LEN to 0 and AI_STATUS busy clear.
# Times are ticks from the full clear. RES[2] = AI_LEN at the full clear, RES[3] = AI_LEN changes,
# RES[4] / RES[5] = smallest / largest drop, RES[6] / RES[7] = first / last change, RES[8] = busy clear,
# RES[9] = 1 on a timeout. v0 = RES[7].
k_bus_ai:
    li $t0, 0xA4500000
    lw $t1, 0($a0)
    bltz $t1, bus_ai_go
    lw $t2, 4($a0)
    sw $t1, 0x10($t0)
    sw $t2, 0x14($t0)
bus_ai_go:
    addiu $t1, $zero, 1
    sw $t1, 0x8($t0)
    lw $t2, 8($a0)
    lw $t3, 12($a0)
    sw $t2, 0x0($t0)
    sw $t3, 0x4($t0)
    sw $t2, 0x0($t0)
    sw $t3, 0x4($t0)
    li $a3, {BUS_POLLS * 4}
bus_ai_full:
    lw $t4, 0xC($t0)
    bgez $t4, bus_ai_second
    nop
    addiu $a3, $a3, -1
    bnez $a3, bus_ai_full
    nop
    b bus_ai_timeout
    nop
bus_ai_second:
    mfc0 $t8, $count
    lw $t5, 0x4($t0)
    sw $t5, 0($a1)
    move $t7, $zero
    addiu $a2, $zero, -1
    move $v1, $zero
    move $t1, $zero
    move $t2, $zero
    li $a3, {BUS_POLLS * 4}
bus_ai_len:
    lw $t6, 0x4($t0)
    beq $t6, $t5, bus_ai_same
    subu $t3, $t5, $t6
    mfc0 $t9, $count
    subu $t9, $t9, $t8
    bnez $t7, bus_ai_later
    nop
    move $t1, $t9
bus_ai_later:
    move $t2, $t9
    addiu $t7, $t7, 1
    sltu $t4, $t3, $a2
    beqz $t4, bus_ai_minok
    nop
    move $a2, $t3
bus_ai_minok:
    sltu $t4, $v1, $t3
    beqz $t4, bus_ai_maxok
    nop
    move $v1, $t3
bus_ai_maxok:
    beqz $t6, bus_ai_zero
    move $t5, $t6
bus_ai_same:
    addiu $a3, $a3, -1
    bnez $a3, bus_ai_len
    nop
    b bus_ai_timeout
    nop
bus_ai_zero:
    li $a3, {BUS_POLLS}
bus_ai_busy:
    lw $t4, 0xC($t0)
    sll $t4, $t4, 1
    bgez $t4, bus_ai_idle
    nop
    addiu $a3, $a3, -1
    bnez $a3, bus_ai_busy
    nop
bus_ai_idle:
    mfc0 $t9, $count
    subu $t9, $t9, $t8
    sltiu $t4, $a3, 1
    sw $t4, 28($a1)
    sw $t7, 4($a1)
    sw $a2, 8($a1)
    sw $v1, 12($a1)
    sw $t1, 16($a1)
    sw $t2, 20($a1)
    sw $t9, 24($a1)
    b bus_ai_end
    move $v0, $t2
bus_ai_timeout:
    addiu $t4, $zero, 1
    sw $t4, 28($a1)
    move $v0, $zero
bus_ai_end:
    sw $zero, 0x8($t0)
    jr $ra
    sw $zero, 0xC($t0)

# args = {{load addr, target V_CURRENT, lines, slow ticks, late, n, (VI register, value) x n}}. Applies the
# writes (late: once V_CURRENT reads the target), then from the line start after the target takes
# back-to-back timed uncached LWs for `lines` x LINE_TICKS (bench_hpos's loop), then takes the line as
# the mean of the next 4 V_CURRENT change intervals. Reduces the loads to RES[2] = loads, RES[3] =
# summed ticks, RES[4] = loads of at least `slow` ticks, RES[5] / RES[6] = shortest / longest, RES[7] =
# line ticks (0 if V_CURRENT stopped after the window; the eighths then use LINE_TICKS), RES[8..15] =
# summed ticks by eighth of the line, RES[16..23] = loads by eighth, RES[24] = 1 on a timeout. Then
# writes vi_init's values back. v0 = RES[3].
k_bus_vline:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    sd $s3, 32($sp)
    sd $s4, 40($sp)
    move $s0, $a0
    move $s1, $a1
    move $t0, $a1
    addiu $t1, $zero, 23
bus_vl_zero:
    sw $zero, 0($t0)
    addiu $t1, $t1, -1
    bnez $t1, bus_vl_zero
    addiu $t0, $t0, 4
    lw $t0, 16($s0)
    bnez $t0, bus_vl_touch
    nop
    jal bus_vi_writes
    move $a0, $s0
bus_vl_touch:
    li $t4, {KSEG0 | BUS_SAMPLES}
    li $t5, {BUS_MAX_SAMPLES * 4}
bus_vl_touch_loop:
    lw $t6, 0($t4)
    addiu $t5, $t5, -16
    bgtz $t5, bus_vl_touch_loop
    addiu $t4, $t4, 16
    jal bus_vwait_eq
    lw $a0, 4($s0)
    beqz $v0, bus_vl_timeout
    nop
    lw $t0, 16($s0)
    beqz $t0, bus_vl_start
    nop
    jal bus_vi_writes
    move $a0, $s0
bus_vl_start:
    jal bus_vchg
    lw $a0, 4($s0)
    beq $v0, $a0, bus_vl_timeout
    nop
    move $s3, $v1
    lw $t9, 8($s0)
    addiu $t8, $zero, {LINE_TICKS}
    multu $t8, $t9
    mflo $a3
    lw $a2, 0($s0)
    li $t4, {KSEG0 | BUS_SAMPLES}
    li $t5, {BUS_MAX_SAMPLES}
    move $s4, $zero
bus_vl_loop:
    mfc0 $t6, $count
    lw $t7, 0($a2)
    addu $t7, $t7, $zero
    mfc0 $t8, $count
    subu $t9, $t8, $t6
    subu $t6, $t6, $s3
    sll $t1, $t6, 16
    or $t1, $t1, $t9
    sw $t1, 0($t4)
    addiu $s4, $s4, 1
    beq $s4, $t5, bus_vl_reduce
    addiu $t4, $t4, 4
    sltu $t1, $t6, $a3
    bnez $t1, bus_vl_loop
    nop
bus_vl_reduce:
    addiu $s2, $zero, {LINE_TICKS}
    li $t0, 0xA4400010
    jal bus_vchg
    lw $a0, 0($t0)
    beq $v0, $a0, bus_vl_noperiod
    nop
    move $s3, $v1
    addiu $a2, $zero, 4
bus_vl_period:
    jal bus_vchg
    move $a0, $v0
    beq $v0, $a0, bus_vl_noperiod
    addiu $a2, $a2, -1
    bnez $a2, bus_vl_period
    nop
    subu $s2, $v1, $s3
    srl $s2, $s2, 2
    b bus_vl_period_ok
    sw $s2, 20($s1)
bus_vl_noperiod:
    addiu $t0, $zero, 1
    sw $t0, 88($s1)
bus_vl_period_ok:
    sw $s4, 0($s1)
    li $t0, 0xFFFF
    sw $t0, 12($s1)
    lw $a3, 12($s0)
    li $t4, {KSEG0 | BUS_SAMPLES}
bus_vl_red:
    beqz $s4, bus_vl_restore
    nop
    lw $t1, 0($t4)
    andi $t2, $t1, 0xFFFF
    srl $t3, $t1, 16
    divu $t3, $s2
    lw $t5, 4($s1)
    addu $t5, $t5, $t2
    sw $t5, 4($s1)
    sltu $t5, $t2, $a3
    bnez $t5, bus_vl_fast
    nop
    lw $t5, 8($s1)
    addiu $t5, $t5, 1
    sw $t5, 8($s1)
bus_vl_fast:
    lw $t5, 12($s1)
    sltu $t6, $t2, $t5
    beqz $t6, bus_vl_notmin
    nop
    sw $t2, 12($s1)
bus_vl_notmin:
    lw $t5, 16($s1)
    sltu $t6, $t5, $t2
    beqz $t6, bus_vl_notmax
    nop
    sw $t2, 16($s1)
bus_vl_notmax:
    mfhi $t6
    nop
    nop
    sll $t6, $t6, 3
    divu $t6, $s2
    mflo $t6
    nop
    nop
    sll $t6, $t6, 2
    addu $t7, $s1, $t6
    lw $t8, 24($t7)
    addu $t8, $t8, $t2
    sw $t8, 24($t7)
    lw $t8, 56($t7)
    addiu $t8, $t8, 1
    sw $t8, 56($t7)
    addiu $t4, $t4, 4
    b bus_vl_red
    addiu $s4, $s4, -1
bus_vl_timeout:
    addiu $t0, $zero, 1
    sw $t0, 88($s1)
bus_vl_restore:
    la $t0, bus_vi_init
    addiu $t1, $zero, {len(VI_INIT)}
bus_vl_rloop:
    lw $t2, 0($t0)
    lw $t3, 4($t0)
    sw $t3, 0($t2)
    addiu $t1, $t1, -1
    bnez $t1, bus_vl_rloop
    addiu $t0, $t0, 8
    lw $v0, 4($s1)
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    ld $s3, 32($sp)
    ld $s4, 40($sp)
    jr $ra
    addiu $sp, $sp, 48

# bench_multi kernel. args = {{target, step}}; a2 = reps left less one. V_INTR = target; at target - 4
# clears the VI interrupt, spins a2 x step iterations, then loops COUNT, MI_INTR, V_CURRENT until it has
# seen both the VI bit and V_CURRENT == target. RES[4] = V_CURRENT read with the first VI bit, RES[5] =
# ticks of the last loop iteration, RES[6] = 1 on a timeout. v0 = COUNT at the VI bit - COUNT at
# V_CURRENT == target + {VINTR_BIAS}. Leaves V_INTR at vi_init's value and the interrupt clear.
k_bus_vintr:
    move $t9, $ra
    move $t8, $a0
    move $t7, $a1
    move $t6, $a2
    sw $zero, 8($t7)
    lw $t3, 0($t8)
    li $t2, 0xA440000C
    sw $t3, 0($t2)
    jal bus_vwait_eq
    addiu $a0, $t3, -4
    beqz $v0, bus_vi_timeout
    nop
    li $t2, 0xA4400010
    sw $zero, 0($t2)
    lw $t4, 4($t8)
    multu $t6, $t4
    mflo $t4
bus_vi_spin:
    bgtz $t4, bus_vi_spin
    addiu $t4, $t4, -1
    li $t0, 0xA4300008
    li $t1, 0xA4400010
    li $a3, {BUS_POLLS}
    move $t5, $zero
bus_vi_loop:
    mfc0 $a0, $count
    lw $a1, 0($t0)
    lw $a2, 0($t1)
    andi $a1, $a1, 8
    beqz $a1, bus_vi_noi
    andi $v1, $t5, 1
    bnez $v1, bus_vi_noi
    nop
    move $t4, $a0
    sw $a2, 0($t7)
    ori $t5, $t5, 1
bus_vi_noi:
    bne $a2, $t3, bus_vi_nov
    andi $v1, $t5, 2
    bnez $v1, bus_vi_nov
    nop
    move $t2, $a0
    ori $t5, $t5, 2
bus_vi_nov:
    xori $v1, $t5, 3
    beqz $v1, bus_vi_both
    mfc0 $v0, $count
    addiu $a3, $a3, -1
    bnez $a3, bus_vi_loop
    nop
bus_vi_timeout:
    addiu $v1, $zero, 1
    sw $v1, 8($t7)
    b bus_vi_end
    move $v0, $zero
bus_vi_both:
    subu $v1, $v0, $a0
    sw $v1, 4($t7)
    subu $v0, $t4, $t2
    addiu $v0, $v0, {VINTR_BIAS}
bus_vi_end:
    li $t0, 0xA440000C
    addiu $t1, $zero, {VI_INIT_V_INTR}
    sw $t1, 0($t0)
    sw $zero, 4($t0)
    jr $t9
    nop

.align 8
bus_vi_init:
{VI_RESTORE}
"""
