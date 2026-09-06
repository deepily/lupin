#!/usr/bin/env bash
# Records WHICH trees are running a tier, every 20s, so each arm's window can be
# attributed. Identifies by /proc/<pid>/cwd — the property the process CARRIES —
# never by its command line, which on this fleet matches any seat merely briefed
# about testing.
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
while true; do
  trees=$( for p in $( ps -eo pid,comm,args --no-headers | awk '$2=="pytest" || ($2 ~ /^python/ && $0 ~ / -m pytest/) {print $1}' ); do
             readlink /proc/$p/cwd 2>/dev/null | xargs -r basename
           done | sort -u | paste -sd, )
  echo "$( date -Is ) trees=[${trees:-none}] load1=$( cut -d' ' -f1 /proc/loadavg )"
  sleep 20
done
