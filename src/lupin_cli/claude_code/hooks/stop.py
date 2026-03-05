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
import re
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts, drain_and_acknowledge,
    format_voice_context, build_stop_block, enrich_voice_context,
    get_stop_block_count, increment_stop_block_count, reset_stop_block_count,
    MAX_STOP_BLOCKS
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, build_sender_id_for_cc
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest, ResponseType, NotificationPriority
)


def extract_qualifier_comment( response_value ):
    """
    Extract qualifier comment from a yes/no response value.

    Requires:
        - response_value is a string or None

    Ensures:
        - Returns ( answer, qualifier ) tuple
        - answer is "yes" or "no" (lowercase)
        - qualifier is the comment text or None

    Examples:
        "yes [comment: fix the tests]" -> ( "yes", "fix the tests" )
        "no [comment: not ready]"      -> ( "no", "not ready" )
        "yes"                          -> ( "yes", None )
        "no"                           -> ( "no", None )
    """
    if not response_value:
        return ( None, None )

    match = re.match( r'^(yes|no)\s*(?:\[comment:\s*(.+)\])?$', response_value.strip(), re.IGNORECASE )
    if match:
        return ( match.group( 1 ).lower(), match.group( 2 ) )

    # Fallback: treat the whole string as the answer
    return ( response_value.strip().lower(), None )


def _ask_anything_else( session_id ):
    """
    Ask the user "Anything else?" via notify_user_sync with a 5-minute timeout.

    Returns the stop hook JSON to emit: block dict if user wants to continue,
    empty dict if user says no / timeout / error.

    Requires:
        - session_id is a string for sender_id resolution

    Ensures:
        - Returns dict suitable for emit_json()
        - On any exception, returns {} (allow stop gracefully)
    """
    try:
        sender_id = build_sender_id_for_cc( session_id )

        request = NotificationRequest(
            message                  = "[LUPIN] I've finished the current task. Is there anything else you'd like me to do?",
            response_type            = ResponseType.YES_NO,
            priority                 = NotificationPriority.HIGH,
            timeout_seconds          = 300,
            response_default         = "no",
            title                    = "Continue Session?",
            sender_id                = sender_id,
            display_qualifier_widget = True
        )

        response = notify_user_sync( request )

        answer, qualifier = extract_qualifier_comment( response.response_value )

        if answer == "yes":
            if qualifier:
                reason = f"The user wants to continue working. They said: {qualifier}. Address their comment and then ask if there's anything else."
            else:
                reason = "The user wants to continue working. Ask them what they'd like done next."
            return build_stop_block( reason )

        # "no", timeout, error → allow stop
        return {}

    except Exception as e:
        # Server down, network error, import error → allow stop gracefully
        send_tts( f"Stop — notify error: {e}" )
        return {}


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
            emit_json( build_stop_block( enrich_voice_context( voice_ctx ) ) )
    else:
        # No voice input → Phase 2: ask user "Anything else?" via notification
        reset_stop_block_count( session_id )
        result = _ask_anything_else( session_id )
        emit_json( result )


if __name__ == "__main__":
    main()
