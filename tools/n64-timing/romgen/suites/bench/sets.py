"""The bench ROMs romgen builds, one per microbenchmark, layout pad and boot delay (README.md, phases.py)."""
from dataclasses import dataclass, field

from ... import runtime
from . import asm, benches, phases
from ..calib import bus

#Kernels of a module that imports benches, so benches.ROM_ASM cannot name them.
EXTRA_ASM = {"vi-frame-latch": [bus.ASM]}


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    asm: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)

    def __post_init__(self):
        self.asm = self.asm + benches.ROM_ASM.get(self.set_name, [])


SETS = [SetDef(name, f"{phases.point_dir(p, k)}/bench-{name}", "Bench", f"(bench={name})", build,
               [asm.ASM] + EXTRA_ASM.get(name, []),
               {"SCRATCH_BASE": runtime.SCRATCH_BASE, "BOOT_DELAY": k, "LAYOUT_PAD": p})
        for p, k in phases.POINTS for name, build in benches.ROMS.items()]
