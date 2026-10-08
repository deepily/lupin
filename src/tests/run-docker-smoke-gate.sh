#!/bin/bash
# Runs the three docker smoke files on the host and fails on any skip.
#
# Usage:
#   run-docker-smoke-gate.sh
#
# The files are test_credential_mount_shape.py, test_db_roles_rollback_real_postgres.py and
# test_db_grants_real_postgres.py, all under src/tests/smoke/. They start a throwaway Postgres or read
# the compute containers, so they need docker. Inside the merge gate's containers there is no docker
# socket and every one of their tests skips, which the smoke step counts as a pass. This step runs on the
# host and counts a skip, an error and a file with no test in the report as a failure.
#
# Skipped on purpose, and counted as a failure: test_compute_containers_run_as_the_host_uid skips itself
# when neither lupin-rest container is up. A host gate with no containers up has checked nothing.
#
# The unit of the count is tests. A skip counts as a failure, so Failed is failures, errors, skips and
# missing files together.
#
# Exit codes: 0 every test passed, 1 a failure or a skip, 2 nothing was checked, 3 no interpreter.
# TestSuiteJob reads a run with no summary block as not executed, never as passed.
#
# Called by TestSuiteJob when test_types="docker_smoke". The suite is host only.

set -uo pipefail

# Up two levels: this script lives at src/tests/. The root comes from BASH_SOURCE, never from
# $LUPIN_ROOT, so the gate always runs the tree it was shipped in.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 2

export LUPIN_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"

source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_python || exit $?

FILES=(
    "src/tests/smoke/test_credential_mount_shape.py"
    "src/tests/smoke/test_db_roles_rollback_real_postgres.py"
    "src/tests/smoke/test_db_grants_real_postgres.py"
)

echo "=========================================================================="
echo "Docker smoke gate: three files, a skip is a failure"
echo "  root   : $PROJECT_ROOT"
echo "  python : $VENV_PYTHON"
echo "=========================================================================="

# Refuse rather than report a clean nothing: without docker every test would skip.
if ! timeout 20 docker info > /dev/null 2>&1; then
    echo "REFUSING: docker is not usable here. Nothing was checked."
    exit 2
fi

JUNIT="$( mktemp )"
trap 'rm -f "$JUNIT"' EXIT

"$VENV_PYTHON" -m pytest "${FILES[@]}" --junit-xml="$JUNIT" -rs -q -p no:cacheprovider
PYTEST_RC=$?

REPORT="$( "$VENV_PYTHON" -m cosa.repo.docker_smoke_report "$JUNIT" )"
RC=$?

# A pytest that failed while the report read clean ran something the report cannot see. The counts are
# withheld then, so the job reads no summary and calls the run not executed.
if [ "$RC" -eq 0 ] && [ "$PYTEST_RC" -ne 0 ]; then
    echo "REFUSING: pytest exited $PYTEST_RC while the report read clean. Nothing was checked."
    exit 2
fi
echo "$REPORT"
exit "$RC"
