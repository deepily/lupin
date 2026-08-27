#!/bin/bash
# Runs the CJ Flow v2 paired eval (cold pass + warm pass) as a registered suite.
#
# Usage:
#   run-v2-eval.sh [v2_eval.py flags...]
#
# Examples:
#   run-v2-eval.sh                                   # defaults: :8000, n_per_command=60, seed 1024
#   run-v2-eval.sh --n-per-command 5                 # a short shakedown
#   run-v2-eval.sh --base-url http://localhost:8000  # explicit venue
#
# WHY THIS EXISTS: row 7e2125a7, decision D6. The v2 eval had NO registered
# runner, so it was absent from SUITE_SCRIPTS and `POST /api/test-suite/submit`
# could not run it at all — and the side-door prohibition (CLAUDE.md § TESTING
# VENUES) forbids every other route. The confirming run that row 7e2125a7 asks
# for was therefore not merely expensive, it was unreachable through the only
# sanctioned door. This runner is the wire.
#
# 🔴 THIS IS NOT A MERGE-GATE TIER, AND IT IS DELIBERATELY ABSENT FROM
# ALL_SUITE_COMPONENTS. It runs ~105 minutes and spends real money on the
# metered firewalled LLM path (CLAUDE.md § COST MODEL). Putting it in the
# pyramid would attach an hour and a half of billed work to every merge.
# Same treatment as `presentation` — individually submittable, never in "all".
#
# WHAT "PASSED" MEANS HERE, AND WHY IT IS ONE. An eval produces METRICS, not
# test outcomes. Reporting its accuracy figures as passed/failed counts would
# manufacture exactly the kind of confident-looking number row 7e2125a7 is
# about. So the suite-level question this runner answers is the only honest
# one available: DID THE EVAL COMPLETE AND WRITE ITS ARTIFACT — one check,
# passing or failing. The findings live in the report the run names on stdout.
#
# Created: 2026-08-26 (row 7e2125a7 decision D6 — v2 eval suite registration)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Not `set -e`-guarded: we WANT the exit code so the summary can report it.
set +e
python3 src/scripts/v2_eval.py "$@"
EVAL_RC=$?
set -e

# The summary block the test_suite parser reads (_parse_non_pytest_stdout).
# Deliberately ONE check — see "WHAT PASSED MEANS HERE" above. Emitting counts
# derived from the eval's own accuracy numbers would report a measurement as a
# test result, which is the misreporting family this row exists to document.
echo ""
echo "=== v2 eval summary ==="
echo "Total Tests: 1"
if [ $EVAL_RC -eq 0 ]; then
    echo "Passed: 1"
    echo "Failed: 0"
else
    echo "Passed: 0"
    echo "Failed: 1"
    echo "v2 eval exited $EVAL_RC — the run did not complete; no artifact to read."
fi

exit $EVAL_RC
