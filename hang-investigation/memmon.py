#!/usr/bin/env python3
"""Per-second memory/major-fault view, to test whether the shard stalls are
major page faults (binary text / page cache) under memory pressure."""
import glob, time, sys

def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""

def kv(text, keys, scale=1):
    out = {}
    for line in text.splitlines():
        p = line.replace(":", "").split()
        if p and p[0] in keys:
            out[p[0]] = int(p[1]) // scale
    return out

DEVS = {"dm-3": "home", "nvme0n1": "nvme"}

def diskstats():
    out = {}
    for line in read("/proc/diskstats").splitlines():
        f = line.split()
        if len(f) > 13 and f[2] in DEVS:
            # reads-completed, sectors-read, ms-reading, writes, sectors-written,
            # ms-writing, ios-in-flight, ms-io (io_ticks), weighted-ms
            out[DEVS[f[2]]] = dict(r=int(f[3]), rsec=int(f[5]), rms=int(f[6]),
                                   w=int(f[7]), wsec=int(f[9]), wms=int(f[10]),
                                   infl=int(f[11]), ioticks=int(f[12]), wtd=int(f[13]))
    return out

def coredump_stats():
    """How many core dumps are being processed, and what do they cost?"""
    n = 0
    cpu_ticks = 0
    wr = 0
    for path in glob.glob("/proc/[0-9]*/comm"):
        c = read(path).strip()
        if c not in ("systemd-coredum", "systemd-coredump"):
            continue
        n += 1
        st = read(path.replace("/comm", "/stat"))
        try:
            f = st[st.rindex(")") + 2:].split()
            cpu_ticks += int(f[11]) + int(f[12])  # utime + stime
        except (ValueError, IndexError):
            pass
        for line in read(path.replace("/comm", "/io")).splitlines():
            k, _, v = line.partition(": ")
            if k == "write_bytes":
                wr += int(v)
    return n, cpu_ticks, wr


def scylla_stats():
    tot_maj = 0
    tot_min = 0
    tot_rd = 0
    tot_wr = 0
    procs = 0
    for path in glob.glob("/proc/[0-9]*/comm"):
        if read(path).strip() != "scylla":
            continue
        procs += 1
        st = read(path.replace("/comm", "/stat"))
        try:
            fields = st[st.rindex(")") + 2:].split()
            # after state: ppid pgrp session tty tpgid flags minflt cminflt majflt
            tot_min += int(fields[7])
            tot_maj += int(fields[9])
        except (ValueError, IndexError):
            pass
        for line in read(path.replace("/comm", "/io")).splitlines():
            k, _, v = line.partition(": ")
            if k == "read_bytes":
                tot_rd += int(v)
            elif k == "write_bytes":
                tot_wr += int(v)
    return procs, tot_min, tot_maj, tot_rd, tot_wr

VM_KEYS = {"pgmajfault", "pgscan_direct", "pgsteal_direct", "allocstall_normal",
           "allocstall_movable", "pswpin", "pswpout", "pgpgin", "pgpgout",
           "nr_dirty", "nr_writeback", "compact_stall"}
MEM_KEYS = {"MemAvailable", "Cached", "Dirty", "Writeback", "SwapFree", "SwapTotal"}

prev_vm = kv(read("/proc/vmstat"), VM_KEYS)
prev_p, prev_min, prev_maj, prev_rd, prev_wr = scylla_stats()
prev_ds = diskstats()
prev_cd = coredump_stats()
while True:
    time.sleep(1.0)
    vm = kv(read("/proc/vmstat"), VM_KEYS)
    mem = kv(read("/proc/meminfo"), MEM_KEYS, 1024)  # MiB
    p, mn, mj, rd, wr = scylla_stats()
    ds = diskstats()
    cd = coredump_stats()
    d = lambda k, cur, prv: cur.get(k, 0) - prv.get(k, 0)
    sys.stdout.write(
        f"{time.strftime('%H:%M:%S')} procs={p} scylla_majflt/s={mj-prev_maj} scylla_minflt/s={mn-prev_min} "
        f"sys_pgmajfault/s={d('pgmajfault', vm, prev_vm)} pgscan_direct/s={d('pgscan_direct', vm, prev_vm)} "
        f"pgsteal_direct/s={d('pgsteal_direct', vm, prev_vm)} allocstall/s={d('allocstall_normal', vm, prev_vm)+d('allocstall_movable', vm, prev_vm)} "
        f"swapin/s={d('pswpin', vm, prev_vm)} swapout/s={d('pswpout', vm, prev_vm)} "
        f"pgpgin/s={d('pgpgin', vm, prev_vm)}KiB pgpgout/s={d('pgpgout', vm, prev_vm)}KiB "
        f"avail={mem.get('MemAvailable',0)}M cached={mem.get('Cached',0)}M dirty={mem.get('Dirty',0)}M "
        f"writeback={mem.get('Writeback',0)}M swapfree={mem.get('SwapFree',0)}M "
        + " ".join(
            f"{dev}_rd={(ds[dev]['rsec']-prev_ds.get(dev,ds[dev])['rsec'])//2048}M/s "
            f"{dev}_wr={(ds[dev]['wsec']-prev_ds.get(dev,ds[dev])['wsec'])//2048}M/s "
            f"{dev}_busy={ds[dev]['ioticks']-prev_ds.get(dev,ds[dev])['ioticks']}ms "
            f"{dev}_qwait={ds[dev]['wtd']-prev_ds.get(dev,ds[dev])['wtd']}ms "
            f"{dev}_infl={ds[dev]['infl']}"
            for dev in sorted(ds))
        + f" scylla_diskrd={(rd-prev_rd)//(1<<20)}M/s scylla_diskwr={(wr-prev_wr)//(1<<20)}M/s"
        + f" coredumps={cd[0]} coredump_cpu/s={(cd[1]-prev_cd[1])*10}ms coredump_wr/s={(cd[2]-prev_cd[2])//(1<<20)}M\n")
    sys.stdout.flush()
    prev_vm, prev_min, prev_maj, prev_rd, prev_wr, prev_ds, prev_cd = vm, mn, mj, rd, wr, ds, cd
