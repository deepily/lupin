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
from pathlib import Path
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
    get_speakerphone, set_speakerphone
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

        # =====================================================================
        # Framing paragraph + tool-inventory navigation map (2026-05-16)
        # Per src/rnd/v0.1.7/2026.05.16-mcp-discovery-surface-expansion.md.
        # Anchors the reader before the deeper protocol sections below.
        # =====================================================================
        f"## Instructions vs Per-Turn Rider\n\n"
        f"This `instructions` payload (which you are reading now) describes what "
        f"this cosa-voice MCP server IS and how to use it — it is injected into "
        f"your system prompt ONCE per session at the `initialize` handshake. "
        f"In contrast, the per-turn `<system-reminder>` rider you'll see on every "
        f"inbound user message tells you what to DO this turn under the CURRENT "
        f"state of `speakerphone_on` + `tts_interaction_mode`. The two are "
        f"complementary: `instructions` is the contract; the rider is the "
        f"per-turn obligation under that contract.\n\n"

        f"## Your Toolkit at a Glance\n\n"
        f"This server exposes 18+ tools grouped by function. Scan this map "
        f"before reading the per-tool docstrings:\n\n"
        f"| Group | Tools | One-line purpose |\n"
        f"|---|---|---|\n"
        f"| **Notifications** | `notify` | Fire-and-forget announcement; spoken via TTS in speakerphone mode |\n"
        f"| **Blocking decisions** | `ask_yes_no`, `ask_multiple_choice`, `converse`, `ask_open_ended_batch` | Block until user responds; route by question shape (see § Interactive Tool Routing) |\n"
        f"| **Commons read** | `commons_read`, `commons_who` | Always-allowed inspection of cross-session traffic |\n"
        f"| **Commons self-disclosure** | `commons_post` | Append to topic blackboard; recipient sees on next poll |\n"
        f"| **Commons DM** | `commons_send_to`, `commons_ask_async`, `commons_ask_sync` | Directed attention-demanding messages to peer sessions |\n"
        f"| **Session state** | `get_session_info`, `set_session_topic`, `enable_speakerphone`, `disable_speakerphone` | Read or update this session's bridge state |\n\n"
        f"Each per-tool docstring opens with a `**[TIER]**` marker on line 1 "
        f"that signals user-permission requirements (READ / SELF-DISCLOSURE / "
        f"ATTENTION-DEMANDING / DM). Consult the marker AT DECISION-TIME — when "
        f"you're considering calling a tool — to know whether the call requires "
        f"a user trigger or can fire on your own initiative.\n\n"

        f"## Speakerphone Mode\n\n"
        f"> **Forward-pointer**: this section describes WHAT `speakerphone_on` + "
        f"`tts_interaction_mode` mean and how to behave under each combination. "
        f"For HOW to obtain those values (the `get_session_info()` Phase-A call + "
        f"the persona/doc_scope extraction protocol), see § MCP Startup Protocol below.\n\n"
        f"This session has a per-session `speakerphone_on` flag backed by the bridge file, "
        f"plus a global `tts_interaction_mode` (`solo` | `chorus`) that controls cross-session "
        f"behavior. At session start (and after any /clear), check `get_session_info()` once to "
        f"read both fields and act accordingly:\n\n"
        f"- **phone mode** (`speakerphone_on=false`): respond normally; speaking via TTS only "
        f"happens when YOU explicitly call notify(), converse(), or ask_*().\n"
        f"- **speakerphone mode** (`speakerphone_on=true`): the user is at a distance, "
        f"listening via TTS rather than reading the terminal. Two per-turn obligations:\n"
        f"  1. **Acknowledge receipt BEFORE tool work begins.** Every user prompt must be greeted "
        f"with at minimum a brief receipt-acknowledgment `notify(message=<short ack>, "
        f"suppress_ding=True, priority='high')` BEFORE you fire any tool calls. A turn that "
        f"opens with tool calls and never speaks violates the contract — the user has no way to "
        f"know the prompt was received. The acknowledgment can be one short sentence ('Looking "
        f"into the speakerphone directives now.') — it does not need to be the full plan. "
        f"This rule applies even when the substantive response will arrive in a later turn.\n"
        f"  2. **Speak every closing turn in full.** After tool work completes (or on any turn "
        f"that produces user-facing text), call "
        f"`notify(message=<full text of your response>, suppress_ding=True, priority='high')` "
        f"so the response is spoken aloud. Strip fenced code blocks and tool-call narration from "
        f"the spoken text (those are TTS-hostile). No length cap — speak the full response.\n\n"
        f"To toggle, call `enable_speakerphone()` or `disable_speakerphone()`. "
        f"The user may say 'enable speakerphone' / 'disable speakerphone' / 'enter conversation "
        f"mode' / 'exit conversation mode' / 'speakerphone on' / 'speakerphone off' (or close "
        f"paraphrases) in voice — pattern-match those phrases and call the corresponding tool, "
        f"then continue with the new state in effect.\n\n"
        f"**USER-ONLY INITIATION (HARD RULE)**: NEVER call `enable_speakerphone()` or "
        f"`disable_speakerphone()` on your own initiative. You may only call them in DIRECT "
        f"response to an explicit user instruction (voice phrase like 'enable speakerphone' / "
        f"'disable speakerphone' or close paraphrases, typed request, slash command). Do NOT "
        f"preemptively toggle on your own judgment (e.g. 'since this is a long task, let me "
        f"enable speakerphone' is FORBIDDEN). The mic is the user's to direct, not yours to "
        f"grab. If unsure whether the user actually asked, prefer NOT calling the tool and ask "
        f"for clarification.\n\n"
        f"**MODE-DEPENDENT CROSS-SESSION BEHAVIOR**:\n"
        f"- Under `tts_interaction_mode=solo` (today's monopoly behavior): at most one CC "
        f"session at a time can hold speakerphone across all of the user's sessions. When the "
        f"user enables speakerphone in this session while another session holds it, the other "
        f"session is automatically displaced — its UI reverts to phone mode, any in-flight TTS "
        f"pauses, and its sender card unpins. The displacement is broadcast via the "
        f"`speakerphone_changed` WebSocket event with `displaced=true, displaced_by=<this "
        f"session's id>`.\n"
        f"- Under `tts_interaction_mode=chorus` (multi-voice default): N sessions can hold "
        f"speakerphone simultaneously; persona voices disambiguate at the listener's ear. No "
        f"displacement; activating in another session does NOT pull the mic away from this one. "
        f"The `speakerphone_changed` event still fires for self-state-change broadcasts but "
        f"never with `displaced=true`.\n\n"
        f"The toggle state survives /clear within this session (stored in the bridge file). "
        f"A fresh Claude Code session's default `speakerphone_on` is mode-aware: false in solo, "
        f"true in chorus (at-distance is the default in chorus).\n\n"
        f"## Voice Persona Self-Announcement (Phase A.5)\n\n"
        f"> **Forward-pointer**: this section describes the announcement obligation "
        f"once your persona is allocated. The allocation itself happens during "
        f"`get_session_info()` Phase A — see § MCP Startup Protocol below for the "
        f"complete startup sequence.\n\n"
        f"After `get_session_info()` returns, if the `voice_persona` field is non-null, "
        f"send a brief TTS greeting by your persona name. Phrasing recipe: time-of-day-"
        f"appropriate greeting + persona's `display_name` (proper-noun form, e.g. 'Maria'; "
        f"NOT `name` which is the lowercase pool key) + brief duty announcement. Examples:\n"
        f"- 'Good morning, Maria reporting for duty, setting things up.'\n"
        f"- 'Good afternoon, Henrietta here, ready to roll.'\n\n"
        f"Send via `notify(notification_type='custom', priority='medium', suppress_ding=False)`. "
        f"If `voice_persona` is None (allocation failed; server fell back to 'Sam'), skip the "
        f"greeting — there's no name to use. Fires once per Phase A startup including after "
        f"`/clear` (the persona persists across /clear, so re-announcing keeps the session "
        f"audibly tagged for users running parallel CC sessions).\n\n"

        # =====================================================================
        # MCP Startup Protocol (G1) — Phase A + Phase B
        # =====================================================================
        f"## MCP Startup Protocol\n\n"
        f"You MUST complete this two-phase startup before any substantive work.\n\n"
        f"**Phase A — Immediate, before composing your first response**:\n\n"
        f"1. Call `get_session_info()` once. The response carries critical session identity + state:\n"
        f"   - `voice_persona` dict (`{{name, display_name, voice_id, icon, color, borrowed}}`) — your assigned persona. **MUST extract before any user-facing text**: in chorus mode, your persona voice is the disambiguator the listener relies on. If `voice_persona` is None (allocation failure / fallback to 'Sam'), ask the user which persona via `converse()` before proceeding.\n"
        f"   - `speakerphone_on` (bool) + `tts_interaction_mode` (`solo` | `chorus`) — drives the per-turn obligations you'll see in the rider.\n"
        f"   - `claude_code.session_id` — your stable session identity, used in cross-session DM correlation.\n"
        f"2. Report MCP server status to the user in your first acknowledgment (project name, session_id, server_url, version, your resolved persona name).\n"
        f"3. If `voice_persona.name` is non-null, call `notify(notification_type='custom', priority='medium')` with a time-of-day-appropriate greeting using `display_name` (see § Voice Persona Self-Announcement above).\n\n"
        f"**Phase B — After context gathering**:\n\n"
        f"Call `set_session_topic(topic='<3-8 word title>')` as soon as you can write a meaningful session title — from the user's first message, from history.md/TODO.md, or from the approved plan. Skipping is a session-start bug, not a minor oversight. The topic appears in the 'Continue Session?' stop-hook notification so the user knows what they'd be continuing.\n\n"
        f"**Rules**: Phase A runs in ALL modes including plan mode (MCP tools are communication tools, not code-changing tools). Phase A MUST complete BEFORE any file reading, exploration, edits, or planning begins — and BEFORE the first user-facing text. Phase B runs as soon as the topic is knowable, NOT 'whenever I get around to it.'\n\n"

        # =====================================================================
        # Inter-Session Commons Protocol (G2)
        # =====================================================================
        f"## Inter-Session Commons Protocol\n\n"
        f"The commons is a file-backed blackboard for cross-session communication. Other CC sessions running on this host (potentially with different personas) read from + write to the same topic files.\n\n"
        f"**Three-tier autonomy** governs when you can use commons tools without explicit user permission:\n\n"
        f"| Tier | Tools | When you can fire on your own |\n"
        f"|---|---|---|\n"
        f"| **READ** | `commons_read`, `commons_who` | Always — inspecting the blackboard never disturbs anyone |\n"
        f"| **SELF-DISCLOSURE** | `commons_post` to free-form / presence / incident topics | When announcing your own state (e.g. 'starting long migration', 'observed bug X') — fire-and-forget, no recipient is summoned |\n"
        f"| **ATTENTION-DEMANDING** | `commons_post` to coordination/help-wanted topics; ALL of `commons_ask_async` / `commons_ask_sync` / `commons_send_to`; broadcasts | Requires clear coordination need OR explicit user trigger. Summons a peer recipient's attention. |\n\n"
        f"**Reserved topic vocabulary** (pre-seeded by the store):\n\n"
        f"- `broadcasts` — user-originated broadcasts (read-only from CC sessions; only the user posts)\n"
        f"- `broadcast-acks` — recipient ack records for broadcast delivery (auto-managed)\n"
        f"- `presence` — session lifecycle signals (joining/leaving)\n"
        f"- `system-events` — server-side notices\n\n"
        f"All other topic names are free-form and auto-create on first post. Persona name/icon/color are stamped server-side at post-time and IMMUTABLE thereafter (you cannot spoof another persona).\n\n"
        f"For full doctrine — anti-patterns, sensitive-content rules, retention semantics — see § Deep Doctrine Reference at the bottom.\n\n"

        # =====================================================================
        # Phase 0 DM Workflow (G3 + G7 + G8)
        # =====================================================================
        f"## Phase 0 DM Workflow\n\n"
        f"Direct messaging between CC sessions is built on top of the commons blackboard. **Three tools** with different ergonomics:\n\n"
        f"| Tool | Use when |\n"
        f"|---|---|\n"
        f"| `commons_send_to(recipient='persona', body=...)` | Directed DM by persona name. Thin wrapper around `commons_ask_async`. Most common case. |\n"
        f"| `commons_ask_async(topic, body, recipient_persona=...)` | Same as `commons_send_to` but with explicit `topic` control + `expect_reply` parameter. Use when you want non-default topic or fire-and-forget. |\n"
        f"| `commons_ask_sync` | BLOCKING — waits for a reply. Rarely justified; consider `commons_ask_async` first. |\n\n"
        f"**Push vs Polling**:\n\n"
        f"- **Push-mode** (preferred): if the result carries `push_mode_active: true` AND `dm_dispatched: true`, the recipient's listener got an immediate notification and the recipient sees your DM as a `COMMONS PEER MESSAGE` `<system-reminder>` injection on their next turn.\n"
        f"- **Polling fallback**: if `push_mode_active: false`, the DM landed on the blackboard but the recipient won't see it until their next `commons_read` poll. Check `register_skip_reason` in the result (`missing_auth_header` / `missing_api_base_url` / `register_failed_status_N` / `register_failed_422`) to debug why push didn't fire.\n"
        f"- **Recipient resolution failures**: if push returned 422, the result carries a `recipient_resolution_error` dict with `resolution_chain_attempted` + `candidate_alternatives` + `suggested_next_action`. Read those before retrying.\n\n"
        f"**Receipt etiquette** — when a `COMMONS PEER MESSAGE` `<system-reminder>` arrives:\n\n"
        f"1. **Acknowledge receipt** before tool calls if you're in speakerphone mode (same rule as user prompts — silent tool-only turns break the audio loop).\n"
        f"2. **Read the topic** via `commons_read(topic='<topic>', limit=10)` to get the body — the system-reminder names the topic + question_id. The system-reminder body itself may be truncated by the push-injection layer; ALWAYS re-fetch via `commons_read` for the canonical body, don't trust the system-reminder text.\n"
        f"3. **Reply** via `commons_post(topic='<sender-mailbox>', body=<reply>, metadata={{'in_reply_to': <question_id>, 'kind': 'answer'}})`. **Sender-mailbox convention**: replies go to `dm-<sender-persona-lowercase>` (e.g. if Tiberius DM'd you, your reply goes to `dm-tiberius`, not back to your own `dm-<yourname>`). The original asker's Phase 3 watcher polls THEIR sender-mailbox topic for answers correlated by `in_reply_to`. **Threading isn't free**: if the asker forgot `expect_reply=True` or already unregistered, your reply lands silently on the blackboard.\n"
        f"4. **Loop avoidance** — don't reply to your own DMs. If the received entry's `sender_session_id` matches YOUR own session_id (you can compare against `get_session_info().session_id`), skip the reply path — you're seeing your own outbound entry echoed back to you, not a genuine peer message. This can happen during MCP restart-recovery or if you accidentally subscribed to your own outbound topic.\n\n"
        f"**DM vs Broadcast — when to choose which**:\n\n"
        f"- **DM** (`commons_send_to`): peer-specific question or coordination request. One recipient. The recipient owes you attention; you owe them context.\n"
        f"- **Broadcast**: user-originated only. Sessions do NOT initiate broadcasts. When a broadcast arrives, it appears as a `USER BROADCAST` `<system-reminder>` injection — that's the user talking to multiple sessions at once.\n\n"
        f"**Cross-session bug-filing pattern** (durable backup for unreliable push):\n\n"
        f"When you discover a bug that affects a peer session's domain, BOTH:\n"
        f"1. DM the responsible session via `commons_send_to` (low-latency notification when push works)\n"
        f"2. File a structured entry in their repo's `bug-fix-queue.md` (durable backup if push fails / they're offline)\n\n"
        f"This double-channel pattern was exercised live 2026-05-16 (María ↔ Tiberius cross-session bug-fix-arc) and is documented in detail at planning-is-prompting → workflow/cross-session-communication.md §6.5.1.\n\n"

        # =====================================================================
        # Interactive Tool Routing (G4)
        # =====================================================================
        f"## Interactive Tool Routing\n\n"
        f"When you need user input, **prefer the cosa-voice blocking tools over Claude Code's built-in `AskUserQuestion`** — those built-in questions render to the TERMINAL only (no TTS, no audio), so users in speakerphone mode never hear them.\n\n"
        f"| Question shape | Use | Why |\n"
        f"|---|---|---|\n"
        f"| Yes / No (binary) | `ask_yes_no(question, default='yes'\\|'no')` | Three-button UI with optional 'Neither' escape hatch when the question itself needs re-framing |\n"
        f"| 2-4 mutually-exclusive options | `ask_multiple_choice(questions=[{{...}}])` | Radio-button UI; supports multi-question batches |\n"
        f"| Single open-ended | `converse(message=..., response_type='open_ended')` | Free-form text or voice response |\n"
        f"| Multiple open-ended at once | `ask_open_ended_batch(questions=[{{header, question}}, ...])` | Single screen with per-question text+mic inputs; user submits all at once |\n\n"
        f"**On 'Neither' from `ask_yes_no`**: treat as a signal that the question needs re-framing, NOT as a soft yes/no. Read the comment (if present) and ask a clearer follow-up.\n\n"
        f"**All blocking tools should use `priority='high'`** to ensure the TTS alert reaches the user in speakerphone mode.\n\n"
        f"**Pros/cons + recommendation in every multi-option ask**: per `feedback_always_include_pros_cons_recommendation`, every substantive `ask_yes_no` or `ask_multiple_choice` should carry per-option pros AND cons AND a 'My recommendation: X because Y' block in the `abstract` parameter, plus a 'flip-condition' (what would make a different option correct). Pros/cons go in `abstract` ONLY — not in the spoken `message` body.\n\n"

        # =====================================================================
        # Failure Modes + Debugging Signals (G5)
        # =====================================================================
        f"## Failure Modes + Debugging Signals\n\n"
        f"Common ways cosa-voice can fail silently or partially, and what to look at in the result dict to debug:\n\n"
        f"**1. `push_mode_active: false` on a `commons_send_to` / `commons_ask_async` call** — the DM didn't get pushed to the recipient. Check the new `register_skip_reason` key (added 2026-05-16 commit `f4e0370`):\n\n"
        f"- `missing_auth_header` — the MCP wrapper couldn't construct an X-API-Key header. The key file at `src/conf/keys/notification-api-claude-code-dev` may be missing or unreadable. Surface to user.\n"
        f"- `missing_api_base_url` — the `LUPIN_API_URL` env var is empty. Misconfiguration.\n"
        f"- `register_network_error` — the HTTP POST raised a connection error. The Lupin REST API may be down or restarting; retry later.\n"
        f"- `register_failed_status_N` — the endpoint returned a non-2xx HTTP status (rate limit, server error, etc.).\n"
        f"- `register_failed_422` — recipient resolution failed. The accompanying `recipient_resolution_error` key carries the diagnostic chain.\n\n"
        f"In all of these, the DM still lands on the blackboard topic (Phase 1 polling fallback). The recipient just won't get auto-injection.\n\n"
        f"**2. `voice_persona: None` in `get_session_info()`** — the per-session persona allocator returned no assignment, OR the persona pool was exhausted and you got a 'Sam' overflow fallback (`borrowed: true` if from the legacy hash-borrow path). When None:\n\n"
        f"- DO NOT respond as 'Claude' or a placeholder — that breaks the chorus-mode disambiguation contract\n"
        f"- Ask the user via `converse(message='Which persona am I?', response_type='open_ended')` before proceeding\n"
        f"- This is rare (allocator is resilient); it indicates either a fresh session pool exhaustion or a bridge-file corruption\n\n"
        f"**3. `commons_send_to` raising 'FunctionTool object is not callable'** — this was a Python bug in the wrapper. Fixed 2026-05-16 commit `f4e0370`. If you encounter it again, the MCP subprocess hasn't picked up the fix yet (fastmcp doesn't auto-reload like uvicorn). User can restart the MCP subprocess to pick up the fix.\n\n"
        f"**4. `dm_dispatched: false` despite `push_mode_active: true`** — the register-question endpoint succeeded BUT the recipient-side dispatch (the actual tmux injection) failed. Check Lupin server logs around the timestamp. The asker's blackboard entry still exists; recipient will see on next poll.\n\n"
        f"**5. Stale-bridge phantom personas in `commons_who`** — `commons_who` may show sessions whose host process has died. The host-side prune at SessionStart eventually cleans these, but during the window between death and prune, they appear active. If a DM to a 'visible' peer never returns a reply, the recipient may be a phantom. Cross-reference with `commons_who(retention_hours=1)` for a narrower window.\n\n"

        f"**6. Persona-allocation cache staleness across MCP restart** — if your session was bounced (architecture switchover, manual MCP subprocess kill, etc.) AND the persona pool was exhausted such that you got a 'Sam' overflow allocation, an in-memory cache of the pre-bounce allocation may persist in the running MCP subprocess until you call `get_session_info()` fresh. After ANY MCP restart or pool-exhaustion event, re-call `get_session_info()` to confirm the current allocation matches what your bridge file says — the bridge file is the source of truth; the in-memory cache may lag.\n\n"

        f"**7. Topic-file name case sensitivity (filed 2026-05-16, fix pending)** — the `commons_send_to` wrapper currently constructs its topic name as `f\"dm-{{recipient}}\"` with literal recipient case. So `commons_send_to(recipient=\"Tiberius\")` writes to `dm-Tiberius.md` (capital T), while a peer reading lowercase `dm-tiberius` won't see it. Push-mode persona resolution is case-insensitive (so the recipient's listener still gets the system-reminder), but the topic FILES fragment across case variants. **Mitigation until the fix lands**: pass recipient names lowercased: `commons_send_to(recipient=recipient.lower(), ...)`. Or use `commons_post(topic=\"dm-<lowercase>\", body=..., metadata={{...}})` directly. Tracking in TODO.md as the case-fragmentation entry.\n\n"

        # =====================================================================
        # Deep Doctrine Reference Footer (G10)
        # =====================================================================
        f"## Deep Doctrine Reference\n\n"
        f"For three-tier autonomy semantics, reserved topic vocabulary, anti-patterns, sensitive-content rules, broadcast routing diagrams, and the full cross-session-bug-filing pattern with mermaid flow, see the canonical reference at:\n\n"
        f"  **planning-is-prompting → workflow/cross-session-communication.md**\n\n"
        f"Key sections to bookmark:\n"
        f"- §1.5 — DM mechanics, threading, receipt etiquette, channel-choice\n"
        f"- §1.5.1 — Result-shape table for `push_mode_active` / `dm_dispatched` / `register_skip_reason`\n"
        f"- §1.5.3 — Threading conventions (`in_reply_to` chains, sender-mailbox topic routing, loop-avoidance)\n"
        f"- §2 — Three-tier autonomy (READ / SELF-DISCLOSURE / ATTENTION-DEMANDING)\n"
        f"- §3 — Reserved topic vocabulary\n"
        f"- §4 — Broadcast receipt rules\n"
        f"- §6.5.1 — Cross-session bug-filing pattern (mermaid diagram of the double-channel flow)\n\n"
        f"That doc was refreshed 2026-05-16 by Tiberius 🌑 alongside the expansion of this `instructions` payload by María 🌸. Both surfaces are intentionally orthogonal — this file covers the cosa-voice-bound how-to; the doctrine file covers the deep semantics and policy."
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


