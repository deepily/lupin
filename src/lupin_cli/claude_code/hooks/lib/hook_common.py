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
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

# Canonical path resolution via cu.get_project_root() — keeps runtime output
# in io/ directory, consistent with existing io/log/ convention.
import cosa.utils.util as cu

LOGS_DIR    = Path( cu.get_project_root() ) / "io" / "claude_code_hooks" / "logs"
STREAM_LOG  = LOGS_DIR / "hook-events.jsonl"

# Tool classification for smart TTS filtering (PostToolUse)
TOOLS_SILENT   = frozenset( { "Read", "Grep", "Glob", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList" } )
TOOLS_ANNOUNCE = frozenset( { "Bash", "Write", "Edit" } )

# MCP voice tool prefix — skip drain when Claude is already talking to user
MCP_VOICE_PREFIX = "mcp__cosa-voice__"

# Stop hook safety valve — max consecutive blocks before allowing stop
MAX_STOP_BLOCKS = 3

# Delay before tmux injection after stop block (seconds)
TMUX_INJECTION_DELAY = 0.25


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


def log_to_stream( hook_name, payload, extra=None ):
    """
    Append single-line JSON entry to hook-events.jsonl for tail -f debugging.

    Requires:
        - hook_name is a non-empty string
        - payload is a dict or None

    Ensures:
        - Creates logs directory if it doesn't exist
        - Appends one compact JSON line to STREAM_LOG
        - Includes hook name, timestamp, PID, and compact payload summary
        - Extra dict fields are merged into the entry when provided
        - Never raises exceptions (logging failure is non-fatal)

    Args:
        hook_name: Name of the hook (e.g., "stop", "mcp_ask_yes_no")
        payload: Hook input dict (only summary fields extracted)
        extra: Optional dict of hook-specific fields to merge into entry
    """
    try:
        LOGS_DIR.mkdir( parents=True, exist_ok=True )
        entry = {
            "ts"   : get_timestamp(),
            "hook" : hook_name,
            "pid"  : os.getpid(),
        }
        # Compact payload summary (avoid multi-MB last_assistant_message dumps)
        if isinstance( payload, dict ):
            entry[ "event" ]      = payload.get( "hook_event_name", "" )
            from lupin_cli.claude_code.hooks.lib.session_bridge import resolve_stable_session_id
            raw_sid = payload.get( "session_id", "" )
            entry[ "session_id" ] = resolve_stable_session_id( raw_sid )[:8]
            entry[ "tool" ]       = payload.get( "tool_name", "" )
        if extra:
            entry.update( extra )
        with open( STREAM_LOG, "a" ) as f:
            f.write( json.dumps( entry, default=str ) + "\n" )
    except Exception:
        pass  # Logging failure is non-fatal


def log_payload( hook_name, payload ):
    """
    Write timestamped JSON payload to logs directory for empirical analysis.

    Requires:
        - hook_name is a non-empty string
        - payload is a JSON-serializable dict

    Ensures:
        - Creates logs directory if it doesn't exist
        - Writes payload to logs/{hook_name}-{timestamp}.json
        - Appends compact summary to JSONL stream (via log_to_stream)
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

    log_to_stream( hook_name, payload )


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
    Get current UTC timestamp in human-readable format.

    Ensures:
        - Returns formatted string with date, time, and milliseconds

    Returns:
        str: Formatted timestamp (e.g., "2026.03.12 @ 17:15 56,123ms")
    """
    now = datetime.now( timezone.utc )
    return now.strftime( "%Y.%m.%d @ %H:%M %S" ) + f",{now.microsecond // 1000:03d}ms"


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


def send_tts( message, priority="low", sender_id=None, progress_group_id=None, suppress_ding=False ):
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
            suppress_ding      = suppress_ding,
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
    No-op — gist auto-response is now handled by CCNotificationListener
    at message receipt time, not at drain time.

    Kept for API compatibility with drain_and_acknowledge().
    """
    pass


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


# ── Voice Context Injection Helpers ───────────────────────────────────────────

def format_voice_context( messages ):
    """
    Format drained voice messages into a [Voice] context string for CC injection.

    Requires:
        - messages is a list of dicts (from drain_voice_buffer)

    Ensures:
        - Returns empty string if messages is empty or all messages are blank
        - Each non-empty message gets a "[Voice]: " prefix
        - Messages are joined with newlines
        - Whitespace is stripped from each message

    Args:
        messages: List of buffered message dicts from voice buffer drain

    Returns:
        str: Newline-joined "[Voice]: ..." context string, or ""
    """
    if not messages:
        return ""
    lines = []
    for msg in messages:
        text = msg.get( "message", msg.get( "text", "" ) ).strip()
        if text:
            lines.append( f"[Voice]: {text}" )
    return "\n".join( lines )


def build_additional_context( context_text, hook_event_name ):
    """
    Build hookSpecificOutput dict with additionalContext for UserPromptSubmit/PostToolUse/PreToolUse.

    Requires:
        - context_text is a string
        - hook_event_name is the event identifier expected by Claude Code's
          hook output schema, e.g. "UserPromptSubmit", "PostToolUse", "PreToolUse"

    Ensures:
        - Returns {} when context_text is empty or falsy (passthrough)
        - Returns { "hookSpecificOutput": { "hookEventName": ..., "additionalContext": ... } } when non-empty

    Args:
        context_text: Formatted voice context string
        hook_event_name: Hook event identifier required by Claude Code schema

    Returns:
        dict: Hook output ready for emit_json(), or empty dict
    """
    if not context_text:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName"   : hook_event_name,
            "additionalContext": context_text
        }
    }


def enrich_voice_context( voice_ctx ):
    """
    Append notification reminder suffix to voice context string.

    Used by all hooks (PreToolUse, PostToolUse, Stop) to ensure Claude
    always gets the cosa-voice acknowledgment instruction alongside
    voice content.

    Requires:
        - voice_ctx is a string (may be empty)

    Ensures:
        - Returns empty string if voice_ctx is empty/falsy (passthrough)
        - Returns voice_ctx + notification reminder when non-empty

    Args:
        voice_ctx: Formatted voice context string from format_voice_context()

    Returns:
        str: Enriched voice context with reminder, or ""
    """
    if not voice_ctx:
        return ""
    return (
        f"{voice_ctx}\n\n"
        "IMPORTANT: You MUST acknowledge the user's voice message by sending "
        "a high-priority notification via mcp__cosa-voice__notify() or "
        "mcp__cosa-voice__converse() so the user receives immediate audio "
        "feedback that their query is being attended to. Do NOT rely on "
        "terminal text output alone — the user is not watching the terminal."
    )


def build_voice_deny_response( voice_ctx ):
    """
    Build PreToolUse deny response when voice buffer has content.

    Combines permissionDecision deny (blocks tool, forces attention)
    with additionalContext (persists voice message into subsequent turns).

    Requires:
        - voice_ctx is a non-empty string containing formatted voice messages

    Ensures:
        - Returns dict with hookSpecificOutput containing:
          - hookEventName: "PreToolUse"
          - permissionDecision: "deny"
          - permissionDecisionReason: instruction to address voice message first
          - additionalContext: voice content + notification reminder
        - Structure is ready for emit_json()

    Args:
        voice_ctx: Formatted voice context string from format_voice_context()

    Returns:
        dict: Hook output that denies the tool call and injects voice context
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : (
                "A user-initiated voice message was received and takes precedence "
                "over this tool call. You must address the user's message before "
                "continuing. You may re-run this tool afterward if still needed."
            ),
            "additionalContext"        : enrich_voice_context( voice_ctx )
        }
    }


