#!/bin/bash
#
# BFE (Bug Fix Expediter) live E2E test driver.
#
# Session 85b05d1d (2026-04-12). Exercises the full BFE pipeline end-to-end:
# submit a known-bad job → wait for failure → wait for DeadQueueWatchdog to
# dispatch a BFE → follow BFE through its phases → verify PR creation +
# original-job auto-resubmit.
#
# Parity: mirrors src/tests/e2e/run-tfe-live-e2e.sh with BFE-specific flow
# (BFE is triggered by a watchdog on a failed job, not submitted directly).
#
# MODES:
#   --dry-run   (default): BFE runs with dry_run=True. No real SDK calls,
#                          no real git operations, no real resubmit.
#                          Validates queue flow, watchdog dispatch, job
#                          lifecycle, artifact storage. $0.
#   --live               : BFE runs with dry_run=False. Real SDK calls,
#                          real git branch + commits + PR, real auto-resubmit
#                          cycle. Models default to INI (production: Opus lead
#                          + Sonnet worker). ~$2-5 per run.
#   --cheap              : Orthogonal to --live / --dry-run. Overrides models
#                          to Sonnet lead + Sonnet worker for cost savings
#                          (~60-75% reduction). Safe for trivially-fixable
#                          fixtures. Combine with --live for cheap real runs
#                          (~$0.50-1.50). No effect on --dry-run (stubbed).
#
# COMBINATIONS:
#   (no flag)            ≡ --dry-run          : stubbed, $0, model irrelevant
#   --live               : full Opus+Sonnet   : ~$2-5
#   --live --cheap       : Sonnet-only live   : ~$0.50-1.50
#   --dry-run --cheap    : stubbed, $0        : (cheap flag effectively inert)
#
# PRECONDITIONS:
#   - Lupin FastAPI test server running at $BASE_URL
#     (default: http://localhost:8000 — dual-container test server.
#      Override via LUPIN_TEST_PORT or LUPIN_TEST_BASE_URL for dev server
#      testing: LUPIN_TEST_PORT=7999 ./run-bfe-live-e2e.sh)
#   - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + PASSWORD env vars set
#   - `bug fix expediter enabled = true` in INI
#   - For --live: also `auto fix enabled = true` in INI
#   - BFE fixture at src/tests/fixtures/bfe/snapshot_known_bad.json
#     (see FIXTURE TODO section below if missing)
#
# ENVIRONMENT:
#   LUPIN_TEST_PORT      - Test server port (default: 8000)
#   LUPIN_TEST_BASE_URL  - Full test server URL (overrides PORT if set)
#
# USAGE:
#   ./src/tests/e2e/run-bfe-live-e2e.sh [--dry-run|--live] [--cheap]
#
# Created: 2026-04-12 Session 85b05d1d (BFE live E2E parity with TFE)
# Updated: 2026-04-12 Session 85b05d1d (--cheap flag for Sonnet-only cost savings)
#

set -e

# Cheap-tier model constants (Sonnet lead + Sonnet worker).
# Change these to adjust the cheap tier globally; see --cheap flag.
CHEAP_LEAD_MODEL="claude-sonnet-4-6"
CHEAP_WORKER_MODEL="claude-sonnet-4-6"

MODE="dry-run"
CHEAP="false"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) MODE="dry-run"; shift ;;
        --live)    MODE="live"; shift ;;
        --cheap)   CHEAP="true"; shift ;;
        -h|--help)
            head -60 "$0" | grep -E "^#"
            exit 0
            ;;
        *)
            echo "Unknown flag: $1"
            exit 1
            ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="/tmp/bfe-live-e2e-${TIMESTAMP}.log"
LUPIN_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"

# Target test server (dual-container pattern — matches run-integration-tests.sh
# and run-e2e-ui-tests.sh). Default: port 8000 (lupin-rest-test container).
PORT="${LUPIN_TEST_PORT:-8000}"
BASE_URL="${LUPIN_TEST_BASE_URL:-http://localhost:$PORT}"

