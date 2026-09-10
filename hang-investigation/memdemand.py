#!/usr/bin/env python3
"""How much memory does each running node consume, and when does the box run dry?

Reads memmon logs from several runs and reports MemAvailable as a function of
the number of live scylla processes, so the two heap sizes can be compared on
the same axis. usage: memdemand.py <run-dir> [<run-dir>...]
"""
import re
import sys

for run in sys.argv[1:]:
    rows = []
    for line in open(f"{run}/memmon.log"):
        p = line.split()
        if not p or not re.match(r"^\d\d:\d\d:\d\d$", p[0]):
            continue
        d = {}
        for tok in p[1:]:
            k, _, v = tok.partition("=")
            m = re.match(r"^-?[\d.]+", v)
            if m:
                d[k] = float(m.group(0))
        if "procs" in d and "avail" in d:
            rows.append((int(d["procs"]), d["avail"], d.get("cached", 0),
                         d.get("allocstall/s", 0), d.get("scylla_majflt/s", 0)))
    if not rows:
        print(f"{run}: no samples")
        continue
    label = open(f"{run}/info.txt").readline().strip()
    print(f"\n== {run}\n   {label}")
    print("   nodes  MemAvailable(MB)   cached(MB)   allocstall/s   majflt/s   (median per node count)")
    buckets = {}
    for procs, avail, cached, alloc, majflt in rows:
        b = procs // 5 * 5
        buckets.setdefault(b, []).append((avail, cached, alloc, majflt))
    for b in sorted(buckets):
        vals = buckets[b]
        med = lambda i: sorted(v[i] for v in vals)[len(vals) // 2]
        mx = lambda i: max(v[i] for v in vals)
        print(f"   {b:3d}+   {med(0):12.0f}   {med(1):10.0f}   {mx(2):12.0f}   {mx(3):8.0f}")
    peak = max(r[0] for r in rows)
    low = min(r[1] for r in rows)
    print(f"   peak nodes={peak}  lowest MemAvailable={low:.0f}MB")
