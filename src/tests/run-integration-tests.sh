#!/bin/bash
#
# Automated Integration Test Runner for Lupin
#
# Dual-container mode: targets the dedicated test server (lupin-rest-test)
# on port 8000. The dev server (lupin-rest-dev, port 7999) is never touched.
# No hot-swap, no config swap, no trap handler needed.
#
# The test server is always running [Lupin: Testing] config with lupin_db_test
# and uvicorn reload=false (stable, no deadlock risk).
#
# Features:
# - Targets the test server on $LUPIN_TEST_PORT (default: 8000)
# - Verifies the test server is in [Lupin: Testing] mode before running
# - Runs pytest with pass-through arguments
# - Returns pytest exit code for CI/CD
# - Background mode (--bg) for Claude Code's 10-minute Bash timeout
# - PID file overlap protection
#
# Usage:
#   ./src/tests/run-integration-tests.sh           # Run all tests
#   ./src/tests/run-integration-tests.sh -v        # Verbose output
#   ./src/tests/run-integration-tests.sh -v -s     # Very verbose (show prints)
#   ./src/tests/run-integration-tests.sh test_auth_integration.py  # Specific file
#   ./src/tests/run-integration-tests.sh --bg -v   # Run in background (nohup)
#
# Environment:
#   LUPIN_TEST_PORT     - Test server port (default: 8000)
#   LUPIN_TEST_BASE_URL - Full test server URL (overrides port if set)
#
# Refactored: 2026-04-12 Session 248e740e (dual-container architecture)
# Original:   Hot-swap model (swapped dev server config, trap handler restored)

set -e  # Exit on error

# Configuration
PORT="${LUPIN_TEST_PORT:-8000}"
BASE_URL="${LUPIN_TEST_BASE_URL:-http://localhost:$PORT}"
PROJECT_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"

# Use venv python on host, fall back to system python in Docker container
# Require an EXPLICIT venv python — never silently degrade to a bare `python3`. The old
# second line here did exactly that, which is the row c98bce3f false-green shape in a
# different spelling: an under-provisioned interpreter under-collects and the reduced
# count gets reported as the whole suite. Shared so it cannot drift again (row fc74c1d4).
source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_python || exit $?

# --- Background execution support ---
LOG_DIR="/tmp"
PID_FILE="/tmp/integration-tests.pid"

# Parse --background / --bg flag (strip it from args passed to pytest)
BG_MODE=false
REMAINING_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --background|--bg)
            BG_MODE=true
            ;;
        *)
            REMAINING_ARGS+=( "$arg" )
            ;;
    esac
done

# Prevent overlapping runs (regardless of mode)
if [ -f "$PID_FILE" ]; then
    EXISTING_PID=$( cat "$PID_FILE" )
    if [ "$EXISTING_PID" = "$$" ]; then
        :
    elif kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "ERROR: Integration test run already in progress (PID $EXISTING_PID)"
        echo "Monitor: tail -f /tmp/integration-latest.log"
        echo "Status:  kill -0 $EXISTING_PID 2>/dev/null && echo running || echo done"
        echo "To force: rm $PID_FILE"
        exit 1
    else
        echo "WARNING: Stale PID file found (PID $EXISTING_PID no longer running). Cleaning up."
        rm -f "$PID_FILE"
    fi
fi

# If --background requested, re-exec via nohup and exit immediately
if [ "$BG_MODE" = true ]; then
    LOG_FILE="$LOG_DIR/integration-$( date +%Y%m%d-%H%M%S ).log"
    ln -sf "$LOG_FILE" /tmp/integration-latest.log

    nohup "$0" "${REMAINING_ARGS[@]}" > "$LOG_FILE" 2>&1 &
    BG_PID=$!
    echo "$BG_PID" > "$PID_FILE"

    echo "Integration tests running in background (PID $BG_PID)"
    echo "  Log:     $LOG_FILE"
    echo "  Link:    /tmp/integration-latest.log"
    echo "  Server:  $BASE_URL"
    echo ""
    echo "Monitor:  tail -f $LOG_FILE"
    echo "Status:   kill -0 $BG_PID 2>/dev/null && echo running || echo done"
    echo "Results:  grep -E '(passed|failed|error)' $LOG_FILE"
    exit 0
fi

# Record our PID (for overlap detection in foreground mode too)
echo "$$" > "$PID_FILE"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Cleanup function - just removes PID file (no config swap needed)
cleanup() {
    rm -f "$PID_FILE"
}

