"""The nemu64-test feature sets romgen builds, one ROM each."""
from dataclasses import dataclass, field
from functools import partial

from ... import runtime
from . import cop0hazard, cycle, measure, phases, routines, timing


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    asm: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)
    hw_asm: list = None   # the console build's asm (build.py --hw), when it differs from asm


CONSTS = {"SCRATCH_BASE": runtime.SCRATCH_BASE}

SETS = [
    SetDef("timing", "nemu64-timing", "Timing", "(base=0 timing=1 cycle=0 cp0-hazards=0)",
           timing.build, [routines.COMMON, routines.TIMING, measure.asm()], CONSTS,
           [routines.COMMON, routines.TIMING, measure.asm_with_hist()]),
    SetDef("cycle", "nemu64-cycle", "Cycle", "(base=0 timing=0 cycle=1 cp0-hazards=0)",
           cycle.build, [routines.COMMON, cycle.ASM, measure.asm()], CONSTS),
    SetDef("cop0hazard", "nemu64-cop0hazard", "CP0-hazards", "(base=0 timing=0 cycle=0 cp0-hazards=1)",
           cop0hazard.build, [routines.COMMON, cop0hazard.ASM, measure.asm()], CONSTS),
] + [
    SetDef("timing-phase", f"phase-{k}/nemu64-timing", "Timing", "(base=0 timing=1 cycle=0 cp0-hazards=0)",
           timing.build_averaged, [routines.COMMON, routines.TIMING, measure.asm(phase=True)],
           {**CONSTS, "PHASE_DELAY": k})
    for k in phases.DELAYS
] + [
    SetDef("timing-phase-2022", f"phase-{k}/nemu64-timing-2022", "Timing", "(base=0 timing=1 cycle=0 cp0-hazards=0)",
           partial(timing.build_averaged, layout=measure.LAYOUT_2022),
           [routines.COMMON, routines.TIMING, measure.asm(phase=True, layout=measure.LAYOUT_2022)],
           {**CONSTS, "PHASE_DELAY": k})
    for k in phases.DELAYS
]
