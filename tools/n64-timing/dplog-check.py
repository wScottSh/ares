#!/usr/bin/env python3
"""Checks an ARES_DPLOG trace for the RSP-RDP back-pressure the timed DPC front end must produce (plan T12).

usage: dplog-check.py LOG [--from UNITS]

Set ARES_DPLOG=<file> when running n64-run to write the trace (ares/n64/rdp/timed.cpp). Lines:
  W <units> <cpu|rsp> START|END|STATUS <value> sv=<START_VALID> ev=<END_VALID> cur=<CURRENT> end=<END>   (state before the write)
  R <units> <cpu|rsp> CURRENT|STATUS <value>
  I <units> rsp_halted=<0|1>                                                                             (DP interrupt raised)
Times are 750 MHz units. --from skips everything before a time (for example the bench window).

Reports, against docs/research/rsp-rdp-fifo.md:
  - stall loops: runs of two or more back-to-back RSP reads of the same register with no RSP write
    between them (stalls B, C and D poll DPC_STATUS or DPC_CURRENT); before T12 every such loop exited
    on its first read;
  - CURRENT trailing END: RSP DPC_END writes made while CURRENT was short of the old END, and of
    those the ones made with START_VALID set, which queue behind the running transfer (END_PENDING);
  - DP interrupts and how long after the last RSP DPC_END write each one came, with the RSP's halt state;
  - DPC_START writes while START_VALID was set.
Exits 1 when a property the plan requires is absent: no stall loop iterated, CURRENT never trailed END,
or a DP interrupt came at the same time as an END write.
"""
import argparse
import statistics
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--from", dest="start", type=int, default=0)
    args = ap.parse_args()

    loops = {"CURRENT": [], "STATUS": []}
    run_reg, run_len = None, 0
    end_writes = trailing = 0
    start_while_valid = start_writes = end_pending = 0
    last_rsp_end = None
    irqs = []

    def close_run():
        nonlocal run_reg, run_len
        if run_reg and run_len >= 2:
            loops[run_reg].append(run_len)
        run_reg, run_len = None, 0

    with open(args.log) as f:
        for line in f:
            p = line.split()
            if len(p) < 3 or int(p[1]) < args.start:
                continue
            kind, t = p[0], int(p[1])
            if kind == "R" and p[2] == "rsp":
                if p[3] == run_reg:
                    run_len += 1
                else:
                    close_run()
                    run_reg, run_len = p[3], 1
            elif kind == "W" and p[2] == "rsp":
                close_run()
                fields = dict(x.split("=") for x in p[5:])
                if p[3] == "END":
                    end_writes += 1
                    if int(fields["cur"], 16) < int(fields["end"], 16):
                        trailing += 1
                        if fields["sv"] == "1":
                            end_pending += 1
                    last_rsp_end = t
                elif p[3] == "START":
                    start_writes += 1
                    if fields["sv"] == "1":
                        start_while_valid += 1
            elif kind == "I":
                irqs.append((t, t - last_rsp_end if last_rsp_end is not None else None, p[2].split("=")[1]))
    close_run()

    failures = []
    for reg, stall in (("CURRENT", "C/D"), ("STATUS", "B")):
        runs = loops[reg]
        extra = sum(n - 1 for n in runs)
        print(f"stall {stall} ({reg} polls): {len(runs)} loops iterated, {extra} extra reads, longest {max(runs, default=0)}")
    if not loops["CURRENT"]:
        failures.append("no DPC_CURRENT poll loop iterated")
    print(f"RSP DPC_END writes: {end_writes}, made while CURRENT trailed END: {trailing}")
    if not trailing:
        failures.append("CURRENT never trailed END at an RSP DPC_END write")
    print(f"RSP DPC_END writes queued behind a running transfer (END_PENDING): {end_pending}")
    print(f"RSP DPC_START writes: {start_writes}, while START_VALID was set: {start_while_valid}")
    lags = [lag for _, lag, _ in irqs if lag is not None]
    halted = sum(1 for _, _, h in irqs if h == "1")
    print(f"DP interrupts: {len(irqs)}, RSP halted at {halted} of them")
    if lags:
        print(f"  units after the last RSP DPC_END write: min {min(lags)} median {statistics.median(lags):.0f} max {max(lags)}")
        if min(lags) <= 0:
            failures.append("a DP interrupt was raised at the time of an RSP DPC_END write")
    for f in failures:
        print(f"FAIL: {f}")
    if not failures:
        print("dplog: PASS")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
