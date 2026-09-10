#!/bin/bash
# Measure one debug node's memory footprint under a given ASAN / cmdline setup.
# usage: nodefootprint.sh <label> [extra test.py args...]
#   env: SCYLLA_EXTRA_ASAN_OPTIONS
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_BASE="${HANG_OUT:-$W/tmp/hang-runs}"
mkdir -p "$OUT_BASE"
LABEL="${1:?label}"; shift
cd "$W"
OUT="$OUT_BASE/footprint-$LABEL.log"

# sample every 0.5s: per-node PSS/anon plus the ASAN shadow region's own RSS
(
  best=0
  while true; do
    for p in $(pgrep -x scylla); do
      pss=$(awk '/^Pss:/{print $2}' /proc/$p/smaps_rollup 2>/dev/null)
      anon=$(awk '/^Anonymous:/{print $2}' /proc/$p/smaps_rollup 2>/dev/null)
      [ -z "$pss" ] && continue
      if [ "$pss" -gt "$best" ]; then
        best=$pss
        # ASAN's shadow lives below the app heap; report the resident part of the
        # biggest non-file anonymous ranges so shadow vs heap can be separated
        shadow=$(awk '
          /^[0-9a-f]+-[0-9a-f]+ / { split($1,a,"-"); start=strtonum("0x" a[1]); isshadow=(start < 0x100000000000 && $6 == "") ; next }
          /^Rss:/ { if (isshadow) s+=$2 }
          END { print s+0 }' /proc/$p/smaps 2>/dev/null)
        echo "pid=$p pss=${pss}K anon=${anon}K low_anon_rss=${shadow}K"
      fi
    done
    sleep 0.5
  done
) > "$OUT" 2>/dev/null &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

./test.py --mode=debug --no-gather-metrics --jobs 1 --repeat 1 "$@" \
    test/cluster/test_config.py > "$OUT_BASE/footprint-$LABEL-test.log" 2>&1
RC=$?
kill $SAMPLER 2>/dev/null
echo "[$LABEL] rc=$RC asan_extra='${SCYLLA_EXTRA_ASAN_OPTIONS:-<none>}' args='$*'"
tail -1 "$OUT" | sed 's/^/  peak: /'
