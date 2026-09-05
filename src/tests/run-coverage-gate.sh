#!/bin/bash
# The Python coverage gate — the step that makes pyproject's `fail_under` mean something.
#
# WHY THIS EXISTS (row e2099400, 2026-08-29). The 100% COVERAGE MANDATE had teeth on the
# TypeScript side (run-typescript-tests.sh runs c8 --check-coverage at 100) and NONE on the
# Python side: pytest.ini's addopts carried no --cov, no runner passed one, TestSuiteJob
# injected none, and run-all-tests.sh mentioned coverage only in a comment. `fail_under`
# sat in pyproject and fired only when a human typed --cov by hand.
#
# WHAT IT CHECKS, and both halves are load-bearing:
#   1. THE FLOOR — the measured total against pyproject's `fail_under`.
#   2. THE FRAME — that every .py the frame CLAIMS is actually in the report. A frame that
#      silently stops covering a directory reports a HIGHER number, because unmeasured code
#      is usually the least-tested code. Measured 2026-08-29: 13 files / 1,234 statements
#      under src/scripts sat outside a `source` entry that reads as inclusive. Checking the
#      floor without checking the frame certifies a percentage over an unknown denominator.
#
# USAGE
#   As a pyramid step, after unit and cosa have appended to one data file:
#       LUPIN_COVERAGE=1 COVERAGE_FILE=<isolated> src/tests/run-coverage-gate.sh
#   Standalone, running the tiers itself:
#       src/tests/run-coverage-gate.sh --run-tiers
#
# EXIT CODES - each is a DIFFERENT cause and none is a synonym for another:
#   0  measured, and at or above the floor
#   1  floor or frame breach, OR the floor this run would enforce is not the branch's
#   2  INCONCLUSIVE - a tier did not run, so the denominator is short and no number is owed
#   3  no interpreter beside the resolved pytest
#   4  REFUSED - the tree MOVED while this run was measuring it (row 73ebccb1)
#   6  refused/contended, from the tier-measured contract

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# ⚠️ PLACED HERE, BEFORE THE VENV RESOLUTION, AND THAT POSITION IS THE POINT OF A BRACKET.
# The first cut sat further down, just above the tier block — which left the span in pyramid
# mode measuring MILLISECONDS (measured: both stamps landed in the same second,
# 19:04:37..19:04:37), so it could not have caught anything and a reader would still have
# been handed `run-span=unmoved` as reassurance. A bracket that starts late is the same
# defect as a stamp taken late, one step smaller.
# ══ RUN-SPAN BRACKET (row 73ebccb1, 2026-09-05) ═════════════════════════════════════
#
# 🔴 THE STAMP USED TO BE TAKEN ONLY AT RENDER TIME, SO A CLEAN `tracked-dirty=0`
# CERTIFIED THE TREE AT THE END AND SAID NOTHING ABOUT THE TWENTY MINUTES THE TIERS WERE
# ACTUALLY RUNNING. Measured on the 15:37-15:56 gate run: the stamp sat at log line 1746,
# after both tiers, and reported a clean tree at ~15:56 about a measurement that began at
# 15:37. The field was honest about what it measured; the reader took it as certifying the
# measurement. Cost: a 97.69% figure reported to three people and then withdrawn - not
# because it was known wrong, but because its provenance could not be established, and an
# unfalsifiable number is worth less than no number.
#
# => SO THE GATE NOW STAMPS AT BOTH ENDS AND REFUSES IF THEY DIFFER. Maria's shape (2), her
# preferred one, because it turns an unanswerable question into a REFUSAL: a gate that
# cannot tell whether its own tree moved should decline to report a number rather than
# report one with a caveat nobody reads.
#
# WARNING - IT FINGERPRINTS, IT DOES NOT COUNT. `tracked-dirty=<n>` is a COUNT, and a count
# cannot tell "file A went clean while file B went dirty" from "nothing moved" - the two
# print the same number. The fingerprint hashes the HEAD sha together with the full
# porcelain status, so any of: a commit landing, a file becoming dirty, a file becoming
# clean, or a DIFFERENT file becoming dirty, moves it.
#
# WARNING - AND IT NAMES THE SPAN IT ACTUALLY COVERS, which differs by mode:
#   --run-tiers  -> the bracket encloses the TIERS. This is the real thing.
#   pyramid mode -> the tiers ran in some OTHER process before this one started, so the
#                   bracket can only enclose THIS script's own render phase. Narrower, and
#                   said out loud rather than left for a reader to assume, because claiming
#                   to bracket a phase this process never owned would be the exact overclaim
#                   the defect above consisted of.
# 🔴 IT HASHES THE DIFF, NOT JUST THE STATUS LINES, AND THE FIRST CUT OF THIS DID NOT.
# `git status --porcelain` prints ` M path` whether a file was edited once or ten times, so
# a fingerprint over the STATUS ALONE is blind to the commonest mid-run edit there is: a
# further change to a file that was ALREADY dirty when the run started. Measured while
# building this, in a throwaway repo - two materially different contents, same porcelain
# line, IDENTICAL fingerprint. That is the same defect this row exists to fix, one level
# down, so it is recorded rather than quietly corrected.
#
# The three inputs cover three different ways a tree moves:
#   HEAD sha    - a commit landed (a peer merging, a rebase)
#   porcelain   - a file became dirty, became clean, or a DIFFERENT file did
#   diff HEAD   - the CONTENT of the tracked changes moved, at constant status
#
# ⚠️ NAMED LIMIT: `--untracked-files=no`, so a NEW untracked .py appearing mid-run does not
# move this. Deliberate and not free - untracked churn on this box is constant (logs,
# scratch files, a peer's symlinks), and a gate that refuses on every one of those is a
# gate whose refusal gets ignored. The existing `tracked-dirty` field already draws the line
# in the same place. If a new untracked source file ever turns out to matter here, that is a
# real gap and it is stated rather than hidden.
tree_fingerprint() {
    # NOT `git status --porcelain | wc -l`. See the count-vs-fingerprint note above.
    printf '%s\n%s\n%s\n' \
        "$( git rev-parse HEAD )" \
        "$( git status --porcelain --untracked-files=no )" \
        "$( git diff HEAD -- )" \
      | sha256sum | cut -c1-12
}

