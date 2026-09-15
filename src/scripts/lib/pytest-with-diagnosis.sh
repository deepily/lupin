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

# True when the command explicitly asked for NO terminal report: a bare `--cov-report=` with
# an empty value. This is not a mistake and not blindness — it is what this repo's own
# `coverage_opt_in_flags()` emits for every tier (row e2099400), because the tiers APPEND to
# one data file and the number is rendered ONCE afterwards by run-coverage-gate.sh.
#
# Without this predicate the block below fires on the repo's own sanctioned tier invocation
# the moment that tier has any red, and tells the reader "this run measured nothing" while
# the run has in fact measured the whole frame. Measured 2026-08-30: the exact tier flags
# against one red test printed the block while 704 measured files / 204 KB sat in
# COVERAGE_FILE. Two seats hit it and read it as a defect in their own run.
# How many files did this run actually MEASURE? Answers the DATA FILE, not a flag.
#
# WHY THIS EXISTS (Chloe's F1 against the first cut of this fix, 2026-08-31). That cut
# printed "Measurement still happened." on the suppressed branch WITHOUT LOOKING -- which is
# the exact charge this commit levels at the old block, pointing the other way. Measured:
# `--cov=<a scope the run never imports> --cov-report=` gives ZERO measured files while the
# note claimed measurement happened. A false alarm gets investigated; a false reassurance
# does not, so that is the worse direction of the two.
#
# Echoes a count on stdout, or NOTHING when it cannot tell (COVERAGE_FILE unset, file
# absent, coverage not importable). "I cannot tell" and "zero" are DIFFERENT answers and the
# callers below must not collapse them -- that collapse is this whole file's subject.
#
# COUNTS FILES WITH AT LEAST ONE EXECUTED LINE, NOT `measured_files()` (review RB-1 on
# 638f6408). With the tier's own flags, pyproject's directory `source` list makes coverage
# enter every unexecuted file in the frame with an EMPTY line set, so `measured_files()`
# lists the whole frame whether or not anything ran. Measured: a red suite importing nothing
# from the frame, under `--cov --cov-report= --cov-fail-under=0 --cov-append`, wrote 735
# files listed / 0 executed, and the note below said "Measurement did happen -- 735 files".
# `lines( f )` is the executed set, so a non-empty one is what "measured" actually means.
_cov_measured_files() {
    [ -n "${COVERAGE_FILE:-}" ] || return 0
    [ -f "$COVERAGE_FILE" ]     || return 0
    "$( _diagnosis_python )" - "$COVERAGE_FILE" <<'PYEOF' 2>/dev/null
import sys
try:
    import coverage
    d = coverage.CoverageData( sys.argv[ 1 ] ); d.read()
    print( sum( 1 for f in d.measured_files() if d.lines( f ) ) )
except Exception:
    pass
PYEOF
}

# True when this run APPENDS to a shared data file -- the tier shape. It is what decides
# whether anything will render the number later, and therefore which remedy is honest.
_cov_appending() {
    local a
    for a in "$@"; do [ "$a" = "--cov-append" ] && return 0; done
    return 1
}

_cov_report_suppressed() {
    local a
    for a in "$@"; do [ "$a" = "--cov-report=" ] && return 0; done
    return 1
}

