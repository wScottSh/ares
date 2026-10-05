# verify-42 (R3, PR #42)

Worktree: ares-wt/verify-42. PR comment: https://github.com/wScottSh/ares/pull/42#issuecomment-5997429789

## Independent verification of #42 (R3, snapper64 suite): PASS-WITH-NOTES

Head 3e2cda0a0 (2 commits, 14 files, tools only; targets master). Emulator under test: a fresh build of feat/t10 head 15abbcb28 (`build/verify-43`). Raw outputs: `C:\Users\Scott\n64-timing\verify\verify-42\`.

### Results (all measured by me)
| Check | Result |
|---|---|
| Deterministic build | `build.py --suite snapper` run twice into separate dirs: all 4 ROMs byte-identical between runs, and byte-identical to the worker's ROMs (sha256 prefixes: span-tri 58dc789f, test-mode-rw d6028970, fill-tri-sweep efc58134, rect-nosync fe84a2e3) |
| Corpus | `corpora/snapper64` HEAD = e1cd8a61fc43e87915c5f6b5cceb3493ef0a030f; 7094 `.test` files; one archive re-extracted with Windows tar.exe and `cmp`'d to the decoded file: identical |
| Digest pins | `compare.py --print-digest` for span-tri, fill-tri-sweep, rect-nosync equals `REFERENCE_DIGEST` in all three; the compare run refuses on mismatch and did not |
| Rerun on feat/t10 build, two runs per set | stdout byte-identical between runs; `records.tsv` identical |
| span-tri | **432/432** match (report: 431/432) |
| test-mode-rw | 32/32 |
| fill-tri-sweep | 2048/2048 |
| rect-nosync | 1C 20/20, 2C 40/40, Fill 20/20 (80/80) |
| T9 binary (`n64-run-t9-after.exe --rdp soft`) on the same ROM | 431/432; the miss is `2A1ADF69_D1E50CBB_02` (24 differing pixels), exactly as the report says |
| Independent byte compare, built with `--define DUMP=1` | rect-nosync: 80/80 records fully dumped and byte-identical to the `.test` files (e.g. 85010AAF_0BD98B10_01, AE2C596C_11D8DDE7_01, EC81FD4F_FFD6BCCB_01, 207360 B each); span-tri: 432/432 byte-identical (e.g. 2A1ADF69_00E48291_01 19456 B, 2A1ADF69_FC6AC063_02 512 B). Also the FNV-1a over 3 sampled fill-tri-sweep dump files equals the ROM's `@snap` hash |

The 432 vs 431 gap is T10 versus T9, not an R3 defect. A scratch build of T10 with the DMEM byteswap reverted still gives 432/432, so the byteswap does not explain the fix; I did not isolate which T10 change (hazard publish order, DPS arm, or other engine delta) fixes the Tri 0 span record. Unattributed.

### Notes
1. `suites/snapper/run.sh` (and rdpstat `run.sh` on feat/r4) pass `--rdp MODE` to `n64-run`; T10 removes that option, so after the stack lands both scripts print usage and fail. I ran the ROMs directly. Needs a follow-up edit when T10 lands.
2. "match" for records that are not dumped is on-target FNV-1a 32 equality (disclosed in the report); I closed that gap for rect-nosync and span-tri above with full-byte compares. fill-tri-sweep (2048 x 64 KiB) full-byte compare not run.
3. test-mode-rw expectations come from the source assertion, not console dumps (disclosed); not independently checkable.
4. No C++ touched; diff vs master is under `tools/n64-timing/romgen` only (14 files).

Verdict: PASS-WITH-NOTES.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
