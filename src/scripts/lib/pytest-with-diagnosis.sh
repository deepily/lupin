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

run_pytest_with_diagnosis() {
    local capture status python_bin module_path
    capture="$( mktemp -t pytest-collection-XXXXXX.log 2>/dev/null )"

    # No temp file available: run pytest plainly rather than not at all. A diagnostic that
    # can block a test run is worse than the silence it removes.
    if [ -z "$capture" ]; then
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

    rm -f "$capture"
    return $status
}
