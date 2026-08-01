#!/usr/bin/env bash
# Managed bounce of the DEV server (port 7999) — the SANCTIONED bounce path (R4).
#
# Sequence (design: src/rnd/v0.1.9/2026.08.01-managed-bounce-for-7999.md §4):
#   1. Post the ack-CONFIRMED warning broadcast (bounce_dev_warn.py) so the fleet
#      is told to hold notifications BEFORE the server dies — and we wait for the
#      warning to actually be delivered, not merely queued.
#   2. Restart the container.
#   3. Poll /health until ready.
# The all-clear (R5) is NOT sent by this script — the restarted server emits it
# from its own startup hook, which covers every restart path, not just this one.
#
# ⚠️ VERB: this uses `docker restart`, which REUSES the container. That serves new
# Python (bind-mounted) but does NOT apply docker-compose.yml / bind-mount / env
# changes — those need `docker compose up -d --force-recreate lupin-rest-dev`,
# which is a LONGER outage. If you changed a mount or compose value, use that
# instead; this script's health deadline is sized with headroom for either.
#
# Usage:
#   ./src/scripts/bounce-dev-server.sh          # verbose
#   ./src/scripts/bounce-dev-server.sh --quiet  # one-line summary only

set -euo pipefail

CONTAINER="lupin-rest-dev"
HEALTH_URL="http://localhost:7999/health"
TIMEOUT_SECS=60           # sized for the slower (recreate) path, not just restart
POLL_INTERVAL=0.5
QUIET=0

for arg in "$@"; do
    case "$arg" in
        --quiet|-q) QUIET=1 ;;
        -h|--help)
            sed -n '2,22p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

log() { [ "$QUIET" -eq 1 ] || echo "$@"; }

if [ -z "${LUPIN_ROOT:-}" ]; then
    echo "ERROR: LUPIN_ROOT is not set — export LUPIN_ROOT=/path/to/project" >&2
    exit 1
fi

# ── Step 1: ack-confirmed warning ─────────────────────────────────────────────
# Non-zero exit is NOT fatal here: partial reach (1) or a wedged server we could
# not reach (2) both still want the restart — that IS the recovery. We proceed
# and let the warning helper's own message say what happened.
log "Warning the fleet before the bounce..."
warn_rc=0
python3 "${LUPIN_ROOT}/src/scripts/bounce_dev_warn.py" || warn_rc=$?
if [ "$warn_rc" -ne 0 ]; then
    log "Warning broadcast exited ${warn_rc} (partial reach or server unreachable) — proceeding with the bounce."
fi

# ── Step 2: restart ───────────────────────────────────────────────────────────
log "Restarting container: $CONTAINER (docker restart — reuses container)"
start_ts=$(date +%s)
if ! docker restart "$CONTAINER" >/dev/null; then
    echo "ERROR: docker restart failed for $CONTAINER" >&2
    exit 1
fi

# ── Step 3: health poll ───────────────────────────────────────────────────────
log "Polling $HEALTH_URL (timeout ${TIMEOUT_SECS}s)..."
deadline=$(( start_ts + TIMEOUT_SECS ))
while :; do
    now=$(date +%s)
    if [ "$now" -ge "$deadline" ]; then
        echo "ERROR: $CONTAINER did not become healthy within ${TIMEOUT_SECS}s — server may be DOWN." >&2
        echo "       The startup all-clear will NOT have fired. Investigate before assuming it is up." >&2
        echo "--- docker logs --tail 50 $CONTAINER ---" >&2
        docker logs --tail 50 "$CONTAINER" >&2 || true
        exit 1
    fi
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        elapsed=$(( now - start_ts ))
        if [ "$QUIET" -eq 1 ]; then
            echo "bounced ${CONTAINER} in ${elapsed}s (all-clear emitted by server startup)"
        else
            log "OK: $CONTAINER healthy in ${elapsed}s. The server's startup hook emits the all-clear."
        fi
        exit 0
    fi
    sleep "$POLL_INTERVAL"
done
