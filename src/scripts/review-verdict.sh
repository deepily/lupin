#!/bin/bash
# Print (or check) the review verdict line: tree sha + census counts + Merge|Fix.
#
# Usage: src/scripts/review-verdict.sh --verdict Merge|Fix [--census-log FILE]
#        src/scripts/review-verdict.sh --check "REVIEW-VERDICT sha=... census=...p/...f/...e verdict=..."
# Run it at the sha under review. Exit 0 printed the line; exit 2 refused, with the cause.
set -uo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export LUPIN_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
export PYTHONPATH="$LUPIN_ROOT/src:${PYTHONPATH:-}"
exec python3 -m cosa.utils.review_verdict "$@"
