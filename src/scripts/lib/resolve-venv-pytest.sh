#!/bin/bash
# Resolve an EXPLICIT venv pytest, or refuse — rows c98bce3f and fc74c1d4.
#
# WHY THIS EXISTS, AND WHY IT IS A LIBRARY RATHER THAN A BLOCK OF SHELL.
#
# A runner that cannot find a venv pytest has two options, and they are not close in
# consequence. It can fall back to a bare `python3 -m pytest`, which resolves to whatever
# interpreter is on PATH; if that one is under-provisioned (the container's /opt/venv
# missing pytest-timeout, say), a collection error aborts a chunk of the suite and the
# runner reports the REDUCED count as the whole suite — ~3000 tests silently uncollected,
# measured in row c98bce3f. On :8000, the final merge gate, that manufactures a false GREEN
# as easily as a false red. Or it can refuse and name exactly what it looked for. Row
# c98bce3f chose refuse.
#
# THE PART THAT MADE THIS A LIBRARY. That guard was written inline in run-unit-tests.sh and
# never reached the other runners. Row fc74c1d4 found run-cosa-tests.sh still falling back
# silently — and it had joined the PR merge requirements on 2026-08-13 (row d83d025b), so it
# carried the same gate weight with none of the protection. Repro from a fresh worktree
# (no .venv) on 2026-08-22: run-unit-tests.sh exited 3 with the warning while
# run-cosa-tests.sh happily started `python3 -m pytest src/cosa/tests/ -q`.
#
# Widening the check while fixing that row found the fallback in FOUR runners, not one:
#     src/tests/run-cosa-tests.sh          the row's own target
#     src/tests/run-smoke-tests.sh         TestSuiteJob's "smoke" test type
#     src/scripts/run-serial-bridge-guard.sh   a NAMED step in § PR MERGE REQUIREMENTS
#     src/tests/run-pytest-direct.sh       worse — bare python3 unconditionally, never
#                                          even trying a venv (its header's "delegates to
#                                          python3 -m pytest" is about module-vs-file
#                                          invocation, not a deliberate interpreter choice)
#
# Copying the fixed block into four more files would have re-armed the exact mechanism that
# produced the drift. So the resolution lives here once and every runner sources it, which
# is also what makes it pinnable: src/tests/unit/test_runner_venv_pytest_guard.py asserts
# that NO sanctioned runner carries a bare-python3 fallback, so the next runner written with
# one is caught by a test rather than by somebody re-finding it in a worktree.
#
# USAGE (source it, then call it; it sets PYTEST in the caller's shell):
#   source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
#   resolve_venv_pytest || exit $?
#   ... "$PYTEST" ...
#
# ⚠️ IT RETURNS, IT DOES NOT EXIT. A sourced function calling `exit` would take the caller's
# shell down from inside a helper, which is both surprising and untestable in isolation. The
# caller decides, and every caller in-tree decides `exit $?` — preserving row c98bce3f's
# exit code 3, which the scheduled suite job and any human reading a log already know.
#
# Created: 2026-08-24 (row fc74c1d4 — the propagation half of c98bce3f)

# The known venv locations, in order. Host developer/CI venv first, then the in-container
# venv baked by docker/lupin/Dockerfile (UV_PROJECT_ENVIRONMENT=/opt/venv), verified present
# in lupin-rest-dev on 2026-08-24.
LUPIN_VENV_PYTEST_CANDIDATES=(
    ".venv/bin/pytest"       # host developer / CI venv        (relative to PROJECT_ROOT)
    "/opt/venv/bin/pytest"   # in-container venv (Docker image) (absolute)
)

