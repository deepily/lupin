#!/usr/bin/env python3
"""
PreToolUse hook: voice buffer drain before tool execution.

Fires before every tool call. Does NOT announce tools via TTS (PostToolUse
handles that). Only drains the voice buffer and acknowledges buffered messages.

Install in ~/.claude/settings.json:
    "hooks": {
        "PreToolUse": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/pre_tool_use.py\""
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
    read_hook_input, log_payload, emit_json, drain_and_acknowledge
)
from lupin_cli.claude_code.hooks.lib.session_bridge import get_claude_session_id


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Log full payload for empirical analysis
    log_payload( "pre_tool_use", payload )

    # Resolve session_id: payload first (future-proof), then session bridge fallback
    session_id = payload.get( "session_id", "" ) or get_claude_session_id()

    # Drain voice buffer and acknowledge buffered messages
    # No tool TTS — PostToolUse handles announcements
    drain_and_acknowledge( session_id )

    # Passthrough — no permission decision
    emit_json( {} )


if __name__ == "__main__":
    main()
