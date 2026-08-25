#!/usr/bin/env bash
#
# Runs the TypeScript test suite under c8 with an ENFORCED coverage threshold.
#
# WHY THIS SCRIPT EXISTS (board row 36e479ed): CLAUDE.md's 100% COVERAGE
# MANDATE names TypeScript explicitly — "100% coverage, lines AND branches AND
# functions, TypeScript via c8 --100". Until this script, nothing invoked it.
# No runner, no test-type, no hook, no CI. The mandate's Python half had real
# teeth via --cov-fail-under=100; the TypeScript half was enforced by a human
# remembering to type a command, which meant a TS regression landed silently.
#
# The threshold below is the enforcement. `--check-coverage` makes c8 exit
# non-zero when any of the four numbers falls short, which is what turns this
# from a report into a gate.
#
# Usage:
#   run-typescript-tests.sh                 # full suite at the enforced threshold
#   run-typescript-tests.sh --report-only   # measure, never fail on coverage
#
# Called by TestSuiteJob when test_types="typescript".
#
# VENUE — :8000, scheduled. Measured 2026-07-21: 2,245 tests in 8m19s, well
# past the 2-minute :7999 ceiling in CLAUDE.md § TESTING VENUES. It mutates no
# persistent state, so the routing is runtime, not blast radius.

set -uo pipefail

# Resolve project root (script is at src/tests/run-typescript-tests.sh → up TWO levels)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT" || exit 1

# Coverage thresholds — the mandate, expressed as numbers a process can act on.
# Statements is included because c8's --100 shorthand covers it and dropping it
# would let a whole uncovered statement class pass a "100%" gate.
THRESHOLD_LINES=100
THRESHOLD_BRANCHES=100
THRESHOLD_FUNCTIONS=100
THRESHOLD_STATEMENTS=100

CHECK_COVERAGE="--check-coverage"
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --report-only) CHECK_COVERAGE="" ;;
        *)             PASSTHROUGH_ARGS+=( "$arg" ) ;;
    esac
done

