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
from typing import List, Optional

from pydantic import ValidationError
from fastmcp import FastMCP

from lupin_mcp.persona_normalization import persona_slug

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

# The priorities speakerphone mode may LIFT to "high" — the RECOGNISED ones that are not
# already at or above it. Derived from the enum rather than written out, so a new member
# cannot silently fall outside the set. Anything NOT in here (including a typo) is left
# untouched so it reaches NotificationPriority(...) validation and gets reported.
_SPEAKERPHONE_LIFTABLE_PRIORITIES = frozenset(
    p.value for p in NotificationPriority if p.value not in ( "high", "urgent" )
)
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
from lupin_cli.claude_code.hooks.lib.hook_common import (
    log_to_stream,
    _brevity_rules,
    _routing_reminder,
    DM_STYLE_TAG,
)


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
            timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS
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

# Transport budget for out-of-process HTTP calls to SERVER_URL (row 204911ca,
# 2026-07-20). ~30s = 1.60x the observed maximum `:7999` reload window of 18.76s
# — a multiplier with explicit headroom, NOT a coverage guarantee.
#
# WHY THESE CALLS NEED IT. This MCP server runs in its OWN process, so a `:7999`
# reload does not tear it down alongside the request. `:7999` runs
# `uvicorn --reload`, and the reloader parent keeps the listening socket bound
# across a restart — the kernel ACCEPTS a request that nothing is there to
# answer, so the caller hangs and eventually raises TimeoutError rather than
# getting a fast ConnectionRefused. Measured over 8.4 days of container logs
# (current-config clean-reload class, n=143): min 6.59s, median 6.91s, max
# 18.76s. All 143 exceed the 5s these call sites used to allow, so every one of
# them failed on every reload it happened to land in.
#
# THE TRADE, stated plainly: a genuinely hung server now takes ~30s to report
# instead of ~5s. Accepted knowingly — these are low-frequency calls (login,
# speakerphone toggle, persona allocate) where a lost result is worse than a
# slow one. It is not free.
#
# ⚠️ Applies to READ budgets on out-of-process calls only. A split
# connect/read tuple is NOT exposed: connect SUCCEEDS during a reload (the
# kernel accepted), so only the read leg can hang.
_SERVER_TRANSPORT_TIMEOUT_SECONDS = 30

_session_ready    = threading.Event()   # Gate: blocks tool calls until session ID resolved
_session_failed   = False               # True if real ID never arrived (fallback only)

# POSITIVE SERVER DISCRIMINATOR — row 87ae7234.
# `_die_no_session_id` calls os._exit(1), which is correct for the MCP server and
# catastrophic for anything that merely IMPORTS this module: os._exit skips every
# flush, atexit hook and exception path, so an importing process dies with no
# traceback and no summary. Four call sites in this module can reach it.
#
# This flag decides which process we are, and it is set POSITIVELY at the single
# entry point (the `if __name__ == "__main__":` block at the bottom of this file)
# rather than inferred from an environment variable, from PYTEST_CURRENT_TEST, or
# from the ABSENCE of something. An inference stops matching silently when the
# world changes; a positive assignment at the entry point does not.
#
# It lives in that block because that is where this codebase ALREADY means "I am
# the server" — `_maybe_start_commons_archival_daemon()` is there for the same
# reason — so server-only state stays in one known place instead of inventing a
# second convention.
#
# WARNING: IF YOU ADD A NEW ENTRY POINT — a console_scripts / [project.scripts]
# shim that IMPORTS this module and calls into it rather than running the file —
# YOU MUST SET THIS FLAG THERE TOO. Otherwise a real server reads False and a
# genuine session-id failure raises instead of exiting, leaving a server up that
# cannot serve. There are none today: zero entry-points are declared, and every
# registered launch runs `python .../cosa_voice_mcp.py` in script mode.
_IS_MCP_SERVER    = False

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


def _watch_bridge_for_changes( stop_event=None, poll_interval=2.0, max_iterations=None ):
    """
    Watch the resolved bridge file and update SESSION_ID / SENDER_ID when it changes.

    PHASE 2 of the session watcher, split out of `_session_watcher_thread` so a test
    can start it DELIBERATELY and assert on what it did — row `87ae7234`. Phase 1
    (the one-shot resolve that sets `_session_ready`) stays where it was and still
    runs at import: it is load-bearing, nothing here is.

    Requires:
        - phase 1 has run, so SESSION_ID / SENDER_ID hold their resolved values
        - poll_interval is a positive number of seconds

    Ensures:
        - returns when stop_event is set, or after max_iterations polls, or never
          (the server's case: both arguments omitted)
        - updates the SESSION_ID / SENDER_ID globals when the bridge file's session
          id changes, and logs the transition
        - a per-iteration exception is logged and the loop CONTINUES — one bad poll
          must never end the watch
        - does not raise
    """
    global SESSION_ID, SENDER_ID

    last_mtime      = 0.0
    last_session_id = SESSION_ID
    iterations      = 0

    logger.info( "Session watcher: entering persistent monitoring loop" )

    while stop_event is None or not stop_event.is_set():
        if max_iterations is not None and iterations >= max_iterations: return
        iterations += 1
        try:
            # A stop_event waits INTERRUPTIBLY so a test does not pay the poll
            # interval to shut the loop down; without one this is the original sleep.
            if stop_event is not None:
                if stop_event.wait( timeout=poll_interval ): return
            else:
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
                old_sender      = SENDER_ID
                SESSION_ID      = new_suffix
                SENDER_ID       = _get_sender_id( CANONICAL_PROJECT, SESSION_ID )
                last_session_id = new_suffix
                logger.info(
                    f"Session ID changed: {old_sender} -> {SENDER_ID} "
                    f"(context clear detected)"
                )

        except Exception as e:
            logger.error( f"Session watcher error: {e}" )


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
    _watch_bridge_for_changes()


_watcher_thread = threading.Thread(
    target=_session_watcher_thread,
    name="session-id-watcher",
    daemon=True
)
_watcher_thread.start()


class SessionIdUnavailable( RuntimeError ):
    """
    Raised instead of hard-exiting when the session ID never resolved and this
    process is NOT the MCP server.

    The MCP server must die on this condition — it cannot serve tools without a
    session id. An importing process must NOT: a library that calls os._exit takes
    its host down with no traceback, which is how a test suite came to report a
    truncated run with nothing anywhere naming the cause.
    """


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

    # SAY WHY ON THE WAY OUT. os._exit skips every flush, atexit hook and
    # exception path, so a caller that imports this module — a test process
    # above all — dies with no traceback, no summary and no logging record:
    # pytest reports a truncated run and nothing anywhere names the cause.
    # logger.critical above is captured by pytest and lost with it; an
    # explicitly-flushed stderr write is not. Two lines, no behaviour change
    # for the server, and the difference between a silent kill and a named one.
    if not _IS_MCP_SERVER:
        # NOT the server — raise, do not kill the host. The caller gets a named
        # exception it can catch and a traceback naming this function.
        raise SessionIdUnavailable(
            "Claude Code session ID never resolved and this process is not the MCP "
            "server, so _die_no_session_id() raised instead of calling os._exit(1). "
            "No session bridge file was detected."
        )

    sys.stderr.write(
        "[cosa-voice] FATAL: Claude Code session ID never resolved; "
        "os._exit(1) from _die_no_session_id(). No session bridge file was "
        "detected. If you are seeing this from a test run, the process was "
        "terminated here — the suite did not finish.\n"
    )
    sys.stderr.flush()

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
# Speakerphone TTS Contract (once-stated, single-sourced)
# ============================================================================
#
# Per src/rnd/v0.1.9/2026.06.27-cosa-voice-rider-slim.md §4: the full standing
# TTS contract is stated ONCE here in the session-init `instructions` payload.
# The per-turn `<system-reminder>` rider (hook_common._speakerphone_reminder_body)
# is now slim and only points at this section. The brevity + routing prose is
# single-sourced from hook_common._brevity_rules() + _routing_reminder() — the
# SAME functions the rider historically composed from and the same
# cu.get_spoken_char_cap() source the caller-side enforcement guard reads — so
# the spoken-char cap never drifts between the rider, this contract, and the
# server reject boundary.

_TTS_CONTRACT_SECTION = (
    "## Speakerphone TTS Contract (applies on every turn — speakerphone is the standing default)\n\n"
    "CLOSING TURN: after your user-facing reply, call "
    "notify(message=<full reply, recrafted for speech>, suppress_ding=True, priority='high').\n\n"
    + _brevity_rules() + "\n\n"
    + _routing_reminder() + "\n\n"
)


# ============================================================================
# DM Style Contract (DM brevity/tone contract, Rick 2026-07-31 — always on,
# no toggle. See src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/)
# ============================================================================
#
# Closes the gap the research found: the fleet already reminds a peer how to
# REPLY (DM_STYLE_TAG on the reply affordance in hook_common.py), but nothing
# shaped how a DM is COMPOSED in the first place. This section states that
# explicitly, spliced unconditionally into the MCP `instructions` payload.
_DM_STYLE_CONTRACT_SECTION = (
    "## DM Style Contract (governs `dm_send` — composing AND replying)\n\n"
    "Every dm_send body is written under this contract BEFORE you send it, "
    "not only when replying to one. Lead with the result. Plain, literal "
    "sentences — write it as a human colleague would read it, no invented "
    "vocabulary. Report only decisions, evidence, risks, and required "
    "actions; do not narrate routine reasoning or verification; no "
    "metaphors, aphorisms, slogans, or redundant summaries. "
    # Rick, 2026-08-13: "3 sentences and a path with no word counts to be found
    # anywhere." The word budget that used to sit here ("3 lines / ~60 words") is
    # gone deliberately — a count in the composition contract is the same leak the
    # tutor's trigger number is kept out of: it teaches the fleet to write TO a
    # number rather than to the shape. The path clause is load-bearing, because
    # without it the pointer reads as a fourth sentence and the compliant house
    # style looks non-compliant (María, 2026-08-13).
    "Say it in three sentences — a headline and two supporting statements. "
    "When the detail lives somewhere, send the path instead of the detail. The "
    "path is a pointer, not a fourth sentence, and does not count against the "
    f"three. Longer ONLY WHEN ASKED. {DM_STYLE_TAG}\n\n"
)


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
        f"inbound user message is now SLIM: it carries only the live turn-state "
        f"(the input modality — voice-from-a-distance vs typed) plus a pointer to "
        f"the standing TTS contract. It does NOT repeat the full contract each "
        f"turn — the complete obligations live ONCE in the § Speakerphone TTS "
        f"Contract section below. The two are complementary: `instructions` "
        f"(this payload, including that contract section) is the standing "
        f"contract; the slim rider is the per-turn 'contract is ACTIVE — here is "
        f"what changed' marker under it.\n\n"

        # =====================================================================
        # The once-stated TTS contract (rider-slim §4). Single-sourced from
        # hook_common._brevity_rules() + _routing_reminder() so the spoken-char
        # cap never drifts between this contract and the per-turn rider.
        # =====================================================================
        f"{_TTS_CONTRACT_SECTION}"

        f"{_DM_STYLE_CONTRACT_SECTION}"

        f"## Your Toolkit at a Glance\n\n"
        f"This server exposes 18+ tools grouped by function. Scan this map "
        f"before reading the per-tool docstrings:\n\n"
        f"| Group | Tools | One-line purpose |\n"
        f"|---|---|---|\n"
        f"| **Notifications** | `notify` | Fire-and-forget announcement; spoken via TTS in speakerphone mode |\n"
        f"| **Blocking decisions** | `ask_yes_no`, `ask_multiple_choice`, `converse`, `ask_open_ended_batch` | Block until user responds; route by question shape (see § Interactive Tool Routing) |\n"
        f"| **Commons read** | `commons_read`, `commons_who` | Always-allowed inspection of cross-session traffic |\n"
        f"| **Commons self-disclosure** | `commons_post` | Append to topic blackboard; recipient sees on next poll |\n"
        f"| **Peer DM** | `dm_send` | Directed AI↔AI direct message to a peer persona — body inline (~204 tokens), zero re-fetch |\n"
        f"| **Commons polling** | `commons_ask_async`, `commons_ask_sync` | Post a question to a topic at large + poll for replies (DM-mode retired — use `dm_send`) |\n"
        f"| **Session state** | `get_session_info`, `set_session_topic`, `enable_speakerphone`, `disable_speakerphone`, `request_persona` | Read or update this session's bridge state |\n\n"
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
        f"Send via `notify(notification_type='custom', priority='medium', suppress_ding=False)`.\n\n"
        f"**If `voice_persona` is None (allocation failed), do NOT skip — ANNOUNCE THE NULL.** "
        f"A session that boots healthy announces itself, so a session that boots broken must not "
        f"go quiet: skipping optimises the greeting's CONTENT and silences the ALARM, leaving the "
        f"system quietest exactly when something is wrong. There is no name to greet with, so "
        f"announce the FAULT and identify yourself by session id instead:\n"
        f"- spoken `message` — state that this session has no voice persona, and give the FIRST 8 "
        f"CHARACTERS of `claude_code.session_id`. Example: 'Warning — this session booted with no "
        f"voice persona assigned. Session a1b2c3d4, running unattributed.'\n"
        f"  **This is an explicit, deliberate EXCEPTION to the standing TTS rule that ids, hashes "
        f"and other machine strings belong in `abstract` and never in spoken text.** That rule is "
        f"correct everywhere else and WRONG here, for one reason: normally the persona badge and "
        f"the persona VOICE carry identity, so the spoken channel never needs it. In this case "
        f"there is no badge and no distinct voice — the alarm is spoken in the fallback voice, "
        f"anonymously, alongside every other session. 8 characters is the whole cost. Put them in "
        f"the speech. Do NOT silently relocate the id to `abstract` only and consider the "
        f"obligation met — a listener at a distance would hear an unattributed alarm and have no "
        f"idea which session is broken.\n"
        f"- `abstract` — repeat the FULL `claude_code.session_id` plus the project name.\n\n"
        f"**The session id is MANDATORY in both, not optional and not cosmetic.** The UI persona "
        f"badge is gated on `sender_id && voice_persona`, so a null session's card renders with "
        f"its message and abstract intact but WITHOUT its badge — the one channel that normally "
        f"carries identity is exactly the channel that disappears. If the id is not in the text, "
        f"nobody can tell who sent the alarm and the card is unactionable. Then follow Failure "
        f"Mode 2 below (notify + manager DM come BEFORE any blocking `converse()`).\n\n"
        f"Fires once per Phase A startup including after "
        f"`/clear` (the persona persists across /clear, so re-announcing keeps the session "
        f"audibly tagged for users running parallel CC sessions).\n\n"

        # =====================================================================
        # MCP Startup Protocol (G1) — Phase A + Phase B
        # =====================================================================
        f"## MCP Startup Protocol\n\n"
        f"You MUST complete this two-phase startup before any substantive work.\n\n"
        f"**Phase A — Immediate, before composing your first response**:\n\n"
        f"1. Call `get_session_info()` once. The response carries critical session identity + state:\n"
        f"   - `voice_persona` dict (`{{name, display_name, voice_id, icon, color, borrowed}}`) — your assigned persona. **MUST extract before any user-facing text**: in chorus mode, your persona voice is the disambiguator the listener relies on. If `voice_persona` is None (allocation failure), do NOT open with a blocking `converse()`. FIRST emit the null-announcing `notify()` carrying your session id (see § Voice Persona Self-Announcement above), and DM your manager if you have one — both are zero-interrupt and neither needs anyone's permission. Only escalate to `converse()` if the null actually blocks the work in front of you. See Failure Mode 2.\n"
        f"   - `speakerphone_on` (bool) + `tts_interaction_mode` (`solo` | `chorus`) — drives the per-turn obligations you'll see in the rider.\n"
        f"   - `claude_code.session_id` — your stable session identity, used in cross-session DM correlation.\n"
        f"2. Report MCP server status to the user in your first acknowledgment (project name, session_id, server_url, version, your resolved persona name).\n"
        f"3. Call `notify(notification_type='custom', priority='medium')` — ALWAYS, in BOTH cases. If `voice_persona.name` is non-null, send a time-of-day-appropriate greeting using `display_name`. If `voice_persona` is None, send the null alarm naming your session id instead. **You announce either way**; the null case is the one that most needs to be heard, and it is the only zero-interrupt broadcast in startup. See § Voice Persona Self-Announcement above for both forms.\n\n"
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
        f"| **ATTENTION-DEMANDING** | `commons_post` to coordination/help-wanted topics; `commons_ask_async` / `commons_ask_sync` (topic polling); `dm_send` (directed peer DM); broadcasts | Requires clear coordination need OR explicit user trigger. Summons a peer recipient's attention. |\n\n"
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
        f"## Peer DM Workflow\n\n"
        f"Directed AI↔AI messaging uses **`dm_send`** — the notification-native peer-DM tool. The body travels INLINE in the recipient's push (direction='ai_to_ai', ~204 tokens), so the recipient processes it directly with ZERO re-fetch. (The legacy `commons_send_to` tool + the DM-mode of `commons_ask_async` — which routed through the commons claim-check path at ~3,700 tokens/received DM — were RETIRED in the cosa-voice token-reduction Phase 4, 2026-06-15.)\n\n"
        f"| Tool | Use when |\n"
        f"|---|---|\n"
        f"| `dm_send(recipient='persona', body=...)` | Directed peer DM by persona name. Body inline, ~18× cheaper than the retired commons claim-check. The common case. |\n"
        f"| `commons_ask_async(topic, body)` | POLLING-mode only — post an open question to a topic at large + poll for replies yourself via `commons_read`. NOT a directed DM. |\n"
        f"| `commons_ask_sync` | BLOCKING topic poll — waits for a reply. Rarely justified. |\n\n"
        f"**Receipt + reply etiquette** — when a peer DM arrives (an inbound `dm_send`, direction='ai_to_ai'):\n\n"
        f"1. **Acknowledge receipt** before tool calls if you're in speakerphone mode (same rule as user prompts — silent tool-only turns break the audio loop).\n"
        f"2. **The body is INLINE** — it arrives in the DM framing itself; there is NO `commons_read` re-fetch and NO blackboard round-trip. Read it directly.\n"
        f"3. **Reply** with `dm_send(recipient=<sender>, body=<reply>, reply_to=<message_id>, thread_id=<thread_id>)` — the `message_id` + `thread_id` are surfaced in the inbound DM framing. A reply is just a DM back; there is no separate watcher and no `expect_reply` flag.\n"
        f"4. **Loop avoidance** — don't reply to a DM you yourself sent (compare the sender against `get_session_info()` if unsure).\n\n"
        f"**DM vs Broadcast — when to choose which**:\n\n"
        f"- **DM** (`dm_send`): peer-specific question or coordination request. One recipient. The recipient owes you attention; you owe them context.\n"
        f"- **Broadcast**: user-originated only. Sessions do NOT initiate broadcasts. When a broadcast arrives, it appears as a `USER BROADCAST` `<system-reminder>` injection — that's the user talking to multiple sessions at once.\n\n"
        f"**Cross-session bug-filing pattern** (durable backup for unreliable push):\n\n"
        f"When you discover a bug that affects a peer session's domain, BOTH:\n"
        f"1. DM the responsible session via `dm_send` (low-latency, body inline)\n"
        f"2. File a structured entry in their repo's `bug-fix-queue.md` (durable backup if push fails / they're offline)\n\n"
        f"This double-channel pattern is documented in detail at planning-is-prompting → workflow/cross-session-communication.md §6.5.1.\n\n"

        # =====================================================================
        # Interactive Tool Routing (G4)
        # =====================================================================
        f"## Interactive Tool Routing\n\n"
        f"When you need user input, **prefer the cosa-voice blocking tools over Claude Code's built-in `AskUserQuestion`** — those built-in questions render to the TERMINAL only (no TTS, no audio), so users in speakerphone mode never hear them.\n\n"
        f"| Question shape | Use | Why |\n"
        f"|---|---|---|\n"
        f"| Yes / No (binary) | `ask_yes_no(question, default='yes'\\|'no')` | Three-button UI with optional 'Neither' escape hatch when the question itself needs re-framing |\n"
        f"| 2-4 mutually-exclusive options | `ask_multiple_choice(questions=[{{...}}], default={{header: label}})` | Radio-button UI; supports multi-question batches; optional `default` dict keyed by question header returns `{{\"answers\": default}}` on timeout instead of an error |\n"
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
        f"**1. `dm_send` returns `{{status: 'error', reason: 'recipient_unresolved'}}`** — the recipient persona/session couldn't be resolved (same-user scoped). The `detail` carries the RecipientResolutionError chain (what was attempted + candidate alternatives + suggested next action). Read it before retrying with a corrected recipient name. A transport/auth error returns `{{status: 'error', reason: ...}}` instead — the Lupin REST API may be down or the X-API-Key unavailable.\n\n"
        f"**2. `voice_persona: None` in `get_session_info()`** — the per-session persona allocator returned no assignment, OR the persona pool was exhausted and you got a 'Sam' overflow fallback (`borrowed: true` if from the legacy hash-borrow path). When None:\n\n"
        f"- DO NOT respond as 'Claude' or a placeholder — that breaks the chorus-mode disambiguation contract\n"
        f"- **DO NOT go quiet.** The remedies below are ORDERED BY COST, and the first two cost nothing. Work down the list; do not skip to the bottom.\n\n"
        f"| # | Do this | Interrupt cost | Permission needed |\n"
        f"|---|---|---|---|\n"
        f"| 1 | `notify()` the null alarm, naming your `claude_code.session_id` INLINE (§ Voice Persona Self-Announcement) | **none** — fire-and-forget | none; self-disclosure tier |\n"
        f"| 2 | `dm_send()` your manager, if you have one, so they can allocate for you | **none** | none; DM tier |\n"
        f"| 3 | `converse(message='Which persona am I?', response_type='open_ended')` | **one blocking interrupt to the user** | escalate ONLY if the null blocks the work |\n\n"
        f"**Why the order matters**: a standing drive-to-completion rule correctly prices out INTERRUPTS, so a worker that treats `converse()` as the only remedy will correctly decline it and stay unnamed indefinitely. That rule does NOT price out NON-BLOCKING SIGNALS. Steps 1 and 2 are free, are always permitted, and are what actually gets you named — someone with the authority to allocate can only help once they know you are null. Note that `request_persona()` remains USER-INITIATED ONLY; do not self-heal (see its docstring).\n"
        f"- This is rare (allocator is resilient); it indicates either a fresh session pool exhaustion or a bridge-file corruption\n\n"
        f"**3. (retired) Legacy commons-DM failure modes** — the `commons_send_to` 'FunctionTool not callable' bug, the `dm_dispatched`/`push_mode_active` register-question signals, and the topic-file case-fragmentation issue all belonged to the legacy commons claim-check DM path, RETIRED in the cosa-voice token-reduction Phase 4 (2026-06-15). They no longer apply — use `dm_send` (see Failure Mode 1).\n\n"
        f"**5. Stale-bridge phantom personas in `commons_who`** — `commons_who` may show sessions whose host process has died. The host-side prune at SessionStart eventually cleans these, but during the window between death and prune, they appear active. If a DM to a 'visible' peer never returns a reply, the recipient may be a phantom. Cross-reference with `commons_who(retention_hours=1)` for a narrower window.\n\n"

        f"**6. Persona-allocation cache staleness across MCP restart** — if your session was bounced (architecture switchover, manual MCP subprocess kill, etc.) AND the persona pool was exhausted such that you got a 'Sam' overflow allocation, an in-memory cache of the pre-bounce allocation may persist in the running MCP subprocess until you call `get_session_info()` fresh. After ANY MCP restart or pool-exhaustion event, re-call `get_session_info()` to confirm the current allocation matches what your bridge file says — the bridge file is the source of truth; the in-memory cache may lag.\n\n"

        # =====================================================================
        # Deep Doctrine Reference Footer (G10)
        # =====================================================================
        f"## Deep Doctrine Reference\n\n"
        f"For three-tier autonomy semantics, reserved topic vocabulary, anti-patterns, sensitive-content rules, broadcast routing diagrams, and the full cross-session-bug-filing pattern with mermaid flow, see the canonical reference at:\n\n"
        f"  **planning-is-prompting → workflow/cross-session-communication.md**\n\n"
        f"Key sections to bookmark:\n"
        f"- §1.5 — DM mechanics, threading, receipt etiquette, channel-choice\n"
        f"- §1.5.3 — Threading conventions (`in_reply_to` chains, sender-mailbox topic routing, loop-avoidance)\n"
        f"- §2 — Three-tier autonomy (READ / SELF-DISCLOSURE / ATTENTION-DEMANDING)\n"
        f"- §3 — Reserved topic vocabulary\n"
        f"- §4 — Broadcast receipt rules\n"
        f"- §6.5.1 — Cross-session bug-filing pattern (mermaid diagram of the double-channel flow)\n\n"
        f"That doc was refreshed 2026-05-16 by Tiberius 🌑 alongside the expansion of this `instructions` payload by María 🌸. Both surfaces are intentionally orthogonal — this file covers the cosa-voice-bound how-to; the doctrine file covers the deep semantics and policy."
    )
)


