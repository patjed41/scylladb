# SCYLLADB-3852 — why shard 0 stops making progress for seconds

Reproduced locally on a 32-CPU / 128 GB box, debug build, running
`test/cluster/test_crash_coordinator_before_streaming.py`. Tested on master
`46f6896925`, which already contains both of Avi's I/O reductions (`00a689677a` →
#29530, `233d822abf` → #31281).

## Summary

The machine runs out of memory when too many debug nodes run at once. Once
`MemAvailable` approaches zero the kernel evicts page cache — including the text of
the 1.7 GB debug binary — and every node starts thrashing: the reactor blocks in
major faults and then waits for CPU behind everyone else doing the same. That is the
multi-second shard-0 hang, after which the failure detector marks live nodes dead.

A debug node costs **~1.3 GB**, against ~90 MB in dev. Most of that is not the
workload: it is a hardcoded "emulate 1 GB per shard" in `logalloc` plus ASAN
overhead. On top of it, Scylla never reclaims memory in debug builds, because
Seastar always reports a full GiB free.

This is not caused by the tests' disk I/O — throttling them to 20 MB/s does not
produce a single hang, because Scylla's data I/O is asynchronous — nor by CPU
oversubscription on its own.

## How it was measured

A local-only `hang_detector` in `main.cc` (not for merge): a 10 ms periodic timer per
shard; when two consecutive ticks are more than 200 ms apart it logs the gap and how
it was spent — `cpu=` thread CPU time, `rq=` run-queue wait, `nvcsw=`/`nivcsw=`
context switches, and by subtraction the time blocked in the kernel. Reports also go
to `$SCYLLA_HANG_LOG` so they survive the framework deleting node logs on success.

Samplers (`tmp/hang/sysmon.py`, `tmp/hang/memmon.py`) record per second: PSI
cpu/io/memory, loadavg, runnable count, D-state threads with their kernel `wchan`,
Scylla's user-vs-system CPU split, `allocstall` / `pgscan_direct` / `pgmajfault`,
`MemAvailable`, per-device disk throughput, and core dumps in flight.

## The hang, and that it is the one from the ticket

At the default 16 jobs gaps reached 101 s; at 10 jobs, 14.6 s. A node log reproduces
the ticket's chain exactly:

```
13:59:31,273 [shard 0] hang_detector - no progress for 5212.6ms: cpu=229.7ms rq=4138.4ms ts=400
13:59:31,365 [shard 0] direct_failure_detector - pinging 0d5e2f7f...: rpc::timeout_error
13:59:31,398 [shard 0] raft_group_registry - marking Raft server 6bedb66d... as dead
13:59:31,398 [shard 0] raft_group_registry - marking Raft server 0d5e2f7f... as dead
13:59:31,400 [shard 0] raft_group_registry - marking Raft server 421187a8... as dead
13:59:31,444 [shard 1] alternator_ttl - scan took 5.55 seconds, longer than period
13:59:31,447 [shard 0] raft_group_registry - marking Raft server 6bedb66d... as alive
```

Three live voters marked dead within 130 ms of the shard resuming, plus the same
`alternator_ttl` gap used as evidence in comment 90456. Of 2042 gaps > 2 s in saved
logs, 1559 had no `Reactor stalled` report — the reactor was not inside a long task,
it simply was not running.

## The cause: the box runs out of memory

At jobs=10, by number of live nodes:

| live nodes | MemAvailable | allocstall/s | majflt/s | worst gap |
|---|---|---|---|---|
| 30–55 | 47 → 15 GB | 0 | ~0 | ~1 s |
| 60+ | 9 GB | 10 441 | 361 | growing |
| 65+ | **2 GB** | **53 510** | **37 394** | **14.6 s** |

Gaps > 2 s at 65+ nodes break down as `cpu=8 % rq=40 % blocked=53 %`, with
`nvcsw=3453` — thousands of blocking major faults inside a single gap — and 7.6 GB/s
of disk reads. Those reads are page-cache refaults, not test data.

A second jobs=10 run that happened to stay at 60 nodes never crossed the wall and
passed all 20 reps, worst gap 2.2 s.

### Nothing else stalls a running node

Once a node has finished starting it is well behaved, so memory exhaustion is the
whole story for hangs that can trip a failure detector:

* Idle box, full test iteration: 24 gaps over 200 ms, **all of them during startup,
  all CPU-bound, max 314 ms — none at all after startup**.
