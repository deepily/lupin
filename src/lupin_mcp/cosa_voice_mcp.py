#!/usr/bin/env python3
"""
CoSA Voice MCP Server - Voice I/O bridge for Claude Code.

Provides five tools:
  - converse(): Speak to user, wait for voice/text response (blocking)
  - notify(): Announce to user without waiting (fire-and-forget)
  - ask_yes_no(): Quick yes/no decision (convenience wrapper)
  - ask_multiple_choice(): Present options and get user's selection(s)
  - get_session_info(): Get current session identification

Sender ID Format: claude.code@{project}.deepily.ai#{session_id}
    - session_id is the first 8 chars of the Claude Code session UUID
    - Derived from the session bridge (env > file > fallback), shared with hooks
    - A background thread upgrades the ID once the SessionStart hook writes it

Project Detection (automatic — no MCP_PROJECT needed):
    1. Auto-detects from current working directory (checked in order):
       - cosa → "cosa" (checked first - may be submodule of lupin)
       - lupin → "lupin"
       - planning-is-prompting → "plan"
       - anything else → CWD basename (works in any repo)
    2. Falls back to MCP_PROJECT env var if cwd detection raises an exception
    3. Last resort: uses CWD basename with warning (never crashes)

Environment Variables:
    MCP_PROJECT: Optional override (auto-detection is preferred and sufficient)
    LUPIN_APP_SERVER_URL: Server URL (default: http://localhost:7999)
    MCP_DEBUG: Enable debug logging (optional)

Installation (global — one registration for all repos):
    install-cosa-voice.sh   # registers at user scope via claude mcp add --scope user
"""

import logging
import os
import re
import requests
import signal
import sys
import time
import threading
from typing import Optional

from pydantic import ValidationError
from fastmcp import FastMCP

# Import from lupin_cli.notifications (the notification library)
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    AsyncNotificationRequest,
    NotificationResponse,
    AsyncNotificationResponse,
    NotificationType,
    NotificationPriority,
    ResponseType
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notify_user_async import notify_user_async
from cosa.utils.notification_utils import (
    format_questions_for_tts,
    convert_questions_for_api,
    format_open_ended_batch_for_tts,
    convert_open_ended_batch_for_api,
    normalize_abstract as _normalize_abstract,
    extract_qualifier_comment,
    format_qualified_response,
    is_known_project
)
from cosa.agents.utils.sender_id import detect_project as _detect_project_shared
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, wait_for_session_id, get_session_metadata as _get_cc_metadata,
    clear_cached_session_id, _find_session_file, _read_session_file,
    get_conversation_mode, set_conversation_mode
)
from lupin_cli.claude_code.hooks.lib.hook_common import log_to_stream


# ============================================================================
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.DEBUG if os.getenv( "MCP_DEBUG" ) else logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger( __name__ )

# ============================================================================
# Version
# ============================================================================

__version__ = "0.3.0"

# ============================================================================
# Configuration
# ============================================================================

def _get_server_url() -> str:
    """Get Lupin server URL from environment."""
    return os.getenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )


def _detect_project_from_cwd() -> Optional[ str ]:
    """Attempt to detect project name from current working directory.

    Delegates to the shared detect_project() utility from
    cosa.agents.utils.sender_id for consistent detection logic.

    Returns None only if detection fails entirely (exception).
    """
    try:
        return _detect_project_shared()
    except Exception as e:
        logger.debug( f"Could not detect project from cwd: {e}" )
        return None


_PROJECT_SOURCE    = "unknown"  # Set by _get_project(): "known" | "basename" | "env_var"
_ACCOUNT_VALIDATED = None       # Set by _validate_repo_account(): True | False | None (not yet checked)


def _get_project() -> str:
    """Get project name with dynamic detection — no silent fallback.

    Detection priority:
        1. Auto-detect from current working directory
        2. MCP_PROJECT environment variable
        3. RuntimeError + os._exit(1) — refuses to run as "unknown"

    Sets module-level _PROJECT_SOURCE to track how the project was resolved:
        - "known"    : auto-detected and in KNOWN_PROJECTS registry
        - "basename" : auto-detected as cwd basename (not in registry)
        - "env_var"  : from MCP_PROJECT environment variable

    Note: MCP_PROJECT can be set in MCP JSON config's env section as a default,
    but dynamic detection from cwd takes precedence for multi-project support.
    """
    global _PROJECT_SOURCE

    # Priority 1: Try dynamic detection from working directory
    detected = _detect_project_from_cwd()
    if detected:
        if is_known_project( detected ):
            _PROJECT_SOURCE = "known"
            logger.info( f"Project auto-detected (known): {detected}" )
        else:
            _PROJECT_SOURCE = "basename"
            logger.info( f"Project auto-detected (basename): {detected}" )
        return detected

    # Priority 2: Check environment variable
    project = os.getenv( "MCP_PROJECT", "" ).strip()
    if project:
        _PROJECT_SOURCE = "env_var"
        logger.info( f"Project from MCP_PROJECT env var: {project.lower()}" )
        return project.lower()

    # Priority 3: Last-resort fallback — use CWD basename with warning
    fallback = os.path.basename( os.getcwd() ).lower() or "unknown"
    _PROJECT_SOURCE = "basename"
    logger.warning( "=" * 60 )
    logger.warning( f"PROJECT DETECTION FALLBACK — using CWD basename: {fallback}" )
    logger.warning( "=" * 60 )
    logger.warning( f"Current working directory: {os.getcwd()}" )
    logger.warning( "Auto-detection raised an exception, and MCP_PROJECT env var not set." )
    logger.warning( f"Falling back to basename '{fallback}' — notifications may route incorrectly." )
    logger.warning( "=" * 60 )

    return fallback


