#!/bin/bash
# Sequentially runs all Lupin test suites in test-pyramid order.
#
# Default behavior: CONTINUE-ON-FAILURE — run all suites, aggregate results.
# Override: --fail-fast flag aborts on first failing suite.
#
# Suite sequence (cheapest → costliest):
#   1. unit       (~30-60s, no server)
#   2. smoke      (~2 min, server-dependent)
#   3. websocket  (~1-2 min, server + WS)
#   4. integration (~5-10 min, server + DB, hot-swaps config)
#   5. e2e        (~17 min, Playwright + browser, hot-swaps config)
#
# Usage:
#   run-all-tests.sh                      # continue-on-failure (default)
#   run-all-tests.sh --fail-fast          # abort on first failure
#
# Called by TestSuiteJob when test_types="all".
# Writes combined output to /tmp/all-tests-latest.log + per-suite logs unchanged.
# Exit 0 only if ALL suites pass; non-zero if ANY failed.
#
# Created: 2026-04-05 (Session 389, Phase 2 test-suite expansion)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Uvicorn subprocess may have empty $HOME — resolve + export so child scripts
# (run-integration-tests.sh, run-e2e-ui-tests.sh, etc.) can find ~/.lupin/
if [ -z "$HOME" ]; then
    HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
    export HOME
fi
# Source test credentials for all child suites that need them
if [ -f "$HOME/.lupin/test-env.sh" ]; then
    # shellcheck source=/dev/null
    source "$HOME/.lupin/test-env.sh"
fi

COMBINED_LOG="/tmp/all-tests-latest.log"
SUMMARY_JSON="/tmp/all-tests-summary.json"
FAIL_FAST=0

# Parse flags (strip them before passing remainder to sub-suites)
PASSTHROUGH_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --fail-fast) FAIL_FAST=1 ;;
        *) PASSTHROUGH_ARGS+=( "$arg" ) ;;
    esac
done

# Suite sequence + runner scripts (pyramid order)
# "typescript" is deliberately absent pending the exclusion ruling on row
# 36e479ed — see the ALL_SUITE_COMPONENTS comment in cosa/agents/test_suite/job.py.
# The suite is schedulable on demand: src/tests/run-typescript-tests.sh
SUITES=( "unit" "smoke" "websocket" "integration" "e2e" )
declare -A SCRIPTS=(
    [unit]="src/tests/run-unit-tests.sh"
    [typescript]="src/tests/run-typescript-tests.sh"
    [smoke]="src/tests/run-smoke-tests.sh"
    [websocket]="src/scripts/run-websocket-smoke-tests.sh"
    [integration]="src/tests/run-integration-tests.sh"
    [e2e]="src/scripts/run-e2e-ui-tests.sh"
)

declare -A EXIT_CODES
declare -A DURATIONS
OVERALL_EXIT=0
SUITES_RUN=0
SUITES_PASSED=0
SUITES_FAILED=0

# Clear combined log
: > "$COMBINED_LOG"

echo "==================================================================" | tee -a "$COMBINED_LOG"
echo "Lupin run-all-tests.sh" | tee -a "$COMBINED_LOG"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S %Z')" | tee -a "$COMBINED_LOG"
echo "Mode: $([ $FAIL_FAST -eq 1 ] && echo 'fail-fast' || echo 'continue-on-failure')" | tee -a "$COMBINED_LOG"
echo "==================================================================" | tee -a "$COMBINED_LOG"

for suite in "${SUITES[@]}"; do
    echo "" | tee -a "$COMBINED_LOG"
    echo "═══ Running: $suite ═══" | tee -a "$COMBINED_LOG"
    START=$(date +%s)

    bash "$PROJECT_ROOT/${SCRIPTS[$suite]}" "${PASSTHROUGH_ARGS[@]}" 2>&1 | tee -a "$COMBINED_LOG"
    EXIT=${PIPESTATUS[0]}

    END=$(date +%s)
    DUR=$(( END - START ))
    EXIT_CODES[$suite]=$EXIT
    DURATIONS[$suite]=$DUR
    SUITES_RUN=$(( SUITES_RUN + 1 ))

    if [ $EXIT -eq 0 ]; then
        SUITES_PASSED=$(( SUITES_PASSED + 1 ))
        echo "  ✓ $suite PASSED (${DUR}s)" | tee -a "$COMBINED_LOG"
    else
        SUITES_FAILED=$(( SUITES_FAILED + 1 ))
        OVERALL_EXIT=$EXIT
        echo "  ✗ $suite FAILED (exit=$EXIT, ${DUR}s)" | tee -a "$COMBINED_LOG"

        if [ $FAIL_FAST -eq 1 ]; then
            echo "" | tee -a "$COMBINED_LOG"
            echo "ABORT: --fail-fast set, skipping remaining suites" | tee -a "$COMBINED_LOG"
            break
        fi
    fi
done

echo "" | tee -a "$COMBINED_LOG"
echo "==================================================================" | tee -a "$COMBINED_LOG"
echo "Summary" | tee -a "$COMBINED_LOG"
echo "==================================================================" | tee -a "$COMBINED_LOG"
for suite in "${SUITES[@]}"; do
    if [ -n "${EXIT_CODES[$suite]}" ]; then
        status=$( [ "${EXIT_CODES[$suite]}" -eq 0 ] && echo "PASS" || echo "FAIL" )
        printf "  %-12s %s (%ss)\n" "$suite" "$status" "${DURATIONS[$suite]}" | tee -a "$COMBINED_LOG"
    else
        printf "  %-12s SKIPPED\n" "$suite" | tee -a "$COMBINED_LOG"
    fi
done
echo "" | tee -a "$COMBINED_LOG"
echo "  Total:  $SUITES_RUN run, $SUITES_PASSED passed, $SUITES_FAILED failed" | tee -a "$COMBINED_LOG"
echo "  Result: $( [ $OVERALL_EXIT -eq 0 ] && echo 'ALL PASSED' || echo 'FAILURES PRESENT' )" | tee -a "$COMBINED_LOG"
echo "==================================================================" | tee -a "$COMBINED_LOG"

# Generate JSON summary for programmatic consumption
python3 -c "
import json, os
summary = {
    'mode': '$([ $FAIL_FAST -eq 1 ] && echo "fail-fast" || echo "continue-on-failure")',
    'suites_run': $SUITES_RUN,
    'suites_passed': $SUITES_PASSED,
    'suites_failed': $SUITES_FAILED,
    'overall_exit': $OVERALL_EXIT,
    'per_suite': {}
}
" > /dev/null 2>&1 || true

cat > "$SUMMARY_JSON" <<EOF
{
  "mode": "$([ $FAIL_FAST -eq 1 ] && echo "fail-fast" || echo "continue-on-failure")",
  "suites_run": $SUITES_RUN,
  "suites_passed": $SUITES_PASSED,
  "suites_failed": $SUITES_FAILED,
  "overall_exit": $OVERALL_EXIT
}
EOF

exit $OVERALL_EXIT
