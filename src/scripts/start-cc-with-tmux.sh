#!/bin/bash
# start-cc-with-tmux.sh — Launch Claude Code inside a named tmux session.
#
# Creates a new tmux session (or reattaches to an existing one) and starts
# Claude Code inside it. The session name is recorded in the session bridge
# file by the SessionStart hook, enabling the CCNotificationListener to send
# tmux Enter keystrokes for voice injection when CC is idle.
#
# Usage:
#   ./start-cc-with-tmux.sh [session-name] [extra-claude-args...]
#
# Examples:
#   ./start-cc-with-tmux.sh lupin
#   ./start-cc-with-tmux.sh lupin --resume
#   ./start-cc-with-tmux.sh                  # defaults to "claude-code"

set -euo pipefail

#SESSION_NAME="${1:-claude-code}"
SESSION_NAME="${1:-cc-tmux-session-$(date +%s | md5sum | cut -c1-8)}"
shift 2>/dev/null || true  # Shift past session name if provided

# Per-project preferred personas. Forwarded into the tmux session via -e so the
# SessionStart hook (register_session.py) sees them regardless of the tmux
# server's frozen env or whether ~/.bashrc was sourced. The hook reads only the
# key matching detect_project(), so unused keys are inert.
PERSONA_ENV_FLAGS=(
    -e "COSA_VOICE_PREFERRED_PERSONA__LUPIN=Tiberius"
    -e "COSA_VOICE_PREFERRED_PERSONA__LUPIN_MOBILE=Tiffany"
    -e "COSA_VOICE_PREFERRED_PERSONA__PLAN=María"
    -e "COSA_VOICE_PREFERRED_PERSONA__LOOKML=Sam"
)

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "tmux session '$SESSION_NAME' already exists — attaching..."
    tmux attach -t "$SESSION_NAME"
else
    echo "Creating tmux session '$SESSION_NAME' with Claude Code..."
    tmux new-session -s "$SESSION_NAME" "${PERSONA_ENV_FLAGS[@]}" -d "claude $*"
    tmux attach -t "$SESSION_NAME"
fi