def _resolve_canonical_project( detected: str ) -> str:
    """
    Resolve canonical project identifier from ~/.lupin/config.

    The cwd-detected project name (e.g., "ampe-to-meridian") may differ from
    the canonical identity used in the user's Lupin account email. For example,
    the user's config may map [ampe-to-meridian] -> claude.code@ampe2meridian.deepily.ai,
    and THAT canonical identifier ("ampe2meridian") is what should be used for
    sender_id construction — not the raw cwd basename.

    The config file is the source of truth: if a matching section exists and
    contains a parseable email, extract the identifier from between '@' and
    '.deepily.ai'. Otherwise, return the detected name unchanged.

    Requires:
        - detected is a non-empty string (project name from cwd detection)

    Ensures:
        - Returns canonical project identifier from ~/.lupin/config if mapped
        - Returns detected name unchanged if no config section or unparseable email
        - Never raises — all lookups are best-effort

    Args:
        detected: Project name detected from cwd

    Returns:
        str: Canonical project identifier for sender_id construction
    """
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        email, _ = get_hook_credentials( detected )
        # Parse: {agent}@{identifier}.deepily.ai -> identifier
        match = re.match( r"^[a-z]+(?:\.[a-z]+)+@([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\.deepily\.ai$", email )
        if match:
            canonical = match.group( 1 )
            if canonical != detected:
                logger.info( f"Canonical project identity from config: {detected} -> {canonical}" )
            return canonical
        logger.warning( f"Config email for [{detected}] does not match expected format: {email}" )
    except ( FileNotFoundError, ValueError ) as e:
        logger.debug( f"No canonical project mapping for '{detected}' in ~/.lupin/config ({e.__class__.__name__})" )
    except Exception as e:
        logger.warning( f"Unexpected error resolving canonical project for '{detected}': {e}" )
    return detected


def _get_sender_id( project: str, session_id: str = None ) -> str:
    """
    Generate sender_id with optional session identifier.

    Delegates to the shared build_sender_id() utility. The caller is expected
    to pass the CANONICAL project identifier (from _resolve_canonical_project),
    not the raw cwd-detected name.

    Examples:
        _get_sender_id( "lupin" ) -> "claude.code@lupin.deepily.ai"
        _get_sender_id( "lupin", "a1b2c3d4" ) -> "claude.code@lupin.deepily.ai#a1b2c3d4"
    """
    from cosa.agents.utils.sender_id import build_sender_id
    return build_sender_id( "claude.code", project=project, suffix=session_id )


# ============================================================================
# Repo Account Validation
# ============================================================================

ERROR_SENDER_ID = "claude.code@errors.deepily.ai"


def _send_validation_error( detail: str ) -> None:
    """
    Send urgent notification about a validation failure.

    Requires:
        - Lupin FastAPI server is running (for notification delivery)

    Ensures:
        - Sends urgent-priority notification from ERROR_SENDER_ID
        - Logs critical message regardless of notification success
        - Never raises (all exceptions caught)
    """
    msg = f"COSA-VOICE MCP VALIDATION FAILED\n\n{detail}"
    logger.critical( msg )
    try:
        request = AsyncNotificationRequest(
            message           = msg,
            notification_type = NotificationType.TASK,
            priority          = NotificationPriority( "urgent" ),
            sender_id         = ERROR_SENDER_ID
        )
        notify_user_async( request=request, debug=False )
    except Exception as e:
        logger.warning( f"Could not send validation error notification: {e}" )


