#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# restart-cc-listeners.sh — Restart all running CC Notification Listener
# subprocesses so they reload edited hook/listener code.
#
# WHY: each cc_notification_listener is a long-running per-session
# subprocess (spawned at SessionStart) that imports heartbeat_events.py /
# cc_notification_listener.py ONCE into memory and does NOT hot-reload.
# After a fix lands on disk (e.g. bug baf5ea6d), the running listeners keep
# executing the OLD code until restarted. This script kills each live
# listener and relaunches it with the SAME argv it was running (so
# --session-id / --accepted-ids / log paths are preserved exactly),
# detached, picking up the new on-disk code.
#
# Idempotent-safe: re-running it just restarts whatever is currently live.
#
# Usage:
#   bash src/scripts/restart-cc-listeners.sh           # restart all live listeners
#   bash src/scripts/restart-cc-listeners.sh --dry-run # show what would restart
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

LR="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"
SESS_DIR="$HOME/.claude/sessions"

export LUPIN_ROOT="$LR"
export PYTHONPATH="$LR/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1

mapfile -t PIDS < <( pgrep -f "cc_notification_listener --session-id" || true )

if [[ ${#PIDS[@]} -eq 0 ]]; then
    echo "No running cc_notification_listener subprocesses found."
    exit 0
fi

echo "Found ${#PIDS[@]} live listener(s)."
echo ""

for pid in "${PIDS[@]}"; do
    argv=$( ps -p "$pid" -o args= 2>/dev/null )
    [[ -z "$argv" ]] && continue
    sid=$( echo "$argv" | grep -oP '(?<=--session-id )\S+' || echo "?" )

    if $DRY_RUN; then
        echo "[dry-run] would restart session=$sid (PID $pid)"
        continue
    fi

    echo "Restarting session=$sid (old PID $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 1

    # Relaunch with the exact captured argv (preserves --session-id /
    # --accepted-ids / --log-file / --centralized-log), detached, with
    # stdout -> centralized log and stderr -> per-session stderr file
    # (mirrors _spawn_listener's Popen redirection).
    # shellcheck disable=SC2086
    setsid env LUPIN_ROOT="$LR" PYTHONPATH="$LR/src" PYTHONUNBUFFERED=1 \
        $argv \
        >> "$SESS_DIR/cc-listeners.log" \
        2>> "$SESS_DIR/cc-listener-$sid.stderr" &
    sleep 1
done

if $DRY_RUN; then
    exit 0
fi

sleep 2
echo ""
echo "=== Listeners after restart ==="
pgrep -af "cc_notification_listener --session-id" || echo "  (none — investigate stderr files)"
