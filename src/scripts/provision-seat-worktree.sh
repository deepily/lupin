#!/usr/bin/env bash
#
# Give a spawned SEAT its own private worktree, so two seats can never be mid-edit in
# one working tree.
#
# THE DEFECT THIS CLOSES (row 9d654899, ruled by Rick 2026-09-03: "Adopt, with drift
# disclosure"). `git commit -- <path>` commits that path's WORKING-TREE CONTENT, so a
# seat that legitimately claims a file still commits whatever a peer left uncommitted
# inside it. Every control the fleet has is per-FILE and the hazard is per-HUNK:
#
#   · the session manifest says the file is yours — and it IS yours
#   · the commit scope guard checks the PATH against your section — and it passes
#   · a pathspec cannot help — you named exactly the file you meant
#
# It has fired three times: a completed HIT (57 of one seat's uncommitted lines landed
# in a peer's commit, under his name, with every control saying yes), and two near
# misses — one caught by reading a diff, and one on 2026-09-03 at 19:11 where a peer's
# uncommitted file sat in the shared checkout during a merge. The commit log dates that
# third window at ONE MINUTE (the peer committed at 19:12), which is why "just look
# before you commit" is a habit rather than a control.
#
# ⚠️ WHY PROVISIONING AND NOT AN ALARM. `session_spawner` already DETECTS this — it
# returns `placement_alarm` when a seat lands in the shared main checkout. An alarm
# tells a seat it is standing somewhere unsafe and leaves it there. Under the ruling the
# default itself is wrong, so the detection becomes the fix. This is deliberately the
# same shape as `link-worktree-venv.sh`, which the spawn path already calls.
#
# ⚠️ WHAT THIS DOES NOT DO: it never removes a worktree. Reaping is a separate policy
# (seat death is the trigger, emptiness is the permission — designed on row 9d654899,
# unbuilt). Measured 2026-09-03 before writing this: 129 worktrees, 123 with no
# uncommitted work, 21G total against 1.1T free — so disk is NOT the argument for
# reaping, and this script does not pretend to settle it.
#
# Usage:
#   provision-seat-worktree.sh <main-repo-root> <seat-name>
#   provision-seat-worktree.sh --check <path>     # report, change nothing
#
# Machine-readable output — the caller parses these keys, one per line, never the prose:
#   WORKTREE=<absolute path>
#   DRIFT_BEHIND=<commits this tree is behind the main checkout's HEAD>
#   STATUS=created|reused|already_seat_tree
#
# Exit codes:
#   0  the seat has a private worktree (created or already there)
#   2  bad arguments, missing directory, or not a git repository
#   4  the target already exists and is NOT a worktree — not ours to touch
#   5  git worktree add failed
#   6  created it but it does not verify — never report success on an unverified tree

set -euo pipefail

if [[ "${1:-}" == "--check" ]]; then
    TARGET="${2:-$PWD}"
    if [[ ! -d "$TARGET" ]]; then
        echo "ERROR: not a directory: $TARGET" >&2
        exit 2
    fi
    # No pipe into a short-circuiting reader — see the SIGPIPE note in
    # link-worktree-venv.sh; this box has a 129-entry worktree list.
    if ! LIST="$( git -C "$TARGET" worktree list --porcelain 2>/dev/null )"; then LIST=""; fi
    MAIN=""
    while IFS= read -r line; do
        if [[ "$line" == "worktree "* ]]; then MAIN="${line#worktree }"; break; fi
    done <<< "$LIST"
    if [[ -z "$MAIN" ]]; then
        echo "ERROR: $TARGET is not inside a git repository" >&2
        exit 2
    fi
    if [[ "$( cd "$TARGET" && pwd -P )" == "$( cd "$MAIN" && pwd -P )" ]]; then
        echo "SHARED: $TARGET is the MAIN checkout — a peer's uncommitted work can be here" >&2
        exit 1
    fi
    echo "PRIVATE: $TARGET is its own worktree"
    exit 0
fi

MAIN_ROOT="${1:-}"
SEAT_NAME="${2:-}"

if [[ -z "$MAIN_ROOT" || -z "$SEAT_NAME" ]]; then
    echo "ERROR: usage: provision-seat-worktree.sh <main-repo-root> <seat-name>" >&2
    exit 2
fi
if [[ ! -d "$MAIN_ROOT" ]]; then
    echo "ERROR: not a directory: $MAIN_ROOT" >&2
    exit 2
fi

if ! LIST="$( git -C "$MAIN_ROOT" worktree list --porcelain 2>/dev/null )"; then LIST=""; fi
MAIN=""
while IFS= read -r line; do
    if [[ "$line" == "worktree "* ]]; then MAIN="${line#worktree }"; break; fi
