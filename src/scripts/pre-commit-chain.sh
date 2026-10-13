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

# ---- gate 3: documentation standard, blocking (docstrings, comments and markdown) ------------------
# The gate runs with --blocking. A finding on a line the commit touches refuses the commit, whichever linter
# reports it, in Python and markdown alike. Two files are the exception: the root history.md and TODO.md stay
# in warn mode, so their findings are printed and the commit goes through (gate.WARN_ONLY_PATHS, exact paths).
# The older refusals stand beside it. A staged Python file in the swept scope (swept_scope.is_swept) holding any
# docstring-lint finding, on any line, is refused; a finding is waived by a same-line
# "doc-lint: waive <rule> -- <reason>", and a waiver without a reason waives nothing. A staged Python,
# TypeScript or JavaScript file outside the swept scope is refused when its finding count rises above its entry
# in its count table; a staged table may not raise an entry, and a table cut under other rules refuses a commit
# that stages such a file. A rule file that differs between the index and the working tree refuses a commit
# that stages a judged file or a table. Every run prints the denominator for each scope.
# Every refusal is exit 3, and only exit 3 stops the commit. Any other non-zero exit means the gate did not
# finish: an import error, a missing interpreter, a crash the gate did not catch. That commit is allowed and a
# loud line says it was not checked, because the hook is shared by every worktree and a broken gate must not
# stop every seat. A crash the gate catches prints its own loud line and exits 0. The gate does not read
# PLANNING_IS_PROMPTING_ROOT, so it runs in every worktree.
doc_lint_rc=0
LUPIN_ROOT="$repo_root" PYTHONPATH="$repo_root/src" python3 -m cosa.repo.doc_lint.gate --blocking --repo-root "$repo_root" || doc_lint_rc=$?
if [ "$doc_lint_rc" -eq 3 ]; then
    echo "[pre-commit-chain] doc-lint gate REFUSED the commit: fix each REFUSED line above, stage the fix with git add and commit again" >&2
    exit 1
elif [ "$doc_lint_rc" -ne 0 ]; then
    echo "[pre-commit-chain] doc-lint gate CRASHED (exit $doc_lint_rc), commit ALLOWED and NOT CHECKED against the documentation standard" >&2
fi

exit 0
