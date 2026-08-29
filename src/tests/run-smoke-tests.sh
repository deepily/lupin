#!/bin/bash
# Runs Lupin pytest-discoverable smoke tests (those with def test_*() functions).
#
# For python-main-style smoke tests (with custom argparse like --auto-proxy),
# use run-smoke-direct.sh instead.
#
# Usage:
#   run-smoke-tests.sh [pytest flags...]
#
# Examples:
#   run-smoke-tests.sh                              # all pytest-discoverable smoke tests
#   run-smoke-tests.sh -k presentation              # tests matching 'presentation'
#   run-smoke-tests.sh src/tests/smoke/test_X.py    # single file
#
# Called by TestSuiteJob when test_types="smoke" — pytest_args become "$@".
# Writes output to /tmp/smoke-latest.log via TestSuiteJob log_symlinks dict.
#
# Created: 2026-04-05 (Session 389, Phase 2 test-suite expansion)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Require an EXPLICIT venv pytest — never silently fall back to a bare `python3 -m pytest`.
# A bare python3 resolves to whatever is on PATH; an under-provisioned interpreter aborts
# collection of part of the suite and the runner reports the REDUCED count as the whole
# suite — a false green on a merge gate (row c98bce3f). The resolution is shared rather
# than inline BECAUSE it was inline once and never reached this script (row fc74c1d4).
source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_pytest || exit $?

# test_proxy_integration.py is a DESTRUCTIVE :8000-venue suite (mutates DB state,
# ~180s/scenario) that only lives in this folder — the folder is not a venue
# marker (CLAUDE.md § TESTING VENUES). It runs via its own scheduled invocation
# (python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy),
# never as part of the pytest-discoverable smoke leg. Observed riding along on
# ts-b51e63c9 (2026-06-12), blowing the smoke leg to 3806.9s.
# A collection error is the suite NEVER RUNNING, and its conftest shape fires no pytest
# hook at all — so the exit code, read out here, is the only thing that can report it
# (row 73c6819d). The wrapper re-raises pytest's status verbatim.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis $PYTEST src/tests/smoke/ --ignore=src/tests/smoke/test_proxy_integration.py "$@"
exit $?