# Instrumented source: the three TypeScript entry trees named by the tsconfigs
# (tsconfig.json, tsconfig.nav.json, tsconfig.diagnostic.json). `--all` counts
# files with ZERO tests — without it, an entirely untested module is invisible
# to the percentage, which is the same silence this gate exists to end.
#
# ===========================================================================
# THE DENOMINATOR EXCLUSIONS — RATIFIED BY RICK 2026-07-21 (gate 07a5460d)
# ===========================================================================
# Answered LIVE, not by timeout — and the timeout default was NO, so this is a
# decision, not a fallthrough.
#
# WHAT IT COST, MEASURED BEFORE THE RULING (full suite under c8, 2026-07-21):
#     2,245 / 2,245 tests pass
#     Statements 93.19% (23,889/25,633) · Lines 93.19%
#     Branches   99.94% (5,145/5,148)   · Functions 99.82% (1,754/1,757)
# The mandate was not merely unenforced — it was UNMET. The ENTIRE 6.81%
# statement gap is the three categories below, at 0% each; nothing else in the
# instrumented trees was under 100%. The numbers are recorded here so the next
# reader sees what was excluded AND what excluding it bought, without re-running
# a nine-minute suite to find out.
#
# Each exclusion carries its own dated reason. An exclusion without a reason is
# a narrowed denominator nobody can audit — and the only thing that makes a
# coverage number mean anything is that nobody adjusted the denominator to
# reach it.
#
#   --exclude='**/boot.ts'   2026-07-21 (Rick, 07a5460d): browser ENTRY POINTS
#       (multiplexer, nav, diagnostic). Imported by no test by construction —
#       importing one executes page bootstrap against a live DOM. Prior art in
#       this repo already excluded boot.ts explicitly before the mandate existed.
#
#   --exclude='**/types.ts'  2026-07-21 (Rick, 07a5460d): TYPE-ONLY modules.
#       They emit no runtime statements, so they can only ever score 0% and
#       cannot be covered by any test that could be written.
#
#   --exclude='**/index.ts'  2026-07-21 (Rick, 07a5460d): BARREL re-exports
#       (transport, render, stores). Pure `export ... from` with no logic; the
#       symbols they forward are themselves covered at their definition sites.
#
# ⚠️ IF YOU ADD A FOURTH EXCLUSION: it needs its own dated ruling on this list.
# Widening the denominator's holes is how a 100% gate becomes decorative, and
# the diff that does it must be one a reviewer can see and question.
#
# ===========================================================================
# DOCUMENTED EXEMPTION — legacy notifications.js is NOT in this gate, ON PURPOSE
# ===========================================================================
# Ruling: Mr. Radio 2026-08-03 (row f8abf4b6, Option 2). This is NOT a fourth
# --exclude — it changes no number below. It is the written record that a large
# legacy file sits OUTSIDE this gate deliberately, so the next reader does not
# mistake its absence for "covered" or its ad-hoc 0/0 for "tested, zero lines".
#
# THE FILE: src/lupin_app/static/js/notifications.js (~20,900 lines). Plain
# browser JS, in NO tsconfig, so it never matches the three --include trees
# above and is not in this gate's denominator at all.
#
# WHY IT CANNOT BE INSTRUMENTED HERE: every test under
# src/tests/unit/notifications_js/ loads it by slicing the source string and
# running it through vm.runInThisContext (see e.g.
# reading_pane_scroll_anchor.test.ts:40). c8 instruments modules it sees through
# the require/import graph; a vm.runInThisContext'd string is not in that graph,
# so c8 reports 0/0 for it EVEN IF you force it into --include. That ad-hoc 0/0
# (measured 2026-08-03) is the "silence" this note exists to replace — the
# defect Rio filed was the silence, not the uncovered lines.
#
# WHAT ITS REAL GATE IS: the behavioural unit tests in
# src/tests/unit/notifications_js/ (DOM assertions under happy-dom + direct
# method calls — they PASS, they just emit no coverage number) PLUS Rachel's
# :8000 Playwright E2E for the real click-through. Not "untested" — measured by
# instruments c8 cannot read.
#
# DO NOT "fix" this by adding a --include for it: that manufactures a 0% red
# gate with no owner and no path to 100%, which is exactly the option (1) that
# was weighed and rejected. The forward direction (Option 3, standing) is to
# extract NEW logic into small importable TS modules — as done for the
# multiplexer — so the un-instrumentable legacy surface shrinks over time
# instead of growing.
#
# NOTE for src/cosa/repo/gate_reachability.py: the `src/tests/**` glob below is
# a GLOB ROOT, not a suite target. That detector's path-token regex rejects it
# on purpose; see the comment on _PATH_TOKEN_RE.
# ── THE RUNNER IS CAPPED, AND THE CAP IS NOT WHY IT IS SAFE ──────────────────
# 2026-08-23 (Clayton found it, Maria verified, Mr. Radio landed it). This line
# used to end in a bare `npx tsx --test "src/tests/**/*.test.ts"` — no timeout, no
# concurrency cap. That is the EXACT command shape that got a session killed by
# systemd-oomd at 13:02:50 that day: node's test runner fans out one worker per
# core (32 here), each tsx worker carrying an esbuild service — 52 processes.
#
# package.json's `test` script was capped the same day; this script is the OTHER
# door into the same 119 files and it was missed. TestSuiteJob wraps its own
# 1500s timeout around this script (SUITE_TIMEOUTS_SECONDS["typescript"]), but a
# HAND-RUN had nothing, and nothing anywhere capped fan-out.
#
# 🔴 Read this before trusting the cap: a second seat died at 16:06:34 the same
# day running ONE file at --test-concurrency=1 under `timeout 300`. Caps and
# timeouts did NOT save it. The allocator is still unidentified (row d84839ae),
# and 77 of the 119 *.test.ts files load a DOM via @happy-dom/global-registrator.
# So this cap bounds the blast radius; it does not make the suite safe. Treat any
# run of this script as a blast-radius action: announce first, one at a time
# across the whole fleet. Full survey:
#   src/rnd/v0.2.0/2026.08.23-typescript-test-runner-oom-hazard.md
TS_TIMEOUT_SECS="${TS_TIMEOUT_SECS:-1400}"      # under TestSuiteJob's own 1500s
TS_CONCURRENCY="${TS_CONCURRENCY:-4}"           # matches package.json's cap

# ── THE LANE (row 32c58572 follow-up) ────────────────────────────────────────
# The `timeout` above is kept for its SIGTERM-on-a-cooperating-process behaviour
# but it is NOT the cap: timeout(1) signals its direct child only, and node
# blocked in a synchronous GC frame never services the signal — a measured run
# under `timeout 300` burned 388 seconds. The enforcing ceiling is the cgroup.
source "$PROJECT_ROOT/src/scripts/lib/jstest-slice.sh"
JSTEST_RUNTIME_MAX="${JSTEST_RUNTIME_MAX:-$(( TS_TIMEOUT_SECS + 100 ))}"

jstest_slice_exec timeout "$TS_TIMEOUT_SECS" npx c8 \
    --all \
    $CHECK_COVERAGE \
    --lines      "$THRESHOLD_LINES" \
    --branches   "$THRESHOLD_BRANCHES" \
    --functions  "$THRESHOLD_FUNCTIONS" \
    --statements "$THRESHOLD_STATEMENTS" \
    --include='src/lupin_app/static/js/multiplexer/**/*.ts' \
    --include='src/lupin_app/static/js/nav/**/*.ts' \
    --include='src/lupin_app/static/js/diagnostic/**/*.ts' \
    --exclude='**/*.test.ts' \
    --exclude='**/boot.ts' \
    --exclude='**/types.ts' \
    --exclude='**/index.ts' \
    --reporter=text-summary \
    --reporter=text \
    node --test-concurrency="$TS_CONCURRENCY" --import tsx \
         --test "src/tests/**/*.test.ts" "${PASSTHROUGH_ARGS[@]}"
