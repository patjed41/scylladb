#!/bin/bash
# Sample a node's anonymous RSS every 100ms through startup, then line the samples
# up with its own log so the allocation steps become visible.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_BASE="${HANG_OUT:-$W/tmp/hang-runs}"
mkdir -p "$OUT_BASE"
cd "$W"
OUT="$OUT_BASE/startupmem.samples"
: > "$OUT"

(
  seen=""
  while true; do
    for p in $(pgrep -x scylla); do
      a=$(awk '/^RssAnon:/{print $2}' /proc/$p/status 2>/dev/null)
      f=$(awk '/^RssFile:/{print $2}' /proc/$p/status 2>/dev/null)
      [ -z "$a" ] && continue
      echo "$(date +%H:%M:%S.%3N) pid=$p anon=$((a/1024))M file=$((f/1024))M"
    done
    sleep 0.1
  done
) >> "$OUT" 2>/dev/null &
S=$!
trap 'kill $S 2>/dev/null' EXIT

./test.py --mode=debug --no-gather-metrics --jobs 1 --repeat 1 -s test/cluster/test_config.py \
    > "$OUT_BASE/startupmem-test.log" 2>&1
kill $S 2>/dev/null

FIRST=$(awk '{print $2}' "$OUT" | head -1)
echo "== anon RSS growth of the first node =="
PID=$(head -1 "$OUT" | grep -oE "pid=[0-9]+" | cut -d= -f2)
grep "pid=$PID" "$OUT" | awk '{split($3,a,"="); v=a[2]+0; if (v != last) {print "  " $1, $3, $4; last=v}}' | head -40
echo "== startup milestones from the node log =="
L=$(ls -t "$W"/testlog/debug/*.log 2>/dev/null | head -1)
grep -nE "starting prometheus|Scylla version .* starting|initialization completed|Setting local host id|starting per-shard database core|primed|allocator" "$L" 2>/dev/null \
  | cut -c1-150 | head -12
