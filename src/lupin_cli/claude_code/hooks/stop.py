#!/usr/bin/env python3
"""
Stop hook: voice-driven blocking + stop observability.

When the voice buffer has content, blocks the stop and injects the voice
content as the reason — Claude processes the user's voice input instead
of stopping. When the buffer is empty, allows the stop.

Safety valve: MAX_STOP_BLOCKS consecutive blocks before force-allowing stop.
Loop prevention: if stop_hook_active is True, the hook is being re-invoked
after a block — don't block again.

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
    read_hook_input, log_payload, emit_json, send_tts, drain_and_acknowledge,
    format_voice_context, build_stop_block,
    get_stop_block_count, increment_stop_block_count, reset_stop_block_count,
    MAX_STOP_BLOCKS
)
from lupin_cli.claude_code.hooks.lib.session_bridge import get_claude_session_id


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract stop_hook_active for loop prevention
    stop_hook_active = payload.get( "stop_hook_active", "NOT_PRESENT" )

    # Log full payload for empirical analysis
    log_payload( "stop", payload )

    # Resolve session_id: payload first, then session bridge fallback
    session_id = payload.get( "session_id", "" ) or get_claude_session_id()

    # Loop prevention: if stop_hook_active is True, we already blocked once —
    # don't block again (would create infinite loop)
    if stop_hook_active is True:
        emit_json( {} )
        sys.exit( 0 )

    # Drain voice buffer and acknowledge buffered messages
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )

    if voice_ctx:
        # Check block counter — safety valve
        count = get_stop_block_count( session_id )
        if count >= MAX_STOP_BLOCKS:
            reset_stop_block_count( session_id )
            send_tts( "Stop — max blocks reached, allowing stop" )
            emit_json( {} )
        else:
            increment_stop_block_count( session_id )
            send_tts( "Stop — blocking with voice input" )
            emit_json( build_stop_block( voice_ctx ) )
    else:
        # No voice input → allow stop
        reset_stop_block_count( session_id )
        send_tts( f"Stop — active={stop_hook_active}" )
        emit_json( {} )


if __name__ == "__main__":
    main()
