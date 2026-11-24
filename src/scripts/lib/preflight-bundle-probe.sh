#!/usr/bin/env bash
#
# preflight-bundle-probe.sh — the served-bundle freshness gate, as a function (row 416c967b).
#
# src/lupin_app/static/dist/ is gitignored and served to :7999 and :8000 from the main checkout. A merge does not
# rebuild it, so merged TypeScript can sit unserved while the E2E pyramid tests the old bytes (measured 23 Nov 2026:
# a bundle built 20 Nov, e2e ts-2bf25ef8 red, rebuilt by hand, ts-42964c16 green). bounce-dev-server.sh already asks
# check_bundle_freshness.py (a content comparison: would a rebuild change the delivered bytes?) after a :7999 bounce.
# This gate asks the same checker before a :8000 preflight or an E2E launch, which no bounce precedes.
#
# Source it, then call bundle_freshness_gate. It prints the checker's report and needs nothing from the caller.
# LUPIN_BUNDLE_FRESHNESS_CMD names a different checker (tests); LUPIN_BUNDLE_REBUILD_CMD a different rebuild (tests).

BUNDLE_PROBE_ROOT="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )/../../.." && pwd )"

# bundle_freshness_gate [--rebuild]
#
# Requires:  the tree this file lives in holds src/scripts/check_bundle_freshness.py and package.json
# Ensures:   returns 0 when every judged bundle is FRESH (after a rebuild, when --rebuild was given and the first
#            check said STALE); 1 when a bundle is STALE; 2 when the checker could not answer; 3 when it crashed.
#            Never rebuilds without --rebuild. A rebuild that fails leaves the verdict at the second check.
bundle_freshness_gate() {
    local rebuild=false rc=0 checker=( python3 "${BUNDLE_PROBE_ROOT}/src/scripts/check_bundle_freshness.py" --quiet )
    [ "${1:-}" = "--rebuild" ] && rebuild=true
    [ -n "${LUPIN_BUNDLE_FRESHNESS_CMD:-}" ] && checker=( "$LUPIN_BUNDLE_FRESHNESS_CMD" )
    "${checker[@]}" 2>&1 || rc=$?
    if [ "$rc" -eq 1 ] && [ "$rebuild" = true ]; then
        echo "bundle gate: STALE, rebuilding (npm run build)"
        if [ -n "${LUPIN_BUNDLE_REBUILD_CMD:-}" ]; then
            "$LUPIN_BUNDLE_REBUILD_CMD" || true
        else
            ( cd "$BUNDLE_PROBE_ROOT" && npm run build ) || true
        fi
        rc=0
        "${checker[@]}" 2>&1 || rc=$?
    fi
    return "$rc"
}
