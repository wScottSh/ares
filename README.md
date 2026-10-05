<img src="https://github.com/ares-emulator/ares/blob/master/ares/ares/resource/logo@2x.png" width="350"/>

[![License: ISC](https://img.shields.io/badge/License-ISC-blue.svg)](LICENSE)

This is a fork of [ares](https://github.com/ares-emulator/ares) for doing performance work on Nintendo 64 software without a console or a window.
You run a ROM through a headless runner and get per-frame timing that matches real hardware, the same on every run.
That lets you measure a change to a game, such as a decomp mod, the way you would measure any other program: script it, run it, and diff the numbers.

For general emulation, use [upstream ares](https://github.com/ares-emulator/ares).
This fork changes the N64 core only. The other cores and the desktop UI are inherited from upstream and are not maintained here.

Goal
----

The target is an N64 timing model in which every behavior that can move a game's frame time is modeled from cited hardware references, and each behavior has a check.
The concrete acceptance target is Majora's Mask.
A 600-frame bench run must be bit-deterministic and finish in 2 minutes or less, and the file-select scenes must reproduce the slowdown measured on a real console.

The design rules are:

* Accuracy is the only goal. The timing model is always on, with no toggle.
* Runs are bit-deterministic. The core reads no host clock, uses no GPU thread, and takes no host entropy.
* The interpreters are the timing reference. The fork has no CPU or RSP recompiler.
* The target console is an NTSC retail NUS-001 with the Expansion Pak.

The roadmap is [issue #1](https://github.com/wScottSh/ares/issues/1).
The architecture is [ADR 0001](docs/adr/0001-timing-core.md), and the build sequence is the [timing-core plan](docs/design/timing-core/plan.md).
The hardware research behind each decision is in [docs/research](docs/research/README.md).

Status
------

Available on `master` today:

* `n64-run`, a headless runner. It stops after N frames or N emulated seconds, writes one TSV row of stats per VI field, dumps frames as PPM, and runs input scripts that can wait on, read, and write guest memory, and save and load state.
* Deterministic output. Each stats row carries a hash of every fired event and the full machine state, and `determinism.sh` fails unless two runs are byte-identical.
* One RDP. The cen64-jgemu pixel engine renders on the emulation thread. paraLLEl and Vulkan are removed.
* Absolute clocks. Core timing uses one 750 MHz time base, the least common multiple of the console's clocks.
* Verification corpora. The nemu64-test timing suite, snapper64 tests, and Thar0's RDP timing tests run against the core.
* `mmbench`, a scripted Majora's Mask bench with an acceptance check for the file-select slowdown.

In progress:

* A discrete-event timeline that replaces the CPU's fixed-order device sync ([PR #49](https://github.com/wScottSh/ares/pull/49)).
* RDRAM arbitration, so that the CPU, RSP, RDP, DMA engines, and VI scanout contend for the bus in true time order.
* A VR4300 pipeline model and an RDP timing model.

Until this work lands, frame times from `n64-run` are deterministic but not yet hardware-accurate.

Quick start
-----------

The scripts target Windows with MSYS2 clang64 and Git Bash.
For the prerequisites, see [tools/n64-timing/README.md](tools/n64-timing/README.md).

Build the runner. The script prints the path of the `n64-run` binary.

```sh
tools/n64-timing/build.sh
```

Run a ROM for 600 fields and write per-field stats:

```sh
n64-run game.z64 --frames 600 --stats stats.tsv
```

Check that two runs are identical:

```sh
tools/n64-timing/determinism.sh game.z64 600
```

For the runner's options, stats columns, input scripts, and exit codes, see [tools/n64-timing/README.md](tools/n64-timing/README.md).
For the Majora's Mask bench, see [tools/n64-timing/mmbench/README.md](tools/n64-timing/mmbench/README.md).
No ROMs are included in this repository.

Layout
------

* __ares/n64__: the N64 core. `timing/` holds the clocks and the trace hash, and `rdp/engine/` holds the pixel engine.
* __tools/n64-run__: the headless runner.
* __tools/n64-timing__: build, run, determinism, and corpus scripts, and the ROM generator for test suites.
* __docs/adr__, __docs/design__, __docs/research__: decisions, plans, and the research that backs them.

The rest of the tree (`desktop-ui`, `hiro`, `ruby`, `mia`, `nall`, `libco`, and the other cores) is upstream ares.

Credits
-------

ares is a multi-system emulator that began development on October 14th, 2004, and descends from [higan](https://github.com/higan-emu/higan) and [bsnes](https://github.com/bsnes-emu/bsnes/).
All credit for the emulator this fork builds on goes to the ares developers.
The RDP pixel engine is ported from the cen64 jgemu fork by Ryan Holtz and Rupert Carmichael, under BSD-3-Clause. See `ares/n64/rdp/engine/README.md`.
