#!/usr/bin/env bash
# Host-side bounce watcher for the managed :7999 bounce (R2/R3 — the button path).
#
# WHY THIS EXISTS
#   The "bounce dev server" button in the web clients cannot run
#   bounce-dev-server.sh itself: that script issues `docker restart lupin-rest-dev`,
#   and the web process serving the button's request lives INSIDE that container —
#   it would be killed mid-run, taking the health poll (and the all-clear) with it.
#   So the button only DROPS a trigger file into the shared io/ mount, and THIS
#   host-side daemon — which survives the restart — sees the trigger and runs the
#   sanctioned script.
#
#   LIVENESS: this daemon stamps a heartbeat file every loop. The
#   POST /api/system/bounce endpoint reads that heartbeat's freshness and refuses
#   (503) if it is stale, so the button can never silently "succeed" while nothing
#   is actually watching. It also writes an in-progress marker around each bounce so
#   the endpoint can answer 409 ("already bouncing") instead of misreading the
#   heartbeat that goes quiet while the script runs.
#
# HANDSHAKE FILES (all under ${LUPIN_ROOT}/io/bounce, the dev container's bind mount):
#   watcher-heartbeat   epoch seconds, rewritten every loop — the liveness signal
#   bounce.trigger      written by the endpoint; claimed + deleted here
#   bounce.inprogress   epoch seconds, present only while a bounce is running
#
# USAGE (run on the HOST, not in a container):
#   Sanctioned (survives reboot + respawns): install the systemd USER service ONCE
#       LUPIN_ROOT=/path/to/lupin ./src/scripts/install-bounce-watcher.sh
#   A hand-run is for dev only and dies with your shell — the button then 503s:
#       LUPIN_ROOT=/path/to/lupin ./src/scripts/bounce-watcher.sh
# The button that drops the trigger is worthless if nothing is watching, so the
# service (not a remembered by-hand start) is what makes R2 actually work.

set -uo pipefail

if [ -z "${LUPIN_ROOT:-}" ]; then
    echo "ERROR: LUPIN_ROOT is not set — export LUPIN_ROOT=/path/to/project" >&2
    exit 1
fi

BOUNCE_DIR="${LUPIN_ROOT}/io/bounce"
HEARTBEAT="${BOUNCE_DIR}/watcher-heartbeat"
TRIGGER="${BOUNCE_DIR}/bounce.trigger"
INPROGRESS="${BOUNCE_DIR}/bounce.inprogress"
BOUNCE_SCRIPT="${LUPIN_ROOT}/src/scripts/bounce-dev-server.sh"
POLL_INTERVAL="${BOUNCE_WATCHER_POLL_SECS:-2}"

# THE SWITCH (row c38a49bd). `cron job side-services enabled` in the main configuration file is read
# fresh, at most once every SWITCH_RECHECK_SECS, through lupin_mcp.cron_switch_read.read_switch, the
# same parse rule every other job uses. Off or unreadable (no default in code): the loop stays alive,
# but it stamps no heartbeat and claims no trigger, so the button answers 503 instead of pretending.
SWITCH_INI="${BOUNCE_WATCHER_INI:-${LUPIN_ROOT}/src/conf/lupin-app.ini}"
SWITCH_RECHECK_SECS="${BOUNCE_WATCHER_SWITCH_SECS:-60}"
SWITCH_PYTHON="${LUPIN_ROOT}/.venv/bin/python"
[ -x "${SWITCH_PYTHON}" ] || SWITCH_PYTHON="python3"
switch_state="unread"
switch_checked_at=0

mkdir -p "${BOUNCE_DIR}"

# A crash mid-bounce would strand the in-progress marker and make the endpoint
# answer 409 forever. Clear it on startup — if a bounce were truly running, it was
# this very process, which is not running yet.
rm -f "${INPROGRESS}"

log() { echo "[bounce-watcher] $*"; }

log "watching ${TRIGGER} (heartbeat every ${POLL_INTERVAL}s → ${HEARTBEAT})"

# Print on, off or unknown for the side-services switch. A missing interpreter, a failed import
# or an unreadable file all print unknown, never on.
read_switch() {
    PYTHONPATH="${LUPIN_ROOT}/src" "${SWITCH_PYTHON}" -c 'import sys; from lupin_mcp import cron_switch_read as c; print({True: "on", False: "off"}.get(c.read_switch(sys.argv[1], "side-services"), "unknown"))' "${SWITCH_INI}" 2>/dev/null || echo unknown
}

# Refresh switch_state when the last read is old enough, logging one line when the answer changes.
refresh_switch() {
    local now previous answer
    now="$( date +%s )"
    if [ $(( now - switch_checked_at )) -lt "${SWITCH_RECHECK_SECS}" ]; then return; fi
    switch_checked_at="${now}"
    previous="${switch_state}"
    answer="$( read_switch )"
    case "${answer}" in on|off) switch_state="${answer}" ;; *) switch_state="unknown" ;; esac
    if [ "${switch_state}" = "${previous}" ]; then return; fi
    case "${switch_state}" in
        on)      if [ "${previous}" != "unread" ]; then log "INI key 'cron job side-services enabled' is true, so the watcher runs again"; fi ;;
        off)     log "INI key 'cron job side-services enabled' is false, so the watcher stamps no heartbeat and claims no trigger until it is true" ;;
        unknown) log "ERROR: INI key 'cron job side-services enabled' is missing or holds neither true nor false, so the watcher stamps no heartbeat and claims no trigger" ;;
    esac
}

while true; do
    refresh_switch
    if [ "${switch_state}" != "on" ]; then
        # A trigger dropped before the switch went off would fire a surprise bounce on the way back on.
        if [ -f "${TRIGGER}" ]; then rm -f "${TRIGGER}"; log "discarded a trigger seen while the switch is not on"; fi
        sleep "${POLL_INTERVAL}"
        continue
    fi

    # Stamp liveness every loop — this is exactly what the endpoint checks.
    date +%s > "${HEARTBEAT}"

    if [ -f "${TRIGGER}" ]; then
        # Claim the trigger by deleting it BEFORE running, so a duplicate press
        # that lands during the bounce cannot queue a second run behind this one.
        rm -f "${TRIGGER}"
        date +%s > "${INPROGRESS}"
        log "trigger seen — running the managed bounce"
        bounce_rc=0
        "${BOUNCE_SCRIPT}" --quiet || bounce_rc=$?
        if [ "${bounce_rc}" -eq 0 ]; then
            log "managed bounce completed (all-clear emitted by the server on startup)"
        else
            log "managed bounce FAILED (rc=${bounce_rc}) — see: docker logs lupin-rest-dev"
        fi
        rm -f "${INPROGRESS}"
        # Freshen the heartbeat immediately after a (possibly long) bounce so a
        # click right after does not see a stale beat from before the restart.
        date +%s > "${HEARTBEAT}"
    fi

    sleep "${POLL_INTERVAL}"
done
