#!/bin/bash
# Runs the documentation lint over every swept Python file and fails if any has a finding.
# Run on the whole tree, it then checks the metrics dashboard page, as a second step.
#
# Usage:
#   run-doclint-gate.sh                         # the whole swept scope, then the dashboard check
#   run-doclint-gate.sh --dashboard-base REV    # the same, with REV as the dashboard's before commit
#   run-doclint-gate.sh --list                  # print the swept files and exit 0
#   run-doclint-gate.sh --tree DIR              # lint the git tree at DIR with THIS tree's code and word list
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
# Step 2, the dashboard check (cosa.repo.doc_lint.doc_metrics dashboard check). It measures the
# tree again and fails when a compared marker value rose in a row, or when the committed page
# src/docs/doc-metrics-dashboard.md is not the page of this tree. --tree does not run it: the
# pre-push hook lints a pushed tip, and the whole-tree run in the merge pyramid checks the page.
# --dashboard-base exists for a repo that does not hold the default before commit, such as the
# scratch repos of the tests.
#
# Exit codes: 0 clean, 1 a finding remains or the dashboard check failed, 2 nothing was checked,
# 3 no interpreter. The dashboard check's own codes map like this: 0 passes; 1 (a value rose)
# and 3 (a row is missing or the page names another before commit) are exit 1 here; 2 (could not
# check) is exit 2 here; 4 (only the numbers on the page are stale) passes, with the check's
# warning line printed and the regenerate command repeated in the last line.
#
# The summary block. With --tree it is the docstring step's own: the unit is files. On the whole
# tree the docstring step's four lines are printed under other names, and one block follows whose
# unit is the swept files plus one for the dashboard check. Errors there is the findings plus the
# lines the dashboard check printed for a rise, a missing row or a stale page.
# TestSuiteJob reads a run with no summary block as not executed, never as passed, so a run
# that could not check prints none.
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

DASH_BASE=()
if [ "${1:-}" = "--dashboard-base" ]; then
    if [ -z "${2:-}" ]; then
        echo "REFUSING: --dashboard-base needs a revision. Nothing was checked."
        exit 2
    fi
    DASH_BASE=( --base "$2" )
    shift 2
fi

TARGET="$PROJECT_ROOT"
TREE_MODE=0
if [ "${1:-}" = "--tree" ]; then
    TREE_MODE=1
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
DASH_REPORT="$( mktemp )"
trap 'rm -f "$REPORT" "$DASH_REPORT"' EXIT

"$VENV_PYTHON" -m cosa.repo.doc_lint.scope_gate --repo-root "$TARGET" --words-root "$PROJECT_ROOT" > "$REPORT" 2>&1
RC=$?

# The module answers 0, 1 or 2. Anything else is a crash, and a crashed gate checked nothing.
if [ "$RC" -ne 0 ] && [ "$RC" -ne 1 ] && [ "$RC" -ne 2 ]; then
    cat "$REPORT"
    echo "REFUSING: the gate exited $RC, which is not a lint result. Nothing was checked."
    exit 2
fi

# An uncaught error also exits 1, the code for findings. The verdict line tells the two apart:
# a pass or a fail ends with it, and a run that ended without one did not finish its check.
if [ "$RC" -ne 2 ] && ! tail -n 1 "$REPORT" | grep -q '^DOCLINT GATE \(PASSED\|FAILED\): '; then
    cat "$REPORT"
    echo "REFUSING: the gate exited $RC without a verdict line. Nothing was checked."
    exit 2
fi

# A refusal of the docstring step, and every --tree run, ends here with that step's own output.
if [ "$RC" -eq 2 ] || [ "$TREE_MODE" -eq 1 ]; then
    cat "$REPORT"
    if [ "$TREE_MODE" -eq 1 ]; then
        echo "Dashboard check: not run with --tree; the whole-tree run of this script runs it."
    fi
    exit "$RC"
fi