def strip_fenced_code_blocks( text: str ) -> str:
    """
    Strip triple-backtick fenced code blocks from text.

    Used by _notify_impl to clean up conv-mode auto-narration messages
    before TTS — code is universally bad voice content. Per design doc
    Phase 3 spec.

    Requires:
        - text is a string (or empty)

    Ensures:
        - Returns text with all ```lang...``` blocks removed (any language tag)
        - Preserves single-backtick inline `code` spans (those are fine for TTS)
        - Returns empty string if input is None or empty
        - Multiple consecutive blocks all stripped
        - Idempotent

    Args:
        text: Markdown-formatted text potentially containing fenced code

    Returns:
        str: Text with fenced code blocks stripped
    """
    if not text: return ""
    import re
    # Match triple-backtick code blocks: optional language tag on the same
    # line as the opening fence, then content (lazy across newlines via
    # DOTALL), then a closing fence. Trailing whitespace/newline consumed
    # so consecutive blocks don't leave gaps.
    return re.sub( r"```[^\n`]*\n.*?\n```\s*", "", text, flags=re.DOTALL )


def _notify_impl(
    message: str,
    notification_type: str = "progress",
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    suppress_ding: bool = False,
    progress_group_id: Optional[ str ] = None,
    session_name: Optional[ str ] = None,
    _internal_call: bool = False
) -> str:
    """
    Core notify implementation — plain Python function callable from anywhere.

    FastMCP 2.x @mcp.tool converts decorated functions into FunctionTool objects
    that are NOT callable as regular Python functions. This private function holds
    the actual logic so that both the MCP tool and internal callers (e.g.,
    set_session_topic) can invoke it directly.

    Phase 3 of the conv-mode three-layer enforcement plan adds a bidirectional
    gate: when conv mode is active for the calling session, force suppress_ding
    + priority=high + strip fenced code blocks; when conv mode is OFF and the
    sender is a CC session asking for suppress_ding, invert it so the user
    hears an audible cross-talk cue. Internal callers bypass via
    _internal_call=True.
    See: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md

    Requires:
        - message is a non-empty string
        - notification_type is a valid NotificationType value
        - priority is a valid NotificationPriority value

    Ensures:
        - Returns a status string (never raises)
        - Sends notification via HTTP POST to /api/notify
        - Conv-mode gate applied unless _internal_call=True

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
        _internal_call: When True, bypass the conv-mode gate entirely (params pass through
            unchanged). Used by internal callers like set_session_topic that have their own
            specific param requirements.

    Returns:
        Delivery status message
    """
    logger.debug( f"_notify_impl() called: {message[:50]}..." )

    # ── Phase 3 bidirectional conv-mode gate ────────────────────────────────
    # Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md §2.5
    if not _internal_call:
        # Dynamic session_id resolution (matches _flip_speakerphone pattern)
        try:
            cc_meta = _get_cc_metadata()
            sid = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
        except Exception:
            sid = SESSION_ID

        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import get_speakerphone
            active = get_speakerphone( sid ) if sid else False
        except Exception:
            active = False

        sender = _wait_for_sender_id() or ""

        if active:
            # Speakerphone ON — enforce speakerphone-render params
            suppress_ding = True
            if priority not in ( "high", "urgent" ):
                priority = "high"
            message = strip_fenced_code_blocks( message )
            logger.debug( "_notify_impl speakerphone ON: forced priority=high, suppress_ding=True, stripped fenced code" )
        elif sender.startswith( "claude.code@" ) and suppress_ding:
            # Speakerphone OFF + CC sender + caller asked for silent TTS.
            # Mode-conditional cross-talk leak cue (Phase 4 of solo/chorus refactor):
            # - SOLO: inversion fires — only one session can hold speakerphone at a time,
            #   so a "silent TTS from a phone-mode session" is a leak symptom worth flagging
            #   audibly. Force ding ON so user knows this session leaked.
            # - CHORUS: passthrough — multiple sessions legitimately call notify() with
            #   suppress_ding=True (it's the normal pattern when a session is in phone mode
            #   but a sibling session is in speakerphone). No leak; no inversion.
            try:
                import cosa.utils.util as _cu
                _tts_mode = _cu.get_tts_interaction_mode()
            except Exception:
                _tts_mode = "chorus"
            if _tts_mode == "solo":
                suppress_ding = False
                logger.info( f"_notify_impl solo cross-talk cue: suppress_ding inverted for {sender}" )
            else:
                logger.debug( f"_notify_impl chorus passthrough: suppress_ding preserved for {sender}" )

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

    Convenience wrapper for quick binary decisions, with a third "Neither"
    escape hatch for cases where the question itself needs re-framing.
    The user may optionally attach a qualifying comment to any answer via the UI.

    Requires:
        - question is a non-empty string
        - default is "yes" or "no" (Neither is never a default — it requires
          an explicit user click)
        - timeout_seconds is a positive integer

    Ensures:
        - returns one of:
          * "yes", "no", "neither"
          * "yes [comment: ...]", "no [comment: ...]", "neither [comment: ...]"
        - returns the default value (as string) on timeout or error
        - On "neither", Claude should treat the response as a signal that the
          question needs re-framing rather than as a soft yes or no — read the
          comment (if present) and ask a clearer follow-up question

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout_seconds: How long to wait (default 60)
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (plan details, URLs, markdown)
        job_id: Optional agentic job ID for routing to job cards (e.g., "dr-a1b2c3d4")

    Returns:
        Annotated string: one of "yes", "no", "neither",
        optionally suffixed with "[comment: ...]"

    Examples:
        response = ask_yes_no("Delete the old backups?")
        # response == "yes" or "no" or "neither"
        # or with qualifier: "yes [comment: only the March ones]"
        # or signaling re-frame: "neither [comment: ambiguous which backups]"
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
            suppress_ding     = True,
            _internal_call    = True   # Bypass conv-mode gate per Phase 3 design doc
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
        speakerphone_on flag, claude_code metadata from the session bridge,
        and voice_persona dict (None if allocation failed; otherwise
        {name, voice_id, icon, color, borrowed, display_name?})
    """
    resolved_sender = _wait_for_sender_id()
    # Resolve the global TTS interaction mode (solo | chorus) so the consumer
    # (e.g. Claude) knows which cross-session semantics apply. Fail-closed to
    # "chorus" (the new operational default per the 2026-05-12 override).
    try:
        import cosa.utils.util as _cu
        _tts_mode = _cu.get_tts_interaction_mode()
    except Exception:
        _tts_mode = "chorus"
    info = {
        "project"              : PROJECT,
        "project_source"       : _PROJECT_SOURCE,
        "session_id"           : SESSION_ID,
        "sender_id"            : resolved_sender,
        "server_url"           : SERVER_URL,
        "version"              : __version__,
        "speakerphone_on"      : False,
        "tts_interaction_mode" : _tts_mode
    }

    # Include CC session bridge metadata when available
    try:
        cc_meta = _get_cc_metadata()
        info[ "claude_code" ] = {
            "session_id"        : cc_meta.get( "session_id", "" ),
            "stable_session_id" : cc_meta.get( "stable_session_id", "" ),
            "source"            : cc_meta.get( "source", "unknown" )
        }
        # Read speakerphone_on from the same bridge metadata
        info[ "speakerphone_on" ] = bool( cc_meta.get( "speakerphone_on", False ) )
        # voice_persona stamped into the bridge by register_session.py Phase 4.5;
        # None if allocation failed (server falls back to "Sam" for TTS, per design).
        # Shape per src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md:
        # {name, voice_id, icon, color, borrowed, display_name?}
        info[ "voice_persona" ] = cc_meta.get( "voice_persona" )
    except Exception:
        pass

    return info


def _flip_speakerphone( active: bool ) -> dict:
    """
    Internal helper: flip speakerphone_on for this session.

    Routes through the canonical HTTP endpoint POST
    /api/cosa-voice/speakerphone/{session_id} when reachable, so:
      - Mutual exclusion across the user's sessions is enforced (any other
        active session is displaced atomically).
      - The speakerphone_changed WebSocket event broadcasts to all of
        the user's connected browser tabs for real-time UI sync.
      - Activate/deactivate flows behave identically whether triggered from
        the UI button, voice phrase, slash command, or this MCP tool.

    Falls back to a direct bridge-file write (today's pre-2026-04-28 behavior)
    when the HTTP endpoint is unreachable — preserves voice/MCP availability
    when the FastAPI server is offline. Degraded mode: no broadcast, no mutex
    enforcement; UI sync deferred until next page reload.

    Resolves session_id by stable_session_id (preferred for /clear-resistance),
    falling back to session_id then SESSION_ID prefix.

    Requires:
        - active is a bool

    Ensures:
        - Returns dict with status="ok", session_id, speakerphone_on=<new state>
          on success (whether via HTTP or fallback)
        - Returns dict with status="error" and reason on failure
        - Never raises exceptions
        - When HTTP succeeded: returned dict includes "displaced_sessions" (list)
          and "ui_sync" = "broadcast"
        - When fallback was used: returned dict includes "ui_sync" = "deferred (HTTP unreachable)"
    """
    try:
        cc_meta = _get_cc_metadata()
        sid = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
    except Exception:
        sid = SESSION_ID

    if not sid:
        return { "status": "error", "reason": "No session_id available" }

    # ── Primary path: canonical HTTP endpoint ─────────────────────────────
    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        project = _get_project()
        email, password = get_hook_credentials( project )

        # Login to obtain a JWT (each call — no caching for low-frequency toggles)
        login_resp = requests.post(
            f"{SERVER_URL}/auth/login",
            json    = { "email": email, "password": password },
            timeout = 5
        )
        if login_resp.status_code != 200:
            raise RuntimeError( f"login HTTP {login_resp.status_code}" )

        access_token = login_resp.json()[ "tokens" ][ "access_token" ]

        # Call the canonical endpoint
        toggle_resp = requests.post(
            f"{SERVER_URL}/api/cosa-voice/speakerphone/{sid}",
            json    = { "active": active },
            headers = { "Authorization": f"Bearer {access_token}" },
            timeout = 5
        )
        if toggle_resp.status_code != 200:
            raise RuntimeError( f"endpoint HTTP {toggle_resp.status_code}: {toggle_resp.text[:200]}" )

        body = toggle_resp.json()
        return {
            "status"                   : "ok",
            "session_id"               : sid,
            "speakerphone_on" : bool( body.get( "active", active ) ),
            "displaced_sessions"       : body.get( "displaced_sessions", [] ),
            "ui_sync"                  : "broadcast"
        }

    except ( requests.ConnectionError, requests.Timeout, RuntimeError, KeyError, FileNotFoundError, ValueError ) as http_err:
        # ── Fallback: direct bridge write (degraded mode) ────────────────
        ok = set_speakerphone( sid, active )
        if not ok:
            return {
                "status"     : "error",
                "reason"     : f"HTTP path failed ({http_err}) AND bridge fallback failed",
                "session_id" : sid
            }
        return {
            "status"                   : "ok",
            "session_id"               : sid,
            "speakerphone_on" : active,
            "ui_sync"                  : f"deferred (HTTP unreachable: {type( http_err ).__name__})"
        }


@mcp.tool
def enable_speakerphone() -> dict:
    """
    Enter conversation mode for this session.

    USER-ONLY INITIATION (HARD RULE): Call this ONLY in direct response to an
    explicit user instruction — voice phrase like "enter conversation mode" (or
    close paraphrases), typed request, or slash command. NEVER call on your own
    initiative. Preemptive activation ("since this is a long task...") is
    forbidden. The mic is the user's to direct, not yours to grab.

    When conversation mode is on, after every assistant turn you should call
    `notify(message=<full_response_text>, suppress_ding=True, priority='high')` so the
    response is spoken aloud (the user is listening at a distance via TTS, not reading
    the terminal). Strip fenced code blocks and tool-call narration from the spoken text.

    Mutual exclusion: at most one CC session at a time can hold conversation mode
    across the user's sessions. Activating here will atomically displace any other
    active session — its UI reverts, in-flight TTS pauses, sender card unpins.

    State is stored in the bridge file and survives /clear within this session.

    Returns:
        dict with status, session_id, speakerphone_on=True on success;
        when HTTP path is reachable, also includes "displaced_sessions" list and
        "ui_sync"="broadcast" (other tabs sync via WebSocket immediately)
    """
    return _flip_speakerphone( True )


@mcp.tool
def disable_speakerphone() -> dict:
    """
    Exit conversation mode (revert to default notification mode) for this session.

    USER-ONLY INITIATION (HARD RULE): Call this ONLY in direct response to an
    explicit user instruction — voice phrase like "exit conversation mode" (or
    close paraphrases), typed request, or slash command. NEVER call on your own
    initiative. The user owns the toggle; you respond to it, not drive it.

    In notification mode, TTS only fires when YOU explicitly call notify(), converse(), or ask_*().

    Returns:
        dict with status, session_id, speakerphone_on=False on success
    """
    return _flip_speakerphone( False )


# ============================================================================
# Commons Tools (Phase 1 — file-based inter-session blackboard)
# ============================================================================
#
# Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md
# AC3 + AC4 + AC5 + AC6 + AC7. Five thin MCP shims wrapping CommonsStore +
# commons_ask. The MCP server lazily constructs a single CommonsStore rooted at
# `<LUPIN_ROOT>/io/commons` (step 6 will wire INI-driven storage path override).
# Tools redundantly check `_commons_enabled()` at call-time as defense per AC12;
# step 6/8 will wire the actual INI key.

from lupin_mcp.commons_store import CommonsStore, DEFAULT_PERSONA_NAME, DEFAULT_PERSONA_ICON, DEFAULT_PERSONA_COLOR
from lupin_mcp.commons_ask import ask_sync as _commons_ask_sync_impl, ask_async as _commons_ask_async_impl
from lupin_mcp.commons_archival import CommonsArchiver


def _mcp_outbound_api_key() -> Optional[ str ]:
    """
    Load the X-API-Key value used for MCP-server outbound HTTP calls
    to the Lupin REST API (e.g. `/api/commons/register-question`).

    Mirrors the canonical pattern in
    `cosa/memory/embedding_provider.py:177` `_http_api_key()` — reads
    `src/conf/keys/notification-api-claude-code-dev` via the
    project-wide `du.get_api_key()` helper. This is the same long-lived
    `ck_live_*` API key used by the embedding HTTP endpoints and the
    notification authentication infrastructure (Phase 2.5).

    Replaces the prior `os.environ.get("LUPIN_MCP_API_KEY")` lookup —
    that env var was added in commit `9bbf298` (Inter-Session DM Phase 0)
    without matching set-side wiring, so it was always None and push-mode
    silently fell through to polling. Switching to the canonical helper
    eliminates the wire-up gap entirely.

    Ensures:
        - Returns the key string if `src/conf/keys/notification-api-claude-code-dev` is readable
        - Returns None on any error (silent fallback to polling)
        - Never raises
    """
    try:
        import cosa.utils.util as du
        return du.get_api_key( "notification-api-claude-code-dev" )
    except Exception:
        return None

_commons_store_singleton:    Optional[ CommonsStore ]     = None
_commons_archiver_singleton: Optional[ CommonsArchiver ]  = None

# 6 commons INI keys, paired in src/conf/lupin-app.ini + lupin-app-splainer.ini under
# the "Inter-Session Commons" block. Loaded once at module import via ConfigurationManager;
# falls back to these hardcoded defaults if the manager is unavailable (env var unset,
# config file missing, etc.). No hot-reload — restart the MCP server to pick up changes.
_COMMONS_CONFIG_DEFAULTS = {
    "commons_enabled"                       : True,
    "commons_storage_path"                  : "/io/commons",
    "commons_retention_hours"               : 24,
    "commons_archival_interval_seconds"     : 3600,
    "commons_broadcast_rate_limit_seconds"  : 30,
    "commons_ask_sync_grace_seconds"        : 1.0,
}


def _load_commons_config() -> dict:
    """
    Resolve the 6 commons INI keys via ConfigurationManager.

    Defensive: returns `_COMMONS_CONFIG_DEFAULTS` (a copy) on any failure
    (env var unset, config-mgr exception, key missing). The MCP server keeps
    working with sensible defaults even if the larger config infrastructure
    is unavailable.

    Test-only override: when `LUPIN_COMMONS_TEST_OVERRIDE` is set to a JSON
    object, its key/value pairs replace matching `_COMMONS_CONFIG_DEFAULTS`
    entries and the normal ConfigurationManager path is bypassed. This hatch
    is used exclusively by the AC12 config-toggle subprocess test — production
    behavior is unaffected when the env var is unset.
    """
    config = dict( _COMMONS_CONFIG_DEFAULTS )
    test_override_json = os.environ.get( "LUPIN_COMMONS_TEST_OVERRIDE" )
    if test_override_json:
        try:
            import json as _json
            overrides = _json.loads( test_override_json )
            if isinstance( overrides, dict ):
                config.update( overrides )
                logger.info( f"[commons] LUPIN_COMMONS_TEST_OVERRIDE applied: {overrides}" )
                return config
            logger.warning( f"[commons] LUPIN_COMMONS_TEST_OVERRIDE is not a JSON object; ignoring: {test_override_json!r}" )
        except Exception as e:
            logger.warning( f"[commons] LUPIN_COMMONS_TEST_OVERRIDE parse failed: {e}" )
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config[ "commons_enabled" ]                      = cm.get( "commons enabled",                      default=config[ "commons_enabled" ],                      return_type="boolean", silent=True )
        config[ "commons_storage_path" ]                 = cm.get( "commons storage path",                 default=config[ "commons_storage_path" ],                 return_type="string",  silent=True )
        config[ "commons_retention_hours" ]              = cm.get( "commons retention hours",              default=config[ "commons_retention_hours" ],              return_type="int",     silent=True )
        config[ "commons_archival_interval_seconds" ]    = cm.get( "commons archival interval seconds",    default=config[ "commons_archival_interval_seconds" ],    return_type="int",     silent=True )
        config[ "commons_broadcast_rate_limit_seconds" ] = cm.get( "commons broadcast rate limit seconds", default=config[ "commons_broadcast_rate_limit_seconds" ], return_type="int",     silent=True )
        config[ "commons_ask_sync_grace_seconds" ]       = cm.get( "commons ask sync grace seconds",       default=config[ "commons_ask_sync_grace_seconds" ],       return_type="float",   silent=True )
    except Exception as e:
        logger.warning( f"[commons] ConfigurationManager unavailable; using hardcoded defaults. Reason: {e}" )
    return config


_COMMONS_CONFIG = _load_commons_config()


def _commons_project_root() -> str:
    """Resolve project root for commons file storage. Prefers LUPIN_ROOT env."""
    env_root = os.environ.get( "LUPIN_ROOT" )
    if env_root: return env_root
    return str( Path( __file__ ).resolve().parents[ 2 ] )


def _commons_storage_root() -> str:
    """
    Resolve the CommonsStore root path.

    `commons storage path` is interpreted as relative to LUPIN_ROOT (matches the
    project's existing config convention — see `solution snapshots lancedb path`
    pattern in lupin-app.ini). CommonsStore appends `io/commons` internally, so
    we strip a leading `/io/commons` segment when the user has left the default
    in place; otherwise we pass through.
    """
    raw = _COMMONS_CONFIG[ "commons_storage_path" ]
    # Default `/io/commons` → CommonsStore's hardcoded subpath already covers this;
    # pass the project root through. Custom values pass through directly.
    if raw == "/io/commons":
        return _commons_project_root()
    return _commons_project_root() + raw


def _commons_enabled() -> bool:
    """Defense-in-depth flag per AC12. Reads the cached INI value."""
    return bool( _COMMONS_CONFIG[ "commons_enabled" ] )


def _commons_ask_sync_grace_default() -> float:
    """Cached default for `commons_ask_sync` grace_seconds when caller omits it."""
    return float( _COMMONS_CONFIG[ "commons_ask_sync_grace_seconds" ] )


def _get_commons_store() -> CommonsStore:
    """Lazy singleton CommonsStore bound to the resolved storage root."""
    global _commons_store_singleton
    if _commons_store_singleton is None:
        _commons_store_singleton = CommonsStore( _commons_storage_root() )
    return _commons_store_singleton


def _maybe_start_commons_archival_daemon() -> Optional[ CommonsArchiver ]:
    """
    Boot the 24h archival daemon IF commons is enabled. Returns the archiver
    (started) or None (skipped). Called from `if __name__ == "__main__":` so
    the daemon does not start on bare module imports (tests, dev shells).
    """
    global _commons_archiver_singleton
    if not _commons_enabled():
        logger.info( "[commons] disabled — archival daemon NOT started" )
        return None
    if _commons_archiver_singleton is not None:
        return _commons_archiver_singleton
    _commons_archiver_singleton = CommonsArchiver(
        root             = _commons_storage_root(),
        interval_seconds = int( _COMMONS_CONFIG[ "commons_archival_interval_seconds" ] ),
        retention_hours  = int( _COMMONS_CONFIG[ "commons_retention_hours" ] ),
    )
    _commons_archiver_singleton.start()
    logger.info(
        f"[commons] archival daemon started "
        f"(interval={_COMMONS_CONFIG[ 'commons_archival_interval_seconds' ]}s, "
        f"retention={_COMMONS_CONFIG[ 'commons_retention_hours' ]}h)"
    )
    return _commons_archiver_singleton


def _commons_persona_fields() -> dict:
    """
    Extract (name, icon, color) from the session bridge's voice_persona block.

    Falls back to AC3 defaults (`<unknown>`, 💬, #888888) when the bridge is
    unavailable or the persona allocation failed.
    """
    try:
        cc_meta = _get_cc_metadata()
        vp      = cc_meta.get( "voice_persona" ) or { }
    except Exception:
        vp = { }
    return {
        "persona_name"  : vp.get( "name" )  or DEFAULT_PERSONA_NAME,
        "persona_icon"  : vp.get( "icon" )  or DEFAULT_PERSONA_ICON,
        "persona_color" : vp.get( "color" ) or DEFAULT_PERSONA_COLOR,
    }


@mcp.tool
def commons_post(
    topic    : str,
    body     : str,
    metadata : Optional[ dict ] = None,
) -> dict:
    """
    Dual tier marker (depends on topic):
    - **[SELF-DISCLOSURE]** — free-form / presence / incident topics (announcing your own state)
    - **[ATTENTION-DEMANDING]** — coordination / help-wanted / contested-claim topics (summons peer attention)

    Append an entry to a commons topic (file-based inter-session blackboard).

    Examples:
        # Self-disclosure: announce your own state
        commons_post(topic="presence", body="starting long migration", metadata={"kind": "status"})

        # Threaded reply to a DM (closes the loop on a `COMMONS PEER MESSAGE`):
        commons_post(
            topic    = "dm-tiberius",
            body     = "yes, that fix landed in commit f4e0370",
            metadata = {"in_reply_to": "<question_id_from_system_reminder>", "kind": "answer"}
        )

    Free-form topics auto-create on first post. Reserved topics
    (`broadcast-acks`, `presence`, `system-events`) are pre-seeded by the store.
    Persona fields are stamped from the session bridge at post-time and are
    immutable thereafter (per C4 ratification) — you cannot spoof another persona.

    **Threading callout**: to reply to a `COMMONS PEER MESSAGE` or
    `COMMONS PEER REPLY` system-reminder, pass `metadata={"in_reply_to": <qid>}`
    where `<qid>` is the `question_id` from the system-reminder. The original
    asker's Phase 3 watcher (if running) will push your reply back to their
    tmux via `commons_answer_received`. **Threading isn't free**: if the asker
    forgot `expect_reply=True` or already unregistered the question, the reply
    lands silently on the blackboard — the asker will see it only on their
    next `commons_read` poll.

    **Failure-mode hint**: posting user-sensitive data is prohibited —
    see cross-session-communication.md §5 for the sensitive-content rules.
    Free-form topics have a 7-day retention by default; reserved topics may
    have different retention.

    Args:
        topic: Topic name (free-form or one of the reserved topics)
        body: The message body (any string)
        metadata: Optional dict of extra metadata fields. Common patterns:
            - `{"kind": "status"}` for presence pings
            - `{"kind": "answer", "in_reply_to": <qid>}` for threaded replies
            - `{"kind": "incident", "severity": "warn|error|info"}` for incidents

    Returns:
        dict with `ts`, `sender_session_id`, `persona_name`, `persona_icon`,
        `persona_color`, `body`, `metadata`

    See: planning-is-prompting → workflow/cross-session-communication.md
         (§2 autonomy tiers, §3 reserved topics, §5 sensitive-content rules)
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    persona = _commons_persona_fields()
    return _get_commons_store().post(
        topic             = topic,
        body              = body,
        sender_session_id = SESSION_ID,
        persona_name      = persona[ "persona_name" ],
        persona_icon      = persona[ "persona_icon" ],
        persona_color     = persona[ "persona_color" ],
        metadata          = metadata,
    )


@mcp.tool
def commons_read(
    topic : str,
    since : Optional[ str ] = None,
    limit : int = 50,
) -> list:
    """
    **[READ — always allowed, no user permission needed]** Tail a commons topic.

    Examples:
        # Most recent 10 entries on the DM topic addressed to you
        commons_read(topic="dm-maria", limit=10)

        # New entries since you last polled (Phase 1 polling-mode pattern)
        commons_read(topic="dm-tiberius", since="2026-05-16T22:00:00+00:00")

    Returns newest-first when `since` is None, ascending when `since` is supplied.
    Honors `limit` strictly. Missing free-form topic → empty list (no error).

    Common pattern: when a `COMMONS PEER MESSAGE` system-reminder arrives,
    call `commons_read(topic=<topic>, limit=10)` and find the entry whose
    `metadata.question_id` matches the system-reminder's `question_id`.

    Args:
        topic: Topic name to read from
        since: Optional ISO-8601 timestamp; only entries with `ts > since` are returned
        limit: Maximum number of entries to return (default 50)

    Returns:
        List of entry dicts, each containing ts, sender_session_id, persona_*,
        body, metadata

    See: planning-is-prompting → workflow/cross-session-communication.md
         (§1.5 DM mechanics + receipt etiquette)
    """
    if not _commons_enabled(): return [ ]
    return _get_commons_store().read( topic=topic, since=since, limit=limit )


@mcp.tool
def commons_who(
    topic            : Optional[ str ] = None,
    retention_hours  : int = 24,
) -> list:
    """
    **[READ — always allowed, no user permission needed]** "Who else is active right now?"

    Examples:
        # Who's been active across all topics in the last 24 hours (default)
        commons_who()

        # Narrow window — last hour only (helps filter stale-bridge phantoms)
        commons_who(retention_hours=1)

        # Who's posted to a specific topic in the last 24 hours
        commons_who(topic="broadcasts", retention_hours=24)

    If `topic` is supplied, scans only that topic; otherwise scans every active
    topic file. Each row gives the most recent post timestamp for that session
    plus their persona name/icon/color.

    **Failure-mode hint**: results may include phantom personas — sessions whose
    host process has died but whose bridge file lingers until the next host-side
    prune. If a DM to a "visible" peer never gets a reply, the recipient may
    be a phantom. Cross-reference with `retention_hours=1` for a narrower window.

    Args:
        topic: Optional topic name; if omitted, scans all topics
        retention_hours: Freshness window in hours (default 24)

    Returns:
        List of dicts `{session_id, persona_name, persona_icon, persona_color, last_post_ts}`,
        sorted by last_post_ts descending

    See: planning-is-prompting → workflow/cross-session-communication.md
    """
    if not _commons_enabled(): return [ ]
    return _get_commons_store().who( topic=topic, retention_hours=retention_hours )


@mcp.tool
def commons_ask_sync(
    topic            : str,
    body             : str,
    timeout_seconds  : float = 120.0,
    grace_seconds    : Optional[ float ] = None,
) -> dict:
    """
    **[ATTENTION-DEMANDING + BLOCKING — rarely justified; consider `commons_ask_async` first]**
    Post a question to commons and block until the first reply arrives + grace expires.

    Example:
        # Synchronously poll peers for the latest build hash, wait up to 60s
        result = commons_ask_sync(topic="builds", body="latest hash?", timeout_seconds=60)
        for entry in result["replies"]:
            print(entry["body"])

    Hybrid first+grace timing (A3b ratification): the call blocks until the
    FIRST matching reply arrives in `topic`, then waits an additional
    `grace_seconds` to coalesce any fast follow-up replies, and returns the
    accumulated list. Replies are correlated via `metadata.in_reply_to`
    matching the question's auto-generated `question_id`.

    **Prefer `commons_ask_async`** in nearly all cases — it returns immediately,
    starts a Phase 3 watcher that pushes the recipient's reply back to your
    tmux when it arrives, and frees your session to do other work in the
    meantime. The sync variant is only justified when downstream logic
    LITERALLY cannot proceed without the reply AND a fixed timeout is acceptable.

    On timeout with zero replies, returns `{..., replies: []}`.

    Args:
        topic: Topic to post the question to (and listen on for replies)
        body: The question text
        timeout_seconds: Maximum wait for the first reply (default 120)
        grace_seconds: Additional wait after first reply for follow-up replies
            (default from `commons ask sync grace seconds` INI key; falls back to 1.0)

    Returns:
        dict `{question_id, posted_ts, replies: [entry, ...]}`

    See: planning-is-prompting → workflow/cross-session-communication.md
         (§1.5 DM mechanics — note this is the BLOCKING variant)
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    grace = grace_seconds if grace_seconds is not None else _commons_ask_sync_grace_default()
    persona = _commons_persona_fields()
    return _commons_ask_sync_impl(
        store             = _get_commons_store(),
        topic             = topic,
        body              = body,
        sender_session_id = SESSION_ID,
        persona_name      = persona[ "persona_name" ],
        persona_icon      = persona[ "persona_icon" ],
        persona_color     = persona[ "persona_color" ],
        timeout_seconds   = timeout_seconds,
        grace_seconds     = grace,
    )


@mcp.tool
def commons_ask_async(
    topic                : str,
    body                 : str,
    question_id          : Optional[ str ] = None,
    recipient_session_id : Optional[ str ] = None,
    recipient_persona    : Optional[ str ] = None,
    expect_reply         : bool            = True,
) -> dict:
    """
    **[ATTENTION-DEMANDING — requires user trigger or clear coordination need]**
    Post a question to commons and return immediately (fire-and-forget).

    Examples:
        # Polling-mode: ask the topic at large, poll for replies yourself
        result = commons_ask_async(topic="builds", body="latest hash?")
        # Later: commons_read(topic="builds", since=result["posted_ts"]) → filter on in_reply_to

        # DM-mode: directed to a specific persona, push-back to asker
        result = commons_ask_async(
            topic             = "dm-tiberius",
            body              = "any blockers on the doctrine refresh?",
            recipient_persona = "tiberius",
            expect_reply      = True,
        )
        # If result["push_mode_active"] is True, tiberius's listener got pushed.
        # His reply will arrive in YOUR tmux as a COMMONS PEER REPLY system-reminder.

    **`expect_reply` side-effect** (default True): when True, the server starts
    an asker-side Phase 3 `CommonsQuestionWatcher` that polls the answer topic
    + pushes the recipient's reply back to your tmux via `commons_answer_received`
    notification injection. When False, the watcher is skipped — fire-and-forget,
    no asker-side correlation. Set False for status pings / acknowledgments;
    leave True when you genuinely need the reply pushed back.

    **Recipient experience** — when push fires (push_mode_active: true), the
    recipient sees this as a `COMMONS PEER MESSAGE` `<system-reminder>` block
    injected into their next turn. When push fails (push_mode_active: false),
    the message lands on the blackboard topic and the recipient sees it only
    on their next `commons_read` poll. Either way the entry is durable.

    **Failure-mode hint** — check `push_mode_active` and `register_skip_reason`
    in the result:

    - `push_mode_active: true, dm_dispatched: true` → recipient got auto-injection ✅
    - `push_mode_active: false` → polling fallback. Check `register_skip_reason`:
        - `missing_auth_header` → MCP couldn't build the X-API-Key (key file issue)
        - `register_network_error` → :7999 server unreachable
        - `register_failed_status_N` → non-2xx (rate limit, server error)
        - `register_failed_422` → recipient resolution failed — see `recipient_resolution_error`
    - `recipient_resolution_error: {...}` → recipient persona/session_id didn't resolve.
      The dict carries `resolution_chain_attempted` + `candidate_alternatives` +
      `suggested_next_action`. Read those before retrying with a different recipient.

    Inter-Session DM mode (auto-activated when `recipient_session_id` OR
    `recipient_persona` is supplied):
    - Push-mode forced on; HTTP register fires with recipient kwargs
    - Server resolves recipient (session_id wins, else persona via
      exact → case-insensitive → punct-tolerant match)
    - Dispatches `commons_question_received` to recipient's listener fire-and-forget

    Args:
        topic: Topic to post the question to
        body: The question text
        question_id: Optional UUID; if omitted, auto-generated
        recipient_session_id: Optional explicit recipient session_id (precise)
        recipient_persona: Optional recipient persona name (fuzzy-resolved)
        expect_reply: When False, server skips reply-tracking watcher overhead

    Returns:
        dict — Phase 1: `{question_id, posted_ts, push_mode_active}`;
        DM mode adds: `dm_dispatched: bool | None`;
        push-mode skip adds: `register_skip_reason: str`;
        on recipient resolution failure: `recipient_resolution_error: dict`

    See: planning-is-prompting → workflow/cross-session-communication.md
         (§1.5 DM mechanics + threading + receipt etiquette;
          §1.5.1 result-shape table for push_mode_active / dm_dispatched / register_skip_reason)
    """
    return _commons_ask_async_dispatch(
        topic                = topic,
        body                 = body,
        question_id          = question_id,
        recipient_session_id = recipient_session_id,
        recipient_persona    = recipient_persona,
        expect_reply         = expect_reply,
    )


def _derive_dm_topic( recipient: str ) -> str:
    """
    Derive a server-pattern-safe DM topic from a recipient persona name.

    Per Rick's Q8 architectural directive (2026-05-17 coordinator walkthrough):
    unicode all the way down. Topic file names preserve the persona's exact
    unicode spelling (e.g. `María` → `dm-maría`, `José Ruiz` → `dm-josé_ruiz`).
    The `re.UNICODE` flag treats letters in any script as word characters;
    only path-dangerous chars and whitespace collapse to `_`.

    Pairs with the unicode-broadened server-side topic pattern at
    `src/cosa/rest/routers/commons.py:100` (`_TOPIC_OR_QID_PATTERN`).

    Requires:
        - recipient is a non-empty string

    Ensures:
        - return value matches the server-side `[\\w-]+` (re.UNICODE) pattern
        - return value starts with `"dm-"`
        - input is lowercased before sanitization (case-insensitive topic-file
          collision per Sub-bug A fix)
        - whitespace and other non-word chars collapse to `_` (Sub-bug C fix)
    """
    sanitized = re.sub( r"[^\w-]+", "_", recipient.lower(), flags=re.UNICODE )
    return f"dm-{sanitized}"


def _commons_ask_async_dispatch(
    topic                : str,
    body                 : str,
    question_id          : Optional[ str ]  = None,
    recipient_session_id : Optional[ str ]  = None,
    recipient_persona    : Optional[ str ]  = None,
    expect_reply         : bool             = True,
) -> dict:
    """
    Shared dispatch helper for `commons_ask_async` and `commons_send_to`.

    Necessary because `@mcp.tool`-decorated functions are wrapped into
    `FunctionTool` instances which are NOT directly callable as Python
    functions. Without this private helper, `commons_send_to` calling
    `commons_ask_async` by name raises
    `TypeError: 'FunctionTool' object is not callable` at runtime.

    Both MCP tools delegate here so they share the persona / auth /
    base-URL construction and the push-mode auto-enable rule.

    Requires:
        - `topic` and `body` are non-empty strings
        - `recipient_session_id` XOR `recipient_persona` may be supplied (or neither)

    Ensures:
        - Returns the `_commons_ask_async_impl` result dict verbatim
        - On `_commons_enabled() is False`, returns `{"status": "error", "reason": "commons disabled"}`
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    persona = _commons_persona_fields()

    # Push-mode auto-enables when caller wants directed DM dispatch
    push_mode    = recipient_session_id is not None or recipient_persona is not None
    api_base_url = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
    api_key      = _mcp_outbound_api_key()
    auth_header  = { "X-API-Key": api_key } if api_key else None

    return _commons_ask_async_impl(
        store                = _get_commons_store(),
        topic                = topic,
        body                 = body,
        sender_session_id    = SESSION_ID,
        persona_name         = persona[ "persona_name" ],
        persona_icon         = persona[ "persona_icon" ],
        persona_color        = persona[ "persona_color" ],
        question_id          = question_id,
        push_mode_enabled    = push_mode,
        api_base_url         = api_base_url,
        auth_header          = auth_header,
        recipient_session_id = recipient_session_id,
        recipient_persona    = recipient_persona,
        expect_reply         = expect_reply,
    )


@mcp.tool
def commons_send_to(
    recipient    : str,
    body         : str,
    expect_reply : bool            = False,
    in_reply_to  : Optional[ str ] = None,
    topic        : Optional[ str ] = None,
    question_id  : Optional[ str ] = None,
) -> dict:
    """
    **[DM — directed attention-demanding]** Thin persona-routed wrapper over `commons_ask_async`.
    Send a directed inter-session DM to another CC session.

    Examples:
        # Basic DM by persona name (most common):
        commons_send_to(recipient="tiberius", body="have you touched src/auth.py today?")

        # Threaded reply to a prior received DM:
        commons_send_to(
            recipient   = "tiberius",
            body        = "yes — landed in commit f4e0370 around 21:00 UTC",
            in_reply_to = "<question_id_from_their_system_reminder>",
        )

        # Fire-and-forget status ping that doesn't need a reply pushed back:
        commons_send_to(recipient="rachel", body="thanks for the doc-scope work", expect_reply=False)

    Per Phase 0 Q1-rev (2026-05-15 ratified): thin ergonomic wrapper around
    `commons_ask_async` that defaults to fire-and-forget semantics and
    addresses the recipient by persona name. The underlying register-question
    endpoint resolves the persona (exact → case-insensitive → punct-tolerant),
    dispatches `commons_question_received` to the recipient's listener via
    tmux injection, and stamps `metadata.recipient_persona` on the topic
    entry so Recent Activity renders a DM badge.

    **`expect_reply` side-effect** (default False for this wrapper, vs True
    for `commons_ask_async`): when True, the server starts an asker-side
    Phase 3 watcher that pushes the recipient's reply back to your tmux via
    `commons_answer_received` notification injection. Use True for genuine
    questions where you need the reply; leave False for status pings.

    **Recipient experience** — same as `commons_ask_async` DM mode: when push
    fires, the recipient sees this as a `COMMONS PEER MESSAGE` `<system-reminder>`
    block injected into their next turn. When push fails (`push_mode_active: false`
    in the result), the message lands on the blackboard topic at `dm-{recipient}`
    and the recipient sees it only on their next `commons_read` poll.

    **Failure-mode hint** — identical to `commons_ask_async`: check
    `push_mode_active` and `register_skip_reason` in the result dict.
    `register_skip_reason: missing_auth_header` is the most common (the MCP
    server's outbound X-API-Key couldn't be loaded — usually means the
    cosa-voice MCP subprocess started before commit `f4e0370` landed).

    Power users who need session_id-precise addressing or finer-grained
    control over topic + question_id can call `commons_ask_async` directly
    with the equivalent kwargs.

    Args:
        recipient: Recipient persona name (e.g. "radio", "rachel", "Maria").
                   Server-side persona resolution is fuzzy: case-insensitive
                   and punctuation/whitespace-tolerant.
        body: Message body
        expect_reply: Default False (fire-and-forget). When True, the asker-side
                      watcher tracks for replies via Phase 3 push-back-to-asker.
        in_reply_to: Optional question_id from a prior received DM (threads
                      the reply via metadata; recipient sees correlation in
                      the system-reminder framing).
        topic: Optional topic override. Default `dm-<recipient>` for routing
                clarity.
        question_id: Optional explicit question_id; auto-generated if omitted.

    Returns:
        Same shape as `commons_ask_async`. On recipient resolution failure,
        the result carries `recipient_resolution_error` describing what was
        tried + candidate alternatives + suggested next action.

    See: planning-is-prompting → workflow/cross-session-communication.md
         (§1.5 DM mechanics + threading + receipt etiquette;
          §1.5.1 result-shape table;
          §6.5.1 cross-session bug-filing pattern with mermaid flow)
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    target_topic = topic or _derive_dm_topic( recipient )
    # When `in_reply_to` is supplied, the body's effective context is "reply to a prior DM" —
    # we still go through _commons_ask_async_dispatch, but stamp `in_reply_to` on the result
    # so the original asker's Phase 3 watcher (if running) correlates this entry as the answer.
    # Effective recipient is the persona; in_reply_to threading is handled at the metadata layer.
    #
    # Bug-fix 2026-05-16: this used to call the `commons_ask_async` name directly, but that name
    # resolves to the `@mcp.tool`-decorated `FunctionTool` instance (not a Python callable),
    # producing `TypeError: 'FunctionTool' object is not callable` on every invocation. Route
    # through the shared private `_commons_ask_async_dispatch` helper instead.
    result = _commons_ask_async_dispatch(
        topic                = target_topic,
        body                 = body,
        question_id          = question_id,
        recipient_persona    = recipient,
        expect_reply         = expect_reply,
    )
    if in_reply_to is not None and isinstance( result, dict ):
        # Surface the in_reply_to on the result so callers can see the threading.
        result[ "in_reply_to" ] = in_reply_to
    return result


if __name__ == "__main__":
    _maybe_start_commons_archival_daemon()
    mcp.run()
