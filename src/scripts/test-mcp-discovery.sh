#!/bin/bash
#
# Test MCP Server Discovery and Tool Naming
#
# This script:
#   1. Lists registered MCP servers
#   2. Checks if cosa-voice is registered
#   3. Shows available tools (if possible)
#
# Usage:
#   ./src/scripts/test-mcp-discovery.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo "======================================"
echo "  MCP Server Discovery Test"
echo "======================================"
echo ""

# Step 1: List all MCP servers
echo -e "${CYAN}Registered MCP Servers:${NC}"
echo "------------------------"
claude mcp list 2>/dev/null || echo "No MCP servers registered or claude command not found"
echo ""

# Step 2: Check if cosa-voice is registered
echo -n "Checking for cosa-voice... "
if claude mcp list 2>/dev/null | grep -q "cosa-voice"; then
    echo -e "${GREEN}FOUND${NC}"
else
    echo -e "${YELLOW}NOT FOUND${NC}"
    echo ""
    echo "The cosa-voice MCP server is not registered."
    echo "Run the installation script:"
    echo "  ./src/scripts/install-mcp-server.sh"
    echo ""
    exit 1
fi

# Step 3: Test server startup
echo ""
echo -e "${CYAN}Testing MCP Server Startup:${NC}"
echo "---------------------------"

if [ -z "$LUPIN_ROOT" ]; then
    echo -e "${YELLOW}Warning: LUPIN_ROOT not set, using current directory${NC}"
    LUPIN_ROOT="$(pwd)"
fi

MCP_SERVER="$LUPIN_ROOT/src/lupin_mcp/cosa_voice_mcp.py"
VENV_PYTHON="$LUPIN_ROOT/.venv/bin/python"

if [ -f "$VENV_PYTHON" ] && [ -f "$MCP_SERVER" ]; then
    export PYTHONPATH="$LUPIN_ROOT/src:$PYTHONPATH"
    export MCP_PROJECT="test"

    echo "Starting MCP server (will timeout after 2 seconds)..."
    echo ""

    # Capture startup output
    timeout 2 "$VENV_PYTHON" "$MCP_SERVER" 2>&1 | head -20 || true

    echo ""
    echo -e "${GREEN}Server startup test complete${NC}"
else
    echo -e "${YELLOW}Could not test server startup - files not found${NC}"
fi

echo ""
echo "======================================"
echo "  Expected Tool Names in Claude Code"
echo "======================================"
echo ""
echo "When using the cosa-voice MCP server, tools are available as:"
echo ""
echo "  mcp__cosa-voice__converse()"
echo "  mcp__cosa-voice__notify()"
echo "  mcp__cosa-voice__ask_yes_no()"
echo "  mcp__cosa-voice__get_session_info()"
echo ""
echo "Or with the shorthand (if no conflicts):"
echo ""
echo "  converse()"
echo "  notify()"
echo "  ask_yes_no()"
echo "  get_session_info()"
echo ""
