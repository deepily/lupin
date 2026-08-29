#!/bin/bash
# Refuse a --cov run while another test suite is live — row `e2099400`, Rick's decision 4.
#
# WHY THIS EXISTS. Measured 2026-08-26: a `pytest --cov` tier run sharing the box with a
# second suite reported 82% / 1320 missing statements. The identical tree, run alone minutes
# later, reported 89% / 853 — same command, same isolated COVERAGE_FILE, same pass/skip/xfail
# counts, and NO warning of any kind. coverage.py has no "I could not measure that" state, so
# it prints a number under the conditions where the number means nothing. The error is
# directionally hostile: it reads LOW, so the reflex is to spend a day writing tests for a
# hole that does not exist. And `fail_under` now rises per milestone (Rick, same day), so a
# floor set from a contended run lands ~7 points too low — and being too low, nothing ever
# goes red to say so. Write-up:
# src/rnd/v0.2.0/2026.08.26-contended-tier-run-fabricates-a-coverage-regression.md
#
# WHERE IT IS WIRED, AND WHY THERE IS EXACTLY ONE PLACE. Row fc74c1d4's lesson is that a
# guard written inline in ONE runner never reaches the others — four were still unguarded
# months later. So this is not sourced by each runner. It is sourced ONCE by
# src/scripts/lib/pytest-with-diagnosis.sh and called at the top of
# run_pytest_with_diagnosis, which every sanctioned runner already routes through. One
# insertion covers all of them, and a runner added next month gets the guard by using the
# wrapper it was already going to use.
#
# ⚠️ UNKNOWN IS A REFUSAL, NOT A PASS. If the process table cannot be read, this guard
# cannot do its job — and "reports OK under the condition where it cannot function" is the
# exact defect class it exists to close. It refuses with a DIFFERENT exit code so the log
# says which of the two happened.
#
# EXIT CODES. Deliberately outside pytest's own 0-5 range so a refusal can never be
# misread as a pytest result:
#     6  contended — another suite is running
#     7  unknown   — the process table could not be read
#
# ESCAPE HATCH: LUPIN_ALLOW_CONTENDED_COVERAGE=1 (the number will not be comparable).
#
# USAGE (source it, then call it with the command about to run):
#   source "$LUPIN_ROOT/src/scripts/lib/guard-contended-coverage.sh"
#   guard_contended_coverage "$@" || return $?
#
# ⚠️ IT RETURNS, IT DOES NOT EXIT — same reason as resolve-venv-pytest.sh: a sourced helper
# calling `exit` takes the caller's shell down from inside a function.
#
# Created: 2026-08-26 (row e2099400, decision 4)

GUARD_CONTENDED_COVERAGE_EXIT_CONTENDED=6
GUARD_CONTENDED_COVERAGE_EXIT_UNKNOWN=7

# True when the command asks for coverage at all.
#
# ⚠️ This list is DUPLICATED from _cov_requested in pytest-with-diagnosis.sh on purpose:
# this file must be sourceable and testable on its own. src/tests/unit/
# test_contended_coverage_guard.py pins the two detectors to agree over a shared corpus, so
# the duplication cannot drift silently.
_guard_cov_requested() {
    local a
    for a in "$@"; do
        case "$a" in --cov|--cov=*|--cov-report|--cov-report=*|--cov-config=*) return 0 ;; esac
    done
    return 1
}

# The interpreter that runs the checker module. Mirrors _diagnosis_python next door.
_guard_contention_python() {
    if [ -n "$LUPIN_DIAGNOSIS_PYTHON" ] && [ -x "$LUPIN_DIAGNOSIS_PYTHON" ]; then
        echo "$LUPIN_DIAGNOSIS_PYTHON"; return
    fi
    local candidate
    for candidate in "$LUPIN_ROOT/.venv/bin/python" "/opt/venv/bin/python"; do
        if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
    echo "python3"
}

guard_contended_coverage() {
    # Requires: LUPIN_ROOT set to the repo root. Args are the pytest command about to run.
    # Ensures:  returns 0 when the run may proceed (no coverage asked for, box is clear, or
    #           the escape hatch is engaged); 6 when another suite is running; 7 when the
    #           process table could not be read. Never runs the command itself.
    _guard_cov_requested "$@" || return 0

    local module_path checker_status
    module_path="${LUPIN_ROOT}/src/cosa/utils/coverage_contention.py"

    # The checker is missing: say so and let the run proceed. A guard that can block every
    # coverage run in the tree because one file moved is worse than the hole it closes —
    # but it must never do that QUIETLY, which is the whole point of this file.
    if [ ! -f "$module_path" ]; then
        echo "guard-contended-coverage: checker not found at $module_path — contention" >&2
        echo "  NOT checked for this run. Do not cite its coverage number as isolated." >&2
        return 0
    fi

    "$( _guard_contention_python )" "$module_path"
    checker_status=$?

    case "$checker_status" in
        0) return 0 ;;
        1) return $GUARD_CONTENDED_COVERAGE_EXIT_CONTENDED ;;
        *)
            echo "" >&2
            echo "REFUSING a --cov run: could not tell whether another suite is running." >&2
            echo "  This guard reports CLEAR only when it actually looked. It could not," >&2
            echo "  so it refuses rather than hand you a number it cannot vouch for." >&2
            echo "  DELIBERATE?  LUPIN_ALLOW_CONTENDED_COVERAGE=1 <your command>" >&2
            echo "" >&2
            return $GUARD_CONTENDED_COVERAGE_EXIT_UNKNOWN
            ;;
    esac
}
