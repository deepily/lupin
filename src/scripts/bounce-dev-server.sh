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
#   ./src/scripts/bounce-dev-server.sh --force  # skip dirty-tree confirm + unwarned pause + running-job refusal
#
# When the warning helper reports exit 2 (nobody was warned at all), the bounce
# still proceeds — a broken warn path must not block recovery of a wedged server —
# but it PAUSES first (UNWARNED_PAUSE_SECS, default 5) so a human gets the beat to
# abort a bounce that will look like a crash to the fleet. --force skips that pause.
#
# DIRTY-TREE AWARENESS (row 7de5a09f): with auto-reload off and the repo bind-mounted,
# a bounce serves EVERY saved file in the tree — committed or not, from every session —
# not just the bouncer's work. So before restarting, if the tree is dirty this script
# NAMES the dirty files (git status --short). For a DIRTY TREE it NEVER fails closed and
# NEVER refuses a non-interactive caller (the running-job guard at Step 0.5 is the ONE
# deliberate exception — it refuses a bounce that would destroy a live job, --force over-
# rides, and it still fails OPEN when its probe is unreachable):
#   • at a TERMINAL ([ -t 0 ]): asks a y/N; answering no aborts (exit 3) before the
#     restart. --force skips this human prompt.
#   • non-interactive (every Claude session): PROCEEDS after naming the files — no
#     --force needed — and the dirty list rides the warning broadcast so the seat that
#     OWNS a file can object during the ack window.
# A tree that is not a git repo is treated as clean — the hand-run bounce must always
# be able to recover a wedged server.

set -euo pipefail

CONTAINER="lupin-rest-dev"
HEALTH_URL="http://localhost:7999/health"
TIMEOUT_SECS=60           # sized for the slower (recreate) path, not just restart
POLL_INTERVAL=0.5
# A SINGLE health 200 does not mean the new process is up. Two ways it lies: the OLD
# process can still be answering in the moment after `docker restart` is issued (Tiberius
# hit exactly this on 2026-08-19 and required three 200s by hand before believing it), and
# a loaded server answers in bursts, so one call is a coin flip (row 1c36199e measured
# /health at 0.47s and then timing out 36s later on :8000). Require consecutive successes.
HEALTH_CONSECUTIVE="${HEALTH_CONSECUTIVE:-3}"     # env-overridable; tests set 1
QUIET=0
FORCE=0
UNWARNED_PAUSE_SECS="${UNWARNED_PAUSE_SECS:-5}"   # env-overridable (tests set 0)

for arg in "$@"; do
    case "$arg" in
        --quiet|-q) QUIET=1 ;;
        --force|-f) FORCE=1 ;;
        -h|--help)
            sed -n '2,27p' "$0"
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

# ── Step 0: dirty-tree awareness ──────────────────────────────────────────────
# A bounce serves EVERY saved file in the bind-mounted tree, committed or not, from
# EVERY session (row 7de5a09f, observed live boot #12) — reload is off, so a restart
# deploys disk state, not the bouncer's commit. The fleet-idle precondition checks
# ATTENTION, nothing checks the TREE. So NAME the dirty files before the restart.
#
# ⚠️ NEVER fail-closed, and NEVER refuse a NON-INTERACTIVE caller. Every Claude
# session invokes this without a TTY, and the tree is essentially always dirty — so
# an abort-by-default would make the sanctioned path refuse the fleet's most common
# bouncer (gate ruling, row 7de5a09f). Two channels instead:
#   • a human AT A TERMINAL (`[ -t 0 ]`) gets a y/N and can abort (exit 3) — the beat
#     to stop before deploying someone's mid-edit;
#   • a non-TTY caller PROCEEDS after naming the files, no --force required, and the
#     dirty list rides the warning broadcast (BOUNCE_DIRTY_FILES → bounce_dev_warn.py)
#     so the seat that OWNS a file can object during the ack window — the reach a
#     skipped prompt can never deliver to an agent.
# --force stays "skip the human pauses" ONLY; it is not the sole way an agent bounces.
# A non-git LUPIN_ROOT yields empty status (treated clean), never an error. Comes
# BEFORE the warn broadcast so a human abort fires no false alarm.
#
# `git -C` follows LUPIN_ROOT, not the caller's cwd. 2>/dev/null + `|| true` keep a
# non-repo tree from tripping set -e. Exported so Step 1's warn helper can name it.
export BOUNCE_DIRTY_FILES="$( git -C "$LUPIN_ROOT" status --short 2>/dev/null || true )"
if [ -n "$BOUNCE_DIRTY_FILES" ]; then
    # Unconditional (not log()): may precede a blocking prompt, and it is the record
    # of what this bounce will deploy — it must show even under --quiet.
    echo "⚠️  The working tree is DIRTY — this bounce will serve these saved files too, not just committed work:"
    echo "$BOUNCE_DIRTY_FILES"
    if [ "$FORCE" -eq 1 ]; then
        log "    --force given — not pausing for confirmation."
    elif [ -t 0 ]; then
        echo "    (commit or stash to deploy only reviewed work, or re-run with --force to skip this prompt.)"
        printf 'Proceed with the bounce anyway? [y/N] '
        read -r reply || reply=""
        case "$reply" in
            y|Y|yes|YES)
                log "Proceeding on a dirty tree by confirmation."
                ;;
            *)
                echo "Aborted — tree is dirty and not confirmed. Commit/stash, or re-run with --force." >&2
                exit 3
                ;;
        esac
    else
        # Non-interactive: proceed (never refuse an agent), and rely on the broadcast
        # carrying BOUNCE_DIRTY_FILES so the owning seat can object during the ack window.
        log "    Non-interactive caller — proceeding; the warning broadcast names these files so their owner can object."
    fi
