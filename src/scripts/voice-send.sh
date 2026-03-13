#!/bin/bash
# voice-send.sh — Manual testing utility for voice injection into idle CC sessions.
#
# Writes a message directly to the JSONL buffer and sends tmux Enter to
# trigger the UserPromptSubmit hook. Useful for testing without the full
# notification pipeline (no WebSocket, no CCNotificationListener).
#
# Usage:
#   ./voice-send.sh <session_id_hash> <tmux_session> "command text"
#   ./voice-send.sh <session_id_hash> "command text"   (auto-resolve tmux)
#
# Examples:
#   ./voice-send.sh a1b2c3d4 lupin "list all Python files"
#   ./voice-send.sh a1b2c3d4 "show git status"

set -euo pipefail

SESSIONS_DIR="$HOME/.claude/sessions"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <session_id_hash> [tmux_session] \"command text\""
    echo ""
    echo "  session_id_hash  8-char CC session hash"
    echo "  tmux_session     tmux session name (optional, auto-resolves)"
    echo "  command text     Voice message to inject"
    exit 1
fi

SESSION_HASH="$1"
shift

# Determine if tmux session was provided or should be auto-resolved
if [ $# -ge 2 ]; then
    TMUX_SESSION="$1"
    shift
    MESSAGE="$*"
else
    MESSAGE="$*"
    # Auto-resolve tmux session from session bridge file
    TMUX_SESSION=""
    for f in "$SESSIONS_DIR"/cc-*.json; do
        [ -f "$f" ] || continue
        if grep -q "\"$SESSION_HASH\"" "$f" 2>/dev/null; then
            TMUX_SESSION=$(python3 -c "import json; d=json.load(open('$f')); print(d.get('tmux_session',''))" 2>/dev/null || true)
            break
        fi
    done
fi

BUFFER_FILE="$SESSIONS_DIR/cc-buffer-${SESSION_HASH}.jsonl"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")

# Write JSONL entry
mkdir -p "$SESSIONS_DIR"
echo "{\"message\":\"$MESSAGE\",\"priority\":\"normal\",\"job_id\":\"$SESSION_HASH\",\"sender_id\":\"voice-send-manual\",\"timestamp\":\"$TIMESTAMP\",\"buffered_at\":\"$TIMESTAMP\"}" >> "$BUFFER_FILE"

echo "Buffered message to: $BUFFER_FILE"
echo "  Message: $MESSAGE"

# Send tmux Enter
if [ -n "$TMUX_SESSION" ]; then
    if tmux send-keys -t "$TMUX_SESSION" Enter 2>/dev/null; then
        echo "  Sent Enter to tmux session: $TMUX_SESSION"
    else
        echo "  WARNING: Failed to send Enter to tmux session: $TMUX_SESSION"
    fi
else
    echo "  WARNING: No tmux session found — message buffered but Enter not sent"
    echo "  Tip: Provide tmux session name as second argument"
fi
