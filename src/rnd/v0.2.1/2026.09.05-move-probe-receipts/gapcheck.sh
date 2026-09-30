#!/usr/bin/env bash
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
echo "samples=$( wc -l < "$S/contention.log" )  expected cadence 20s"
awk '{ gsub(/T/," ",$1); sub(/-04:00$/,"",$1); cmd="date -d \""$1"\" +%s"; cmd|getline e; close(cmd);
       if(p && e-p>25) printf "  GAP %ds between %s and %s\n", e-p, pt, $1; p=e; pt=$1 }' "$S/contention.log"
echo "  (no GAP lines above = unbroken record)"
echo "distinct tree-sets observed:"; grep -oE 'trees=\[[^]]*\]' "$S/contention.log" | sort | uniq -c
