#!/bin/bash
#
# DEPRECATED: This per-project notify.sh script is deprecated.
# Please use the global 'notify-claude' command instead.
#
# Migration: Replace all calls to this script with 'notify-claude'
# Example: notify-claude "message" --type=TYPE --priority=PRIORITY
#
# This script will redirect to notify-claude for backward compatibility.
#

echo "⚠️  DEPRECATION WARNING: src/scripts/notify.sh is deprecated." >&2
echo "   Please use the global 'notify-claude' command instead." >&2
echo "   This script will be removed in a future version." >&2
echo "" >&2

# Redirect to global notify-claude command
exec notify-claude "$@"