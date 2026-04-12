#!/bin/bash
#
# TFE Resume E2E driver — validates the session 9056c113 resume stack
# (MCP timeout detection + checkpoint-resume + smart resume-from endpoint +
# voice expeditor handler) against a running Lupin FastAPI server.
#
# Most of the validation is pure-API endpoint exercising (no real voice gate
# timeout required). The full stall-and-resume path is gated behind
# TFE_RESUME_E2E_LIVE=1 since it needs interactive voice-gate timeout control.
#
# MODES:
#   (default): Runs endpoint-validation integration tests only.
#              ~30s, $0, no real SDK calls.
#   --live:    Adds the full stall-and-resume path. Still requires manual INI
#              tuning (`test fix expediter feedback timeout seconds = 5`) and
#              is typically scheduled via the test-suite submit card with
#              monopolize=true for after-hours execution.
#
# PRECONDITIONS:
#   - Lupin FastAPI server running at $LUPIN_TEST_BASE_URL (default: http://localhost:7999)
#   - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + PASSWORD env vars set
#   - CoSA submodule commits landed and server restarted (doc 16 Phases 1+2 live)
#
# USAGE:
#   ./src/tests/e2e/run-tfe-resume-e2e.sh           # endpoint validation
#   ./src/tests/e2e/run-tfe-resume-e2e.sh --live   # full stall-and-resume
#
# Session 9056c113 doc 16 Phase 3.

set -e

MODE="endpoint"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --live)    MODE="live"; shift ;;
        -h|--help)
            head -30 "$0" | grep -E "^#"
            exit 0
            ;;
        *)
            echo "Unknown flag: $1"
            exit 1
            ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="/tmp/tfe-resume-e2e-${TIMESTAMP}.log"
LUPIN_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"
BASE_URL="${LUPIN_TEST_BASE_URL:-http://localhost:7999}"

echo "=================================================================="
echo "TFE Resume E2E Driver (${MODE} mode)"
echo "Target: ${BASE_URL}"
echo "Log:    ${LOG_FILE}"
echo "=================================================================="

echo ""
echo "[1/3] Preflight checks..."

if ! curl -sf "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "Lupin FastAPI server not responding at ${BASE_URL}"
    exit 1
fi
echo "  OK Server responding"

if [[ -z "${LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL}" ]]; then
    echo "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL not set"
    exit 1
fi
echo "  OK Test credentials present"

echo ""
echo "[2/3] Running endpoint validation tests..."

export LUPIN_TEST_BASE_URL="${BASE_URL}"

if [[ "${MODE}" == "live" ]]; then
    export TFE_RESUME_E2E_LIVE=1
    echo "  [LIVE MODE] Full stall-and-resume enabled (requires INI timeout tuning)"
fi

cd "${LUPIN_ROOT}"
PYTHONPATH="${LUPIN_ROOT}/src:${PYTHONPATH:-}" python3 -m pytest \
    src/tests/integration/test_tfe_resume_e2e.py \
    -v --tb=short 2>&1 | tee "${LOG_FILE}"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "[3/3] Summary"
echo "  Log: ${LOG_FILE}"
if [[ ${EXIT_CODE} -eq 0 ]]; then
    echo "  Status: PASSED"
else
    echo "  Status: FAILED (exit ${EXIT_CODE})"
fi

exit ${EXIT_CODE}