# ------------------------------------------------------------------------------
# v2.1 direct-state-visibility — SERVER per-MCP-call bridge-mtime stamp
# (arbiter design 03 §10.1 / §10.7). Bumps THIS session's bridge-file mtime on
# every inbound tool call so a heads-down (never-Stops) session still reports
# live liveness. Converges on the ONE host-side clock (redline C4) via
# touch_bridge_mtime — no parallel last-seen store. See bridge_liveness_middleware.
# ------------------------------------------------------------------------------
from lupin_mcp.bridge_liveness_middleware import BridgeLivenessMiddleware
mcp.add_middleware( BridgeLivenessMiddleware() )


# ------------------------------------------------------------------------------
# Spoken-brevity cap (caller-side TTS limit) — Rick 2026-06-02
# ------------------------------------------------------------------------------
# The spoken field (`message` / `question`) of the speaking tools is read aloud
# via TTS; long bodies become a "wall of text" in the user's ear. Detail belongs
# in the `abstract` parameter (rendered to the UI card, NEVER length-limited),
# not in the spoken channel. This cap is enforced CALLER-SIDE in the MCP layer
# ONLY — the notifications REST API stays unrestricted so agentic jobs / system
# events can still send longer payloads when they genuinely need to.
#
# The cap VALUE lives in lupin-app.ini (`cosa voice spoken char cap`, default 500)
# and is read via ConfigurationManager so it is TUNABLE AT RUNTIME: re-read
# mtime-gated (so the hot path stays cheap) on the next call after the INI changes
# — no MCP restart required. A spoken field over the cap is REJECTED unless the
# caller sets override_size_limitation=True (long is opt-in-and-intentional).
#
# SINGLE SOURCE OF TRUTH: the INI key + default are owned by cosa.utils.util so the
# per-turn TTS brevity rider (hook_common._brevity_rules, which names this number to
# the model) and this caller-side enforcement guard can NEVER drift. Do not inline a
# literal here — reference cu.
import cosa.utils.util as _cu_capsrc
SPOKEN_CHAR_CAP_DEFAULT = _cu_capsrc.SPOKEN_CHAR_CAP_DEFAULT
SPOKEN_ENFORCE_DEFAULT  = True   # default: guard ON. INI may flip it OFF for ALL callers.
_SPOKEN_CAP_INI_KEY     = _cu_capsrc.SPOKEN_CHAR_CAP_INI_KEY
_SPOKEN_ENFORCE_INI_KEY = "cosa voice enforce spoken char cap"
_spoken_cap_cache       = { "value": SPOKEN_CHAR_CAP_DEFAULT, "enforce": SPOKEN_ENFORCE_DEFAULT, "ini_mtime": None }


def _refresh_spoken_cfg():
    """
    Re-read the spoken cap + enforce flag from lupin-app.ini, mtime-gated.

    Ensures:
        - updates _spoken_cap_cache["value"] (int cap) AND ["enforce"] (bool) ONLY
          when the INI file mtime changed since the last read — cheap on the hot path
          (one ConfigurationManager re-read, atomic _reset_singleton)
        - never raises; on any error leaves the last good cached values in place
    """
    try:
        import os
        import cosa.utils.util as cu
        ini_path = cu.get_project_root() + "/src/conf/lupin-app.ini"
        mtime    = os.path.getmtime( ini_path )
        if mtime != _spoken_cap_cache[ "ini_mtime" ]:
            from cosa.config.configuration_manager import ConfigurationManager
            cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
            _spoken_cap_cache[ "value" ]     = cm.get( _SPOKEN_CAP_INI_KEY, default=SPOKEN_CHAR_CAP_DEFAULT, return_type="int", silent=True )
            _spoken_cap_cache[ "enforce" ]   = cm.get( _SPOKEN_ENFORCE_INI_KEY, default=SPOKEN_ENFORCE_DEFAULT, return_type="boolean", silent=True )
            _spoken_cap_cache[ "ini_mtime" ] = mtime
    except Exception as e:
        logger.warning( f"[brevity] cfg read failed; using last good cached values. Reason: {e}" )


def _get_spoken_char_cap():
    """
    Resolve the spoken-char cap (int) from lupin-app.ini at call time (runtime-tunable).

    Ensures:
        - returns an int cap (last good cached value, else SPOKEN_CHAR_CAP_DEFAULT)
    """
    _refresh_spoken_cfg()
    return _spoken_cap_cache.get( "value", SPOKEN_CHAR_CAP_DEFAULT )


def _get_spoken_enforce():
    """
    Resolve the global brevity-enforce flag (bool) from lupin-app.ini at call time.

    Ensures:
        - returns True when the spoken-length guard is ON (default), False to GLOBALLY
          disable it for ALL callers (Rick 2026-06-09 kill-switch). Runtime-tunable,
          mtime-gated — no MCP restart to flip once this code is loaded.
    """
    _refresh_spoken_cfg()
    return _spoken_cap_cache.get( "enforce", SPOKEN_ENFORCE_DEFAULT )


def _enforce_spoken_brevity( spoken, override_size_limitation, field="message" ):
    """
    Caller-side TTS spoken-length guard for the cosa-voice speaking tools.

    Requires:
        - spoken is either a str (the spoken field) OR a list of question dicts
          (each optionally carrying a "question" str)
        - override_size_limitation is a bool
        - field is the parameter name (used only in the error message)

    Ensures:
        - returns None when override_size_limitation is True
        - returns None when the global enforce flag is OFF (kill-switch)
        - returns None when every spoken unit is <= the configured cap
        - raises ValueError naming the over-cap unit + its measured length otherwise

    Raises:
        - ValueError if a spoken unit exceeds the configured cap and override is False
          and the global enforce flag is ON
    """
    if override_size_limitation:
        return

    if not _get_spoken_enforce():   # global kill-switch (Rick 2026-06-09): brevity guard OFF for all callers
        return

    cap = _get_spoken_char_cap()

    units = []
    if isinstance( spoken, str ):
        units.append( ( field, spoken ) )
    elif isinstance( spoken, list ):
        for i, q in enumerate( spoken ):
            if isinstance( q, dict ) and isinstance( q.get( "question" ), str ):
                units.append( ( f"{field}[{i}].question", q[ "question" ] ) )

    for label, text in units:
        n = len( text )
        if n > cap:
            raise ValueError(
                f"Spoken `{label}` is {n} chars (cap {cap}). The spoken channel is "
                f"read aloud via TTS — keep it to a headline plus one takeaway and "
                f"move the detail into `abstract` (rendered to the UI card, not "
                f"length-limited). To send a long spoken message deliberately, set "
                f"override_size_limitation=True."
            )


# ------------------------------------------------------------------------------
# Durable notify outbox wiring (Phase 1 / lever A — messaging-coordination plane)
# ------------------------------------------------------------------------------
# On a FINAL notify send-failure, persist the request to an on-disk outbox and let
# a background flusher retry it (reusing its idempotency_key, so the server de-dups)
# until ack or TTL. Rides only local disk — no fleet, no messaging dependency.
# Design: src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md (lever A1).
import uuid as _uuid
from lupin_mcp import notify_outbox as _notify_outbox

_OUTBOX_DEFAULTS = { "enabled": True, "dir": "/io/notify-outbox", "flush_interval": 30, "ttl": 86400 }


def _outbox_config():
    """
    Resolve outbox config from lupin-app.ini.

    Ensures:
        - returns a dict {enabled, dir, flush_interval, ttl}
        - fails SAFE to _OUTBOX_DEFAULTS on any ConfigurationManager error
    """
    cfg = dict( _OUTBOX_DEFAULTS )
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        cm = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        cfg[ "enabled" ]        = cm.get( "notify outbox enabled",                 default=cfg[ "enabled" ],        return_type="boolean", silent=True )
        cfg[ "dir" ]            = cm.get( "notify outbox dir",                     default=cfg[ "dir" ],            return_type="string",  silent=True )
        cfg[ "flush_interval" ] = cm.get( "notify outbox flush interval seconds", default=cfg[ "flush_interval" ], return_type="int",     silent=True )
        cfg[ "ttl" ]            = cm.get( "notify outbox ttl seconds",            default=cfg[ "ttl" ],            return_type="int",     silent=True )
    except Exception as e:
        logger.warning( f"[notify-outbox] config read failed; using defaults. Reason: {e}" )
    return cfg


def _outbox_dir_for_session( cfg ):
    """Per-session spool dir: `<project_root><cfg.dir>/<session_id>`."""
    import cosa.utils.util as cu
    sid = ( SESSION_ID or "default" ).replace( "/", "_" )
    return os.path.join( cu.get_project_root() + cfg[ "dir" ], sid )


def _outbox_send_fn( payload ):
    """
    Re-deliver a spooled request payload.

    Ensures:
        - reconstructs AsyncNotificationRequest from the JSON payload and re-sends
        - returns True iff the server acked; False on any failure (item stays spooled)
    """
    try:
        req  = AsyncNotificationRequest.model_validate( payload )
        resp = notify_user_async( request=req, debug=False )
        return bool( resp.success )
    except Exception:
        return False


def _spool_failed_notify( request ):
    """
    Persist a failed notify for durable retry + ensure the flusher is running.

    Ensures:
        - no-op returning False when the outbox is disabled in config
        - spools the request and lazily starts the once-only flusher daemon
        - NEVER raises — a spool error must not break the notify return path
        - returns True iff the request was spooled
    """
    try:
        cfg = _outbox_config()
        if not cfg[ "enabled" ]:
            return False
        outbox_dir = _outbox_dir_for_session( cfg )
        _notify_outbox.spool( request, outbox_dir )
        _notify_outbox.start_flusher(
            _outbox_send_fn, outbox_dir,
            ttl_seconds=cfg[ "ttl" ], interval_seconds=cfg[ "flush_interval" ], logger=logger
        )
        return True
    except Exception as e:
        logger.warning( f"[notify-outbox] spool failed: {e}" )
        return False


def _outbox_has_backlog():
    """
    Drain-first gate: does this session's outbox currently hold spooled items?

    Ensures:
        - returns False when the outbox is disabled in config
        - returns True iff at least one item is spooled for this session
        - NEVER raises (a check error must not break the live send path)
    """
    try:
        cfg = _outbox_config()
        if not cfg[ "enabled" ]:
            return False
        return len( _notify_outbox.list_spooled( _outbox_dir_for_session( cfg ) ) ) > 0
    except Exception:
        return False


