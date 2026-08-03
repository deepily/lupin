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
# ===========================================================================
# THE DENOMINATOR EXCLUSIONS — RATIFIED BY RICK 2026-07-21 (gate 07a5460d)
# ===========================================================================
# Answered LIVE, not by timeout — and the timeout default was NO, so this is a
# decision, not a fallthrough.
#
# WHAT IT COST, MEASURED BEFORE THE RULING (full suite under c8, 2026-07-21):
#     2,245 / 2,245 tests pass
#     Statements 93.19% (23,889/25,633) · Lines 93.19%
#     Branches   99.94% (5,145/5,148)   · Functions 99.82% (1,754/1,757)
# The mandate was not merely unenforced — it was UNMET. The ENTIRE 6.81%
# statement gap is the three categories below, at 0% each; nothing else in the
# instrumented trees was under 100%. The numbers are recorded here so the next
# reader sees what was excluded AND what excluding it bought, without re-running
# a nine-minute suite to find out.
#
# Each exclusion carries its own dated reason. An exclusion without a reason is
# a narrowed denominator nobody can audit — and the only thing that makes a
# coverage number mean anything is that nobody adjusted the denominator to
# reach it.
#
#   --exclude='**/boot.ts'   2026-07-21 (Rick, 07a5460d): browser ENTRY POINTS
#       (multiplexer, nav, diagnostic). Imported by no test by construction —
#       importing one executes page bootstrap against a live DOM. Prior art in
#       this repo already excluded boot.ts explicitly before the mandate existed.
#
#   --exclude='**/types.ts'  2026-07-21 (Rick, 07a5460d): TYPE-ONLY modules.
#       They emit no runtime statements, so they can only ever score 0% and
#       cannot be covered by any test that could be written.
#
#   --exclude='**/index.ts'  2026-07-21 (Rick, 07a5460d): BARREL re-exports
#       (transport, render, stores). Pure `export ... from` with no logic; the
#       symbols they forward are themselves covered at their definition sites.
#
# ⚠️ IF YOU ADD A FOURTH EXCLUSION: it needs its own dated ruling on this list.
# Widening the denominator's holes is how a 100% gate becomes decorative, and
# the diff that does it must be one a reviewer can see and question.
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
    --exclude='**/boot.ts' \
    --exclude='**/types.ts' \
    --exclude='**/index.ts' \
    --reporter=text-summary \
    --reporter=text \
    npx tsx --test "src/tests/**/*.test.ts" "${PASSTHROUGH_ARGS[@]}"
