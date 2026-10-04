#!/bin/bash
# What may a green run CLAIM? Answer pytest's own account of it, never the adjective.
#
# WHY THIS EXISTS. run-e2e-ui-tests.sh printed "✓ All E2E UI tests passed!" on exit 0
# unconditionally and never echoed its args. All three 2026-09-24 reports under
# io/test-suite/ were `-k` filtered — 891 deselected, 33 / 43 / 45 selected — and two of
# them carry that banner verbatim. So the strongest-sounding line in the whole log, the one
# a reader skims to, asserted a property of 924 tests on the evidence of 33. Nothing in the
# output contradicted it: the selected/deselected line sits hundreds of lines above, and the
# args that caused the narrowing were never printed at all.
#
# THE PREDICATE, not an enumeration of flags. "Was this the whole suite?" is a question
# about what pytest DID, and pytest already answers it in its summary line. Sniffing the
# argv for `-k` restates the rule instead of asking the gate, and it is wrong in both
# directions — measured 2026-09-27, real pytest, four arms:
#
#     -k alpha                          -> "1 passed, 2 deselected"   narrowed
#     -m 'not slow'                     -> "2 passed, 1 deselected"   narrowed
#     --deselect <nodeid>               -> "2 passed, 1 deselected"   narrowed
#     -k 'test_'   (matches everything) -> "3 passed"                  NOT narrowed
#
# The fourth arm is the one that settles the design. A flag-sniffer calls that run filtered
# and cries wolf; pytest calls it a full run, because it was one. One signal — pytest's own
# deselected count — covers every spelling of narrowing, including spellings nobody has
# invented yet, and stays quiet when a filter narrowed nothing.
#
# TWO THINGS THE DESELECTED COUNT CANNOT SEE, so they are asked separately:
#
#   --half a|b   The partition is not a filter. pytest is handed exactly the files in
#                half-<a|b>.txt, collects all of them, and deselects nothing — a half run
#                reports a clean "N passed" and is still half a suite. The RUNNER knows,
#                so the runner passes it in.
#   zero tests   `--collect-only` exits 0 having run nothing ("3 tests collected"), and a
#                selector matching nothing exits with "no tests ran". Both are exit 0 and
#                neither is a pass of anything.
#
# WHAT IS DELIBERATELY *NOT* CHECKED HERE: narrowing by path. Through run-e2e-ui-tests.sh it
# is unreachable — the script always supplies its own collection paths and appends the
# caller's args after them, so an extra path widens the run or is a no-op. A bare
# `pytest <nodeid>` DOES narrow without reporting a deselection (measured: "1 passed", no
# deselected line), so a future caller that lets the user REPLACE the paths must re-derive
# this, not inherit it. Named rather than bridged.
#
# Created: 2026-09-27 (Tiberius, on Mr. Radio's assignment — the banner half of the
#          io/test-suite baseline finding)

# Strip ANSI colour so a summary line captured from a terminal parses the same as one
# captured from a pipe. pytest colours its summary, and PY_COLORS=1 is set by
# pytest-with-diagnosis.sh whenever stdout is a tty.
_run_scope_strip_ansi() {
    sed -e 's/\x1b\[[0-9;]*[a-zA-Z]//g'
}

# Echo pytest's LAST summary line from a captured run, with decoration and colour removed.
# Echoes nothing when no summary line is present — which is a THIRD answer, distinct from
# "full" and "partial", and the callers below must not collapse it into either. A run whose
# output was lost (no capture, a crash before the summary, a timeout kill) cannot be
# certified as a full suite, and must not be.
#
# The shape matched is pytest's own: a terminal-summary line always carries a duration
# (`in 1.23s`) and at least one outcome word. `=` decoration from non-quiet mode is
# tolerated because the match is a substring, not an anchor.
run_scope_summary_line() {
    local capture="$1"
    [ -n "$capture" ] || return 0
    [ -f "$capture" ] || return 0
    _run_scope_strip_ansi < "$capture" \
        | grep -E '(passed|failed|error|errors|skipped|deselected|xfailed|xpassed|warnings?|no tests ran|tests? collected)[^|]*in [0-9]+\.[0-9]+s' \
        | tail -1 \
        || true   # no summary line is the THIRD answer ("unknown"), not a failure: under `set -eo pipefail` grep's 1 would kill the caller (row cb64a4b1)
}

