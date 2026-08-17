#!/bin/bash
# Runs the in-tree CoSA test suite: src/cosa/tests/** (~8,800 tests).
#
# Usage:
#   run-cosa-tests.sh [pytest flags...]
#
# Examples:
#   run-cosa-tests.sh                       # all CoSA tests
#   run-cosa-tests.sh -k config             # tests matching 'config'
#   run-cosa-tests.sh -x -q                 # stop on first failure, quiet
#
# WHY THIS EXISTS: board row c9d3ddcb. The entire src/cosa/tests/ tree was
# reachable by NO gate-invocable runner, no INI key, and no test_suite
# test-type — so it could not go red and its rot emitted nothing (the exact
# defect the gate-reachability census, row d97b024e, was built to catch). Rick
# ruled WIRE IT IN on 2026-08-13; this runner is the wire. Adding it to
# SUITE_SCRIPTS in cosa/agents/test_suite/job.py makes the census follow it and
# treat src/cosa/tests/** as reachable.
#
# Called by TestSuiteJob when test_types="cosa" — pytest_args become "$@".
#
# Created: 2026-08-13 (board row c9d3ddcb — CoSA test tree wire-in)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Use venv pytest on host, fall back to system pytest in Docker container
VENV_PYTEST="$PROJECT_ROOT/.venv/bin/pytest"
if [ -x "$VENV_PYTEST" ] && "$VENV_PYTEST" --version > /dev/null 2>&1; then PYTEST="$VENV_PYTEST"; else PYTEST="python3 -m pytest"; fi

# A collection error is the suite NEVER RUNNING, and its conftest shape fires no pytest
# hook at all — so the exit code, read out here, is the only thing that can report it
# (row 73c6819d). The wrapper re-raises pytest's status verbatim.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis $PYTEST src/cosa/tests/ "$@"
exit $?
