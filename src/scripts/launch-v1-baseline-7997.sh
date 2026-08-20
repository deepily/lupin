#!/usr/bin/env bash
#
# Stand up the PINNED v1 baseline arm on :7997 for the CJ Flow v2 paired eval
# (row d8d019f6).
#
# WHY THIS FILE EXISTS AT ALL, and it is the whole lesson: the previous version
# of this launcher lived in a session scratchpad. The scratchpad went away, the
# host power-cycled overnight, and on 2026-08-19 the paired run was blocked not
# by code, a model, or a database, but because nobody could remember how to
# start the server. Every other precondition was green. A launch procedure that
# lives in a scratchpad is a precondition nobody can satisfy twice — so this is
# committed, and the next person re-stands the arm with one command.
#
#   bash src/scripts/launch-v1-baseline-7997.sh           # start
#   bash src/scripts/launch-v1-baseline-7997.sh --check    # verify only, never start
#
# 🔴 THE IDENTITY GATE IS THE POINT (María, 2026-08-19): code-identity must read
# b0735467 BEFORE a single utterance runs. The v1 arm is a BASELINE — its whole
# job is to be the fixed thing the v2 delta is measured against. An arm serving
# any other sha is not a baseline, and a delta computed against it is a number
# with nothing behind it. So this script REFUSES rather than starting, or
# continuing, whenever the identity does not match the pin.
#
# THE FOUR OVERRIDES ARE NOT OPTIONAL AND NOT DECORATIVE. Each is a gap the
# bare-host path hit in sequence during the 2026-08-16 run, recorded in
# src/rnd/v0.2.0/2026.08.16-v2-paired-live-run-results.md §4:
#
#   DB_NAME=lupin_db_v1baseline
#       Isolates the v1 arm's writes. It defaulted to lupin_db_dev — the LIVE
#       dev database. That is a hazard, not a tidiness preference.
#
#   AUTH_MODE=mock
#       The arm authenticates with `mock_token_email_<email>`. The config block
#       is `jwt`, which rejects it.
#
#   LUPIN_MODEL_SERVER_URL + LUPIN_MODEL_SERVER_API_KEY_NAME
#       The bare host has no in-process GPU embedding engine, so routing
#       embeddings must go over the model-server HTTP path — THE SAME BACKEND
#       THE v2 ARM USES. This is what keeps the paired instrument fair; an arm
#       that embeds differently is measuring a different thing.
#
# ⚠️ THE DESIGN DOC PREFERS A CONTAINER FROM THE PINNED SHA over this bare-host
# uvicorn ("the boring, faithful option" —
# 2026.08.15-v1-baseline-standalone-server-design.md). This script reproduces
# the path that was actually used and verified end to end, and carries the
# caveat rather than hiding it: if this arm ever disagrees with the container,
# believe the container.

set -euo pipefail

WORKTREE="/mnt/DATA01/include/www.deepily.ai/projects/lupin-v1-baseline-b0735467"
PINNED_SHA="b0735467"
PORT=7997
MAIN_ROOT="${LUPIN_ROOT:?LUPIN_ROOT must be set (the MAIN tree — its venv runs this)}"
LOG="/tmp/v1-baseline-7997.log"

check_only=0
[[ "${1:-}" == "--check" ]] && check_only=1

