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

# TWO harness bundles, deliberately separate. The sender-card harness and the
# inner-accordion harness own different roots and different Tier-1 entries, so a
# failure names the surface that broke; bundling them together would undo that.
ENTRY="src/lupin_app/static/js/multiplexer/testkit/parityHarness.ts"
ACCORDION_ENTRY="src/lupin_app/static/js/multiplexer/testkit/accordionHarness.ts"
OUTDIR="src/lupin_app/static/dist/multiplexer"
OUTFILE="$OUTDIR/parity-harness.js"
ACCORDION_OUTFILE="$OUTDIR/accordion-harness.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

if [ ! -x "$ESBUILD" ]; then
  echo "build-parity-harness: esbuild binary not found at $ESBUILD" >&2
  echo "  Run: npm install (from project root)" >&2
  exit 2
fi

for e in "$ENTRY" "$ACCORDION_ENTRY"; do
  if [ ! -f "$e" ]; then
    echo "build-parity-harness: entry not found: $e" >&2
    exit 2
  fi
done

mkdir -p "$OUTDIR"

# --watch execs a single long-lived esbuild, so it watches ONE entry. Default is
# the sender-card harness; `--watch accordion` watches the accordion one.
if [ "${1:-}" = "--watch" ]; then
  WATCH_ENTRY="$ENTRY"
  WATCH_OUTFILE="$OUTFILE"
  if [ "${2:-}" = "accordion" ]; then
    WATCH_ENTRY="$ACCORDION_ENTRY"
    WATCH_OUTFILE="$ACCORDION_OUTFILE"
  fi
  echo "build-parity-harness: dev mode (--watch=forever); rebuilding on changes to $WATCH_ENTRY ..."
  exec "$ESBUILD" \
    "$WATCH_ENTRY" \
    --bundle \
    --format=esm \
    --target=es2022 \
    --platform=browser \
    --sourcemap \
    --outfile="$WATCH_OUTFILE" \
    --log-level=info \
    --watch=forever
fi

build_one() {
  local entry="$1" outfile="$2"
  echo "build-parity-harness: production build → $outfile"
  "$ESBUILD" \
    "$entry" \
    --bundle \
    --format=esm \
    --target=es2022 \
    --platform=browser \
    --sourcemap \
    --outfile="$outfile" \
    --log-level=warning
  local size
  size="$( stat -c%s "$outfile" )"
  echo "build-parity-harness: ✓ $outfile  (${size} bytes)"
}

build_one "$ENTRY"           "$OUTFILE"
build_one "$ACCORDION_ENTRY" "$ACCORDION_OUTFILE"
