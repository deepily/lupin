#!/usr/bin/env bash
# build-console.sh — esbuild driver for the standalone live-console page (/app/console).
#
# Row 27760534, Rick's ruling 2026-09-28: a seat's live CC console opens in its OWN tab, as its
# own page. That page loads this bundle, NOT the multiplexer's, so it stands alone — no
# multiplexer tab has to be open.
#
# A SEPARATE driver, not a second entry in build-multiplexer.sh, for two reasons measured
# against what reads these scripts:
#   · check_bundle_freshness.py parses ONE ENTRY= / OUTDIR= / OUTFILE= and ONE production
#     `"$ESBUILD" \` block per driver, and reads ONE "hash" per manifest. A second entry in the
#     multiplexer's driver would be invisible to it, or worse, checked against the wrong hash.
#   · the same pattern as build-nav.sh and build-diagnostic.sh: own entry, own dist dir, own
#     content-hashed copy + manifest.
# `npm run build` runs this after build-multiplexer.sh, so the Docker builder stage and the
# freshness checker's "Run: npm run build" remedy both cover it.
#
# Modes:
#   bash src/scripts/build-console.sh           # production: minified + sourcemap + content-hashed copy
#   bash src/scripts/build-console.sh --watch   # dev: rebuilds on .ts changes
#
# Outputs (production):
#   src/lupin_app/static/dist/console/console.js          — stable filename (fallback)
#   src/lupin_app/static/dist/console/console.js.map      — sourcemap sibling
#   src/lupin_app/static/dist/console/console.<hash>.js   — content-hashed copy (cache-bust target)
#   src/lupin_app/static/dist/console/manifest.json       — { "console.js": "console.<hash>.js" }

set -euo pipefail

# Resolve project root from this script's location (src/scripts/build-console.sh → ../..).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

ENTRY="src/lupin_app/static/js/multiplexer/console/boot.ts"
OUTDIR="src/lupin_app/static/dist/console"
OUTFILE="$OUTDIR/console.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

if [ ! -x "$ESBUILD" ]; then
  echo "build-console: esbuild binary not found at $ESBUILD" >&2
  echo "  Run: npm install (from project root)" >&2
  exit 2
fi

if [ ! -f "$ENTRY" ]; then
  echo "build-console: entry not found: $ENTRY" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

if [ "${1:-}" = "--watch" ]; then
  echo "build-console: dev mode (--watch=forever); rebuilding on changes to $ENTRY ..."
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

echo "build-console: production build → $OUTFILE"
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
HASHED_NAME="console.${HASH}.js"
HASHED_PATH="$OUTDIR/$HASHED_NAME"

cp "$OUTFILE" "$HASHED_PATH"

cat > "$OUTDIR/manifest.json" <<EOF
{
  "console.js" : "${HASHED_NAME}",
  "hash"       : "${HASH}",
  "built"      : "$( date -u +%Y-%m-%dT%H:%M:%SZ )"
}
EOF

SIZE="$( stat -c%s "$OUTFILE" )"
echo "build-console: ✓ stable    $OUTFILE  (${SIZE} bytes)"
echo "build-console: ✓ hashed    $HASHED_PATH"
echo "build-console: ✓ manifest  $OUTDIR/manifest.json"
