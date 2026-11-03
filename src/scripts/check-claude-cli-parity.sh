#!/usr/bin/env bash
#
# check-claude-cli-parity.sh — say whether a container's bundled Claude Code is too far behind the host's.
#
# Usage:
#   src/scripts/check-claude-cli-parity.sh                    # lupin-rest-dev, the :7999 server
#   src/scripts/check-claude-cli-parity.sh lupin-rest-test    # the :8000 server
#   CLAUDE_CLI_MAX_LAG=5 src/scripts/check-claude-cli-parity.sh
#
# Exit codes:
#   0 — within the limit
#   1 — too far behind (the remedy line is printed)
#   2 — a version could not be read, or docker is unreachable or the container is not running

set -u

CONTAINER="${1:-lupin-rest-dev}"

if ! docker ps --filter "name=^${CONTAINER}$" --format "{{.Names}}" 2>/dev/null | grep -q "^${CONTAINER}$"; then
    printf "[ABORT] container '%s' is not running\n" "${CONTAINER}"
    exit 2
fi

# shellcheck source=lib/claude-cli-parity-probe.sh
source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )/lib/claude-cli-parity-probe.sh"
probe_claude_cli_parity "${CONTAINER}"