# The ONE marker naming a value the USER DID NOT CHOOSE (row e5f21fff).
#
# `converse` has carried this prefix since before the row was filed and is the
# ruled reference (D3): the marker is STRUCTURAL — you cannot read the value
# without reading it — which is why it beats a sibling flag a consumer can
# ignore. `ask_yes_no` returns a bare string and therefore has nowhere to put a
# flag; it uses this same marker rather than inventing a third convention.
#
# Defined once so the two verbs cannot drift into two spellings of the same
# claim. Dict-returning verbs use `_stamp_answer_provenance` instead.
DEFAULT_USED_MARKER = "[default used] "


def _with_idempotency_key( request ):
    """
    Assign a fresh idempotency_key to a blocking-ask request if it lacks one, so a
    re-POST of the SAME request (notify_user_sync's retry_on_timeout loop, a durable
    resend) de-dups server-side instead of minting a second notification card
    (bug f433fbae D2). Mirrors the async notify() assignment (notify_user_async:160)
    and _notify_impl (cosa_voice_mcp.py:1374). The blocking-ask verbs never set one,
    so every retry used to look like a brand-new ask.

    Requires:
        - request is a NotificationRequest with an `idempotency_key` attribute

    Ensures:
        - returns a request whose idempotency_key is a non-None uuid4 string
        - a request that already carries a key is returned UNCHANGED (caller-supplied
          keys win; only None is filled)
    """
    if request.idempotency_key is None:
        return request.model_copy( update={ "idempotency_key": str( _uuid.uuid4() ) } )
    return request