fi

# ── Step 0.5: running-job guard (row 08919110, Rick's ruling 2026-08-02) ──────────
# THE ONE PLACE THIS SCRIPT REFUSES. A restart DESTROYS any job running in the container
# — Rick lost a podcast generation job to a pending bounce. A running job is NOT a dirty
# tree: a dirty tree is recoverable (the bounce is often how you deploy it), a running job
# is work no re-bounce brings back. So this step DELIBERATELY reverses the "never refuses"
# letter of Step 0 above: on a detected live job it REFUSES (exit 4), it does not merely
# warn. "Ask first" was rejected because the bouncer cannot enumerate what is running from
# outside the box — the refusal is a mechanism, not a reminder someone must keep.
#
#   • bounce_busy_probe.py GETs the unauthenticated /api/busy (two ints:
#     inflight_agentic_jobs + run_queue_size) and exits 0=idle, 10=busy (either > 0,
#     the OR trigger), 20=unreachable/malformed.
#   • BUSY (10) → REFUSE (exit 4) UNLESS --force, the deliberate override that keeps the
#     wedged-server recovery path open.
#   • UNREACHABLE (20) or any unexpected code → FAIL OPEN and proceed. A wedged server has
#     no job to protect and is exactly the case the probe cannot reach; a probe that could
#     block recovery would be worse than the job-loss this guards. So the "never fails
#     CLOSED" spirit of the line-32 rule is kept — only its "never refuses" letter changes,
#     and only for an affirmatively-detected live job.
# Runs BEFORE the warn broadcast so a refused bounce never fires a false fleet alarm.
log "Checking for a running job on :7999 before the bounce..."
busy_rc=0
python3 "${LUPIN_ROOT}/src/scripts/bounce_busy_probe.py" || busy_rc=$?
case "$busy_rc" in
    0)
        log "No job running on :7999 — safe to bounce."
        ;;
    10)
        if [ "$FORCE" -eq 1 ]; then
            log "⚠️  A job is RUNNING on :7999 — --force given, bouncing anyway and DESTROYING it."
        else
            echo "REFUSED: a job is running on :7999 and this bounce would destroy it (row 08919110)." >&2
            echo "        Wait for it to finish, or re-run with --force to bounce anyway." >&2
            exit 4
        fi
        ;;
    *)
        # 20 (unreachable / malformed) and any unexpected code: FAIL OPEN — a broken probe
        # must never block recovery of a wedged server (which is why it is unreachable).
        log "Busy-probe reported no live job it could confirm (rc ${busy_rc}) — failing OPEN and proceeding."
        ;;
esac

