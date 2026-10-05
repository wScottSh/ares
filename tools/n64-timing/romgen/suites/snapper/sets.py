"""The snapper ROMs: one per ported snapper64 test family (README.md)."""
from dataclasses import dataclass, field
from functools import cached_property

from ... import runtime
from ...suite import Test, Value
from ..rdpstat import routines
from . import asm, cases


@dataclass
class SetDef:
    set_name: str
    rom_name: str
    category: str
    banner_flags: str
    make: object                  # (Lists) -> [Case]
    consts: dict = field(default_factory=lambda: {"DUMP": 0})

    @cached_property
    def _built(self):
        lists = cases.Lists(self.set_name.replace("-", "_"))
        return self.make(lists), lists.all()

    @property
    def cases(self):
        return self._built[0]

    @property
    def asm(self):
        case_list, lists = self._built
        parts = [routines.ASM, asm.ASM, "\n".join([
            f"str_snap: .asciiz {runtime.asm_string('@snap ')}",
            f"str_snap_sep: .asciiz {runtime.asm_string(' ')}",
            f"str_snap_nl: .asciiz {runtime.asm_string(chr(10))}"])]
        parts += [lst.asm() for lst in lists]
        parts.append("\n".join(f"{name_label(rec)}: .asciiz {runtime.asm_string(rec.id)}"
                               for c in case_list for rec in c.records))
        if self.set_name == "test-mode-rw":
            parts.append(rw_data_asm())
        return parts

    def build(self, suite):
        tests = {}
        for c in self.cases:
            steps = c.steps + [cases.emit(rec, name_label(rec)) for rec in c.records]
            tests.setdefault(c.group, []).append(Value(f" [{c.name}]", steps, []))
        suite.tests += [Test(group, values) for group, values in tests.items()]


def name_label(rec):
    return f"snap_{rec.id}"


def rw_data_asm():
    out = [".align 4"]
    for val_type in range(4):
        words = cases.rw_data(val_type)
        out.append(f"rw_data_{val_type}:")
        for i in range(0, len(words), 16):
            out.append("    .word " + ", ".join(str(w) for w in words[i:i + 16]))
    return "\n".join(out)


SETS = [
    SetDef("span-tri", "snapper-span-tri", "Snapper", "(snapper: RDP Test-Mode Span Tri)",
           cases.span_tri),
    SetDef("test-mode-rw", "snapper-test-mode-rw", "Snapper", "(snapper: RDP Test-Mode R/W)",
           lambda lists: cases.rw_cases()),
    SetDef("fill-tri-sweep", "snapper-fill-tri-sweep", "Snapper",
           "(snapper: RDP Fill Mode Tri Sweep)", cases.fill_tri_sweep),
    SetDef("rect-nosync", "snapper-rect-nosync", "Snapper", "(snapper: RDP Rect No-Sync)",
           cases.rect_nosync),
]
