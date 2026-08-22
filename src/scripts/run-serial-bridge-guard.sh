#!/bin/bash
# Runs the whole-directory bridge-contact guard (row e2ae4102) — the tier-2 gate.
#
# WHY THIS SCRIPT EXISTS
# The tests marked `serial_bridge_guard` fingerprint the operator's REAL bridge
# directory (~/.claude/sessions) before and after driving register_session.main().
# That check is only VALID on a QUIESCENT box: on a busy fleet box a peer session
# writes its own bridge mid-run and the guard would blame the test (the exact false
# accusation row e2ae4102 was filed for). So these tests are DESELECTED from every
# default run by pytest.ini's `-m "not serial_bridge_guard"`, and run ONLY here.
#
# ⚠️ NOTHING ELSE INVOKES THIS. It is wired into the human merge checklist —
# CLAUDE.md § PR MERGE REQUIREMENTS. If that line is dropped, the whole-directory
# hazard guard is silently gone; the concurrent scoped canary does not see a merge
# into a live seat.
#
# WHEN TO RUN: at merge time, on a quiescent box (you are the only session writing
# bridges — no other CC session mid-write). If it reports contact, a hook is
# resolving its directory from a hardcoded real path instead of the seam.
#
# Usage:
#   run-serial-bridge-guard.sh [extra pytest flags...]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"   # src/scripts → repo root (two levels, not one)
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

VENV_PYTEST="$PROJECT_ROOT/.venv/bin/pytest"
if [ -x "$VENV_PYTEST" ] && "$VENV_PYTEST" --version > /dev/null 2>&1; then PYTEST="$VENV_PYTEST"; else PYTEST="python3 -m pytest"; fi

# `-m serial_bridge_guard` OVERRIDES the addopts `-m` expression, selecting exactly
# the deselected-by-default guard tests. Both files carry one.
#
# A collection error is the guard NEVER RUNNING, and its conftest shape fires no pytest
# hook at all — so the exit code, read out here, is the only thing that can report it
# (row 73c6819d). The wrapper re-raises pytest's status verbatim.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis $PYTEST \
    src/tests/unit/test_sessions_dir_seam.py \
    src/tests/unit/test_register_session_bridge_write_contract.py \
    -m serial_bridge_guard -v "$@"
exit $?