SPAN_START_FP="$( tree_fingerprint )"
SPAN_START_TS="$( date '+%H:%M:%S' )"
SPAN_START_SHA="$( git rev-parse --short HEAD )"
SPAN_START_DIRTY="$( git status --porcelain --untracked-files=no )"
SPAN_START_HEAD="$( git rev-parse HEAD )"
SPAN_START_DIFF_SHA="$( git diff HEAD -- | sha256sum )"


export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
export LUPIN_ROOT="$PROJECT_ROOT"

# Never a bare `python3`: an under-provisioned interpreter would make the gate report
# on a tree it cannot import. Resolved the same way the tiers resolve pytest.
source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
resolve_venv_pytest || exit $?
PYBIN="$(dirname "$PYTEST")/python3"
if [ ! -x "$PYBIN" ]; then PYBIN="$(dirname "$PYTEST")/python"; fi
if [ ! -x "$PYBIN" ]; then
    echo "run-coverage-gate.sh: found pytest at $PYTEST but no interpreter beside it" >&2
    exit 3
fi

RUN_TIERS=0
for arg in "$@"; do
    case "$arg" in
        --run-tiers) RUN_TIERS=1 ;;
    esac
done

# An isolated data file is a PRECONDITION, not a nicety. The repo-root default is shared
# by every session and pytest-cov ERASES it at startup, so a twenty-minute measurement and
# a nine-second one share one file and the short one wins (measured 2026-08-26).
if [ -z "${COVERAGE_FILE:-}" ]; then
    export COVERAGE_FILE="$PROJECT_ROOT/.coverage-gate-$$"
    echo "run-coverage-gate.sh: COVERAGE_FILE was unset; using an isolated $COVERAGE_FILE" >&2
fi

# 🔴 A TIER THAT NEVER RAN MUST NOT BECOME A LOW PERCENTAGE (row e2099400, 2026-08-30).
# These two invocations discarded both exit statuses until today — the script sets
# `-o pipefail` but NOT `-e`, so a refused tier fell straight through to the report. A peer
# suite arrived mid-run, the contention guard correctly refused the cosa tier with exit 6,
# and this gate published 70.68% / "FAILED" against 95.14% from the identical tree an hour
# earlier. Nothing had regressed; 8,769 cosa tests simply never ran, and the verdict said so
# nowhere. See src/scripts/lib/tier-measured.sh for the full measurement and for why a tier
# with FAILING TESTS still counts as measured.
source "$PROJECT_ROOT/src/scripts/lib/tier-measured.sh"

INCONCLUSIVE_TIERS=()

