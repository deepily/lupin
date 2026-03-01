#!/usr/bin/env python3
"""
Shared library for all Claude Code hook scripts.

Provides common utilities for reading hook input from stdin, logging payloads,
emitting JSON responses, and sending TTS notifications via lupin_cli.notifications.

Usage from hook scripts:
    import sys
    import os
    sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src" ) )
    from lupin_cli.claude_code.hooks.lib.hook_common import (
        read_hook_input, log_payload, emit_json, send_tts, get_target_email,
        is_tts_enabled, build_progress_group_id
    )
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

# Canonical path resolution via cu.get_project_root() — keeps runtime output
# in io/ directory, consistent with existing io/log/ convention.
import cosa.utils.util as cu

LOGS_DIR = Path( cu.get_project_root() ) / "io" / "claude_code_hooks" / "logs"

# Tool classification for smart TTS filtering (PostToolUse)
TOOLS_SILENT   = frozenset( { "Read", "Grep", "Glob", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList" } )
TOOLS_ANNOUNCE = frozenset( { "Bash", "Write", "Edit" } )


# ── Core Functions ────────────────────────────────────────────────────────────

def read_hook_input():
    """
    Read and parse JSON payload from stdin (provided by Claude Code).

    Requires:
        - sys.stdin contains valid JSON

    Ensures:
        - Returns parsed dict with hook payload
        - Returns empty dict on parse failure (non-blocking: never crashes the hook)

    Returns:
        dict: Parsed hook input with session_id, hook_event_name, cwd, etc.
    """
    try:
        return json.load( sys.stdin )
    except ( json.JSONDecodeError, EOFError, ValueError ):
        return {}


def log_payload( hook_name, payload ):
    """
    Write timestamped JSON payload to logs directory for empirical analysis.

    Requires:
        - hook_name is a non-empty string
        - payload is a JSON-serializable dict

    Ensures:
        - Creates logs directory if it doesn't exist
        - Writes payload to logs/{hook_name}-{timestamp}.json
        - Never raises exceptions (logging failure is non-fatal)

    Args:
        hook_name: Name of the hook (e.g., "post_tool_use")
        payload: Full hook input dict to log
    """
    try:
        LOGS_DIR.mkdir( parents=True, exist_ok=True )
        timestamp = datetime.now( timezone.utc ).strftime( "%Y%m%dT%H%M%S_%f" )
        log_file  = LOGS_DIR / f"{hook_name}-{timestamp}.json"

        log_entry = {
            "hook_name"  : hook_name,
            "timestamp"  : get_timestamp(),
            "pid"        : os.getpid(),
            "ppid"       : os.getppid(),
            "payload"    : payload
        }

        with open( log_file, "w" ) as f:
            json.dump( log_entry, f, indent=2, default=str )

    except Exception:
        pass  # Logging failure is non-fatal


def emit_json( data ):
    """
    Emit JSON response to stdout for Claude Code to consume.

    Requires:
        - data is a JSON-serializable dict

    Ensures:
        - Prints JSON string to stdout (single line)
        - Flushes stdout to ensure Claude Code receives it

    Args:
        data: Response dict (hook-specific output)
    """
    print( json.dumps( data ), flush=True )


def get_timestamp():
    """
    Get current UTC timestamp in ISO format.

    Ensures:
        - Returns ISO 8601 formatted string with timezone

    Returns:
        str: ISO timestamp (e.g., "2026-02-26T14:30:00+00:00")
    """
    return datetime.now( timezone.utc ).isoformat()


def get_target_email():
    """
    Resolve notification target email from LUPIN_DEV_EMAIL environment variable.

    Requires:
        - LUPIN_DEV_EMAIL environment variable is set

    Ensures:
        - Returns email string if env var is set
        - Returns None if env var is not set

    Returns:
        str or None: Target email address
    """
    return os.environ.get( "LUPIN_DEV_EMAIL" )


def is_tts_enabled():
    """
    Check if TTS notifications are enabled via HOOK_TTS_ENABLED env var.

    Default is True (enabled). Set HOOK_TTS_ENABLED=false to silence TTS
    while logging continues.

    Ensures:
        - Returns True if env var is missing, empty, or "true"
        - Returns False only if env var is explicitly "false" (case-insensitive)

    Returns:
        bool: Whether TTS notifications should be sent
    """
    value = os.environ.get( "HOOK_TTS_ENABLED", "true" ).strip().lower()
    return value != "false"


def build_progress_group_id( prefix, session_id ):
    """
    Build progress_group_id from hook prefix and session ID.

    Produces IDs like "pt-6c54ecc2" for in-place DOM counter updates.
    Extensible: any hook can call with its own prefix.

    Requires:
        - prefix is a 2-3 char lowercase string (e.g., "pt", "pu", "ss")
        - session_id is a string (may be full UUID or truncated hex)

    Ensures:
        - Returns string matching regex ^[a-z]{2,3}-[a-f0-9]{6,8}(-\\d+)?$
        - Truncates session_id to first 8 chars
        - Falls back to "00000000" if session_id is falsy

    Args:
        prefix: Hook type prefix (e.g., "pt" for PreToolUse, "pu" for PostToolUse)
        session_id: Claude Code session ID (full or truncated)

    Returns:
        str: Progress group ID (e.g., "pt-6c54ecc2")
    """
    hex_part = session_id[:8] if session_id else "00000000"
    return f"{prefix}-{hex_part}"


def send_tts( message, priority="low", sender_id=None, progress_group_id=None ):
    """
    Send fire-and-forget TTS notification via lupin_cli.notifications.

    Uses AsyncNotificationRequest + notify_user_async() for non-blocking delivery.
    Respects HOOK_TTS_ENABLED env var toggle. Silently fails if notification
    infrastructure is unavailable (hooks must never block Claude Code).

    Requires:
        - message is a non-empty string
        - priority is one of: low, medium, high, urgent
        - LUPIN_DEV_EMAIL environment variable is set for target resolution

    Ensures:
        - Sends TTS notification if TTS is enabled and target email is available
        - Auto-resolves sender_id via session bridge when not explicitly provided
        - Passes progress_group_id through to AsyncNotificationRequest for counter grouping
        - Returns silently on any failure (non-blocking)
        - Never raises exceptions

    Args:
        message: TTS message text
        priority: Notification priority (default: "low")
        sender_id: Explicit sender_id string (default: None = auto-resolve from session bridge)
        progress_group_id: Progress group ID for in-place DOM updates (default: None)
    """
    if not is_tts_enabled():
        return

    target_email = get_target_email()
    if not target_email:
        return

    try:
        from lupin_cli.notifications.notification_models import (
            AsyncNotificationRequest,
            NotificationType,
            NotificationPriority
        )
        from lupin_cli.notifications.notify_user_async import notify_user_async

        # Auto-resolve sender_id from session bridge when not explicitly provided
        if sender_id is None:
            try:
                from lupin_cli.claude_code.hooks.lib.session_bridge import build_sender_id_for_cc
                sender_id = build_sender_id_for_cc()
            except Exception:
                pass  # Graceful degradation — notification fires without sender_id

        request = AsyncNotificationRequest(
            message            = message,
            notification_type  = NotificationType.PROGRESS,
            priority           = NotificationPriority( priority ),
            target_user        = target_email,
            sender_id          = sender_id,
            progress_group_id  = progress_group_id,
            timeout            = 3
        )

        notify_user_async( request=request )

    except Exception:
        pass  # Hook must never block Claude Code due to notification failure


# ── Tool Summary + Voice Drain Helpers ────────────────────────────────────────

def format_tool_summary( tool_name, tool_input ):
    """
    Build a concise one-liner for TTS announcements in PostToolUse.

    Requires:
        - tool_name is a string
        - tool_input is a dict or None

    Ensures:
        - Bash: "Bash: <command>" (truncated at 60 chars)
        - Write/Edit: "Write: <basename>" or "Edit: <basename>"
        - Other: just tool_name

    Args:
        tool_name: Name of the tool (e.g., "Bash", "Write")
        tool_input: Tool input dict from hook payload

    Returns:
        str: TTS-friendly tool summary
    """
    if tool_input is None:
        tool_input = {}

    if tool_name == "Bash":
        command = tool_input.get( "command", "" )
        if len( command ) > 60:
            command = command[:60] + "..."
        return f"Bash: {command}" if command else "Bash"

    if tool_name in ( "Write", "Edit" ):
        file_path = tool_input.get( "file_path", "" )
        basename  = os.path.basename( file_path ) if file_path else ""
        return f"{tool_name}: {basename}" if basename else tool_name

    return tool_name


def acknowledge_drained( messages ):
    """
    Send low-priority TTS acknowledgment for each drained voice buffer message.

    Requires:
        - messages is a list of dicts (from drain_voice_buffer)

    Ensures:
        - Sends one low-priority TTS per message
        - Message text truncated at 32 chars
        - Never raises exceptions
        - Does nothing if messages is empty

    Args:
        messages: List of buffered message dicts from voice buffer drain
    """
    for msg in messages:
        text      = msg.get( "message", msg.get( "text", "" ) )
        truncated = text[:32] + "..." if len( text ) > 32 else text
        try:
            send_tts( f"Received: {truncated}", priority="low" )
        except Exception:
            pass  # Acknowledgment failure is non-fatal


def drain_and_acknowledge( session_id ):
    """
    Convenience wrapper: drain voice buffer then acknowledge messages.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Calls drain_voice_buffer( session_id )
        - Calls acknowledge_drained( messages ) for any buffered messages
        - Returns the list of drained messages
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID

    Returns:
        list[dict]: Drained messages (may be empty)
    """
    try:
        messages = drain_voice_buffer( session_id )
        if messages:
            acknowledge_drained( messages )
        return messages
    except Exception:
        return []


# ── Voice Buffer Functions ────────────────────────────────────────────────────

SESSION_DIR = Path.home() / ".claude" / "sessions"


def get_buffer_path( session_id ):
    """
    Get the JSONL buffer file path for a CC session.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns Path to buffer file in ~/.claude/sessions/
        - Truncates session_id to first 8 chars

    Args:
        session_id: Claude Code session ID (full or truncated)

    Returns:
        Path: Buffer file path (e.g., ~/.claude/sessions/cc-buffer-abc12345.jsonl)
    """
    hash_part = session_id[:8] if session_id else "00000000"
    return SESSION_DIR / f"cc-buffer-{hash_part}.jsonl"


def drain_voice_buffer( session_id ):
    """
    Atomically drain the voice buffer for a CC session.

    Implements atomic rename-read-delete pattern:
    1. Rename buffer file to random /tmp/ path (atomic on same filesystem? no,
       but os.rename across filesystems will fail, so we copy+delete)
    2. Read all JSONL lines from temp file
    3. Delete temp file

    Only one concurrent drain succeeds — the first os.rename() wins, others
    get FileNotFoundError and return empty list.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns list of message dicts from buffer
        - Returns empty list if no buffer exists or drain fails
        - Buffer file is consumed (deleted) after successful drain
        - Thread-safe via atomic rename
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID (full or truncated)

    Returns:
        list[dict]: List of buffered message dicts, in chronological order
    """
    buffer_path = get_buffer_path( session_id )

    if not buffer_path.exists():
        return []

    # Random drain path in /tmp to avoid collision with concurrent drains
    hash_part = session_id[:8] if session_id else "00000000"
    drain_id  = uuid.uuid4().hex[:8]
    drain_path = Path( f"/tmp/cc-drain-{hash_part}-{drain_id}.jsonl" )

    try:
        # Atomic rename — only one concurrent drain succeeds
        os.rename( str( buffer_path ), str( drain_path ) )
    except ( FileNotFoundError, OSError ):
        # Another hook already drained it, or file vanished
        return []

    messages = []
    try:
        with open( drain_path ) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append( json.loads( line ) )
                    except json.JSONDecodeError:
                        pass  # Skip malformed lines
    except OSError:
        pass  # File read error — return whatever we got
    finally:
        try:
            drain_path.unlink( missing_ok=True )
        except Exception:
            pass

    return messages


# ── Permission Decision Builder ──────────────────────────────────────────────

def build_permission_decision( behavior, message=None, interrupt=False ):
    """
    Build the hookSpecificOutput dict for a PermissionRequest hook.

    Constructs the JSON structure that Claude Code expects from a
    PermissionRequest hook to allow or deny a tool call.

    Requires:
        - behavior is "allow" or "deny"
        - message is a string or None (only used for deny)
        - interrupt is a bool (only used for deny)

    Ensures:
        - Returns dict with hookSpecificOutput.decision.behavior
        - For "allow": ignores message and interrupt
        - For "deny": includes message and interrupt if provided
        - Structure: { "hookSpecificOutput": { "decision": { ... } } }

    Args:
        behavior: "allow" or "deny"
        message: Optional denial reason (ignored for allow)
        interrupt: Whether to interrupt Claude Code (ignored for allow)

    Returns:
        dict: Hook output ready for emit_json()
    """
    decision = { "behavior": behavior }

    if behavior == "deny":
        if message is not None:
            decision[ "message" ] = message
        if interrupt:
            decision[ "interrupt" ] = True

    return {
        "hookSpecificOutput": {
            "decision": decision
        }
    }


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    print( f"LOGS_DIR:  {LOGS_DIR}" )
    print( f"TTS enabled: {is_tts_enabled()}" )
    print( f"Target email: {get_target_email()}" )
    print( f"Timestamp: {get_timestamp()}" )

    # Test logging
    test_payload = { "test": True, "session_id": "smoke-test" }
    log_payload( "smoke_test", test_payload )
    print( f"Log written to: {LOGS_DIR}/smoke_test-*.json" )

    # Test emit
    print( "\nEmit test:" )
    emit_json( { "status": "ok", "hook": "smoke_test" } )