done <<< "$LIST"
if [[ -z "$MAIN" ]]; then
    echo "ERROR: $MAIN_ROOT is not inside a git repository" >&2
    exit 2
fi

# ⚠️ RESOLVE THE MAIN CHECKOUT RATHER THAN TRUSTING THE ARGUMENT. A manager standing in
# its own worktree hands us that worktree; nesting a worktree inside one is not what the
# ruling asks for, and `git worktree list` already names the primary tree for us.
MAIN="$( cd "$MAIN" && pwd -P )"

# Sanitize the seat name into a path segment. A seat name reaches us from a spawn
# record; it is not a path and must never be able to become one.
SLUG="$( printf '%s' "$SEAT_NAME" | tr -c 'A-Za-z0-9._-' '-' | sed 's/^-*//; s/-*$//' )"
if [[ -z "$SLUG" ]]; then
    echo "ERROR: seat name sanitizes to nothing: $SEAT_NAME" >&2
    exit 2
fi

REPO_NAME="$( basename "$MAIN" )"
TARGET="$( dirname "$MAIN" )/${REPO_NAME}-wt-${SLUG}"

# 🔴 THE SHORT-CIRCUIT ASKS "AM I THIS SEAT'S OWN TREE", NOT "AM I SOMEWHERE OTHER THAN
# THE MAIN CHECKOUT" — and it is computed AFTER `TARGET` for exactly that reason.
#
# This block used to sit above, testing `MAIN_ROOT != MAIN`, and it had a hole Rachel
# measured on 2026-09-03: a manager standing in its OWN worktree hands us that worktree
# (`_resolve_project_root` returns it deliberately — row 1cf6c918, because sending its
# workers to the main checkout would quietly undo the manager's own isolation). The old
# test passed, the seat name was IGNORED, and every seat of the batch plus the manager
# shared one working tree with every alarm silent. Measured: two different seat names,
# same tree, `STATUS=main_repo_ok` both times.
#
# ⚠️ IT IS A HOLE, NOT A REGRESSION — today's code puts them in the same place. But it
# means the fix does not fire in a configuration the row's own hazard lives in, which is
# worse than it sounds: a silent pass reads as protection.
#
# ⇒ It is the same shape as the blind assertion in this change's own test suite:
# "not the main checkout" is not "private to me", exactly as git listing the main
# checkout as a worktree makes "appears in `git worktree list`" no proof of isolation.
if [[ "$( cd "$MAIN_ROOT" && pwd -P )" == "$TARGET" ]]; then
    echo "STATUS=already_seat_tree"
    echo "WORKTREE=$TARGET"
    echo "DRIFT_BEHIND=$( git -C "$MAIN_ROOT" rev-list --count HEAD.."$( git -C "$MAIN" rev-parse HEAD )" 2>/dev/null || echo 0 )"
    echo "Already this seat's own worktree — nothing to provision."
    exit 0
fi

# Idempotent: a registered worktree at that path is REUSED, never recreated. A seat that
# is re-spun under the same name comes back to its own tree with its work still in it.
IS_REGISTERED=0
while IFS= read -r line; do
    if [[ "$line" == "worktree "* ]]; then
        if [[ "${line#worktree }" == "$TARGET" ]]; then IS_REGISTERED=1; break; fi
    fi
done <<< "$LIST"

if [[ $IS_REGISTERED -eq 1 && -d "$TARGET" ]]; then
    echo "STATUS=reused"
    echo "WORKTREE=$TARGET"
    echo "DRIFT_BEHIND=$( git -C "$TARGET" rev-list --count HEAD.."$( git -C "$MAIN" rev-parse HEAD )" 2>/dev/null || echo 0 )"
    echo "Reusing the existing worktree for seat $SEAT_NAME"
    exit 0
fi

if [[ -e "$TARGET" ]]; then
    echo "ERROR: $TARGET exists and is not a registered worktree — not mine to touch" >&2
    exit 4
fi

if ! git -C "$MAIN" worktree add --detach "$TARGET" HEAD >/dev/null 2>&1; then
    echo "ERROR: git worktree add failed for $TARGET" >&2
    exit 5
fi

# Verify rather than assume — a directory that exists is not a working tree.
if [[ ! -d "$TARGET" ]] || ! git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
    echo "ERROR: created $TARGET but it is not a usable worktree" >&2
    exit 6
fi

echo "STATUS=created"
echo "WORKTREE=$TARGET"
echo "DRIFT_BEHIND=$( git -C "$TARGET" rev-list --count HEAD.."$( git -C "$MAIN" rev-parse HEAD )" 2>/dev/null || echo 0 )"
echo "Created a private worktree for seat $SEAT_NAME at $TARGET"
