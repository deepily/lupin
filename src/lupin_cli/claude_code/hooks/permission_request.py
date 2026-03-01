#!/usr/bin/env python3
"""
PermissionRequest hook: voice buffer drain + sync notification forwarding.

Checks the voice buffer for pre-buffered messages (acknowledgment only),
then ALWAYS forwards the permission decision to the user via notify_user_sync()
as a blocking yes/no notification. User responds via voice or browser card.

Flow:
    1. Read hook input (tool_name, tool_input, session_id)
    2. Log payload
    3. Build human-readable tool description
    4. Drain voice buffer — acknowledge buffered messages (no decision impact)
    5. Forward to user via notify_user_sync() — blocking yes/no, always runs
    6. Emit permission decision (allow/deny)

Install in ~/.claude/settings.json:
    "hooks": {
        "PermissionRequest": [{
            "hooks": [{
                "type": "command",
                "timeout": 30000,
                "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/permission_request.py\""
            }]
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
    read_hook_input, log_payload, emit_json, send_tts,
    drain_voice_buffer, build_permission_decision
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, build_sender_id_for_cc
)
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    ResponseType,
    NotificationPriority
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync


# ── Constants ────────────────────────────────────────────────────────────────

SYNC_TIMEOUT_SECONDS = 25   # 5s headroom under CC's 30s hook timeout
DEFAULT_ON_TIMEOUT   = "deny"  # Security-safe default


# ── Helper Functions ─────────────────────────────────────────────────────────

def _format_tool_description( tool_name, tool_input ):
    """
    Build a concise human-readable description of the tool being requested.

    Requires:
        - tool_name is a string (may be empty)
        - tool_input is a dict or None

    Ensures:
        - Bash: "Bash: <command>" (command truncated at 100 chars)
        - Write/Edit: "Write: <basename>" or "Edit: <basename>"
        - Other tools: just the tool name
        - Returns non-empty string

    Args:
        tool_name: Name of the tool (e.g., "Bash", "Write", "Edit")
        tool_input: Tool input dict from hook payload

    Returns:
        str: Human-readable tool description
    """
    if not tool_name:
        return "unknown tool"

    if tool_input is None:
        tool_input = {}

    if tool_name == "Bash":
        command = tool_input.get( "command", "" )
        if len( command ) > 100:
            command = command[:100] + "..."
        return f"Bash: {command}" if command else "Bash"

    if tool_name in ( "Write", "Edit" ):
        file_path = tool_input.get( "file_path", "" )
        basename  = os.path.basename( file_path ) if file_path else ""
        return f"{tool_name}: {basename}" if basename else tool_name

    return tool_name


def _acknowledge_buffered_messages( messages ):
    """
    Send low-priority acknowledgment for each buffered voice message.

    This is purely an acknowledgment step — does NOT influence the
    permission decision. Each message gets a fire-and-forget TTS
    notification so the sender knows their message was received.

    Requires:
        - messages is a list of dicts (from drain_voice_buffer)

    Ensures:
        - Sends one low-priority TTS per message
        - Message text truncated at 32 chars in the acknowledgment
        - Never raises exceptions
        - Does nothing if messages is empty

    Args:
        messages: List of buffered message dicts from voice buffer drain
    """
    for msg in messages:
        text = msg.get( "message", msg.get( "text", "" ) )
        truncated = text[:32] + "..." if len( text ) > 32 else text
        try:
            send_tts( f"Received: {truncated}", priority="low" )
        except Exception:
            pass  # Acknowledgment failure is non-fatal


def _forward_to_user( tool_description, session_id ):
    """
    Forward permission request to user via blocking sync notification.

    Sends a yes/no notification card with TTS announcement. Blocks until
    the user responds, timeout occurs, or an error happens. Defaults to
    "deny" on timeout/error for security safety.

    Requires:
        - tool_description is a non-empty string
        - session_id is a string (for sender_id resolution)

    Ensures:
        - Returns "allow" if user responds "yes"
        - Returns "deny" if user responds "no", timeout, or error
        - Blocks for at most SYNC_TIMEOUT_SECONDS + network overhead
        - Never raises exceptions

    Args:
        tool_description: Human-readable description of the tool request
        session_id: Claude Code session_id for sender_id resolution

    Returns:
        str: "allow" or "deny"
    """
    try:
        resolved_sender_id = build_sender_id_for_cc( session_id )

        request = NotificationRequest(
            message          = f"Permission requested: {tool_description}",
            response_type    = ResponseType.YES_NO,
            priority         = NotificationPriority.HIGH,
            timeout_seconds  = SYNC_TIMEOUT_SECONDS,
            response_default = DEFAULT_ON_TIMEOUT,
            title            = "Permission Request",
            sender_id        = resolved_sender_id
        )

        response = notify_user_sync( request=request )

        # Map response to allow/deny
        if response.response_value and response.response_value.strip().lower() == "yes":
            return "allow"
        return "deny"

    except Exception as e:
        # Any failure → deny (security-safe)
        print( f"Permission forward error: {e}", file=sys.stderr )
        return "deny"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    """
    PermissionRequest hook entry point.

    Six phases:
        1. Read hook input
        2. Log payload
        3. Build tool description
        4. Drain voice buffer (acknowledge only, no decision impact)
        5. Forward to user via notify_user_sync (blocking yes/no)
        6. Emit permission decision

    Ensures:
        - Always emits a valid JSON decision (allow or deny)
        - Defaults to deny on any unhandled error
        - Never crashes Claude Code
    """
    try:
        # Phase 1: Read hook input
        payload = read_hook_input()
        if not payload:
            emit_json( build_permission_decision( "deny", message="Empty hook payload" ) )
            sys.exit( 0 )

        # Phase 2: Log payload
        log_payload( "permission_request", payload )

        # Phase 3: Build tool description
        tool_name  = payload.get( "tool_name", "" )
        tool_input = payload.get( "tool_input", {} )
        tool_desc  = _format_tool_description( tool_name, tool_input )

        # Resolve session_id: payload first, then session bridge fallback
        session_id = payload.get( "session_id", "" ) or get_claude_session_id()

        # Phase 4: Drain voice buffer — acknowledgment only
        messages = drain_voice_buffer( session_id )
        if messages:
            _acknowledge_buffered_messages( messages )

        # Phase 5: Forward to user — blocking sync yes/no
        decision = _forward_to_user( tool_desc, session_id )

        # Phase 6: Emit decision
        emit_json( build_permission_decision( decision ) )

    except Exception as e:
        # Catch-all: deny on any unhandled error
        print( f"PermissionRequest hook error: {e}", file=sys.stderr )
        emit_json( build_permission_decision( "deny", message=f"Hook error: {e}" ) )


if __name__ == "__main__":
    main()
