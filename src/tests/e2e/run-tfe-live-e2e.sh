#!/bin/bash
#
# TFE live E2E test driver.
#
# Session 1cfcdf73 (2026-04-10), step 18 of the approved plan. Exercises
# the full TFE pipeline end-to-end against the real Lupin FastAPI server.
#
# MODES:
#   --dry-run   (default): TFE runs with dry_run=True. No real SDK calls,
#                          no real git operations, no real rerun dispatch.
#                          Used during development + CI.
#   --live               : TFE runs with dry_run=False. Real SDK calls,
#                          real git branch + commits + PR (trust level
#                          permitting), real validation rerun. Models default
#                          to INI (production: Opus lead + Sonnet worker).
#                          ~$2-8 per run. Schedule via /schedule-tests skill.
#   --cheap              : Orthogonal to --live / --dry-run. Overrides models
#                          to Sonnet lead + Sonnet worker for cost savings
#                          (~60-75% reduction). Safe for trivially-fixable
#                          fixtures. Combine with --live for cheap real runs
#                          (~$0.50-2). No effect on --dry-run (stubbed).
#
# COMBINATIONS:
#   (no flag)            ≡ --dry-run          : stubbed, $0, model irrelevant
#   --live               : full Opus+Sonnet   : ~$2-8
#   --live --cheap       : Sonnet-only live   : ~$0.50-2
#   --dry-run --cheap    : stubbed, $0        : (cheap flag effectively inert)
#
# PRECONDITIONS:
#   - Lupin FastAPI test server running at $BASE_URL
#     (default: http://localhost:8000 — dual-container test server.
#      Override via LUPIN_TEST_PORT or LUPIN_TEST_BASE_URL for dev server
#      testing: LUPIN_TEST_PORT=7999 ./run-tfe-live-e2e.sh)
#   - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + PASSWORD env vars set
#   - `test fix expediter auto fix enabled = true` in INI (for --live mode)
#     OR manual TFE submission (works in both modes)
#
# ENVIRONMENT:
#   LUPIN_TEST_PORT      - Test server port (default: 8000)
#   LUPIN_TEST_BASE_URL  - Full test server URL (overrides PORT if set)
#
# USAGE:
#   ./src/tests/e2e/run-tfe-live-e2e.sh [--dry-run|--live] [--cheap]
#
# Port refactor:     2026-04-12 Session 85b05d1d (dual-container alignment)
# --cheap flag:      2026-04-12 Session 85b05d1d (Sonnet-only cost savings)

set -e

# Cheap-tier model constants (Sonnet lead + Sonnet worker).
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
            head -50 "$0" | grep -E "^#"
            exit 0
            ;;
        *)
            echo "Unknown flag: $1"
            exit 1
            ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="/tmp/tfe-live-e2e-${TIMESTAMP}.log"
LUPIN_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"

# Target test server (dual-container pattern — matches run-integration-tests.sh
# and run-e2e-ui-tests.sh). Default: port 8000 (lupin-rest-test container).
PORT="${LUPIN_TEST_PORT:-8000}"
BASE_URL="${LUPIN_TEST_BASE_URL:-http://localhost:$PORT}"

echo "=================================================================="
echo "TFE Live E2E Test Driver (${MODE} mode)"
echo "Target: ${BASE_URL}"
echo "Log:    ${LOG_FILE}"
echo "=================================================================="

echo ""
echo "[1/6] Preflight checks..."

if ! curl -sf "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "Lupin FastAPI test server not responding at ${BASE_URL}"
    echo "  Start the test container with: sdlat  (or: docker compose up -d lupin-rest-test)"
    echo "  For dev-server testing instead: LUPIN_TEST_PORT=7999 $0 $@"
    exit 1
fi
echo "  OK Server responding at ${BASE_URL}"

if [[ -z "${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL}" ]]; then
    echo "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL not set"
    exit 1
fi
echo "  OK Test credentials present"

FIXTURE="${LUPIN_ROOT}/src/tests/fixtures/tfe/snapshot_kcluster.json"
if [[ ! -f "${FIXTURE}" ]]; then
    echo "Fixture snapshot missing: ${FIXTURE}"
    exit 1
fi
echo "  OK Fixture snapshot present"

echo ""
echo "[2/6] Staging fixture snapshot..."
IO_SNAPSHOT="io/test-suite/tfe-e2e-${TIMESTAMP}-remediation.json"
mkdir -p "${LUPIN_ROOT}/io/test-suite"
cp "${FIXTURE}" "${LUPIN_ROOT}/${IO_SNAPSHOT}"
echo "  OK Staged at ${IO_SNAPSHOT}"

