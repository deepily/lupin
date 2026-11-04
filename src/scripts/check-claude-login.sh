#!/usr/bin/env bash
#
# check-claude-login.sh — say whether a container's Claude Code login has expired.
#
# A container keeps its own login, and an expired one fails every Claude Code job in it. This reads the
# expiry field only (never a token, never a CLI call) and prints the remedy line when it is past.
#
# Usage:
#   src/scripts/check-claude-login.sh                    # lupin-rest-dev, the :7999 server
#   src/scripts/check-claude-login.sh lupin-rest-test    # the :8000 server
#
# Exit codes:
#   0 — the login is valid
#   1 — expired, or the expiry could not be read (the remedy line is printed)
#   2 — docker is unreachable or the container is not running, so nothing was checked

set -u

CONTAINER="${1:-lupin-rest-dev}"
failures=0

say_ok()   { printf "[OK]   %s\n" "$1"; }
say_fail() { printf "[FAIL] %s\n" "$1"; failures=$(( failures + 1 )); }
remedy()   { printf "       remedy: %s\n" "$1"; }
run_cmd()  { "$@"; }

if ! docker info >/dev/null 2>&1; then
    printf "[ABORT] docker daemon not reachable\n"
    exit 2
fi

if ! docker ps --filter "name=^${CONTAINER}$" --format "{{.Names}}" | grep -q "^${CONTAINER}$"; then
    printf "[ABORT] container '%s' is not running\n" "${CONTAINER}"
    remedy "docker compose up -d ${CONTAINER}"
    exit 2
fi

# shellcheck source=lib/claude-login-probe.sh
source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )/lib/claude-login-probe.sh"
probe_claude_login "${CONTAINER}"

[ "$failures" -eq 0 ] || exit 1
exit 0
