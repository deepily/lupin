#!/usr/bin/env bash
#
# Runs the TypeScript test suite under c8 with an ENFORCED coverage threshold.
#
# WHY THIS SCRIPT EXISTS (board row 36e479ed): CLAUDE.md's 100% COVERAGE
# MANDATE names TypeScript explicitly — "100% coverage, lines AND branches AND
# functions, TypeScript via c8 --100". Until this script, nothing invoked it.
# No runner, no test-type, no hook, no CI. The mandate's Python half had real
# teeth via --cov-fail-under=100; the TypeScript half was enforced by a human
# remembering to type a command, which meant a TS regression landed silently.
#
# The threshold below is the enforcement. `--check-coverage` makes c8 exit
# non-zero when any of the four numbers falls short, which is what turns this
# from a report into a gate.
#
# Usage:
#   run-typescript-tests.sh                 # full suite at the enforced threshold
#   run-typescript-tests.sh --report-only   # measure, never fail on coverage
#
# Called by TestSuiteJob when test_types="typescript".
#
# VENUE — :8000, scheduled. Measured 2026-07-21: 2,245 tests in 8m19s, well
# past the 2-minute :7999 ceiling in CLAUDE.md § TESTING VENUES. It mutates no
# persistent state, so the routing is runtime, not blast radius.

set -uo pipefail

# Resolve project root (script is at src/tests/run-typescript-tests.sh → up TWO levels)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 1

# Coverage thresholds — the mandate, expressed as numbers a process can act on.
# Statements is included because c8's --100 shorthand covers it and dropping it
# would let a whole uncovered statement class pass a "100%" gate.
THRESHOLD_LINES=100
THRESHOLD_BRANCHES=100
THRESHOLD_FUNCTIONS=100
THRESHOLD_STATEMENTS=100

CHECK_COVERAGE="--check-coverage"
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --report-only) CHECK_COVERAGE="" ;;
        *)             PASSTHROUGH_ARGS+=( "$arg" ) ;;
    esac
done

# Instrumented source: the three TypeScript entry trees named by the tsconfigs
# (tsconfig.json, tsconfig.nav.json, tsconfig.diagnostic.json). `--all` counts
# files with ZERO tests — without it, an entirely untested module is invisible
# to the percentage, which is the same silence this gate exists to end.
#
# NOTE for src/cosa/repo/gate_reachability.py: the `src/tests/**` glob below is
# a GLOB ROOT, not a suite target. That detector's path-token regex rejects it
# on purpose; see the comment on _PATH_TOKEN_RE.
exec npx c8 \
    --all \
    $CHECK_COVERAGE \
    --lines      "$THRESHOLD_LINES" \
    --branches   "$THRESHOLD_BRANCHES" \
    --functions  "$THRESHOLD_FUNCTIONS" \
    --statements "$THRESHOLD_STATEMENTS" \
    --include='src/lupin_app/static/js/multiplexer/**/*.ts' \
    --include='src/lupin_app/static/js/nav/**/*.ts' \
    --include='src/lupin_app/static/js/diagnostic/**/*.ts' \
    --exclude='**/*.test.ts' \
    --reporter=text-summary \
    --reporter=text \
    npx tsx --test "src/tests/**/*.test.ts" "${PASSTHROUGH_ARGS[@]}"
