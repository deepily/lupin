#!/bin/bash
# Run pytest, and when it turns out the suite never RAN, say so — row 73c6819d.
#
# WHY THIS EXISTS. A pytest collection error is silence, not a red, and it comes in two
# shapes that behave completely differently (measured 2026-08-17, row bc83f2df):
#
#   error in a TEST module -> exit 2, junit written, pytest hooks FIRE  -> catchable in-process
#   error in a CONFTEST    -> exit 4, NO junit, NO hook fires anywhere  -> invisible in-process
#
# The conftest shape takes the whole directory down BEFORE pytest has a session, so a
# plugin or a conftest hook cannot report it — not even the outermost one. The EXIT CODE,
# read from outside the process, is the only signal that survives it. That is what this
# wrapper reads, and it is why the fix lives in the shell rather than in pytest.
#
# The scheduled suite job already does this (job.py reads the same exit code and calls the
# same module). This wrapper is the OTHER caller: a human at a terminal running one of the
# sanctioned runner scripts, who until now got pytest's bare traceback and no cause class.
#
# ⚠️ THE EXIT CODE IS THE PRODUCT. This wrapper re-raises pytest's status verbatim. A
# wrapper that swallowed a non-zero status would turn every failure into the same silence
# it was built to end, so the diagnosis is printed BESIDE the result and never instead of
# it, and the diagnoser's own status is discarded rather than allowed to become the run's.
#
# USAGE (source it, then call it in place of `exec pytest`). Every argument is part of the
# command, so a multi-word pytest ("python3 -m pytest") works as well as a venv binary:
#   source "$PROJECT_ROOT/src/scripts/lib/pytest-with-diagnosis.sh"
#   run_pytest_with_diagnosis "$PYTEST" src/tests/unit/ "$@"
#   exit $?
#
# ⚠️ NOTE FOR CALLERS THAT USED `exec`. `exec` replaces the shell, so there is no shell
# left to read the exit code — a caller must drop the exec and exit with the returned
# status. That leaves this script alive as the child's parent, which is a real change: a
# PID-file guard now records THIS shell's PID, not pytest's. Both were verified for the
# runners that use one (row 73c6819d).
#
# Created: 2026-08-17 (row 73c6819d — the human-at-a-terminal half of bc83f2df)

# ── Contended-coverage guard (row e2099400, decision 4) ─────────────────────
#
# Sourced HERE rather than by each runner on purpose. Row fc74c1d4's lesson is that a guard
# written inline in one runner never reaches the others — four were still unguarded months
# after the first fix. Every sanctioned runner already routes through
# run_pytest_with_diagnosis below, so one insertion covers all of them.
_GUARD_CONTENDED_COVERAGE_LIB="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/guard-contended-coverage.sh"
if [ -f "$_GUARD_CONTENDED_COVERAGE_LIB" ]; then
    # shellcheck source=guard-contended-coverage.sh
    source "$_GUARD_CONTENDED_COVERAGE_LIB"
else
    echo "pytest-with-diagnosis: guard-contended-coverage.sh not found beside this file —" >&2
    echo "  a --cov run will NOT be checked for a competing suite. Row e2099400." >&2
fi

# Resolve the interpreter used to render a diagnosis. It runs the module BY FILE PATH, so
# no `cosa` package import is involved — which matters, because the failure being
# diagnosed is frequently an import error in this very tree.
_diagnosis_python() {
    if [ -n "$LUPIN_DIAGNOSIS_PYTHON" ] && [ -x "$LUPIN_DIAGNOSIS_PYTHON" ]; then
        echo "$LUPIN_DIAGNOSIS_PYTHON"; return
    fi
    local candidate
    for candidate in "$LUPIN_ROOT/.venv/bin/python" "/opt/venv/bin/python"; do
        if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
    echo "python3"
}

# ── Coverage-blindness detector (row f8e5215b) ──────────────────────────────
#
# THE SHAPE: pytest-cov's --no-cov-on-fail suppresses the ENTIRE coverage report when any
# test in the run fails. Pair that with a tier carrying tolerated red — a worktree tier
# always does (row 1cf6c918) — and the instrument goes blind exactly when the number is
# wanted. The failure is SILENT: no warning, no "coverage suppressed" line, just an absent
# table. Nothing distinguishes "coverage was not measured" from "I forgot to pass --cov",
# so a ten-minute tier can be run specifically to get a number the flag then deletes
# (measured 2026-08-22 gating a0322a77; reproduced 2026-08-24 on this branch).
#
# WHAT THE FLAG ACTUALLY BUYS, measured 2026-08-24 rather than assumed. Coverage TRACING is
# paid whenever --cov is passed at all; the flag skips only the report RENDER at the end.
# Same two-file red run, three configs:
#     --no-cov                                 0.61s
#     --cov=cosa --no-cov-on-fail              0.83s   <- tracing paid, NO table produced
#     --cov=cosa                              10.19s   <- tracing paid, table produced
# So the flag saves ~9.4s of rendering at cosa scope (49,542 statements, branch mode) and
# ~6.3s at the full repo scope (61,370 statements, line mode) — a fixed end-of-run cost that
# does not scale with test count. Against the unit tier's measured 698s that is ~1.3%. The
# number is worth the second and a bit; that is why this warns instead of staying quiet.
#
# WHY A DETECTOR RATHER THAN A BAN ON THE FLAG. --no-cov-on-fail is only one way to end a
# run with no number. A --cov scoped to a module the run never imports reports "No data to
# report" and prints no table (reproduced while measuring the above). A --cov-report routed
# only to a file, or a pytest-cov missing from the interpreter, look identical to the
# reader. So this asserts the PROPERTY worth having — a number reached you — instead of the
# absence of one flag, and names the flag as the cause only when it was actually passed.
#
# It never changes the exit status. It reports beside the result, like the diagnosis above.