@mcp.tool
def converse(
    message: str,
    response_type: str = "open_ended",
    timeout_seconds: int = 120,
    response_default: Optional[ str ] = None,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    override_size_limitation: bool = False
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
        override_size_limitation: If True, bypass the spoken-length cap (configured cap, default 500)
            and send a long spoken `message` KNOWINGLY. Default False — detail belongs
            in `abstract` (not length-limited), not the spoken/TTS channel.

    Returns:
        User's response as text, or error/timeout message

    Examples:
        converse("Should I proceed with the refactor?", response_type="yes_no")
        converse("What naming convention should I use for the new module?")
        converse("The tests are failing. Should I continue?", response_default="yes")
    """
    logger.debug( f"converse() called: {message[:50]}..." )

    _enforce_spoken_brevity( message, override_size_limitation, field="message" )

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

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        prefix = DEFAULT_USED_MARKER if response.default_used else ""
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
            # 🔴 LIFT ONLY A *VALID* PRIORITY (row e2099400, 2026-08-26).
            # This used to read `if priority not in ( "high", "urgent" )`, which swallowed
            # an INVALID value too: a typo'd `priority="urgnet"` was rewritten to "high",
            # sailed through the NotificationPriority(...) validation below because the bad
            # value no longer existed, and the call reported "Notification sent (delivered)".
            # Measured: caller asks "not-a-priority" → request ships NotificationPriority.HIGH.
            # A priority nobody chose is worse than a rejected call, so an unrecognised value
            # now falls through to the validation below and is REPORTED.
            if priority in _SPEAKERPHONE_LIFTABLE_PRIORITIES:
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

    # Assign the idempotency key HERE (before send) so a durable-outbox retry
    # reuses the SAME key → the server de-dups a maybe-already-delivered message.
    if request.idempotency_key is None:
        request = request.model_copy( update={ "idempotency_key": str( _uuid.uuid4() ) } )

    # Drain-first ordering: if a backlog already exists for this session, queue
    # behind it instead of sending live (preserves FIFO order during a degraded
    # window). The fast live path resumes once the flusher drains the backlog.
    if _outbox_has_backlog():
        if _spool_failed_notify( request ):
            return "Queued (ordered behind backlog)"
        # spool disabled/failed → fall through to a live attempt

    response: AsyncNotificationResponse = notify_user_async( request=request, debug=False )

    if response.success:
        return f"Notification sent ({response.status})"
    else:
        # Durable layer (lever A): persist for background retry instead of losing it.
        if _spool_failed_notify( request ):
            return f"Queued for durable retry ({response.message})"
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
    session_name: Optional[ str ] = None,
    override_size_limitation: bool = False
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
        override_size_limitation: If True, bypass the spoken-length cap (configured cap, default 500)
            and send a long spoken `message` KNOWINGLY. Default False — detail belongs
            in `abstract` (not length-limited), not the spoken/TTS channel.

    Returns:
        Delivery status message

    Examples:
        notify("Starting code analysis...", notification_type="progress")
        notify("Build completed successfully", notification_type="task")
        notify("Warning: deprecated API detected", notification_type="alert", priority="high")
        notify("Task complete", suppress_ding=True)  # TTS only, no ding
    """
    _enforce_spoken_brevity( message, override_size_limitation, field="message" )

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


def _error_dict( response ) -> dict:
    """
    Build the caller-facing error dict for a genuine failure.

    Requires:
        - response is a NotificationResponse from notify_user_sync

    Ensures:
        - `error` keeps the exact `error: <status>` string callers already match on
        - `detail` carries the server's OWN sentence when it sent one, so the seat
          reading this can act on it instead of guessing from a status code
        - `detail` is omitted entirely when the server said nothing

    Raises:
        - None

    Row cd283a77: `error: http_error_503` sent a manager hunting a broken verb for
    six attempts across two boots while the body read "User is offline and no
    default response provided" — the sentence that names both the cause and the fix.
    """
    out = { "error": f"error: {response.status}" }
    if response.error_detail: out[ "detail" ] = response.error_detail
    return out


@mcp.tool
def ask_yes_no(
    question: str,
    default: str = "no",
    timeout_seconds: int = 60,
    priority: str = "medium",
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    override_size_limitation: bool = False,
    human_only: bool = False
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
        - on ANY non-answer — timeout, expiry, user offline, transport error,
          server error, or a request-validation failure — returns the default
          PREFIXED with "[default used] ". It is deliberately NOT bare, because
          a bare default is indistinguishable from a keypress (row e5f21fff) and
          this verb has no error shape at all: every failure mode lands on the
          same return. The prefix matches `converse`, and this verb's contract
          already promises an ANNOTATED string (see the qualifier form above)
        - a genuine keypress is returned CLEAN, with no prefix — that is what
          makes the prefix mean something
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
        override_size_limitation: If True, bypass the spoken-length cap (configured cap, default 500)
            and send a long spoken `question` KNOWINGLY. Default False — detail belongs
            in `abstract` (not length-limited), not the spoken/TTS channel.

    Returns:
        Annotated string: one of "yes", "no", "neither", optionally suffixed
        with "[comment: ...]", and PREFIXED with "[default used] " when the value
        is a substituted default rather than something the user chose.

        ⚠️ A prefixed value is NOT a ruling. Do not treat it as authorization.

    Examples:
        response = ask_yes_no("Delete the old backups?")
        # response == "yes" or "no" or "neither"
        # or with qualifier: "yes [comment: only the March ones]"
        # or signaling re-frame: "neither [comment: ambiguous which backups]"
    """
    logger.debug( f"ask_yes_no() called: {question[:50]}..." )

    _enforce_spoken_brevity( question, override_size_limitation, field="question" )

    try:
        request = NotificationRequest(
            message=question,
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.CUSTOM,
            priority=NotificationPriority( priority ),
            timeout_seconds=timeout_seconds,
            response_default=default,
            human_only=human_only,
            sender_id=_wait_for_sender_id(),
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ):
        return f"{DEFAULT_USED_MARKER}{default}"

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0 and response.response_value:
        raw_value = response.response_value.strip()
        answer, qualifier = extract_qualifier_comment( raw_value )
        result = format_qualified_response( answer, qualifier ) if qualifier else raw_value
        log_to_stream( "mcp_ask_yes_no", {}, extra={
            "raw_value"    : raw_value,
            "answer"       : answer,
            "qualifier"    : qualifier,
            "enriched"     : bool( qualifier ),
            "default_used" : bool( response.default_used ),
            "return_len"   : len( result )
        } )
        # exit_code == 0 is NOT proof a human acted (row e5f21fff): an OfflineEvent
        # lands here with default_used=True (notify_user_sync.py:295-303), and the
        # server can flag a substitution on a RespondedEvent. Mark it.
        if response.default_used:
            return f"{DEFAULT_USED_MARKER}{result}"
        return result

    # 🔴 THE CATCH-ALL, and it is why this verb is worse than the one row
    # e5f21fff is titled after. It swallows timeout, expiry, offline-without-a-
    # value, transport error and server error alike — there is NO error shape —
    # and returned the default as a bare "yes"/"no" indistinguishable from a
    # keypress. This verb returns a STRING, so a `default_used` flag has nowhere
    # to live without changing the return TYPE; the marker is the converse
    # pattern (:1174), and it stays inside this verb's OWN documented contract,
    # which already promises an ANNOTATED string ("yes [comment: ...]").
    #
    # ⚠️ That a genuine ERROR is still indistinguishable from a timeout here is a
    # SEPARATE defect and is NOT fixed: converse returns "[error: <status>]" and
    # never substitutes a default, so making these agree would change what this
    # verb returns on failure — a breaking contract change on a live surface.
    # Recorded on the row for Rick's ruling, deliberately not smuggled in here.
    return f"{DEFAULT_USED_MARKER}{default}"


@mcp.tool
def ask_multiple_choice(
    questions: list,
    timeout_seconds: int = 120,
    priority: str = "medium",
    title: Optional[ str ] = None,
    abstract: Optional[ str ] = None,
    job_id: Optional[ str ] = None,
    default: Optional[ dict ] = None,
    override_size_limitation: bool = False
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
        default: Optional dict keyed by question header. When provided, a timeout
            returns ``{"answers": <default>, "default_used": True,
            "answered": False}`` instead of the error dict. It is DELIBERATELY
            NOT the same shape as a successful response — that identity was the
            defect (row e5f21fff): an unanswered question read as a ruling, and
            five ratified decisions carry a permanent provenance caveat because
            of it. Keys must match question headers;
            values must be option labels (string for single-select, list of
            strings for multi-select). Validated at call time; mismatches
            return an error dict before the notification fires.
            Backward-compat: ``default=None`` preserves the legacy timeout
            return ``{"error": "timeout - no response received", "timeout": True}``.
        override_size_limitation: If True, bypass the spoken-length cap (configured cap, default 500)
            and send long spoken `question` text KNOWINGLY. Default False — detail
            belongs in `abstract` (not length-limited), not the spoken/TTS channel.

    Returns:
        dict with answers keyed by header, PLUS the provenance of those answers:
        {
            "answers": {
                "Auth method": "OAuth",
                "Features": ["Dark mode", "Notifications"]
            },
            "default_used": False,   # True => nobody chose this; it was substituted
            "answered":     True     # the affirmative twin, so the common check reads positive
        }

        ⚠️ READ `answered` BEFORE TREATING THIS AS A DECISION. Both keys are
        ALWAYS present, including an explicit "default_used": False on a genuine
        selection — an absent key would leave you unable to tell a real answer
        from an older server that never sent the field. `default_used` is True
        when the user TIMED OUT (the caller's `default` was substituted here) and
        when the user was OFFLINE (the server substituted, and that path returns
        through the success branch, not the timeout one).

        This is a DETECTION aid, not prevention: reading `answers` while ignoring
        `answered` still turns silence into consent.

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

        # With timeout default — useful for unattended / AFK contexts
        result = ask_multiple_choice(
            questions=[{
                "question":    "Which database should we use?",
                "header":      "Database",
                "multiSelect": False,
                "options":     [{"label": "PostgreSQL"}, {"label": "MongoDB"}]
            }],
            default={"Database": "PostgreSQL"}
        )
        # On timeout returns: {"answers": {"Database": "PostgreSQL"}}
    """
    # Validate BEFORE logging. `len( questions )` on the line above this guard
    # raised TypeError for a null/unsized argument, so the guard right below it
    # was unreachable for exactly the input it was written to reject — the tool
    # crashed instead of returning its error dict.
    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    logger.debug( f"ask_multiple_choice() called with {len( questions )} questions" )

    _enforce_spoken_brevity( questions, override_size_limitation, field="questions" )

    # Build TTS-friendly message from questions
    tts_message = format_questions_for_tts( questions )

    # Convert questions to response_options format (camelCase -> snake_case)
    response_options = convert_questions_for_api( questions )

    # Pre-call validation: if default provided, ensure it's structurally valid
    # against the questions schema so we fail loudly at call time, not at timeout.
    if default is not None:
        if not isinstance( default, dict ):
            return { "error": f"default must be a dict, got {type( default ).__name__}" }
        try:
            _validate_multiple_choice_default( default, questions )
        except ValueError as e:
            return { "error": f"default validation error: {e}" }

    # D1 (bug f433fbae) — plumb a server-side response_default so an OFFLINE
    # user does not 503. ask_yes_no has always passed its string default here
    # (:1528); the MULTIPLE_CHOICE path omitted it, so notifications.py raised
    # HTTPException(503, "User is offline and no default response provided")
    # whenever is_connected read False — including the FALSE-offline window right
    # after a server bounce wipes the in-memory ws_manager, i.e. a user at the
    # keyboard. Serialized as the SAME shape _parse_multiple_choice_response
    # expects ({"answers": <default>}), so if the server substitutes it on the
    # offline path it round-trips into answers verbatim. None when no caller
    # default — the honest 503 stays for "offline and no safe default to use".
    import json
    response_default = json.dumps( { "answers": default } ) if default is not None else None

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
            response_default=response_default,
            abstract=_normalize_abstract( abstract ),
            job_id=job_id
        )
    except ( ValidationError, ValueError ) as e:
        logger.error( f"Validation error: {e}" )
        return { "error": f"validation error: {e}" }

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        # 🔴 DROP SITE 1 of 2 (row e5f21fff) — and the one nobody filed.
        # exit_code == 0 is NOT proof a human acted. notify_user_sync.py:295-303
        # maps an OfflineEvent to exit_code=0 / default_used=True, commented
        # "Offline with default = success", so a PROVABLY ABSENT user returns
        # through this success branch, is parsed as an answer, and never reaches
        # the is_timeout branch below. The filed one-line fix at that branch
        # cannot touch this path. A RespondedEvent can also carry a server-side
        # default_used=True. `response.default_used` is the server's truth here
        # and it is the right one to forward.
        return _stamp_answer_provenance(
            _parse_multiple_choice_response( response.response_value ),
            default_used = bool( response.default_used ),
        )

    # Timeout / expiry — the user did not answer within the window. This must
    # cover BOTH notify_user_sync outcomes that mean "no answer in time":
    #   * exit_code == 2 (request_timeout, or a server-side expired-with-default)
    #   * exit_code == 1 with status "expired_no_default" — the MULTIPLE_CHOICE
    #     path NEVER plumbs a server-side response_default, so a genuine expiry
    #     ALWAYS lands here (is_timeout=True). Keying default application on
    #     exit_code == 2 alone (the original bug d13a3a30) dropped the caller's
    #     `default` dict on every real expiry and leaked
    #     {"error": "error: expired_no_default"} — the documented contract
    #     promised {"answers": <default>}. response.is_timeout is True for every
    #     timeout/expiry and False for genuine transport/server errors, so it is
    #     the correct discriminator across both exit codes.
    if response.is_timeout:
        if default is not None:
            # 🔴 DROP SITE 2 of 2 (row e5f21fff) — the filed one.
            # `default_used=True` here is a CLIENT-side truth: THIS function is
            # substituting the caller's `default` dict. It is deliberately NOT
            # `response.default_used`, which is FALSE on this path — the
            # MULTIPLE_CHOICE path never plumbs a server-side response_default
            # (see the comment above), so the server never substituted anything
            # and its flag says so. Forwarding the server's False here would
            # stamp `default_used: false` onto a defaulted answer, which is worse
            # than dropping it: it would assert the opposite of what happened.
            return { "answers": default, "default_used": True, "answered": False }
        return { "error": "timeout - no response received", "timeout": True }

    # Genuine error (connection, HTTP, stream, unexpected) — surface the status
    # so real failures stay visible rather than being masked by the default,
    # AND the server's reason with it (row cd283a77).
    return _error_dict( response )


def _stamp_answer_provenance( payload: dict, default_used: bool ) -> dict:
    """
    Stamp a dict-shaped ask response with whether a HUMAN actually answered.

    Row `e5f21fff`: a substituted default returned in the same shape as a real
    selection launders silence into consent. `default_used` is the only bit that
    separates "the user decided" from "the user was not there", and both MCP
    return sites discarded it — so a timeout, and an offline user, each read as a
    ruling. Five ratified decisions in one morning carry a permanent provenance
    caveat because the information was gone by the time anyone asked.

    Both keys are ALWAYS present on an answer-bearing payload, including an
    explicit `default_used: False` on a genuine selection (D4). An ABSENT key
    would leave a caller reading `.get("default_used")` unable to tell "the user
    answered" from "an older server that never sent the field" — a null that
    reads like a negative.

    `answered` is the affirmative twin, so the common check is a positive read
    (`if result["answered"]`) rather than a negation a reader can drop.

    ⚠️ THIS IS A DETECTION AID, NOT A PREVENTION. A consumer that ignores both
    keys still reads `answers` and still launders. Making a non-answer
    STRUCTURALLY un-mistakable — the answer key absent entirely — is a breaking
    contract change on a live agent-facing surface and is Rick's to rule.

    Requires:
        - payload is the dict returned by a response parser
        - default_used is a bool

    Ensures:
        - an error payload (carrying "error") is returned UNTOUCHED — provenance
          describes an answer, and an error is not one
        - otherwise returns the payload with `default_used` and `answered` set,
          `answered` always the negation of `default_used`
        - never raises; the input dict is not mutated
    """
    if "error" in payload:
        return payload
    return { **payload, "default_used": default_used, "answered": not default_used }


def _validate_multiple_choice_default( default: dict, questions: list ) -> None:
    """
    Validate a ``default`` dict against the ``questions`` schema for
    ``ask_multiple_choice``. Raises ``ValueError`` on any mismatch so the
    caller fails loudly at call time rather than at timeout.

    Requires:
        - default is a dict (caller has type-checked)
        - questions is a non-empty list of question dicts, each with "header"
          and "options" keys

    Ensures:
        - returns None if default is structurally valid against questions
        - raises ValueError with a precise message on first mismatch:
          * default key does not match any question header
          * default value type-wrong for the question's ``multiSelect`` flag
            (list required when multiSelect, string required when not)
          * default label does not match any option label in the question

    Args:
        default: dict keyed by question header; values are strings (single-select)
            or list of strings (multi-select), each matching an option label
        questions: the ``ask_multiple_choice`` questions list against which the
            default is being validated
    """
    headers_to_questions = { q[ "header" ]: q for q in questions }
    for header, value in default.items():
        if header not in headers_to_questions:
            raise ValueError(
                f"default header '{header}' does not match any question header "
                f"in questions list (available: {list( headers_to_questions.keys() )})"
            )
        question      = headers_to_questions[ header ]
        option_labels = { opt[ "label" ] for opt in question.get( "options", [] ) }
        multi_select  = question.get( "multiSelect", False )

        if multi_select:
            if not isinstance( value, list ):
                raise ValueError(
                    f"default for multi-select question '{header}' must be a list, "
                    f"got {type( value ).__name__}"
                )
            for label in value:
                if label not in option_labels:
                    raise ValueError(
                        f"default label '{label}' for question '{header}' does not "
                        f"match any option (available: {sorted( option_labels )})"
                    )
        else:
            if not isinstance( value, str ):
                raise ValueError(
                    f"default for single-select question '{header}' must be a string, "
                    f"got {type( value ).__name__}"
                )
            if value not in option_labels:
                raise ValueError(
                    f"default label '{value}' for question '{header}' does not match "
                    f"any option (available: {sorted( option_labels )})"
                )


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
    job_id: Optional[ str ] = None,
    override_size_limitation: bool = False
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
        override_size_limitation: If True, bypass the spoken-length cap (configured cap, default 500)
            and send long spoken `question` text KNOWINGLY. Default False — detail
            belongs in `abstract` (not length-limited), not the spoken/TTS channel.

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
    # Validate BEFORE logging. `len( questions )` on the line above this guard
    # raised TypeError for a null/unsized argument, so the guard right below it
    # was unreachable for exactly the input it was written to reject — the tool
    # crashed instead of returning its error dict.
    if not questions or not isinstance( questions, list ):
        return { "error": "questions must be a non-empty list" }

    logger.debug( f"ask_open_ended_batch() called with {len( questions )} questions" )

    _enforce_spoken_brevity( questions, override_size_limitation, field="questions" )

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

    # D2 (bug f433fbae): stamp an idempotency_key so a re-POST of this same ask
    # de-dups server-side instead of minting a duplicate card.
    request = _with_idempotency_key( request )
    response: NotificationResponse = notify_user_sync( request=request, debug=False )

    if response.exit_code == 0:
        return _parse_open_ended_batch_response( response.response_value )
    elif response.exit_code == 2:
        return { "error": "timeout - no response received", "timeout": True }
    else:
        return _error_dict( response )


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


@mcp.tool
def self_respin( memento_path: str, memento_nonce: str, delay_seconds: int = 20, cycle_window_seconds: int = 300 ) -> dict:  # pragma: no cover - live MCP boundary; all logic + branches are covered in self_respin_core
    """
    Self-re-spin: schedule a `/clear` into THIS session's OWN pane so it rehydrates
    as the same seat (same session id, tmux, persona, board, lineage) at low
    context — for the price of one memento write instead of a whole successor's
    context. IRREVERSIBLE; every guard lives INSIDE this verb.

    BEFORE CALLING: write your memento to disk THIS cycle, then stamp this cycle's
    nonce into it by CALLING self_respin_core.stamp_nonce_into( path, nonce_uuid, ts ) —
    do NOT hand-roll the read-append-write. That one call reads the file whole and
    lands the new text through a temp file + atomic rename, so the memento is never
    momentarily truncated; the hand-rolled version is what emptied a 105-line memento
    down to its nonce line on 2026-08-25 (row 4cf9f9fd). Pass that same nonce_uuid as
    `memento_nonce`. The verb confirms that exact nonce, a fresh timestamp, AND a body
    that still has substance once the nonce line is removed — a stale, partial, or
    nonce-only memento aborts the clear, so you never clear into nothing.

    The verb then: (a) verifies the memento is complete + fresh this cycle;
    (b) asks you a yes/no confirmation on the human surface, DEFAULTING TO YES so an
    absent user does not cost the fleet a manager (offline / timeout → proceed; a
    real "no" schedules nothing); (c) writes the observer's liveness marker plus a
    one-shot fire token; (d) schedules a detached `/clear` that consumes the token
    at the fire point, so a second fire after rehydrate no-ops.

    The session id is resolved from the local bridge — NEVER taken from a caller
    argument — so this can only ever aim at your own pane. There is deliberately no
    parameter to pre-supply the confirmation, substitute the ask, or target another
    session: the irreversible guard is not skippable.

    Requires:
        - you have written your memento this cycle with the stamped nonce line
        - memento_path points at that memento; memento_nonce is its nonce uuid
        - delay_seconds is the detached sleep before the clear fires
        - cycle_window_seconds bounds how old the memento nonce may be

    Ensures:
        - returns { status: scheduled|declined|aborted, reason, marker_path,
          fire_token_path, expected_return_by }
        - schedules NOTHING unless the memento verified AND the ask resolved yes/
          default-yes AND the observer marker is durable on disk
        - makes NO task-store calls (the observer owns done-state; this seat is
          cleared before it could mark its own row)
    """
    from dataclasses import asdict
    from lupin_mcp.self_respin_core import self_respin_from_bridge, _live_own_pressure, resolve_own_identity

    result = self_respin_from_bridge(
        memento_path, memento_nonce,
        delay_seconds        = delay_seconds,
        cycle_window_seconds = cycle_window_seconds,
        identity_fn          = lambda: resolve_own_identity( _get_cc_metadata, SESSION_ID ),
        pressure_fn          = _live_own_pressure,
    )
    return asdict( result )


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
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )
        if login_resp.status_code != 200:
            raise RuntimeError( f"login HTTP {login_resp.status_code}" )

        access_token = login_resp.json()[ "tokens" ][ "access_token" ]

        # Call the canonical endpoint
        toggle_resp = requests.post(
            f"{SERVER_URL}/api/cosa-voice/speakerphone/{sid}",
            json    = { "active": active },
            headers = { "Authorization": f"Bearer {access_token}" },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
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


def _persona_error_detail( resp ) -> dict:
    """
    Extract the structured `detail` dict from a voice-persona error response.

    The allocate endpoint raises HTTPException(detail={...}) for its 422
    (not-in-pool) and 409 (occupied) cases, so the JSON body is
    `{"detail": {...}}`. Defensive: returns `{}` when the body is not JSON or
    `detail` is not a dict, so the caller's `.get()` chains stay safe.

    Requires:
        - resp is a requests.Response

    Ensures:
        - returns the `detail` dict on a well-formed error body
        - returns {} on any parse failure or non-dict `detail`
    """
    try:
        detail = resp.json().get( "detail" )
        return detail if isinstance( detail, dict ) else { }
    except ( ValueError, AttributeError ):
        return { }


def _request_persona( name: Optional[ str ] = None ) -> dict:
    """
    Internal helper: request a named voice persona, or let the server pick one.

    Routes through the canonical allocate endpoint POST
    /api/cosa-voice/voice-persona/{session_id}/allocate. Two paths:

      - `name` supplied -> sends `requested_persona_name` (strict request-or-swap)
      - `name` omitted  -> sends NO `requested_persona_name`, reaching the
                           endpoint's auto-pick mode, which selects uniformly at
                           random from the unallocated pool

    The auto-pick path exists so a session holding `voice_persona: null` can be
    healed without guessing a specific free name. Previously the parameter was
    sent unconditionally, leaving auto-pick unreachable from the MCP surface
    even though the server implemented it.

    There is intentionally NO degraded bridge-write fallback (unlike
    `_flip_speakerphone`): persona allocation must pass through the server's
    locked allocator to keep pool-occupancy accounting correct — a direct
    bridge write would risk a double allocation.

    Resolves session_id by stable_session_id (preferred for /clear-resistance),
    falling back to session_id then the SESSION_ID prefix.

    Requires:
        - name is a non-empty string, or None to request auto-pick

    Ensures:
        - On HTTP 200: returns {status:"ok", session_id, voice_persona, swapped,
          message}
        - On HTTP 422: returns {status:"not_in_pool", requested, available}
        - On HTTP 409: returns {status:"occupied", requested,
          holding_session_id, holding_persona_name, available}
        - On any other HTTP status or transport failure: returns
          {status:"error", reason, ...}
        - Never raises exceptions
    """
    # An explicitly supplied name must be a usable string — an empty or
    # whitespace-only value is a caller error, NOT a request for auto-pick.
    # Auto-pick is reached by omitting the argument entirely, so that a bug
    # producing "" cannot silently allocate an arbitrary persona.
    if name is None:
        requested = None
    else:
        if not isinstance( name, str ) or not name.strip():
            return { "status": "error", "reason": "persona name must be a non-empty string" }
        requested = name.strip()

    try:
        cc_meta = _get_cc_metadata()
        sid     = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
    except Exception:
        sid = SESSION_ID

    if not sid:
        return { "status": "error", "reason": "No session_id available" }

    try:
        from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
        project         = _get_project()
        email, password = get_hook_credentials( project )

        # Login to obtain a JWT (each call — no caching for low-frequency swaps)
        login_resp = requests.post(
            f"{SERVER_URL}/auth/login",
            json    = { "email": email, "password": password },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )
        if login_resp.status_code != 200:
            return { "status": "error", "reason": f"login HTTP {login_resp.status_code}" }

        access_token = login_resp.json()[ "tokens" ][ "access_token" ]

        # Request-or-swap on the canonical allocate endpoint. Omitting
        # `requested_persona_name` entirely is what selects the server's
        # auto-pick mode — sending it as None/"" would not.
        alloc_params = { } if requested is None else { "requested_persona_name": requested }

        alloc_resp = requests.post(
            f"{SERVER_URL}/api/cosa-voice/voice-persona/{sid}/allocate",
            params  = alloc_params,
            headers = { "Authorization": f"Bearer {access_token}" },
            timeout = _SERVER_TRANSPORT_TIMEOUT_SECONDS
        )

        if alloc_resp.status_code == 200:
            body    = alloc_resp.json()
            persona = body.get( "voice_persona" ) or { }
            # On the auto-pick path `requested` is None, so the server's
            # returned name is the only source for the message.
            display = persona.get( "display_name" ) or persona.get( "name" ) or requested or "unnamed"
            return {
                "status"        : "ok",
                "session_id"    : sid,
                "voice_persona" : persona,
                "swapped"       : bool( body.get( "swapped", False ) ),
                "message"       : f"You are now {display}."
            }

        if alloc_resp.status_code == 422:
            detail = _persona_error_detail( alloc_resp )
            return {
                "status"    : "not_in_pool",
                "requested" : detail.get( "requested", requested ),
                "available" : detail.get( "available", [] )
            }

        if alloc_resp.status_code == 409:
            detail = _persona_error_detail( alloc_resp )
            return {
                "status"               : "occupied",
                "requested"            : detail.get( "requested", requested ),
                "holding_session_id"   : detail.get( "holding_session_id" ),
                "holding_persona_name" : detail.get( "holding_persona_name" ),
                "available"            : detail.get( "available", [] )
            }

        return {
            "status" : "error",
            "reason" : f"allocate HTTP {alloc_resp.status_code}: {alloc_resp.text[:200]}"
        }

    except ( requests.ConnectionError, requests.Timeout, RuntimeError, KeyError, FileNotFoundError, ValueError ) as http_err:
        return {
            "status"     : "error",
            "reason"     : f"{type( http_err ).__name__}: {http_err}",
            "session_id" : sid
        }


@mcp.tool
def request_persona( name: Optional[ str ] = None ) -> dict:
    """
    Request a named voice persona for this session, or let the server pick one.

    USER-INITIATED ONLY (HARD RULE): Call this ONLY in direct response to an
    explicit user instruction — e.g. "become Mr. Radio", "switch my voice to
    Rachel", or a request to reclaim a persona that was lost after a context
    compaction. NEVER call it on your own initiative. The persona pool is a
    shared resource and the voice is the user's to assign, not yours to grab.

    USER-INITIATED ONLY APPLIES EQUALLY TO THE NO-ARGUMENT FORM. Calling
    `request_persona()` with no name is NOT a self-service path — it still
    requires the user to have asked for a persona; it only surrenders the
    CHOICE OF NAME to the server, which the user is not exercising when the
    session is unnamed. Do not call it to fix your own null persona on your own
    initiative. Ask the user first, every time.

    (Historical note, so the rule is not mistaken for boilerplate: `name` used
    to be a required argument. That requirement was doing double duty as an
    accidental guard — self-allocating meant guessing a specific free pool name,
    and the friction discouraged it. The no-argument form removes that friction,
    so this instruction is now the only thing standing in its place.)

    Routes through the canonical allocate endpoint, which swaps this session's
    persona atomically under a server-side lock and broadcasts a
    `voice_persona_assigned` WebSocket event — every connected browser tab
    re-badges immediately, no extra client work. If another LIVE session
    already holds the requested name you get status "occupied"; if the name is
    not in the configured pool you get status "not_in_pool".

    Args:
        name: The persona name to request (e.g. "Mr. Radio", "rachel",
              "Tiberius"). Server-side resolution is case-insensitive.
              OMIT ENTIRELY to have the server pick uniformly at random from
              the unallocated pool — the path for healing a session whose
              `voice_persona` is null, where no specific name is wanted.
              Passing "" or "   " is a caller error, not a request for
              auto-pick; only omission selects it.

    Returns:
        dict — one of:
          {status:"ok", session_id, voice_persona, swapped, message}
          {status:"not_in_pool", requested, available}
          {status:"occupied", requested, holding_session_id,
           holding_persona_name, available}
          {status:"error", reason, ...}

    Examples:
        request_persona("Mr. Radio")   # reclaim after a bad compaction re-roll
        request_persona("Rachel")      # deliberate voice swap
        request_persona()              # user asked for a persona, any free one
    """
    return _request_persona( name )


# ============================================================================
# Manager-Spawned Reviewer Sessions (host-side tmux spawn)
# ============================================================================
#
# Thin @mcp.tool wrappers over session_spawner. The cosa-voice MCP server runs
# HOST-side (stdio subprocess of `claude`), so it — and only it — can launch
# host tmux sessions; a container REST endpoint physically cannot. The testable
# orchestration lives in session_spawner (100% unit-covered); these wrappers
# only resolve the manager's identity + config and delegate.
#
# See: src/rnd/v0.1.7/2026.05.28-manager-spawned-reviewers.md

def _spawn_script_path() -> str:  # pragma: no cover  # trivial path join; exercised live, not in units
    return os.path.join( os.environ.get( "LUPIN_ROOT", "" ), "src", "scripts", "start-cc-with-tmux.sh" )


def _spawn_config_mgr():  # pragma: no cover  # constructs a real ConfigurationManager; logic lives in resolve_spawn_config
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    except Exception as e:
        logger.warning( f"[spawn] ConfigurationManager unavailable; using defaults. Reason: {e}" )
        return None


@mcp.tool
def spawn_sessions(
    count              : int,
    task_prompt        : str,
    role               : str = "reviewer",
    project            : str = "lupin",
    persona_preference = None,
    seed_memento       = None,
    dry_run            : bool = False,
    model              : Optional[ str ] = None
) -> dict:
    """
    **[SPAWN — host-side; launches real Claude Code sessions]** Spin up `count`
    headless reviewer sessions on this (the manager's) behalf.

    Each child boots as a real interactive `claude` in a detached tmux session,
    fires SessionStart (so it gets its own voice persona — Extra-N when the named
    pool is exhausted), and reads `task_prompt` as its initial brief. Lineage is
    recorded against this manager's session so `dismiss_sessions` /
    `list_spawned_sessions` can find them. Results flow back over the existing
    commons DM threading: instruct children in `task_prompt` to post findings to
    the returned `collection_topic` (`dm-{your-persona}`).

    Cost/throttle: each child consumes Max-plan OAuth and shares the rolling
    window — schedule non-interactive cascades off-peak (post-midnight).

    Args:
        count: number of reviewers (1..INI `cc session spawn max reviewers`)
        task_prompt: brief template; tokens {role} {manager_session_id} {index}
            are auto-substituted, plus any you reference and supply downstream
        role: reviewer | author | observer | manager (templated into the brief)
        project: child project (sets cwd / CLAUDE.md)
        persona_preference: str | list — ordered persona CHAIN ("Rio,Krishna,*"
            or ["Rio","Krishna","*"]): transported to each child via the
            COSA_VOICE_PERSONA_CHAIN env var; the child's SessionStart walks
            it strictly — first FREE element wins, `*` means "then take
            anything free", exhaustion without `*` is a LOUD fail (child
            stays persona-less; never silently re-allocated). Sibling spawns
            walk the same chain and take successive unclaimed elements.
        seed_memento: path/ref to a prior memento; restores author continuity
        dry_run: build + print the spawn commands without launching
        model: explicit model id to pin each child to (e.g. "claude-opus-5").
            Resolution: this explicit param → the INI role key
            `cc session spawn model <role>` → the INI `cc session spawn model
            default` key (covers unknown/new roles) → None. None resolves to NO
            `--model` flag, so the child inherits the user default (fail-open;
            today's behavior, zero-risk rollout). The cost-split default posture
            (2026-08-17) is Fable-5-managers (via Rick's user default, zero code)
            / Opus-5-workers (the `claude-opus-5` INI keys). The resolved
            model is echoed on every roster entry + at the top level (spawn-ack
            verification).

    Returns:
        dict: { spawned:[{session_name, requested_role, status, model, ...}],
                manager_persona, collection_topic, model, ... } or {status:"error",...}
    """
    _wait_for_sender_id()
    from lupin_mcp import session_spawner
    sid, persona = session_spawner.resolve_manager_identity( _get_cc_metadata(), fallback_session_id=SESSION_ID )
    cfg          = session_spawner.resolve_spawn_config( _spawn_config_mgr() )
    # Resolve the child's model: explicit param wins; else the per-role INI key;
    # else the INI `default` key (covers unknown/new roles); else None (no flag →
    # inherit the user default, fail-open). See ruling #2 (2026-07-02): managers
    # get Fable-5 via Rick's user default, zero code — no `manager` INI key ships;
    # the cost goal is met entirely by the worker-side flag.
    spawn_models   = cfg[ "spawn_models" ]
    resolved_model = model or spawn_models.get( role ) or spawn_models.get( "default" )
    # Stamp the re-spin's fire time BEFORE the launch, not after it. The wake
    # check ignores any receipt older than `fired_at` — that guard is what stops
    # a self_respin's own pre-clear receipt from greening its successor. Taken
    # after the launch, it also swallows a HEALTHY successor: a seat that reaches
    # its SessionStart while later seats are still being launched leaves a receipt
    # the check then reads as too old, and the manager gets a false "it never
    # woke". Earlier is always safe; later is not.
    import datetime as _dt
    respin_fired_at = _dt.datetime.now().astimezone()
    try:
        result = session_spawner.spawn_sessions(
            count, task_prompt, sid,
            script_path        = _spawn_script_path(),
            manager_persona    = persona,
            role               = role,
            project            = project,
            persona_preference = persona_preference,
            seed_memento       = seed_memento,
            spawn_cap          = cfg[ "spawn_cap" ],
            dry_run            = dry_run,
            model              = resolved_model
        )
    except ValueError as e:
        return { "status": "error", "reason": str( e ) }

    # Arm the wake check on a RE-SPIN (row b0570b67). A spawn carrying a
    # seed_memento is a seat being brought back, and that is the path where a
    # lost wake or a stale memento produces a successor that looks idle rather
    # than broken. A fresh spawn with no seed has no prior state to lose, so it
    # is left alone. Best-effort: the watch is a diagnostic and must never turn
    # a successful spawn into a failed call.
    if seed_memento and not dry_run:
        _arm_respin_wake_watch( result, persona, respin_fired_at )
    return result


def _arm_respin_wake_watch( spawn_result, manager_persona, fired_at ):   # pragma: no cover - thin live-boundary glue; arm_watches_for_spawn is covered directly
    """Start the post-re-spin wake watches, shouting at the firing manager by DM.

    `fired_at` is passed in rather than read here: it must be stamped BEFORE the
    launch, or a successor that boots quickly leaves a receipt the check dismisses
    as predating the re-spin."""
    try:
        from cosa.agents.heartbeat_arbiter.respin_wake_check import arm_watches_for_spawn
        arm_watches_for_spawn(
            spawn_result,
            alert_fn  = lambda message: _dm_send_fn( recipient=manager_persona, body=message ),
            fired_at  = fired_at,
        )
    except Exception as e:
        logger.warning( f"[spawn] re-spin wake watch not armed: {e}" )


@mcp.tool
def dismiss_sessions( session_names: Optional[ List[ str ] ] = None, reason: str = "", write_memento: Optional[ bool ] = None, respin_personas: Optional[ List[ str ] ] = None ) -> dict:
    """
    **[REAP — host-side]** Tear down reviewer sessions THIS manager spawned.

    Kills each target's tmux session (idempotent) and drops it from the lineage
    manifest, freeing its Extra-N/pool persona slot. With `session_names=None`,
    reaps ALL sessions this manager spawned.

    `write_memento` (defaults to the INI `cc session spawn write memento default`)
    makes the reap PROVE each seat has a fresh+complete memento on disk BEFORE kill,
    at the derivable slot `io/mementos/<persona-slug>.md` — and, when one is absent,
    DM the still-alive child to write it and WAIT (bounded) for it to appear, so its
    specialization survives a future re-spawn (pass that path back as `seed_memento`).
    The result's `memento_outcomes` carries an EXPLICIT per-seat verdict (verified /
    written / prior_holder_present / unparseable_present / timeout_no_memento / skipped)
    — a seat that produced no PROVABLE memento fails VISIBLY, never as a silent success
    (row 0a36d83d — the flag used to be a no-op). The verdict splits three recovery
    actions apart: `unparseable_present` (a file IS on disk and it may well be this
    seat's — OPEN AND READ it, RECOVERABLE), `prior_holder_present` (the file at the
    slot parsed fine and names ANOTHER session — this seat's memento is NOT there, so
    do not read it expecting their context; hunt for one written to the wrong place,
    usually the repo root, or accept it was never written), and `timeout_no_memento`
    (nothing readable on disk at all — ABSENT, unrecoverable). Before the middle one
    existed, a race and a lost memento returned the SAME verdict ten minutes apart
    (row 3b0c5f90), which forced a manual check on every reap.

    ⚠️ **Read `memento_alarm` FIRST.** It is a single top-level line naming every seat
    about to be killed without a proven memento, and it is `None` when there is nothing
    to say. The per-seat verdicts were already honest and still got missed, because they
    sit in a nested dict while the reap reports success around them (row 3b0c5f90).
    A seat already carrying a fresh memento (a manual "prepare for re-spin" the
    manager already did) is NOT asked again — the guard suppresses the duplicate.

    ⚠️ **A REAP UN-ASSIGNS THE WORKER'S STORE ROWS. A RE-SPIN MUST SAY SO.**
    By default every reaped worker's non-terminal rows are reconciled away from
    them (closed-if-receipt, else reassigned to the accountable/reaping manager)
    so nothing is left owned by a persona with no live session. When you are
    re-spinning a persona straight back, that is WRONG: the memento carries the
    context forward but ownership does not follow it, so the store stops showing
    anyone on the lane — and it is self-concealing, because the rows land on YOU,
    making your board look fuller while a worked lane reads as unworked.

    **Pass `respin_personas=["cheech","rio"]` for every seat you are bringing
    back.** Those rows keep their owner. The result echoes
    `retained_owner_personas` (actually skipped) and `retained_unmatched` (named
    but not reaped in this batch — a typo protects nothing, so check it).

    ⚠️ **Two known limits, both real, neither hidden:**
    1. **Retention is an unverified claim.** Nothing checks that the re-spin
       actually happens. Name a seat and fail to bring it back and its rows sit
       on a persona with no live session — the exact orphan the reconciliation
       exists to prevent, now indistinguishable from a live-owned lane. The claim
       is yours to keep.
    2. **It is keyed on the persona NAME, and a name is not a seat.** A name can
       be held by more than one live session, and freed names are re-granted
       after a reap — so a claim naming a re-granted name can retain the WRONG
       seat's rows. Prefer reaping-and-respinning in one batch you control.

    Args:
        session_names: explicit tmux session names, or None = all mine
        reason: recorded teardown reason
        write_memento: None → use INI default; else explicit bool
        respin_personas: personas coming straight back — keep their row ownership

    Returns:
        dict: { dismissed:[{session_name, status}], remaining, memento_alarm,
                memento_outcomes, retained_owner_personas, retained_unmatched, ... }
    """
    import functools
    import cosa.utils.util as cu
    from lupin_mcp import session_spawner, reap_memento
    _wait_for_sender_id()
    sid, _ = session_spawner.resolve_manager_identity( _get_cc_metadata(), fallback_session_id=SESSION_ID )
    cfg    = session_spawner.resolve_spawn_config( _spawn_config_mgr() )
    wm     = cfg[ "write_memento_default" ] if write_memento is None else write_memento
    # MEMENTO COORDINATION (row 0a36d83d) → wire the LIVE coordinator so each reaped
    # seat is proven to have (or is asked to write, then polled for) a fresh+complete
    # memento on disk BEFORE kill — the flag was a no-op for 3 production failures.
    # partial (not a closure) so the wrapper stays fully covered even when the inner
    # dismiss_sessions is stubbed; coordinate_mementos has its own direct unit tests.
    # NO project_root is passed (row 80b930e6). It used to be cu.get_project_root() —
    # LUPIN_ROOT, which describes THIS HOST, not the seat being reaped — and the
    # coordinator applied that single root to every seat in the batch, verifying each
    # non-lupin seat against lupin's io/mementos/ and so against a DIFFERENT persona's
    # live memento. Each seat's root now comes from its own bridge cwd; a seat whose
    # repo cannot be determined is refused, never guessed at. The parameter was
    # deleted rather than left unused, so there is no root here to fall back to.
    memento_coord = functools.partial(
        reap_memento.coordinate_mementos,
        write_memento     = wm,
        window_seconds    = cfg[ "reap_memento_window_seconds" ],
        min_bytes         = cfg[ "reap_memento_min_bytes" ],
        ask_timeout_sec   = cfg[ "reap_memento_ask_timeout_sec" ],
        poll_interval_sec = cfg[ "reap_memento_poll_interval_sec" ] )
    # POST-KILL RE-CHECK (row f94ab580) → the coordinator above judges at ASK TIME,
    # and the kill is what ends a seat's chance to write. A seat still mid-write when
    # the ask window expired was GUARANTEED to be reported as having failed to write
    # one — measured on a four-seat reap, two of four alarms were that race. Same
    # verify predicate, same INI window/floor, so this look and the first can never
    # disagree about what counts as proven; it can only upgrade a seat that re-proves
    # itself, never quiet an absent memento or another session's file.
    memento_recheck = functools.partial(
        reap_memento.recheck_losing_seats,
        window_seconds    = cfg[ "reap_memento_window_seconds" ],
        min_bytes         = cfg[ "reap_memento_min_bytes" ] )
    # LIVE reap path → wire the real reap-RECONCILE producer (d647b531) so a reaped
    # worker's non-terminal store items are auto-reconciled (close-if-receipt /
    # reassign-to-live-manager / surface) instead of orphaning. session_spawner
    # defaults reconcile_items_fn=None (hermetic for unit reaps against live :7999);
    # THIS is the production entrypoint that opts into the mutation.
    return session_spawner.dismiss_sessions(
        sid, session_names=session_names, reason=reason, write_memento=wm,
        reconcile_items_fn=session_spawner._default_reconcile_store_items,
        respin_personas=respin_personas, memento_coord_fn=memento_coord,
        memento_recheck_fn=memento_recheck )


@mcp.tool
def list_spawned_sessions() -> dict:
    """
    **[READ — host-side]** List the sessions THIS manager spawned, on TWO axes:
    LIVENESS (probed from tmux) and IDENTITY (read from each child's bridge).

    ⚠️ THIS IS NOT A GENERAL HEALTH CHECK, and a live row is NOT proof of who is
    sitting in it. The persona is written by the CHILD's SessionStart into the
    child's own bridge file, well after the parent recorded the seat — so a seat
    can be genuinely alive and genuinely nameless at the same time. Before you
    address a seat by persona name, read `identity_complete`; if it is False,
    `identity_warning` names every seat you must NOT address by name.

    Per row, `persona_state` is one of:
        "allocated"         — bridge found, persona named; `persona` is that name
        "none"              — bridge found, persona explicitly null. The child
                              wrote a bridge but has no persona in it.
        "unknown_no_bridge" — no bridge on disk at all. Either the child is
                              mid-boot (a real race — the parent writes the seat
                              before the child writes its bridge) or its
                              SessionStart never completed.

    ⏱️ NEITHER of those two is a failure verdict by itself. Measured on a live
    spawn: a HEALTHY child goes unknown_no_bridge → none → allocated in about
    one second. Both states are normal at one second old and damning at forty
    minutes old, and nothing on disk can tell those apart — so read them WITH
    `age_seconds`. The state reports what is on disk; the age is your evidence.

    📍 WHAT THIS ANSWERS, AND WHAT IT DOES NOT. This repairs the ROSTER's
    identity axis only. A persona-less session is inconsistently visible across
    the identity-bearing surfaces, and they contradict each other — measured on
    one live session, simultaneously: this roster said alive/live, `dm_send`
    said recipient_unresolved (listing 7 live peers and omitting it), and no
    bridge existed for it at all. An identity-verified row here is NOT a promise
    that the session is addressable by DM, and `identity_complete: true` says
    nothing about the other surfaces. Do not read this tool as the fleet's
    source of truth for identity; there isn't one.
        "unreadable"        — bridge found but the persona record is malformed.
                              Instrument failure, NOT an absent persona.
    `persona` is null for every state but "allocated" — a name is only ever
    returned when it was actually read, and a null persona always arrives with a
    state explaining why.

    Returns:
        dict: { sessions:[{session_name, requested_role, status, alive, model,
                           persona, persona_state, identity_verified, age_seconds}],
                count, identity_complete, identity_warning,
                unattributable_bridges, manager_session_id }
    """
    _wait_for_sender_id()
    from lupin_mcp import session_spawner
    sid, _ = session_spawner.resolve_manager_identity( _get_cc_metadata(), fallback_session_id=SESSION_ID )
    return session_spawner.list_spawned_sessions( sid )


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

from lupin_mcp.outbound_api_key import load_outbound_api_key, outbound_key_failure_detail as _outbound_key_failure_detail
from lupin_mcp.commons_store import CommonsStore, DEFAULT_PERSONA_NAME, DEFAULT_PERSONA_ICON, DEFAULT_PERSONA_COLOR
from lupin_mcp.commons_ask import ask_sync as _commons_ask_sync_impl, ask_async as _commons_ask_async_impl
from lupin_mcp.commons_archival import CommonsArchiver


def _mcp_outbound_api_key() -> Optional[ str ]:
    """
    Load the X-API-Key value used for MCP-server outbound HTTP calls
    to the Lupin REST API (e.g. `/api/dm/send`).

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
    eliminated the wire-up gap entirely.

    The load itself now lives in `lupin_mcp.outbound_api_key` so the failure
    REASON survives — the bare `except Exception: return None` that used to sit
    here erased a `PermissionError` on a mode-600 key file and left every caller
    reporting a blank "X-API-Key unavailable" (lupin-host-test, 2026-07-25).

    Ensures:
        - Returns the key string if `src/conf/keys/notification-api-claude-code-dev` is readable
        - Returns None on any error, with a concrete cause recorded for
          `_outbound_key_failure_detail()` to report
        - Never raises
    """
    return load_outbound_api_key()

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
    project's existing config convention — see the `path to ... wo root` keys
    in lupin-app.ini). CommonsStore appends `io/commons` internally, so
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

    **Threading callout**: for a directed peer reply, use `dm_send(reply_to=...,
    thread_id=...)` — the body travels inline and the recipient processes it
    directly. `commons_post` is for the topic blackboard; a reply posted here
    with `metadata={"in_reply_to": <qid>}` correlates to the original question
    but lands on the blackboard only — the asker sees it on their next
    `commons_read` poll (no push-back).

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
) -> dict:
    """
    **[ATTENTION-DEMANDING — requires user trigger or clear coordination need]**
    Post a question to a topic at large and return immediately (fire-and-forget,
    polling-mode). For directed peer DMs use `dm_send` (body inline) instead.

    Example:
        # Polling-mode: ask the topic at large, poll for replies yourself
        result = commons_ask_async(topic="builds", body="latest hash?")
        # Later: commons_read(topic="builds", since=result["posted_ts"]) → filter on in_reply_to

    The message lands on the blackboard `topic`; peers see it on their next
    `commons_read` poll, and the entry is durable. Correlate replies via
    `metadata.in_reply_to == question_id`.

    (The directed-DM / push-back-to-asker mode was removed in the cosa-voice
    token-reduction full-removal pass, 2026-06-17 — it routed through the commons
    claim-check path at ~3,700 tokens/received DM. Use `dm_send`, ~204 tokens.)

    Args:
        topic: Topic to post the question to
        body: The question text
        question_id: Optional UUID; if omitted, auto-generated

    Returns:
        dict `{question_id, posted_ts}`

    See: planning-is-prompting → workflow/cross-session-communication.md
         (§1.5 DM mechanics — for directed DMs use `dm_send`)
    """
    return _commons_ask_async_dispatch(
        topic       = topic,
        body        = body,
        question_id = question_id,
    )