# ── Step 1: ack-confirmed warning ─────────────────────────────────────────────
# bounce_dev_warn.py distinguishes THREE outcomes (its own header):
#   0 — every recipient acked (or zero active sessions)
#   1 — PARTIAL reach: the broadcast went out, some sessions did not ack in time
#   2 — FAILED: nobody was warned at all (broadcast errored / server unreachable)
# None is fatal — a broken warn path must never block recovery of a wedged server,
# and the hand-run restart IS the recovery path. But 1 and 2 are NOT the same event
# and must not read the same (row 32e659f1): on 1 the fleet WAS warned; on 2 a bounce
# nobody was warned about is indistinguishable from a crash — the exact state the
# warning exists to prevent. So 2 names itself in those words and PAUSES (skippable
# with --force) to give a human the beat to abort; 1 proceeds directly.
log "Warning the fleet before the bounce..."
warn_rc=0
python3 "${LUPIN_ROOT}/src/scripts/bounce_dev_warn.py" || warn_rc=$?
case "$warn_rc" in
    0)
        log "Warning confirmed reached the fleet."
        ;;
    1)
        log "Warning reached the fleet only PARTIALLY (some sessions did not ack in time) — proceeding with the bounce."
        ;;
    *)
        # exit 2 (nobody warned) AND any unexpected non-zero code: assume the fleet
        # was NOT warned and make that impossible to miss, then proceed anyway.
        log "⚠️  Warning FAILED (exit ${warn_rc}) — NOBODY was warned; this bounce will look like a CRASH to the fleet."
        if [ "$FORCE" -eq 1 ]; then
            log "    --force given — proceeding immediately."
        elif [ "$UNWARNED_PAUSE_SECS" -gt 0 ]; then
            log "    Pausing ${UNWARNED_PAUSE_SECS}s before bouncing anyway — Ctrl-C to abort, or re-run with --force to skip this pause."
            sleep "$UNWARNED_PAUSE_SECS"
        fi
        ;;
esac

# ── Step 2: restart ───────────────────────────────────────────────────────────
log "Restarting container: $CONTAINER (docker restart — reuses container)"
start_ts=$(date +%s)
if ! docker restart "$CONTAINER" >/dev/null; then
    echo "ERROR: docker restart failed for $CONTAINER" >&2
    exit 1
fi

# ── Step 3: health poll ───────────────────────────────────────────────────────
# Delegated to src/scripts/lib/wait-for-health.sh, which requires HEALTH_CONSECUTIVE
# successes IN A ROW. One 200 is not proof: right after `docker restart` the OLD process
# can still be answering (hit on :7999, 2026-08-19), and a loaded server answers in
# bursts (measured on :8000, row 1c36199e). The helper is separate so it can be tested
# without running this script, which restarts a container and broadcasts to the fleet —
# see src/tests/unit/test_wait_for_health.py.
log "Polling $HEALTH_URL (need ${HEALTH_CONSECUTIVE} consecutive OKs, timeout ${TIMEOUT_SECS}s)..."

health_args=( "$HEALTH_URL"
              --consecutive "$HEALTH_CONSECUTIVE"
              --timeout     "$TIMEOUT_SECS"
              --interval    "$POLL_INTERVAL" )
# NOT `[ ... ] && health_args+=(...)` — under `set -e` that whole list returns 1 when
# QUIET is 0 and kills the script right here, one line before the poll.
if [ "$QUIET" -eq 1 ]; then health_args+=( --quiet ); fi

if "${LUPIN_ROOT}/src/scripts/lib/wait-for-health.sh" "${health_args[@]}"; then
    elapsed=$(( $( date +%s ) - start_ts ))
    if [ "$QUIET" -eq 1 ]; then
        echo "bounced ${CONTAINER} in ${elapsed}s (all-clear emitted by server startup)"
    else
        log "OK: $CONTAINER healthy in ${elapsed}s — ${HEALTH_CONSECUTIVE} consecutive health checks. The server's startup hook emits the all-clear."
    fi
    exit 0
fi

echo "ERROR: $CONTAINER did not become healthy within ${TIMEOUT_SECS}s — server may be DOWN." >&2
echo "       The startup all-clear will NOT have fired. Investigate before assuming it is up." >&2
echo "--- docker logs --tail 50 $CONTAINER ---" >&2
docker logs --tail 50 "$CONTAINER" >&2 || true
exit 1
