#!/usr/bin/env bash
# Force the test server (port 8000) to pick up source changes.
# Restarts the `lupin-rest-test` container and polls /health until ready.
#
# Usage:
#   ./src/scripts/refresh-test-server.sh          # verbose
#   ./src/scripts/refresh-test-server.sh --quiet  # one-line summary only

set -euo pipefail

CONTAINER="lupin-rest-test"
HEALTH_URL="http://localhost:8000/health"
TIMEOUT_SECS=30
POLL_INTERVAL=0.5
QUIET=0

for arg in "$@"; do
    case "$arg" in
        --quiet|-q) QUIET=1 ;;
        -h|--help)
            sed -n '2,9p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

log() { [ "$QUIET" -eq 1 ] || echo "$@"; }

log "Restarting container: $CONTAINER"
start_ts=$(date +%s)
if ! docker restart "$CONTAINER" >/dev/null; then
    echo "ERROR: docker restart failed for $CONTAINER" >&2
    exit 1
fi

log "Polling $HEALTH_URL (timeout ${TIMEOUT_SECS}s)..."
deadline=$(( start_ts + TIMEOUT_SECS ))
while :; do
    now=$(date +%s)
    if [ "$now" -ge "$deadline" ]; then
        echo "ERROR: health check did not pass within ${TIMEOUT_SECS}s" >&2
        echo "--- docker logs --tail 50 $CONTAINER ---" >&2
        docker logs --tail 50 "$CONTAINER" >&2 || true
        exit 1
    fi
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        elapsed=$(( now - start_ts ))
        if [ "$QUIET" -eq 1 ]; then
            echo "refreshed ${CONTAINER} in ${elapsed}s"
        else
            log "OK: $CONTAINER healthy in ${elapsed}s"
        fi
        exit 0
    fi
    sleep "$POLL_INTERVAL"
done