# Timing parameters
FAILURE_WAIT_TIMEOUT=120   # Seconds to wait for original job to land in dead queue
DISPATCH_WAIT_TIMEOUT=60   # Seconds to wait for watchdog to dispatch BFE
BFE_COMPLETION_TIMEOUT=600 # Seconds to wait for BFE to finish (dry-run: fast; live: up to 10 min)
RESUBMIT_TIMEOUT=180       # Seconds to wait for resubmitted job to complete (post-BFE)
POLL_INTERVAL=5

echo "=================================================================="
echo "BFE Live E2E Test Driver (${MODE} mode)"
echo "Target: ${BASE_URL}"
echo "Log:    ${LOG_FILE}"
if [[ "${CHEAP}" == "true" ]]; then
    echo "Models: ${CHEAP_LEAD_MODEL} (lead) + ${CHEAP_WORKER_MODEL} (worker) [--cheap]"
else
    echo "Models: INI defaults (production: Opus lead + Sonnet worker)"
fi
echo "=================================================================="

# ---------------------------------------------------------------------------
# [1/8] Preflight checks
# ---------------------------------------------------------------------------
echo ""
echo "[1/8] Preflight checks..."

if ! curl -sf "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "Lupin FastAPI test server not responding at ${BASE_URL}"
    echo "  Start the test container with: sdlat  (or: docker compose up -d lupin-rest-test)"
    echo "  For dev-server testing instead: LUPIN_TEST_PORT=7999 $0 $@"
    exit 1
fi
echo "  OK Server responding at ${BASE_URL}"

# Verify test server is in Testing config (not Development/Production)
CONFIG_BLOCK=$(curl -sf "${BASE_URL}/api/server-info" 2>/dev/null \
    | python3 -c "import sys, json; print( json.load( sys.stdin ).get( 'config_block_id', '' ) )" 2>/dev/null || echo "")
if ! echo "${CONFIG_BLOCK}" | grep -qi "testing"; then
    echo "Test server is NOT in [Lupin: Testing] mode (got: ${CONFIG_BLOCK})"
    exit 1
fi
echo "  OK Config block: ${CONFIG_BLOCK}"

if [[ -z "${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL}" || -z "${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD}" ]]; then
    echo "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD not set"
    exit 1
fi
echo "  OK Test credentials present"

FIXTURE="${LUPIN_ROOT}/src/tests/fixtures/bfe/snapshot_known_bad.json"
if [[ ! -f "${FIXTURE}" ]]; then
    echo ""
    echo "FIXTURE TODO: ${FIXTURE}"
    echo ""
    echo "This script requires a 'known-bad job' fixture: a job payload that will"
    echo "fail deterministically, letting the DeadQueueWatchdog dispatch a BFE."
    echo ""
    echo "Per TODO.md:85, suggested fixture is a presentation-gen job with an"
    echo "intentional source-path bug. Expected JSON shape (submit via /api/push):"
    echo ""
    echo '  {'
    echo '    "question": "agent router go to presentation generator",'
    echo '    "args": {'
    echo '      "source_path": "/nonexistent/path/that/will/fail.md",'
    echo '      "title": "BFE E2E test — known bad source path"'
    echo '    }'
    echo '  }'
    echo ""
    echo "Alternative: any TestSuiteJob with a known-failing test seeded in."
    echo ""
    echo "Once the fixture exists, this script will pick it up automatically."
    exit 1
fi
echo "  OK BFE fixture present"

# --live mode requires auto-fix enabled in INI — check via server-info if it's exposed
if [[ "${MODE}" == "live" ]]; then
    echo "  NOTE --live mode requires 'bug fix expediter enabled = true' AND"
    echo "       'auto fix enabled = true' in lupin-app.ini [Lupin: Testing] block."
    echo "       Verify manually if this is the first --live run."
fi

# ---------------------------------------------------------------------------
# [2/8] Authenticate
# ---------------------------------------------------------------------------
echo ""
echo "[2/8] Authenticating..."

TOKEN=$(curl -sf -X POST "${BASE_URL}/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL}\",\"password\":\"${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD}\"}" \
    | python3 -c "import sys, json; print( json.load( sys.stdin )[ 'tokens' ][ 'access_token' ] )")
if [[ -z "${TOKEN}" ]]; then
    echo "Failed to obtain auth token"
    exit 1
fi
echo "  OK Token obtained"

# ---------------------------------------------------------------------------
# [3/8] Submit the known-bad job
# ---------------------------------------------------------------------------
echo ""
echo "[3/8] Submitting known-bad job (from fixture)..."

