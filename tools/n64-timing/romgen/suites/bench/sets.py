"""The bench ROMs romgen builds, one per microbenchmark (README.md)."""
from dataclasses import dataclass, field

from ... import runtime
from . import asm, benches


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    asm: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)


SETS = [SetDef(name, f"bench-{name}", "Bench", f"(bench={name})", build, [asm.ASM],
               {"SCRATCH_BASE": runtime.SCRATCH_BASE})
        for name, build in benches.ROMS.items()]
