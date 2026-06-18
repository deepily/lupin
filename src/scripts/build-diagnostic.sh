#!/usr/bin/env bash
# build-diagnostic.sh — esbuild driver for the standalone WebSocket-diagnostic bundle.
#
# ADDITIVE: a NEW standalone entry that does NOT touch the multiplexer build
# (build-multiplexer.sh) or its single-entry config. Mirrors build-nav.sh —
# the reusable "standalone non-mux module" build pattern: a self-contained .ts
# tree (src/lupin_app/static/js/diagnostic/) compiled to its own dist output,
# loadable by the diagnostic page via a plain <script type="module"> tag.
#
# Modes:
#   bash src/scripts/build-diagnostic.sh           # production: minified + sourcemap + content-hashed copy
#   bash src/scripts/build-diagnostic.sh --watch   # dev: rebuilds on .ts changes
#
# Outputs (production):
#   src/lupin_app/static/dist/diagnostic/websocket-diagnostic.js          — stable filename
#   src/lupin_app/static/dist/diagnostic/websocket-diagnostic.js.map      — sourcemap sibling
#   src/lupin_app/static/dist/diagnostic/websocket-diagnostic.<hash>.js   — content-hashed copy (cache-bust target)
#   src/lupin_app/static/dist/diagnostic/manifest.json                    — { "websocket-diagnostic.js": "websocket-diagnostic.<hash>.js" }

set -euo pipefail

# Resolve project root from this script's location (src/scripts/build-diagnostic.sh → ../..).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

ENTRY="src/lupin_app/static/js/diagnostic/boot.ts"
OUTDIR="src/lupin_app/static/dist/diagnostic"
OUTFILE="$OUTDIR/websocket-diagnostic.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

if [ ! -x "$ESBUILD" ]; then
  echo "build-diagnostic: esbuild binary not found at $ESBUILD" >&2
  echo "  Run: npm install (from project root)" >&2
  exit 2
fi

if [ ! -f "$ENTRY" ]; then
  echo "build-diagnostic: entry not found: $ENTRY" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

WATCH_FLAG="${1:-}"
if [ "$WATCH_FLAG" = "--watch" ]; then
  echo "build-diagnostic: dev mode (--watch=forever); rebuilding on changes to $ENTRY ..."
  exec "$ESBUILD" \
    "$ENTRY" \
    --bundle \
    --format=esm \
    --target=es2022 \
    --platform=browser \
    --sourcemap \
    --outfile="$OUTFILE" \
    --log-level=info \
    --watch=forever
fi

echo "build-diagnostic: production build → $OUTFILE"
"$ESBUILD" \
  "$ENTRY" \
  --bundle \
  --format=esm \
  --target=es2022 \
  --platform=browser \
  --minify \
  --keep-names \
  --sourcemap \
  --outfile="$OUTFILE" \
  --log-level=warning

# Compute a short content hash of the bundled output and emit a hashed copy + manifest.
HASH="$( sha256sum "$OUTFILE" | awk '{print substr($1, 1, 12)}' )"
HASHED_NAME="websocket-diagnostic.${HASH}.js"
HASHED_PATH="$OUTDIR/$HASHED_NAME"

cp "$OUTFILE" "$HASHED_PATH"

cat > "$OUTDIR/manifest.json" <<EOF
{
  "websocket-diagnostic.js" : "${HASHED_NAME}",
  "hash"                    : "${HASH}",
  "built"                   : "$( date -u +%Y-%m-%dT%H:%M:%SZ )"
}
EOF

SIZE="$( stat -c%s "$OUTFILE" )"
echo "build-diagnostic: ✓ stable    $OUTFILE  (${SIZE} bytes)"
echo "build-diagnostic: ✓ hashed    $HASHED_PATH"
echo "build-diagnostic: ✓ manifest  $OUTDIR/manifest.json"
