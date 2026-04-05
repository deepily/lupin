#!/bin/bash
# Runs a python-main-style smoke test directly (with its own argparse flags).
#
# Usage:
#   run-smoke-direct.sh <path-to-test.py> [custom flags...]
#
# Examples:
#   run-smoke-direct.sh src/tests/smoke/test_presentation_live_smoke.py --auto-proxy --cost-cap-usd 2.00
#   run-smoke-direct.sh src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm
#
# Called by TestSuiteJob when test_types="smoke_direct" — pytest_args become "$@".
#
# Writes combined output to /tmp/smoke-direct-latest.log via TestSuiteJob's
# log-symlink mechanism (see src/cosa/agents/test_suite/job.py log_symlinks dict).
#
# Created: 2026-04-05 (Session 389, Phase 1 test-suite expansion)

set -e

# Resolve project root (script is at src/tests/run-smoke-direct.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure PYTHONPATH + LUPIN_ROOT are set for the smoke test
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Delegate to python3 — test file's own argparse handles flags
exec python3 "$@"