# Echo the number pytest deselected, or nothing when the line does not say.
# ⚠️ ABSENT AND ZERO ARE DIFFERENT ANSWERS. pytest omits the clause entirely when it
# deselected nothing, so "no deselected clause in a real summary line" means zero — but "no
# summary line at all" means unknown. run_scope_verdict below is what keeps those apart;
# this function reports only what the line it was given says.
run_scope_deselected_count() {
    local line="$1"
    # 🔴 `|| true`: the last grep exits 1 on a line with no "N deselected" clause, which is every fully
    # green unfiltered run. Under the caller's `set -e` the assignment `x="$( ... )"` then killed the runner
    # before its banner and before `exit $PYTEST_EXIT_CODE`: a green e2e half was recorded as exit 1 (row cb64a4b1).
    # Empty output still means "no clause" (zero); only the exit status is neutralised.
    echo "$line" | grep -oE '[0-9]+ deselected' | head -1 | grep -oE '^[0-9]+' || true
}

# Echo how many tests pytest actually reported an outcome for: passed + failed + error(s) +
# skipped + xfailed + xpassed. This is the count a banner may speak about.
run_scope_selected_count() {
    local line="$1" total=0 n
    for n in $( echo "$line" | grep -oE '[0-9]+ (passed|failed|errors?|skipped|xfailed|xpassed)' | grep -oE '^[0-9]+' ); do
        total=$(( total + n ))
    done
    echo "$total"
}

# The verdict: full | partial | empty | unknown.
#
#   full     pytest collected everything it was given, deselected nothing, ran at least one
#            test, and the runner did not ask for a half. Only this may say "all".
#   partial  something narrowed the run — a deselection, or a half.
#   empty    exit 0 with no test outcomes at all (--collect-only, or a selector that matched
#            nothing). A pass of zero tests is not a pass.
#   unknown  no parseable summary line reached us. NOT a synonym for full.
#
# Args: <summary line> <half, may be empty>
run_scope_verdict() {
    local line="$1" half="$2" deselected selected

    [ -n "$line" ] || { echo "unknown"; return 0; }

    deselected="$( run_scope_deselected_count "$line" )"
    selected="$( run_scope_selected_count "$line" )"

    # A half is partial by construction, whatever pytest says about deselection — it is
    # handed half the files and honestly reports collecting all of them.
    if [ -n "$half" ];                                    then echo "partial"; return 0; fi
    if [ "$selected" -eq 0 ];                             then echo "empty";   return 0; fi
    if [ -n "$deselected" ] && [ "$deselected" -gt 0 ];   then echo "partial"; return 0; fi

    echo "full"
}

# Print the result banner for a finished run. This REPLACES the old unconditional
# "✓ All E2E UI tests passed!" on the green path; the red path is unchanged, because a red
# run claims nothing and so cannot overclaim.
#
# Args: <suite label> <exit code> <summary line> <half> <the args the run was given...>
#
# ⚠️ THE ARGS ARE ECHOED ON EVERY PATH, INCLUDING THE FULL ONE. Not printing them is what
# made the 2026-09-24 reports unreadable after the fact: the banner was wrong and the
# evidence that it was wrong had never been written down. A reader who can see the argv can
# check this function's verdict instead of trusting it.
report_run_scope() {
    local label="$1" status="$2" line="$3" half="$4"; shift 4
    local verdict deselected selected

    verdict="$( run_scope_verdict "$line" "$half" )"
    deselected="$( run_scope_deselected_count "$line" )"
    selected="$( run_scope_selected_count "$line" )"
    [ -n "$deselected" ] || deselected=0

    # Colours: defined by the caller when it has them, defaulted here so this file is
    # sourceable and testable on its own.
    local green="${GREEN:-}" red="${RED:-}" yellow="${YELLOW:-}" nc="${NC:-}"

    echo "Invoked with: ${*:-<no extra args>}${half:+   [--half $half]}"
    if [ -n "$line" ]; then echo "pytest said:  $line"; fi

    if [ "$status" -ne 0 ]; then
        echo -e "${red}✗ $label failed (exit code: $status)${nc}"
        return 0
    fi

    case "$verdict" in
        full)
            echo -e "${green}✓ All $label passed!${nc}"
            ;;
        partial)
            # The wording is deliberately NOT a variant of "all ... passed". A reader
            # skimming for that phrase must not find it here, because the phrase is the
            # thing that was false.
            echo -e "${yellow}✓ PARTIAL RUN passed — $selected test(s) selected, $deselected deselected.${nc}"
            echo -e "${yellow}  THIS IS NOT THE WHOLE $label SUITE. It says nothing about the tests that did not run.${nc}"
            ;;
        empty)
            echo -e "${yellow}⚠ NO TESTS RAN. Exit 0 here is not a pass — nothing was executed.${nc}"
            ;;
        unknown)
            echo -e "${yellow}⚠ EXIT 0, but pytest's summary line was not found in the output, so the${nc}"
            echo -e "${yellow}  scope of this run is UNKNOWN. Do not report it as a full suite.${nc}"
            ;;
    esac
}