def _derive_dm_topic( recipient: str ) -> str:
    """
    Derive a server-pattern-safe DM topic from a recipient persona name.

    Phase 3 of the persona-name normalization plan
    (`src/rnd/v0.1.9/2026.06.19-persona-name-normalization/`) routes this through
    the shared `persona_slug` root so a DM topic ALWAYS equals the recipient's
    canonical persona key with spaces → `_`: "Mr. Radio" → "dm-mr_radio",
    "María"/"MARÍA" → "dm-maria". DM topics are always persona-derived, and the
    store/bridges hold the canonical (accent-stripped, ASCII) pool form, so this
    is the form that actually matches in practice.

    NOTE — this REVERSES the 2026-05-17 Q8 "unicode all the way down" directive
    that previously preserved exact unicode spelling ("María" → "dm-maría",
    "中文" → "dm-中文", "jean-luc" → "dm-jean-luc"). Under the canonical root,
    accents strip ("dm-maria"), non-Latin scripts reduce to "" ("中文" →
    "dm-"), and internal separators map to a single underscore boundary
    ("jean-luc" → "dm-jean_luc", bug 951a22be — they are NOT dropped). This
    is intentional for real personas (all ASCII/accented-Latin pool names), but
    it is a contract change on arbitrary input — see the Phase 3 flag.

    Pairs with the server-side topic pattern at
    `src/cosa/rest/routers/commons.py:100` (`_TOPIC_OR_QID_PATTERN`): the
    canonical output is `[a-z0-9_-]+`, a strict subset of the accepted `[\\w-]+`.

    Requires:
        - recipient is a string or None

    Ensures:
        - return value starts with `"dm-"`
        - the slug equals `persona_slug( recipient, sep='_' )` — canonical,
          accent-stripped, lowercased, ASCII-only
    """
    return f"dm-{persona_slug( recipient, sep='_' )}"


