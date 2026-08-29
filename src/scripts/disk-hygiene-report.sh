#!/bin/bash
# disk-hygiene-report.sh — weekly inventory of what the fleet leaves behind.
#
# WHY THIS EXISTS. io/claude_code_hooks/logs reached 748,063 files / 6.1 GB over six
# months and nobody knew, because nothing reported it. This prints NUMBERS, not a
# verdict. A janitor that says "cleanup complete" without counts is exactly how you
# get to three quarters of a million files.
#
# Every command here has bounded output by construction — no path list is ever
# materialized. That is deliberate: the OOM analysis names unbounded sweeps as the
# leading hypothesis for the 2026-08-22 crash, and a hygiene tool must not be the
# thing that trips it.
#
# Design: src/rnd/v0.2.0/2026.08.23-plan-3-worker-detritus-containment.md
set -euo pipefail

LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"
PROJECTS="$( dirname "$LUPIN_ROOT" )"

gb() { awk '{printf "%.2f", $1/1073741824}'; }
dir_bytes() { du -sb "$1" 2>/dev/null | cut -f1 || echo 0; }

hook_logs="$LUPIN_ROOT/io/claude_code_hooks/logs"
hl_files=$( find "$hook_logs" -maxdepth 1 -type f 2>/dev/null | wc -l )
hl_gb=$( dir_bytes "$hook_logs" | gb )

wt_count=$( git -C "$LUPIN_ROOT" worktree list 2>/dev/null | wc -l )
wt_gb=$( du -scb "$PROJECTS"/lupin-wt-* "$PROJECTS"/lupin-v1-* 2>/dev/null | tail -1 | cut -f1 | gb )
wti_gb=$( dir_bytes "$LUPIN_ROOT/.claude/worktrees" | gb )
tx_gb=$( dir_bytes "$HOME/.claude/projects" | gb )
io_gb=$( dir_bytes "$LUPIN_ROOT/io" | gb )

# A worktree whose HEAD is already an ancestor of the integration branch is dead
# weight — count them, because that number IS the reclaimable backlog.
BASE="$( git -C "$LUPIN_ROOT" rev-parse --abbrev-ref HEAD )"
merged=0
while read -r wt; do
    [ -z "$wt" ] && continue
    h=$( git -C "$wt" rev-parse HEAD 2>/dev/null ) || continue
    git -C "$LUPIN_ROOT" merge-base --is-ancestor "$h" "$BASE" 2>/dev/null && merged=$(( merged + 1 ))
done < <( git -C "$LUPIN_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2}' )

cat <<REPORT
disk hygiene — $( date '+%Y-%m-%d %H:%M' )
  hook logs      : ${hl_files} files, ${hl_gb} GB
  worktrees      : ${wt_count} total (${merged} fully merged = reclaimable)
  worktree bytes : ${wt_gb} GB external + ${wti_gb} GB in-repo
  transcripts    : ${tx_gb} GB
  io/ total      : ${io_gb} GB
REPORT

# Thresholds worth waking someone for. Numbers first, judgment second.
[ "$hl_files" -gt 50000 ] && echo "  ⚠ hook logs over 50k files — run sweep-hook-logs.sh --apply"
[ "$merged" -gt 5 ]       && echo "  ⚠ ${merged} fully-merged worktrees reclaimable — see Plan 2"
exit 0
