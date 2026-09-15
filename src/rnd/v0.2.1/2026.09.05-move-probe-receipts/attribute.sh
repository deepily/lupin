#!/usr/bin/env bash
# PER-ARM TREE SET as a FIRST-CLASS COLUMN (maria's ruling, 18:59).
# Not a caveat in prose — a column beside the failing count, for every arm.
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
epoch () { date -d "$( echo "$1" | sed 's/T/ /; s/-04:00$//' )" +%s 2>/dev/null; }
for a in A B A2 C RBASE RTIP RCARRIED; do
  [ -f "$S/$a.meta" ] || continue
  st=$( grep -oP 'started_at=\K.*'  "$S/$a.meta" ); fi=$( grep -oP 'finished_at=\K.*' "$S/$a.meta" )
  [ -n "$fi" ] || fi=$( date -Is )
  se=$( epoch "$st" ); fe=$( epoch "$fi" )
  n=$( [ -f "$S/$a.failset" ] && wc -l < "$S/$a.failset" || echo "?" )
  # every OTHER tree seen inside this arm's window, and how many samples saw it
  others=$( awk -v s="$se" -v f="$fe" '
      { ts=$1; gsub(/T/," ",ts); sub(/-04:00$/,"",ts)
        cmd="date -d \""ts"\" +%s"; cmd|getline e; close(cmd)
        if(e>=s && e<=f){ match($0,/trees=\[[^]]*\]/); t=substr($0,RSTART+7,RLENGTH-8); print t } }' "$S/contention.log" \
    | tr ',' '\n' | grep -v '^lupin-wt-tiberius-moveprobe$' | grep -v '^$' | sort | uniq -c \
    | awk '{printf "%s(x%s) ", $2, $1}' )
  smp=$( awk -v s="$se" -v f="$fe" '{ts=$1; gsub(/T/," ",ts); sub(/-04:00$/,"",ts); cmd="date -d \""ts"\" +%s"; cmd|getline e; close(cmd); if(e>=s&&e<=f) c++} END{print c+0}' "$S/contention.log" )
  printf "%-9s failing=%-4s samples=%-4s CO-RESIDENT TREES: %s\n" "$a" "$n" "$smp" "${others:-<none — sole tier on the box>}"
done