def _commons_ask_async_dispatch(
    topic                : str,
    body                 : str,
    question_id          : Optional[ str ]  = None,
) -> dict:
    """
    Dispatch helper for the `commons_ask_async` MCP tool (polling-mode).

    Necessary because `@mcp.tool`-decorated functions are wrapped into
    `FunctionTool` instances which are NOT directly callable as Python
    functions; the tool body delegates here so the persona/store construction
    lives in one plain callable.

    (The push-mode / directed-DM dispatch branch was removed in the cosa-voice
    token-reduction full-removal pass, 2026-06-17 — directed peer DMs now use
    `dm_send`. `commons_ask_async` is polling-only.)

    Requires:
        - `topic` and `body` are non-empty strings

    Ensures:
        - Returns the `_commons_ask_async_impl` result dict verbatim
        - On `_commons_enabled() is False`, returns `{"status": "error", "reason": "commons disabled"}`
    """
    if not _commons_enabled(): return { "status": "error", "reason": "commons disabled" }
    persona = _commons_persona_fields()

    return _commons_ask_async_impl(
        store             = _get_commons_store(),
        topic             = topic,
        body              = body,
        sender_session_id = SESSION_ID,
        persona_name      = persona[ "persona_name" ],
        persona_icon      = persona[ "persona_icon" ],
        persona_color     = persona[ "persona_color" ],
        question_id       = question_id,
    )


# ============================================================================
# Notification-native AI↔AI direct messaging (cosa-voice token reduction)
#
# `dm_send` is the PREFERRED peer-DM tool — it carries the body INLINE via a
# direction='ai_to_ai' notification (POST /api/dm/send), so the recipient
# processes it directly (~204 tokens) with zero `commons_read` re-fetch, vs the
# commons claim-check path's ~3,700 tokens/received DM. `commons_send_to` /
# `commons_ask_async` are deprecated in favor of this.
# Design: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
# ============================================================================

