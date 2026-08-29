#!/usr/bin/env python3
"""
PermissionRequest hook: voice buffer redirect + auto-allow + sync forwarding.

Three-path flow:
    1. Auto-allow: low-risk tools (Read, Grep, Glob) → immediate allow
    2. Buffer redirect: if voice buffer has content, deny permission and redirect
       Claude to process the user's voice input first (it was spoken before the
       permission request and takes priority as a course-changing instruction)
    3. Sync forward: if buffer is empty, forward to user via notify_user_sync()
       as a blocking yes/no notification

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
    drain_voice_buffer, build_permission_decision, format_voice_context
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, build_sender_id_for_cc, resolve_stable_session_id
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

# Auto-allow low-risk tools that CC may prompt for in certain permission modes
AUTO_ALLOW_TOOLS = frozenset( { "Read", "Grep", "Glob" } )


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

    🔴 A DEFAULT IS NOT A RULING, AND THIS FUNCTION USED TO ERASE THE DIFFERENCE.
    It returned the bare string "deny" for outcomes that are not the same thing:
    the user considered the request and refused it; the user was reached but never
    answered; the user was never reached at all; and the notification failed to
    send. The caller then emitted that denial with NO message, so the one place the
    distinction could still have been recovered discarded it too — leaving a
    refusal indistinguishable from a decision.

    Not a hypothetical confusion: this fleet has already mistaken a timed-out ask
    for the user's answer, recorded "[default used] no" as though Rick had ruled,
    and had to correct the record (row d8d019f6). The response object ALREADY
    carries what separates these cases — default_used, is_timeout, status,
    exit_code — so the information was never missing, only thrown away.

    FOUR OUTCOMES, NOT THREE (María, 2026-08-19). default_used and is_timeout are
    different facts, and collapsing them loses the one a reader most needs:
      · is_timeout            — the ask REACHED the user and ran out of time.
                                They may be present and thinking, or stepped away.
      · default_used, no      — the ask never got an answer path at all (offline /
        timeout                 undeliverable). Nobody was asked anything.
    Re-asking is sensible in the first case and pointless in the second until the
    user is back, so the reason has to say WHICH.

    ⚠️ THE REASON DOES NOT MOVE THE DECISION. DEFAULT_ON_TIMEOUT stays "deny" and
    every non-yes outcome still denies — Rick's ruling was to weaken no refusal.
    All that changes is that a denial now says which kind it is.

    Requires:
        - tool_description is a non-empty string
        - session_id is a string (for sender_id resolution)

    Ensures:
        - Returns ( "allow", None ) if and only if the user answered yes
        - Returns ( "deny", reason ) otherwise, where reason NAMES the cause:
          user refused / reached but unanswered / never reached / delivery failed
        - Denies on every non-yes outcome, unchanged
        - Blocks for at most SYNC_TIMEOUT_SECONDS + network overhead
        - Never raises exceptions

    Args:
        tool_description: Human-readable description of the tool request
        session_id: Claude Code session_id for sender_id resolution

    Returns:
        tuple: ( "allow" | "deny", reason_or_None )
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

        answer = ( response.response_value or "" ).strip().lower()
        status = response.status or "unknown"

        # NO-ANSWER CASES FIRST, and deliberately before reading the value. On a timeout
        # the response still carries response_default ("deny"), so a value-first check
        # would read that default back and present it as though the user had said it.

        # (a) REACHED THE USER, RAN OUT OF TIME. Re-asking is reasonable.
        if response.is_timeout:
            return ( "deny",
                     f"DENIED BY TIMEOUT, NOT BY THE USER. The request for "
                     f"'{tool_description}' was delivered but no answer came within "
                     f"{SYNC_TIMEOUT_SECONDS}s (status: {status}), so the security-safe "
                     f"default was applied. The user has NOT refused this. They may be "
                     f"present and considering it — asking again is reasonable." )

        # (b) NEVER REACHED THE USER. Re-asking is pointless until they are back.
        if response.default_used:
            return ( "deny",
                     f"DENIED WITHOUT REACHING THE USER. The request for "
                     f"'{tool_description}' never got to anyone (status: {status}), so the "
                     f"security-safe default was applied. Nobody was asked, so this is not "
                     f"a refusal — and re-asking will not help until the user is reachable." )

        if answer == "yes":
            return ( "allow", None )

        if answer == "no":
            return ( "deny", f"The user was asked and answered NO to: {tool_description}" )

        # Answered, not timed out, but the value is not one this hook understands.
        return ( "deny",
                 f"DENIED WITHOUT A USABLE ANSWER. The request for '{tool_description}' "
                 f"returned {response.response_value!r} (status: {status}, exit_code: "
                 f"{response.exit_code}), which is neither yes nor no. Not a decision by "
                 f"the user." )

    except Exception as e:
        # Any failure → deny (security-safe), named as a delivery failure so it is never
        # read as the user having refused.
        print( f"Permission forward error: {e}", file=sys.stderr )
        return ( "deny",
                 f"DENIED BECAUSE THE REQUEST COULD NOT BE DELIVERED: {e}. The user was "
                 f"never asked about '{tool_description}' — an infrastructure failure, "
                 f"not a refusal." )


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    """
    PermissionRequest hook entry point.

    Three-path flow:
        Path A: Auto-allow (low-risk tools) → immediate allow, no sync
        Path B: Buffer redirect (voice content) → deny + redirect Claude
        Path C: Sync forward (buffer empty) → blocking yes/no to user

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
        session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

        # Path A: Auto-allow low-risk tools
        if tool_name in AUTO_ALLOW_TOOLS:
            send_tts( f"Auto-allow: {tool_name}", priority="low" )
            emit_json( build_permission_decision( "allow" ) )
            sys.exit( 0 )

        # Phase 4: Drain voice buffer
        messages = drain_voice_buffer( session_id )

        if messages:
            # Path B: Buffer has content → deny + redirect Claude
            # Voice content was spoken BEFORE the permission request —
            # it's a course-changing instruction that takes priority.
            _acknowledge_buffered_messages( messages )
            voice_ctx    = format_voice_context( messages )
            redirect_msg = (
                "The user said this before you asked for permission. "
                "You must attend to their comments or questions before you "
                "request permission again — if you still need to after taking "
                "their possibly course-changing input into consideration first. "
                f"User said: {voice_ctx}"
            )
            send_tts( "Voice input received — redirecting Claude", priority="medium" )
            emit_json( build_permission_decision( "deny", message=redirect_msg ) )
            sys.exit( 0 )

        # Path C: Buffer empty → forward to user via sync yes/no
        decision, reason = _forward_to_user( tool_desc, session_id )

        # Emit the decision WITH its reason. Passing it is the whole point: every other
        # deny path in this function already explains itself, and this one — the only
        # path where a human is involved — was the silent one.
        # build_permission_decision ignores message on "allow".
        emit_json( build_permission_decision( decision, message=reason ) )

    except Exception as e:
        # Catch-all: deny on any unhandled error
        print( f"PermissionRequest hook error: {e}", file=sys.stderr )
        emit_json( build_permission_decision( "deny", message=f"Hook error: {e}" ) )


if __name__ == "__main__":
    main()
