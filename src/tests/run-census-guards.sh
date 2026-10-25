#!/bin/bash
# Runs the census and pin guards of the unit tier, the ones that go red when NEW code lands.
#
# Usage: src/tests/run-census-guards.sh      (about 40 s on 2026-10-09; no server, no network)
#
# Run it before asking for review, as well as the tests of the files you changed. A census guard
# counts something in the whole tree, so it can fail on a commit that touches none of its files
# (row 420e96ee: two went red only on the first whole unit run of a 17-commit line).
#
# The selection is from git, so a new guard is picked up the day it is added, two ways:
#   a file named test_every_*, *census*, *_pin*, *pins* or *pinned* is run whole;
#   in any other tracked unit file, each test_every_* function is run by node id (bug a197b338).
# A guard named otherwise is not in this set. Name new ones to match.
# The rule lives in src/tests/helpers/census_selection.py; "--list" prints the selection and runs nothing.
#
# Exit code: pytest's; 2 when the selection finds nothing or cannot read a file (a run over nothing is not a pass).

set -uo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 2

export LUPIN_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"

source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_pytest || exit $?

PYBIN="$( dirname "$PYTEST" )/python3"
if [ ! -x "$PYBIN" ]; then PYBIN="$( dirname "$PYTEST" )/python"; fi
FILES="$( git ls-files 'src/tests/unit/*' | "$PYBIN" -m tests.helpers.census_selection )" || {
    echo "run-census-guards: the selection could not read a file; refusing to run a smaller census" >&2
    exit 2
}
if [ -z "$FILES" ]; then
    echo "run-census-guards: the selection found nothing; refusing to call that a pass" >&2
    exit 2
fi
if [ "${1:-}" = "--list" ]; then
    echo "$FILES"
    exit 0
fi
echo "run-census-guards: $( echo "$FILES" | grep -vc '::' ) files by name, $( echo "$FILES" | grep -c '::' ) test_every_* functions elsewhere"

# The wrapper reports a collection error as the suite never running, and keeps the contention guard.
source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
# shellcheck disable=SC2086  # the file names are tracked paths without spaces
run_pytest_with_diagnosis "$PYTEST" $FILES -q -p no:cacheprovider --no-cov
exit $?
