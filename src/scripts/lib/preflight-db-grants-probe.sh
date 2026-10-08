#!/usr/bin/env bash
#
# preflight-db-grants-probe.sh — the database-grants probe of preflight-test-container.sh, as a function.
#
# Source it, then call probe_db_grants. It needs the caller's say_ok, say_warn, say_fail and remedy functions
# and the VERBOSE variable. lib/check-db-grants.sh does the work: it checks, and with LUPIN_DB_GRANTS_REPAIR=on
# it repairs once with --grants-only and checks again. Repair is off until the one-time apply has been run
# by hand, so a red answer is a warning, and it blocks only after a repair that left the roles short.
# Exit 2, or any code the helper does not define, means the check could not run: that says nothing about
# the container, so it is a warning too. LUPIN_DB_GRANTS_CHECK=skip turns the probe off.
#
# DB_GRANTS_HELPER overrides the helper path, so a test can stand in a stub for it.

probe_db_grants() {
    if [ "${LUPIN_DB_GRANTS_CHECK:-on}" = "skip" ]; then
        say_warn "database grants probe skipped (LUPIN_DB_GRANTS_CHECK=skip)"
        return 0
    fi
    local helper="${DB_GRANTS_HELPER:-$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )/check-db-grants.sh}"
    local grants_rc=0 grants_out
    grants_out="$( "$helper" --repair-when-enabled 2>&1 )" || grants_rc=$?
    if [ "${VERBOSE:-false}" = true ] || [ "$grants_rc" -ne 0 ]; then printf "%s\n" "$grants_out" | sed 's/^/       /'; fi
    case "$grants_rc" in
        0) say_ok "database roles hold every grant the matrix requires" ;;
        1) say_fail "database roles still lack grants after a repair"
           remedy "src/scripts/provision-db-roles.sh with the three password files (needs root); see the lines above" ;;
        3) say_warn "database roles lack grants (repair is off)"
           remedy "LUPIN_DB_GRANTS_REPAIR=on src/scripts/lib/check-db-grants.sh --repair-when-enabled, or the remedy line above" ;;
        *) say_warn "database grants could not be checked (exit ${grants_rc})" ;;
    esac
}
