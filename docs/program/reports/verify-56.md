## Verify #56 (T7a): PASS-WITH-NOTES

Built base 826e1fb1b and head 1326f3f40 independently (RelWithDebInfo, clang, `--target n64-run`; dirs `build\verify-56-{base,head}`). Same suite driver, same ROMs, both sides.

### Reproduced (raw)
| Check | base | head |
|---|---|---|
| nemu64 timing failed | 909 of 1604 | 453 of 1604 |
| cycle / cop0hazard failed | 9 of 13 / 5 of 5 | 9 of 13 / 5 of 5 |
| categories C2 C3 C4 C5 C8 C9 | 195 172 50 18 21 9 | 0 0 0 0 0 0 |
| C7 / C1 / C6 / C10 | 1 / 439 / 1 / 3 | 10 / 439 / 1 / 3 |
| moved values (timing) | | 465 fixed, 9 broken (cycle, cop0hazard 0 moved) |
| stepcap nemu64 x3 | PASS | PASS |
| stepcap MM | PASS (8138 fields) | PASS (8158 fields) |
| det MM | PASS (27 files) | PASS (27 files, 8158 fields) |
| state-roundtrip + TMEM poke | PASS | PASS |
| `behaviors.py --check`, `lint-literals.py` | | ok, ok |
| `step(` in interpreter-*.cpp | | 0 matches |

The 9 broken values are all Load Miss (VI on x2, VI off x7), as claimed.

### Load Miss experiment
Built head plus one line (`case 0x09: t.gprFields = 0;` for JALR in `opTiming`, scratch worktree, not pushed). Result: timing failed 444 (base 909), 465 fixed, **0 broken**, C7 back to 1. All Load Miss values pass except the one bank-4 value (`80400000`) that also fails on base. So the worker's attribution holds: the LDI stall on the harness's `LD $S3; JALR $S3` moves the loop from the 42 to the 41 pclk phase and exposes the model's missing miss tail. Whether hardware stalls JALR is not independently tested here (inferred from the `LD; JR` rows). The regression is real on the nemu64 mean check and is a model gap, not an LDI bug. Needs a tracked follow-up (miss tail, T6 deviation 6).

### MM 600 fields, interleaved wall
| run | base wall_s (ns/instr) | head wall_s (ns/instr) |
|---|---|---|
| 1 | 11.251 (15.18) | 11.735 (15.99) |
| 2 | 11.124 (15.00) | 12.069 (16.44) |
| 3 | 10.857 (14.65) | 12.284 (16.73) |
| median | 11.124 | 12.069 |

About +8.5% wall, +1.4 ns per instruction, under the ADR's 5 ns budget and the 2 min bar. Head executes 734.1M instructions vs 741.4M (timing moved the schedule). Shared host, 3 runs, so treat as roughly +1 to 1.7 s.

### Code read (pipeline.*, decoder.cpp)
- LDI: raw rs/rt compare, COP1 rt only, LWC1/LDC1/SWC1/SDC1 base only, J/JAL none, MFC0/DMFC0 late via `Cp0Rt`. Matches the cited rows; nemu64 CPU register dependency groups pass.
- FPU forwarding: fs/ft checked on every arithmetic format including one-operand ops, destination never checked. COP1 register dependency passes.
- MULT/DIV and FPU: one cost per op, whole pipe; no hilo scoreboard. Consistent with the HiLoInterlockTiming quote.
- Trivial operands: classes in `fastOperands` match the comment; operands are read at issue, before execute. Exception ops skip retire (`faulted`).
- MTC0 slow regs (1,2,3,7,10) = 2 pclk; likely-nullified bubble in `Pipeline::skip`.
- Dead code: none found; old `OpInfo` and `step(pclk(n))` removed.

### Notes (not blocking)
1. **Inferred rules are not labelled in the spec.** COP2 checks rt only (decoder.cpp case 0x12) and LWC1/LDC1 FPR results using the LDI latency for FPU readers (`Late::LoadFt`) are called inferred only in the worker report. `cpu.ldi` is `vendor` with a `cpu-register-dependency` check; no row or note says these two extensions have no corpus case. They should be `model-choice`/inferred rows or notes in behaviors.tsv.
2. **DCB (`cpu.dcb`) is basis `vendor`** and its check column points at `cpu-register-dependency`, but no corpus case exercises it. The row note should say "no corpus; consistent with Data cache Size loop". The report admits it; the spec does not.
3. `cpu.fpu-trivial` reference text ("operand 0, -0, Inf, qNaN") is narrower than the implemented classes (MUL power-of-two mantissa, SQRT negative, CVT from integer 0). `cpu.fpu-convert` is `measured` while ROUND/TRUNC/CEIL/FLOOR are assumed (stated in the row text).
4. BC1 (COP1 format 8) still carries the rt field check against GPR loads; BC1's rt bits are cc/nd/tf. Unmeasured edge.
5. Unreproducible by me: none. Report numbers matched exactly (bench not rerun).

Raw outputs: `C:\Users\Scott\n64-timing\results\verify-56`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
