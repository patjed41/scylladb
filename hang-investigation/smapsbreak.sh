#!/bin/bash
# Break a live node's resident memory into ASAN shadow / app heap / file-backed,
# using the standard x86-64 ASAN mapping:
#   LowShadow  [0x00007fff8000, 0x00008fff6fff]
#   HighShadow [0x02008fff7000, 0x10007fff7fff]
#   HighMem    [0x10007fff8000, ...]        <- application
P="${1:-$(pgrep -x scylla | head -1)}"
echo "pid=$P  cmdline: $(tr '\0' ' ' < /proc/$P/cmdline | grep -oE '\-\-smp [0-9]+ \-m [0-9A-Za-z]+')"
grep -E "^(VmRSS|RssAnon|RssFile|RssShmem|VmSwap|VmSize)" /proc/$P/status | sed 's/^/  /'
echo "  -- resident bytes by region --"
awk '
  /^[0-9a-f]+-[0-9a-f]+ / {
      split($1, a, "-")
      start = strtonum("0x" a[1])
      path = ""
      for (i = 6; i <= NF; i++) path = path $i
      if (path != "") cat = "file-backed"
      else if (start >= 0x00007fff8000 && start <= 0x00008fff6fff) cat = "ASAN LowShadow"
      else if (start >= 0x02008fff7000 && start <= 0x10007fff7fff) cat = "ASAN HighShadow"
      else if (start >= 0x10007fff8000) cat = "app (HighMem) anon"
      else cat = "low anon (< shadow)"
      next
  }
  /^Rss:/ { rss[cat] += $2 }
  /^Size:/ { size[cat] += $2 }
  END {
      for (c in rss) printf "  %-22s rss=%8.1f MB   mapped=%10.1f MB\n", c, rss[c]/1024, size[c]/1024
  }
' /proc/$P/smaps | sort -t= -k2 -rn
echo "  -- 8 largest resident mappings --"
awk '
  /^[0-9a-f]+-[0-9a-f]+ / { range=$1; path=""; for (i=6;i<=NF;i++) path=path" "$i; next }
  /^Rss:/ { if ($2 > 10240) printf "  %10.1f MB  %s %s\n", $2/1024, range, path }
' /proc/$P/smaps | sort -rn | head -8
