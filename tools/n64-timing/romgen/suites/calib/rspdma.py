"""SP DMAs of 8-128 B started and timed by the RSP on its own clock (kit-dma, question sp-dma-rsp).

The CPU's busy poll quantizes one small SP DMA to its 26 pclk period, and a CPU-queued chain runs at
the CPU's register-write rate, so neither times an 8-128 B DMA (questions.tsv sp-dma-direction). Here
an RSP program writes SP_MEM_ADDR and SP_DRAM_ADDR, reads DPC_CLOCK (COP0 $12), writes the length
register, polls SP_DMA_BUSY (COP0 $6) and reads DPC_CLOCK again. DPC_CLOCK counts RCP clocks, the
RSP's own clock (nemu64-test rsp_timing ClockCPUvsRSP, CyclesSLL). Each run walks the poll's phase:
block s puts s extra NOPs between the length write and the first poll, so one block's first poll
lands on the first idle clock for any poll period up to WALK. The point records the least and greatest
block (min and walk_max), in RCP clocks.
"""
from ... import mips
from ..bench.benches import SP_DMA_BUF, VI_OFF, Rom

WALK = 8                # >= the 6 rclk poll period (questions.tsv sp-dma-rsp)
SIZES = [8, 16, 32, 64, 128]
DMEM_TARGET = 0x800
RESULTS = 0x10
# The RSP's COP0 registers: SP_MEM_ADDR, SP_DRAM_ADDR, SP_RD_LEN, SP_WR_LEN, SP_DMA_BUSY, DPC_CLOCK.
MEM_ADDR, DRAM_ADDR, RD_LEN, WR_LEN, DMA_BUSY, CLOCK = 0, 1, 2, 3, 6, 12
# rd is RDRAM to DMEM (SP_RD_LEN), wr is DMEM to RDRAM; poll rewrites SP_DRAM_ADDR, which starts no DMA.
TRIGGERS = {"rd": f"mtc0 $t1, ${RD_LEN}", "wr": f"mtc0 $t1, ${WR_LEN}", "poll": f"mtc0 $t0, ${DRAM_ADDR}"}


def program(trigger):
    """RSP code for one direction; DMEM 0 = {DRAM address, length - 1}, results at DMEM RESULTS.
    The RSP counts MTC0 and MFC0 as both a load and a store and stalls a store two slots after a
    load (n64brew Reality_Signal_Processor/CPU_Pipeline), so NOPs keep them apart."""
    lines = ["lw $t0, 0($zero)", "lw $t1, 4($zero)", f"addiu $t4, $zero, {DMEM_TARGET}", "nop", "nop"]
    for s in range(WALK):
        lines += [f"mtc0 $t4, ${MEM_ADDR}", f"mtc0 $t0, ${DRAM_ADDR}", "nop", "nop", f"mfc0 $t5, ${CLOCK}",
                  trigger, "nop", "nop"] + ["nop"] * s
        poll = 4 * len(lines)
        lines += [f"mfc0 $t6, ${DMA_BUSY}", f"bne $t6, $zero, {poll}", "nop",
                  f"mfc0 $t7, ${CLOCK}", "subu $t7, $t7, $t5", f"sw $t7, {RESULTS + 4 * s}($zero)"]
    lines.append("break")
    return [w for i, text in enumerate(lines) for w in mips.assemble_one(text, 4 * i)]


ASM = f"""
# args = {{program, words, DRAM address, length - 1}}. Loads the RSP program into IMEM and its
# arguments into DMEM, runs it from PC 0 until its BREAK halts the RSP, and returns the least of its
# {WALK} DPC_CLOCK deltas (24 bit); RES[2] = the greatest.
k_rsp_dma:
    li $t4, 0xA4040000
krd_idle:
    lw $t5, 0x18($t4)
    bnez $t5, krd_idle
    nop
    lw $t0, 0($a0)
    lw $t1, 4($a0)
    li $t2, 0xA4001000
krd_copy:
    lw $t3, 0($t0)
    sw $t3, 0($t2)
    addiu $t0, $t0, 4
    addiu $t1, $t1, -1
    bnez $t1, krd_copy
    addiu $t2, $t2, 4
    li $t2, 0xA4000000
    lw $t3, 8($a0)
    sw $t3, 0($t2)
    lw $t3, 12($a0)
    sw $t3, 4($t2)
    li $t3, 0xA4080000
    sw $zero, 0($t3)
    # clear HALT, BROKE, the SP interrupt, single step and interrupt on break
    li $t3, 0xAD
    sw $t3, 0x10($t4)
krd_run:
    lw $t3, 0x10($t4)
    andi $t3, $t3, 1
    beqz $t3, krd_run
    nop
    li $t9, 0xFFFFFF
    addiu $v0, $zero, -1
    move $t6, $zero
    addiu $t2, $t2, {RESULTS}
    li $t7, {WALK}
krd_scan:
    lw $t3, 0($t2)
    and $t3, $t3, $t9
    sltu $t5, $t3, $v0
    beqz $t5, krd_nomin
    nop
    move $v0, $t3
krd_nomin:
    sltu $t5, $t6, $t3
    beqz $t5, krd_nomax
    nop
    move $t6, $t3
krd_nomax:
    addiu $t7, $t7, -1
    bnez $t7, krd_scan
    addiu $t2, $t2, 4
    jr $ra
    sw $t6, 0($a1)
"""


def sp_dma_rsp(suite):
    rom = Rom(suite, "sp-dma-rsp")
    for direction in ("poll", "rd", "wr"):
        code = program(TRIGGERS[direction])
        label = suite.blob(code)
        for size in [0] if direction == "poll" else SIZES:
            rom.point(f"{direction}-{size}" if size else direction, "k_rsp_dma",
                      [label, len(code), SP_DMA_BUF, max(size, 8) - 1],
                      [("bytes", size), ("dir", direction), ("walk", WALK), ("unit", "rclk")],
                      flags=VI_OFF, extra=["walk_max"])


BUILDERS = [sp_dma_rsp]
