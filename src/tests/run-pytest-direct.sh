#!/bin/bash
# Runs an arbitrary pytest file via the TestSuiteJob framework.
#
# Usage:
#   run-pytest-direct.sh <path-to-test.py> [pytest flags...]
#
# Examples:
#   run-pytest-direct.sh src/tests/integration/test_tfe_resume_e2e.py -v
#   run-pytest-direct.sh src/tests/integration/test_auth.py -k test_login --tb=short
#
# Called by TestSuiteJob when test_types="pytest_direct" — pytest_args become "$@".
# Mirrors run-smoke-direct.sh but delegates to `python3 -m pytest` instead of
# `python3` directly, so test files with fixtures / markers / parametrize
# decorators work (those can't run under plain `python3 file.py`).
#
# Writes combined output to /tmp/pytest-direct-latest.log via TestSuiteJob's
# log-symlink mechanism (see src/cosa/agents/test_suite/job.py log_symlinks dict).
#
# Created: 2026-04-12 (Session 9056c113 doc 16 follow-up — UI scheduling support)

set -e

# Resolve project root (script is at src/tests/run-pytest-direct.sh → go up TWO levels)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure PYTHONPATH + LUPIN_ROOT are set for the pytest invocation
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Source test credentials if env file exists (allows running under uvicorn
# subprocess context where the server's env doesn't include test creds).
if [ -z "$HOME" ]; then
    HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
    export HOME
fi
if [ -f "$HOME/.lupin/test-env.sh" ]; then
    # shellcheck source=/dev/null
    source "$HOME/.lupin/test-env.sh"
fi

# Delegate to pytest — first arg is the test file, remaining args are pytest flags.
# A collection error is the suite NEVER RUNNING, and its conftest shape fires no pytest
# hook at all — so the exit code, read out here, is the only thing that can report it
# (row 73c6819d). The wrapper re-raises pytest's status verbatim.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis python3 -m pytest "$@"
exit $?
