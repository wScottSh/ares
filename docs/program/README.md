# Timing-model program store

This directory is a snapshot of the orchestration store that drives the map #1 build: the hardware-accurate N64 timing model. The live copy lives outside the repo at `~/.claude/orchestrate/ares-n64-timing/`. This copy lets the work resume on another machine.

- `preferences.md` holds the standing orders. Every worker brief points at them. The top line is the current STOP order.
- `units.tsv` lists every unit and its state, and `status.md` is generated from it.
- `decisions.tsv` is the decision log: one row per decision, with its evidence.
- `reports/` holds each unit's worker report and each independent verification verdict (`verify-<pr>.md`).
- `briefs/` holds the templates the coordinator spawns workers and verifiers from. `build-common.md` covers build units and `verify-pr.md` covers verifiers.
- `followups.md` lists minor issues parked for a cleanup unit.
- `resolve.sh` and `map_add.py` close a ticket and append its gist to map #1.

The plan of record is `docs/design/timing-core/plan.md`, the design is `docs/adr/0001-timing-core.md`, and the spec as built is `docs/spec/n64-timing.md`. The research docs live in `docs/research/`.

To resume on a new machine, copy this directory to `~/.claude/orchestrate/ares-n64-timing/`, read `handoff.md` if it exists, and start the next unit in `plan.md` from a fresh agent with `briefs/build-common.md`. Paths inside the reports refer to the original Windows machine, `C:\Users\Scott\...`. Local data such as builds, results and the snapper64 corpus is not in git. The scripts regenerate it: `tools/n64-timing/build.sh`, `romgen/build.py`, and `suites/snapper/fetch.sh`. The MM ROM is your own copy.
