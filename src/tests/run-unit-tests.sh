#!/bin/bash
# Runs Lupin unit tests (fast, no server dependency).
#
# COUNT: 20,974 collected, 11 deselected by pytest.ini's marker addopts, measured
# 2026-08-30 at a5e13262 and again at 742ac477 with the same result. The "~915" that
# stood on this line from this file's creation (172cb57f, 2026-04-05) until today had
# aged by a factor of 23. So DATE the figure, and re-derive rather than quote it:
#
#   run-unit-tests.sh --collect-only -q 2>/dev/null | tail -1
#
# Usage:
#   run-unit-tests.sh [pytest flags...]
#
# Examples:
#   run-unit-tests.sh                       # all unit tests
#   run-unit-tests.sh -k jwt                # tests matching 'jwt'
#
# COVERAGE — use the LUPIN_COVERAGE opt-in, never a `--cov=<path>` flag:
#
#   LUPIN_COVERAGE=1 COVERAGE_FILE=/tmp/cov-$USER.data run-unit-tests.sh
#
# This example read `-v --cov=cosa` until 2026-08-30, and that TAUGHT the defect row
# e2099400 exists to close: a scoped `--cov=<path>` OVERRIDES pyproject's `source`
# list, so the run measures a SMALLER frame than the config names — and a report says
# nothing at all about a file it never traced, so the output looks clean either way.
# Absence from a scoped report means never-measured, not zero. The opt-in passes a
# BARE `--cov`, which uses the config's own source list; see the reasoning in
# src/scripts/lib/coverage-opt-in.sh. No single tier meets the whole-system floor —
# enforcement happens once, after every tier has appended, in run-coverage-gate.sh.
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

# Arm the unit tier's network guard in BLOCK mode (row 7c84b8b8): a "unit" test that
# opens a routed socket FAILS THE RUN, named by test id, address and the STACK that
# dialled — not the test that happened to be in flight, which named a file containing
# no networking code at all the first time this was measured.
#
# FLIPPED FROM count TO block on 2026-08-19, the last step of 7c84b8b8. It ran in count
# while two known offenders were open: a collection-time probe in test_dm_quality_judge.py
# (closed, 4d35c39d) and the DM send path's inline grader (closed test-side, f5a860a9 /
# 77e5d7df; moved off the send path entirely for row ec5cf83a). Both tiers then measured
# 0 outbound with the guard armed, which is what made the flip safe rather than hopeful.
#
# `count` is still available for a census — export LUPIN_UNIT_NETWORK=count — and is the
# right mode when you WANT the full list rather than the first offender.
export LUPIN_UNIT_NETWORK="${LUPIN_UNIT_NETWORK:-block}"

# Require an EXPLICIT venv pytest — never silently fall back to a bare `python3 -m pytest`.
# This guard was born here (row c98bce3f) and lived here as inline shell, which is precisely
# why it never reached run-cosa-tests.sh, run-smoke-tests.sh or run-serial-bridge-guard.sh —
# all three were still falling back silently when row fc74c1d4 found them on 2026-08-24. The
# resolution now lives in ONE place that every runner sources; behaviour here is unchanged,
# including the exit code 3 and the message.
source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_pytest || exit $?
echo "run-unit-tests.sh: using pytest at $PYTEST" >&2

# A collection error is the suite NEVER RUNNING, and the conftest shape of it fires no
# pytest hook at all — so the exit code, read out here, is the only thing that can report
# it (row 73c6819d). The wrapper re-raises pytest's status verbatim; `exec` is gone
# because an exec'd shell has no life left in which to read a status.
# Opt-in coverage (row e2099400). OFF unless LUPIN_COVERAGE is set, so an ad-hoc
# scoped run never emits a partial tier-wide number. run-all-tests.sh sets it for the
# pyramid; the floor is enforced once, afterwards, by run-coverage-gate.sh.
source "$PROJECT_ROOT/src/scripts/lib/coverage-opt-in.sh"
COV_FLAGS="$( coverage_opt_in_flags )" || exit $?

source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
run_pytest_with_diagnosis "$PYTEST" src/tests/unit/ $COV_FLAGS "$@"
exit $?
