#!/bin/bash
#
# DEPRECATED: This per-project notify.sh script is deprecated.
# Please use the global 'notify-claude-async' or 'notify-claude-sync' commands instead.
#
# Migration:
#   - Fire-and-forget: notify-claude-async "message" --type=TYPE --priority=PRIORITY
#   - Response-required: notify-claude-sync "message" --response-type=yes_no|open_ended
#
# This script will redirect to notify-claude-async for backward compatibility.
#

echo "⚠️  DEPRECATION WARNING: src/scripts/notify.sh is deprecated." >&2
echo "   Please use the global notification commands instead:" >&2
echo "     notify-claude-async  (fire-and-forget)" >&2
echo "     notify-claude-sync   (response-required)" >&2
echo "   This script will be removed in a future version." >&2
echo "" >&2

# Redirect to global notify-claude-async command (fire-and-forget default)
exec notify-claude-async "$@"