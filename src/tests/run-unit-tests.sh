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
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

exec python3 -m pytest src/tests/unit/ "$@"
