#!/usr/bin/env bash
# Re-copies probe receipts from the session scratchpad into the worktree.
# WHY THIS EXISTS: the scratchpad is SESSION-SCOPED. A re-spin deletes it, and every
# failset, meta and contention sample with it. This runs until the radio tiers finish,
# then harvests once more — so an in-flight tier's result survives the seat that started it.
S=/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin-wt-cc-author-maria-2/35068dcf-5402-4be5-8c5a-4722232f1a2d/scratchpad/moveprobe
D=/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-cc-author-maria-2/src/rnd/v0.2.1/2026.09.05-move-probe-receipts
for i in $( seq 1 240 ); do
  cp -f "$S"/*.failset "$S"/*.meta "$S"/contention.log "$S"/driver.log "$S"/radio.log "$D"/ 2>/dev/null
  for f in "$S"/*.log; do b=$( basename "$f" )
    case "$b" in contention.log|driver.log|radio.log) ;; *) tail -40 "$f" > "$D/${b%.log}-tail.log" 2>/dev/null ;; esac
  done
  grep -q 'RADIO TIERS DONE' "$S/radio.log" 2>/dev/null && { echo "$( date -Is ) harvested final — RADIO TIERS DONE" >> "$D/harvest.log"; exit 0; }
  sleep 30
done
echo "$( date -Is ) harvester timed out after 2h — copies are current to this moment" >> "$D/harvest.log"