def _validate_repo_account( project: str ) -> None:
    """
    Validate that a Lupin service account exists for this project.

    Checks:
        1. Credentials exist in ~/.lupin/config for [project] section
        2. Login succeeds via POST /auth/login

    On failure, sends an urgent notification with setup instructions via
    the synthetic claude.code@errors.deepily.ai sender. Tools continue
    working in degraded mode — this does not crash the server.

    Requires:
        - SERVER_URL is set
        - project is a non-empty string

    Ensures:
        - On success: logs confirmation, returns normally
        - On failure: sends urgent notification, logs critical, returns normally
    """
    global _ACCOUNT_VALIDATED
    from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials

    expected_email = f"claude.code@{project}.deepily.ai"

    # Check 1: Credentials exist in config file
    try:
        email, password = get_hook_credentials( project )
    except ( FileNotFoundError, ValueError ) as e:
        _ACCOUNT_VALIDATED = False
        _send_validation_error(
            f"No credentials for project '{project}'.\n{e}\n\n"
            f"To fix:\n"
            f"1. Open the Admin UI: {SERVER_URL}/app/admin/users\n"
            f"2. Create a new user account with email: {expected_email}\n"
            f"3. Add credentials to ~/.lupin/config:\n"
            f"   [{project}]\n"
            f"   email = {expected_email}\n"
            f"   password = <the password you set in the admin UI>\n\n"
            f"Once the account exists, the CC Notification Listener can authenticate\n"
            f"via WebSocket and auto-start receiving hook events for this repo."
        )
        return

    # Check 2: Login works
    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/login",
            json={ "email": email, "password": password },
            timeout=5
        )
        if resp.status_code != 200:
            _ACCOUNT_VALIDATED = False
            _send_validation_error(
                f"Login failed for {email} (HTTP {resp.status_code}).\n"
                f"Account may not exist or may be disabled.\n\n"
                f"To fix:\n"
                f"1. Open the Admin UI: {SERVER_URL}/app/admin/users\n"
                f"2. Verify or create the user account: {expected_email}\n"
                f"3. Check that the password in ~/.lupin/config [{project}] matches"
            )
            return
    except ( requests.ConnectionError, requests.Timeout ) as e:
        # Catch BOTH ConnectionError (server down) AND Timeout (server up but
        # unresponsive). Without the Timeout case, a slow server propagates
        # `requests.ReadTimeout` out of module-import scope and breaks every
        # test that imports cosa_voice_mcp.
        _ACCOUNT_VALIDATED = False
        _send_validation_error(
            f"Cannot reach Lupin server at {SERVER_URL} ({type( e ).__name__}).\n"
            f"Ensure FastAPI is running: src/scripts/run-fastapi-lupin.sh"
        )
        return
    except Exception as e:
        # Final fallback — never let validation explode at import time.
        _ACCOUNT_VALIDATED = False
        logger.warning( f"Repo account validation aborted: {type( e ).__name__}: {e}" )
        return

    _ACCOUNT_VALIDATED = True
    logger.info( f"Repo account validated: {email}" )


# ============================================================================
# Signal Handlers
# ============================================================================

def _handle_sigterm( signum, frame ):
    """Handle SIGTERM for graceful shutdown."""
    logger.info( "Received SIGTERM, shutting down gracefully" )
    sys.exit( 0 )


signal.signal( signal.SIGTERM, _handle_sigterm )

# ============================================================================
# Initialize at module load
# ============================================================================

PROJECT           = _get_project()
CANONICAL_PROJECT = _resolve_canonical_project( PROJECT )  # Config-mapped identity for sender_id
SESSION_ID        = get_claude_session_id()[:8]  # 8-char hex from session bridge (env > file > fallback)
SENDER_ID         = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
SERVER_URL        = _get_server_url()
_session_ready    = threading.Event()   # Gate: blocks tool calls until session ID resolved
_session_failed   = False               # True if real ID never arrived (fallback only)

# Validate repo service account (non-blocking — logs + notifies on failure)
_validate_repo_account( PROJECT )

# ── Startup banner (consolidated status to stderr) ──────────────────────
_account_status = "validated" if _ACCOUNT_VALIDATED else "FAILED" if _ACCOUNT_VALIDATED is False else "skipped"
_project_line   = f"  Project : {PROJECT} ({_PROJECT_SOURCE})" if PROJECT == CANONICAL_PROJECT else f"  Project : {PROJECT} ({_PROJECT_SOURCE}) -> {CANONICAL_PROJECT} (config)"
_banner_lines   = [
    "",
    "=" * 42,
    f"  cosa-voice MCP v{__version__} — Runtime",
    "=" * 42,
    _project_line,
    f"  Session : {SESSION_ID}",
    f"  Sender  : {SENDER_ID}",
    f"  Server  : {SERVER_URL}",
    f"  Account : {_account_status}",
    "=" * 42,
    "",
]
for _line in _banner_lines:
    logger.info( _line )


