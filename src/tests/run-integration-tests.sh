#!/bin/bash
#
# Automated Integration Test Runner for Lupin
#
# Hot-swap approach: Instead of starting a separate test server, this script
# swaps the running dev server's config block and database connection to
# [Lupin: Testing] / lupin_db_test, runs pytest, then swaps back.
#
# Features:
# - Requires dev server already running on port 7999
# - Hot-swaps to [Lupin: Testing] config block (lupin_db_test)
# - Runs pytest with pass-through arguments
# - ALWAYS swaps back to [Lupin: Development] on exit (trap handler)
# - Returns pytest exit code for CI/CD
#
# Usage:
#   ./src/tests/run-integration-tests.sh           # Run all tests
#   ./src/tests/run-integration-tests.sh -v        # Verbose output
#   ./src/tests/run-integration-tests.sh -v -s     # Very verbose (show prints)
#   ./src/tests/run-integration-tests.sh test_auth_integration.py  # Specific file
#   ./src/tests/run-integration-tests.sh --bg -v   # Run in background (nohup)
#
# Background mode (--background / --bg):
#   The integration suite can exceed 10 minutes under load (rate limiting,
#   slow DB, suite growth). Claude Code's Bash tool has a 10-minute max
#   timeout. --bg re-execs via nohup so the caller returns immediately.
#   A PID file prevents overlapping runs that corrupt server config state.
#   Session 378 incident: overlapping runners caused 49 ERRORs + 15 FAILEDs.
#

set -e  # Exit on error

# Configuration
PORT=7999
BASE_URL="http://localhost:$PORT"
PROJECT_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"
ORIGINAL_BLOCK=""

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
        # This is our own PID — nohup re-exec case. Proceed normally.
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

# Cleanup function - ALWAYS swap back, even on test failure or Ctrl+C
cleanup() {
    # Remove PID file so future runs aren't blocked
    rm -f "$PID_FILE"

    if [ -n "$ORIGINAL_BLOCK" ]; then
        echo ""
        echo -e "${YELLOW}[CLEANUP] Restoring original config: $ORIGINAL_BLOCK${NC}"
        local encoded_block="${ORIGINAL_BLOCK// /+}"
        python3 -c "
import urllib.request
try:
    urllib.request.urlopen( '${BASE_URL}/api/init?config_block_id=${encoded_block}' )
    print( 'Config restored to ${ORIGINAL_BLOCK}' )
except Exception as e:
    print( f'WARNING: Failed to restore config: {e}' )
" 2>/dev/null || true
        echo -e "${GREEN}[CLEANUP] Server restored${NC}"
    fi
}

# Register cleanup handler
trap cleanup EXIT INT TERM

# Print banner
echo "================================================================"
echo "  Lupin Integration Test Runner (Hot-Swap Mode)"
echo "================================================================"
echo ""
echo "These tests will:"
echo "  • Hot-swap the running dev server to [Lupin: Testing] config"
echo "  • Use lupin_db_test database for complete isolation"
echo "  • Swap back to [Lupin: Development] when done"
echo ""
echo "================================================================"
echo ""

# Ensure PostgreSQL test database is ready (works from host or inside container)
if ! python3 "$PROJECT_ROOT/src/tests/preflight_test_db.py"; then
    echo ""
    echo -e "${RED}[ERROR] PostgreSQL test database pre-flight failed${NC}"
    echo -e "${RED}        If Postgres is stopped, start it from the host:${NC}"
    echo -e "${RED}          $PROJECT_ROOT/src/scripts/run-postgresql-dev.sh${NC}"
    echo ""
    exit 1
fi

echo ""

# Check that dev server IS running (via health endpoint, not lsof — works with Docker too)
echo -e "${YELLOW}[SERVER] Checking dev server on port $PORT...${NC}"

SERVER_HEALTHY=$(python3 -c "
import urllib.request
try:
    urllib.request.urlopen( '${BASE_URL}/health', timeout=3 )
    print( 'yes' )
except Exception:
    print( 'no' )
" 2>/dev/null)

if [ "$SERVER_HEALTHY" != "yes" ]; then
    echo ""
    echo "========================================================================"
    echo -e "${RED}  ERROR: Development Server Not Running${NC}"
    echo "========================================================================"
    echo ""
    echo "Integration tests require the development server running on port $PORT."
    echo ""
    echo "Start the server first:"
    echo -e "  ${GREEN}./src/scripts/run-fastapi-lupin.sh${NC}"
    echo ""
    echo "Then re-run:"
    echo -e "  ${GREEN}./src/tests/run-integration-tests.sh -v${NC}"
    echo ""
    echo "========================================================================"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Dev server is running on port $PORT${NC}"

# Record original config block
echo -e "${YELLOW}[CONFIG] Querying current server state...${NC}"

ORIGINAL_BLOCK=$(python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen( '${BASE_URL}/api/server-info', timeout=5 )
    info = json.loads( resp.read() )
    print( info.get( 'config_block_id', '' ) )
except Exception as e:
    print( '' )
" 2>/dev/null)

if [ -z "$ORIGINAL_BLOCK" ]; then
    echo -e "${RED}[ERROR] Cannot query /api/server-info — is the server running?${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Current config: $ORIGINAL_BLOCK${NC}"

# Hot-swap to Testing config
echo -e "${YELLOW}[CONFIG] Swapping to [Lupin: Testing] config block...${NC}"

SWAP_RESULT=$(python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen( '${BASE_URL}/api/init?config_block_id=Lupin:+Testing', timeout=10 )
    info = json.loads( resp.read() )
    print( info.get( 'status', 'error' ) )
    print( info.get( 'database_url', 'unknown' ) )
    print( info.get( 'config_block_id', 'unknown' ) )
except Exception as e:
    print( 'error' )
    print( str( e ) )
    print( '' )
" 2>/dev/null)

SWAP_STATUS=$(echo "$SWAP_RESULT" | head -1)
SWAP_DB_URL=$(echo "$SWAP_RESULT" | sed -n '2p')
SWAP_BLOCK=$(echo "$SWAP_RESULT" | tail -1)

if [ "$SWAP_STATUS" != "success" ]; then
    echo -e "${RED}[ERROR] Hot-swap failed: $SWAP_DB_URL${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Config block: $SWAP_BLOCK${NC}"
echo -e "${GREEN}✓ Database: $SWAP_DB_URL${NC}"

# Verify swap via /api/server-info
VERIFY_DB=$(python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen( '${BASE_URL}/api/server-info', timeout=5 )
    info = json.loads( resp.read() )
    print( info.get( 'database_url', '' ) )
except Exception:
    print( '' )
" 2>/dev/null)

if echo "$VERIFY_DB" | grep -q "lupin_db_test"; then
    echo -e "${GREEN}✓ Verified: database is lupin_db_test${NC}"
else
    echo -e "${RED}[ERROR] Verification failed — database is NOT lupin_db_test${NC}"
    echo -e "${RED}  Got: $VERIFY_DB${NC}"
    exit 1
fi

echo ""

# Set environment for pytest conftest.py
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
export LUPIN_ENV="testing"

# Run pytest with all arguments passed through
echo "================================================================"
echo "  Running Integration Tests"
echo "================================================================"
echo ""

cd "$PROJECT_ROOT"

# Run pytest and capture exit code
set +e  # Don't exit on pytest failure
"$PROJECT_ROOT/src/cosa/.venv/bin/pytest" src/tests/integration/ "${REMAINING_ARGS[@]}"
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

# Cleanup happens automatically via trap (swaps back to original config)
exit $PYTEST_EXIT_CODE
