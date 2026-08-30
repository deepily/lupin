#!/usr/bin/env bash
#
# Purge this tree's bytecode cache SAFELY — the replacement for
# `find src -name '__pycache__' -type d -exec rm -rf {} +`.
#
# 🔴 WHY THE RAW COMMAND IS NO LONGER SAFE (row 866f43ce, 2026-08-30).
# Rick ruled checked-hash invalidation repo-wide, because CPython's default timestamp
# validation (whole-second mtime + size) serves stale bytecode after a same-size edit inside
# one second — and points the wrong way while doing it.
#
# But a pyc written when NO prior pyc exists is TIMESTAMP-based: there is nothing to inherit
# a mode from, and timestamp is CPython's default. So a raw purge deletes every checked-hash
# cache, the next import silently rebuilds them as timestamp, and the tree is back to the
# original defect **with nothing in any output saying so**.
#
# ⇒ THE INSTRUCTION THE FLEET HAS IN ITS FINGERS — purge when you cannot explain a red — IS
#   NOW THE THING THAT RE-OPENS THE HOLE IT USED TO PLUG.
#
# This script exists so the fix is not "remember not to purge". A habit is not a control.
# Purging remains a legitimate and useful move; it just has to be followed by a reconvert,
# so the two are welded into one command that cannot be half-done.
#
# Cost: ~3.5s on this tree — the reconvert is scoped to real Lupin source (~2,400 files),
# not the 29,303-file vendored venv at src/cosa/.venv.
#
# Usage:
#   src/scripts/purge-pycache.sh              # purge + reconvert (what you want)
#   src/scripts/purge-pycache.sh --dry-run    # show what would be removed
#
set -uo pipefail

LUPIN_ROOT="${LUPIN_ROOT:-$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )}"
HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# Same exclusions as the migration: never touch vendored trees. Purging src/cosa/.venv would
# throw away ~29k third-party pycs that nothing here is debugging, and cost minutes to rebuild.
mapfile -t CACHES < <(
    find "$LUPIN_ROOT/src" -name '__pycache__' -type d \
         -not -path '*/.venv/*' -not -path '*/node_modules/*' \
         -not -path '*/site-packages/*' -prune 2>/dev/null
)

if [[ ${#CACHES[@]} -eq 0 ]]; then
    echo "No __pycache__ directories under src/ (excluding vendored trees). Nothing to purge."
    exit 0
fi

if [[ $DRY_RUN -eq 1 ]]; then
    echo "Would remove ${#CACHES[@]} __pycache__ directories under src/:"
    printf '  %s\n' "${CACHES[@]:0:10}"
    [[ ${#CACHES[@]} -gt 10 ]] && echo "  ... and $(( ${#CACHES[@]} - 10 )) more"
    echo
    echo "Then would reconvert to checked-hash. Re-run without --dry-run."
    exit 0
fi

echo "Purging ${#CACHES[@]} __pycache__ directories under src/ (vendored trees excluded)..."
rm -rf "${CACHES[@]}"

echo "Reconverting to checked-hash — WITHOUT THIS STEP THE PURGE SILENTLY REVERTS THE TREE"
echo "to timestamp invalidation, which is the defect row 866f43ce closed."
"$HERE/migrate-pyc-to-checked-hash.sh"
