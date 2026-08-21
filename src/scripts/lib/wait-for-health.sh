#!/usr/bin/env bash
#
# wait-for-health.sh — poll a health URL until it answers N times IN A ROW, or give up.
#
# WHY N IN A ROW AND NOT ONE. A single 200 does not mean the thing you are waiting for is
# up. It lies in two directions we have both actually hit:
#   · TOO EARLY — right after `docker restart` is issued, the OLD process can still be
#     answering. Tiberius hit this on :7999 on 2026-08-19 and required three 200s by hand
#     before believing a bounce was clean.
#   · TOO NOISY — a loaded server answers in bursts, so one call is a coin flip. Measured
#     on :8000 under a monopolize run (row 1c36199e): /health answered in 0.47s and timed
#     out 36 seconds later, and 6 of 8 samples had every endpoint time out together.
# A failure RESETS the count: a run of 200s broken by a 500 is not a run.
#
# Usage:  wait-for-health.sh <url> [--consecutive N] [--timeout SECS] [--interval SECS] [--quiet]
# Exit:   0 = reached the streak · 1 = deadline passed without it · 2 = bad usage
#
# Deliberately standalone so it can be tested without running whatever calls it — the
# callers do irreversible things (restart a container, broadcast to the fleet) and a test
# must never need those.

set -euo pipefail

URL=""
CONSECUTIVE="${HEALTH_CONSECUTIVE:-3}"
TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
INTERVAL="${HEALTH_POLL_INTERVAL:-0.5}"
QUIET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --consecutive) CONSECUTIVE="$2"; shift 2 ;;
        --timeout)     TIMEOUT_SECS="$2"; shift 2 ;;
        --interval)    INTERVAL="$2"; shift 2 ;;
        --quiet|-q)    QUIET=1; shift ;;
        -h|--help)     sed -n '2,20p' "$0"; exit 0 ;;
        -*)            echo "wait-for-health: unknown option $1" >&2; exit 2 ;;
        *)             if [ -n "$URL" ]; then echo "wait-for-health: more than one url" >&2; exit 2; fi
                       URL="$1"; shift ;;
    esac
done

if [ -z "$URL" ]; then
    echo "wait-for-health: a health url is required" >&2
    exit 2
fi
if ! [ "$CONSECUTIVE" -ge 1 ] 2>/dev/null; then
    echo "wait-for-health: --consecutive must be a positive integer, got '$CONSECUTIVE'" >&2
    exit 2
fi

log() { [ "$QUIET" -eq 1 ] || echo "[wait-for-health] $*"; }

start_ts=$( date +%s )
deadline=$(( start_ts + TIMEOUT_SECS ))
streak=0
attempts=0

log "polling $URL — need $CONSECUTIVE consecutive OKs, giving up after ${TIMEOUT_SECS}s"

while :; do
    now=$( date +%s )
    if [ "$now" -ge "$deadline" ]; then
        echo "wait-for-health: $URL did not reach $CONSECUTIVE consecutive OKs within ${TIMEOUT_SECS}s (best streak ended at $streak, $attempts attempts)" >&2
        exit 1
    fi

    attempts=$(( attempts + 1 ))
    if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
        streak=$(( streak + 1 ))
        if [ "$streak" -ge "$CONSECUTIVE" ]; then
            log "OK — $streak consecutive OKs after ${attempts} attempts, $(( now - start_ts ))s"
            exit 0
        fi
    else
        if [ "$streak" -gt 0 ]; then
            log "streak broken at ${streak}/${CONSECUTIVE} — restarting the count"
        fi
        streak=0
    fi

    sleep "$INTERVAL"
done
