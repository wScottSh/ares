"""Back-to-back dirty D-cache line writebacks, VI off (kit-dma, question block-write-slope; prehw-plan.md U-OP-SLOPE-DMA).

The cached memset's steady state, N = 16 and N = 64 lines at a time. Untimed, the kernel dirties the N 16 B lines at
A (two SDs each) and drains the write buffer with an uncached load. Timed, it stores two SDs to each of the N lines
8 KiB on: every first SD misses the 8 KiB direct-mapped D-cache at a dirty line's index, so the line fills and the
dirty victim at A is written back, and the next line's fill waits for that write's EOK. The N = 64 less N = 16 COUNT
is 48 such lines, and every constant term (the first line's fill, the last victim still buffered at the closing mfc0)
cancels, as in repeat-write (repeat.py).
"""
from ..bench.benches import KSEG0, KSEG1, MEMSET_BUF, VI_OFF, Rom

NS = [16, 64]
DCACHE = 0x2000
LINE = 16


def kernel(n):
    return f"k_bws_memset_cached_{n}"


def memset_cached_kernel(n):
    dirty = "\n".join(f"    sd $zero, {i * LINE}($t0)\n    sd $zero, {i * LINE + 8}($t0)" for i in range(n))
    timed = "\n".join(f"    sd $zero, {i * LINE}($t1)\n    sd $zero, {i * LINE + 8}($t1)" for i in range(n))
    return f"""
# args = {{A (KSEG0), an uncached word}}: dirties the {n} lines at A, drains, then times {n} line stores 8 KiB on.
{kernel(n)}:
    lw $t0, 0($a0)
    lw $t2, 4($a0)
    li $t1, {DCACHE:#x}
    addu $t1, $t0, $t1
{dirty}
    lw $t3, 0($t2)
    mfc0 $t8, $count
{timed}
    mfc0 $t9, $count
    jr $ra
    subu $v0, $t9, $t8
"""


ASM = "\n".join(memset_cached_kernel(n) for n in NS)


def block_write_slope(suite):
    rom = Rom(suite, "block-write-slope")
    for n in NS:
        rom.point(f"memset-cached-n{n}", kernel(n), [KSEG0 | MEMSET_BUF, KSEG1 | MEMSET_BUF],
                  [("op", "memset-cached"), ("n", n), ("vi", "off")], reps=8, flags=VI_OFF)


BUILDERS = [block_write_slope]
