#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# tail-cc-listeners.sh — Live aggregated output from all CC Notification Listeners
#
# All listeners now write to a single centralized log file.
# This script is a thin wrapper around `tail -f` with optional filtering.
#
# Usage:
#   src/scripts/tail-cc-listeners.sh                    # follow centralized log
#   src/scripts/tail-cc-listeners.sh --all              # cat full history + follow
#   src/scripts/tail-cc-listeners.sh --filter 7211      # grep filter by hash
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

LOG_FILE="$HOME/.claude/sessions/cc-listeners.log"

SHOW_ALL=false
FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)      SHOW_ALL=true; shift ;;
        --filter)
            shift
            if [[ $# -eq 0 ]]; then
                echo "Error: --filter requires a session hash (or prefix)" >&2
                exit 1
            fi
            FILTER="$1"; shift
            ;;
        -h|--help)
            echo "Usage: $0 [--all] [--filter HASH]"
            echo ""
            echo "  --all           Show full log history, then follow"
            echo "  --filter HASH   Only show lines matching HASH (prefix match)"
            echo ""
            echo "Log file: $LOG_FILE"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--all] [--filter HASH]" >&2
            exit 1
            ;;
    esac
done

if [[ ! -f "$LOG_FILE" ]]; then
    echo "No centralized log found at: $LOG_FILE"
    echo "Listeners write to this file automatically on startup."
    exit 0
fi

echo ""
echo "═══ CC Listener Log ═══"
echo "  File: $LOG_FILE"
echo ""

if [[ -n "$FILTER" ]]; then
    if [[ "$SHOW_ALL" == true ]]; then
        grep "$FILTER" "$LOG_FILE" 2>/dev/null || true
    fi
    tail -f "$LOG_FILE" | grep --line-buffered "$FILTER"
else
    if [[ "$SHOW_ALL" == true ]]; then
        cat "$LOG_FILE"
    fi
    tail -f "$LOG_FILE"
fi