def _session_watcher_thread():
    """
    Persistent daemon thread that resolves and monitors the CC session_id.

    Phase 1 (Initial resolution):
        Polls for the real CC session_id via wait_for_session_id(). Signals
        _session_ready so gated tool calls can proceed.

    Phase 2 (Continuous monitoring):
        Watches the resolved bridge file for changes (mtime check every 2s).
        If the session ID changes (context clear), updates SESSION_ID and
        SENDER_ID atomically. Clears the session bridge cache before each
        poll to ensure fresh resolution.

    This replaces the one-shot _upgrade_session_id_background() to handle
    context clears that overwrite the bridge file mid-session.
    """
    global SESSION_ID, SENDER_ID, _session_failed

    # ── Phase 1: Initial resolution ─────────────────────────────────────
    try:
        real_id    = wait_for_session_id( timeout=10.0, poll_interval=1.0 )
        new_suffix = real_id[:8]

        if new_suffix != SESSION_ID:
            old_sender = SENDER_ID
            SESSION_ID = new_suffix
            SENDER_ID  = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
            logger.info( f"Session ID upgraded: {old_sender} -> {SENDER_ID}" )

        # Verify we got a real session ID, not the fallback
        meta = _get_cc_metadata()
        if meta.get( "source" ) == "fallback":
            logger.warning( "No session bridge file found for this project" )
            logger.warning( f"Using stable fallback sender_id: {SENDER_ID}" )
        else:
            logger.info( f"Session ready (sender_id={SENDER_ID})" )

    except Exception as e:
        _session_failed = True
        logger.critical( f"Session ID resolution failed: {e}" )

    finally:
        _session_ready.set()

    # ── Phase 2: Persistent bridge file watcher ─────────────────────────
    # Track the last-seen mtime and session ID for change detection
    last_mtime      = 0.0
    last_session_id = SESSION_ID
    poll_interval   = 2.0  # seconds

    logger.info( "Session watcher: entering persistent monitoring loop" )

    while True:
        try:
            time.sleep( poll_interval )

            # Clear cache so _find_session_file() does a fresh lookup
            clear_cached_session_id()

            result = _find_session_file()
            if result is None:
                continue

            bridge_path, _source = result

            # Check if file was modified
            try:
                current_mtime = bridge_path.stat().st_mtime
            except OSError:
                continue

            if current_mtime <= last_mtime:
                continue

            last_mtime = current_mtime

            # Re-read the session ID
            file_id = _read_session_file( bridge_path )
            if not file_id:
                continue

            new_suffix = file_id[:8]
            if new_suffix != last_session_id:
                old_sender     = SENDER_ID
                SESSION_ID     = new_suffix
                SENDER_ID      = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
                last_session_id = new_suffix
                logger.info(
                    f"Session ID changed: {old_sender} -> {SENDER_ID} "
                    f"(context clear detected)"
                )

        except Exception as e:
            logger.error( f"Session watcher error: {e}" )


_watcher_thread = threading.Thread(
    target=_session_watcher_thread,
    name="session-id-watcher",
    daemon=True
)
_watcher_thread.start()


def _die_no_session_id():
    """
    Send error notification and hard-exit — real session ID never arrived.

    Requires:
        - Lupin FastAPI server is running (for notification delivery)

    Ensures:
        - Sends high-priority alert from sender_id claude.code@{PROJECT}.deepily.ai#mcp-error
        - Terminates MCP server process via os._exit( 1 )
        - Never returns
    """
    error_sender = f"claude.code@{PROJECT}.deepily.ai#mcp-error"
    logger.critical( "Sending error notification and terminating MCP server" )

    try:
        request = AsyncNotificationRequest(
            message           = "MCP server failed: Claude Code session ID not found. "
                                "No session bridge file detected. Restart Claude Code to fix.",
            notification_type = NotificationType.ALERT,
            priority          = NotificationPriority( "high" ),
            sender_id         = error_sender
        )
        notify_user_async( request=request, debug=False )
    except Exception as e:
        logger.error( f"Failed to send error notification: {e}" )

    os._exit( 1 )


def _wait_for_sender_id( timeout: float = 12.0 ) -> str:
    """
    Block until the session ID is resolved, then return SENDER_ID.
    If resolution failed (fallback only), send error notification and exit.

    Requires:
        - _session_ready is a threading.Event set by _upgrade_session_id_background
        - _session_failed is a bool set by _upgrade_session_id_background
        - timeout exceeds background thread's 10s wait

    Ensures:
        - Returns SENDER_ID with real session ID on success
        - Calls _die_no_session_id() and never returns on failure
        - Zero overhead after first resolution (Event.wait on set event returns instantly)
    """
    if not _session_ready.wait( timeout=timeout ):
        _die_no_session_id()

    if _session_failed:
        _die_no_session_id()

    return SENDER_ID


# ============================================================================
# MCP Server
# ============================================================================

