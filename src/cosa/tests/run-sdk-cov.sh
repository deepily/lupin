#!/usr/bin/env bash
#
# run-sdk-cov.sh — coverage runner for SDK-adjacent CoSA packages.
#
# WHY THIS EXISTS
#   Packages that transitively import claude_agent_sdk (bug_fix_expediter,
#   test_fix_expediter, swe_team, shared, claude_code) pull in mcp.types, whose
#   pydantic RootModel[Union[...]] generic-submodel is created at import time.
#   Under pytest-cov's tracer that creation hits:
#       KeyError: 'pydantic.root_model'
#   inside pydantic._internal._generics.create_generic_submodel (the dynamic
#   model's __module__ resolves to 'pydantic.root_model', which is momentarily
#   absent from sys.modules while the cov tracer is active).
#
#   NOTE: `unset COVERAGE_CORE` does NOT fix this (both the ctrace and pytrace
#   cores fail identically). The reliable fix is to PRE-IMPORT claude_agent_sdk
#   in the parent process BEFORE pytest.main() starts coverage — this warms
#   pydantic's _GENERIC_TYPES_CACHE so the later traced import reuses the cached
#   model and never re-runs create_generic_submodel.
#
# WHAT IT DOES
#   Resolves the cosa venv interpreter, sets PYTHONPATH=<repo>/src, pre-imports
#   claude_agent_sdk, then forwards ALL arguments verbatim to pytest.main().
#   Test-only; touches no production code; makes no real LLM/SDK/network calls
#   (the pre-import is a pure module import, zero spend).
#
# USAGE
#   src/cosa/tests/run-sdk-cov.sh <any pytest args>
#
#   e.g.
#   src/cosa/tests/run-sdk-cov.sh \
#       src/cosa/tests/unit/agents/bug_fix_expediter/ \
#       --cov=cosa.agents.bug_fix_expediter.git_ops \
#       --cov-report=term-missing -q
#
# Established 2026-05-31 (Mr. Radio 🦉) per Tiberius's fleet ruling: all
# SDK-adjacent packages re-measure through this runner.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"   # .../src/cosa/tests -> repo root
VENV_PY="$REPO_ROOT/src/cosa/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    echo "run-sdk-cov.sh: cosa venv interpreter not found at $VENV_PY" >&2
    exit 1
fi

exec env PYTHONPATH="$REPO_ROOT/src:${PYTHONPATH:-}" "$VENV_PY" -c '
import claude_agent_sdk  # noqa: F401  pre-warm pydantic generic-model cache before cov tracer
import sys, pytest
sys.exit( pytest.main( sys.argv[1:] ) )
' "$@"