# Run one tier and record whether its data can be trusted. Never aborts here: both tiers are
# attempted so the operator learns about both problems in one run rather than one per re-run,
# which is the same reason the frame and floor verdicts are both printed below.
run_tier() {
    local label="$1" script="$2" status=0
    echo "═══ coverage gate: running $label tier ═══"
    bash "$PROJECT_ROOT/$script" -q || status=$?
    if ! tier_measured "$status"; then
        INCONCLUSIVE_TIERS+=( "$label|$status|$( tier_not_measured_reason "$status" )" )
    fi
}

if [ "$RUN_TIERS" -eq 1 ]; then
    rm -f "$COVERAGE_FILE"
    export LUPIN_COVERAGE=1
    run_tier unit src/tests/run-unit-tests.sh
    run_tier cosa src/tests/run-cosa-tests.sh

    # ⚠️ REFUSE TO RENDER, rather than render a number over a denominator known to be short.
    # This exits BEFORE the floor comparison on purpose: a percentage printed beside a
    # fail_under is read as a verdict on the code, and this one would be a verdict on the
    # box. Exit 2 is distinct from the floor/frame breach (1) so a caller can tell
    # "the gate says you are below the line" from "the gate could not tell".
    if [ ${#INCONCLUSIVE_TIERS[@]} -ne 0 ]; then
        echo ""
        echo "COVERAGE GATE INCONCLUSIVE — a tier did not run, so no percentage is owed."
        for entry in "${INCONCLUSIVE_TIERS[@]}"; do
            IFS="|" read -r label status reason <<< "$entry"
            echo "  the $label tier exited $status: $reason"
        done
        echo ""
        echo "  NOTHING HERE IS A COVERAGE VERDICT. The data file holds only the tiers that"
        echo "  finished, so any number rendered from it would be measured over a SHORT"
        echo "  denominator — and an unmeasured file reads exactly like an untested one."
        echo "  Measured 2026-08-30: one refused tier turned 95.14% into 70.68% on an"
        echo "  unchanged tree, and the old verdict called that a floor breach."
        echo "  Re-run when the cause above is cleared."
        exit 2
    fi
fi

# Record the tree the figure is earned on. A coverage number without a sha cannot be
# recovered later, only re-earned: coverage stores line NUMBERS and parses the file at
# RENDER time, so once the source moves underneath, previously-recorded lines land on
# different statements (measured 2026-08-26 — one data file read 99% then 38%, seventy
# minutes and two peer commits apart, with nothing re-run).
SPAN_END_FP="$( tree_fingerprint )"
SPAN_END_TS="$( date '+%H:%M:%S' )"
if [ "$RUN_TIERS" -eq 1 ]; then
    SPAN_COVERS="the tiers"
else
    SPAN_COVERS="this script's render phase ONLY (the tiers ran in another process)"
fi
if [ "$SPAN_START_FP" = "$SPAN_END_FP" ]; then SPAN_VERDICT="unmoved"; else SPAN_VERDICT="MOVED"; fi

echo "[coverage-gate] sha=$(git rev-parse --short HEAD) tracked-dirty=$(git status --porcelain --untracked-files=no | wc -l) coverage-file=$COVERAGE_FILE"
echo "[coverage-gate] run-span=$SPAN_VERDICT ($SPAN_START_TS..$SPAN_END_TS, fp $SPAN_START_FP..$SPAN_END_FP) covers=$SPAN_COVERS"

# 🔴 THE FIFTH STATE, AND IT GETS ITS OWN EXIT CODE ON PURPOSE (row 73ebccb1). The gate's
# existing codes are 0 measured, 1 floor/frame breach, 2 INCONCLUSIVE no data, 3 no
# interpreter, 6 refused/contended. A tree that moved mid-run is none of those, and folding
# it into one would have a reader map it onto the wrong cause. 4 was free.
if [ "$SPAN_VERDICT" != "unmoved" ]; then
    echo ""
    echo "COVERAGE GATE REFUSED - THE TREE MOVED WHILE THIS RUN WAS MEASURING IT."
    echo "  span covered : $SPAN_COVERS"
    echo "  from         : $SPAN_START_TS  sha $SPAN_START_SHA  fingerprint $SPAN_START_FP"
    echo "  to           : $SPAN_END_TS  sha $(git rev-parse --short HEAD)  fingerprint $SPAN_END_FP"
    echo ""
    # PRINT THE PATHS, NOT JUST A COUNT. A flag a reader must go investigate to act on is a
    # flag most readers will not act on - this repo's own finding, from a tracked-dirty=1
    # that everybody saw and nobody read.
    # 🔴 NAME WHAT MOVED, AND COVER THE CASE WHERE THE STATUS DID NOT. Measured while
    # building this: editing a file that was ALREADY dirty leaves the porcelain line
    # byte-identical, so a status-diff alone printed an EMPTY section under a refusal that
    # had genuinely fired. A refusal that names nothing is half a refusal.
    if [ "$( git rev-parse HEAD )" != "$SPAN_START_HEAD" ]; then
        echo "  HEAD moved: $SPAN_START_SHA -> $( git rev-parse --short HEAD )  (a commit landed under the run)"
    fi
    _status_delta="$( diff <( printf '%s\n' "$SPAN_START_DIRTY" ) \
                           <( git status --porcelain --untracked-files=no ) || true )"
    if [ -n "$_status_delta" ]; then
        echo "  files that changed dirty-state (porcelain, start -> end):"
        printf '%s\n' "$_status_delta" | sed 's/^/    /'
    else
        echo "  dirty-state list is UNCHANGED — the movement is in file CONTENT, not in which"
        echo "  files are dirty. This is exactly the case a tracked-dirty COUNT cannot see."
    fi
    if [ "$( git diff HEAD -- | sha256sum )" != "$SPAN_START_DIFF_SHA" ]; then
        echo "  tracked content changed. Files with content differing from HEAD right now:"
        git diff HEAD --name-only -- | sed 's/^/    /'
    fi
    echo ""
    echo "  NO PERCENTAGE IS OWED AND NONE IS PRINTED. Coverage stores line NUMBERS and"
    echo "  parses the source at RENDER time, so a tree that moved underneath makes"
    echo "  recorded lines land on different statements. A figure rendered now would not"
    echo "  be wrong so much as UNFALSIFIABLE, which is worse - it cannot be checked and"
    echo "  it reads like a receipt."
    echo "  Re-run on a quiet tree. Nothing here is a verdict on the code."
    exit 4
fi

# 🔴 THE FLOOR MUST BE THE ONE THE BRANCH COMMITTED (Maya's working-tree-artifact audit,
# src/rnd/v0.2.1/2026.08.30-working-tree-artifact-gate-audit.md — the coverage gate's own row).
# The tell ABOVE is a print, not a check: measured 2026-08-30 at sha 908414ad, lowering
# pyproject's fail_under from 92 to 0 in the working tree turned a 0.84% measurement into
# "COVERAGE GATE PASSED", exit 0 — and the tell dutifully printed tracked-dirty=1 while it
# happened. That count cannot carry the check either: an unrelated README edit prints the
# IDENTICAL string while the gate correctly fails, because a repo-wide count is not a
# statement about pyproject.
#
# ⇒ FAIL CLOSED, on Mr Radio's condition: ANY non-zero refuses. Exit 1 is a lowered floor,
#   exit 2 is "cannot tell" — and a guard that shrugs on a parse error is the defect wearing
#   the cure's clothes, so an unreadable threshold is a refusal too, never a pass.
# Negative control: src/tests/control-coverage-gate-floor-tamper.sh
if ! "$SCRIPT_DIR/lib/check-floor-not-lowered.sh" "$PYBIN"; then
    echo "COVERAGE GATE REFUSED  (the floor this run would enforce is not the branch's floor)"
    exit 1
fi

echo "═══ coverage gate: frame completeness ═══"
# A data file that does not exist, or holds nothing, must say EXACTLY that. The first
# version of this let `coverage json` fail silently and then handed the frame check a
# missing path, which surfaced as a FileNotFoundError traceback — a red that does not
# say what is red, which is this row's own defect wearing a stack trace.
# ⚠️ THE REPORT MUST NOT LIVE BESIDE THE DATA FILE. coverage combines every path matching
# `$COVERAGE_FILE.*` as a parallel data file, so writing the report to "$COVERAGE_FILE.json"
# makes the next read try to parse the JSON as a coverage database ("file is not a
# database", "Combined 0 files, 1 file errored") and the gate destroys its own input.
# Measured 2026-08-29 while verifying this script.
REPORT_JSON="${COVERAGE_FILE%/*}/coverage-frame-report-$$.json"
[ "$REPORT_JSON" = "$COVERAGE_FILE" ] && REPORT_JSON="./coverage-frame-report-$$.json"
trap 'rm -f "$REPORT_JSON"' EXIT

# ⚠️ AND THE EXIT CODE CANNOT BE THE NO-DATA TEST. `coverage json` also exits non-zero
# for a fail_under breach, so keying "no data" on it reported NO DATA over a perfectly
# good measurement — a false negative of exactly the kind this row exists to catch.
# Ask the report whether it holds files instead.
"$PYBIN" -m coverage json -o "$REPORT_JSON" >/dev/null 2>&1 || true
if ! "$PYBIN" -c "import json,sys; sys.exit( 0 if json.load( open( sys.argv[1] ) ).get( 'files' ) else 1 )" "$REPORT_JSON" 2>/dev/null; then
    echo "NO COVERAGE DATA TO GATE ON."
    echo "  COVERAGE_FILE=$COVERAGE_FILE holds no measurement, so there is nothing to"
    echo "  check and NOTHING HERE SHOULD BE READ AS A PASS. Usual causes: the tiers ran"
    echo "  without LUPIN_COVERAGE set; they were refused by the contended-coverage guard"
    echo "  (exit 6) because a peer was already running --cov; or they wrote a different"
    echo "  COVERAGE_FILE than this gate is reading."
    echo "  Re-run with:  src/tests/run-coverage-gate.sh --run-tiers"
    echo "COVERAGE GATE INCONCLUSIVE  (no data)"
    exit 2
fi
FRAME_EXIT=0
"$PYBIN" - "$REPORT_JSON" <<'PY' || FRAME_EXIT=$?
import sys
import cosa.utils.coverage_frame as cf

report_json = sys.argv[ 1 ]
pyproject   = open( "pyproject.toml", encoding="utf-8" ).read()
dirs        = cf.source_dirs( pyproject )
# READ, not restated. A hard-coded copy of this list had already drifted from
# pyproject's `omit` the first time this gate ran.
OMIT        = cf.omit_patterns( pyproject )

orphans = cf.unreachable_subdirs( ".", dirs, OMIT )
if orphans:
    print( "FRAME IS NOT WHAT IT CLAIMS — these directories hold .py files that no source" )
    print( "entry can reach, so their code is outside the denominator while `source` reads" )
    print( "as if it covered them. coverage's walk does not descend into non-package dirs." )
    for o in orphans: print( f"    {o}" )
    print( "Fix: add each as its own entry in [tool.coverage.run] source." )
    sys.exit( 1 )

reported            = cf.report_paths( report_json )
unexpected, unseen  = cf.unseen_python_files( ".", dirs, reported, OMIT )
undeclared          = [ u for u in unseen if u not in cf.KNOWN_UNSEEABLE ]
if unexpected:
    print( "FILES THE FRAME CLAIMS BUT THE REPORT DOES NOT CARRY:" )
    for u in unexpected: print( f"    {u}" )
    sys.exit( 1 )
if undeclared:
    print( "FILES COVERAGE CANNOT SEE AND NOBODY HAS DECLARED (a dot in the filename stem" )
    print( "makes a file invisible to coverage; rename it, or add it to KNOWN_UNSEEABLE" )
    print( "with the reason, so the frame's claim equals its measurement):" )
    for u in undeclared: print( f"    {u}" )
    sys.exit( 1 )
dead = cf.unreachable_declarations( unseen )
if dead:
    # Row f3400eab. A declaration the census never reaches reads as "handled" while
    # nothing has looked — the state the live tree was in until 2026-08-30, when the
    # walk pruned src/cosa/rnd unread and KNOWN_UNSEEABLE named a file inside it.
    print( "DECLARED UNSEEABLE BUT NEVER REACHED — these KNOWN_UNSEEABLE entries name" )
    print( "paths this census did not find, so each is a receipt for a check that did" )
    print( "not happen. The file was renamed or moved, or its source entry is gone:" )
    for d in dead: print( f"    {d}" )
    sys.exit( 1 )
print( f"frame OK — {len( reported )} files reported, "
       f"{len( cf.KNOWN_UNSEEABLE )} declared unseeable, 0 unaccounted" )
PY

echo "═══ coverage gate: floor ═══"
FLOOR_EXIT=0
"$PYBIN" -m coverage report --precision=2 | tail -3 || FLOOR_EXIT=$?

# Report BOTH verdicts before exiting. Failing at the first one hides the second, and a
# gate that shows you one problem at a time costs a full re-run to learn the next.
if [ "$FRAME_EXIT" -ne 0 ] || [ "$FLOOR_EXIT" -ne 0 ]; then
    echo "COVERAGE GATE FAILED  (frame_exit=$FRAME_EXIT floor_exit=$FLOOR_EXIT)"
    exit 1
fi
echo "COVERAGE GATE PASSED"
exit 0
