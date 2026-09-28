#!/usr/bin/env bash
#
# heartbeat-poke-toggle.sh — turn the heartbeat Stop poke on or off, or show its state.
#
# Usage:
#   heartbeat-poke-toggle.sh status    # print the heartbeat block
#   heartbeat-poke-toggle.sh off       # heartbeat.poke_output_enabled = false
#   heartbeat-poke-toggle.sh on        # heartbeat.poke_output_enabled = true
#
# Edits ~/.claude/settings.json (override with CLAUDE_SETTINGS). Writes through a temp
# file and re-reads the result, so a bad write never replaces the settings file.
#
# Exit codes: 0 ok · 1 bad usage · 2 settings file missing or unparseable · 3 write did not land

set -euo pipefail

SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
ACTION="${1:-}"

if [[ ! -f "$SETTINGS" ]] || ! jq -e . "$SETTINGS" > /dev/null 2>&1; then
    echo "ERROR: $SETTINGS is missing or not valid JSON" >&2
    exit 2
fi

case "$ACTION" in
    status)
        jq '.heartbeat' "$SETTINGS"
        exit 0
        ;;
    off) VALUE=false ;;
    on)  VALUE=true ;;
    *)
        echo "Usage: $0 status|on|off" >&2
        exit 1
        ;;
esac

TMP="$( mktemp "${SETTINGS}.XXXXXX" )"
trap 'rm -f "$TMP"' EXIT

jq --argjson v "$VALUE" '.heartbeat.poke_output_enabled = $v' "$SETTINGS" > "$TMP"
jq -e . "$TMP" > /dev/null
mv "$TMP" "$SETTINGS"
trap - EXIT

ACTUAL="$( jq -r '.heartbeat.poke_output_enabled' "$SETTINGS" )"
if [[ "$ACTUAL" != "$VALUE" ]]; then
    echo "ERROR: wanted poke_output_enabled=$VALUE, file reads $ACTUAL" >&2
    exit 3
fi

echo "heartbeat.poke_output_enabled = $ACTUAL  ($SETTINGS)"
