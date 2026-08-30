#!/bin/bash
# NEGATIVE CONTROL for the coverage gate's floor false-green.
#
# THE DEFECT, measured 2026-08-30 at sha 908414ad before the guard existed: the gate's
# floor is pyproject's `fail_under`, read from the WORKING TREE and never from HEAD.
# Lowering it 92 -> 0 turned a 0.84% measurement into "COVERAGE GATE PASSED", exit 0.
# The gate's tell printed `tracked-dirty=1` while that happened and nothing consumed it.
#
# FIVE SCENARIOS, each ASSERTED rather than printed for a human to judge — a control that
# only prints is the same defect as the tell it replaces:
#
#   1. clean tree,      gate  -> FAILS on the floor      (the gate does work at all)
#   2. clean tree,      guard -> ALLOWS                  (the fix does not cry wolf)
#   3. lowered floor,   raw `coverage report` -> EXIT 0  🔴 THE DEFECT, still demonstrable
#   4. lowered floor,   gate  -> REFUSES                 (the fix, in place)
#   5. malformed toml,  gate  -> REFUSES                 (FAIL CLOSED, not a shrug)
#
# ⚠️ SCENARIO 3 IS WHY THIS FILE STILL EARNS ITS KEEP once the gate is fixed. Without it
# the suite would only prove the gate refuses things, never that there was anything to
# refuse — and a control that cannot show the disease is not evidence the cure works.
#
# ⚠️ AND SCENARIOS 1 AND 4 BOTH EXIT 1, so the exit code CANNOT tell them apart. They are
# distinguished on the verdict LINE. Asserting only the code here would have passed while
# the guard did nothing.
#
# Restores pyproject.toml on ANY exit path, including a failed assertion.

set -u
set -o pipefail

cd "$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
PYBIN="$PWD/.venv/bin/python"
GATE="./src/tests/run-coverage-gate.sh"
GUARD="./src/tests/lib/check-floor-not-lowered.sh"
DATA="$( mktemp -u /tmp/covgate-control-XXXXXX.data )"

if ! git diff --quiet -- pyproject.toml; then
    echo "REFUSING TO RUN: pyproject.toml is already dirty. This control edits it, and it"
    echo "will not clobber somebody's in-flight change. Commit or stash it first."
    exit 3
fi
cleanup() { git checkout -- pyproject.toml 2>/dev/null; rm -f "$DATA"; }
trap cleanup EXIT

FAILURES=0
assert() {  # assert <label> <expected> <actual>
    if [ "$2" = "$3" ]; then echo "  ✓ $1 (got $3)"
    else echo "  ✗ $1 — EXPECTED $2, GOT $3"; FAILURES=$(( FAILURES + 1 )); fi
}
verdict() {  # verdict <output> -> the gate's own last verdict line
    echo "$1" | grep -oE 'COVERAGE GATE (PASSED|FAILED|REFUSED|INCONCLUSIVE)' | tail -1
}

echo "═══ generating a real, honestly-low measurement ═══"
COVERAGE_FILE="$DATA" LUPIN_ROOT="$PWD" "$PYBIN" -m pytest \
    src/tests/unit/test_manager_figure.py -q --cov --cov-branch -p no:randomly >/dev/null 2>&1
[ -s "$DATA" ] || { echo "no coverage data produced — control cannot run"; exit 3; }
HEAD_FLOOR="$( git show HEAD:pyproject.toml | grep -m1 '^fail_under' | tr -d ' ' )"
echo "  data=$DATA   HEAD $HEAD_FLOOR"

echo "═══ 1. clean tree — the gate must FAIL on the floor ═══"
OUT="$( COVERAGE_FILE="$DATA" LUPIN_COVERAGE=1 "$GATE" 2>&1 )"
assert "gate rejects a low measurement" "COVERAGE GATE FAILED" "$( verdict "$OUT" )"

echo "═══ 2. clean tree — the guard must ALLOW ═══"
"$GUARD" "$PYBIN" >/dev/null 2>&1; assert "guard does not cry wolf on a clean tree" 0 $?

echo "═══ lowering the floor in the working tree only ═══"
sed -i 's/^fail_under = .*/fail_under = 0/' pyproject.toml
echo "  HEAD still carries: $HEAD_FLOOR   working tree now: $( grep -m1 '^fail_under' pyproject.toml | tr -d ' ' )"

echo "═══ 3. lowered floor — the RAW floor check still passes (the defect itself) ═══"
COVERAGE_FILE="$DATA" "$PYBIN" -m coverage report --precision=2 >/dev/null 2>&1
assert "an unguarded floor check certifies 0.84% as a pass" 0 $?

echo "═══ 4. lowered floor — the gate must REFUSE ═══"
OUT="$( COVERAGE_FILE="$DATA" LUPIN_COVERAGE=1 "$GATE" 2>&1 )"
assert "gate refuses an uncommitted floor" "COVERAGE GATE REFUSED" "$( verdict "$OUT" )"
git checkout -- pyproject.toml

echo "═══ 5. malformed pyproject — the gate must REFUSE, not shrug ═══"
printf '\nthis is not = = toml\n' >> pyproject.toml
OUT="$( COVERAGE_FILE="$DATA" LUPIN_COVERAGE=1 "$GATE" 2>&1 )"
assert "gate fails CLOSED on an unreadable threshold" "COVERAGE GATE REFUSED" "$( verdict "$OUT" )"
git checkout -- pyproject.toml

echo ""
if [ "$FAILURES" -eq 0 ]; then echo "CONTROL PASSED — defect demonstrable, gate refuses it, gate fails closed, guard stays quiet otherwise."; exit 0; fi
echo "CONTROL FAILED — $FAILURES assertion(s) did not hold."; exit 1