def build_stop_block( reason ):
    """
    Build top-level decision block for Stop hook.

    The Stop hook uses a different structure than PreToolUse/PostToolUse —
    it emits a top-level "decision" + "reason" dict (NOT wrapped in
    hookSpecificOutput).

    Requires:
        - reason is a non-empty string

    Ensures:
        - Returns { "decision": "block", "reason": reason }

    Args:
        reason: Human-readable reason for blocking the stop

    Returns:
        dict: Stop hook decision block ready for emit_json()
    """
    return { "decision": "block", "reason": reason }


def build_stop_block_with_system_message( reason, system_message ):
    """
    Build top-level decision block for Stop hook with systemMessage injection.

    DEPRECATED (Session 336): systemMessage is silently ignored by CC Stop hooks.
    Qualifier injection now uses inject_qualifier_via_tmux(). Kept for test compatibility.

    When a qualifier is present, the stop hook needs BOTH:
    - "reason" for hook logging/metadata (low salience, not reliably acted on)
    - "systemMessage" for conversation injection (high salience, visible to model)

    Requires:
        - reason is a non-empty string (short metadata summary)
        - system_message is a non-empty string (full instruction for the model)

    Ensures:
        - Returns { "decision": "block", "reason": reason, "systemMessage": system_message }

    Args:
        reason: Short metadata reason for blocking the stop
        system_message: Full instruction injected into Claude's conversation context

    Returns:
        dict: Stop hook decision block with systemMessage, ready for emit_json()
    """
    return {
        "decision"      : "block",
        "reason"        : reason,
        "systemMessage" : system_message
    }


