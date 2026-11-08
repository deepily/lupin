#!/usr/bin/env bash
# build-jobs.sh — esbuild driver for the standalone background-jobs page (/app/jobs).
#
# Row efe188bf: one accordion of every background job (design 2026.11.07-background-job-reporting-
# format.md §6, §11.1). A SEPARATE driver, like build-console.sh, because check_bundle_freshness.py
# parses ONE ENTRY= / OUTDIR= / OUTFILE= per driver and reads ONE hash per manifest.
# `npm run build` runs this after build-console.sh, so the Docker builder stage and the freshness
# checker's "Run: npm run build" remedy both cover it.
#
# Modes:
#   bash src/scripts/build-jobs.sh           # production: minified + sourcemap + content-hashed copy
#   bash src/scripts/build-jobs.sh --watch   # dev: rebuilds on .ts changes
#
# Outputs (production):
#   src/lupin_app/static/dist/jobs/jobs.js          — stable filename (fallback)
#   src/lupin_app/static/dist/jobs/jobs.js.map      — sourcemap sibling
#   src/lupin_app/static/dist/jobs/jobs.<hash>.js   — content-hashed copy (cache-bust target)
#   src/lupin_app/static/dist/jobs/manifest.json    — { "jobs.js": "jobs.<hash>.js" }

set -euo pipefail

# Resolve project root from this script's location (src/scripts/build-jobs.sh → ../..).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

ENTRY="src/lupin_app/static/js/multiplexer/jobs/boot.ts"
OUTDIR="src/lupin_app/static/dist/jobs"
OUTFILE="$OUTDIR/jobs.js"

ESBUILD="$PROJECT_ROOT/node_modules/.bin/esbuild"

if [ ! -x "$ESBUILD" ]; then
  echo "build-jobs: esbuild binary not found at $ESBUILD" >&2
  echo "  Run: npm install (from project root)" >&2
  exit 2
fi

if [ ! -f "$ENTRY" ]; then
  echo "build-jobs: entry not found: $ENTRY" >&2
  exit 2
fi

mkdir -p "$OUTDIR"

if [ "${1:-}" = "--watch" ]; then
  echo "build-jobs: dev mode (--watch=forever); rebuilding on changes to $ENTRY ..."
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

echo "build-jobs: production build → $OUTFILE"
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
HASHED_NAME="jobs.${HASH}.js"
HASHED_PATH="$OUTDIR/$HASHED_NAME"

cp "$OUTFILE" "$HASHED_PATH"

cat > "$OUTDIR/manifest.json" <<EOF
{
  "jobs.js"    : "${HASHED_NAME}",
  "hash"       : "${HASH}",
  "built"      : "$( date -u +%Y-%m-%dT%H:%M:%SZ )"
}
EOF

SIZE="$( stat -c%s "$OUTFILE" )"
echo "build-jobs: ✓ stable    $OUTFILE  (${SIZE} bytes)"
echo "build-jobs: ✓ hashed    $HASHED_PATH"
echo "build-jobs: ✓ manifest  $OUTDIR/manifest.json"