_warn_if_coverage_went_blind() {
    local capture="$1" status="$2"; shift 2
    _cov_requested "$@"           || return 0
    [ "$status" -eq 0 ]           && return 0   # a green run reports; nothing to warn about
    _cov_table_present "$capture" && return 0

    # A table suppressed ON PURPOSE is not blindness. Say what is true — the run measured,
    # it simply did not RENDER — and point at the step that does. Still a note, because you
    # genuinely cannot cite a number from THIS run; just not an alarm about a defect.
    #
    # ⚠️ `--no-cov-on-fail` WINS OVER THIS, AND THE ORDER IS THE WHOLE POINT. A run carrying
    # BOTH flags is the named cause with a named remedy, so it keeps the full block.
    #
    # WHY A DATA-FILE CHECK CANNOT REPLACE THIS FLAG CHECK — measured, and here is the number
    # rather than the word "measured". The tier flags plus `--no-cov-on-fail`, against a suite
    # with one red, still wrote **249,856 bytes / 704 measured files** to COVERAGE_FILE. So the
    # data file is NON-EMPTY in both cases and cannot tell them apart; only the flag can.
    # Reproduce:
    #     COVERAGE_FILE=/tmp/probe.dat .venv/bin/pytest <a red suite> -q \
    #       --cov --cov-report= --cov-fail-under=0 --cov-append --no-cov-on-fail
    #     python -c "import coverage;d=coverage.CoverageData('/tmp/probe.dat');d.read();\
    #                print(len(list(d.measured_files())))"    # -> non-zero
    #
    # ⚠️ THE FIRST VERSION OF THIS COMMENT SAID "measured" ON THE STRENGTH OF A PRECONDITION
    # ASSERTION FAILING, WHICH SHOWED ONLY THAT THE COUNT WAS NOT ZERO — I never printed it.
    # That is an inference from a flag dressed as a measurement, and it was caught in review.
    # The figure above is the actual reading.
    #
    # A first cut of this branch also sat ABOVE the `--no-cov-on-fail` check and silently
    # swallowed the one explanation in here that tells the reader exactly what to re-run.
    if _cov_report_suppressed "$@" && ! _cov_suppressed_on_fail "$@"; then
        local measured; measured="$( _cov_measured_files )"
        {
            echo ""
            echo "  note: no coverage table here, because --cov-report= asked for none. That is"
            echo "        this repo's tier default (row e2099400): tiers APPEND to COVERAGE_FILE"
            echo "        and src/tests/run-coverage-gate.sh renders the number once, afterwards."
            if   [ -z "$measured" ]; then
                echo "        Whether anything was MEASURED is unknown here -- COVERAGE_FILE is unset"
                echo "        or unreadable, so this run cannot tell you either way. Check the gate."
            elif [ "$measured" -eq 0 ]; then
                echo ""
                echo "  AND THE DATA FILE IS EMPTY: 0 files measured. A suppressed table is normal;"
                echo "      measuring NOTHING is not. Nothing will be rendered later either, so this"
                echo "      is a real hole rather than the tier's deferred render. Usual cause:"
                echo "      --cov scoped to code this run never imported."
            else
                echo "        Measurement did happen -- $measured files are in COVERAGE_FILE."
            fi
            echo "        Cite the gate's number, never this run's."
            echo ""
        } >&2
        return 0
    fi

    {
        echo ""
        echo "================================================================================"
        echo "NO COVERAGE NUMBER WAS PRODUCED BY THIS RUN  (row f8e5215b)"
        echo "--------------------------------------------------------------------------------"
        # CHLOE's F2, second cut -- and the placement is the whole fix. The headline used to
        # read "This run measured nothing you can cite" UNCONDITIONALLY, with the correction
        # printed fifteen lines below it and only inside the --no-cov-on-fail arm. Both
        # sentences were then true of the same block, and a reader who stops at the headline
        # -- which is what a headline is FOR -- carries the one this branch already knows to
        # be false. An addition below a wrong sentence does not correct it; it outranks it
        # only for whoever reads that far. Decide the fact BEFORE the headline and say the
        # true sentence FIRST.
        local measured_any; measured_any="$( _cov_measured_files )"
        echo "Coverage was requested, the run exited $status, and no coverage table appeared in"
        if [ -n "$measured_any" ] && [ "$measured_any" -gt 0 ]; then
            echo "the output. BUT THE DATA SURVIVED: $measured_any files are in COVERAGE_FILE."
            echo "The REPORT was dropped, the MEASUREMENT was not. No number from THIS output is"
            echo "citable; the data is on disk, and whether anything renders it is the next line."
        else
            echo "the output. This run measured nothing you can cite. An absent table looks exactly"
            echo "like never having asked for coverage, which is why this says so out loud."
        fi
        if _cov_suppressed_on_fail "$@"; then
            echo ""
            echo "  Cause: --no-cov-on-fail was passed. pytest-cov drops the REPORT when any test"
            echo "         fails, so a tier with tolerated red never PRINTS a number."
            # WHICH REMEDY IS RIGHT DEPENDS ON WHETHER ANYTHING WILL RENDER THIS LATER, AND
            # THAT IS THE TIER SHAPE (--cov-append), NOT MERELY THE DATA EXISTING. An earlier
            # cut of this branch keyed on "data survived" alone and told an AD-HOC run not to
            # re-run -- but no gate renders an ad-hoc data file, so that advice stranded the
            # reader with a number nothing would ever print. Caught by the original pin
            # test_the_block_names_the_flag_when_the_flag_is_what_caused_it, which is exactly
            # what a true positive is for.
            if _cov_appending "$@"; then
                echo "  Fix:   under the tier architecture, do NOT re-run. The data is already"
                echo "         appended and src/tests/run-coverage-gate.sh renders it; re-running"
                echo "         buys a number that is already on disk at the price of a full tier."
            else
                echo "  Fix:   re-run the same command WITHOUT --no-cov-on-fail. Nothing renders"
                echo "         an ad-hoc data file later, so the number has to come from a report."
                echo "         Measured cost on this repo: ~6-10s, fixed, whatever the test count."
            fi
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