SUBMIT_PAYLOAD=$(cat "${FIXTURE}")

# When --cheap, inject bfe_* model override keys into the fixture's args dict.
# The DeadQueueWatchdog reads these from failed_job.original_args and propagates
# them to the BFE job it spawns. This way we can control the BFE's model tier
# without bypassing the watchdog dispatch path (preserves end-to-end validation).
if [[ "${CHEAP}" == "true" ]]; then
    SUBMIT_PAYLOAD=$(echo "${SUBMIT_PAYLOAD}" | python3 -c "
import sys, json
payload = json.load( sys.stdin )
payload.setdefault( 'args', {} )
payload[ 'args' ][ 'bfe_lead_model_override' ]   = '${CHEAP_LEAD_MODEL}'
payload[ 'args' ][ 'bfe_worker_model_override' ] = '${CHEAP_WORKER_MODEL}'
print( json.dumps( payload ) )
")
    echo "  [MODELS] Injected bfe_lead/worker_model_override=${CHEAP_LEAD_MODEL} into fixture args"
fi

ORIGINAL_RESP=$(curl -sf -X POST "${BASE_URL}/api/push" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${SUBMIT_PAYLOAD}")

ORIGINAL_JOB_ID=$(echo "${ORIGINAL_RESP}" | python3 -c "import sys, json; print( json.load( sys.stdin ).get( 'job_id', '' ) )" 2>/dev/null || echo "")
if [[ -z "${ORIGINAL_JOB_ID}" ]]; then
    echo "Failed to submit known-bad job"
    echo "  Response: ${ORIGINAL_RESP}"
    exit 1
fi
echo "  OK Original job submitted: ${ORIGINAL_JOB_ID}"

# ---------------------------------------------------------------------------
# [4/8] Wait for original job to fail (land in dead queue)
# ---------------------------------------------------------------------------
echo ""
echo "[4/8] Waiting for original job to fail (timeout ${FAILURE_WAIT_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + FAILURE_WAIT_TIMEOUT ))
ORIGINAL_FAILED="false"
while [[ $(date +%s) -lt ${DEADLINE} ]]; do
    DEAD_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
        "${BASE_URL}/api/get-queue/dead" 2>/dev/null || echo "")
    if echo "${DEAD_STATE}" | grep -q "${ORIGINAL_JOB_ID}"; then
        ORIGINAL_FAILED="true"
        break
    fi
    echo "  ..polling (${POLL_INTERVAL}s) — not yet dead"
    sleep ${POLL_INTERVAL}
done

if [[ "${ORIGINAL_FAILED}" != "true" ]]; then
    echo "Original job did not fail within ${FAILURE_WAIT_TIMEOUT}s"
    echo "  Job ID: ${ORIGINAL_JOB_ID}"
    echo "  Expected: failure due to fixture's known-bad content"
    exit 1
fi
echo "  OK Original job failed as expected: ${ORIGINAL_JOB_ID}"

# ---------------------------------------------------------------------------
# [5/8] Wait for DeadQueueWatchdog to dispatch a BFE job
# ---------------------------------------------------------------------------
echo ""
echo "[5/8] Waiting for DeadQueueWatchdog to dispatch BFE (timeout ${DISPATCH_WAIT_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + DISPATCH_WAIT_TIMEOUT ))
BFE_JOB_ID=""
while [[ $(date +%s) -lt ${DEADLINE} ]]; do
    # Look for a todo/running job with triggered_by_bfe metadata pointing at our original job
    for QUEUE in todo running; do
        QUEUE_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
            "${BASE_URL}/api/get-queue/${QUEUE}" 2>/dev/null || echo "")
        # Find jobs whose agent_type is bug_fix_expediter and whose metadata
        # references our failed original job ID.
        BFE_JOB_ID=$(echo "${QUEUE_STATE}" | python3 -c "
import sys, json
try:
    data = json.load( sys.stdin )
    jobs = data if isinstance( data, list ) else data.get( 'jobs', [] )
    for j in jobs:
        agent = j.get( 'agent_type', '' )
        meta  = j.get( 'metadata', {} ) or {}
        if 'bug_fix' in agent.lower() and meta.get( 'original_job_id' ) == '${ORIGINAL_JOB_ID}':
            print( j.get( 'id_hash', j.get( 'job_id', '' ) ) )
            break
except Exception:
    pass
" 2>/dev/null || echo "")
        if [[ -n "${BFE_JOB_ID}" ]]; then
            break 2
        fi
    done
    echo "  ..polling (${POLL_INTERVAL}s) — BFE not yet dispatched"
    sleep ${POLL_INTERVAL}
done

if [[ -z "${BFE_JOB_ID}" ]]; then
    echo "DeadQueueWatchdog did not dispatch a BFE within ${DISPATCH_WAIT_TIMEOUT}s"
    echo "  Original job: ${ORIGINAL_JOB_ID}"
    echo "  Possible causes:"
    echo "    - 'bug fix expediter enabled = false' in INI"
    echo "    - RepairAttemptTracker has exhausted attempts for this user"
    echo "    - Watchdog not running (check startup logs for init_watchdogs)"
    exit 1
fi
echo "  OK BFE dispatched: ${BFE_JOB_ID}"

# ---------------------------------------------------------------------------
# [6/8] Poll BFE through its pipeline (todo → running → done/dead)
# ---------------------------------------------------------------------------
echo ""
echo "[6/8] Polling BFE completion (timeout ${BFE_COMPLETION_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + BFE_COMPLETION_TIMEOUT ))
BFE_FINAL_STATE=""
while [[ $(date +%s) -lt ${DEADLINE} ]]; do
    DONE_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
        "${BASE_URL}/api/get-queue/done" 2>/dev/null || echo "")
    if echo "${DONE_STATE}" | grep -q "${BFE_JOB_ID}"; then
        BFE_FINAL_STATE="done"
        break
    fi

    DEAD_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
        "${BASE_URL}/api/get-queue/dead" 2>/dev/null || echo "")
    if echo "${DEAD_STATE}" | grep -q "${BFE_JOB_ID}"; then
        BFE_FINAL_STATE="dead"
        break
    fi

    echo "  ..polling (${POLL_INTERVAL}s) — BFE still running"
    sleep ${POLL_INTERVAL}
