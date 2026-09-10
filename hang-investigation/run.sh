#!/bin/bash
# SCYLLADB-3852 hang reproduction at controlled concurrency.
# usage: hang-investigation/run.sh <jobs> <repeat> [extra test.py args...]
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_BASE="${HANG_OUT:-$W/tmp/hang-runs}"
mkdir -p "$OUT_BASE"
JOBS="${1:?jobs}"; REPEAT="${2:?repeat}"; shift 2
RUN="$OUT_BASE/j${JOBS}-$(date +%H%M%S)"
mkdir -p "$RUN"

export SCYLLA_HANG_TICK_MS="${SCYLLA_HANG_TICK_MS:-10}"
export SCYLLA_HANG_THRESHOLD_MS="${SCYLLA_HANG_THRESHOLD_MS:-200}"
export SCYLLA_HANG_LOG="$RUN/hangs.log"
: > "$SCYLLA_HANG_LOG"

cd "$W"
python3 "$SCRIPT_DIR"/sysmon.py > "$RUN/sysmon.log" 2>&1 &
MON1=$!
python3 "$SCRIPT_DIR"/memmon.py > "$RUN/memmon.log" 2>&1 &
MON2=$!
trap 'kill $MON1 $MON2 2>/dev/null' EXIT

{ echo "jobs=$JOBS repeat=$REPEAT extra=$* tick=$SCYLLA_HANG_TICK_MS threshold=$SCYLLA_HANG_THRESHOLD_MS"
  echo "start=$(date -Is)"; } > "$RUN/info.txt"

./test.py --mode=debug --no-gather-metrics --jobs "$JOBS" --repeat "$REPEAT" "$@" \
    test/cluster/test_crash_coordinator_before_streaming.py > "$RUN/test.log" 2>&1
RC=$?
echo "end=$(date -Is) rc=$RC" >> "$RUN/info.txt"
kill $MON1 $MON2 2>/dev/null
echo "run=$RUN rc=$RC hang_events=$(wc -l < "$SCYLLA_HANG_LOG")"
