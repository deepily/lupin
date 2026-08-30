#!/bin/bash
# Did a coverage tier actually MEASURE, or did it never get to run? — row `e2099400`.
#
# 🔴 WHY THIS EXISTS. Measured 2026-08-30. run-coverage-gate.sh --run-tiers invoked its two
# tiers with a bare `bash …` and captured NEITHER exit status (the script sets -o pipefail
# but not -e, so both statuses were discarded and it rendered the report regardless). A peer
# suite arrived between the tiers, the contention guard correctly refused the cosa tier with
# exit 6, and the gate published:
#
#     TOTAL 70,842 statements / 20,045 missing = 70.68%   ->   "COVERAGE GATE FAILED"
#
# against 95.14% from the identical tree an hour earlier. Nothing had regressed: 8,769 cosa
# tests simply never ran. The verdict named a percentage and a floor and said nothing about
# a tier having been refused.
#
# ⚠️ THE EXISTING NO-DATA BRANCH CANNOT CATCH THIS, and that is the whole point. It fires
# only when the data file holds NOTHING. One tier of two is not nothing — it is a plausible
# database with a plausible number on top, which is the harder case and the one left open.
#
# ⚠️ AND IT FAILED RED ONLY BY LUCK. Which direction a partial run lands depends on WHICH
# tier goes missing, and the gate cannot tell you which happened. A red gets investigated; a
# green does not.
#
# 🔴 THE DISTINCTION THAT MAKES THIS CORRECT: A TIER WITH FAILING TESTS STILL MEASURED.
# pytest exit 1 means tests ran and some failed — the coverage data is complete and the
# number is real. The verified 95.14% baseline was earned by a run with 14 pre-existing
# failures, so treating "non-zero" as "did not measure" would have thrown away the correct
# answer. Only a status meaning COULD NOT RUN makes a measurement incomplete:
#
#     0  all tests passed                    -> MEASURED
#     1  tests ran, some failed              -> MEASURED   (this is the one that matters)
#     2  interrupted        3  internal error
#     4  usage error        5  nothing collected
#     6  refused: box contended (guard-contended-coverage.sh)
#     7  refused: could not read the process table
#     anything else                          -> DID NOT MEASURE
#
# The same reasoning is already written down for mutation harnesses in CLAUDE.md — "a
# non-zero exit is not a red test; rc 4/5 mean it could not RUN the node". This is that
# lesson applied to a whole tier instead of a single node.

# True when a tier's exit status means its coverage data is complete enough to render.
#
# Requires:
#   - $1 is the tier's exit status, as an integer
# Ensures:
#   - returns 0 for status 0 and 1 (ran; possibly with failures)
#   - returns 1 for every other status (never ran, or died before finishing)
tier_measured() {
    case "${1:-}" in
        0|1) return 0 ;;
        *)   return 1 ;;
    esac
}

# A human-readable reason a tier did not measure, for a verdict that names its own cause.
#
# Requires:
#   - $1 is the tier's exit status
# Ensures:
#   - prints a one-line explanation; never empty, even for an unrecognised status
tier_not_measured_reason() {
    case "${1:-}" in
        2) echo "interrupted before it finished" ;;
        3) echo "internal error, or the venv pytest could not be resolved" ;;
        4) echo "pytest usage error — the tier never ran a test" ;;
        5) echo "collected no tests at all" ;;
        6) echo "REFUSED: another suite was running on this box (contention guard)" ;;
        7) echo "REFUSED: could not tell whether another suite was running" ;;
        *) echo "exited $1, which is not a status a completed tier produces" ;;
    esac
}
