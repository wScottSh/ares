"""The hardware output layer: lets a romgen ROM run on a console from a flashcart.

emux (XLOG, XHEXDUMP, XIOCTL) exists only in emulators, so a ROM built with `build.py --hw` replaces
every emux instruction. Each line the runtime prints goes three ways:

- ISViewer: the bytes at 0x13FF0020, then the length to 0x13FF0014 (libdragon's isviewer protocol).
  The fork's n64-run prints them on stdout; a SummerCart64 forwards them over USB
  (`sc64deployer debug --isv 0x03FF0000`).
- Cartridge SRAM: the log is copied to SRAM at 0x08000000 after every line (32 KiB; the ROM header
  declares SRAM through the ED64 homebrew header, bytes 0x3C-0x3F), so a flashcart that saves SRAM to
  its SD card on reset (EverDrive-64 X7, SummerCart64 with N64FlashcartMenu) keeps the whole log.
- The screen: when the ROM ends it shows the log in pages of 26 lines, 8 s per page, looping, for
  the photographed fallback.

The log starts with `#kit rom=<id> sha=<git sha> fmt=1 build=<boot-K or single>` and the RI and MI registers, and ends with
`#kit-end rom=<id> bytes=<n> fnv=<FNV-1a 32 of the n bytes before the footer>`, so ingestion can tell
a complete capture from a cut one. A done word at DATA_BASE + D_HW_DONE lets the fork's runner stop
(calibration/run.sh).
"""
from . import font8x8, runtime

D_HW_LOGPOS = 0x0E0
D_HW_FNV = 0x0E4
D_HW_DONE = 0x0E8
D_HW_SAVE = 0x1700
DONE_MAGIC = 0x600DF00D
LOG = 0xA0488000          # bank 4 above the stack top (0x80480000) and below SCRATCH_BASE: no suite uses it
LOG_SIZE = 0x8000         # 32 KiB SRAM
SRAM = 0x08000000
ISV_BUF = 0xB3FF0020
ISV_LEN = 0xB3FF0014
PI_BASE = 0xA4600000
PI_STATUS = PI_BASE + 0x10
FB = runtime.FB0 | 0xA0000000
PAGE_ROWS = 26           # rows and columns inside a one-glyph margin, which TV overscan keeps visible
COLS = 38
PAGE_FIELDS = 480         # 8 s at 60 fields per second


def header_bytes(rom):
    """ED64 homebrew header (n64brew ROM Header, Advanced Homebrew): 'ED' at 0x3C, save type in the
    high nibble of 0x3F, 3 = SRAM 256 Kbit."""
    rom = bytearray(rom)
    rom[0x3C:0x40] = b"ED\x00\x30"
    return bytes(rom)


def transform(text):
    """Rewrites runtime and suite asm so it uses no emux instruction."""
    flush_old = "    xlog $t2\n    jr $ra\n    sw $t2, 0($t0)\n"
    flush_new = "    sw $t2, 0($t0)\n    j hw_out\n    nop\n"
    text = text.replace(flush_old, flush_new)
    text = text.replace("    xioctl 2\n", "    jal hw_init\n    nop\n    jal hw_header\n    nop\n")
    text = text.replace("    xioctl 1\nhalt:", "    jal hw_finish\n    nop\nhalt:")
    text = text.replace("    xhexdump $t0, $t1\n", "    jal hw_hexdump\n    nop\n")
    text = text.replace("    xioctl 1\n", "    nop\n").replace("    xlog $v0\n", "    nop\n")
    for op in ("xlog", "xhexdump", "xioctl", "xdetect", "xprof"):
        if op + " " in text:
            raise SystemExit(f"--hw: the asm still uses emux {op}; a hardware ROM cannot run it")
    return text


def pi_wait(reg, label):
    return f"""
    li {reg}, {PI_STATUS:#x}
{label}:
    lw $t9, 0({reg})
    andi $t9, $t9, 3
    bnez $t9, {label}
    nop"""