* Loaded box without memory pressure (jobs=10): post-startup gaps stay at
  210–254 ms with only 22–84 ms of CPU — ordinary scheduling delay, nowhere near a
  failure-detector threshold. Every gap over 1 s in that run carries `cpu` of
  400–463 ms, the signature of the startup task below.

The startup task itself can be ignored: a node in startup was fully down moments
earlier, so its peers already treat it as dead and a couple of extra seconds change
nothing. It is worth naming only because it is more evidence about the priming
described in the next section — the ~250 ms of CPU (≈455 ms under load, stretching
to 2.2 s of wall time) falls strictly between

```
INFO ... init - installing SIGHUP handler          (main.cc:1110)
WARN ... hang_detector - no progress for 246.9ms: cpu=244.9ms rq=0.0ms
INFO ... init - Scylla version ... starting        (main.cc:1117)
```

whose only substantive work is `logalloc::prime_segment_pool()` at `main.cc:1115`.
Seastar never reports it because Scylla disables the stall detector for the whole of
startup (`main.cc:1064`, restored at `main.cc:1595`), which is why the largest
`Reactor stalled` report on an idle box is 33 ms.

## Why a debug node costs ~1.3 GB

Measured on one node (`--smp 2 -m 1G`) running the single-node `test_config.py`, peak
**1544 MB PSS**. Each contributor was measured by removing it:

| contributor | size | how it was measured |
|---|---|---|
| LSA segment-pool priming at startup | **~800 MB** (~400/shard) | anon RSS 49 → 835 MB in the 600 ms ending 16 ms before the log line `main.cc` prints right after `prime_segment_pool()` |
| ASAN shadow, resident and never unmapped | ~550–600 MB (part of the anon above) | `smaps`: the single 14.6 TB mapping `2008fff7000-10007fff8000` |
| ASAN quarantine (freed memory retained) | **344 MB** | `quarantine_size_mb=0` → 1544 → 1200 MB |
| debug binary text/data resident per node | ~245 MB | `RssFile` |
| ASAN per-allocation stack traces | 30 MB | `malloc_context_size=0` |
| redzones | ~5 MB | `redzone=16:max_redzone=16` |

### The big item

`utils/logalloc.cc:907`, in the segment store used only when
`SEASTAR_DEFAULT_ALLOCATOR` is defined (i.e. `Debug;Sanitize;Fuzz`):

```cpp
static constexpr size_t _std_memory_available = size_t(1) << 30; // emulate 1GB per shard
```

`main.cc:1115` primes that pool with a strategy documented as *"Allocate all of
memory so that we occupy the top part"*: it allocates segments until the store is
full — 1 GiB per shard — and gives back only ~32 MB. With Seastar's own allocator
that is free, since the segments come from the arena `-m` already sized. With the
system allocator each shard really asks malloc for ~1 GiB at boot.

Asked-for and resident are not the same number: of that ~1 GiB per shard, about
**400 MB stays resident** (the pages actually touched — segment headers, and the
ASAN shadow written when each segment is poisoned). The LSA then frees nearly all of
the segments, ending up owning just 11.5 MB (`scylla_lsa_total_space_bytes`), but the
RSS does not come back. So `--smp 2` leaves ~800 MB resident from priming alone, and
the node's total settles at ~1.3 GB once text and the rest of the heap are counted.

Per-shard cost is therefore fixed and independent of `-m`:

| shards (`-m 1G` throughout) | peak PSS |
|---|---|
| `--smp 1` | 1078 MB |
| `--smp 2` | 1544 MB (+466) |
| `--smp 4` | 2522 MB (+489/shard) |

In dev, `-m 1G` is divided across shards, so the node total stays ~1 GB whatever
`--smp` is. In debug every added shard adds ~480 MB, bounded by nothing.

### Reclaim never runs in debug

A live node reports, on every shard:

```
scylla_memory_total_memory{shard="0"} 1073741824
scylla_memory_free_memory{shard="0"}  1073741824
```

`stats()` is hardcoded to `statistics{0,0,0, 1<<30, 1<<30, ...}` at
`seastar/src/core/memory.cc:2728`, so free memory never falls and `--memory` is
ignored (the node logs a warning saying so). Scylla's memory-pressure signals never
fire in debug: LSA does not evict, caches do not shrink, memtables are not flushed
under pressure. Whatever a test allocates accumulates until the machine runs out.

## Why the job budget does not prevent this — in any mode

`test.py`'s `ThreadsCalculator` sizes a *test job*, but a cluster test is a fleet of
processes. On this box (135 GB, 32 CPUs):

