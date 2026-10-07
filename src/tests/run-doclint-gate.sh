#!/bin/bash
# Runs the documentation lint over every swept Python file and fails if any has a finding.
#
# Usage:
#   run-doclint-gate.sh              # the whole swept scope
#   run-doclint-gate.sh --list       # print the swept files and exit 0
#   run-doclint-gate.sh --tree DIR   # lint the git tree at DIR with THIS tree's code and word list
#
# --tree is what the pre-push hook uses. The files come from DIR; the linter and its word list
# come from the tree this script lives in, so nothing in DIR can switch the check off.
#
# Why this exists. The pre-commit hook lints only the files one commit stages, and a hook can be
# skipped. This gate reads the whole swept scope, so a finding that arrived by a merge or by a
# commit made without the hook is still caught. The merge pyramid and the pre-push hook run it.
#
# The population is swept_scope.swept_files: tracked Python files the documentation standard
# covers, minus the held prefixes. It comes from git, never from a disk walk.
#
# Exit codes: 0 clean, 1 a finding remains, 2 nothing was checked, 3 no interpreter.
# TestSuiteJob reads a run with no summary block as not executed, never as passed.
#
# Called by TestSuiteJob when test_types="doclint".

set -uo pipefail

# Up two levels: this script lives at src/tests/. The root comes from BASH_SOURCE, never from
# $LUPIN_ROOT, so the gate always checks the tree it was shipped in.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 2

export LUPIN_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"

source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_python || exit $?

# Refuse rather than report a clean nothing: a module that does not import checked no file.
if ! "$VENV_PYTHON" -c "import cosa.repo.doc_lint.scope_gate" > /dev/null 2>&1; then
    echo "REFUSING: cosa.repo.doc_lint.scope_gate does not import under $PROJECT_ROOT/src. Nothing was checked."
    exit 2
fi

TARGET="$PROJECT_ROOT"
if [ "${1:-}" = "--tree" ]; then
    if [ -z "${2:-}" ] || [ ! -d "$2" ]; then
        echo "REFUSING: --tree needs a directory, got '${2:-}'. Nothing was checked."
        exit 2
    fi
    TARGET="$( cd "$2" && pwd )"
fi

if [ "${1:-}" = "--list" ]; then
    "$VENV_PYTHON" -c "import sys; from cosa.repo.doc_lint.swept_scope import swept_files; print( '\n'.join( swept_files( sys.argv[ 1 ] ) ) )" "$PROJECT_ROOT"
    exit $?
fi

echo "=========================================================================="
echo "Documentation lint gate: the swept scope"
echo "  root   : $PROJECT_ROOT"
echo "  tree   : $TARGET"
echo "  python : $VENV_PYTHON"
echo "=========================================================================="

REPORT="$( mktemp )"
trap 'rm -f "$REPORT"' EXIT

"$VENV_PYTHON" -m cosa.repo.doc_lint.scope_gate --repo-root "$TARGET" --words-root "$PROJECT_ROOT" > "$REPORT" 2>&1
RC=$?
cat "$REPORT"

# The module answers 0, 1 or 2. Anything else is a crash, and a crashed gate checked nothing.
if [ "$RC" -ne 0 ] && [ "$RC" -ne 1 ] && [ "$RC" -ne 2 ]; then
    echo "REFUSING: the gate exited $RC, which is not a lint result. Nothing was checked."
    exit 2
fi

# An uncaught error also exits 1, the code for findings. The verdict line tells the two apart:
# a pass or a fail ends with it, and a run that ended without one did not finish its check.
if [ "$RC" -ne 2 ] && ! tail -n 1 "$REPORT" | grep -q '^DOCLINT GATE \(PASSED\|FAILED\): '; then
    echo "REFUSING: the gate exited $RC without a verdict line. Nothing was checked."
    exit 2
fi
exit "$RC"