echo ""
echo "[3/6] Authenticating..."
TOKEN=$(curl -sf -X POST "${BASE_URL}/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL}\",\"password\":\"${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD}\"}" \
    | python3 -c "import sys, json; print( json.load( sys.stdin )[ 'tokens' ][ 'access_token' ] )")
if [[ -z "${TOKEN}" ]]; then
    echo "Failed to obtain auth token"
    exit 1
fi
echo "  OK Token obtained"

echo ""
echo "[4/6] Submitting TFE job..."
DRY_RUN_ARG="false"
if [[ "${MODE}" == "dry-run" ]]; then
    DRY_RUN_ARG="true"
fi

# Cheap-mode overrides (directly on TFE since we're submitting TFE, not a
# failing job routed via watchdog). Emitted as extra keys in the args dict;
# the agentic_job_factory reads them and applies them to the TFE's config.
MODEL_OVERRIDE_JSON=""
if [[ "${CHEAP}" == "true" ]]; then
    MODEL_OVERRIDE_JSON=",
    \"lead_model_override\":   \"${CHEAP_LEAD_MODEL}\",
    \"worker_model_override\": \"${CHEAP_WORKER_MODEL}\""
    echo "  [MODELS] Using ${CHEAP_LEAD_MODEL} (lead) + ${CHEAP_WORKER_MODEL} (worker) [--cheap]"
else
    echo "  [MODELS] Using INI defaults (production: Opus lead + Sonnet worker)"
fi

SUBMIT_PAYLOAD=$(cat <<EOF
{
  "routing_command": "agent router go to test fix expediter",
  "websocket_id": "unattended-tfe-live",
  "question": "TFE E2E live test (dry-run=${DRY_RUN_ARG})",
  "args": {
    "remediation_snapshot_path": "${IO_SNAPSHOT}",
    "source_test_suite_job_id": "ts-e2e-${TIMESTAMP}",
    "original_test_types": "unit,integration",
    "dry_run": "${DRY_RUN_ARG}"${MODEL_OVERRIDE_JSON}
  }
}
EOF
)

SUBMIT_RESP=$(curl -sf -X POST "${BASE_URL}/api/push-agentic" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${SUBMIT_PAYLOAD}")

JOB_ID=$(echo "${SUBMIT_RESP}" | python3 -c "import sys, json; print( json.load( sys.stdin ).get( 'job_id', '' ) )" 2>/dev/null || echo "")
if [[ -z "${JOB_ID}" ]]; then
    echo "Failed to submit TFE job"
    echo "  Response: ${SUBMIT_RESP}"
    exit 1
fi
echo "  OK TFE job submitted: ${JOB_ID}"

echo ""
echo "[5/6] Polling for completion (timeout 600s)..."
DEADLINE=$(( $(date +%s) + 600 ))
POLL_INTERVAL=5
FINAL_STATE=""
while [[ $(date +%s) -lt ${DEADLINE} ]]; do
    QUEUE_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
        "${BASE_URL}/api/get-queue/done" 2>/dev/null || echo "")

    if echo "${QUEUE_STATE}" | grep -q "${JOB_ID}"; then
        FINAL_STATE="done"
        break
    fi

    DEAD_STATE=$(curl -sf -H "Authorization: Bearer ${TOKEN}" \
        "${BASE_URL}/api/get-queue/dead" 2>/dev/null || echo "")
    if echo "${DEAD_STATE}" | grep -q "${JOB_ID}"; then
        FINAL_STATE="dead"
        break
    fi

    echo "  ..polling (${POLL_INTERVAL}s)"
    sleep ${POLL_INTERVAL}
done

if [[ -z "${FINAL_STATE}" ]]; then
    echo "TFE job did not complete within 600s"
    echo "  Job ID: ${JOB_ID}"
    exit 1
fi
echo "  OK TFE job reached state: ${FINAL_STATE}"

echo ""
echo "[6/6] Validating result..."
if [[ "${FINAL_STATE}" == "dead" ]]; then
    echo "TFE job failed (landed in dead queue)"
    exit 1
fi

echo "  OK TFE job completed successfully in ${MODE} mode"

echo ""
echo "=================================================================="
echo "TFE Live E2E Test PASSED (${MODE})"
echo "  Job ID: ${JOB_ID}"
echo "  Log:    ${LOG_FILE}"
echo "=================================================================="
echo ""
echo "Cleaning up fixture snapshot..."
rm -f "${LUPIN_ROOT}/${IO_SNAPSHOT}"
echo "Done."