mcp = FastMCP(
    name="CoSA Voice Bridge",
    instructions=(
        f"Voice I/O for Claude Code [Session: {SENDER_ID}]\n\n"
        f"## Conversation Mode\n\n"
        f"This session has a 'conversation mode' toggle backed by the bridge file. "
        f"At session start (and after any /clear), check `get_session_info()` once to read "
        f"the `conversation_mode_active` flag and act accordingly:\n\n"
        f"- **notification mode** (default, conversation_mode_active=false): respond normally; "
        f"speaking via TTS only happens when YOU explicitly call notify(), converse(), or ask_*().\n"
        f"- **conversation mode** (conversation_mode_active=true): the user is at a distance, "
        f"listening via TTS rather than reading the terminal. After every assistant turn, call "
        f"`notify(message=<full text of your response>, suppress_ding=True, priority='high')` "
        f"so the response is spoken aloud. Strip fenced code blocks and tool-call narration from "
        f"the spoken text (those are TTS-hostile). No length cap — speak the full response.\n\n"
        f"To toggle modes, call `enter_conversation_mode()` or `exit_conversation_mode()`. "
        f"The user may say 'enter conversation mode' / 'exit conversation mode' (or close paraphrases) "
        f"in voice — pattern-match those phrases and call the corresponding tool, then continue with "
        f"the new mode in effect.\n\n"
        f"The toggle state survives /clear within this session (stored in the bridge file). "
        f"A fresh Claude Code session starts in notification mode."
    )
)


