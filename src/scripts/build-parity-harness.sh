#!/usr/bin/env bash
# build-parity-harness.sh — esbuild driver for the WS3 component-isolation
# harness bundle (Layout-Parity Oracle, Doc 01 Pillar 2).
#
# Bundles the harness entry (which pulls in the mux sender-card template + the
# canonical dual adapter) to a stable, browser-loadable module the harness page
# (static/html/parity-harness.html) imports. Run this in the preamble of any
# component-isolation browser tier so the bundle is fresh before the test loads
# the page (sibling to build-multiplexer.sh's role for boot.js on full-page tiers).
#
#   bash src/scripts/build-parity-harness.sh           # production-style build
#   bash src/scripts/build-parity-harness.sh --watch   # rebuild on change

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

ENTRY="src/lupin_app/static/js/multiplexer/testkit/parityHarness.ts"
OUTDIR="src/lupin_app/static/dist/multiplexer"
OUTFILE="$OUTDIR/parity-harness.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

if [ ! -x "$ESBUILD" ]; then
  echo "build-parity-harness: esbuild binary not found at $ESBUILD" >&2
  echo "  Run: npm install (from project root)" >&2
  exit 2
fi

if [ ! -f "$ENTRY" ]; then
  echo "build-parity-harness: entry not found: $ENTRY" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

if [ "${1:-}" = "--watch" ]; then
  echo "build-parity-harness: dev mode (--watch=forever); rebuilding on changes to $ENTRY ..."
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

echo "build-parity-harness: production build → $OUTFILE"
"$ESBUILD" \
  "$ENTRY" \
  --bundle \
  --format=esm \
  --target=es2022 \
  --platform=browser \
  --sourcemap \
  --outfile="$OUTFILE" \
  --log-level=warning

SIZE="$( stat -c%s "$OUTFILE" )"
echo "build-parity-harness: ✓ $OUTFILE  (${SIZE} bytes)"
