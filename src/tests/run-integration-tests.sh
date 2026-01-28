#!/bin/bash
#
# Automated Integration Test Runner for Lupin
#
# Features:
# - Checks if port 7999 is available
# - Starts FastAPI server with Testing config block
# - Waits for server health check
# - Runs pytest with pass-through arguments
# - Automatic server cleanup on exit
# - Returns pytest exit code for CI/CD
#
# Usage:
#   ./src/tests/run-integration-tests.sh           # Run all tests
#   ./src/tests/run-integration-tests.sh -v        # Verbose output
#   ./src/tests/run-integration-tests.sh -v -s     # Very verbose (show prints)
#   ./src/tests/run-integration-tests.sh test_auth_integration.py  # Specific file
#

set -e  # Exit on error

# Configuration
PORT=7999
PROJECT_ROOT="${LUPIN_ROOT:-/mnt/DATA01/include/www.deepily.ai/projects/lupin}"
SERVER_PID=""
MAX_WAIT=30  # Maximum seconds to wait for server startup

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Cleanup function - runs on EXIT/INT/TERM
cleanup() {
    if [ -n "$SERVER_PID" ]; then
        echo ""
        echo -e "${YELLOW}[CLEANUP] Stopping test server (PID: $SERVER_PID)...${NC}"
        kill $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
        echo -e "${GREEN}[CLEANUP] Server stopped${NC}"
    fi
}

# Register cleanup handler
trap cleanup EXIT INT TERM

# Print banner
echo "================================================================"
echo "  Lupin Integration Test Runner"
echo "================================================================"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: This script requires the development server to be stopped!${NC}"
echo ""
echo "These tests will:"
echo "  • Start their own test server on port $PORT"
echo "  • Use [Lupin: Testing] config block (test database)"
echo "  • Run in complete isolation from production"
echo ""
echo "If you see authentication or 401 errors:"
echo "  → Your dev server is probably still running"
echo "  → Stop it first: kill \$(lsof -ti:$PORT)"
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

# Check if port 7999 is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo ""
    echo "========================================================================"
    echo -e "${RED}  ERROR: Development Server Running${NC}"
    echo "========================================================================"
    echo ""
    echo "Port $PORT is already in use (likely the development FastAPI server)."
    echo ""
    echo -e "${YELLOW}IMPORTANT: Integration tests REQUIRE the development server to be stopped.${NC}"
    echo ""
    echo "Why this is required:"
    echo "  • Integration tests manage their own FastAPI server instance"
    echo "  • Tests use [Lupin: Testing] config block (test database)"
    echo "  • Development server uses [Lupin: Development] config block (production database)"
    echo "  • Both try to use port $PORT → port conflict"
    echo ""
    echo "To fix this issue:"
    echo ""
    echo "  1. Find the running server:"
    echo -e "     ${GREEN}lsof -Pi :$PORT -sTCP:LISTEN${NC}"
    echo ""
    echo "  2. Stop the development server:"
    echo -e "     ${GREEN}kill <PID>${NC}"
    echo ""
    echo "  3. Re-run the integration tests:"
    echo -e "     ${GREEN}./src/tests/run-integration-tests.sh -v${NC}"
    echo ""
    echo "========================================================================"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Port $PORT is available${NC}"

# Start FastAPI server with Testing config block
echo -e "${YELLOW}[SERVER] Starting FastAPI server with Testing config block...${NC}"

cd "$PROJECT_ROOT/src"

export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
export LUPIN_ENV="testing"

# Start server in background
"$PROJECT_ROOT/src/cosa/.venv/bin/python3" -m fastapi_app.main > /tmp/lupin-test-server.log 2>&1 &
SERVER_PID=$!

echo -e "${GREEN}✓ Server started (PID: $SERVER_PID)${NC}"
echo -e "${YELLOW}[SERVER] Waiting for health check...${NC}"

# Wait for server to be ready
SECONDS_WAITED=0
until curl -s http://localhost:$PORT/health > /dev/null 2>&1; do
    sleep 1
    SECONDS_WAITED=$((SECONDS_WAITED + 1))

    if [ $SECONDS_WAITED -ge $MAX_WAIT ]; then
        echo -e "${RED}[ERROR] Server failed to start within $MAX_WAIT seconds${NC}"
        echo ""
        echo "Server log:"
        tail -20 /tmp/lupin-test-server.log
        exit 1
    fi

    # Check if server process is still running
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo -e "${RED}[ERROR] Server process died during startup${NC}"
        echo ""
        echo "Server log:"
        tail -20 /tmp/lupin-test-server.log
        exit 1
    fi
done

echo -e "${GREEN}✓ Server is healthy (took ${SECONDS_WAITED}s)${NC}"
echo ""

# Run pytest with all arguments passed through
echo "================================================================"
echo "  Running Integration Tests"
echo "================================================================"
echo ""

cd "$PROJECT_ROOT"

# Run pytest and capture exit code
set +e  # Don't exit on pytest failure
"$PROJECT_ROOT/src/cosa/.venv/bin/pytest" src/tests/integration/ "$@"
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

# Cleanup happens automatically via trap
exit $PYTEST_EXIT_CODE
