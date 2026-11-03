#!/bin/bash
# Runs the reuse gate over the outcome lines the branch under test adds, as a merge-pyramid step.
#
# Usage:
#   run-reuse-gate.sh                       # this tree's HEAD against the merge base with main
#   run-reuse-gate.sh --base REV            # measure from REV instead of main
#   run-reuse-gate.sh --diff FILE           # use a symbol index diff as the list of new definitions, in place of the one built from git
#
# What it reads: the Markdown lines HEAD adds since the merge base, the call log, the search records, the
# definitions HEAD adds to indexed files (found from git, each needs an outcome line) and the key
# `reuse review gating` in the main checkout's lupin-app.ini. It sends nothing and runs no model.
# With the key false it reports and exits 0. With the key true any refused line or any definition with no
# outcome line exits 1.
#
# Exit codes: 0 clean or report only, 1 refused, 3 could not check (the key is unreadable, git names no base,
# the list of new definitions cannot be built, or no interpreter). A run that could not check prints no
# summary block, so TestSuiteJob reads it as not executed, never as passed.
#
# Called by TestSuiteJob when test_types="reuse". Module: src/lupin_mcp/reuse_merge_gate.py.

set -uo pipefail

# Up two levels: this script lives at src/tests/. The root comes from BASH_SOURCE, never from $LUPIN_ROOT,
# so the gate always checks the tree it was shipped in.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 3

export LUPIN_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"

source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_python || exit $?

# Refuse rather than report a clean nothing: a module that does not import checked no line.
if ! "$VENV_PYTHON" -c "import lupin_mcp.reuse_merge_gate" > /dev/null 2>&1; then
    echo "REFUSING: lupin_mcp.reuse_merge_gate does not import under $PROJECT_ROOT/src. Nothing was checked."
    exit 3
fi

echo "=========================================================================="
echo "Reuse gate: the outcome lines this branch adds"
echo "  root   : $PROJECT_ROOT"
echo "  python : $VENV_PYTHON"
echo "=========================================================================="

"$VENV_PYTHON" -m lupin_mcp.reuse_merge_gate --root "$PROJECT_ROOT" "$@"
RC=$?

# The module answers 0, 1 or 3. Anything else is a crash, and a crashed gate checked nothing.
if [ "$RC" -ne 0 ] && [ "$RC" -ne 1 ] && [ "$RC" -ne 3 ]; then
    echo "REFUSING: the gate exited $RC, which is not a gate result. Nothing was checked."
    exit 3
fi
exit "$RC"