#The log's header registers: the RI state the boot left (cold or warm boot differ) and the VI line.
HEADER_REGS = [("ri_mode", 0xA4700000), ("ri_config", 0xA4700004), ("ri_refresh", 0xA4700010),
               ("ri_latency", 0xA4700014), ("mi_version", 0xA4300004), ("vi_v_current", 0xA4400010)]
#Read back before the footer: hw_out must leave the domain-1 timing the boot set from the ROM header
#(word 0x80371240: LAT 0x40, PWD 0x12, PGS 7, RLS 3), since every PI-timed point runs under it.
PI_REGS = [("dom1_lat", PI_BASE + 0x14), ("dom1_pwd", PI_BASE + 0x18), ("dom1_pgs", PI_BASE + 0x1C),
           ("dom1_rls", PI_BASE + 0x20)]
DOM1_HEADER = {"dom1_lat": 0x40, "dom1_pwd": 0x12, "dom1_pgs": 0x7, "dom1_rls": 0x3}


def regs_asm(label, regs):
    names = "\n".join(f'    .asciiz " {name}="' for name, _ in regs)
    addrs = ", ".join(f"{addr:#x}" for _, addr in regs)
    return f"{label}_names:\n{names}\n.align 4\n{label}_addrs:\n    .word {addrs}"