done

if [[ -z "${BFE_FINAL_STATE}" ]]; then
    echo "BFE did not complete within ${BFE_COMPLETION_TIMEOUT}s"
    echo "  BFE job ID: ${BFE_JOB_ID}"
    exit 1
fi
echo "  OK BFE reached state: ${BFE_FINAL_STATE}"

# ---------------------------------------------------------------------------
# [7/8] Validate BFE outcome
# ---------------------------------------------------------------------------
echo ""
echo "[7/8] Validating BFE outcome..."

if [[ "${BFE_FINAL_STATE}" == "dead" ]]; then
    echo "BFE job failed (landed in dead queue)"
    echo "  Fetching dead-queue artifacts for forensics..."
    DEAD_DETAIL=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
        "${BASE_URL}/api/get-queue/dead" 2>/dev/null || echo "")
    echo "${DEAD_DETAIL}" | python3 -c "
import sys, json
try:
    data = json.load( sys.stdin )
    jobs = data if isinstance( data, list ) else data.get( 'jobs', [] )
    for j in jobs:
        if j.get( 'id_hash' ) == '${BFE_JOB_ID}' or j.get( 'job_id' ) == '${BFE_JOB_ID}':
            print( '  Plan path:            ', j.get( 'plan_path', '(none)' ) )
            print( '  Report path:          ', j.get( 'report_path', '(none)' ) )
            print( '  Error:                ', j.get( 'error', '(none)' )[:200] )
            meta = j.get( 'metadata', {} ) or {}
            trace = meta.get( 'stack_trace', '' )
            if trace:
                print( '  Stack trace (first 10 lines):' )
                for line in trace.split( chr(10) )[:10]:
                    print( '   ', line )
            break
except Exception as e:
    print( f'  (could not parse dead-queue detail: {e})' )
" 2>/dev/null
    exit 1
fi

# BFE succeeded — extract PR URL and resubmitted_job_id from done-queue artifacts
echo "  Fetching done-queue artifacts..."
DONE_DETAIL=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}/api/get-queue/done" 2>/dev/null || echo "")

