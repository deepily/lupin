#!/bin/bash
# Runs `tsc --noEmit` over ALL THREE TypeScript projects and fails if any is red.
#
# Usage:
#   run-typecheck-gate.sh              # all three projects
#   run-typecheck-gate.sh --list       # print the projects and exit 0
#
# WHY THIS EXISTS. `tsc` was in NO gate at all. Measured 2026-09-08 at 98319e12:
# FIVE type errors across two of the three projects, and every one of them landed
# AFTER `checkJs` was switched on (2026-08-03) — the newest one day before it was
# found. Nothing was stopping a sixth.
#
# ⚠️ AND THE TEST TIER CANNOT SUBSTITUTE FOR IT, which is why this is its own step
# rather than a line in an existing runner. Measured, one variable: a deliberate type
# error appended to a module the TypeScript tier imports took `tsc` from 4 errors to
# 5 and left the tier at 12 pass / 0 fail. The tier executes TypeScript with types
# STRIPPED and never checked, so 100% coverage and a red `tsc` are not in tension —
# they answer different questions.
#
# ⚠️ ALL THREE PROJECTS, NOT `npm run typecheck`. That script runs ONE of the three.
# The first report of this defect said "four errors", which was true of the COMMAND
# and incomplete about the TREE: `typecheck:nav` was red too and nobody had run it.
#
# Called by TestSuiteJob when test_types="typecheck".
#
# Created: 2026-09-08 (the typecheck gate wire-in)

set -uo pipefail

# Up TWO levels — this script lives at src/tests/, so `..` alone lands on src/ and every
# tsconfig lookup below then misses. It is derived from BASH_SOURCE and never from
# $LUPIN_ROOT: a script shipped INSIDE the tree it checks can only be disagreed with by
# the environment, never informed by it.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 1

export LUPIN_ROOT="$PROJECT_ROOT"

# The three tsconfigs are the WHOLE instrumented TypeScript surface. Keep this list
# and the tsconfig files themselves in step: a project added on disk and not added
# here is a project nothing typechecks, which is the exact silence this gate ends.
PROJECTS=( "tsconfig.json" "tsconfig.nav.json" "tsconfig.diagnostic.json" )

if [ "${1:-}" = "--list" ]; then
    printf '%s\n' "${PROJECTS[@]}"
    exit 0
fi

# 🔴 REFUSE RATHER THAN REPORT A CLEAN NOTHING. A missing tsconfig, or a missing tsc,
# makes this gate pass vacuously — and a gate that checked nothing prints exactly what
# a clean tree prints. Both are named and both exit non-zero.
for cfg in "${PROJECTS[@]}"; do
    if [ ! -f "$PROJECT_ROOT/$cfg" ]; then
        echo "REFUSING: $cfg is not present at the project root. Nothing was checked."
        exit 2
    fi
done
if [ ! -x "$PROJECT_ROOT/node_modules/.bin/tsc" ]; then
    echo "REFUSING: no tsc at node_modules/.bin/tsc. Nothing was checked."
    echo "  In a worktree this usually means node_modules was never borrowed —"
    echo "  run src/scripts/link-worktree-artifacts.sh <worktree> first."
    exit 2
fi

echo "=========================================================================="
echo "TypeScript typecheck gate — ${#PROJECTS[@]} projects"
echo "  root : $PROJECT_ROOT"
echo "  tsc  : $( "$PROJECT_ROOT/node_modules/.bin/tsc" --version )"
echo "=========================================================================="

FAILED=0
PASSED=0

for cfg in "${PROJECTS[@]}"; do
    echo
    echo "--- $cfg ---"
    OUT="$( "$PROJECT_ROOT/node_modules/.bin/tsc" --noEmit -p "$cfg" 2>&1 )"
    RC=$?
    N="$( printf '%s\n' "$OUT" | grep -c 'error TS' )"
    if [ "$RC" -eq 0 ] && [ "$N" -eq 0 ]; then
        echo "  OK — 0 errors"
        PASSED=$(( PASSED + 1 ))
    else
        echo "  FAILED — $N errors (rc=$RC)"
        printf '%s\n' "$OUT" | grep 'error TS' | sed 's/^/    /'
        FAILED=$(( FAILED + 1 ))
    fi
done

# Summary in the shape TestSuiteJob._parse_non_pytest_stdout already reads, so a run
# reports counts instead of 0/0/0/0. The "tests" here are the three PROJECTS — said
# plainly, because a count whose unit is unstated is the kind of number that gets
# quoted as something else later.
echo
echo "=========================================================================="
echo "Total Tests: ${#PROJECTS[@]}"
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "=========================================================================="

if [ "$FAILED" -gt 0 ]; then
    echo "TYPECHECK GATE FAILED — $FAILED of ${#PROJECTS[@]} projects have type errors."
    exit 1
fi

echo "TYPECHECK GATE PASSED — all ${#PROJECTS[@]} projects clean."
exit 0
