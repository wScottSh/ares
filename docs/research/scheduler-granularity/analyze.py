"""Summarize a matrix log: per config, median wall and thread CPU seconds over reps,
CPU instructions and syncs (from each run's stderr), and host ns per CPU instruction.
usage: analyze.py LOG PREFIX [window]"""
import re, statistics, sys, collections, pathlib

log, prefix = sys.argv[1], sys.argv[2]
window = len(sys.argv) > 3
root = pathlib.Path(log).parent
rows = collections.defaultdict(list)
for line in open(log):
    f = line.rstrip("\n").split("\t")
    label = f[0]
    if not label.startswith(prefix):
        continue
    config = re.sub(r"-r\d+$", "", label[len(prefix):])
    err = (root / f"err-{label}.txt").read_text()
    txn = dict((m.group(1), int(m.group(2))) for m in re.finditer(r"^m9\.(?:w)?txn\t(\S+)\t(\d+)$", err, re.M)) if not window else \
          dict((m.group(1), int(m.group(2))) for m in re.finditer(r"^m9\.wtxn\t(\S+)\t(\d+)$", err, re.M))
    if window:
        m = re.search(r"m9\.window\tthread_cpu_s=([\d.]+)\ttsc_s=([\d.]+)", err)
        cpu, wall = float(m.group(1)), float(m.group(2))
    else:
        wall = float(re.search(r"wall_s=([\d.]+)", err).group(1))
        m = re.search(r"thread_cpu_s=([\d.]+)", err)
        cpu = float(m.group(1)) if m else float("nan")
    rows[config].append((wall, cpu, txn, f[-1]))

print("config\treps\tquiet\twall_med\twall_min\tcpu_med\tcpu_instr_M\trsp_run_instr_M\trsp_instr_M\tsyncs_M\tns_per_instr_wall_med\tns_per_instr_wall_min")
for config, rs in rows.items():
    walls = [r[0] for r in rs]; cpus = [r[1] for r in rs]
    txn = rs[0][2]
    n = txn.get("cpu_steps") or 0
    quiet = sum(1 for r in rs if r[3] == "quiet")
    med, mn = statistics.median(walls), min(walls)
    def ns(x): return f"{x * 1e9 / n:.2f}" if n else "NA"
    print(f"{config}\t{len(rs)}\t{quiet}\t{med:.3f}\t{mn:.3f}\t{statistics.median(cpus):.3f}\t{n/1e6:.1f}\t"
          f"{txn.get('cpu_steps_rsp_running', 0)/1e6:.1f}\t{txn.get('rsp_steps', 0)/1e6:.1f}\t{txn.get('syncs', 0)/1e6:.1f}\t{ns(med)}\t{ns(mn)}")
