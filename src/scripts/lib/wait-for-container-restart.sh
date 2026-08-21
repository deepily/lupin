#!/usr/bin/env bash
#
# wait-for-container-restart.sh — wait until a container's OWN start time is newer than
# a given instant. Identity, not liveness.
#
# WHY THIS EXISTS SEPARATELY FROM wait-for-health.sh. The two guard DIFFERENT lies and
# neither substitutes for the other (Mr Radio, 2026-08-21):
#   · wait-for-health.sh counts consecutive OKs. That defends against BURSTS — a loaded
#     server answering intermittently. It does NOT defend against too-early: three 200s
#     at 0.5s spacing is a 1.5-second window, and the OLD process can comfortably answer
#     all three in that window after `docker restart` is issued but before it dies.
#   · THIS script defends against too-early, and it does it by IDENTITY: the container's
#     StartedAt must be newer than the moment we asked for the restart. A count cannot
#     establish that no matter how high you set it.
# Tiberius hit the too-early failure on :7999 on 2026-08-19 — his first 200 came from the
# process that was on its way out.
#
# Usage:  wait-for-container-restart.sh <container> <not-before-epoch> [--timeout SECS] [--interval SECS] [--quiet]
# Exit:   0 = the container reports a start newer than not-before-epoch
#         1 = deadline passed without it
#         2 = bad usage / the container's start time could not be read

set -euo pipefail

CONTAINER="${1:-}"
NOT_BEFORE="${2:-}"
shift 2 2>/dev/null || true

TIMEOUT_SECS="${RESTART_TIMEOUT_SECS:-60}"
INTERVAL="${RESTART_POLL_INTERVAL:-0.5}"
QUIET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --timeout)  TIMEOUT_SECS="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --quiet|-q) QUIET=1; shift ;;
        -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
        *)          echo "wait-for-container-restart: unexpected argument $1" >&2; exit 2 ;;
    esac
done

if [ -z "$CONTAINER" ] || [ -z "$NOT_BEFORE" ]; then
    echo "wait-for-container-restart: usage: <container> <not-before-epoch> [options]" >&2
    exit 2
fi
if ! [ "$NOT_BEFORE" -ge 0 ] 2>/dev/null; then
    echo "wait-for-container-restart: not-before-epoch must be an integer, got '$NOT_BEFORE'" >&2
    exit 2
fi

log() { [ "$QUIET" -eq 1 ] || echo "[wait-for-restart] $*"; }

# docker prints RFC3339 with nanoseconds; `date -d` handles it, but a container that has
# never run reports the zero time, which must NOT be mistaken for "started long ago and
# therefore fine" — it parses to epoch -6795364578 or similar, which is < NOT_BEFORE, so
# the comparison below correctly keeps waiting rather than passing.
started_epoch() {
    local raw
    raw=$( docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null ) || return 1
    [ -n "$raw" ] || return 1
    date -d "$raw" +%s 2>/dev/null || return 1
}

deadline=$(( $( date +%s ) + TIMEOUT_SECS ))
log "waiting for $CONTAINER to report a start newer than $NOT_BEFORE (timeout ${TIMEOUT_SECS}s)"

while :; do
    if [ "$( date +%s )" -ge "$deadline" ]; then
        echo "wait-for-container-restart: $CONTAINER did not report a start newer than $NOT_BEFORE within ${TIMEOUT_SECS}s" >&2
        exit 1
    fi

    if current=$( started_epoch ); then
        if [ "$current" -ge "$NOT_BEFORE" ]; then
            log "OK — $CONTAINER started at $current, at or after $NOT_BEFORE"
            exit 0
        fi
        log "still the old process: started $current, need >= $NOT_BEFORE"
    else
        log "could not read StartedAt for $CONTAINER — retrying"
    fi

    sleep "$INTERVAL"
done