| mode | per-job memory | per-job CPU | jobs chosen |
|---|---|---|---|
| debug | `min(135/8, 5) × 1.5` = **7.5 GB** | 1.5 | 16 (memory-bound; CPU rule allows 22) |
| dev / release | `min(135/8, 4)` = **4 GB** | 1.0 | 31 (memory-bound; CPU rule allows 32) |

This test creates 8 server objects per iteration but never runs them all at once:
nodes are stopped, removed and replaced as it goes. Measured live process count for
one worker over two iterations (348 samples, 1 s apart):

| live nodes | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| % of the run | 2 | 3 | 3 | 21 | 32 | 30 | 9 |

So **5 nodes normally, peaking at 6** — the 6th being a joining node overlapping the
existing five. At scale the per-worker peak was slightly higher, 6.0 at jobs=6 and
6.7 at jobs=10, the extra coming from one cluster's teardown overlapping the next
one's startup rather than from the test itself.

Against the budgets, using measured resident cost per node rather than `-m` (which
debug ignores):

| mode | per-node, measured | a 6-node job needs | vs. its budget |
|---|---|---|---|
| debug | ~1.3 GB | **~7.7 GB** | just over 7.5 GB |
| dev / release | ~90 MB | ~0.5 GB | far under 4 GB |

Per job that is only a marginal overshoot. The damage is in the aggregate: the model
hands 16 × 7.5 GB = 120 GB of a 135 GB machine to test processes and keeps 8 GB in
reserve, so at 16 jobs × ~6.5 live nodes × 1.3 GB ≈ 135 GB the box is already at its
limit with **nothing left for page cache** — which is what has to hold the 1.7 GB
debug binary's text. That is why the page cache is the first thing squeezed and why
the thrash is refaults of executable text.

Dev survives the same arithmetic only because `-m` is a lazy reservation: those
6 nodes nominally reserve 6 GB against a 4 GB budget but actually touch ~0.5 GB. A
test that genuinely used its heap would exceed RAM there too, and the budget would
not be what stopped it.

The CPU rule is off by a similar factor — a job runs 10–18 reactor threads while
being charged 1–1.5 CPUs, which is how 16 jobs produced 199 runnable threads on
32 CPUs.

How many clusters are alive at once is capped by the worker count, and it is the same
in both modes: measured at jobs=6, debug peaked at 36 live nodes and dev at 34. The
difference is entirely footprint — 36 × 1.29 GB ≈ 46 GB against 34 × 90 MB ≈ 3 GB.

## What would help

1. Add `quarantine_size_mb=0` to the tests' `ASAN_OPTIONS`: −344 MB per node (22 %),
   about 20 GB of pressure removed at jobs=10, at little cost to bug detection.
2. Derive `_std_memory_available` and the default-allocator `stats()` from the
   configured `-m` / `--smp` instead of hardcoding 1 GiB per shard — or skip the
   eager priming under the default allocator, where "occupy the top part" has no
   purpose. This also restores memory-pressure handling in debug.
3. Budget concurrency by *nodes* rather than test cases, which is what PR #25617's
   `max_running_servers` accounting is for. Either of the above would also make the
   existing per-job budget roughly meaningful again.
4. Raising failure-detector thresholds only covers the ~2 s CPU-contention tier; it
   cannot survive the memory collapse, so it is a partial mitigation at best.

## Reproducing

The scripts live next to this file. Run them from the repo root; output goes to
`tmp/hang-runs/` (override with `$HANG_OUT`). `run.sh` starts the two samplers
itself, so `sysmon.py` and `memmon.py` are not invoked directly.

```
hang-investigation/run.sh 10 20            # jobs, repeats - hangs appear once >60 nodes
hang-investigation/summary.sh <run-dir>    # gap distribution, peak load/memory/disk
hang-investigation/correlate.py <run-dir> 1000    # gaps vs machine state at the time
hang-investigation/memdemand.py <run-dir>...      # MemAvailable vs live node count
hang-investigation/nodefootprint.sh <label> [test.py args]
                                           # one node's cost; honours $SCYLLA_EXTRA_ASAN_OPTIONS
hang-investigation/smapsbreak.sh [pid]     # split a live node into shadow / heap / text
hang-investigation/startupmem.sh           # RSS through startup, against the node's own log
```

The measurements also need the two local-only source changes on this branch (both
marked not-for-merge): the `hang_detector` in `main.cc`, and the
`SCYLLA_EXTRA_ASAN_OPTIONS` hook in `test/pylib/scylla_server.py` that
`nodefootprint.sh` uses.
