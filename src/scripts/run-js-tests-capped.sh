#!/bin/bash
# Door 1 of the JS-test lane: what `npm test` actually runs.
#
# package.json cannot `source` a shell library, so this thin script is the seam.
# It exists so `npm test` and src/tests/run-typescript-tests.sh reach the SAME
# capped cgroup rather than each carrying their own copy of the ceiling — the
# 2026-08-23 incident happened because two doors into the same 119 files were
# capped independently and one of them was missed.
#
# The mechanism this caps is documented once, in src/scripts/lib/jstest-slice.sh.
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# 🔴 TWO LEVELS, NOT ONE. This script lives in src/scripts/, so the repo root is
# TWO directories up — `..` lands on src/ and every path built from it gains a
# phantom src/ segment. It shipped that way at 8bf71a64 (2026-08-29) and was
# never once correct, so `npm test` has ALWAYS died at the source line below and
# door 1 has ALWAYS been uncapped. Door 2, src/tests/run-typescript-tests.sh:30,
# is one directory deeper and correctly says `../..` — the two doors disagreeing
# is the whole defect. Guard: src/tests/unit/test_both_js_test_doors_reach_the_same_cap.py
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/src/scripts/lib/jstest-slice.sh"

JS_TIMEOUT_SECS="${JS_TIMEOUT_SECS:-900}"
JS_CONCURRENCY="${JS_CONCURRENCY:-4}"
JSTEST_RUNTIME_MAX="${JSTEST_RUNTIME_MAX:-$(( JS_TIMEOUT_SECS + 100 ))}"

# State the tree before the run — see the note in run-typescript-tests.sh for why this is
# BEFORE and not after. `jstest_slice_exec` replaces this shell, so anything emitted after
# it would never run at all.
source "$PROJECT_ROOT/src/scripts/lib/tree-state.sh"
emit_tree_state

jstest_slice_exec timeout "$JS_TIMEOUT_SECS" \
    node --test-concurrency="$JS_CONCURRENCY" --import tsx \
         --test "src/tests/**/*.test.ts" "$@"