# Register cleanup handler
trap cleanup EXIT INT TERM

# Print banner
echo "================================================================"
echo "  Lupin Integration Test Runner (Dual-Container Mode)"
echo "================================================================"
echo ""
echo "Target server: $BASE_URL"
echo ""
echo "These tests will:"
echo "  • Run integration tests against $BASE_URL"
echo "  • Use lupin_db_test database (test server's fixed config)"
echo "  • Dev server (port 7999) is NOT touched"
echo ""
echo "================================================================"
echo ""

# Ensure PostgreSQL test database is ready (works from host or inside container)
if ! "$VENV_PYTHON" "$PROJECT_ROOT/src/tests/preflight_test_db.py"; then
    echo ""
    echo -e "${RED}[ERROR] PostgreSQL test database pre-flight failed${NC}"
    echo -e "${RED}        If Postgres is stopped, start it from the host:${NC}"
    echo -e "${RED}          $PROJECT_ROOT/src/scripts/run-postgresql-dev.sh${NC}"
    echo ""
    exit 1
fi

echo ""

# Check that the test server IS running (via health endpoint)
echo -e "${YELLOW}[SERVER] Checking test server at $BASE_URL ...${NC}"

SERVER_HEALTHY=$("$VENV_PYTHON" -c "
import urllib.request
try:
    urllib.request.urlopen( '${BASE_URL}/health', timeout=5 )
    print( 'yes' )
except Exception:
    print( 'no' )
" 2>/dev/null)

if [ "$SERVER_HEALTHY" != "yes" ]; then
    echo ""
    echo "========================================================================"
    echo -e "${RED}  ERROR: Test Server Not Running${NC}"
    echo "========================================================================"
    echo ""
    echo "Integration tests require the test server running at $BASE_URL."
    echo ""
    echo "Start it with:"
    echo -e "  ${GREEN}sdlat${NC}  (alias for start-docker-lupin.sh --env test)"
    echo ""
    echo "Or via docker compose:"
    echo -e "  ${GREEN}docker compose up -d lupin-rest-test${NC}"
    echo ""
    echo "========================================================================"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Test server is running at $BASE_URL${NC}"

# Verify the test server is in Testing config
echo -e "${YELLOW}[CONFIG] Verifying test server configuration...${NC}"

CONFIG_BLOCK=$("$VENV_PYTHON" -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen( '${BASE_URL}/api/server-info', timeout=5 )
    info = json.loads( resp.read() )
    print( info.get( 'config_block_id', '' ) )
except Exception:
    print( '' )
" 2>/dev/null)

if echo "$CONFIG_BLOCK" | grep -qi "testing"; then
    echo -e "${GREEN}✓ Config block: $CONFIG_BLOCK${NC}"
else
    echo -e "${RED}[ERROR] Test server is NOT in [Lupin: Testing] mode${NC}"
    echo -e "${RED}  Got: $CONFIG_BLOCK${NC}"
    exit 1
fi

echo ""

# Set environment for pytest conftest.py
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
export LUPIN_ENV="testing"
export LUPIN_TEST_BASE_URL="$BASE_URL"
# Host-side seed_test_companions.py default DB_HOST is 'lupin-postgres' (docker-internal DNS).
# Override to localhost so fixtures that re-run the seed from the pytest client process
# (e.g. clean_test_db in conftest.py) can reach the shared Postgres over the bridged port.
export DB_HOST="${DB_HOST:-localhost}"

# Run pytest with all arguments passed through
echo "================================================================"
echo "  Running Integration Tests"
echo "================================================================"
echo ""

cd "$PROJECT_ROOT"

# Run pytest and capture exit code. The wrapper adds one thing only: when the code says
# the suite never RAN (a collection error — exit 4's conftest shape fires no pytest hook
# and writes no junit), it prints the cause instead of leaving a bare traceback. The
# status is re-raised verbatim, so the reporting below is unchanged. Row 73c6819d.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
set +e  # Don't exit on pytest failure
run_pytest_with_diagnosis "$VENV_PYTHON" -m pytest src/tests/integration/ "${REMAINING_ARGS[@]}"
PYTEST_EXIT_CODE=$?
set -e

echo ""
echo "================================================================"

# Report results
if [ $PYTEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
else
    echo -e "${RED}✗ Tests failed (exit code: $PYTEST_EXIT_CODE)${NC}"
fi

echo "================================================================"
echo ""

exit $PYTEST_EXIT_CODE