@mcp.tool
def converse(
    message: str,
    response_type: str = "open_ended",
    timeout_seconds: int = 120,
    response_default: Optional[ str ] = None,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> str:
    """
    Speak to the user and wait for their voice/text response.

    Use this when you need input, clarification, or a decision from the user.
    The message will be converted to speech (TTS) and played to the user.
    Their response (via voice or text) will be returned to you.

    Args:
        message: What to say to the user
        response_type: "yes_no" for binary choices, "open_ended" for free-form
        timeout_seconds: How long to wait (1-600, default 120)
        response_default: Fallback if timeout or user offline
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        User's response as text, or error/timeout message

    Examples:
        converse("Should I proceed with the refactor?", response_type="yes_no")
        converse("What naming convention should I use for the new module?")
        converse("The tests are failing. Should I continue?", response_default="yes")
    """
    logger.debug( f"converse() called: {message[:50]}..." )

    try:
        request = NotificationRequest(
            message=message,
            response_type=ResponseType( response_type ),
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=response_default,
            title=title,
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return f"[validation error: {e}]"

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        prefix = "[default used] " if response.default_used else ""
        return f"{prefix}{response.response_value or ''}"
    elif response.exit_code == 2:
        if response_default is not None:
            return f"[timeout - using default] {response_default}"
        return "[timeout - no response received]"
    else:
        return f"[error: {response.status}]"


def _notify_impl(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False,
    progress_group_id: Optional[ str ] = None,
    session_name: Optional[ str ] = None
) -> str:
    """
    Core notify implementation — plain Python function callable from anywhere.

    FastMCP 2.x @mcp.tool converts decorated functions into FunctionTool objects
    that are NOT callable as regular Python functions. This private function holds
    the actual logic so that both the MCP tool and internal callers (e.g.,
    set_session_topic) can invoke it directly.

    Requires:
        - message is a non-empty string
        - notification_type is a valid NotificationType value
        - priority is a valid NotificationPriority value

    Ensures:
        - Returns a status string (never raises)
        - Sends notification via HTTP POST to /api/notify

    Args:
        message: What to announce to the user
        notification_type: "task", "progress", "alert", "custom", or "session_topic"
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        suppress_ding: Suppress notification sound while still speaking via TTS (default False)
        progress_group_id: Optional progress group ID (pg-{8 hex chars}) for in-place DOM updates.
            Notifications sharing this ID update a single element instead of appending new ones.
        session_name: Optional human-readable session name for UI header display.
            When set, updates the sender-session-name span in notification history card.

    Returns:
        Delivery status message
    """
    logger.debug( f"_notify_impl() called: {message[:50]}..." )

    try:
        request = AsyncNotificationRequest(
            message=message,
            notification_type=NotificationType( notification_type ),
            priority=NotificationPriority( priority ),
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id,
            suppress_ding=suppress_ding,
            progress_group_id=progress_group_id,
            session_name=session_name
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return f"[validation error: {e}]"

    response: AsyncNotificationResponse = notify_user_async( request=request, debug=False )

    if response.success:
        return f"Notification sent ({response.status})"
    else:
        return f"Failed: {response.message}"


@mcp.tool
def notify(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False,
    progress_group_id: Optional[ str ] = None,
    session_name: Optional[ str ] = None
) -> str:
    """
    Announce something to the user without waiting for response.

    Use this for status updates, progress reports, or FYI messages.
    The message will be converted to speech (TTS) and played to the user.
    This call returns immediately - it does not wait for acknowledgment.

    Args:
        message: What to announce to the user
        notification_type: "task", "progress", "alert", "custom", or "session_topic"
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")
        suppress_ding: Suppress notification sound while still speaking via TTS (default False)
        progress_group_id: Optional progress group ID (pg-{8 hex chars}) for in-place DOM updates.
            Notifications sharing this ID update a single element instead of appending new ones.
        session_name: Optional human-readable session name for UI header display.
            When set, updates the sender-session-name span in notification history card.

    Returns:
        Delivery status message

    Examples:
        notify("Starting code analysis...", notification_type="progress")
        notify("Build completed successfully", notification_type="task")
        notify("Warning: deprecated API detected", notification_type="alert", priority="high")
        notify("Task complete", suppress_ding=True)  # TTS only, no ding
    """
    return _notify_impl(
        message=message,
        notification_type=notification_type,
        priority=priority,
        abstract=abstract,
        job_id=job_id,
        suppress_ding=suppress_ding,
        progress_group_id=progress_group_id,
        session_name=session_name
    )


@mcp.tool
def ask_yes_no(
    question: str,
    default: str = "no",
    timeout_seconds: int = 60,
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> str:
    """
    Ask a yes/no question and get the user's response as a string.

    Convenience wrapper for quick binary decisions. The user may optionally
    attach a qualifying comment to their answer via the UI.

    Requires:
        - question is a non-empty string
        - default is "yes" or "no"
        - timeout_seconds is a positive integer

    Ensures:
        - returns "yes", "no", "yes [comment: ...]", or "no [comment: ...]"
        - returns the default value (as string) on timeout or error

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout_seconds: How long to wait (default 60)
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        Annotated string: "yes", "no", "yes [comment: ...]", or "no [comment: ...]"

    Examples:
        response = ask_yes_no("Delete the old backups?")
        # response == "yes" or "no" or "yes [comment: only the March ones]"
    """
    logger.debug( f"ask_yes_no() called: {question[:50]}..." )

    try:
        request = NotificationRequest(
            message=question,
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=default,
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ):
        return default

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0 and response.response_value:
        raw_value = response.response_value.strip()
        answer, qualifier = extract_qualifier_comment( raw_value )
        result = format_qualified_response( answer, qualifier ) if qualifier else raw_value
        log_to_stream( "mcp_ask_yes_no", {}, extra={
            "raw_value"  : raw_value,
            "answer"     : answer,
            "qualifier"  : qualifier,
            "enriched"   : bool( qualifier ),
            "return_len" : len( result )
        } )
        return result

    return default


@mcp.tool
def ask_multiple_choice(
    questions: list,
    timeout_seconds: int = 120,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> dict:
    """
    Ask multiple-choice questions and get user's selection(s).

    Presents questions with options via TTS and UI. Supports both single-select
    (radio buttons) and multi-select (checkboxes) questions. Users can select
    from predefined options or provide custom "Other" answers.

    Args:
        questions: List of question objects matching Claude Code's AskUserQuestion format:
            [
                {
                    "question": "Which auth method?",
                    "header": "Auth method",
                    "multiSelect": false,
                    "options": [
                        {"label": "OAuth", "description": "Use OAuth2 flow"},
                        {"label": "JWT", "description": "Use JWT tokens"}
                    ]
                }
            ]
        timeout_seconds: How long to wait for response (1-600, default 120)
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        dict with answers keyed by header:
        {
            "answers": {
                "Auth method": "OAuth",
                "Features": ["Dark mode", "Notifications"]
            }
        }

    Examples:
        # Single question, single select
        result = ask_multiple_choice([{
            "question": "Which database should we use?",
            "header": "Database",
            "multiSelect": False,
            "options": [
                {"label": "PostgreSQL", "description": "Relational database"},
                {"label": "MongoDB", "description": "Document database"}
            ]
        }])
        # Returns: {"answers": {"Database": "PostgreSQL"}}

        # Multiple questions
        result = ask_multiple_choice([
            {"question": "Which framework?", "header": "Framework", "multiSelect": False,
             "options": [{"label": "FastAPI"}, {"label": "Flask"}]},
            {"question": "Which features?", "header": "Features", "multiSelect": True,
             "options": [{"label": "Auth"}, {"label": "Caching"}]}
        ])
    """
    logger.debug( f"ask_multiple_choice() called with {len( questions )} questions" )

    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    # Build TTS-friendly message from questions
    tts_message = format_questions_for_tts( questions )

    # Convert questions to response_options format (camelCase -> snake_case)
    response_options = convert_questions_for_api( questions )

    try:
        request = NotificationRequest(
            message=tts_message,
            response_type=ResponseType.MULTIPLE_CHOICE,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            title=title,
            sender_id=_wait_for_sender_id(),
            response_options=response_options,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return { "error": f"validation error: {e}" }

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        return _parse_multiple_choice_response( response.response_value )
    elif response.exit_code == 2:
        return { "error": "timeout - no response received", "timeout": True }
    else:
        return { "error": f"error: {response.status}" }


def _parse_multiple_choice_response( response_value: Optional[ str ] ) -> dict:
    """
    Parse the response from multiple choice notification.

    Expects JSON string like: {"answers": {"Header": "value"}}

    Requires:
        - response_value is None or a JSON string

    Ensures:
        - Returns parsed dict if valid JSON
        - Returns error dict if parsing fails

    Args:
        response_value: JSON string from notification response

    Returns:
        dict: Parsed answers or error
    """
    if not response_value:
        return { "answers": {} }

    try:
        import json
        parsed = json.loads( response_value )
        return parsed if isinstance( parsed, dict ) else { "answers": parsed }
    except ( json.JSONDecodeError, TypeError ) as e:
        logger.warning( f"Could not parse multiple choice response: {e}" )
        # Return raw value wrapped in answers
        return { "answers": { "response": response_value } }


@mcp.tool
def ask_open_ended_batch(
    questions: list,
    timeout_seconds: int = 300,
    priority: str = "high",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None
) -> dict:
    """
    Ask multiple open-ended questions at once and get all answers as a dict.

    Presents all questions on a single screen with text input + mic button per question.
    User answers all questions and submits once. Much faster than asking one at a time.

    Args:
        questions: List of question objects, each with "question" and "header" keys.
            Optional "default_value" key pre-fills the text input so the user can
            accept the default by simply hitting Submit All:
            [
                {"question": "What topic would you like to research?", "header": "Topic"},
                {"question": "Would you like to set a budget limit?", "header": "Budget", "default_value": "no limit"},
                {"question": "Who is the target audience?", "header": "Audience", "default_value": "academic"}
            ]
        timeout_seconds: How long to wait for response (1-600, default 300)
        priority: "low", "medium", "high", or "urgent"
        title: Optional short title for the notification
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        dict with answers keyed by header:
        {
            "answers": {
                "Topic": "quantum computing",
                "Budget": "no limit",
                "Audience": "graduate students"
            }
        }

    Examples:
        result = ask_open_ended_batch([
            {"question": "What topic?", "header": "Topic"},
            {"question": "What budget?", "header": "Budget"}
        ])
        # Returns: {"answers": {"Topic": "quantum computing", "Budget": "10"}}
    """
    logger.debug( f"ask_open_ended_batch() called with {len( questions )} questions" )

    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    # Build TTS-friendly message from questions
    tts_message = format_open_ended_batch_for_tts( questions )

    # Convert questions to response_options format
    response_options = convert_open_ended_batch_for_api( questions )

    try:
        request = NotificationRequest(
            message          = tts_message,
            response_type    = ResponseType.OPEN_ENDED_BATCH,
            notification_type = NotificationType.CUSTOM,
            priority         = NotificationPriority( priority ),
            timeout_seconds  = timeout_seconds,
            title            = title,
            sender_id        = _wait_for_sender_id(),
            response_options = response_options,
            abstract         = _normalize_abstract( abstract ),
            job_id           = job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return { "error": f"validation error: {e}" }

    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        return _parse_open_ended_batch_response( response.response_value )
    elif response.exit_code == 2:
        return { "error": "timeout - no response received", "timeout": True }
    else:
        return { "error": f"error: {response.status}" }


def _parse_open_ended_batch_response( response_value: Optional[ str ] ) -> dict:
    """
    Parse the response from an open-ended batch notification.

    Expects JSON string like: {"answers": {"Topic": "quantum computing", "Budget": "10"}}

    Requires:
        - response_value is None or a JSON string

    Ensures:
        - Returns parsed dict if valid JSON
        - Returns error dict if parsing fails

    Args:
        response_value: JSON string from notification response

    Returns:
        dict: Parsed answers or error
    """
    if not response_value:
        return { "answers": {} }

    try:
        import json
        parsed = json.loads( response_value )
        return parsed if isinstance( parsed, dict ) else { "answers": parsed }
    except ( json.JSONDecodeError, TypeError ) as e:
        logger.warning( f"Could not parse open-ended batch response: {e}" )
        return { "answers": { "response": response_value } }


@mcp.tool
def set_session_topic( topic: str ) -> dict:
    """
    Set the current session's topic/description for context in stop hook notifications.

    The topic appears in the "Continue Session?" notification abstract so users
    know WHAT they'd be continuing. Call this at session start, after plan
    approval, or when switching tasks.

    The full topic is stored in the bridge file. For UI propagation, topics
    longer than 64 characters are truncated with "..." because the notification
    header has minimal display space.

    Args:
        topic: Brief description of current work (e.g., "Bug Fix: WS queue crash")

    Returns:
        dict with status and the topic that was set
    """
    import json

    meta        = _get_cc_metadata()
    bridge_path = meta.get( "_bridge_path" )
    if not bridge_path:
        return { "status": "error", "reason": "No bridge file found" }

    try:
        with open( bridge_path ) as f:
            data = json.load( f )
        data[ "session_topic" ] = topic
        with open( bridge_path, "w" ) as f:
            json.dump( data, f, indent=2 )

        # Also push to notification UI for real-time header update
        # Truncate session_name for UI display (max 64 chars)
        MAX_SESSION_NAME = 64
        if len( topic ) > MAX_SESSION_NAME:
            display_topic = topic[ :MAX_SESSION_NAME - 3 ] + "..."
        else:
            display_topic = topic

        result = _notify_impl(
            message           = display_topic,
            notification_type = "session_topic",
            priority          = "low",
            session_name      = display_topic,
            suppress_ding     = True
        )
        ui_ok = not ( result.startswith( "[validation error" ) or result.startswith( "Failed:" ) )

        if not ui_ok:
            logger.warning( f"set_session_topic() UI push failed: {result}" )

        return { "status": "ok", "topic": topic, "ui_push": "ok" if ui_ok else result }
    except Exception as e:
        return { "status": "error", "reason": str( e ) }


@mcp.tool
def get_session_info() -> dict:
    """
    Get current session identification and server info.

    Returns:
        dict with project name, session_id, sender_id, server_url, version,
        conversation_mode_active flag, and claude_code metadata from the session bridge
    """
    resolved_sender = _wait_for_sender_id()
    info = {
        "project"                  : PROJECT,
        "project_source"           : _PROJECT_SOURCE,
        "session_id"               : SESSION_ID,
        "sender_id"                : resolved_sender,
        "server_url"               : SERVER_URL,
        "version"                  : __version__,
        "conversation_mode_active" : False
    }

    # Include CC session bridge metadata when available
    try:
        cc_meta = _get_cc_metadata()
        info[ "claude_code" ] = {
            "session_id"        : cc_meta.get( "session_id", "" ),
            "stable_session_id" : cc_meta.get( "stable_session_id", "" ),
            "source"            : cc_meta.get( "source", "unknown" )
        }
        # Read conversation_mode_active from the same bridge metadata
        info[ "conversation_mode_active" ] = bool( cc_meta.get( "conversation_mode_active", False ) )
    except Exception:
        pass

    return info


def _flip_conversation_mode( active: bool ) -> dict:
    """
    Internal helper: flip conversation_mode_active in this session's bridge file.

    Resolves the bridge by stable_session_id (preferred for /clear-resistance), falling
    back to session_id then SESSION_ID prefix. Writes via session_bridge.set_conversation_mode.

    NOTE: This does NOT broadcast a WebSocket conversation_mode_changed event.
    Real-time UI sync arrives via Phase 3's HTTP endpoint when the UI toggle button is
    clicked. When this MCP tool flips the state, other connected UI clients see the
    new value on their next page reload (via the GET endpoint) or get_session_info() poll.

    Requires:
        - active is a bool

    Ensures:
        - Returns dict with status="ok" and conversation_mode_active=<new state> on success
        - Returns dict with status="error" and reason on failure
        - Never raises exceptions
    """
    try:
        cc_meta = _get_cc_metadata()
        sid = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
    except Exception:
        sid = SESSION_ID

    if not sid:
        return { "status": "error", "reason": "No session_id available" }

    ok = set_conversation_mode( sid, active )
    if not ok:
        return { "status": "error", "reason": "Bridge file not found or write failed", "session_id": sid }

    return {
        "status"                   : "ok",
        "session_id"               : sid,
        "conversation_mode_active" : active,
        "ui_sync"                  : "deferred (other tabs reflect on reload until Phase 3 WS broadcast lands)"
    }


@mcp.tool
def enter_conversation_mode() -> dict:
    """
    Enter conversation mode for this session.

    When conversation mode is on, after every assistant turn you should call
    `notify(message=<full_response_text>, suppress_ding=True, priority='high')` so the
    response is spoken aloud (the user is listening at a distance via TTS, not reading
    the terminal). Strip fenced code blocks and tool-call narration from the spoken text.

    State is stored in the bridge file and survives /clear within this session.

    Returns:
        dict with status, session_id, conversation_mode_active=True on success
    """
    return _flip_conversation_mode( True )


@mcp.tool
def exit_conversation_mode() -> dict:
    """
    Exit conversation mode (revert to default notification mode) for this session.

    In notification mode, TTS only fires when YOU explicitly call notify(), converse(), or ask_*().

    Returns:
        dict with status, session_id, conversation_mode_active=False on success
    """
    return _flip_conversation_mode( False )


if __name__ == "__main__":
    mcp.run()
