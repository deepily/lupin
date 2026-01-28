#!/bin/bash
#
# Install CoSA Voice MCP Server for Claude Code
#
# This script:
#   1. Verifies LUPIN_ROOT is set
#   2. Verifies the MCP server file exists
#   3. Tests the MCP server can start
#   4. Adds the MCP server to Claude Code
#
# Usage:
#   ./src/scripts/install-mcp-server.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "  CoSA Voice MCP Server Installation"
echo "======================================"
echo ""

# Step 1: Check LUPIN_ROOT
echo -n "Checking LUPIN_ROOT... "
if [ -z "$LUPIN_ROOT" ]; then
    echo -e "${RED}NOT SET${NC}"
    echo ""
    echo "Error: LUPIN_ROOT environment variable is not set."
    echo ""
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  export LUPIN_ROOT=\"/path/to/lupin\""
    echo ""
    exit 1
fi
echo -e "${GREEN}$LUPIN_ROOT${NC}"

# Step 2: Check MCP server file exists
MCP_SERVER="$LUPIN_ROOT/src/lupin_mcp/cosa_voice_mcp.py"
echo -n "Checking MCP server file... "
if [ ! -f "$MCP_SERVER" ]; then
    echo -e "${RED}NOT FOUND${NC}"
    echo ""
    echo "Error: MCP server file not found at:"
    echo "  $MCP_SERVER"
    echo ""
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Step 3: Check Python virtual environment
VENV_PYTHON="$LUPIN_ROOT/src/cosa/.venv/bin/python"
echo -n "Checking Python venv... "
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${RED}NOT FOUND${NC}"
    echo ""
    echo "Error: Python virtual environment not found at:"
    echo "  $LUPIN_ROOT/src/cosa/.venv/"
    echo ""
    echo "Create it with:"
    echo "  cd $LUPIN_ROOT/src/cosa && python3 -m venv .venv"
    echo "  source .venv/bin/activate && pip install -r requirements.txt"
    echo ""
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Step 4: Test MCP server can start
echo -n "Testing MCP server startup... "
export PYTHONPATH="$LUPIN_ROOT/src:$PYTHONPATH"
export MCP_PROJECT="test"
if ! timeout 3 "$VENV_PYTHON" "$MCP_SERVER" >/dev/null 2>&1; then
    # Timeout is expected (server runs until killed), check if it was a real error
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 124 ]; then
        # Timeout - this is expected, server started successfully
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        echo ""
        echo "Error: MCP server failed to start. Run manually to see errors:"
        echo "  export PYTHONPATH=\"$LUPIN_ROOT/src:\$PYTHONPATH\""
        echo "  export MCP_PROJECT=\"test\""
        echo "  $VENV_PYTHON $MCP_SERVER"
        echo ""
        exit 1
    fi
else
    echo -e "${GREEN}OK${NC}"
fi

# Step 5: Add MCP server to Claude Code
echo ""
echo "Adding MCP server to Claude Code..."
echo ""

# Build the claude mcp add command
# Note: We use the venv python and set env vars
# MCP_PROJECT is not needed - server auto-detects from working directory
claude mcp add cosa-voice \
    --transport stdio \
    --env "LUPIN_APP_SERVER_URL=http://localhost:7999" \
    --env "PYTHONPATH=$LUPIN_ROOT/src" \
    -- "$VENV_PYTHON" "$MCP_SERVER"

echo ""
echo -e "${GREEN}======================================"
echo "  Installation Complete!"
echo "======================================${NC}"
echo ""
echo "The cosa-voice MCP server has been added to Claude Code."
echo ""
echo "To verify, run:"
echo "  claude mcp list"
echo ""
echo "To test, start a Claude Code session and use:"
echo "  notify(\"Hello from MCP!\")"
echo ""
echo "Make sure the Lupin server is running:"
echo "  $LUPIN_ROOT/src/scripts/run-fastapi-lupin.sh"
echo ""