# Print the served sha, or fail. NEVER print the whole payload as a fallback.
#
# 🔴 THIS FUNCTION HAD THE EXACT BUG THE GATE EXISTS TO CATCH (María, 2026-08-19).
# It probed d['sha'] / d['code_identity'] — neither of which this endpoint serves —
# and fell back to json.dumps(d), which the callers then SUBSTRING-matched against
# the pin. The record's real field is `git_sha`, and when git cannot read a HEAD the
# record says so in `git_sha_source`: "UNAVAILABLE: git could not read a HEAD sha at
# /…/lupin-v1-baseline-b0735467". That string CONTAINS b0735467 — the worktree is
# named after the pin. So the gate passed, loudest and most convincingly, in precisely
# the case where the sha was explicitly UNAVAILABLE. A gate that can pass without
# reading the value it gates on is not a gate.
#
# Now: read `git_sha` and nothing else, refuse UNAVAILABLE, and let the caller
# PREFIX-match a bare sha rather than searching a blob.
read_identity() {
    python3 -c "
import urllib.request, json, sys
try:
    d = json.load( urllib.request.urlopen( 'http://localhost:$PORT/api/code-identity', timeout=5 ) )
except Exception:
    sys.exit( 1 )
if not isinstance( d, dict ):
    sys.exit( 1 )
sha = d.get( 'git_sha' )
# UNAVAILABLE is a REPORTED MISS, not a value. Treat it as no answer at all.
if not isinstance( sha, str ) or not sha or sha.startswith( 'UNAVAILABLE' ):
    sys.exit( 1 )
print( sha )
" 2>/dev/null
}

# 🔴 CREDENTIAL PARITY WITH THE MAIN TREE (row d8d019f6, 2026-08-20).
#
# THE RUN THIS EXISTS TO PREVENT: on 2026-08-20 the v1 arm posted a 47% failure rate and
# lost two whole routing categories, and it read as a reliability defect in v1. It was not.
# The worktree held TWO key files against the main tree's twelve. Every embed hit
# "Key [openai] not found", returned nothing, and the insert died on "expected 768
# dimensions, not 0" — 300 times. The arm was measured without its credentials, so a
# comparison against it would have blamed an architecture for a missing file.
#
# WHY IT WILL HAPPEN AGAIN WITHOUT THIS: src/conf/keys/ is GITIGNORED. Every worktree is
# born credential-less. This is not a slip in setting up one baseline — it is the default
# state of the next one too.
#
# WHY A DIFF AND NOT A LIST: the check above names model-server-api because that is the key
# somebody thought of. Enumerating keys here would repeat exactly that mistake, one key at a
# time. Comparing the two directories catches whatever the main tree has and this one does
# not, including keys added after this line was written.
assert_credential_parity() {
    local missing_keys
    missing_keys=$( comm -23 \
    <( ls -1 "$MAIN_ROOT/src/conf/keys" 2>/dev/null | sort ) \
    <( ls -1 "$WORKTREE/src/conf/keys"        2>/dev/null | sort ) )
    if [[ -z "$missing_keys" ]]; then return 0; fi
    echo "🔴 the worktree is missing credentials the main tree has — the arm would run" >&2
    echo "   crippled and its failure rate would be read as a v1 defect:" >&2
    echo "$missing_keys" | sed 's/^/     · /' >&2
    echo "   src/conf/keys is gitignored, so a fresh worktree never has them. Copy them:" >&2
    echo "     cp -n $MAIN_ROOT/src/conf/keys/* $WORKTREE/src/conf/keys/" >&2
    exit 1
}

# ── Already running? Verify identity; never start on top of it. ───────────────
if identity=$( read_identity ); then
    echo "[:$PORT] already up — code-identity: $identity"
    case "$identity" in
        "$PINNED_SHA"*)
            # Identity is not capability. On 2026-08-20 the arm was already up, matched the
            # pin, and every re-check said "nothing to do" while it ran without its keys for
            # four hours. Credentials are re-asserted here, not only on a fresh start.
            assert_credential_parity
            echo "[:$PORT] identity matches the pin ($PINNED_SHA). Nothing to do." ; exit 0 ;;
        *) echo "🔴 [:$PORT] REFUSING: a server holds this port and its identity is NOT $PINNED_SHA." >&2
           echo "   A paired run against an unpinned arm measures the wrong thing. Stop that process first." >&2
           exit 1 ;;
    esac
fi

