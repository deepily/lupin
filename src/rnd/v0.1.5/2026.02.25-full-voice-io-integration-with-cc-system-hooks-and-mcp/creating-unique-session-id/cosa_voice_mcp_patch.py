#!/usr/bin/env python3
"""
Integration patch for cosa_voice_mcp.py — replace self-generated SESSION_ID
with the real Claude Code session_id via session_bridge.

BEFORE (current code):
    SESSION_ID = uuid.uuid4().hex[:8]

AFTER (with bridge):
    SESSION_ID = get_claude_session_id()   # non-blocking, immediate fallback
    # Then lazily upgrade when the real ID becomes available

This shows ONLY the changed sections. Apply to cosa_voice_mcp.py.
"""

# ============================================================================
# Replace the module-level initialization block in cosa_voice_mcp.py
# ============================================================================

# --- OLD ---
# SESSION_ID = uuid.uuid4().hex[:8]  # 8-char hex, e.g., "a1b2c3d4"
# SENDER_ID  = _get_sender_id( PROJECT, SESSION_ID )

# --- NEW ---
from session_bridge import get_claude_session_id, get_session_metadata
import threading

PROJECT    = _get_project()
SESSION_ID = get_claude_session_id()  # Immediate: env > file > fallback UUID
SENDER_ID  = _get_sender_id( PROJECT, SESSION_ID )
SERVER_URL = _get_server_url()

# Lazy upgrade: poll for real session_id in background thread.
# When SessionStart hook fires (typically <2s after MCP spawn), the
# session file appears, and we upgrade SESSION_ID + SENDER_ID in place.
def _upgrade_session_id():
    """Background thread: wait for real Claude Code session_id."""
    global SESSION_ID, SENDER_ID

    from session_bridge import wait_for_session_id, _fallback_session_id

    real_id = wait_for_session_id( timeout=15.0, poll_interval=1.0 )
    if real_id != _fallback_session_id and real_id != SESSION_ID:
        SESSION_ID = real_id
        SENDER_ID  = _get_sender_id( PROJECT, SESSION_ID )
        logger.info( f"Session ID upgraded: {SESSION_ID}" )
        logger.info( f"Sender ID upgraded: {SENDER_ID}" )

_upgrade_thread = threading.Thread( target=_upgrade_session_id, daemon=True )
_upgrade_thread.start()


# ============================================================================
# Enhanced get_session_info() tool — now returns Claude Code metadata
# ============================================================================

@mcp.tool
def get_session_info() -> dict:
    """
    Get current session identification, including Claude Code session_id.

    Returns:
        dict with:
          - project: detected project name
          - session_id: Claude Code session_id (or fallback)
          - sender_id: full sender identifier
          - server_url: Lupin app server URL
          - version: MCP server version
          - claude_code: full metadata from session bridge
    """
    return {
        "project"    : PROJECT,
        "session_id" : SESSION_ID,
        "sender_id"  : SENDER_ID,
        "server_url" : SERVER_URL,
        "version"    : __version__,
        "claude_code": get_session_metadata()
    }


# ============================================================================
# settings.json hook configuration (add to ~/.claude/settings.json)
# ============================================================================

SETTINGS_JSON_HOOK = """
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/register_session.py"
          }
        ]
      }
    ]
  }
}
"""