resolve_venv_pytest() {
    # Requires: PROJECT_ROOT set to the repo root by the calling runner.
    # Ensures:  on success sets PYTEST to a runnable pytest and returns 0;
    #           otherwise prints what was looked for, and why a fallback is refused,
    #           to stderr and returns 3 — leaving PYTEST empty.
    local root="${PROJECT_ROOT:-$LUPIN_ROOT}" cand resolved
    PYTEST=""

    for cand in "${LUPIN_VENV_PYTEST_CANDIDATES[@]}"; do
        case "$cand" in
            /*) resolved="$cand" ;;
             *) resolved="$root/$cand" ;;
        esac
        if [ -x "$resolved" ] && "$resolved" --version > /dev/null 2>&1; then
            PYTEST="$resolved"
            return 0
        fi
    done

    {
        echo "FATAL: no runnable venv pytest found. Looked for (in order):"
        for cand in "${LUPIN_VENV_PYTEST_CANDIDATES[@]}"; do
            case "$cand" in
                /*) echo "  - $cand" ;;
                 *) echo "  - $root/$cand" ;;
            esac
        done
        echo "Refusing to fall back to a bare 'python3 -m pytest': a silent interpreter switch can"
        echo "run an under-provisioned interpreter, abort collection of part of the suite, and report"
        echo "the reduced count as the whole suite — a false green on the :8000 merge gate (row c98bce3f)."
        echo "Provision the venv (e.g. /opt/venv in the container), then re-run."
        echo "In a fresh git worktree the usual cause is simply that it has no .venv of its own;"
        echo "'ln -s <main-repo>/.venv .venv' inside the worktree is the one-line fix (row fc74c1d4)."
    } >&2
    return 3
}


# ── The same rule for a venv PYTHON ────────────────────────────────────────────────────
#
# Three runners resolve an interpreter rather than a pytest binary, and run the suite as
# `"$VENV_PYTHON" -m pytest`. They carried the identical silent degrade in a different
# spelling, which is why grepping for `python3 -m pytest` did not find them:
#
#     VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python3"
#     if ! "$VENV_PYTHON" --version > /dev/null 2>&1; then VENV_PYTHON="python3"; fi
#
# That second line is the c98bce3f fallback wearing a variable name. It was in
# run-integration-tests.sh — THE FINAL MERGE GATE per CLAUDE.md § PR MERGE REQUIREMENTS —
# and in run-e2e-ui-tests.sh and run-presentation-regression.sh. Those runners also use the
# interpreter for non-pytest work (preflight_test_db.py, inline `-c` probes), so they need a
# python rather than a pytest; the refusal rule is the same either way.

LUPIN_VENV_PYTHON_CANDIDATES=(
    ".venv/bin/python3"       # host developer / CI venv        (relative to PROJECT_ROOT)
    "/opt/venv/bin/python3"   # in-container venv (Docker image) (absolute)
)

resolve_venv_python() {
    # Requires: PROJECT_ROOT set to the repo root by the calling runner.
    # Ensures:  on success sets VENV_PYTHON to a runnable interpreter and returns 0;
    #           otherwise explains the refusal on stderr and returns 3, leaving it empty.
    local root="${PROJECT_ROOT:-$LUPIN_ROOT}" cand resolved
    VENV_PYTHON=""

    for cand in "${LUPIN_VENV_PYTHON_CANDIDATES[@]}"; do
        case "$cand" in
            /*) resolved="$cand" ;;
             *) resolved="$root/$cand" ;;
        esac
        if [ -x "$resolved" ] && "$resolved" --version > /dev/null 2>&1; then
            VENV_PYTHON="$resolved"
            return 0
        fi
    done

    {
        echo "FATAL: no runnable venv python found. Looked for (in order):"
        for cand in "${LUPIN_VENV_PYTHON_CANDIDATES[@]}"; do
            case "$cand" in
                /*) echo "  - $cand" ;;
                 *) echo "  - $root/$cand" ;;
            esac
        done
        echo "Refusing to fall back to a bare 'python3': a silent interpreter switch can run an"
        echo "under-provisioned interpreter, abort collection of part of the suite, and report the"
        echo "reduced count as the whole suite — a false green on the :8000 merge gate (row c98bce3f)."
        echo "Provision the venv (e.g. /opt/venv in the container), then re-run."
        echo "In a fresh git worktree the usual cause is simply that it has no .venv of its own;"
        echo "'ln -s <main-repo>/.venv .venv' inside the worktree is the one-line fix (row fc74c1d4)."
    } >&2
    return 3
}
