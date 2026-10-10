"""Fork-authored CPU ROMs. Each checks the VR4300 User's Manual's stated result, not a timing."""
from ..nemu64 import routines
from ..nemu64.sets import CONSTS, SetDef
from . import llsc

SETS = [
    SetDef("llsc", "cpu-llsc", "CPU", "(cpu: SC/SCD against U10504EJ7V0UM00)",
           llsc.build, [routines.COMMON, llsc.asm()], CONSTS),
]
