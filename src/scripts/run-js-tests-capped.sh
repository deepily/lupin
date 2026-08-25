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
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/src/scripts/lib/jstest-slice.sh"

JS_TIMEOUT_SECS="${JS_TIMEOUT_SECS:-900}"
JS_CONCURRENCY="${JS_CONCURRENCY:-4}"
JSTEST_RUNTIME_MAX="${JSTEST_RUNTIME_MAX:-$(( JS_TIMEOUT_SECS + 100 ))}"

jstest_slice_exec timeout "$JS_TIMEOUT_SECS" \
    node --test-concurrency="$JS_CONCURRENCY" --import tsx \
         --test "src/tests/**/*.test.ts" "$@"
