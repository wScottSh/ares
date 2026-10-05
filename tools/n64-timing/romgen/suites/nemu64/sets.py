"""The nemu64-test feature sets romgen builds, one ROM each."""
from dataclasses import dataclass, field

from ... import runtime
from . import measure, routines, timing


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
]