# The whole tree. The docstring step's count lines and verdict are printed under other names, so
# the one block TestSuiteJob reads is the block at the end, which covers both steps.
sed -e 's/^Total Tests: /Docstring step, files checked: /' \
    -e 's/^Passed: /Docstring step, files clean: /' \
    -e 's/^Failed: /Docstring step, files with a finding: /' \
    -e 's/^Errors: /Docstring step, findings: /' \
    -e 's/^DOCLINT GATE PASSED: /Docstring step passed: /' \
    -e 's/^DOCLINT GATE FAILED: /Docstring step failed: /' "$REPORT"

count_of() {
    sed -n "s/^$1: \([0-9][0-9]*\)\$/\1/p" "$REPORT" | tail -n 1
}
FILES="$( count_of 'Total Tests' )"
CLEAN="$( count_of 'Passed' )"
FOUND="$( count_of 'Failed' )"
FINDINGS="$( count_of 'Errors' )"

echo "=========================================================================="
echo "Documentation lint gate, step 2: the metrics dashboard check"
echo "=========================================================================="

"$VENV_PYTHON" -m cosa.repo.doc_lint.doc_metrics dashboard check --repo-root "$TARGET" --words-root "$PROJECT_ROOT" ${DASH_BASE[@]+"${DASH_BASE[@]}"} > "$DASH_REPORT" 2>&1
DRC=$?
cat "$DASH_REPORT"

# The check answers 0, 1, 2, 3 or 4. Anything else is a crash, and a crashed check checked nothing.
if [ "$DRC" -eq 2 ]; then
    echo "REFUSING: the dashboard check could not check (exit 2). Nothing is summarised."
    exit 2
fi
if [ "$DRC" -ne 0 ] && [ "$DRC" -ne 1 ] && [ "$DRC" -ne 3 ] && [ "$DRC" -ne 4 ]; then
    echo "REFUSING: the dashboard check exited $DRC, which is not a check result. Nothing was checked."
    exit 2
fi
# An interpreter that dies also exits 1, the code for a rise. The verdict line tells them apart.
if ! tail -n 1 "$DASH_REPORT" | grep -q '^DASHBOARD CHECK \(PASSED\|FAILED\): '; then
    echo "REFUSING: the dashboard check exited $DRC without a verdict line. Nothing was checked."
    exit 2
fi
# Exit 4 is a pass only with its warning line, so stale numbers are never passed in silence.
STALE_NOTE=""
if [ "$DRC" -eq 4 ]; then
    STALE_COMMAND="$( sed -n 's/^WARNING .*; regenerate with: \(.*\)$/\1/p' "$DASH_REPORT" | tail -n 1 )"
    if [ -z "$STALE_COMMAND" ]; then
        echo "REFUSING: the dashboard check exited 4 without its warning line. Nothing was checked."
        exit 2
    fi
    STALE_NOTE="; dashboard numbers are stale, regenerate with: $STALE_COMMAND"
fi
if [ -z "$FILES" ] || [ -z "$CLEAN" ] || [ -z "$FOUND" ] || [ -z "$FINDINGS" ]; then
    echo "REFUSING: the docstring step printed no counts to add to. Nothing is summarised."
    exit 2
fi

DASH_FAILED=0
DASH_WORD="passed"
if [ "$DRC" -ne 0 ] && [ "$DRC" -ne 4 ]; then
    DASH_FAILED=1
    DASH_WORD="failed"
fi
DASH_LINES="$( grep -c '^\(ROSE\|MISSING\|STALE\) ' "$DASH_REPORT" )"

echo "=========================================================================="
echo "Documentation lint gate: both steps. The unit is the swept files plus one for the dashboard check."
echo "Total Tests: $(( FILES + 1 ))"
echo "Passed: $(( CLEAN + 1 - DASH_FAILED ))"
echo "Failed: $(( FOUND + DASH_FAILED ))"
echo "Errors: $(( FINDINGS + DASH_LINES ))"
if [ "$RC" -eq 0 ] && [ "$DASH_FAILED" -eq 0 ]; then
    if [ -n "$STALE_NOTE" ]; then
        echo "DOCLINT GATE PASSED: $FILES files clean$STALE_NOTE"
    else
        echo "DOCLINT GATE PASSED: $FILES files clean and the dashboard check passed."
    fi
    exit 0
fi
echo "DOCLINT GATE FAILED: $FOUND of $FILES files hold a finding; the dashboard check $DASH_WORD$STALE_NOTE."
exit 1
