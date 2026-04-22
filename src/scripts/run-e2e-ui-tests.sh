#!/bin/bash
#
# Automated E2E UI Test Runner for Lupin (Playwright)
#
# Dual-container mode: targets the dedicated test server (lupin-rest-test)
# on port 8000. The dev server (lupin-rest-dev, port 7999) is never touched.
# No hot-swap, no config swap, no trap handler needed.
#
# The test server is always running [Lupin: Testing] config with lupin_db_test
# and uvicorn reload=false (stable, no deadlock risk). Code changes are picked
# up on container restart (docker restart lupin-rest-test).
#
# Features:
# - Targets the test server on $LUPIN_TEST_PORT (default: 8000)
# - Verifies the test server is in [Lupin: Testing] mode before running
# - Runs pytest with Playwright against src/tests/e2e_ui/
# - Returns pytest exit code for CI/CD
# - Background mode (--bg) for Claude Code's 10-minute Bash timeout
# - PID file overlap protection (prevents concurrent runs)
#
# Usage:
#   ./src/scripts/run-e2e-ui-tests.sh           # Run all E2E UI tests
#   ./src/scripts/run-e2e-ui-tests.sh -v         # Verbose output
#   ./src/scripts/run-e2e-ui-tests.sh -v -s      # Very verbose (show prints)
#   ./src/scripts/run-e2e-ui-tests.sh -k login   # Run only login tests
#   ./src/scripts/run-e2e-ui-tests.sh --update-snapshots  # Update visual baselines
#   ./src/scripts/run-e2e-ui-tests.sh --bg -v    # Run in background (for Claude Code)
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
VENV_PYTHON="$PROJECT_ROOT/src/cosa/.venv/bin/python3"
if ! "$VENV_PYTHON" --version > /dev/null 2>&1; then VENV_PYTHON="python3"; fi

# --- Background execution support ---
LOG_DIR="/tmp"
PID_FILE="/tmp/e2e-ui-tests.pid"

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
        # This is our own PID — nohup re-exec case. Proceed normally.
        :
    elif kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "ERROR: E2E test run already in progress (PID $EXISTING_PID)"
        echo "Log: $( readlink -f /tmp/e2e-ui-latest.log 2>/dev/null || echo 'unknown' )"
        echo "To force: rm $PID_FILE"
        exit 1
    else
        echo "WARNING: Stale PID file found (PID $EXISTING_PID no longer running). Cleaning up."
        rm -f "$PID_FILE"
    fi
fi

# If --background requested, re-exec via nohup and exit immediately
if [ "$BG_MODE" = true ]; then
    LOG_FILE="$LOG_DIR/e2e-ui-$( date +%Y%m%d-%H%M%S ).log"
    ln -sf "$LOG_FILE" /tmp/e2e-ui-latest.log

    nohup "$0" "${REMAINING_ARGS[@]}" > "$LOG_FILE" 2>&1 &
    BG_PID=$!
    echo "$BG_PID" > "$PID_FILE"

    echo "E2E UI tests running in background"
    echo "  PID:  $BG_PID"
    echo "  Log:  $LOG_FILE"
    echo "  Link: /tmp/e2e-ui-latest.log"
    echo "  Server: $BASE_URL"
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
echo "  Lupin E2E UI Test Runner (Playwright + Dual-Container Mode)"
echo "================================================================"
echo ""
echo "Target server: $BASE_URL"
echo ""
echo "These tests will:"
echo "  • Run Playwright browser tests (Chromium headless)"
echo "  • Target the test server at $BASE_URL"
echo "  • Use lupin_db_test database (test server's fixed config)"
echo "  • Dev server (port 7999) is NOT touched"
echo ""
echo "================================================================"
echo ""

# Ensure PostgreSQL test database is ready
if ! "$VENV_PYTHON" "$PROJECT_ROOT/src/tests/preflight_test_db.py"; then
    echo ""
    echo -e "${RED}[ERROR] PostgreSQL test database pre-flight failed${NC}"
    echo -e "${RED}        Is lupin-postgres running? Try: $PROJECT_ROOT/src/scripts/run-postgresql-dev.sh${NC}"
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
    echo "E2E UI tests require the test server running at $BASE_URL."
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

# Verify the test server is in Testing config (not swapped to dev by accident)
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
    echo ""
    echo "Expected the test server to be configured with [Lupin: Testing]."
    echo "Check LUPIN_CONFIG_MGR_CLI_ARGS in docker-compose.yml for lupin-rest-test."
    exit 1
fi

# Verify database is lupin_db_test
VERIFY_DB=$("$VENV_PYTHON" -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen( '${BASE_URL}/api/server-info', timeout=5 )
    info = json.loads( resp.read() )
    print( info.get( 'database_url', '' ) )
except Exception:
    print( '' )
" 2>/dev/null)

if echo "$VERIFY_DB" | grep -q "lupin_db_test"; then
    echo -e "${GREEN}✓ Database: $VERIFY_DB${NC}"
else
    echo -e "${RED}[ERROR] Test server database is NOT lupin_db_test${NC}"
    echo -e "${RED}  Got: $VERIFY_DB${NC}"
    exit 1
fi

# Verify Playwright is installed
echo -e "${YELLOW}[PLAYWRIGHT] Checking Playwright installation...${NC}"

PLAYWRIGHT_OK=$("$VENV_PYTHON" -c "
try:
    from playwright.sync_api import sync_playwright
    print( 'yes' )
except ImportError:
    print( 'no' )
" 2>/dev/null)

if [ "$PLAYWRIGHT_OK" != "yes" ]; then
    echo ""
    echo -e "${RED}[ERROR] Playwright not installed${NC}"
    echo "Install with:"
    echo -e "  ${GREEN}pip install pytest-playwright>=0.7.0${NC}"
    echo -e "  ${GREEN}playwright install chromium${NC}"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Playwright installed${NC}"

echo ""

# Set environment for pytest conftest.py
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
export LUPIN_ENV="testing"
export LUPIN_TEST_BASE_URL="$BASE_URL"

# Run pytest with Playwright
echo "================================================================"
echo "  Running E2E UI Tests (Playwright)"
echo "================================================================"
echo ""

cd "$PROJECT_ROOT"

# Run pytest and capture exit code
set +e  # Don't exit on pytest failure
$VENV_PYTHON -m pytest src/tests/e2e_ui/ --browser chromium "${REMAINING_ARGS[@]}"
PYTEST_EXIT_CODE=$?
set -e

echo ""
echo "================================================================"

# Report results
if [ $PYTEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All E2E UI tests passed!${NC}"
else
    echo -e "${RED}✗ E2E UI tests failed (exit code: $PYTEST_EXIT_CODE)${NC}"
fi

echo "================================================================"
echo ""

exit $PYTEST_EXIT_CODE
