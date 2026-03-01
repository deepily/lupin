#!/usr/bin/env python3
"""
Stop hook: voice buffer drain + stop observability.

Drains the voice buffer, acknowledges buffered messages, logs stop_hook_active
for observability, and emits {} (allow stop).

Install in ~/.claude/settings.json:
    "hooks": {
        "Stop": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/stop.py\""
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
from lupin_cli.claude_code.hooks.lib.session_bridge import get_claude_session_id


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract stop_hook_active for observability
    stop_hook_active = payload.get( "stop_hook_active", "NOT_PRESENT" )

    # Log full payload for empirical analysis
    log_payload( "stop", payload )

    # Resolve session_id: payload first, then session bridge fallback
    session_id = payload.get( "session_id", "" ) or get_claude_session_id()

    # Drain voice buffer and acknowledge buffered messages
    drain_and_acknowledge( session_id )

    # Send TTS notification (respects HOOK_TTS_ENABLED)
    send_tts( f"Stop — active={stop_hook_active}" )

    # Allow stop (emit empty = passthrough)
    emit_json( {} )


if __name__ == "__main__":
    main()