def inject_qualifier_via_tmux( session_id, text, delay=TMUX_INJECTION_DELAY ):
    """
    Inject qualifier text into Claude Code's tmux input via detached background process.

    After a stop block, CC enters "waiting for user input" state. This spawns a
    background process that sleeps briefly, then uses tmux send-keys to inject the
    qualifier text as first-class user input. Uses bash positional args ($1, $2, $3)
    to safely pass text without shell escaping.

    Requires:
        - session_id is a non-empty string
        - text is a non-empty string (the qualifier to inject)
        - delay is a positive float (seconds before injection)

    Ensures:
        - Resolves tmux session name from session_id via find_session_by_id()
        - Spawns detached subprocess (start_new_session=True)
        - Background process: sleep → tmux send-keys -l → Enter
        - Returns silently if session not found or on any failure
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID (full or truncated)
        text: Qualifier text to inject into CC's input
        delay: Seconds to wait before tmux injection (default: TMUX_INJECTION_DELAY)
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id

        session_data = find_session_by_id( session_id )
        if not session_data:
            log_to_stream( "stop", {}, extra={
                "phase"   : "qualifier_tmux_inject_skip",
                "reason"  : "no session found",
                "session" : session_id[:8] if session_id else ""
            } )
            return

        tmux_session = session_data.get( "tmux_session" )
        if not tmux_session:
            log_to_stream( "stop", {}, extra={
                "phase"   : "qualifier_tmux_inject_skip",
                "reason"  : "no tmux_session in bridge data",
                "session" : session_id[:8] if session_id else ""
            } )
            return

        # Phase 5b — speakerphone rider: wrap qualifier text with the per-turn
        # rider. The qualifier comes from the user's reply to the idle-aware
        # Stop hook's "Anything else?" prompt and is injected back into
        # Claude's input — clear inbound path.
        # See: src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/14-phase5-hook-rider-design.md
        try:
            text = speakerphone_wrap(
                text,
                source     = "hook-idle-prompt",
                session_id = session_id
            )
        except Exception:
            pass  # Non-fatal — fall through with raw text

        subprocess.Popen(
            [ "bash", "-c",
              'sleep "$1" && tmux send-keys -t "$2" -l -- "$3" && sleep 0.25 && tmux send-keys -t "$2" Enter',
              "_",              # $0 placeholder
              str( delay ),    # $1
              tmux_session,    # $2
              text             # $3
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except Exception:
        pass  # Hook must never block Claude Code


def is_mcp_voice_tool( tool_name ):
    """
    Check if tool_name is a cosa-voice MCP tool (direct user communication).

    When Claude calls cosa-voice MCP tools, the LLM is already communicating
    directly with the user. Hooks should NOT drain the buffer or inject context
    during those calls — it would interfere with an active voice conversation.

    Requires:
        - tool_name is a string or None

    Ensures:
        - Returns True if tool_name starts with MCP_VOICE_PREFIX
        - Returns False if tool_name is empty, None, or doesn't match

    Args:
        tool_name: Name of the tool being called

    Returns:
        bool: True if this is a cosa-voice MCP tool
    """
    return tool_name.startswith( MCP_VOICE_PREFIX ) if tool_name else False


# ── Stop Block Counter (safety valve) ────────────────────────────────────────

def _stop_counter_path( session_id ):
    """
    Get the path to the stop block counter file for a CC session.

    Args:
        session_id: Claude Code session ID

    Returns:
        Path: Counter file path in /tmp/
    """
    hash_part = session_id[:8] if session_id else "00000000"
    return Path( f"/tmp/claude-hook-stop-count-{hash_part}" )


def get_stop_block_count( session_id ):
    """
    Read the current block count from the stop counter file.

    Requires:
        - session_id is a string

    Ensures:
        - Returns integer count (0 if file doesn't exist or is unreadable)
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID

    Returns:
        int: Current block count
    """
    try:
        path = _stop_counter_path( session_id )
        if path.exists():
            return int( path.read_text().strip() )
    except ( ValueError, OSError ):
        pass
    return 0


def increment_stop_block_count( session_id ):
    """
    Increment and persist the stop block count. Returns the new count.

    Requires:
        - session_id is a string

    Ensures:
        - Increments count by 1
        - Persists to file
        - Returns new count
        - Returns 1 on first call (file created)
        - Never raises exceptions (returns 0 on failure)

    Args:
        session_id: Claude Code session ID

    Returns:
        int: New block count after increment
    """
    try:
        count = get_stop_block_count( session_id ) + 1
        path  = _stop_counter_path( session_id )
        path.write_text( str( count ) )
        return count
    except OSError:
        return 0


def reset_stop_block_count( session_id ):
    """
    Reset the stop block count to 0 (deletes the counter file).

    Requires:
        - session_id is a string

    Ensures:
        - Counter file is deleted if it exists
        - Never raises exceptions

    Args:
        session_id: Claude Code session ID
    """
    try:
        path = _stop_counter_path( session_id )
        path.unlink( missing_ok=True )
    except OSError:
        pass


# ── Turn Start Marker (duration gating for stop hook) ─────────────────────────

TURN_MARKER_DIR = Path( "/tmp" )


def write_turn_start_marker( session_id ):
    """
    Write epoch timestamp to /tmp/cc-turn-start-{session_id[:8]}.

    Called by UserPromptSubmit hook to record when the user's prompt was submitted.
    The stop hook reads this marker to compute turn duration for gating.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Creates/overwrites marker file with current epoch timestamp
        - Never raises exceptions
    """
    try:
        marker = TURN_MARKER_DIR / f"cc-turn-start-{session_id[ :8 ]}"
        marker.write_text( str( time.time() ) )
    except OSError:
        pass  # Marker write failure is non-fatal


def get_turn_elapsed_seconds( session_id ):
    """
    Read turn start marker and return elapsed seconds since user prompt.

    Requires:
        - session_id is a non-empty string

    Ensures:
        - Returns float elapsed seconds if marker exists and is readable
        - Returns None if marker missing or unreadable (safe fallback)
        - Never raises exceptions

    Returns:
        float or None: Elapsed seconds since turn start, or None
    """
    try:
        marker      = TURN_MARKER_DIR / f"cc-turn-start-{session_id[ :8 ]}"
        start_epoch = float( marker.read_text().strip() )
        return time.time() - start_epoch
    except ( FileNotFoundError, ValueError, OSError ):
        return None


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


# ── Speakerphone Wrap (per-turn rider) ────────────────────────────────────────
#
# Per src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/14-phase5-hook-rider-design.md
# (predecessor: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md)
# Phase 5b: wrap inbound text with a <system-reminder> rider on every turn.
# Body varies by (tts_interaction_mode, speakerphone_on) per a 4-variant
# matrix (solo+speaker / solo+phone / chorus+speaker / chorus+phone).
# Sanitization at the boundary closes the prompt-injection escape vector
# (§2.4a of the predecessor design doc).

# Markers stripped by sanitize_for_wrap to prevent user content from escaping
# the wrapper or injecting a fake system-reminder. First-marker-wins; case
# insensitive.
_SANITIZE_MARKERS = ( "</voice-message", "<system-reminder" )

# Sentinel substring used to detect already-wrapped strings for idempotency.
# Appears in BOTH on-variant and off-variant rider bodies so the check is
# universal across the 4-variant matrix.
_SPEAKERPHONE_WRAP_SENTINEL = "This session has speakerphone mode"


def sanitize_for_wrap( text ):
    """
    Strip user content from the first occurrence of </voice-message or
    <system-reminder (case-insensitive) to end-of-string. Closes the
    prompt-injection escape vector at the wrapper boundary.

    Requires:
        - text is a string

    Ensures:
        - Returns text unchanged if neither marker present
        - Returns text[ :first_marker_index ] if either marker present
        - Whichever marker appears first wins (first-marker-wins)
        - Match is case-insensitive (lower() comparison)
        - Empty input returns empty

    Args:
        text: Raw user content prior to wrapping

    Returns:
        str: Sanitized content safe for substitution into the wrapper
    """
    if not text: return text

    lower   = text.lower()
    indices = [ lower.find( m ) for m in _SANITIZE_MARKERS ]
    indices = [ i for i in indices if i >= 0 ]
    if not indices: return text

    return text[ :min( indices ) ]


def _source_preamble( source ):
    """
    Build the source-attribution preamble for the rider — one sentence that
    names where the input came from. Helpful for Claude's framing and for
    transcript readability.

    Requires:
        - source is a string

    Ensures:
        - Returns a single-sentence string for known sources
        - Returns empty string for unknown sources (defensive)

    Args:
        source: Which injection point the text came from

    Returns:
        str: Preamble sentence or empty string
    """
    if source == "voice":
        return "The user spoke the above as a voice message from a distance."
    if source == "terminal-typed":
        return "The user typed the above at the terminal."
    if source == "hook-idle-prompt":
        return "The Stop hook fired the above as an idle-aware re-prompt."
    if source == "hook-permission-prompt":
        return "A permission-request hook synthesized the above prompt."
    return ""


def _brevity_rules():
    """
    The TTS brevity-rules block migrated from CLAUDE.md per Phase 5 of the
    speakerphone refactor. Fires only when speakerphone_on=True (live TTS).

    Ensures:
        - Returns a non-empty paragraph describing how the closing `notify()`
          spoken-text should differ from the terminal reply

    Returns:
        str: Brevity guidance text
    """
    return (
        "Brevity for TTS: re-craft the spoken `message` for speech, do NOT pipe "
        "terminal markdown through `notify()`. Strip headings, bullets, fenced "
        "code blocks, inline backticks, file:line refs, JSON, hashes, and URLs "
        "from the spoken text — those are TTS-hostile. Routine closings about "
        "60 words; substantive turns 80-120 words. Speak the verdict, not the "
        "inventory. Acknowledge receipt at turn-start in one sentence BEFORE "
        "tool calls. Rich detail goes in the `abstract` parameter (rendered to "
        "the UI card); the two channels are complementary, not duplicates."
    )


def _routing_reminder():
    """
    The cosa-voice routing-reminder block migrated from CLAUDE.md per Phase 5
    of the speakerphone refactor. Fires when speakerphone_on=True so the model
    uses voice tools rather than the terminal-only AskUserQuestion fallback.

    Ensures:
        - Returns a non-empty paragraph mapping interaction types to cosa-voice
          MCP blocking tools

    Returns:
        str: Routing reminder text
    """
    return (
        "Interactive tool routing: PREFER cosa-voice MCP blocking tools over "
        "AskUserQuestion. Yes/no goes to `ask_yes_no`. Two to four options "
        "goes to `ask_multiple_choice`. Open-ended goes to `converse`. Multiple "
        "open-ended goes to `ask_open_ended_batch`. AskUserQuestion renders to "
        "the terminal only — the user is listening, not watching."
    )


def _speakerphone_reminder_body( source, mode, speakerphone_on ):
    """
    Build the per-turn rider body for the given (source, mode, speakerphone_on)
    triple. The body is plain text — no wrapping <system-reminder> tags
    (those are added by the caller).

    Per the Phase 5 design, the rider fires on every turn; content varies by
    state, not whether it fires. Composition by variant:

    - Source preamble (1 sentence) — always
    - Speakerphone state notice — always (ON: notify-after; OFF: no notify)
    - Brevity rules — speakerphone_on=True only
    - Routing reminder — speakerphone_on=True only
    - Mode-specific monopoly notice — mode="solo" only
    - Multi-voice notice — mode="chorus" and speakerphone_on=True only

    Requires:
        - source is one of: "voice", "terminal-typed",
          "hook-idle-prompt", "hook-permission-prompt"
        - mode is "solo" or "chorus"
        - speakerphone_on is a bool

    Ensures:
        - Returns a non-empty string body
        - Always contains the _SPEAKERPHONE_WRAP_SENTINEL substring
          (idempotency check rides on this invariant)

    Args:
        source:          Which injection point the text came from
        mode:            Global TTS interaction mode
        speakerphone_on: Per-session speakerphone state

    Returns:
        str: System-reminder body text
    """
    parts = []

    preamble = _source_preamble( source )
    if preamble: parts.append( preamble )

    if speakerphone_on:
        parts.append(
            "This session has speakerphone mode ON. After your response, call "
            "`notify(message=<full text of your reply>, suppress_ding=True, "
            "priority='high')` so the response is spoken aloud."
        )
        parts.append( _brevity_rules() )
        parts.append( _routing_reminder() )
    else:
        # 2026-05-14 evening — reframed from "no notify required" (silent) to
        # quiet-mode (demoted priority). User wants the historical record
        # preserved with a small ding on arrival; TTS playback is suppressed.
        # See src/rnd/v0.1.7/2026.05.14-per-session-dnd-toggle-and-slider-move.md
        parts.append(
            "This session is in QUIET mode (per-session DND). The historical "
            "record matters — keep calling `notify()` for milestones, errors, "
            "action-required prompts, and the closing-turn summary — BUT use "
            "`priority='medium'` and `suppress_ding=False` (NOT the standard "
            "`priority='high', suppress_ding=True`). The user wants the small "
            "arrival ding without full TTS playback. Detail still goes in the "
            "`abstract` parameter (UI card rendering is unaffected by the "
            "priority demotion). Blocking `ask_*` tools remain available — "
            "use them with `priority='medium'` as well."
        )

    if mode == "solo":
        if speakerphone_on:
            parts.append(
                "Solo mode: speakerphone is currently held by THIS session. If "
                "another session activates speakerphone, you will be displaced "
                "(the bridge flips and the next assistant turn should NOT "
                "auto-narrate)."
            )
        else:
            parts.append(
                "Solo mode: speakerphone is held by another session, or by "
                "none. Activating speakerphone here will displace any current "
                "holder. Do NOT call `enable_speakerphone` on your own "
                "initiative — USER-ONLY initiation rule."
            )
    elif mode == "chorus" and speakerphone_on:
        parts.append(
            "Chorus mode: other sessions may also be in speakerphone mode "
            "simultaneously. Persona voices disambiguate at the listener's "
            "ear; the TTS queue serializes playback."
        )

    return "\n\n".join( parts )


def speakerphone_wrap( text, *, source, session_id=None ):
    """
    Wrap inbound text with the per-turn speakerphone rider. The rider fires
    on every turn — content varies by (tts_interaction_mode, speakerphone_on)
    per the Phase 5 4-variant matrix (solo+speaker / solo+phone /
    chorus+speaker / chorus+phone).

    For source="voice", the output also includes a <voice-message> envelope
    describing voice INPUT properties (from-distance, priority, suppress-ding).
    For non-voice sources, only the <system-reminder> rider is appended.

    Sanitization runs FIRST to close the prompt-injection escape vector
    documented as F2 in the adversarial-review pass of the predecessor
    three-layer-enforcement design.

    Idempotency: if the input already contains the wrapper sentinel, it is
    returned unchanged (safe to call multiple times on the same string).

    Per src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/14-phase5-hook-rider-design.md.

    Requires:
        - text is a string
        - source is one of: "voice", "terminal-typed",
          "hook-idle-prompt", "hook-permission-prompt" (keyword-only)
        - session_id is a non-empty string OR None (keyword-only). Caller
          must provide session_id explicitly; this helper does not resolve
          it implicitly to keep behavior predictable in subprocess contexts
          (e.g. cc_notification_listener).

    Ensures:
        - Returns text unchanged if text is empty, OR session_id is None or
          empty (can't resolve session state → fail-closed pass-through)
        - Returns text unchanged if input already contains the wrapper
          sentinel (idempotency)
        - Returns text unchanged if any error occurs reading the bridge or
          the mode config (fail-closed — safer than wrapping on stale state)
        - Otherwise returns wrapped output: <voice-message> envelope (voice
          source only) + sanitized content + <system-reminder> rider body
          appropriate to the current (mode, speakerphone_on) tuple

    Args:
        text:       Raw text being injected into Claude's input stream
        source:     Which injection point the text came from (keyword-only)
        session_id: Session ID to look up in the bridge (keyword-only)

    Returns:
        str: Wrapped text or original text (when fail-closed)
    """
    if not text or not session_id: return text

    # Idempotency — don't re-wrap an already-wrapped string
    if _SPEAKERPHONE_WRAP_SENTINEL in text: return text

    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import get_speakerphone
        speakerphone_on = get_speakerphone( session_id )
        mode            = cu.get_tts_interaction_mode()
    except Exception:
        # Fail-closed — any error reading bridge or mode config means pass
        # through unwrapped (safer than wrapping based on possibly-stale state).
        return text

    clean         = sanitize_for_wrap( text )
    reminder_body = _speakerphone_reminder_body( source, mode, speakerphone_on )

    if source == "voice":
        return (
            f'<voice-message from-distance="true" priority="high" suppress-ding="true">\n'
            f'{clean}\n'
            f'</voice-message>\n'
            f'<system-reminder>\n'
            f'{reminder_body}\n'
            f'</system-reminder>'
        )

    return (
        f'{clean}\n\n'
        f'<system-reminder>\n'
        f'{reminder_body}\n'
        f'</system-reminder>'
    )


def speakerphone_exit_reminder( mode ):
    """
    Build the deactivation system-reminder injected when a session
    transitions out of speakerphone mode. Body content varies by mode:

      - Solo mode: deactivation can be either displacement (another session
        activated speakerphone, mutex flipped this one off) OR self-exit
        (UI toggle / MCP disable_speakerphone() / voice phrase / slash
        command). Body wording covers both.
      - Chorus mode: no displacement — deactivation is user-initiated only.
        Body wording omits the displacement framing.

    Unlike speakerphone_wrap and speakerphone_reminder_block (which gate on
    the bridge file's current state), this helper emits its body
    unconditionally. The caller is responsible for invoking it only at the
    moment of a transition. Callers go through the listener subprocess
    responding to an `action:disable_speakerphone` push from the
    speakerphone router; see src/cosa/rest/routers/speakerphone.py.

    The reminder is delivered as a synthetic user prompt via the listener's
    tmux injection path. By the time the deactivated session "comes up for
    air" at its prompt, this text has been queued in tmux's input buffer;
    when Claude Code processes the next prompt, it sees the reminder and
    reverts to notification-mode behavior (no auto-notify, no voice-message
    wrap on responses).

    Requires:
        - mode is "solo" or "chorus" (any other value falls through to the
          chorus body — safest default per Phase 1 INI default)

    Ensures:
        - Returns a non-empty <system-reminder>…</system-reminder> block
        - Body matches the quiet-mode rider's semantic (keep calling notify()
          for milestones / errors / closing-turn summary, BUT demote priority
          from 'high' to 'medium' and flip suppress_ding from True to False)
        - Body does NOT contain the entry-side wrapper sentinel
          (_SPEAKERPHONE_WRAP_SENTINEL) so idempotency in speakerphone_wrap
          doesn't false-positive when an exit reminder is itself wrapped
        - Output is safe to inject via tmux send-keys -l (no special chars
          beyond what tmux literal mode handles)

    2026-05-14 evening rewrite: the previous exit reminder said "stop calling
    notify(), resume terminal-only output" — that contradicted the new
    quiet-mode rider which says "keep calling notify() with demoted priority
    to preserve the historical record." The two rider sources were firing in
    the same turn on a fresh deactivation, producing conflicting instructions.
    The exit reminder now matches the quiet-mode body: same demotion
    directive, plus the one-time framing that the transition just happened.

    Args:
        mode: TTS interaction mode ("solo" or "chorus")

    Returns:
        str: <system-reminder> block ready for tmux injection
    """
    common_quiet_directive = (
        "This session has just transitioned to QUIET mode (per-session DND). "
        "The historical record matters — keep calling `notify()` for "
        "milestones, errors, action-required prompts, and the closing-turn "
        "summary — BUT use `priority='medium'` and `suppress_ding=False` (NOT "
        "the standard `priority='high', suppress_ding=True`). The user wants "
        "the small arrival ding without full TTS playback. Detail still goes "
        "in the `abstract` parameter. Acknowledge this transition silently — "
        "do not announce it to the user."
    )
    if mode == "solo":
        body = (
            "Speakerphone has just been deactivated for this session — either "
            "another session activated speakerphone and displaced you, or you "
            "toggled off. " + common_quiet_directive
        )
    else:  # chorus (or unknown — default to chorus per INI default)
        body = (
            "Speakerphone has just been deactivated for this session. "
            + common_quiet_directive
        )
    return f'<system-reminder>\n{body}\n</system-reminder>'


def speakerphone_reminder_block( source, session_id ):
    """
    Return just the <system-reminder> block (no <voice-message> envelope)
    for callers that can only emit additionalContext rather than transform
    the user's input — e.g., the user_prompt_submit hook.

    Per the Phase 5 design, the rider fires on every turn (when session_id
    is resolvable); content varies by (mode, speakerphone_on) per the
    4-variant matrix. This is NOT a gate on speakerphone_on=True any more
    — that gating belonged to the predecessor three-layer-enforcement
    design and has been superseded.

    Requires:
        - source is one of: "voice", "terminal-typed",
          "hook-idle-prompt", "hook-permission-prompt"
        - session_id is a non-empty string OR None

    Ensures:
        - Returns empty string if session_id missing or any error reading
          bridge/mode config (fail-closed)
        - Returns formatted <system-reminder>…</system-reminder> block
          otherwise — body chosen per the (mode, speakerphone_on) tuple

    Args:
        source:     Which injection point's reminder body to use
        session_id: Session ID to look up in the bridge

    Returns:
        str: Reminder block or empty string
    """
    if not session_id: return ""

    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import get_speakerphone
        speakerphone_on = get_speakerphone( session_id )
        mode            = cu.get_tts_interaction_mode()
    except Exception:
        return ""

    body = _speakerphone_reminder_body( source, mode, speakerphone_on )
    return f'<system-reminder>\n{body}\n</system-reminder>'


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