# True when the command asks for coverage at all.
_cov_requested() {
    local a
    for a in "$@"; do
        case "$a" in --cov|--cov=*|--cov-report|--cov-report=*|--cov-config=*) return 0 ;; esac
    done
    return 1
}

# True when --no-cov-on-fail is in the command — the one cause that can be named exactly.
_cov_suppressed_on_fail() {
    local a
    for a in "$@"; do [ "$a" = "--no-cov-on-fail" ] && return 0; done
    return 1
}

# True when the captured output actually contains a coverage report. pytest-cov's terminal
# report opens with a `coverage: platform ...` separator and ends in a TOTAL row; either one
# present means a number reached the reader.
_cov_table_present() {
    grep -qE 'coverage: platform|^TOTAL[[:space:]]' "$1" 2>/dev/null
}

_warn_if_coverage_went_blind() {
    local capture="$1" status="$2"; shift 2
    _cov_requested "$@"           || return 0
    [ "$status" -eq 0 ]           && return 0   # a green run reports; nothing to warn about
    _cov_table_present "$capture" && return 0

    {
        echo ""
        echo "================================================================================"
        echo "NO COVERAGE NUMBER WAS PRODUCED BY THIS RUN  (row f8e5215b)"
        echo "--------------------------------------------------------------------------------"
        echo "Coverage was requested, the run exited $status, and no coverage table appeared in"
        echo "the output. This run measured nothing you can cite. An absent table looks exactly"
        echo "like never having asked for coverage, which is why this says so out loud."
        if _cov_suppressed_on_fail "$@"; then
            echo ""
            echo "  Cause: --no-cov-on-fail was passed. pytest-cov drops the whole report when"
            echo "         any test fails, so a tier with tolerated red never reports a number."
            echo "  Fix:   re-run the same command WITHOUT --no-cov-on-fail. Measured cost of"
            echo "         the report on this repo: ~6-10s, fixed, whatever the test count."
        else
            echo ""
            echo "  --no-cov-on-fail was NOT passed, so the cause is something else: a --cov"
            echo "  scoped to code this run never imported (pytest-cov then warns \"No data to"
            echo "  report\" and prints no table), a --cov-report routed only to a file, or"
            echo "  pytest-cov missing from this interpreter."
        fi
        echo ""
        echo "Do not report coverage as verified from this run."
        echo "================================================================================"
        echo ""
    } >&2
}

run_pytest_with_diagnosis() {
    local capture status python_bin module_path

    # Refuse a coverage run while another suite is live (row e2099400). Returns non-zero
    # ONLY for a refusal; a run with no --cov, or a clear box, falls straight through.
    if declare -F guard_contended_coverage >/dev/null 2>&1; then
        guard_contended_coverage "$@" || return $?
    fi

    capture="$( mktemp -t pytest-collection-XXXXXX.log 2>/dev/null )"

    # No temp file available: run pytest plainly rather than not at all. A diagnostic that
    # can block a test run is worse than the silence it removes.
    if [ -z "$capture" ]; then
        # No capture file: neither the collection diagnosis nor the coverage-blindness check
        # (row f8e5215b) can read this run's output. Name the guarantees that are off rather
        # than running degraded in silence — that silence is the defect both checks are about.
        echo "pytest-with-diagnosis: no temp file available — collection diagnosis and the" >&2
        echo "  coverage-blindness check are DISABLED for this run." >&2
        "$@"
        return $?
    fi

    # Keep colour for a human terminal: `tee` makes stdout a pipe, and pytest drops colour
    # on a pipe. PY_COLORS is used rather than injecting --color=yes because the caller's
    # command may be several words ("python3 -m pytest") and there is no reliable place in
    # it to insert a flag — and because an explicit --color=no still wins over the env var.
    # The escape codes it puts in the capture are stripped by the diagnosis module.
    local color_env=()
    if [ -t 1 ]; then color_env=( "PY_COLORS=1" ); fi

    # NOT `set -o pipefail` on purpose: without it the pipeline's status is tee's, so a
    # failing pytest cannot trip a caller's `set -e` before we have reported the code
    # ourselves. PIPESTATUS[0] carries pytest's real status.
    env "${color_env[@]}" "$@" 2>&1 | tee "$capture"
    status=${PIPESTATUS[0]}

    # 0 and 1 are a real pass and a real failure — both RAN, so neither is this tool's
    # business. Every other code is asked about; the module answers with silence for the
    # ones that are not collection errors (3 internal error, 124 timeout, 130 Ctrl-C...).
    if [ "$status" -ne 0 ] && [ "$status" -ne 1 ]; then
        python_bin="$( _diagnosis_python )"
        module_path="${LUPIN_ROOT}/src/cosa/utils/pytest_collection_diagnosis.py"
        if [ -f "$module_path" ]; then
            "$python_bin" "$module_path" \
                --exit-code "$status" \
                --output-file "$capture" \
                --project-root "$LUPIN_ROOT" || true
        fi
    fi

    _warn_if_coverage_went_blind "$capture" "$status" "$@"

    rm -f "$capture"
    return $status
}
