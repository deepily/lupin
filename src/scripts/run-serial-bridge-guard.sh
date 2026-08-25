#!/bin/bash
# Runs the whole-directory bridge-contact guard (row e2ae4102) — the tier-2 gate.
#
# WHY THIS SCRIPT EXISTS
# The tests marked `serial_bridge_guard` fingerprint the operator's REAL bridge
# directory (~/.claude/sessions) before and after driving register_session.main().
# A peer session can write its own bridge mid-run, and the guard would then blame the
# test (the exact false accusation row e2ae4102 was filed for). So these tests are
# DESELECTED from every default run by pytest.ini's `-m "not serial_bridge_guard"`,
# and run ONLY here.
#
# ⚠️ NOTHING ELSE INVOKES THIS. It is wired into the human merge checklist —
# CLAUDE.md § PR MERGE REQUIREMENTS. If that line is dropped, the whole-directory
# hazard guard is silently gone; the concurrent scoped canary does not see a merge
# into a live seat.
#
# WHEN TO RUN: at merge time. 🔴 THIS HEADER USED TO SAY "on a quiescent box (you are
# the only session writing bridges)". THAT STATE NEVER ARRIVES — measured 2026-08-24
# with no suite running anywhere, 13 entries under ~/.claude/sessions changed in 60
# seconds, and the seat RUNNING the guard writes its own bridge while the guard
# executes. It cannot be arranged by asking peers to hold still. Superseded by
# CLAUDE.md § PR MERGE REQUIREMENTS (row 5a68c92c); analysis in
# src/rnd/v0.2.0/2026.08.24-serial-bridge-guard-unsatisfiable-precondition.md.
#
# HOW TO READ THE RESULT — real contact is DETERMINISTIC, peer noise is not:
#   1. Re-run and compare the NAMED file. Same filename every run = contact.
#      A different file each run, or none = peer noise.
#   2. Identify the writer: read the named file's session_id / cc_pid, then
#      `ls /proc/<cc_pid>`. A live seat that is not the test is noise.
#   3. 🔴 IT CUTS BOTH WAYS — ONE GREEN IS ALSO ONE SAMPLE. On a check whose failure
#      mode is nondeterministic, a single pass is exactly as weak as a single fail.
#      Run it more than once before reporting EITHER colour.
# Real contact means a hook is resolving its directory from a hardcoded real path
# instead of the seam.
#
# Usage:
#   run-serial-bridge-guard.sh [extra pytest flags...]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"   # src/scripts → repo root (two levels, not one)
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

# `-m serial_bridge_guard` OVERRIDES the addopts `-m` expression, selecting exactly
# the deselected-by-default guard tests. Every file listed below carries one.
#
# ⚠️ THIS LIST AND THE MARKER MUST AGREE, IN BOTH DIRECTIONS (row ece4d86a).
# A file that carries the marker and is MISSING here runs NOWHERE — addopts
# deselects it from every default run and nothing selects it back. A file listed
# here that carries NO marker contributes ZERO tests, and an empty selection exits
# green. test_register_session_no_bridge_witness.py was in the first case until
# 2026-08-22: marked module-wide, absent from this list, running nowhere.
# Both directions are now pinned by tests in src/tests/unit/test_bridge_dir_guard.py
# ("every marked file is actually run by the serial runner" + its inverse), which
# read THIS file — so adding a marker without adding the path here goes red.
#
# A collection error is the guard NEVER RUNNING, and its conftest shape fires no pytest
# hook at all — so the exit code, read out here, is the only thing that can report it
# (row 73c6819d). The wrapper re-raises pytest's status verbatim.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis $PYTEST \
    src/tests/unit/test_sessions_dir_seam.py \
    src/tests/unit/test_register_session_bridge_write_contract.py \
    src/tests/unit/test_register_session_no_bridge_witness.py \
    -m serial_bridge_guard -v "$@"
exit $?
