#!/bin/bash
# Convenience wrapper for the cascade heartbeat scheduler.
#
# Usage: start-cascade-heartbeat.sh <manager_persona> [extra-args...]
#
# Example:
#   start-cascade-heartbeat.sh tiberius
#   start-cascade-heartbeat.sh tiberius --cadence-active 120 --max-ticks 5
#
# Doctrine reference: planning-is-prompting/workflow/plan-review-cascaded.md §6.4
#                     planning-is-prompting/src/rnd/2026.05.18-cascaded-prototype-postmortem.md §6.B
#
# Exits with PID printed to stdout; daemon detaches via nohup + disown.

set -e

MANAGER="${1:?Usage: $0 <manager_persona> [extra-args...]}"
shift  # consume manager arg; remaining args pass through to the python daemon

: "${LUPIN_ROOT:?LUPIN_ROOT environment variable must be set (e.g. export LUPIN_ROOT=/path/to/lupin)}"

SCRIPT="$LUPIN_ROOT/src/scripts/cascade_heartbeat_scheduler.py"
LOG="/tmp/cascade-heartbeat-${MANAGER}.log"

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: $SCRIPT not found" >&2
    exit 1
fi

nohup python "$SCRIPT" \
    --manager "$MANAGER" \
    --cadence-active 180 \
    --cadence-idle 300 \
    --strikes 3 \
    --input-plan-topic cascaded-prototype-input-plan \
    "$@" \
    > "$LOG" 2>&1 &

PID=$!
disown $PID 2>/dev/null

cat <<EOF
Cascade heartbeat scheduler started
  Manager  : $MANAGER
  PID      : $PID
  Log      : $LOG
  Stop     : kill $PID
EOF
