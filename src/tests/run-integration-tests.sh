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
PROJECT_ROOT="/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box"
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

# Check if port 7999 is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${RED}[ERROR] Port $PORT is already in use!${NC}"
    echo ""
    echo "Please stop the existing server or process using port $PORT:"
    echo "  lsof -Pi :$PORT -sTCP:LISTEN"
    echo "  kill <PID>"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Port $PORT is available${NC}"

# Start FastAPI server with Testing config block
echo -e "${YELLOW}[SERVER] Starting FastAPI server with Testing config block...${NC}"

cd "$PROJECT_ROOT/src"

export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"

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
