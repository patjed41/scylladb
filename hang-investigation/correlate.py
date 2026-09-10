#!/usr/bin/env python3
"""Correlate shard-hang events with the machine state at the time (SCYLLADB-3852).

For every hang_detector gap over a threshold, look at the seconds the gap spans
and report what the machine was doing then; compare against the same metrics
over all observed seconds, so "the stalls happen when X is high" is backed by a
contrast rather than by eyeballing.

usage: correlate.py <run-dir> [min-gap-ms]
"""
import os
import re
import sys
from datetime import datetime, timedelta

run = sys.argv[1]
min_gap = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
# hangs.log stamps are UTC, the samplers use local time
OFFSET = timedelta(hours=int(os.environ.get("UTC_OFFSET_H", "2")))

METRICS = ["allocstall/s", "scylla_majflt/s", "sys_pgmajfault/s", "pgscan_direct/s",
           "avail", "home_rd", "home_wr", "coredumps", "coredump_cpu/s",
           "psi_cpu_some", "psi_io_full", "psi_mem_some", "scylla_sys", "scylla_user",
           "load", "running", "procs"]

def load_samples(path):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        p = line.split()
        if not p or not re.match(r"^\d\d:\d\d:\d\d$", p[0]):
            continue
        row = out.setdefault(p[0], {})
        for tok in p[1:]:
            k, _, v = tok.partition("=")
            if k in METRICS:
                m = re.match(r"^-?[\d.]+", v)
                if m:
                    row[k] = float(m.group(0))
    return out

samples = load_samples(f"{run}/memmon.log")
for sec, row in load_samples(f"{run}/sysmon.log").items():
    samples.setdefault(sec, {}).update(row)

pat = re.compile(r"^(\S+ \S+) shard (\d+) gap=([\d.]+)ms cpu=([\d.]+)ms rq=([\d.]+)ms"
                 r" nvcsw=(\d+) nivcsw=(\d+) ts=(\d+)")
events = []
for line in open(f"{run}/hangs.log"):
    m = pat.match(line)
    if not m:
        continue
    gap = float(m.group(3))
    if gap < min_gap:
        continue
    end = datetime.strptime(m.group(1)[:26], "%Y-%m-%d %H:%M:%S.%f") + OFFSET
    start = end - timedelta(milliseconds=gap)
    secs = []
    t = start.replace(microsecond=0)
    while t <= end:
        key = t.strftime("%H:%M:%S")
        if key in samples:
            secs.append(samples[key])
        t += timedelta(seconds=1)
    events.append(dict(gap=gap, cpu=float(m.group(4)), rq=float(m.group(5)),
                       nvcsw=int(m.group(6)), slices=int(m.group(8)), secs=secs))

print(f"== {run}: {len(events)} gaps >= {min_gap:.0f}ms, {len(samples)} sampled seconds ==")
if not events:
    sys.exit(0)

def pct(vals, q):
    if not vals:
        return float("nan")
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))]

print("\nmetric                    all-seconds p50   all-seconds p95   during-gaps p50   during-gaps p95")
for k in METRICS:
    allv = [r[k] for r in samples.values() if k in r]
    gapv = [s[k] for e in events for s in e["secs"] if k in s]
    if not allv or not gapv:
        continue
    print(f"  {k:22s} {pct(allv,0.5):15.1f} {pct(allv,0.95):17.1f} "
          f"{pct(gapv,0.5):17.1f} {pct(gapv,0.95):17.1f}")

def peak(e, k):
    return max((s.get(k, 0) for s in e["secs"]), default=0)

mem = [e for e in events if peak(e, "allocstall/s") > 1000 or peak(e, "scylla_majflt/s") > 1000
       or peak(e, "psi_mem_some") > 100]
core = [e for e in events if e not in mem and peak(e, "coredumps") > 0]
io = [e for e in events if e not in mem and e not in core and peak(e, "psi_io_full") > 200]
rest = [e for e in events if e not in mem and e not in core and e not in io]
print("\nclassification of the gaps (first matching rule):")
for name, group in (("memory reclaim / refault", mem), ("core dump in flight", core),
                    ("io stall (psi_io_full)", io), ("neither", rest)):
    if not group:
        print(f"  {name:26s} n=0")
        continue
    g = sum(e["gap"] for e in group) / len(group)
    c = sum(e["cpu"] for e in group) / len(group)
    r = sum(e["rq"] for e in group) / len(group)
    print(f"  {name:26s} n={len(group):5d}  mean gap={g:8.0f}ms  cpu={100*c/g:4.0f}%  "
          f"rq={100*r/g:4.0f}%  blocked/other={100*(g-c-r)/g:4.0f}%  max gap={max(e['gap'] for e in group):8.0f}ms")
