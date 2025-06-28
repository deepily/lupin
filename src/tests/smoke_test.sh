#!/bin/bash
# Smoke test for FastAPI refactoring
# Quick validation that server is running and basic endpoints work

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🚀 FastAPI Refactoring Smoke Test"
echo "=================================="

# Configuration
PORT=7999
BASE_URL="http://localhost:${PORT}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Function to check if server is running
check_server() {
    echo -n "Checking if server is running on port ${PORT}... "
    if curl -s -f "${BASE_URL}/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Server is running${NC}"
        return 0
    else
        echo -e "${RED}❌ Server is not running${NC}"
        return 1
    fi
}

# Function to start server in background
start_server() {
    echo "Starting FastAPI server..."
    cd "$PROJECT_ROOT/src"
    python -m uvicorn fastapi_app.main:app --port ${PORT} > /tmp/fastapi_test.log 2>&1 &
    SERVER_PID=$!
    echo "Server PID: ${SERVER_PID}"
    
    # Wait for server to start
    echo -n "Waiting for server to start"
    for i in {1..10}; do
        if curl -s -f "${BASE_URL}/health" > /dev/null 2>&1; then
            echo -e " ${GREEN}✅${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    
    echo -e " ${RED}❌ Server failed to start${NC}"
    echo "Server logs:"
    tail -20 /tmp/fastapi_test.log
    return 1
}

# Function to test endpoint
test_endpoint() {
    local method=$1
    local endpoint=$2
    local expected_status=$3
    local auth_header=$4
    
    echo -n "Testing ${method} ${endpoint}... "
    
    if [ -n "$auth_header" ]; then
        response=$(curl -s -w "\n%{http_code}" -X ${method} -H "Authorization: Bearer mock_token_test" "${BASE_URL}${endpoint}")
    else
        response=$(curl -s -w "\n%{http_code}" -X ${method} "${BASE_URL}${endpoint}")
    fi
    
    status_code=$(echo "$response" | tail -n1)
    
    if [ "$status_code" == "$expected_status" ]; then
        echo -e "${GREEN}✅ (${status_code})${NC}"
        return 0
    else
        echo -e "${RED}❌ (expected ${expected_status}, got ${status_code})${NC}"
        return 1
    fi
}

# Main test sequence
main() {
    echo "Starting smoke test at $(date)"
    echo ""
    
    # Check if server is already running
    if check_server; then
        echo "Using existing server"
        STARTED_SERVER=false
    else
        echo "Server not running, starting it..."
        if start_server; then
            STARTED_SERVER=true
            trap "echo 'Shutting down server...'; kill $SERVER_PID 2>/dev/null || true" EXIT
        else
            exit 1
        fi
    fi
    
    echo ""
    echo "Running endpoint tests..."
    echo "========================"
    
    # Test system endpoints
    test_endpoint "GET" "/" 200
    test_endpoint "GET" "/health" 200
    test_endpoint "GET" "/api/get-session-id" 200
    test_endpoint "GET" "/api/init" 200
    
    # Test auth endpoint
    test_endpoint "GET" "/api/auth-test" 401  # Without auth
    test_endpoint "GET" "/api/auth-test" 200 "auth"  # With auth
    
    # Test queue endpoints (with auth)
    test_endpoint "GET" "/api/get-queue/todo" 200 "auth"
    test_endpoint "GET" "/api/get-queue/run" 200 "auth"
    test_endpoint "GET" "/api/get-queue/done" 200 "auth"
    test_endpoint "GET" "/api/get-queue/dead" 200 "auth"
    
    echo ""
    echo "Testing WebSocket connectivity..."
    echo "================================="
    
    # Quick WebSocket test using Python
    python3 -c "
import asyncio
import websockets
import json

async def test_ws():
    try:
        uri = 'ws://localhost:${PORT}/ws/test-session'
        async with websockets.connect(uri) as websocket:
            print('✅ WebSocket connection established')
            
            # Send auth
            await websocket.send(json.dumps({'type': 'auth', 'token': 'mock_token_test'}))
            
            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(response)
            
            if data.get('type') == 'auth_success':
                print('✅ WebSocket authentication successful')
            else:
                print('❌ WebSocket authentication failed')
                
    except Exception as e:
        print(f'❌ WebSocket test failed: {e}')

asyncio.run(test_ws())
"
    
    echo ""
    echo "Testing with jq (if available)..."
    echo "================================="
    
    if command -v jq > /dev/null 2>&1; then
        echo "Health check response:"
        curl -s "${BASE_URL}/health" | jq .
        
        echo ""
        echo "Session ID response:"
        curl -s "${BASE_URL}/api/get-session-id" | jq .
    else
        echo "jq not installed, skipping JSON formatting"
    fi
    
    echo ""
    echo "=================================="
    echo -e "${GREEN}✅ Smoke test completed successfully!${NC}"
    echo "=================================="
    
    # Run full test suite if requested
    if [ "$1" == "--full" ]; then
        echo ""
        echo "Running full test suite..."
        echo "========================="
        
        cd "$SCRIPT_DIR"
        
        echo "1. Running endpoint tests..."
        python test_refactoring.py --quick
        
        echo ""
        echo "2. Running WebSocket tests..."
        python test_websockets.py
    fi
}

# Run main function
main "$@"