def asm(rom_id, sha, variant):
    """variant is padded to a fixed width so every boot-delay build keeps one code layout."""
    glyphs = ",".join(f"{g >> 32:#010x},{g & 0xFFFFFFFF:#010x}" for g in font8x8.GLYPHS)
    return rf"""
hw_str_header: .asciiz {runtime.asm_string(f"#kit rom={rom_id} sha={sha} fmt=1 build={variant:<12}")}
hw_str_end: .asciiz {runtime.asm_string(f"#kit-end rom={rom_id} bytes=")}
hw_str_fnv: .asciiz " fnv="
hw_str_hex: .asciiz "#hex "
hw_str_page: .asciiz {runtime.asm_string(f"{rom_id} page ")}
hw_str_pi: .asciiz "#kit-pi"
{regs_asm("hw_regs", HEADER_REGS)}
{regs_asm("hw_pi_regs", PI_REGS)}
.align 8
hw_font:
    .word {glyphs}

# PI domain 2 timing for SRAM (libdragon's values: LAT 5, PWD 12, PGS 13, RLS 2), output state, a
# zeroed log buffer, and the zeroed buffer copied over all of SRAM, so no earlier save's bytes follow
# the log.
hw_init:
    li $t0, {PI_BASE:#x}
    li $t1, 0x05
    sw $t1, 0x24($t0)
    li $t1, 0x0C
    sw $t1, 0x28($t0)
    li $t1, 0x0D
    sw $t1, 0x2C($t0)
    li $t1, 0x02
    sw $t1, 0x30($t0)
    la $t0, DATA_BASE
    sw $zero, {D_HW_LOGPOS}($t0)
    li $t1, 0x811C9DC5
    sw $t1, {D_HW_FNV}($t0)
    sw $zero, {D_HW_DONE}($t0)
    li $t0, {LOG:#x}
    li $t1, {LOG + LOG_SIZE:#x}
hwi_zero:
    sd $zero, 0($t0)
    addiu $t0, $t0, 8
    bne $t0, $t1, hwi_zero
    nop{pi_wait("$t0", "hwi_w1")}
    li $t0, {PI_BASE:#x}
    li $t1, {LOG & 0x1FFFFFFF:#x}
    sw $t1, 0($t0)
    li $t1, {SRAM:#x}
    sw $t1, 4($t0)
    li $t1, {LOG_SIZE - 1:#x}
    sw $t1, 8($t0){pi_wait("$t0", "hwi_w2")}
    jr $ra
    nop

hw_header:
    addiu $sp, $sp, -16
    sd $ra, 0($sp)
    la $a0, hw_str_header
    jal pr_str
    nop
    la $a0, hw_regs_names
    la $a1, hw_regs_addrs
    jal hw_regline
    addiu $a2, $zero, {len(HEADER_REGS)}
    ld $ra, 0($sp)
    jr $ra
    addiu $sp, $sp, 16

# a0 = names (consecutive NUL-terminated " key=" strings), a1 = register addresses, a2 = count:
# appends " key=<hex>" per register to the line, then ends and flushes it.
hw_regline:
    addiu $sp, $sp, -32
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    move $s0, $a0
    move $s1, $a1
    move $s2, $a2
hwr_loop:
    jal pr_str
    move $a0, $s0
hwr_skip:
    lbu $t0, 0($s0)
    bnez $t0, hwr_skip
    addiu $s0, $s0, 1
    lw $t0, 0($s1)
    jal pr_hex
    lw $a0, 0($t0)
    addiu $s2, $s2, -1
    bnez $s2, hwr_loop
    addiu $s1, $s1, 4
    la $a0, str_nl
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

# $t2 = a NUL-terminated string. Appends it to the log and the FNV hash, sends it to the ISViewer,
# and copies the log's new bytes to SRAM. Preserves every register but $t0-$t2 and $at.
hw_out:
    la $t0, DATA_BASE + {D_HW_SAVE}
    sd $a0, 0($t0)
    sd $a1, 8($t0)
    sd $a2, 16($t0)
    sd $a3, 24($t0)
    sd $v0, 32($t0)
    sd $v1, 40($t0)
    sd $t3, 48($t0)
    sd $t4, 56($t0)
    sd $t5, 64($t0)
    sd $t6, 72($t0)
    sd $t7, 80($t0)
    sd $t8, 88($t0)
    sd $t9, 96($t0)
    mfhi $t1
    sd $t1, 104($t0)
    mflo $t1
    sd $t1, 112($t0)
    la $t0, DATA_BASE
    lw $v0, {D_HW_LOGPOS}($t0)
    move $a1, $v0
    lw $a2, {D_HW_FNV}($t0)
    li $a3, 0x01000193
    li $t3, {LOG:#x}
    li $t8, {LOG_SIZE:#x}
    move $t4, $t2
hwo_scan:
    lbu $t5, 0($t4)
    beqz $t5, hwo_scanned
    xor $a2, $a2, $t5
    multu $a2, $a3
    mflo $a2
    sltu $t6, $a1, $t8
    beqz $t6, hwo_full
    addu $t7, $t3, $a1
    sb $t5, 0($t7)
hwo_full:
    addiu $a1, $a1, 1
    b hwo_scan
    addiu $t4, $t4, 1
hwo_scanned:
    sw $a2, {D_HW_FNV}($t0)
    sw $a1, {D_HW_LOGPOS}($t0)
    subu $v1, $t4, $t2
    beqz $v1, hwo_restore
    nop
    li $t3, {ISV_BUF:#x}
    move $t4, $t2
    addiu $t8, $v1, 3
    srl $t8, $t8, 2
hwo_isv:
    lbu $t5, 0($t4)
    lbu $t6, 1($t4)
    lbu $t7, 2($t4)
    lbu $a3, 3($t4)
    sll $t5, $t5, 24
    sll $t6, $t6, 16
    sll $t7, $t7, 8
    or $t5, $t5, $t6
    or $t5, $t5, $t7
    or $t5, $t5, $a3{pi_wait("$a0", "hwo_w1")}
    sw $t5, 0($t3)
    addiu $t3, $t3, 4
    addiu $t8, $t8, -1
    bnez $t8, hwo_isv
    addiu $t4, $t4, 4{pi_wait("$a0", "hwo_w2")}
    li $t3, {ISV_LEN:#x}
    sw $v1, 0($t3)
    li $t8, {LOG_SIZE:#x}
    sltu $t6, $v0, $t8
    beqz $t6, hwo_restore
    sltu $t6, $a1, $t8
    bnez $t6, hwo_end_ok
    nop
    move $a1, $t8
hwo_end_ok:
    li $t6, -8
    and $v0, $v0, $t6
    addiu $a1, $a1, 7
    and $a1, $a1, $t6
    subu $t7, $a1, $v0{pi_wait("$a0", "hwo_w3")}
    li $a0, {PI_BASE:#x}
    li $t3, {LOG & 0x1FFFFFFF:#x}
    addu $t3, $t3, $v0
    sw $t3, 0($a0)
    li $t3, {SRAM:#x}
    addu $t3, $t3, $v0
    sw $t3, 4($a0)
    addiu $t7, $t7, -1
    sw $t7, 8($a0){pi_wait("$a0", "hwo_w4")}
hwo_restore:
    la $t0, DATA_BASE + {D_HW_SAVE}
    ld $t1, 104($t0)
    mthi $t1
    ld $t1, 112($t0)
    mtlo $t1
    ld $a0, 0($t0)
    ld $a1, 8($t0)
    ld $a2, 16($t0)
    ld $a3, 24($t0)
    ld $v0, 32($t0)
    ld $v1, 40($t0)
    ld $t3, 48($t0)
    ld $t4, 56($t0)
    ld $t5, 64($t0)
    ld $t6, 72($t0)
    ld $t7, 80($t0)
    ld $t8, 88($t0)
    jr $ra
    ld $t9, 96($t0)

# a0 = value: appends 8 hex digits to the line buffer.
hw_hex8:
    la $t0, DATA_BASE + D_LINEPOS
    lw $t1, 0($t0)
    li $t2, 8
hwx_loop:
    srl $t3, $a0, 28
    sltiu $t4, $t3, 10
    bnez $t4, hwx_digit
    addiu $t3, $t3, 48
    addiu $t3, $t3, 39
hwx_digit:
    sb $t3, 0($t1)
    sll $a0, $a0, 4
    addiu $t2, $t2, -1
    bnez $t2, hwx_loop
    addiu $t1, $t1, 1
    jr $ra
    sw $t1, 0($t0)

# $t0 = address, $t1 = bytes: "#hex <addr> <8 words>" lines, the XHEXDUMP replacement.
hw_hexdump:
    addiu $sp, $sp, -48
    sd $ra, 0($sp)
    sd $s0, 8($sp)
    sd $s1, 16($sp)
    sd $s2, 24($sp)
    move $s0, $t0
    addu $s1, $t0, $t1
hwd_line:
    sltu $t0, $s0, $s1
    beqz $t0, hwd_done
    nop
    la $a0, hw_str_hex
    jal pr_str
    nop
    jal hw_hex8
    move $a0, $s0
    li $s2, 8
hwd_word:
    sltu $t0, $s0, $s1
    beqz $t0, hwd_eol
    nop
    la $a0, str_space
    jal pr_str
    nop
    jal hw_hex8
    lw $a0, 0($s0)
    addiu $s2, $s2, -1
    bnez $s2, hwd_word
    addiu $s0, $s0, 4
hwd_eol:
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    b hwd_line
    nop
hwd_done:
    ld $ra, 0($sp)
    ld $s0, 8($sp)
    ld $s1, 16($sp)
    ld $s2, 24($sp)
    jr $ra
    addiu $sp, $sp, 48

# The footer, the done word, then the log on screen forever.
hw_finish:
    la $a0, hw_str_pi
    jal pr_str
    nop
    la $a0, hw_pi_regs_names
    la $a1, hw_pi_regs_addrs
    jal hw_regline
    addiu $a2, $zero, {len(PI_REGS)}
    la $t0, DATA_BASE
    lw $s0, {D_HW_LOGPOS}($t0)
    lw $s1, {D_HW_FNV}($t0)
    la $a0, hw_str_end
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s0
    la $a0, hw_str_fnv
    jal pr_str
    nop
    jal hw_hex8
    move $a0, $s1
    la $a0, str_nl
    jal pr_str
    nop
    jal pr_flush
    nop
    la $t0, DATA_BASE
    li $t1, {DONE_MAGIC:#x}
    sw $t1, {D_HW_DONE}($t0)
    jal vi_init
    nop
    move $s2, $zero
    move $s3, $zero
hwf_page:
    li $t0, {FB:#x}
    li $t1, {FB + 320 * 240 * 2:#x}
hwf_clear:
    sd $zero, 0($t0)
    addiu $t0, $t0, 8
    bne $t0, $t1, hwf_clear
    nop
    la $t0, DATA_BASE
    lw $s0, {D_HW_LOGPOS}($t0)
    li $t1, {LOG_SIZE:#x}
    sltu $t2, $s0, $t1
    bnez $t2, hwf_len_ok
    nop
    move $s0, $t1
hwf_len_ok:
    move $s4, $s2
    move $s5, $zero
    move $s6, $zero
hwf_char:
    sltu $t0, $s4, $s0
    beqz $t0, hwf_last
    nop
    li $t0, {LOG:#x}
    addu $t0, $t0, $s4
    lbu $a0, 0($t0)
    addiu $s4, $s4, 1
    li $t1, 10
    beq $a0, $t1, hwf_newline
    nop
    move $a1, $s5
    jal hw_glyph
    move $a2, $s6
    addiu $s5, $s5, 1
    li $t1, {COLS}
    bne $s5, $t1, hwf_char
    nop
hwf_newline:
    move $s5, $zero
    addiu $s6, $s6, 1
    li $t1, {PAGE_ROWS}
    bne $s6, $t1, hwf_char
    nop
    b hwf_status
    nop
hwf_last:
    move $s4, $zero
hwf_status:
    addiu $s3, $s3, 1
    la $t0, DATA_BASE + D_LINEBUF
    la $t1, DATA_BASE + D_LINEPOS
    sw $t0, 0($t1)
    la $a0, hw_str_page
    jal pr_str
    nop
    jal pr_dec
    move $a0, $s3
    la $t0, DATA_BASE + D_LINEPOS
    lw $t1, 0($t0)
    sb $zero, 0($t1)
    la $s7, DATA_BASE + D_LINEBUF
    sw $s7, 0($t0)
    move $s5, $zero
hwf_status_char:
    lbu $a0, 0($s7)
    beqz $a0, hwf_wait
    move $a1, $s5
    li $a2, {PAGE_ROWS}
    jal hw_glyph
    nop
    addiu $s7, $s7, 1
    b hwf_status_char
    addiu $s5, $s5, 1
hwf_wait:
    move $s2, $s4
    bnez $s2, hwf_hold
    nop
    move $s3, $zero
hwf_hold:
    li $s5, {PAGE_FIELDS}
    li $t0, 0xA4400010
hwf_field_hi:
    lw $t1, 0($t0)
    sltiu $t1, $t1, 100
    bnez $t1, hwf_field_hi
    nop
hwf_field_lo:
    lw $t1, 0($t0)
    sltiu $t1, $t1, 10
    beqz $t1, hwf_field_lo
    nop
    addiu $s5, $s5, -1
    bnez $s5, hwf_field_hi
    nop
    b hwf_page
    nop

# a0 = character, a1 = column, a2 = row inside the margin: draws it white on black into FB0 (RGBA5551).
hw_glyph:
    addiu $a1, $a1, 1
    addiu $a2, $a2, 1
    addiu $a0, $a0, -32
    sltiu $t0, $a0, 95
    bnez $t0, hwg_ok
    nop
    li $a0, 31
hwg_ok:
    sll $a0, $a0, 3
    la $t0, hw_font
    addu $t0, $t0, $a0
    li $t1, {320 * 8 * 2}
    multu $a2, $t1
    mflo $t1
    sll $t2, $a1, 4
    addu $t1, $t1, $t2
    li $t2, {FB:#x}
    addu $t1, $t1, $t2
    li $t2, 8
hwg_row:
    lbu $t3, 0($t0)
    li $t4, 0x80
    move $t5, $t1
hwg_px:
    and $t6, $t3, $t4
    beqz $t6, hwg_dark
    ori $t7, $zero, 0x0001
    ori $t7, $zero, 0xFFFF
hwg_dark:
    sh $t7, 0($t5)
    srl $t4, $t4, 1
    bnez $t4, hwg_px
    addiu $t5, $t5, 2
    addiu $t0, $t0, 1
    addiu $t2, $t2, -1
    bnez $t2, hwg_row
    addiu $t1, $t1, 640
    jr $ra
    nop
"""
