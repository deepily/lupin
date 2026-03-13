#!/usr/bin/env python3
"""
Notification hook: message-aware TTS relay + voice buffer drain.

Relays CC system notifications with type-specific TTS content:
- permission_prompt: includes the full message text
- idle_prompt: announces idle state with message
- other: includes truncated message (80 chars)

Observation-only (output is ignored by CC).

Install in ~/.claude/settings.json:
    "hooks": {
        "Notification": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/notification.py\""
        }]
    }
"""
import os
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts, drain_and_acknowledge
)
from lupin_cli.claude_code.hooks.lib.session_bridge import get_claude_session_id, resolve_stable_session_id


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract notification details
    notification_type = payload.get( "type", payload.get( "notification_type", "unknown" ) )
    message           = payload.get( "message", "" )

    # Log full payload for empirical analysis
    log_payload( "notification", payload )

    # Resolve session_id: payload first, then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

    # Drain voice buffer and acknowledge buffered messages
    drain_and_acknowledge( session_id )

    # Type-specific TTS content (respects HOOK_TTS_ENABLED)
    # Permission prompts use high priority so TTS speaks them aloud —
    # the user needs to hear these to know Claude needs approval.
    if notification_type == "permission_prompt":
        tts_msg      = message if message else "Permission prompt"
        tts_priority = "high"
    elif notification_type == "idle_prompt":
        tts_msg      = message if message else "Claude is waiting for input"
        tts_priority = "low"
    else:
        if message:
            truncated = message[:80] + "..." if len( message ) > 80 else message
            tts_msg   = f"Notification ({notification_type}): {truncated}"
        else:
            tts_msg = f"Notification: {notification_type}"
        tts_priority = "low"

    send_tts( tts_msg, priority=tts_priority )

    # Observation-only — output is ignored by CC
    emit_json( {} )


if __name__ == "__main__":
    main()
