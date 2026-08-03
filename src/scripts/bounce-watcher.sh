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

mkdir -p "${BOUNCE_DIR}"

# A crash mid-bounce would strand the in-progress marker and make the endpoint
# answer 409 forever. Clear it on startup — if a bounce were truly running, it was
# this very process, which is not running yet.
rm -f "${INPROGRESS}"

log() { echo "[bounce-watcher] $*"; }

log "watching ${TRIGGER} (heartbeat every ${POLL_INTERVAL}s → ${HEARTBEAT})"

while true; do
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
