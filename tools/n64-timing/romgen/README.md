# romgen

romgen generates self-checking N64 test ROMs from Python in this repository. It needs Python 3 and libdragon's public-domain `ipl3_compat.z64` boot stub, and no other toolchain. The first suite is a port of nemu64-test's `timing`, `cycle` and `cop0hazard` feature sets.

## Commands

Run these from the repository root.

```sh
python tools/n64-timing/romgen/build.py --suite nemu64 --out $N64_TIMING_HOME/roms
N64_RUN=<path to n64-run.exe> tools/n64-timing/run-nemu64.sh --cpu interpreter
python tools/n64-timing/romgen/selftest.py
```

- `build.py` writes `nemu64-{timing,cycle,cop0hazard}.z64` and a `<rom>.tests.tsv` listing per ROM. A rebuild from the same sources produces byte-identical files. `--ipl3` overrides the default stub path, `$N64_TIMING_HOME/scratch/r29/clones/libdragon/boot/bin/ipl3_compat.z64`.
- `run-nemu64.sh` runs each ROM through `n64-run`. It prints the ROM's own `Timing: Failed X of Y tests` line, or the `Cycle` or `CP0-hazards` line. It also writes `values.tsv`, one row per test value with the result and the measured and expected cycles. For the timing ROM, it writes `categories.tsv`, which assigns each failure to a root-cause category C1-C11 from `docs/research/nemu64-timing-failures.md`. `N64_RUN` defaults to the runner built from the current worktree (`tools/n64-timing/build.sh`).
- `selftest.py` checks the assembler against encodings worked out by hand from the VR4300 User's Manual instruction chapters (16 and 17). It also checks the nemu64-compatible encoder API against the text assembler.

## Layout

| Module | Role |
|---|---|
| `mips.py` | VR4300 encoder and two-pass text assembler, with labels, `.word`/`.asciiz`-style directives and the `li`, `la` and `dla` pseudo-instructions |
| `runtime.py` | On-target runtime: boot, exception vectors, a table-driven test runner, output through emux `XLOG`, and the cycle-measurement harness |
| `suite.py` | Suite model. A test has values. A value runs steps, which are runtime routines that write raw results into `RES[]`, and then checks over `RES[]`. `checkpoint()` runs checks between steps. |
| `nemu.py` | Python port of the nemu64-test types the tables use (`Assembler`, `GPR`, `Status`, `FCSR`, float literals) |
| `import_nemu64.py` | Translates the Rust value tables in `src/tests/timing/mod.rs` into `suites/nemu64/tables.py`. It reads the source as text and never compiles or runs it. |
| `suites/nemu64/` | Ported `run()` logic per feature set (`timing.py`, `cycle.py`, `cop0hazard.py`), routines, value descriptions, and the root-cause classifier |
| `report.py` | Joins a ROM's `@<test>.<value>` records with its `.tests.tsv` listing |

The ROM decides pass or fail by itself and prints nemu64-test's output format. The host side only parses output.

## Port notes

These are the places where the port is not a direct translation of the Rust source.

- The Rust tests call `run()` code compiled by rustc. The port keeps the inline-asm instruction sequences and the generated measurement programs word for word. The Rust glue code around them (loops, comparisons, allocation) becomes runtime code. Timing in the glue code differs, and no test observes it.
- Inline-asm operands that the compiler allocates (`in(reg)`, `out(reg)`) get fixed registers in the port.
- `dla` expands to LLVM's six-instruction sequence for the n64 ABI without `$at`. This expansion was inferred from LLVM's MIPS assembler and not checked against a rustc build. The interrupt hazard tests run it between their CP0 writes.
- A Rust `?` ends a test at its first failed assertion, before the rest of the test runs. Where the rest has side effects, the port puts a `checkpoint()` step at the same place. An example is `CountHazards`, whose later COUNT values carry COUNT past Compare and raise IP7.
- Exception context fields are compared on their low 32 bits.
- Heap buffers (`UncachedHeapMemory`) are at a fixed `SCRATCH_BASE` with the same alignment.

## Attribution

The `nemu64` suite is a port of [nemu64-test](https://github.com/thelemmy/nemu64-test) at commit `9a8b9f7`. `suites/nemu64/tables.py` is generated from its source, and the test logic in `suites/nemu64/` follows its `src/tests`. nemu64-test is distributed under the MIT License. A copy is in `suites/nemu64/LICENSE.nemu64-test`:

```text
MIT License

Copyright (c) 2021 lemmy-64

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
