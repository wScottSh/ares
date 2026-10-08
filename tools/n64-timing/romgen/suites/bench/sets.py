"""The bench ROMs romgen builds, one per microbenchmark and boot delay (README.md, phases.py)."""
from dataclasses import dataclass, field

from ... import runtime
from . import asm, benches, phases


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    asm: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)


SETS = [SetDef(name, f"boot-{k}/bench-{name}", "Bench", f"(bench={name})", build, [asm.ASM],
               {"SCRATCH_BASE": runtime.SCRATCH_BASE, "BOOT_DELAY": k})
        for k in phases.DELAYS for name, build in benches.ROMS.items()]
