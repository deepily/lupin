#!/bin/bash
#
# generate-api-docs.sh
#
# Regenerates REST API documentation from the running FastAPI server's OpenAPI spec.
#
# Prerequisites:
#   - FastAPI server running on port 7999 (see: src/scripts/run-fastapi-lupin.sh)
#   - LUPIN_ROOT environment variable set
#
# Outputs:
#   - src/docs/fastapi/api.json  (pretty-printed OpenAPI spec)
#   - src/docs/fastapi/api.md    (full Markdown API documentation)
#
# Usage:
#   ./src/scripts/generate-api-docs.sh              # Fetch from live server and generate
#   ./src/scripts/generate-api-docs.sh --offline     # Regenerate .md from existing api.json

# --- Environment validation ---

if [ -z "$LUPIN_ROOT" ]; then
    echo "ERROR: LUPIN_ROOT environment variable is not set."
    echo "Set it before running:"
    echo "  export LUPIN_ROOT=/path/to/lupin"
    exit 1
fi

DOCS_DIR="$LUPIN_ROOT/src/docs/fastapi"
VENV_PYTHON="$LUPIN_ROOT/src/cosa/.venv/bin/python3"
API2MD="$LUPIN_ROOT/src/cosa/.venv/bin/openapi-to-markdown"
SERVER_URL="http://localhost:7999"
OPENAPI_URL="$SERVER_URL/openapi.json"

# --- Parse arguments ---

OFFLINE=false
if [ "$1" = "--offline" ]; then
    OFFLINE=true
fi

# --- Verify dependencies ---

if [ ! -x "$VENV_PYTHON" ]; then
    echo "ERROR: Python not found at $VENV_PYTHON"
    exit 1
fi

if [ ! -x "$API2MD" ]; then
    echo "ERROR: openapi-to-markdown not found at $API2MD"
    echo "Install with: pip install openapi-to-md"
    exit 1
fi

if [ ! -d "$DOCS_DIR" ]; then
    echo "ERROR: Output directory not found: $DOCS_DIR"
    exit 1
fi

# --- Fetch OpenAPI spec (unless --offline) ---

if [ "$OFFLINE" = false ]; then
    echo "Checking if FastAPI server is running on port 7999..."
    if ! curl -s --max-time 5 "$OPENAPI_URL" > /dev/null 2>&1; then
        echo "ERROR: FastAPI server is not responding on port 7999."
        echo "Start it with: src/scripts/run-fastapi-lupin.sh"
        exit 1
    fi
    echo "Server is running."

    echo "Fetching OpenAPI spec from $OPENAPI_URL..."
    curl -s "$OPENAPI_URL" | "$VENV_PYTHON" -m json.tool > "$DOCS_DIR/api.json"

    if [ $? -ne 0 ] || [ ! -s "$DOCS_DIR/api.json" ]; then
        echo "ERROR: Failed to fetch or format OpenAPI spec."
        exit 1
    fi
    echo "Saved pretty-printed spec to $DOCS_DIR/api.json"
else
    echo "Offline mode: using existing $DOCS_DIR/api.json"
fi

# --- Verify api.json exists ---

if [ ! -f "$DOCS_DIR/api.json" ]; then
    echo "ERROR: $DOCS_DIR/api.json not found. Run without --offline first."
    exit 1
fi

# --- Generate Markdown ---

echo "Generating API documentation..."
"$API2MD" \
    --input_file "$DOCS_DIR/api.json" \
    --output_file "$DOCS_DIR/api.md"

if [ $? -ne 0 ]; then
    echo "ERROR: openapi-to-markdown failed."
    exit 1
fi

# --- Inject timestamp footer ---

TIMESTAMP=$( date "+%Y.%m.%d %H:%M:%S" )
echo "" >> "$DOCS_DIR/api.md"
echo "---" >> "$DOCS_DIR/api.md"
echo "_Auto-generated on ${TIMESTAMP} by \`src/scripts/generate-api-docs.sh\`_" >> "$DOCS_DIR/api.md"

# --- Summary ---

JSON_LINES=$( wc -l < "$DOCS_DIR/api.json" )
MD_LINES=$( wc -l < "$DOCS_DIR/api.md" )

echo ""
echo "Done. Generated:"
echo "  $DOCS_DIR/api.json  ($JSON_LINES lines)"
echo "  $DOCS_DIR/api.md    ($MD_LINES lines)"
echo "  Timestamp: $TIMESTAMP"
