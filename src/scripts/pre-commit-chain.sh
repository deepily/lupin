#!/usr/bin/env bash
#
# pre-commit-chain.sh — run every pre-commit gate this repo installs, in order.
#
# WHY A CHAIN EXISTS AT ALL: git allows exactly ONE `.git/hooks/pre-commit`. Before this
# file, that slot was a symlink to `pre-commit-secret-scan.py`, so installing a second gate
# meant silently displacing the first. A chain makes adding a gate an APPEND rather than a
# REPLACE, and makes the full set readable in one place.
#
# INSTALL IT DELIBERATELY, not automatically — this repo is worked by several sessions at
# once and a hook installed under one of them changes how everybody else commits:
#
#     ln -sf ../../src/scripts/pre-commit-chain.sh .git/hooks/pre-commit
#
# FAIL-CLOSED ON THE GATES, FAIL-OPEN ON THE CHAIN. A gate that returns non-zero stops the
# commit. A gate that is MISSING from disk does not: a chain that refuses every commit
# because an optional external script moved is a chain somebody deletes within the hour, and
# a deleted chain takes the gates that DID work down with it. Each skip is announced on
# stderr, loudly, so "not installed" is never mistaken for "passed".
#
# 🔴 A SKIPPED GATE PRINTS. A SILENT SKIP IS THE FAILURE MODE THIS COMMENT EXISTS TO PREVENT:
# a hook that quietly no-ops reads exactly like a hook that passed, and the first person to
# notice is whoever finds the thing it was supposed to stop.
#
# Escape hatch for the whole chain: `git commit --no-verify`. Per-gate hatches are the gates'
# own business (the R&D guard reads RND_GUARD_ALLOW=1). Either way the reason belongs in the
# commit message, where a reviewer sees it.
#
# Added 2026-09-22 by Mr. Radio 🦉 under Rick's ticket `3a2f726b` (R&D directory cleanup),
# to seat María 🌸's `rnd_write_guard.py` beside the existing secret scan.

set -uo pipefail

repo_root="$( git rev-parse --show-toplevel )"
rc=0

# ---- gate 1: no NEW credential value enters the tree -----------------------------------
secret_scan="$repo_root/src/scripts/pre-commit-secret-scan.py"
if [ -x "$secret_scan" ]; then
    "$secret_scan" || rc=$?
    [ "$rc" -ne 0 ] && exit "$rc"
else
    echo "[pre-commit-chain] SKIPPED secret-scan — not executable at $secret_scan" >&2
fi

# ---- gate 2: no UNAUTHORIZED research document enters src/rnd --------------------------
# Lives in planning-is-prompting, which is a SIBLING repo, not vendored here. Resolved from
# PLANNING_IS_PROMPTING_ROOT so the two repos stay independently updatable; when that env var
# is unset the gate announces itself as skipped rather than pretending to have run.
pip_root="${PLANNING_IS_PROMPTING_ROOT:-}"
rnd_guard="$pip_root/workflow/scripts/rnd_write_guard.py"
if [ -n "$pip_root" ] && [ -f "$rnd_guard" ]; then
    python3 "$rnd_guard" --mode precommit --repo-root "$repo_root" || rc=$?
    [ "$rc" -ne 0 ] && exit "$rc"
elif [ -z "$pip_root" ]; then
    echo "[pre-commit-chain] SKIPPED rnd-guard — PLANNING_IS_PROMPTING_ROOT is not set" >&2
else
    echo "[pre-commit-chain] SKIPPED rnd-guard — not found at $rnd_guard" >&2
fi

exit 0
