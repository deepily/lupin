#!/bin/bash
# sweep-hook-logs.sh — bound the hook-event log directory.
#
# WHY THIS EXISTS. io/claude_code_hooks/logs accumulated 748,063 files and 6.1 GB
# between 2026-02-26 and 2026-08-23 with no retention policy. It is gitignored, so
# it never appeared in a session-end review. The inode count is the bigger problem
# than the bytes: three quarters of a million entries in ONE flat directory makes
# every repo-wide find/grep slow — and unbounded-output sweeps are the leading
# hypothesis for the 2026-08-22 OOM that took the fleet down twice.
#
# WHY NOT logrotate. logrotate rotates append-only files. 748k of these are DISCRETE
# per-event JSON dumps (pre_tool_use-*.json etc), which logrotate cannot express.
# This script does both jobs: age-sweep the per-event files, rotate the two
# append-only ones.
#
# Design: src/rnd/v0.2.0/2026.08.23-plan-3-worker-detritus-containment.md
#
# Usage:
#   ./sweep-hook-logs.sh              # dry run — reports, deletes nothing
#   ./sweep-hook-logs.sh --apply      # actually delete
#   RETAIN_DAYS=30 ./sweep-hook-logs.sh --apply
set -euo pipefail

LUPIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set}"
LOGS_DIR="$LUPIN_ROOT/io/claude_code_hooks/logs"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
ROTATE_AT_MB="${ROTATE_AT_MB:-64}"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

[[ -d "$LOGS_DIR" ]] || { echo "no logs dir at $LOGS_DIR — nothing to do"; exit 0; }

# Per-event JSON dumps, by hook event name. Named explicitly rather than swept with
# a wildcard: a bare `*.json` would also match anything a future writer drops here,
# and a deletion tool that guesses is worse than the mess it cleans.
EVENTS=( pre_tool_use post_tool_use user_prompt_submit stop notification
         session_start session_end permission_request smoke_test )

count_old() {
    local total=0 n
    for e in "${EVENTS[@]}"; do
        n=$( find "$LOGS_DIR" -maxdepth 1 -type f -name "${e}-*.json" -mtime "+$RETAIN_DAYS" 2>/dev/null | wc -l )
        total=$(( total + n ))
    done
    echo "$total"
}

before_files=$( find "$LOGS_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l )
before_bytes=$( du -sb "$LOGS_DIR" 2>/dev/null | cut -f1 )
old=$( count_old )

printf 'hook-log sweep — retain %s days\n' "$RETAIN_DAYS"
printf '  before   : %s files, %.2f GB\n' "$before_files" "$( echo "$before_bytes" | awk '{printf "%.2f", $1/1073741824}' )"
printf '  eligible : %s per-event files older than %sd\n' "$old" "$RETAIN_DAYS"

if [[ "$APPLY" -eq 0 ]]; then
    echo "  DRY RUN — nothing deleted. Re-run with --apply."
    exit 0
fi

# -delete rather than `| xargs rm`: no path list is ever materialized, so this
# cannot itself become the unbounded-output command the OOM analysis warned about.
for e in "${EVENTS[@]}"; do
    find "$LOGS_DIR" -maxdepth 1 -type f -name "${e}-*.json" -mtime "+$RETAIN_DAYS" -delete 2>/dev/null || true
done

# Append-only logs: rotate at size, keep one generation.
for f in hook-events.jsonl arbiter.log; do
    p="$LOGS_DIR/$f"
    [[ -f "$p" ]] || continue
    mb=$(( $(stat -c%s "$p") / 1048576 ))
    if (( mb >= ROTATE_AT_MB )); then
        mv -f "$p" "$p.1"
        : > "$p"
        echo "  rotated  : $f (${mb} MB) -> $f.1"
    fi
done

after_files=$( find "$LOGS_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l )
after_bytes=$( du -sb "$LOGS_DIR" 2>/dev/null | cut -f1 )
printf '  after    : %s files, %.2f GB\n' "$after_files" "$( echo "$after_bytes" | awk '{printf "%.2f", $1/1073741824}' )"
printf '  reclaimed: %s files, %.2f GB\n' "$(( before_files - after_files ))" \
       "$( echo "$before_bytes $after_bytes" | awk '{printf "%.2f", ($1-$2)/1073741824}' )"
