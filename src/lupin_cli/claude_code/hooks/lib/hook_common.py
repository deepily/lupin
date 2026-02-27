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
        read_hook_input, log_payload, emit_json, send_tts, get_target_email, is_tts_enabled
    )
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

HOOKS_DIR  = Path( __file__ ).parent.parent
LOGS_DIR   = HOOKS_DIR / "logs"


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


def send_tts( message, priority="low", sender_id=None ):
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
        - Returns silently on any failure (non-blocking)
        - Never raises exceptions

    Args:
        message: TTS message text
        priority: Notification priority (default: "low")
        sender_id: Explicit sender_id string (default: None = auto-resolve from session bridge)
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
            message           = message,
            notification_type = NotificationType.PROGRESS,
            priority          = NotificationPriority( priority ),
            target_user       = target_email,
            sender_id         = sender_id,
            timeout           = 3
        )

        notify_user_async( request=request )

    except Exception:
        pass  # Hook must never block Claude Code due to notification failure


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    print( f"HOOKS_DIR: {HOOKS_DIR}" )
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
