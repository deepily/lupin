#!/bin/bash
# Runs the test-suite live pipeline smoke by hand against :8000, only on a verified-idle venue.
#
# WHY THIS EXISTS. That smoke submits a test-suite job, and a test-suite job always takes the
# monopolize slot. Inside any suite job (the smoke tier, smoke_direct, pytest_direct) the slot is
# held by the suite job itself, so the submitted job is deferred until the suite ends and can never
# run as its child. Every suite job exports LUPIN_TEST_MONOPOLIZE_PARENT_ID, so a "scheduled run"
# of this file would skip for the same reason. This runner is the one door that works: the host,
# outside any suite job.
#
# Usage:
#   src/scripts/run-test-suite-live-smoke.sh [pytest flags...]
#
# It refuses, exit 64, when:
#   - LUPIN_TEST_MONOPOLIZE_PARENT_ID is set (it was started from inside a suite job), or
#   - cosa.rest.venue_idle does not exit 0 for :8000. Busy (1) and unknown (2) are both refused:
#     unknown is not idle.
# Otherwise it runs the one file against :8000 and exits with pytest's status, unchanged.
#
# The check and the run are two steps, so a job queued between them is not seen. The window is
# small; it is not zero.
#
# Credentials: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD, as for every live smoke.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH}"
export LUPIN_ROOT="$PROJECT_ROOT"

REFUSED=64

if [ -n "${LUPIN_TEST_MONOPOLIZE_PARENT_ID:-}" ]; then
    echo "REFUSED: this was started from inside a suite job (LUPIN_TEST_MONOPOLIZE_PARENT_ID is set)." >&2
    echo "  A test-suite job cannot run as the child of a suite job. Run this from a host shell." >&2
    exit $REFUSED
fi

python3 -m cosa.rest.venue_idle --port 8000
idle=$?
if [ "$idle" -ne 0 ]; then
    echo "REFUSED: cosa.rest.venue_idle --port 8000 exited $idle (1 BUSY, 2 UNKNOWN). Unknown is not idle." >&2
    echo "  Wait until the venue reads IDLE, then run this again." >&2
    exit $REFUSED
fi

source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_pytest || exit $?

source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
export LUPIN_TEST_BASE_URL="http://localhost:8000"
run_pytest_with_diagnosis $PYTEST src/tests/smoke/test_test_suite_live_pipeline.py "$@"
exit $?
