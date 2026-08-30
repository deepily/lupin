#!/usr/bin/env bash
#
# Give a linked worktree a .venv by symlinking the main repo's, so the unit tier answers
# the same question in every tree.
#
# THE DEFECT THIS CLOSES (row f42ac20c). `.venv` is gitignored, so `git worktree add` never
# produces one — measured 2026-08-29, only 5 of 29 trees had a usable `.venv/bin/python`.
# Four unit-test files shell out to `<PROJECT_ROOT>/.venv/bin/{python,pytest}`, so they PASS
# in the main tree and FAIL in every worktree without one, with no code difference between
# them. Measured on ONE clean tree at ONE sha with only this symlink added and removed:
#
#     no .venv    14 failed · 835 passed · 2 skipped
#     .venv       1 failed · 848 passed · 2 skipped
#
# The remaining 1 is an unrelated genuine failure (test_pragma_reason_policy), not venue.
#
# WHY A SYMLINK AND NOT A BUILT VENV: it costs nothing, duplicates no packages, and is what
# the shared resolver's own guard already tells people to do — `resolve-venv-pytest.sh`
# (row c98bce3f) refuses to degrade to a bare `python3 -m pytest`, and its docstring names
# symlinking the main repo's .venv as the worktree fix.
#
# ⚠️ THIS DOES NOT TOUCH THE SPAWN PATH. Making worktree creation do this automatically is a
# separate row per Mr. Radio's ruling, because it is fleet-wide plumbing that cannot be
# validated in the same change. This script is the manual half, usable today.
#
# Usage:
#   src/scripts/link-worktree-venv.sh            # provision the tree you are standing in
#   src/scripts/link-worktree-venv.sh <path>     # provision another worktree
#   src/scripts/link-worktree-venv.sh --check    # report, change nothing (exit 1 if absent)

set -euo pipefail

TARGET="${1:-$PWD}"
CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=1
    TARGET="$PWD"
fi

if [[ ! -d "$TARGET" ]]; then
    echo "ERROR: not a directory: $TARGET" >&2
    exit 2
fi

# The main repo is the worktree list's first entry — git reports the primary tree first,
# which is the one that actually owns a .venv.
MAIN_REPO="$( git -C "$TARGET" worktree list --porcelain | awk '/^worktree /{print $2; exit}' )"
if [[ -z "$MAIN_REPO" ]]; then
    echo "ERROR: $TARGET is not inside a git repository" >&2
    exit 2
fi

SOURCE_VENV="$MAIN_REPO/.venv"
LINK="$TARGET/.venv"

if [[ $CHECK_ONLY -eq 1 ]]; then
    if [[ -x "$LINK/bin/python" ]]; then
        echo "OK: $TARGET has a usable .venv ($( readlink "$LINK" 2>/dev/null || echo "real directory" ))"
        exit 0
    fi
    echo "MISSING: $TARGET has no usable .venv/bin/python" >&2
    echo "  Four unit-test files will fail here that pass in the main tree (row f42ac20c)." >&2
    echo "  Fix: src/scripts/link-worktree-venv.sh" >&2
    exit 1
fi

if [[ "$( cd "$TARGET" && pwd -P )" == "$( cd "$MAIN_REPO" && pwd -P )" ]]; then
    echo "REFUSING: $TARGET is the MAIN repo, which owns the real .venv."
    echo "  Linking it to itself would replace a real directory with a loop."
    exit 3
fi

if [[ ! -x "$SOURCE_VENV/bin/python" ]]; then
    echo "ERROR: the main repo has no usable venv to link: $SOURCE_VENV/bin/python" >&2
    echo "  Build it there first; this script only shares an existing one." >&2
    exit 4
fi

if [[ -e "$LINK" || -L "$LINK" ]]; then
    if [[ -x "$LINK/bin/python" ]]; then
        echo "ALREADY PROVISIONED: $LINK resolves to a usable interpreter — leaving it alone."
        exit 0
    fi
    # A dangling symlink is the one case worth clearing: it is ours and it is broken.
    if [[ -L "$LINK" && ! -e "$LINK" ]]; then
        echo "Replacing a dangling symlink at $LINK"
        rm "$LINK"
    else
        echo "REFUSING: $LINK already exists and is not a usable venv." >&2
        echo "  It is not mine to delete — inspect it and remove it yourself if it is stale." >&2
        exit 5
    fi
fi

ln -s "$SOURCE_VENV" "$LINK"

# Verify rather than assume: a symlink that resolves to nothing looks identical to success.
if [[ ! -x "$LINK/bin/python" ]]; then
    echo "ERROR: created $LINK but it does not resolve to an executable interpreter" >&2
    exit 6
fi

echo "Linked: $LINK -> $SOURCE_VENV"
echo "        $( "$LINK/bin/python" --version )"
