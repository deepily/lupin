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

# 🔴 DERIVED UNCONDITIONALLY — $LUPIN_ROOT IS NOT CONSULTED. This script is shipped INSIDE the
# tree it cleans, so the environment can only DISAGREE with it, never inform it. The old line
# read "${LUPIN_ROOT:-<this same expression>}": the shell default was already right, and a SET
# variable simply won over it. ("Default" not "fallback" — the only thing in this script now
# called a fallback is the interpreter one further down, which it deliberately does NOT do.) Every seat's shell exports LUPIN_ROOT pointing at the MAIN
# checkout, so running this from a worktree purged /…/lupin, printed its success banner, and
# left the worktree exactly as poisoned as it found it — two harms in one command, and the
# clobbered tree belongs to somebody else. Found and remedied by Pocholo 📣, 2026-08-30 ~17:52.
#
# ⚠️ SO THE TARGET CANNOT BE STEERED, AND THE OLD STOPGAP IS NOW A NO-OP. The remedy that
# circulated while this was broken —
#     LUPIN_ROOT="$PWD" src/scripts/purge-pycache.sh
# — still gives the right answer, but for the wrong reason: the prefix does nothing at all now,
# and what makes it correct is that you were standing in the tree whose copy you ran. Harmless
# to keep typing; misleading to keep believing. The one way to aim this script is to run the
# copy that lives in the tree you mean.
LUPIN_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DRY_RUN=0

usage() {
    cat <<'USAGE'
Usage: purge-pycache.sh [--dry-run]

  --dry-run    list what would be removed; change nothing
  -h, --help   this message

Takes no positional arguments. Every argument is honoured or refused — never
silently discarded, because the silent path here is a REAL purge: a mistyped
--dry-run used to preview nothing and delete everything.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run )   DRY_RUN=1 ;;
        -h|--help )   usage; exit 0 ;;
        * )           echo "ERROR: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

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

# PREFLIGHT THE RECONVERT BEFORE DESTROYING ANYTHING. This script's whole promise is that
# purge and reconvert "cannot be half-done" — but the reconvert needs an interpreter, and 35 of
# this repo's 80 worktrees have no .venv/bin/python. There, the old order purged, THEN failed,
# and left the tree timestamp-based: exactly the defect row 866f43ce closed, reported at the
# moment it was already too late to decline. Checking first makes the weld real.
#
# Resolution is deliberately identical to migrate-pyc-to-checked-hash.sh:71 — if that line
# changes, this one must change with it, and test_purge_pycache_args.py fails if they diverge.
PYTHON="${PYTHON:-$LUPIN_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: no interpreter at $PYTHON (set PYTHON=... or build the venv)" >&2
    echo "Refusing to purge: the reconvert would fail and leave this tree on timestamp" >&2
    echo "invalidation. ${#CACHES[@]} __pycache__ directories left untouched." >&2
    echo "" >&2
    echo "Two ways forward, both supported:" >&2
    echo "  1. Name an interpreter for this one run:" >&2
    echo "       PYTHON=\"\$( git rev-parse --git-common-dir )/../.venv/bin/python\" $0" >&2
    echo "  2. Give this worktree a venv once — the whole unit tier benefits, not just this:" >&2
    echo "       $HERE/link-worktree-venv.sh" >&2
    echo "" >&2
    echo "What it will NOT do is reach for another tree's interpreter on its own. An override" >&2
    echo "you type is a decision; one this script makes for you is invisible, and invisible" >&2
    echo "cross-tree reach is the defect the root resolution above was just repaired for." >&2
    exit 2
fi

echo "Purging ${#CACHES[@]} __pycache__ directories under src/ (vendored trees excluded)..."
rm -rf "${CACHES[@]}"

echo "Reconverting to checked-hash — WITHOUT THIS STEP THE PURGE SILENTLY REVERTS THE TREE"
echo "to timestamp invalidation, which is the defect row 866f43ce closed."
"$HERE/migrate-pyc-to-checked-hash.sh"
