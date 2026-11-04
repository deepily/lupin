#!/usr/bin/env bash
#
# preflight-smoke-admin-probe.sh — the smoke admin credentials probe of preflight-test-container.sh, as a function.
#
# Source it, then call probe_smoke_admin_credentials. It needs the caller's CONTAINER, run_cmd, say_ok, say_warn and
# remedy. The smoke helpers sign in as an admin because /api/debug/websocket-state is admin-only, and they read the
# credentials from the container's environment. docker-compose.yml passes them with an empty default, so a recreate
# from a shell that lacks them still starts the container, and the smoke tests then fail. This probe names the empty
# variables before that happens. It never prints a value.

SMOKE_ADMIN_VARS="LUPIN_TEST_ADMIN_EMAIL LUPIN_TEST_ADMIN_PASSWORD"

# smoke_admin_empty_names
#
# Requires:  CONTAINER names a running container; run_cmd runs its arguments
# Ensures:   prints the names, space separated, of the variables that are empty or unset in the container
#            and returns 0; returns 1 and prints nothing when the container cannot be queried
smoke_admin_empty_names() {
    run_cmd docker exec "${CONTAINER}" sh -c "for n in ${SMOKE_ADMIN_VARS}; do eval \"v=\\\${\$n:-}\"; [ -n \"\$v\" ] || printf '%s ' \"\$n\"; done" 2>/dev/null
}

probe_smoke_admin_credentials() {
    local empty
    if ! empty="$( smoke_admin_empty_names )"; then
        say_warn "smoke admin credentials could not be read from container '${CONTAINER}'"
        remedy "check that the container is running, then re-run this preflight"
        return 0
    fi
    empty="${empty% }"
    if [ -z "$empty" ]; then
        say_ok "smoke admin credentials are set in the container"
    else
        say_warn "smoke admin credentials are empty in the container: ${empty} (smoke tests that sign in as admin will fail)"
        remedy "export both in the shell (bash -ic loads them from ~/.bashrc), then docker compose up -d --force-recreate lupin-rest-test"
    fi
}