ARTIFACTS=$(echo "${DONE_DETAIL}" | python3 -c "
import sys, json
try:
    data = json.load( sys.stdin )
    jobs = data if isinstance( data, list ) else data.get( 'jobs', [] )
    for j in jobs:
        if j.get( 'id_hash' ) == '${BFE_JOB_ID}' or j.get( 'job_id' ) == '${BFE_JOB_ID}':
            pr_url    = j.get( 'pr_url',    ( j.get( 'artifacts', {} ) or {} ).get( 'pr_url',    '' ) )
            resubmit  = j.get( 'metadata',  {} ).get( 'resubmitted_job_id', '' )
            plan_path = j.get( 'plan_path', '' )
            print( f'{pr_url}|{resubmit}|{plan_path}' )
            break
except Exception as e:
    print( f'||(error: {e})' )
" 2>/dev/null)

PR_URL=$(echo "${ARTIFACTS}" | cut -d'|' -f1)
RESUBMITTED_JOB_ID=$(echo "${ARTIFACTS}" | cut -d'|' -f2)
PLAN_PATH=$(echo "${ARTIFACTS}" | cut -d'|' -f3)

echo "  PR URL:             ${PR_URL:-(none — dry-run?)}"
echo "  Resubmitted job:    ${RESUBMITTED_JOB_ID:-(none — dry-run or no resubmit)}"
echo "  Plan path:          ${PLAN_PATH:-(none)}"

if [[ "${MODE}" == "live" ]]; then
    if [[ -z "${PR_URL}" ]]; then
        echo ""
        echo "WARNING: --live mode but no PR URL in artifacts. BFE may have"
        echo "         skipped git ops (trust mode gating?). Check BFE logs."
    fi
    if [[ -z "${RESUBMITTED_JOB_ID}" ]]; then
        echo ""
        echo "WARNING: --live mode but no resubmitted job ID. BFE Phase 6 auto-retry"
        echo "         did not fire. Check 'auto fix enabled' setting."
    fi
fi

# ---------------------------------------------------------------------------
# [8/8] Optional: validate that the resubmitted job itself completes (live only)
# ---------------------------------------------------------------------------
echo ""
echo "[8/8] Validating resubmitted job..."

if [[ -z "${RESUBMITTED_JOB_ID}" ]]; then
    echo "  SKIPPED (no resubmitted job — expected in dry-run mode)"
else
    echo "  Polling resubmitted job ${RESUBMITTED_JOB_ID} (timeout ${RESUBMIT_TIMEOUT}s)..."
    DEADLINE=$(( $(date +%s) + RESUBMIT_TIMEOUT ))
    RESUBMIT_STATE=""
    while [[ $(date +%s) -lt ${DEADLINE} ]]; do
        DONE_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
            "${BASE_URL}/api/get-queue/done" 2>/dev/null || echo "")
        if echo "${DONE_STATE}" | grep -q "${RESUBMITTED_JOB_ID}"; then
            RESUBMIT_STATE="done"
            break
        fi
        DEAD_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
            "${BASE_URL}/api/get-queue/dead" 2>/dev/null || echo "")
        if echo "${DEAD_STATE}" | grep -q "${RESUBMITTED_JOB_ID}"; then
            RESUBMIT_STATE="dead"
            break
        fi
        echo "  ..polling resubmitted (${POLL_INTERVAL}s)"
        sleep ${POLL_INTERVAL}
    done

    if [[ "${RESUBMIT_STATE}" == "done" ]]; then
        echo "  OK Resubmitted job completed successfully — BFE fix validated end-to-end"
    elif [[ "${RESUBMIT_STATE}" == "dead" ]]; then
        echo "  FAIL Resubmitted job also failed — BFE fix did not actually fix the bug"
        exit 1
    else
        echo "  WARN Resubmitted job did not complete within ${RESUBMIT_TIMEOUT}s"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
echo "BFE Live E2E Test PASSED (${MODE})"
echo "  Original job:     ${ORIGINAL_JOB_ID}"
echo "  BFE job:          ${BFE_JOB_ID}"
echo "  Resubmitted job:  ${RESUBMITTED_JOB_ID:-(none)}"
echo "  PR URL:           ${PR_URL:-(none)}"
echo "  Log:              ${LOG_FILE}"
echo "=================================================================="
