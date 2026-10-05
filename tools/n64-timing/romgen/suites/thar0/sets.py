"""The Thar0 RDP timing ROM. RUNS is the per-spec run count (the original's TOTAL_RUNS is
1000); override it with build.py --define RUNS=N."""
from dataclasses import dataclass, field

from ... import rcp
from . import thar0


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    asm: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)
    payload_limit: int = thar0.PAYLOAD_LIMIT


CONSTS = dict(rcp.CONSTS, RUNS=32, RESULTS=thar0.RESULTS, BASELINE=thar0.BASELINE,
              RUN_DL=thar0.RUN_DL)

SETS = [SetDef("rdp", "thar0-rdp", "Thar0", "(thar0 rdp-timing-tests a81ced93b28d)",
               thar0.build,
               [rcp.ASM, thar0.ASM], CONSTS)]
