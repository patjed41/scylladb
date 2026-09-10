#!/usr/bin/env python3
"""External observer for SCYLLADB-3852 shard-hang investigation.

Samples every INTERVAL seconds:
  * PSI (cpu/io/memory) deltas  -> was the machine starved for CPU or stuck in I/O?
  * loadavg / procs_running     -> how oversubscribed are we?
  * every scylla thread's state -> reactor threads sitting in D (uninterruptible)
    are reported together with their kernel wchan.
  * its own wakeup delay        -> if even this process is not scheduled, say so.

Writes one summary line per second plus an immediate line for every
D-state reactor thread observation and every self-delay.
"""
import glob
import os
import sys
import time

INTERVAL = float(os.environ.get("SYSMON_INTERVAL", "0.1"))
SELF_DELAY_WARN = float(os.environ.get("SYSMON_SELF_DELAY_MS", "200")) / 1000.0
out = sys.stdout


def psi(kind):
    try:
        res = {}
        with open(f"/proc/pressure/{kind}") as f:
            for line in f:
                parts = line.split()
                res[parts[0]] = int(parts[-1].split("=")[1])
        return res
    except OSError:
        return {}


def scylla_pids():
    pids = []
    for path in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(path) as f:
                if f.read().strip() == "scylla":
                    pids.append(path.split("/")[2])
        except OSError:
            pass
    return pids


def sample_threads(pids):
    """Return (nr_threads, blocked list, user ticks, system ticks)."""
    total = 0
    blocked = []
    ut = 0
    st_ticks = 0
    for pid in pids:
        for tdir in glob.glob(f"/proc/{pid}/task/[0-9]*"):
            total += 1
            try:
                with open(f"{tdir}/stat") as f:
                    st = f.read()
                # comm may contain spaces/parens; state follows the last ')'
                rp = st.rindex(")")
                name = st[st.index("(") + 1:rp]
                state = st[rp + 2]
                f = st[rp + 2:].split()
                ut += int(f[11])
                st_ticks += int(f[12])
                if state in ("D",):
                    try:
                        with open(f"{tdir}/wchan") as f:
                            wchan = f.read().strip() or "?"
                    except OSError:
                        wchan = "?"
                    blocked.append((pid, tdir.rsplit("/", 1)[1], name, state, wchan))
            except (OSError, ValueError):
                pass
    return total, blocked, ut, st_ticks


def main():
    now = time.monotonic
    prev = {k: psi(k) for k in ("cpu", "io", "memory")}
    next_tick = now()
    last_summary = now()
    acc_blocked = {}
    max_threads = 0
    samples = 0
    prev_cpu = [None, None]
    acc_cpu = [0, 0]
    while True:
        next_tick += INTERVAL
        delay = next_tick - now()
        if delay > 0:
            time.sleep(delay)
        overshoot = now() - next_tick
        if overshoot > SELF_DELAY_WARN:
            out.write(f"{time.strftime('%H:%M:%S')} SELF-DELAY sampler woke {overshoot*1000:.0f}ms late\n")
            out.flush()
            next_tick = now()
        pids = scylla_pids()
        nr, blocked, ut, stk = sample_threads(pids)
        if prev_cpu[0] is None or ut < prev_cpu[0]:
            prev_cpu[0], prev_cpu[1] = ut, stk
        acc_cpu[0] += ut - prev_cpu[0]
        acc_cpu[1] += stk - prev_cpu[1]
        prev_cpu[0], prev_cpu[1] = ut, stk
        max_threads = max(max_threads, nr)
        samples += 1
        for pid, tid, name, state, wchan in blocked:
            key = (name, wchan)
            acc_blocked[key] = acc_blocked.get(key, 0) + 1
        if now() - last_summary >= 1.0:
            cur = {k: psi(k) for k in ("cpu", "io", "memory")}
            def d(kind, field):
                try:
                    return (cur[kind][field] - prev[kind][field]) / 1000.0  # ms of stall
                except KeyError:
                    return -1.0
            with open("/proc/loadavg") as f:
                load = f.read().split()[0]
            running = "?"
            try:
                with open("/proc/stat") as f:
                    for line in f:
                        if line.startswith("procs_running"):
                            running = line.split()[1]
            except OSError:
                pass
            top = sorted(acc_blocked.items(), key=lambda kv: -kv[1])[:5]
            top_s = " ".join(f"{n}:{w}={c}" for (n, w), c in top)
            out.write(
                f"{time.strftime('%H:%M:%S')} procs={len(pids)} thr={max_threads} load={load} "
                f"running={running} psi_cpu_some={d('cpu','some'):.0f}ms psi_io_some={d('io','some'):.0f}ms "
                f"psi_io_full={d('io','full'):.0f}ms psi_mem_some={d('memory','some'):.0f}ms "
                f"samples={samples} scylla_user={acc_cpu[0]*10}ms/s scylla_sys={acc_cpu[1]*10}ms/s "
                f"Dstate=[{top_s}]\n")
            out.flush()
            prev = cur
            last_summary = now()
            acc_blocked = {}
            max_threads = nr
            samples = 0
            acc_cpu = [0, 0]


if __name__ == "__main__":
    main()