# A port that answers /health but cannot prove its sha is NOT the same failure as a
# port with nothing on it, and saying "DOWN" for both is how a guard that blocks for
# the wrong reason ends up looking exactly like one that works. Name which case it is.
port_answers_health() {
    python3 -c "
import urllib.request, sys
try: urllib.request.urlopen( 'http://localhost:$PORT/health', timeout=2 )
except Exception: sys.exit( 1 )
" 2>/dev/null
}

if port_answers_health; then
    echo "🔴 [:$PORT] a server IS answering /health, but /api/code-identity did not report a" >&2
    echo "   usable git_sha (missing, or the record says UNAVAILABLE). Identity is UNPROVEN —" >&2
    echo "   do NOT run the eval against it, and do NOT assume the port is free." >&2
    exit 1
fi

if [[ "$check_only" -eq 1 ]]; then
    echo "[:$PORT] DOWN — nothing answering (checked, not started)."
    exit 1
fi

# ── Preconditions, each named so a failure says which one ────────────────────
[[ -d "$WORKTREE" ]] || { echo "🔴 worktree missing: $WORKTREE" >&2; exit 1; }
[[ -f "$WORKTREE/src/conf/keys/model-server-api" ]] \
    || { echo "🔴 model-server key missing: $WORKTREE/src/conf/keys/model-server-api" >&2; exit 1; }

assert_credential_parity

actual_sha=$( git -C "$WORKTREE" rev-parse --short HEAD )
[[ "$actual_sha" == "$PINNED_SHA"* ]] \
    || { echo "🔴 worktree HEAD is $actual_sha, expected $PINNED_SHA — the arm would not be the baseline." >&2; exit 1; }

python3 -c "
import urllib.request, sys
try: urllib.request.urlopen( 'http://localhost:7998/health', timeout=5 )
except Exception: sys.exit( 1 )
" || { echo "🔴 model server :7998 is down — embeddings would differ from the v2 arm and un-fair the instrument." >&2; exit 1; }

# ── Launch ───────────────────────────────────────────────────────────────────
echo "[:$PORT] starting pinned v1 arm from $WORKTREE ($PINNED_SHA) → $LOG"

LUPIN_ROOT="$WORKTREE" \
DB_NAME="lupin_db_v1baseline" \
AUTH_MODE="mock" \
LUPIN_MODEL_SERVER_URL="http://localhost:7998" \
LUPIN_MODEL_SERVER_API_KEY_NAME="model-server-api" \
PYTHONPATH="$WORKTREE/src" \
nohup "$MAIN_ROOT/.venv/bin/python" -m uvicorn lupin_app.main:app \
    --host 0.0.0.0 --port "$PORT" >"$LOG" 2>&1 &

pid=$!
echo "[:$PORT] pid $pid — waiting for health"

for _ in $( seq 1 60 ); do
    if python3 -c "
import urllib.request, sys
try: urllib.request.urlopen( 'http://localhost:$PORT/health', timeout=2 )
except Exception: sys.exit( 1 )
" 2>/dev/null; then
        echo "[:$PORT] UP (pid $pid)"
        # THE GATE AGAIN, POST-BOOT. Health only says a server answered; it says
        # nothing about WHICH code answered, and that is the property the whole
        # measurement rests on.
        if identity=$( read_identity ); then
            echo "[:$PORT] code-identity: $identity"
            case "$identity" in
                "$PINNED_SHA"*) echo "[:$PORT] ✅ pinned at $PINNED_SHA — safe to run the paired eval." ; exit 0 ;;
                *) echo "🔴 [:$PORT] booted but identity is $identity, NOT $PINNED_SHA. Do NOT run the eval." >&2
                   exit 1 ;;
            esac
        fi
        echo "🔴 [:$PORT] healthy but /api/code-identity did not answer — identity unproven, do NOT run the eval." >&2
        exit 1
    fi
    sleep 2
done

echo "🔴 [:$PORT] did not come up within 120s — last log lines:" >&2
tail -20 "$LOG" >&2
exit 1
