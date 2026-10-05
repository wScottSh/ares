"""Suite model: tests -> values -> steps + checks, emitted as runtime tables."""
from dataclasses import dataclass, field

from . import runtime


@dataclass
class Check:
    op: int
    a: int
    b: int = 0
    c: int = 0
    d: int = 0
    msg: str = ""


@dataclass
class Step:
    routine: str
    params: list          # words; str entries are assembler expressions (labels)
    res: int = 0


def checkpoint(checks):
    """A step that runs `checks` where it stands. The first failure ends the value, the way a
    Rust `?` returns before the rest of the test runs (and before its side effects)."""
    return Step("step_checks", [len(checks), *checks], 0)


@dataclass
class Value:
    desc: str
    steps: list
    checks: list
    full_desc: str = None

    def expected_cycles(self):
        return [c.d for c in self.checks if c.op == runtime.CHK_SUM_DEC]


@dataclass
class Test:
    name: str
    values: list


@dataclass
class Suite:
    rom_name: str
    category: str
    banner_flags: str
    tests: list = field(default_factory=list)
    asm: list = field(default_factory=list)     # extra runtime routines
    blobs: dict = field(default_factory=dict)   # label -> list of words (deduplicated)
    _blob_index: dict = field(default_factory=dict)

    def blob(self, words):
        """Interns a word list (code body or data) and returns its label."""
        key = tuple(w & 0xFFFFFFFF for w in words)
        label = self._blob_index.get(key)
        if label is None:
            label = f"blob_{len(self._blob_index)}"
            self._blob_index[key] = label
            self.blobs[label] = list(key)
        return label

    def value_count(self):
        return sum(len(t.values) for t in self.tests)

    def emit(self):
        """Returns assembler text for the tables, strings and blobs."""
        strings = {}

        def s(text):
            if text not in strings:
                strings[text] = f"str_{len(strings)}"
            return strings[text]

        out = [".align 4", "suite_tests:", f"    .word {len(self.tests)}"]
        for ti, t in enumerate(self.tests):
            out.append(f"    .word {s(t.name)}, {len(t.values)}, t{ti}_values")
        for ti, t in enumerate(self.tests):
            out.append(f"t{ti}_values:")
            for vi, v in enumerate(t.values):
                out.append(f"    .word {s(v.desc)}, {len(v.steps)}, t{ti}v{vi}_steps, "
                           f"{len(v.checks)}, t{ti}v{vi}_checks")
            for vi, v in enumerate(t.values):
                out.append(f"t{ti}v{vi}_steps:")
                for si, st in enumerate(v.steps):
                    out.append(f"    .word {st.routine}, t{ti}v{vi}s{si}_params, {st.res}")
                out.append(f"t{ti}v{vi}_checks:")
                for c in v.checks:
                    out.append(f"    .word {c.op}, {c.a}, {c.b & 0xFFFFFFFF}, {c.c & 0xFFFFFFFF}, "
                               f"{c.d & 0xFFFFFFFF}, {s(c.msg)}")
                for si, st in enumerate(v.steps):
                    out.append(f"t{ti}v{vi}s{si}_params:")
                    words = []
                    for p in st.params:
                        if isinstance(p, Check):
                            words += [str(p.op), str(p.a), str(p.b & 0xFFFFFFFF),
                                      str(p.c & 0xFFFFFFFF), str(p.d & 0xFFFFFFFF), s(p.msg)]
                        else:
                            words.append(p if isinstance(p, str) else str(p & 0xFFFFFFFF))
                    if words:
                        out.append("    .word " + ", ".join(words))
        out.append(".align 4")
        for label, words in self.blobs.items():
            out.append(f"{label}:")
            for i in range(0, len(words), 16):
                out.append("    .word " + ", ".join(str(w) for w in words[i:i + 16]))
        out.append(f"str_summary_head: .asciiz {runtime.asm_string(chr(10) + 'n64-systemtest 3.0.0 romgen port ' + self.banner_flags + chr(10) + 'Finished in ')}")
        out.append(f"str_summary_mid: .asciiz {runtime.asm_string('s. ' + self.category + ': Failed ')}")
        for name, text in runtime.STRINGS.items():
            out.append(f"{name}: .asciiz {runtime.asm_string(text)}")
        for text, label in strings.items():
            out.append(f"{label}: .asciiz {runtime.asm_string(text)}")
        out.append(".align 4")
        out.append("exception_names:")
        names = []
        for code in range(32):
            names.append(f"exc_name_{code}")
        out.append("    .word " + ", ".join(names))
        for code in range(32):
            name = runtime.EXCEPTION_NAMES.get(code, f"{code:#x}")
            out.append(f"exc_name_{code}: .asciiz {runtime.asm_string(name)}")
        return "\n".join(out)
