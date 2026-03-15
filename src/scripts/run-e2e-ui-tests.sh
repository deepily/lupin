#!/bin/bash
#
# Automated E2E UI Test Runner for Lupin (Playwright)
#
# Hot-swap approach: Reuses the same pattern as run-integration-tests.sh.
# Swaps the running dev server's config block to [Lupin: Testing] / lupin_db_test,
# runs Playwright E2E tests, then swaps back.
#
# Features:
# - Requires dev server already running on port 7999
# - Hot-swaps to [Lupin: Testing] config block (lupin_db_test)
# - Runs pytest with Playwright against src/tests/e2e_ui/
# - ALWAYS swaps back to original config on exit (trap handler)
# - Returns pytest exit code for CI/CD
#
# Usage:
#   ./src/scripts/run-e2e-ui-tests.sh           # Run all E2E UI tests
#   ./src/scripts/run-e2e-ui-tests.sh -v         # Verbose output
#   ./src/scripts/run-e2e-ui-tests.sh -v -s      # Very verbose (show prints)
#   ./src/scripts/run-e2e-ui-tests.sh -k login   # Run only login tests
#   ./src/scripts/run-e2e-ui-tests.sh --update-snapshots  # Update visual baselines
#

set -e  # Exit on error

# Configuration
PORT=7999
BASE_URL="http://localhost:$PORT"
PROJECT_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"
VENV_PYTHON="$PROJECT_ROOT/src/cosa/.venv/bin/python3"
ORIGINAL_BLOCK=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Cleanup function - ALWAYS swap back, even on test failure or Ctrl+C
cleanup() {
    if [ -n "$ORIGINAL_BLOCK" ]; then
        echo ""
        echo -e "${YELLOW}[CLEANUP] Restoring original config: $ORIGINAL_BLOCK${NC}"
        local encoded_block="${ORIGINAL_BLOCK// /+}"
        "$VENV_PYTHON" -c "
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
echo "  Lupin E2E UI Test Runner (Playwright + Hot-Swap Mode)"
echo "================================================================"
echo ""
echo "These tests will:"
echo "  • Hot-swap the running dev server to [Lupin: Testing] config"
echo "  • Use lupin_db_test database for complete isolation"
echo "  • Run Playwright browser tests (Chromium headless)"
echo "  • Swap back to original config when done"
echo ""
echo "================================================================"
echo ""

# Ensure PostgreSQL is running and test database exists
echo -e "${YELLOW}[POSTGRES] Ensuring PostgreSQL is ready...${NC}"

if ! "$PROJECT_ROOT/src/scripts/run-postgresql-dev.sh" --no-follow-logs; then
    echo ""
    echo -e "${RED}[ERROR] Failed to start/verify PostgreSQL${NC}"
    echo ""
    exit 1
fi

echo ""

# Check that dev server IS running (via health endpoint)
echo -e "${YELLOW}[SERVER] Checking dev server on port $PORT...${NC}"

SERVER_HEALTHY=$("$VENV_PYTHON" -c "
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
    echo "E2E UI tests require the development server running on port $PORT."
    echo ""
    echo "Start the server first:"
    echo -e "  ${GREEN}./src/scripts/run-fastapi-lupin.sh${NC}"
    echo ""
    echo "Then re-run:"
    echo -e "  ${GREEN}./src/scripts/run-e2e-ui-tests.sh -v${NC}"
    echo ""
    echo "========================================================================"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Dev server is running on port $PORT${NC}"

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

# Record original config block
echo -e "${YELLOW}[CONFIG] Querying current server state...${NC}"

ORIGINAL_BLOCK=$("$VENV_PYTHON" -c "
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

SWAP_RESULT=$("$VENV_PYTHON" -c "
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

# Run pytest with Playwright
echo "================================================================"
echo "  Running E2E UI Tests (Playwright)"
echo "================================================================"
echo ""

cd "$PROJECT_ROOT"

# Run pytest and capture exit code
set +e  # Don't exit on pytest failure
"$PROJECT_ROOT/src/cosa/.venv/bin/pytest" src/tests/e2e_ui/ --browser chromium "$@"
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

# Cleanup happens automatically via trap (swaps back to original config)
exit $PYTEST_EXIT_CODE
