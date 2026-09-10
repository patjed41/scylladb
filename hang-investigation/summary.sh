#!/bin/bash
# usage: hang-investigation/summary.sh <run-dir>
R="${1:?run dir}"
echo "== $R =="
cat "$R/info.txt"
echo "-- pytest progress --"
grep -oE "^[F.sx]+" "$R/test.log" | tail -1
echo "-- hang events: $(wc -l < "$R/hangs.log") --"
awk '{
  gap=cpu=rq=0
  for (i=1;i<=NF;i++) {
    if ($i ~ /^gap=/) { split($i,g,"="); gap=g[2]+0 }
    if ($i ~ /^cpu=/) { split($i,c,"="); cpu=c[2]+0 }
    if ($i ~ /^rq=/)  { split($i,r,"="); rq=r[2]+0 }
  }
  n++
  if (gap>500) g500++
  if (gap>1000) g1++
  if (gap>2000) { g2++; sg+=gap; scpu+=cpu; srq+=rq }
  if (gap>5000) g5++
  if (gap>max) max=gap
} END {
  printf "  total=%d  >0.5s=%d  >1s=%d  >2s=%d  >5s=%d  max=%.0fms\n", n, g500+0, g1+0, g2+0, g5+0, max+0
  if (g2>0) printf "  mean breakdown of gaps>2s: gap=%.0fms cpu=%.0fms(%.0f%%) rq=%.0fms(%.0f%%) unexplained=%.0fms(%.0f%%)\n", \
     sg/g2, scpu/g2, 100*scpu/sg, srq/g2, 100*srq/sg, (sg-scpu-srq)/g2, 100*(sg-scpu-srq)/sg
}' "$R/hangs.log"
echo "-- worst 3 --"
awk '{for(i=1;i<=NF;i++) if($i ~ /^gap=/){split($i,g,"=");print g[2]+0"\t"$0}}' "$R/hangs.log" | sort -rn | head -3 | cut -c1-165
echo "-- peak load / memory / disk --"
awk '{for(i=1;i<=NF;i++){split($i,a,"=");if(a[1]=="load"&&a[2]+0>l)l=a[2]+0;if(a[1]=="procs"&&a[2]+0>p)p=a[2]+0;if(a[1]=="running"&&a[2]+0>r)r=a[2]+0}} END{printf "  peak procs=%d load=%.0f runnable=%d\n",p,l,r}' "$R/sysmon.log"
awk '{for(i=1;i<=NF;i++){split($i,a,"=");
   if(a[1]=="avail"){v=a[2]+0; if(min==0||v<min)min=v}
   if(a[1]=="scylla_majflt/s"&&a[2]+0>mf)mf=a[2]+0
   if(a[1]=="allocstall/s"&&a[2]+0>as)as=a[2]+0
   if(a[1]=="home_rd"){v=a[2]+0; if(v>rd)rd=v}
   if(a[1]=="home_wr"){v=a[2]+0; if(v>wr)wr=v}
   if(a[1]=="home_qwait"){v=a[2]+0; if(v>qw)qw=v}}}
   END{printf "  min MemAvailable=%dM  peak scylla_majflt/s=%d  peak allocstall/s=%d  peak disk rd=%dM/s wr=%dM/s  peak io qwait=%dms/s\n",min,mf,as,rd,wr,qw}' "$R/memmon.log"
awk '/psi_cpu_some/{for(i=1;i<=NF;i++){split($i,a,"=");
   if(a[1]=="psi_cpu_some"){v=a[2]+0; if(v>c)c=v}
   if(a[1]=="psi_io_full"){v=a[2]+0; if(v>f)f=v}
   if(a[1]=="psi_mem_some"){v=a[2]+0; if(v>m)m=v}}}
   END{printf "  peak psi/s: cpu_some=%dms io_full=%dms mem_some=%dms\n",c,f,m}' "$R/sysmon.log"
