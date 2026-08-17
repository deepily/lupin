#!/bin/bash
# Runs Lupin unit tests (fast, no server dependency, ~915 tests).
#
# Usage:
#   run-unit-tests.sh [pytest flags...]
#
# Examples:
#   run-unit-tests.sh                       # all unit tests
#   run-unit-tests.sh -k jwt                # tests matching 'jwt'
#   run-unit-tests.sh -v --cov=cosa         # verbose + coverage
#
# Called by TestSuiteJob when test_types="unit" — pytest_args become "$@".
# Writes output to /tmp/unit-latest.log via TestSuiteJob log_symlinks dict.
#
# Created: 2026-04-05 (Session 389, Phase 2 test-suite expansion)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Require an EXPLICIT venv pytest — never silently fall back to a bare `python3 -m pytest`.
# The old fallback quietly ran whatever `python3` resolved to on PATH; when that interpreter
# was under-provisioned (e.g. the container's /opt/venv missing pytest-timeout), a collection
# error aborted a chunk of the suite and the runner presented the REDUCED count as the whole
# suite — ~3000 tests silently uncollected. On :8000, the final merge gate, that silent
# interpreter switch can manufacture a false GREEN as easily as a false red. So: try the known
# venv pytest locations in order, and if NONE is a runnable pytest, FAIL LOUD naming exactly
# what was looked for and where, rather than degrading to system python. (row c98bce3f)
VENV_PYTEST_CANDIDATES=(
    "$PROJECT_ROOT/.venv/bin/pytest"   # host developer / CI venv
    "/opt/venv/bin/pytest"             # in-container venv (Docker image)
)
PYTEST=""
for _cand in "${VENV_PYTEST_CANDIDATES[@]}"; do
    if [ -x "$_cand" ] && "$_cand" --version > /dev/null 2>&1; then PYTEST="$_cand"; break; fi
done
if [ -z "$PYTEST" ]; then
    echo "FATAL: no runnable venv pytest found. Looked for (in order):" >&2
    for _cand in "${VENV_PYTEST_CANDIDATES[@]}"; do echo "  - $_cand" >&2; done
    echo "Refusing to fall back to a bare 'python3 -m pytest': a silent interpreter switch can" >&2
    echo "run an under-provisioned interpreter, abort collection of part of the suite, and report" >&2
    echo "the reduced count as the whole suite — a false green on the :8000 merge gate (row c98bce3f)." >&2
    echo "Provision the venv (e.g. /opt/venv in the container), then re-run." >&2
    exit 3
fi
echo "run-unit-tests.sh: using pytest at $PYTEST" >&2

# A collection error is the suite NEVER RUNNING, and the conftest shape of it fires no
# pytest hook at all — so the exit code, read out here, is the only thing that can report
# it (row 73c6819d). The wrapper re-raises pytest's status verbatim; `exec` is gone
# because an exec'd shell has no life left in which to read a status.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis "$PYTEST" src/tests/unit/ "$@"
exit $?