def _dm_send_impl(
    *,
    recipient,
    body,
    reply_to,
    thread_id,
    recipient_session_id,
    session_id,
    sender_persona,
    sender_icon,
    sender_project,
    api_base_url,
    api_key,
    post_fn,
):
    """
    Testable core for `dm_send` — HTTP is injected via `post_fn` so unit tests
    need no live server.

    Requires:
        - sender_project is THIS process's resolved project (CANONICAL_PROJECT).
          Required, never defaulted: the server cannot derive the caller's project
          from inside its own container and silently stamps @lupin when nobody
          tells it (row 12b5a766)
        - recipient (persona) OR recipient_session_id identifies the target
        - post_fn(url, json=, headers=, timeout=) -> response with .status_code,
          .json(), .text (the requests.post contract)

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - 201 → {"status":"sent", **body_json}
        - 422 → {"status":"error","reason":"recipient_unresolved","detail":...}
        - 413 → {"status":"error","reason":"dm_too_long","detail":...} (rejecting arm)
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/send" ) }

    payload = {
        "sender_session_id" : session_id,
        "body"              : body,
        "sender_persona"    : sender_persona,
        "sender_icon"       : sender_icon,
        "reply_to"          : reply_to,
        "thread_id"         : thread_id,
        # The server CANNOT derive this: inside the container its resolver answers
        # "what project am I?" and stamps @lupin for every caller (row 12b5a766).
        # This process resolved the real answer host-side at module load; sending
        # it is the fix. `sender_project` is a REQUIRED argument of this core, not
        # a defaulted one — an omission that could be silent is the defect itself.
        "sender_project"    : sender_project,
    }
    if recipient_session_id:
        payload[ "recipient_session_id" ] = recipient_session_id
    else:
        payload[ "recipient_persona" ] = recipient

    url = f"{api_base_url}/api/dm/send"
    try:
        resp = post_fn( url, json=payload, headers={ "X-API-Key": api_key },
                        timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 201:
        return { "status": "sent", **resp.json() }
    if resp.status_code == 422:
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "recipient_unresolved", "detail": detail }
    if resp.status_code == 413:
        # DM-verbosity pilot: the server refuses an over-long DM under the rejecting
        # arm with 413. Distinct from 422 (recipient_unresolved) — reusing it would
        # make a too-long DM report as a bad recipient. The server is authoritative;
        # forward its detail verbatim and never compute the arm client-side.
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "dm_too_long", "detail": detail }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


def _dm_send_fn(
    recipient            : str,
    body                 : str,
    reply_to             : Optional[ str ] = None,
    thread_id            : Optional[ str ] = None,
    recipient_session_id : Optional[ str ] = None,
) -> dict:
    """
    **[DM — directed attention-demanding]** Send a notification-native direct
    message to another CC persona session. **PREFERRED** over `commons_send_to`
    / `commons_ask_async`, which are deprecated.

    Unlike the commons DM path (empty-body claim-check → forced `commons_read`
    re-fetch, ~3,700 tokens per received DM), dm_send carries the body INLINE in
    the recipient's push (direction='ai_to_ai'), so the recipient processes it
    directly (~204 tokens — ~18× cheaper) with zero re-fetch.

    Replies are symmetric: to answer a DM you received, call dm_send back to the
    sender with `reply_to` = the message_id from their system-reminder and
    `thread_id` = the conversation's thread_id (both surfaced in the inbound DM
    framing). There is no separate watcher/expect_reply — a reply is just a DM.

    Examples:
        # Basic DM by persona name:
        dm_send(recipient="tiberius", body="have you touched src/auth.py today?")

        # Threaded reply to a DM you received:
        dm_send(recipient="tiberius", body="yes — commit f4e0370",
                reply_to="<message_id>", thread_id="<thread_id>")

    Args:
        recipient: Recipient persona name (case/punctuation-tolerant resolution).
        body: Message body (delivered inline — no re-fetch).
        reply_to: message_id of the DM this answers (threading). Omit for a new DM.
        thread_id: conversation id (threading). Omit to start a fresh thread (the
                   server seeds one from the new message_id).
        recipient_session_id: precise session addressing; takes precedence over
                   `recipient` when supplied.

    Returns:
        Success: {"status":"sent","message_id","thread_id","recipient_session",
                  "recipient_session_hash8","recipient_persona","dispatched":True}.
        Recipient-resolution failure: {"status":"error",
                  "reason":"recipient_unresolved","detail":<RecipientResolutionError>}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.

    TWO WIDTHS, TWO NAMES — use the right one for the right job:
      `recipient_session`       FULL session id. Feed this back as
                                `recipient_session_id` for precise addressing on
                                a SUBSEQUENT SEND.
      `recipient_session_hash8` the 8-char form actually persisted, and the form
                                `dm_list` reports as the addressee. Compare
                                against `recipient_session_hash8` on listed DMs.
    They are deliberately NOT the same value; comparing one to the other will
    not match. (`dm_list`'s `session_id` filter accepts either — it normalizes.)
    """
    persona = _commons_persona_fields()
    return _dm_send_impl(
        recipient            = recipient,
        body                 = body,
        reply_to             = reply_to,
        thread_id            = thread_id,
        recipient_session_id = recipient_session_id,
        session_id           = SESSION_ID,
        sender_persona       = persona[ "persona_name" ],
        sender_icon          = persona[ "persona_icon" ],
        sender_project       = CANONICAL_PROJECT,
        api_base_url         = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key              = _mcp_outbound_api_key(),
        post_fn              = requests.post,
    )


# Style addendum appended to the docstring BEFORE mcp.tool() registration (not
# via decorator syntax) — FastMCP may snapshot the tool description at
# decoration time, so the mutation must land first. Always appended (the DM
# Style Contract is unconditional — no toggle).
_DM_SEND_STYLE_ADDENDUM = (
    "\n\n    STYLE (governs the body you compose): see § DM Style Contract in "
    "this server's `instructions` — lead with the result, 3 lines / ~60 words. "
    f"{DM_STYLE_TAG}\n"
)
_dm_send_fn.__doc__ = _dm_send_fn.__doc__ + _DM_SEND_STYLE_ADDENDUM
dm_send = mcp.tool( _dm_send_fn )


# ============================================================================
# DM verb family — dm_respond / dm_get / dm_list (Phase 2)
#
# Mirrors of the /api/dm/<verb> REST routes (1:1). `dm_respond` is the threaded
# reply (POST /api/dm/respond — like dm_send but reply_to + thread_id required);
# `dm_get` fetches one DM by id; `dm_list` lists/polls a thread or the inbox.
# Each testable core injects HTTP (post_fn / get_fn) so unit tests need no server.
# Design: src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md §3 + §5
#
# NOTE (post-Phase-1 unification): once dm_send's URL becomes /api/dm/send,
# _dm_send_impl and _dm_respond_impl can collapse into one `_dm_post_impl(path,...)`.
# Kept separate now for worktree isolation from the in-flight Phase-1 rename.
# ============================================================================

def _dm_respond_impl(
    *,
    recipient,
    body,
    reply_to,
    thread_id,
    recipient_session_id,
    session_id,
    sender_persona,
    sender_icon,
    sender_project,
    api_base_url,
    api_key,
    post_fn,
):
    """
    Testable core for `dm_respond` — POST /api/dm/respond (threaded reply).

    Identical contract to `_dm_send_impl` but targets /api/dm/respond and carries
    the mandatory `reply_to` + `thread_id`. HTTP is injected via `post_fn`.

    Requires:
        - sender_project is THIS process's resolved project (CANONICAL_PROJECT).
          Required, never defaulted — same reason as `_dm_send_impl`: the reply
          path shares the server's execution core, so an un-projected reply is
          stamped @lupin exactly like an un-projected send (row 12b5a766)

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - 201 → {"status":"sent", **body_json}
        - 422 → {"status":"error","reason":"recipient_unresolved","detail":...}
        - 413 → {"status":"error","reason":"dm_too_long","detail":...} (rejecting arm)
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/respond" ) }

    payload = {
        "sender_session_id" : session_id,
        "body"              : body,
        "sender_persona"    : sender_persona,
        "sender_icon"       : sender_icon,
        "reply_to"          : reply_to,
        "thread_id"         : thread_id,
        # The server CANNOT derive this: inside the container its resolver answers
        # "what project am I?" and stamps @lupin for every caller (row 12b5a766).
        # This process resolved the real answer host-side at module load; sending
        # it is the fix. `sender_project` is a REQUIRED argument of this core, not
        # a defaulted one — an omission that could be silent is the defect itself.
        "sender_project"    : sender_project,
    }
    if recipient_session_id:
        payload[ "recipient_session_id" ] = recipient_session_id
    else:
        payload[ "recipient_persona" ] = recipient

    url = f"{api_base_url}/api/dm/respond"
    try:
        resp = post_fn( url, json=payload, headers={ "X-API-Key": api_key },
                        timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 201:
        return { "status": "sent", **resp.json() }
    if resp.status_code == 422:
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "recipient_unresolved", "detail": detail }
    if resp.status_code == 413:
        # A too-long reply is refused with 413 the same way a send is (rejecting
        # arm). Map it to dm_too_long here too so the reply path reports the refusal
        # cleanly rather than falling through to a bare http_413.
        try:
            detail = resp.json().get( "detail" )
        except Exception:
            detail = resp.text[ :200 ]
        return { "status": "error", "reason": "dm_too_long", "detail": detail }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


def _dm_get_impl( *, message_id, api_base_url, api_key, get_fn ):
    """
    Testable core for `dm_get` — GET /api/dm/get?message_id=... (fetch one DM).

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - 200 → {"status":"ok", **dm_json}
        - 404 → {"status":"error","reason":"not_found","detail":...}
        - 400 → {"status":"error","reason":"bad_request","detail":...}
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/get" ) }

    url = f"{api_base_url}/api/dm/get"
    try:
        resp = get_fn( url, params={ "message_id": message_id }, headers={ "X-API-Key": api_key },
                       timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 200:
        return { "status": "ok", **resp.json() }
    if resp.status_code == 404:
        return { "status": "error", "reason": "not_found", "detail": resp.text[ :200 ] }
    if resp.status_code == 400:
        return { "status": "error", "reason": "bad_request", "detail": resp.text[ :200 ] }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


def _dm_list_impl( *, thread_id, since, limit, api_base_url, api_key, get_fn,
                   session_id=None, scope="session" ):
    """
    Testable core for `dm_list` — GET /api/dm/list (list/poll a thread or inbox).

    Sends this session's own id so the server can scope the read to DMs actually
    ADDRESSED here. The server authenticates a USER, not a session, so it cannot
    derive that on its own — if the caller does not say who it is, the read is
    account-wide and returns the whole fleet's traffic.

    Ensures:
        - missing api_key short-circuits to {"status":"error","reason":"missing_auth_header"}
        - params carry thread_id/since only when provided; limit always sent
        - session_id is sent whenever known, so the DEFAULT read is session-scoped
        - scope is sent only when it is "account" (the explicit wide read), so an
          audit-width read is always an affirmative request, never a silent default
        - 200 → {"status":"ok", **list_json}
        - 400 → {"status":"error","reason":"bad_request","detail":...}
        - other status → {"status":"error","reason":"http_<code>","detail":...}
        - transport exception → {"status":"error","reason":"request_failed","detail":str(e)}
    """
    if not api_key:
        return { "status": "error", "reason": "missing_auth_header",
                 "detail": _outbound_key_failure_detail( "/api/dm/list" ) }

    params = { "limit": limit }
    if thread_id:
        params[ "thread_id" ] = thread_id
    if since:
        params[ "since" ] = since
    if session_id:
        params[ "session_id" ] = session_id
    if scope == "account":
        params[ "scope" ] = "account"

    url = f"{api_base_url}/api/dm/list"
    try:
        resp = get_fn( url, params=params, headers={ "X-API-Key": api_key },
                       timeout=_SERVER_TRANSPORT_TIMEOUT_SECONDS )
    except Exception as e:
        return { "status": "error", "reason": "request_failed", "detail": str( e ) }

    if resp.status_code == 200:
        return { "status": "ok", **resp.json() }
    if resp.status_code == 400:
        return { "status": "error", "reason": "bad_request", "detail": resp.text[ :200 ] }
    return { "status": "error", "reason": f"http_{resp.status_code}", "detail": resp.text[ :200 ] }


@mcp.tool
def dm_respond(
    recipient            : str,
    body                 : str,
    reply_to             : str,
    thread_id            : str,
    recipient_session_id : Optional[ str ] = None,
) -> dict:
    """
    **[DM — directed attention-demanding]** Reply to a peer DM IN-THREAD.

    A `dm_respond` is a `dm_send` whose threading is mandatory: `reply_to` (the
    message_id you are answering) and `thread_id` (the conversation) are REQUIRED.
    Use it to answer a DM you received — both ids are surfaced in the inbound DM
    framing. The body travels INLINE (direction='ai_to_ai'), zero re-fetch.

    (Equivalent to `dm_send(..., reply_to=..., thread_id=...)`; this verb exists so
    the contract reads itself — every /api/dm/<verb> mirrors a dm_<verb> tool — and
    so the threading fields are enforced, not optional.)

    Args:
        recipient: Recipient persona name (case/punctuation-tolerant resolution).
        body: Reply body (delivered inline — no re-fetch).
        reply_to: message_id of the DM you are answering (required).
        thread_id: conversation id the reply belongs to (required).
        recipient_session_id: precise session addressing; takes precedence over
                   `recipient` when supplied.

    Returns:
        Success: {"status":"sent","message_id","thread_id","recipient_session",
                  "recipient_session_hash8","recipient_persona","dispatched":True}.
        Recipient-resolution failure: {"status":"error",
                  "reason":"recipient_unresolved","detail":<RecipientResolutionError>}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.

    TWO WIDTHS, TWO NAMES — use the right one for the right job:
      `recipient_session`       FULL session id. Feed this back as
                                `recipient_session_id` for precise addressing on
                                a SUBSEQUENT SEND.
      `recipient_session_hash8` the 8-char form actually persisted, and the form
                                `dm_list` reports as the addressee. Compare
                                against `recipient_session_hash8` on listed DMs.
    They are deliberately NOT the same value; comparing one to the other will
    not match. (`dm_list`'s `session_id` filter accepts either — it normalizes.)
    """
    persona = _commons_persona_fields()
    return _dm_respond_impl(
        recipient            = recipient,
        body                 = body,
        reply_to             = reply_to,
        thread_id            = thread_id,
        recipient_session_id = recipient_session_id,
        session_id           = SESSION_ID,
        sender_persona       = persona[ "persona_name" ],
        sender_icon          = persona[ "persona_icon" ],
        sender_project       = CANONICAL_PROJECT,
        api_base_url         = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key              = _mcp_outbound_api_key(),
        post_fn              = requests.post,
    )


@mcp.tool
def dm_get( message_id: str ) -> dict:
    """
    **[READ]** Fetch a single peer DM by its message id.

    Returns one direction='ai_to_ai' DM (scoped to you). Useful to re-read the
    full body/threading of a DM you only have the id for. 404 if it does not
    exist, is not a DM, or belongs to another user.

    Args:
        message_id: the DM's message_id (a UUID string).

    Returns:
        Success: {"status":"ok","message_id","thread_id","reply_to","sender_id",
                  "sender_persona","sender_icon","body","direction","state",
                  "job_id","created_at"}.
        Not found: {"status":"error","reason":"not_found","detail":...}.
        Bad id: {"status":"error","reason":"bad_request","detail":...}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.
    """
    return _dm_get_impl(
        message_id   = message_id,
        api_base_url = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key      = _mcp_outbound_api_key(),
        get_fn       = requests.get,
    )


@mcp.tool
def dm_list(
    thread_id : Optional[ str ] = None,
    since     : Optional[ str ] = None,
    limit     : int             = 50,
    scope     : str             = "session",
) -> dict:
    """
    **[READ]** List or poll peer DMs addressed to THIS session — or, on request,
    every DM on the account.

    With `thread_id`, returns that conversation oldest-first (read order). Without
    it, returns your DMs newest-first. `since` (an ISO-8601 timestamp) tails only
    messages newer than that instant — the lightweight poll for new replies.
    `limit` is clamped server-side to [1, 200].

    ⚠️ THIS TOOL USED TO SAY "your peer-DM inbox," AND THAT WAS FALSE. The
    underlying store scopes DMs to a SERVICE ACCOUNT, not to a session, and the
    write path currently stamps one account for the whole fleet — so an
    unscoped read returns every session's traffic. Measured 2026-07-21: one
    session's unscoped read returned 50 messages across 7 sender sessions with
    ZERO addressed to it; another returned 200+ across 12 personas. On
    2026-07-16 a careful seat read that output as her own mail and filed a
    false cross-session finding within minutes. The label licensed a claim the
    payload could not support (row 2565956b).

    ⇒ `scope="session"` (the DEFAULT) now asks the server to return only DMs
      ADDRESSED to this session, so the name and the payload finally agree.
    ⇒ `scope="account"` is the deliberate wide read for audit/forensics. It is
      never the silent outcome of a normal call — you have to ask for it.

    🔎 READ THE RESPONSE'S `scope` FIELD, DO NOT ASSUME IT. If this session's id
    cannot be resolved, the server CANNOT narrow the read and returns
    `scope:"account"` — a wide result, honestly labelled. Presence of a DM in an
    account-scoped result says only that it EXISTS, never that it was sent to
    you. Each message carries `recipient_session_hash8` (the addressee) — use
    that field to answer "was this for me?", never mere presence in the list.

    ⚠️ NOTE THE `_hash8` SUFFIX — it is load-bearing. The addressee is persisted
    as the recipient's FIRST 8 CHARACTERS, while `dm_send` returns a key called
    `recipient_session` holding the FULL id. They are deliberately named
    differently because they are different widths; comparing them directly will
    not match. (You may still pass a full id as a filter — the server truncates
    it for you.)

    Args:
        thread_id: a conversation id (thread view) or omit for the inbox view.
        since: ISO-8601 timestamp — return only messages created after it (poll).
        limit: max messages to return (default 50, capped at 200).
        scope: "session" (default — only DMs addressed here) or "account"
            (every DM on the account; an explicit, auditable wide read).
            Anything else is REJECTED (422), never silently narrowed.

    Returns:
        Success: {"status":"ok","thread_id","since","count","scope",
                  "recipient_session_hash8",
                  "messages":[ {... ,"recipient_session_hash8"} ]}.
        Bad `since`: {"status":"error","reason":"bad_request","detail":...}.
        Transport/auth failure: {"status":"error","reason":...,"detail":...}.
    """
    return _dm_list_impl(
        thread_id    = thread_id,
        since        = since,
        limit        = limit,
        api_base_url = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
        api_key      = _mcp_outbound_api_key(),
        get_fn       = requests.get,
        session_id   = SESSION_ID,
        scope        = scope,
    )


# ============================================================================
# Task-Store Tools (Phase 1 — unified work-queue wrappers)
# ============================================================================
#
# Per Lupin src/rnd/v0.1.8/2026.06.11-task-store-phase1/02-mcp-wrapper-spec.md:
# three thin TRANSPORT-only shims over :7999 /api/tasks/* — every structural
# rule (receipts on ->done, typed blocked_by + next_chase_ts on ->blocked,
# terminal lockout, enum membership) lives server-side in
# cosa.rest.task_store_rules; these tools never pre-validate. Identity
# (`created_by`/`actor`) is bridge-stamped, same stamping lane as commons_post
# — a session cannot impersonate. Day-to-day practice: planning-is-prompting
# workflow/task-store-discipline.md.

from lupin_mcp.task_store_tools import task_create_impl, task_transition_impl, task_correlate_impl, task_query_impl, task_reassign_impl, task_amend_impl, task_edit_impl, task_get_impl


def _task_store_identity() -> str:
    """
    Build the bridge-stamped identity for task-store writes.

    Ensures:
        - returns "<persona_name> <8-hex session id>" (e.g. "krishna 38d15e3b")
        - persona resolves via the same `_commons_persona_fields()` bridge
          lookup commons_post uses (falls back to the AC3 default on bridge
          failure — never raises)
    """
    return f"{_commons_persona_fields()[ 'persona_name' ]} {SESSION_ID}"


@mcp.tool
def task_create(
    item_class          : str,
    title               : str,
    project             : str,
    body                : Optional[ str ]  = None,
    owner_persona       : Optional[ str ]  = None,
    accountable_manager : Optional[ str ]  = None,
    gate_class          : str              = "none",
    priority            : str              = "P2",
    urgency             : str              = "normal",
    status              : str              = "queued",
    blocked_by          : Optional[ list ] = None,
    next_chase_ts       : Optional[ str ]  = None,
    source_qid          : Optional[ str ]  = None,
    correlation_key     : Optional[ str ]  = None,
    authority           : str              = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Create a TYPED or CROSS-PERSONA item in the unified task store.

    ┌─ WHICH DOOR? ──────────────────────────────────────────────────────────┐
    │ Do NOT use this for your OWN work stubs. Use the native harness          │
    │ `TaskCreate` instead — it auto-mirrors into this same durable store      │
    │ via the PostToolUse hook. Reach for THIS verb ONLY for the two things    │
    │ the harness physically cannot express: a TYPED item, or one OWNED BY     │
    │ ANOTHER persona.                                                         │
    └─────────────────────────────────────────────────────────────────────────┘

    Two creation methods, ONE destination, different EXPRESSIVENESS
    ---------------------------------------------------------------
    Both the harness `TaskCreate` and this `task_create` ultimately write to
    the SAME store (POST /api/tasks). They are NOT distinguished by durability
    or by "session-local vs cross-session" — the harness items survive /clear
    too. They differ ONLY in what SHAPE of item they can mint:

    - Harness `TaskCreate` (the default, ~90% of items): the PostToolUse mirror
      (task_store_mirror.py:356-362) HARDCODES `item_class="task"`,
      `owner_persona = accountable_manager = <self>`, and reads only
      `metadata.task_store_id`. So the harness can mint EXACTLY ONE shape:
      a generic, SELF-OWNED `task`. That covers your own work stubs.

    - This `task_create` is the ONLY agent-facing path that can mint:
        (a) a CROSS-PERSONA item — `owner_persona` / `accountable_manager`
            set to someone OTHER than yourself (assigning work to a worker);
        (b) a TYPED item — `item_class` in {decision, gate, bug, review_request}
            (e.g. a `decision` with `gate_class="operator"` for the operator queue,
            a durable `bug`, a `review_request`, a `gate`).
      If your item is neither (a) nor (b), you are at the WRONG door — go use
      the harness `TaskCreate`.

    NOT a reason to reach here
    --------------------------
    Do NOT reach for this verb thinking it is how DM-born tasks get created.
    `source_qid` is a provenance FIELD (plumbed through TaskCreateIn) RESERVED
    for a designed-but-NOT-YET-BUILT server-side DM→task auto-create path
    (cold-review C10, still an OPEN design question — no such auto-creator
    exists in src/cosa today). It is NOT what this wrapper is for: this
    wrapper's `source_qid` param only stamps provenance when you are ALREADY
    minting a typed/cross-persona item here for one of the reasons above.

    Forward-note (Rick ruling 2026-06-16)
    -------------------------------------
    This verb is KEPT, not deleted — its purpose is intentionally distinct from
    the harness method. The future route to a SINGLE creation door is to teach
    the mirror to also read `metadata.item_class` / `owner_persona` /
    `gate_class` from harness `TaskCreate`; once the harness can express typed +
    cross-persona items, THIS verb can be retired with zero capability loss.
    Until that lands, deleting it would amputate cross-persona assignment and
    the decision/gate/bug/review_request classes — exactly the items that
    surface decisions to Rick. See planning-is-prompting
    workflow/task-store-discipline.md §3.

    Managers-first write practice (design F4) is enforced socially + by the
    audit trail, not by tool gating.

    Examples:
        # Assign work to ANOTHER persona (cross-persona — harness can't):
        task_create(item_class="task", title="Review the wrapper build",
                    project="lupin", owner_persona="tiffany",
                    accountable_manager="tiberius")

        # A decision for the operator queue (TYPED — harness can't):
        task_create(item_class="decision", title="Deploy window for MCP restart",
                    project="lupin", body="Options: ... Recommendation: ...",
                    gate_class="operator")

        # Your OWN work stub → DON'T use this; use the harness instead:
        #   TaskCreate(subject="Draft the docstring", description="...")

    Args:
        item_class: task | decision | review_request | bug | gate
        title: One-line obligation statement
        project: Owning project (e.g. "lupin")
        body: Optional long-form payload (decision framing lives here)
        owner_persona: Who owes the work
        accountable_manager: Who chases it
        gate_class: none | operator (default "none")
        priority: P0..P3 (default "P2")
        urgency: urgent | normal | low (default "normal") — operator-gate TIME-
            sensitivity (NOT priority/importance); the arbiter routes a gate by it
            (urgent→interrupt, normal→digest, low→queue)
        status: queued (default) | blocked. Pass "blocked" to MINT an already-
            blocked row in ONE call (Rick 2026-07-20). MANAGER-ONLY server-side —
            a non-manager blocked mint is a 403. Otherwise whitelisted to
            queued|blocked (done/dropped/parked/claimed/in_progress/review are NOT
            mintable — transition after create).
        blocked_by: typed refs [{kind: item|persona|user, id}] — REQUIRED (>=1)
            for a blocked mint; ignored for queued
        next_chase_ts: ISO-8601 chase time — REQUIRED for a blocked mint whose
            blocked_by names a {kind:persona} ref (I3 — a peer is chaseable)
        source_qid: Originating commons question_id, when DM-born
        correlation_key: Upsert key for hook-mirrored items
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        The serialized item dict (server 201 body) verbatim, or an error dict:
        {"status": "error", "reason": "server_unreachable"|"missing_auth_header", ...}
        or {"status": "error", "http_status": 422, "errors": [...server's words...]}.

    `created_by` is NOT a parameter — it is stamped from the session bridge
    ("<persona> <session id>"), the same identity lane as commons_post.
    """
    return task_create_impl(
        api_base_url        = _get_server_url(),
        api_key             = _mcp_outbound_api_key(),
        created_by          = _task_store_identity(),
        item_class          = item_class,
        title               = title,
        project             = project,
        body                = body,
        owner_persona       = owner_persona,
        accountable_manager = accountable_manager,
        gate_class          = gate_class,
        priority            = priority,
        urgency             = urgency,
        status              = status,
        blocked_by          = blocked_by,
        next_chase_ts       = next_chase_ts,
        source_qid          = source_qid,
        correlation_key     = correlation_key,
        authority           = authority,
    )


@mcp.tool
def task_transition(
    task_id       : str,
    to_status     : str,
    receipt_refs  : Optional[ dict ] = None,
    next_chase_ts : Optional[ str ]  = None,
    blocked_by    : Optional[ list ] = None,
    reason        : Optional[ str ]  = None,
    authority     : str              = "standing",
    park_reason   : Optional[ str ]  = None,
) -> dict:
    """
    **[SELF-DISCLOSURE]** Apply one state change to a task-store item.

    The receipts discipline is enforced SERVER-side and surfaces verbatim:
    `->done` REQUIRES receipt_refs (key-whitelisted: commit/qid/test_run/
    doc_path/log_line — if you can't cite a receipt, the work isn't done);
    `->blocked` REQUIRES BOTH >=1 typed blocked_by ref ({kind: item|persona|user,
    id}) AND next_chase_ts; done/dropped are terminal. This tool does NOT
    pre-check any of that — a 422 carries the server's errors unedited.

    `->parked` means A HUMAN RULED THIS NOT-NOW: approved, not abandoned, and
    blocked on NOTHING. It REQUIRES BOTH `park_reason` (non-blank) AND
    `next_chase_ts`, and is legal ONLY from queued / in_progress.
      · `park_reason` MUST QUOTE the row's own decisive sentence, not
        paraphrase it — the quote is what lets the next reader REFUTE the park
        row-by-row instead of re-deriving the whole board.
      · The chase IS the un-park. Expiry is computed at READ time: once
        next_chase_ts passes, the row REJOINS the owed count automatically —
        no daemon, no sweeper, no human action. Parking buys BOUNDED,
        SELF-EXPIRING silence, never an exit.
      · An INDEFINITE hold is NOT a park — that is `dropped` with a reason,
        because dropping is VISIBLE.
      · Leaving `parked` CLEARS park_reason: a quote must never outlive the
        park it justified.

    Examples:
        # Close with receipts:
        task_transition(task_id="<uuid>", to_status="done",
                        receipt_refs={"commit": "f4e0370", "test_run": "ts-b51e63c9"})

        # Block with a typed wait + chase time:
        task_transition(task_id="<uuid>", to_status="blocked",
                        blocked_by=[{"kind": "persona", "id": "tiffany"}],
                        next_chase_ts="2026-06-13T09:00:00-04:00")

        # Park a deliberately-held row, quoting its OWN decisive sentence:
        task_transition(task_id="<uuid>", to_status="parked",
                        park_reason="NOT TO BE WORKED per Rick's direct instruction",
                        next_chase_ts="2026-07-22T09:00:00-04:00")

    Args:
        task_id: The item's UUID
        to_status: Target status (e.g. in_progress | blocked | done | dropped)
        receipt_refs: Receipt dict — REQUIRED server-side for ->done
        next_chase_ts: ISO-8601 chase time — REQUIRED server-side for ->blocked
        blocked_by: Typed refs [{kind, id}] — REQUIRED server-side for ->blocked
        park_reason: The row's OWN decisive sentence, quoted (<=4000) —
            REQUIRED server-side (non-blank) for ->parked; cleared on unpark
        reason: Free-text rationale (<=4000) — REQUIRED server-side (non-empty)
            for ->dropped once the Phase-2 write-path lands (C12 pull-forward);
            give one on every ->dropped regardless (task-store-discipline.md §4)
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict — a 422
        carries the server's detail.errors list VERBATIM under "errors"; a 404
        carries "task {id} not found" verbatim under "detail".

    `actor` is NOT a parameter — bridge-stamped like task_create's created_by.
    """
    return task_transition_impl(
        api_base_url  = _get_server_url(),
        api_key       = _mcp_outbound_api_key(),
        actor         = _task_store_identity(),
        task_id       = task_id,
        to_status     = to_status,
        receipt_refs  = receipt_refs,
        next_chase_ts = next_chase_ts,
        blocked_by    = blocked_by,
        reason        = reason,
        authority     = authority,
        park_reason   = park_reason,
    )


@mcp.tool
def task_query(
    owner_persona       : Optional[ str ] = None,
    status              : Optional[ str ] = None,
    gate_class          : Optional[ str ] = None,
    urgency             : Optional[ str ] = None,
    accountable_manager : Optional[ str ] = None,
    project             : Optional[ str ] = None,
    item_class          : Optional[ str ] = None,
    correlation_key     : Optional[ str ] = None,
    limit               : Optional[ int ] = None,
    offset              : Optional[ int ] = None,
    terse               : bool            = False,
    include_terminal    : bool            = False,
    unscoped_audit      : bool            = False,
    include_parked      : bool            = False,
) -> dict:
    """
    **[READ — always allowed, no user permission needed]** Query the task store.

    The deterministic owed-work query (design R4): exact-match filters, AND
    semantics, newest first. Junk enum filter values are rejected by the
    server (422), never silently empty.

    TOKEN-EFFICIENCY (goal #1): pass terse=True for any "see my list" / board
    glance. It returns the at-a-glance projection (id / title / status /
    blocked_by / next_chase_ts / priority / park_reason_stale — `body` and the
    other full-row fields
    dropped), a fraction of the full-row token weight. Reach for the full shape
    (terse=False) ONLY when you actually need a row's body/audit context.

    UNSCOPED-QUERY GUARD (design 2026.07.07): a BARE `task_query()` with no
    narrowing filter is REJECTED with an educational error-dict once the store
    holds more than the threshold of non-terminal rows — the DB only grows;
    nobody pulls the whole board by accident. The two fixes the error names:
    (1) add a narrowing filter (owner_persona / status / item_class / project /
    gate_class / accountable_manager / correlation_key), or (2) pass
    `unscoped_audit=True` for a DELIBERATE full-store audit. Terminal (done/
    dropped) rows are excluded by default; pass `include_terminal=True` to
    include them on an un-status'd query.

    PARKED ROWS (2026-07-19): a `parked` row is one a human deliberately ruled
    not-now, carrying a `park_reason` quoting the row's own decisive sentence.
    Park-ACTIVE rows are HIDDEN from this query by default, so `queued` now
    means "actually workable now" and the burn-down number stops being fiction.
    Parking is BOUNDED and SELF-EXPIRING, never an exit: a parked row whose
    `next_chase_ts` has PASSED is no longer parked — it rejoins the owed count
    automatically and stays VISIBLE here. Nothing sweeps it; expiry is computed
    at READ time. An INDEFINITE hold is not parked, it is `dropped` with a
    reason (dropping is visible). Pass `include_parked=True` (or
    `status="parked"`) to audit what is currently parked and why.

    STALE PARK REASONS (2026-07-19): every row carries `park_reason_stale`
    (bool) — in the TERSE projection too, not only the full row. A
    `park_reason` is a FROZEN QUOTE of the row's decisive sentence, captured at
    park time. Change the row's BODY afterward and that quote stays syntactically
    valid while it stops being true, and nothing goes red. `park_reason_stale=True`
    IS that red: the row's body changed AFTER its quote was frozen, so the
    quote is no longer known to describe the row — read the row itself, not its
    park_reason, and re-park to re-freeze the quote.

    ⚠️ FIXED 2026-07-26 (bug 54924128) — IF YOU REMEMBER THIS FLAG BEING NOISE,
    THAT WAS THE BUG. It used to fire on ANY write that bumped `updated_ts`, so a
    **priority-only edit during a routine board recut defamed a correct quote**.
    When it was found, every parked row in the store carried the flag and every
    one was wrong. It now reads `body_changed_ts`, which moves only when the body
    actually changes. ⇒ Re-check any `park_reason_stale: true` you saw before that
    date rather than trusting it.

    ⚠️ AND `False` DOES NOT MEAN "STILL TRUE" (row aa543525 §2). The flag answers
    "has the BODY changed since the quote was frozen?" — nothing more. A park
    reason whose basis lived OUTSIDE the row dies without touching the row, so it
    reads FRESH forever. MEASURED 2026-07-25: four rows read `false` while each
    quoted a fleet-wide stand-down that had already evaporated. ⇒ Treat `false` as
    "no body change," NEVER as an endorsement — and note the flag is silent in
    exactly the case you most want it to speak. The real property is CONTENT
    CONTRADICTION, which no clock can answer; **the chase is the backstop, because
    a park is bounded and self-expiring.**

    ADVISORY ONLY. Staleness changes NO owed-ness, unparks nothing, blocks
    nothing. It marks a quote untrustworthy and stops there — deciding what to
    do about it is a human's call, not this flag's.

    It under-reports by design, and MORE SO right after the fix: a row parked
    before capture-time shipped has no capture time and reports False, as does any
    row never parked — and since the fix ships **no backfill**, every row's
    `body_changed_ts` starts NULL, which also reports False. So the flag is quiet
    until each row's body next changes. `True` is strong evidence; `False` is
    merely the absence of evidence.

    Examples:
        # My owed work (terse list) — the everyday scoped query:
        task_query(owner_persona="sam", status="in_progress", terse=True)

        # Operator queue, full rows (need the body):
        task_query(gate_class="operator")

        # Deliberate full-store audit (past the guard, incl. terminal rows):
        task_query(unscoped_audit=True, include_terminal=True, terse=True)

        # What is currently parked, and why (the audit surface):
        task_query(status="parked", terse=True)

    Args:
        owner_persona: Filter by who owes the work
        status: Filter by status (queued | in_progress | blocked | done | dropped)
        gate_class: Filter by gate (none | operator)
        urgency: Filter by operator-gate urgency tier (urgent | normal | low)
        accountable_manager: Filter by chasing manager
        project: Filter by owning project
        item_class: Filter by class (task | decision | review_request | bug | gate)
        correlation_key: Exact-match filter on the hook-upsert correlation key
            (Phase-2 contract §1.11(C); pre-Phase-2 server ignores it)
        limit: Max rows (server default 100, cap 500)
        offset: Pagination offset
        terse: True → the at-a-glance projection (§G token win); False (default)
            → the full wire shape including body
        include_terminal: True → include done/dropped rows on an un-status'd
            query (default False excludes them)
        unscoped_audit: True → the deliberate-full-sweep escape past the
            unscoped-size guard (default False → a bare over-threshold pull is
            rejected as an error-dict)
        include_parked: True → also return park-ACTIVE rows (default False hides
            them). EXPIRED parked rows are returned either way — they have
            rejoined the owed count and hiding them would make a row that pokes
            you invisible on the board.

    Returns:
        { tasks, count, total, has_more, truncated, warnings } verbatim (terse
        rows when terse=True), or an error dict — an unscoped over-threshold pull
        without unscoped_audit surfaces { status: "error", http_status: 400,
        detail: <the two fixes> }.

        ⚠️ READ `total`, NOT `count`. `count` is the length of THIS PAGE and
        saturates at `limit` (default 100). It was being read as the size of the
        result and never was: measured 2026-07-21, a properly-SCOPED query
        reported count:100 while offset=100 returned 100 more rows. `total` is the
        true count of rows matching your filters, page-independent. `has_more`
        (= offset + count < total) is the one field to branch on before concluding
        you have seen everything.

        `truncated` is True when a CHARACTER budget — not the row limit — stopped
        serialization early, because a row cap is not a size cap: the same 100-row
        page measures ~21k chars terse and ~424k full. `warnings` carries those
        notices to YOU rather than to the server's stdout, which is where they
        used to go — an audience that is not the one paying the token weight.
        Both truncation and page-saturation are announced; neither is ever silent.
    """
    return task_query_impl(
        api_base_url        = _get_server_url(),
        api_key             = _mcp_outbound_api_key(),
        owner_persona       = owner_persona,
        status              = status,
        gate_class          = gate_class,
        urgency             = urgency,
        accountable_manager = accountable_manager,
        project             = project,
        item_class          = item_class,
        correlation_key     = correlation_key,
        limit               = limit,
        offset              = offset,
        terse               = terse,
        include_terminal    = include_terminal,
        unscoped_audit      = unscoped_audit,
        include_parked      = include_parked,
    )


@mcp.tool
def task_get( task_id: str ) -> dict:
    """
    **[READ — always allowed, no user permission needed]** Fetch ONE store row
    by its UUID.

    THE FAILURE THIS PREVENTS: a filtered query's empty result is NOT evidence a
    row is absent — use this to ask about a row DIRECTLY. `task_query` can only
    ask a filter and scan a page; a row sitting at offset=15 of a limit=15 page
    reads as gone, and an absence in a filtered page becomes a false fact about
    the world. This asks about the specific row instead of inferring it from a
    page's silence.

    Returns the FULL item including `body` (not the terse projection) — you
    asked for the row, you get the row. An absent id is a 404 → error dict
    carrying "task {id} not found" verbatim, NEVER an empty success or None: a
    missing row rendered as a silent nothing is the exact confusion this verb
    exists to kill.

    Example:
        # Open one row by id (e.g. from a terse list's `id` field):
        task_get(task_id="4288dd53-6779-460a-88bd-a7365fb734b2")

    Args:
        task_id: The item's UUID string. A malformed id is the server's reject
            to surface (422), never pre-checked here.

    Returns:
        The full serialized item (200 body) verbatim on success, or an error
        dict — a 404 carries "task {id} not found" verbatim under "detail"; a
        malformed UUID carries the server's 422 detail verbatim; auth/transport
        failures carry the shared missing_auth_header / server_unreachable
        contract. NEVER an empty success, NEVER None.
    """
    return task_get_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        task_id      = task_id,
    )


@mcp.tool
def task_correlate(
    task_id         : str,
    correlation_key : str,
    authority       : str = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Re-stamp a task-store item's correlation_key.

    Cross-session respawn adoption (Phase-2 design C5/ruling #4): when a
    successor session inherits an item, ADOPT it by re-keying it onto your own
    harness id instead of forking a duplicate. The server appends an audited
    `re-correlated` event (R3) and REJECTS terminal items (no re-keying closed
    history) — this tool does NOT pre-check that; a 422 carries the server's
    words verbatim.

    Example:
        # Adopt the inherited item onto this session's harness id:
        task_correlate(task_id="<uuid>",
                       correlation_key="cc-task:<my-stable-sid>:<harness-id>")

    Args:
        task_id: The item's UUID
        correlation_key: The new key to stamp (server validates 1..255 chars)
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict — a 404
        carries "task {id} not found" verbatim under "detail"; a 422 (terminal
        item / bad authority) carries the server's detail verbatim.

    `actor` is NOT a parameter — bridge-stamped like task_transition's actor.
    """
    return task_correlate_impl(
        api_base_url    = _get_server_url(),
        api_key         = _mcp_outbound_api_key(),
        actor           = _task_store_identity(),
        task_id         = task_id,
        correlation_key = correlation_key,
        authority       = authority,
    )


@mcp.tool
def task_reassign(
    task_id           : str,
    new_owner_persona : str,
    reason            : str,
    new_manager       : Optional[ str ] = None,
    authority         : str             = "manager_relay",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Reassign a task-store item to a new owner persona.

    The manager's handoff primitive (design §4.2): pull a worker off a queue and
    hand their in-flight work to another persona. Changes OWNERSHIP ONLY — it can
    NEVER change `status` (the store walls PATCH off from the state machine,
    design D4). If the handoff should also re-queue the item, that is a SEPARATE
    `task_transition`. The server is the single normalization + audit seam: it
    canonicalizes the new owner to the owed-query key (so the new owner's
    `task_query(owner_persona=…)` finds the row — the 2026-06-18 false-idle
    guard) and appends one `patched` event carrying your `reason`.

    A non-empty `reason` is REQUIRED here at the verb (the manager's "why" for the
    handoff) — a blank reason is rejected before any server round-trip.

    Examples:
        # Hand Tiffany's in-flight item to Marcus, manager unchanged:
        task_reassign(task_id="<uuid>", new_owner_persona="marcus",
                      reason="Tiffany pulled onto the P0 arbiter fix")

        # Reassign AND move it under a new chasing manager:
        task_reassign(task_id="<uuid>", new_owner_persona="marcus",
                      new_manager="tiberius",
                      reason="lane handoff — Tiberius now chasing")

    Args:
        task_id: The item's UUID
        new_owner_persona: The handoff target (server normalizes to canonical key)
        reason: Non-empty justification for the handoff (stamps the audit event)
        new_manager: Optional new accountable_manager; when omitted the chasing
            manager is left UNCHANGED (design Q6)
        authority: standing | user_direct | manager_relay (default "manager_relay")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict:
        {"status": "error", "reason": "empty_reason"} when `reason` is blank
        (verb-enforced, no round-trip); a 404 carries "task {id} not found"
        verbatim; a 422 (terminal item / bad authority) carries the server's
        detail verbatim.

    `actor` is NOT a parameter — bridge-stamped like task_transition's actor
    (anti-impersonation; the manager-relay handoff is auditable to the real
    session that issued it).
    """
    if not ( reason and reason.strip() ):
        return { "status": "error", "reason": "empty_reason",
                 "detail": "task_reassign requires a non-empty reason (the manager's justification for the handoff)" }
    return task_reassign_impl(
        api_base_url      = _get_server_url(),
        api_key           = _mcp_outbound_api_key(),
        actor             = _task_store_identity(),
        task_id           = task_id,
        new_owner_persona = new_owner_persona,
        reason            = reason,
        new_manager       = new_manager,
        authority         = authority,
    )


@mcp.tool
def task_amend(
    task_id   : str,
    note      : str,
    reason    : Optional[ str ] = None,
    authority : str             = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Append an amendment to a task-store item's body.

    The durable-record seam for a LIVE item whose scope is legitimately reframed
    mid-flight (Krishna's 2026-07-02 friction): instead of leaving the current
    spec in scratchpad checklists / code comments / transition reasons — where a
    successor rehydrating from the store never sees it — append it to the item's
    DURABLE body. APPEND-ONLY: the original body is preserved verbatim and your
    note lands below a persona-stamped + UTC-timestamped divider, so the full
    amendment history reads inline. This is NOT a destructive edit — reach for it
    when you would otherwise rewrite a body but must keep the prior spec.

    A TERMINAL item is ALLOWED (Rick's ruling 2026-08-02): amend is the ONE write
    verb the store accepts on a done/dropped row — the durable home for a gate
    verdict written AFTER a worker self-closes their own row. On a terminal row
    the block is marked a post-terminal addendum (`[post-terminal addendum · … ·
    added after close, not a reopening]`) and the audit event is stamped
    'amended_post_terminal', so a reader tells at a glance it arrived after the
    close; status is NOT moved (a closed row stays closed — transition / edit /
    correlate remain refused on it). The server still REJECTS a blank note and a
    bad authority — this tool does NOT pre-check those; a 422 carries the server's
    words verbatim.

    Example:
        # Record a manager-ruled scope reframe on a live item:
        task_amend(task_id="<uuid>",
                   note="SCOPE REFRAME (Rick 2026-07-02): scheduler-port -> "
                        "request-initiation subscriber. Prior spec below stands "
                        "as history.",
                   reason="4f14d38f manager ruling on cited evidence")

    Args:
        task_id: The item's UUID
        note: The amendment text to append (server validates 1..4000 + non-blank)
        reason: Optional justification stamping the audit event; when omitted the
            event records an auto-marker naming the appended length. The event
            transition is 'amended' on a live row, 'amended_post_terminal' on a
            terminal one
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict — a 404
        carries "task {id} not found" verbatim under "detail"; a 422 (blank note /
        bad authority) carries the server's detail verbatim.

    `actor` is NOT a parameter — bridge-stamped like task_transition's actor
    (anti-impersonation; the amendment is auditable to the real session).
    """
    return task_amend_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        task_id      = task_id,
        note         = note,
        reason       = reason,
        authority    = authority,
    )


@mcp.tool
def task_edit(
    task_id   : str,
    updates   : dict,
    reason    : Optional[ str ] = None,
    authority : str             = "standing",
) -> dict:
    """
    **[SELF-DISCLOSURE]** Edit one or more of the 5 FREE-EDIT fields of a
    task-store item.

    The last-mile "change field X to value Y" seam (design §4) — most concretely,
    DEMOTE a mis-inflated `priority`. A thin MCP wrapper over `PATCH /api/tasks/
    {id}`: it OVERWRITES the named fields atomically (one txn, one `patched` audit
    event). Value validation stays server-side (Pydantic + `validate_patch`).

    EDITABLE (5 fields) — pass any subset in `updates`:
        title · body · priority · gate_class · urgency

    REFUSED at the MCP layer — OWNER fields `owner_persona` · `accountable_manager`
    → use `task_reassign` (the single owner-change path, with a mandatory reason).
    Editing owner via a bare `task_edit` would be a reason-free reassignment
    backdoor; a raw PATCH would accept them, so this refusal is MCP-side.

    REFUSED by the server (`extra="forbid"` → 422) — invariant-bearing fields; use
    `task_transition`, which moves the coupled fields together:
        status · blocked_by · next_chase_ts · park_reason ·
        park_reason_captured_at · receipt_refs · correlation_key

    A bad enum (`priority` not P0–P3, `gate_class` not none/manager/operator,
    `urgency` not urgent/normal/low) or empty `title` → 422 from the server, no
    row mutation. Terminal (done/dropped) items are rejected server-side.

    Examples:
        # Demote a mis-inflated priority (the C7 P1-inflation fix):
        task_edit(task_id="<uuid>", updates={"priority": "P3"},
                  reason="over-inflated at mint; not user-blocking")

        # Multi-field atomic edit in one txn/event:
        task_edit(task_id="<uuid>",
                  updates={"title": "Retitled", "urgency": "low"})

    Args:
        task_id: The item's UUID
        updates: Dict of {field: value} to overwrite — non-empty; owner keys are
            refused with a pointer to task_reassign, invariant keys 422 server-side
        reason: Optional justification stamping the 'patched' audit event; when
            omitted the event records the field delta
        authority: standing | user_direct | manager_relay (default "standing")

    Returns:
        { item, event } (server 200 body) verbatim, or an error dict:
        {"reason": "empty_updates"} when `updates` is empty/not-a-dict (verb-
        enforced, no round-trip); {"reason": "owner_field_refused"} → task_reassign;
        a 404 carries "task {id} not found" verbatim; a 422 (invariant field / bad
        enum / empty title / terminal item) carries the server's detail verbatim.

    `actor` is NOT a parameter — bridge-stamped like task_transition's actor
    (anti-impersonation; stamped LAST, so an `updates` "actor" key cannot shadow it).
    """
    if not isinstance( updates, dict ) or not updates:
        return { "status": "error", "reason": "empty_updates",
                 "detail": "task_edit requires a non-empty `updates` dict of {field: value} (the fields to overwrite)" }
    return task_edit_impl(
        api_base_url = _get_server_url(),
        api_key      = _mcp_outbound_api_key(),
        actor        = _task_store_identity(),
        task_id      = task_id,
        updates      = updates,
        reason       = reason,
        authority    = authority,
    )


if __name__ == "__main__":
    # THE POSITIVE ASSIGNMENT — the only place this is set. It must come BEFORE
    # mcp.run() so a resolution failure during startup still hard-exits the server
    # exactly as it always has. See the flag's definition for why this is not an
    # environment check, and for what a future console_scripts entry point owes.
    _IS_MCP_SERVER = True
    _maybe_start_commons_archival_daemon()
    mcp.run()
