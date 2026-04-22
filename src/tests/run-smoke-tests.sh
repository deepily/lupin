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

# Use venv pytest on host, fall back to system pytest in Docker container
VENV_PYTEST="$PROJECT_ROOT/src/cosa/.venv/bin/pytest"
if [ -x "$VENV_PYTEST" ] && "$VENV_PYTEST" --version > /dev/null 2>&1; then PYTEST="$VENV_PYTEST"; else PYTEST="python3 -m pytest"; fi

exec $PYTEST src/tests/smoke/ "$@"
