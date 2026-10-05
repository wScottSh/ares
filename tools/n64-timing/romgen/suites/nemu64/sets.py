"""The nemu64-test feature sets romgen builds, one ROM each."""
from dataclasses import dataclass, field

from ... import runtime
from . import cop0hazard, cycle, measure, routines, timing


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    asm: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)


CONSTS = {"SCRATCH_BASE": runtime.SCRATCH_BASE}

SETS = [
    SetDef("timing", "nemu64-timing", "Timing", "(base=0 timing=1 cycle=0 cp0-hazards=0)",
           timing.build, [routines.COMMON, routines.TIMING, measure.loop_templates_asm()], CONSTS),
    SetDef("cycle", "nemu64-cycle", "Cycle", "(base=0 timing=0 cycle=1 cp0-hazards=0)",
           cycle.build, [routines.COMMON, cycle.ASM, measure.loop_templates_asm()], CONSTS),
    SetDef("cop0hazard", "nemu64-cop0hazard", "CP0-hazards", "(base=0 timing=0 cycle=0 cp0-hazards=1)",
           cop0hazard.build, [routines.COMMON, cop0hazard.ASM, measure.loop_templates_asm()], CONSTS),
]
