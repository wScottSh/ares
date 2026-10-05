"""The rdpstat ROMs: n64-systemtest's RDP tests, DPC DMA sequencing, and repeater64's no-sync demos."""
import os
from dataclasses import dataclass, field

from . import dpc, repeater64, routines, systemtest


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    build: object
    lists: list
    data: object = None          # () -> asm text, read only when this set is built
    consts: dict = field(default_factory=dict)

    @property
    def asm(self):
        parts = [routines.ASM] + [lst.asm() for lst in self.lists]
        if self.data:
            parts.append(self.data())
        return parts


def repeater64_data():
    assets = os.environ.get("REPEATER64_ASSETS", repeater64.DEFAULT_ASSETS)
    return repeater64.reference_asm(assets) + "\n" + repeater64.FILL_EXPECTED_ASM


SETS = [
    SetDef("systemtest", "rdpstat-systemtest", "RDP-status", "(rdpstat: n64-systemtest tests/rdp)",
           systemtest.build, systemtest.LISTS),
    SetDef("dpc", "rdpstat-dpc", "DPC-sequencing", "(rdpstat: DMA_BUSY, END_PENDING)",
           dpc.build, dpc.LISTS),
    SetDef("repeater64", "rdpstat-repeater64", "RDP-pixels", "(rdpstat: repeater64 no-sync)",
           repeater64.build, repeater64.LISTS, repeater64_data),
]
