#!/usr/bin/env bash
# build-multiplexer.sh — esbuild driver for the multiplexer notifications UI (Phase 1 scaffolding).
#
# Modes:
#   bash src/scripts/build-multiplexer.sh           # production: minified + sourcemap + content-hashed copy
#   bash src/scripts/build-multiplexer.sh --watch   # dev: rebuilds on .ts changes
#
# Outputs (production):
#   src/fastapi_app/static/dist/multiplexer/boot.js          — stable filename, loaded by multiplexer.html
#   src/fastapi_app/static/dist/multiplexer/boot.js.map      — sourcemap sibling
#   src/fastapi_app/static/dist/multiplexer/boot.<hash>.js   — content-hashed copy (CDN cache-bust target)
#   src/fastapi_app/static/dist/multiplexer/manifest.json    — { "boot.js": "boot.<hash>.js" }

set -euo pipefail

# Resolve project root from this script's location (src/scripts/build-multiplexer.sh → ../..).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

ENTRY="src/fastapi_app/static/js/multiplexer/boot.ts"
OUTDIR="src/fastapi_app/static/dist/multiplexer"
OUTFILE="$OUTDIR/boot.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

if [ ! -x "$ESBUILD" ]; then
  echo "build-multiplexer: esbuild binary not found at $ESBUILD" >&2
  echo "  Run: npm install (from project root)" >&2
  exit 2
fi

if [ ! -f "$ENTRY" ]; then
  echo "build-multiplexer: entry not found: $ENTRY" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

WATCH_FLAG=""
if [ "${1:-}" = "--watch" ]; then
  WATCH_FLAG="--watch"
  echo "build-multiplexer: dev mode (--watch=forever); rebuilding on changes to $ENTRY ..."
  # --watch=forever keeps the watcher alive even when stdin is closed (subprocess /
  # background invocation). Plain --watch exits on stdin close, which is the wrong
  # default for a build driver that gets backgrounded by tooling.
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

echo "build-multiplexer: production build → $OUTFILE"
"$ESBUILD" \
  "$ENTRY" \
  --bundle \
  --format=esm \
  --target=es2022 \
  --platform=browser \
  --minify \
  --sourcemap \
  --outfile="$OUTFILE" \
  --log-level=warning

# Compute a short content hash of the bundled output and emit a hashed copy + manifest.
HASH="$( sha256sum "$OUTFILE" | awk '{print substr($1, 1, 12)}' )"
HASHED_NAME="boot.${HASH}.js"
HASHED_PATH="$OUTDIR/$HASHED_NAME"

cp "$OUTFILE" "$HASHED_PATH"

cat > "$OUTDIR/manifest.json" <<EOF
{
  "boot.js" : "${HASHED_NAME}",
  "hash"    : "${HASH}",
  "built"   : "$( date -u +%Y-%m-%dT%H:%M:%SZ )"
}
EOF

SIZE="$( stat -c%s "$OUTFILE" )"
echo "build-multiplexer: ✓ stable    $OUTFILE  (${SIZE} bytes)"
echo "build-multiplexer: ✓ hashed    $HASHED_PATH"
echo "build-multiplexer: ✓ manifest  $OUTDIR/manifest.json"
